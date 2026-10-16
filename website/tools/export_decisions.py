"""Export a small, verified, read-only research demo from the development archive.

Usage: python tools/export_decisions.py /path/to/review-bundle
Requires pandas and pyarrow. Never reads the protected 2025 partition.
"""

from __future__ import annotations

import ast
import hashlib
import json
import math
import sys
from pathlib import Path

import pandas as pd

SITE = Path(__file__).resolve().parents[1]


def verified_file(folder: Path, filename: str, record: dict) -> Path:
    path = folder / filename
    blob = path.read_bytes()
    assert len(blob) == record["size_bytes"], f"size mismatch: {path}"
    assert hashlib.sha256(blob).hexdigest() == record["sha256"], f"hash mismatch: {path}"
    return path


def driver_names(source: Path) -> dict[str, str]:
    tree = ast.parse(source.read_text())
    for item in tree.body:
        if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name) and item.target.id == "_DRIVER_NAMES":
            return ast.literal_eval(item.value)
    raise ValueError("driver name mapping missing from verified API source")


def number(value: object) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("non-finite value in verified report")
    return result


def optional_number(value: object) -> float | None:
    if pd.isna(value):
        return None
    return number(value)


def main(bundle: Path) -> None:
    root = bundle / "artifacts" / "optimizer_evaluation" / "format_version=1.0" / "run_id=phase-8-final-audit"
    manifest = json.loads((root / "manifest.json").read_text())
    assert manifest["run_id"] == "phase-8-final-audit"
    paths = {name: verified_file(root, name, record) for name, record in manifest["artifacts"].items()}
    provenance = json.loads(paths["provenance.json"].read_text())
    assert provenance["protected_evaluation_rows"] == 0
    assert provenance["model_artifact_id"] == "phase-6-final-audit-lap-time"
    model_provenance = json.loads((bundle / "artifacts" / "models" / "contract_version=1.2" / "artifact_id=phase-6-final-audit-lap-time" / "provenance.json").read_text())
    assert model_provenance["training_seasons"] == [2022, 2023, 2024]
    names = driver_names(bundle / "backend" / "app" / "api" / "historical.py")

    decisions = pd.read_parquet(paths["decisions.parquet"])
    cases = pd.read_parquet(paths["cases.parquet"])
    nominal = cases.loc[(cases.tyre_age_scenario == "NOMINAL") & (cases.pit_loss_scenario == "NOMINAL")].set_index("decision_id", verify_integrity=True)
    assert len(decisions) == 124 and len(nominal) == len(decisions)
    assert set(nominal.pit_loss_source) == {"EXPLICIT_ASSUMPTION"}
    context_rows: dict[str, pd.Series] = {}
    for season, session_id in decisions[["season", "session_id"]].drop_duplicates().itertuples(index=False, name=None):
        assert season in (2022, 2023, 2024) and session_id.startswith(f"{season}-")
        round_code = session_id.split("-")[1]
        folder = bundle / "data" / "datasets" / "f1_strategy" / "dataset_contract_version=1.0" / f"season={season}" / f"round={round_code}" / "session=R"
        session_manifest = json.loads((folder / "manifest.json").read_text())
        assert session_manifest["session"]["identifier"] == session_id
        assert session_manifest["validation"]["protected_evaluation_season_accessed"] is False
        assert session_manifest["validation"]["status"] == "passed"
        table_path = verified_file(folder, "decision_rows.parquet", session_manifest["files"]["decision_rows.parquet"])
        subset = pd.read_parquet(table_path)
        for row in subset.itertuples(index=False):
            context_rows[row.decision_id] = row

    output = []
    for row in decisions.itertuples(index=False):
        assert row.season in (2022, 2023, 2024) and row.driver in names
        assert row.decision_id in nominal.index
        recorded = context_rows[f"{row.session_id}-{row.driver}-{row.decision_lap:03d}"]
        assert recorded.is_decision_eligible and recorded.dry_at_decision and recorded.previous_lap_green
        assert recorded.team == row.team and recorded.current_compound == row.current_compound
        assumption = nominal.loc[row.decision_id]
        assert math.isclose(number(assumption.pit_now_time_seconds), number(row.nominal_pit_now_time_seconds), abs_tol=1e-6)
        assert math.isclose(number(assumption.stay_out_time_seconds), number(row.nominal_stay_out_time_seconds), abs_tol=1e-6)
        assert math.isclose(number(row.nominal_stay_out_time_seconds) - number(row.nominal_pit_now_time_seconds), number(row.nominal_pit_now_advantage_seconds), abs_tol=1e-6)
        output.append({
            "id": row.decision_id,
            "season": int(row.season),
            "race_id": row.session_id,
            "race": row.event_name,
            "driver": row.driver,
            "name": names[row.driver],
            "team": row.team,
            "lap": int(row.decision_lap),
            "total_laps": int(row.total_laps),
            "remaining_laps": int(row.remaining_laps),
            "current_tyre": row.current_compound,
            "target_tyre": row.target_compound,
            "tyre_age": int(row.current_tyre_age_laps),
            "pit_now_seconds": number(row.nominal_pit_now_time_seconds),
            "wait_seconds": number(row.nominal_stay_out_time_seconds),
            "advantage_seconds": number(row.nominal_pit_now_advantage_seconds),
            "point_favors": row.nominal_recommendation,
            "margin_per_path_seconds": number(row.action_time_margin_seconds),
            "band_low_seconds": number(row.conservative_min_advantage_seconds),
            "band_high_seconds": number(row.conservative_max_advantage_seconds),
            "verdict": row.stable_recommendation,
            "pit_loss_assumption_seconds": number(assumption.pit_loss_seconds),
            "position": int(recorded.previous_position),
            "last_lap_seconds": optional_number(recorded.previous_lap_time_seconds),
            "recent_median_seconds": optional_number(recorded.rolling_lap_time_median_3),
            "track_celsius": optional_number(recorded.track_temperature_celsius),
            "air_celsius": optional_number(recorded.air_temperature_celsius),
            "rainfall": bool(recorded.rainfall),
            "previous_track_status": str(recorded.previous_track_status),
        })
    output.sort(key=lambda item: (item["season"], item["race_id"], item["driver"], item["lap"]))
    pairs: dict[tuple[str, str], list[dict]] = {}
    for item in output:
        pairs.setdefault((item["race_id"], item["driver"]), []).append(item)
    assert len(pairs) == 62 and all(len(pair) == 2 and pair[1]["lap"] == pair[0]["lap"] + 1 for pair in pairs.values())
    assert {item["verdict"] for item in output} == {"NO_CLEAR_ADVANTAGE"}
    assert {item["pit_loss_assumption_seconds"] for item in output} == {20.0}
    result = {
        "source": "Verified Phase 8 development optimizer report; precomputed, read-only",
        "model_id": provenance["model_artifact_id"],
        "training_seasons": model_provenance["training_seasons"],
        "source_sha256": manifest["artifacts"]["decisions.parquet"]["sha256"],
        "count": len(output),
        "paired_checkpoints": len(pairs),
        "decisions": output,
    }
    target = SITE / "dist" / "decisions.json"
    target.write_text(json.dumps(result, separators=(",", ":"), ensure_ascii=False) + "\n")
    print(f"Exported {len(output)} decisions across {len(pairs)} one-lap pairs to {target}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python tools/export_decisions.py /path/to/review-bundle")
    main(Path(sys.argv[1]).resolve())
