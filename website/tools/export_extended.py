"""Compute additional dry pit windows from the frozen development model.

Usage: python tools/export_extended.py /path/to/review-bundle [workers]
Run with the backend's locked Python environment. These exploratory point
estimates do not replace the 124 immutable Phase 8 audited decisions.
"""

from __future__ import annotations

import json
import math
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

from export_decisions import SITE, driver_names, optional_number, verified_file

MODEL = None


def initialize(bundle: str) -> None:
    global MODEL
    from app.ml import ModelArtifactPaths
    from app.simulation import Phase6ModelAdapter

    root = Path(bundle)
    MODEL = Phase6ModelAdapter.from_paths(
        ModelArtifactPaths(root / "artifacts", "phase-6-final-audit-lap-time")
    )


def export_session(bundle_str: str, folder_str: str, names: dict, audited: list[str], margin: float) -> tuple[str, list[dict]]:
    from app.optimizer.audit import _build_candidate, _pit_loss_registry, _rank_pit_pairs
    from app.optimizer.comparison import compare_pit_decision
    from app.optimizer.contracts import OptimizerContractError, PitDecisionAction
    from app.pipeline import SessionKey
    from app.simulation import SimulationContractError

    assert MODEL is not None
    bundle = Path(bundle_str)
    folder = Path(folder_str)
    manifest = json.loads((folder / "manifest.json").read_text())
    session = manifest["session"]
    season = session["season"]
    race_id = session["identifier"]
    assert season in (2022, 2023, 2024) and session["session_type"] == "R"
    assert manifest["validation"]["status"] == "passed"
    laps = pd.read_parquet(verified_file(folder, "laps.parquet", manifest["files"]["laps.parquet"]))
    dataset = bundle / "data" / "datasets" / "f1_strategy" / "dataset_contract_version=1.0" / f"season={season}" / f"round={session['round_number']:02d}" / "session=R"
    dm = json.loads((dataset / "manifest.json").read_text())
    assert dm["session"]["identifier"] == race_id and dm["validation"]["status"] == "passed"
    assert dm["validation"]["protected_evaluation_season_accessed"] is False
    decisions = pd.read_parquet(verified_file(dataset, "decision_rows.parquet", dm["files"]["decision_rows.parquet"]))
    registry = _pit_loss_registry(pd.DataFrame({"event_name": [session["event_name"]]}))
    selected = set()
    output = []
    audited_set = set(audited)
    for stay, pit, pit_lap, total, tyre in _rank_pit_pairs(decision_rows=decisions, processed_laps=laps):
        driver = str(pit["driver"])
        if driver in selected or driver in audited_set:
            continue
        try:
            candidates = [
                _build_candidate(
                    session_key=SessionKey(season, session["round_number"], "R"),
                    row=row, total_laps=total, pit_lap=pit_lap,
                    target_compound=tyre, observed_action=action,
                    decision_rows=decisions, processed_laps=laps,
                    pit_loss_registry=registry,
                )
                for row, action in ((stay, PitDecisionAction.STAY_OUT), (pit, PitDecisionAction.PIT_NOW))
            ]
        except (OptimizerContractError, SimulationContractError):
            continue
        pair = []
        for candidate, row in zip(candidates, (stay, pit), strict=True):
            comparison = compare_pit_decision(
                candidate.request, context=candidate.context, adapter=MODEL
            )
            state = candidate.request.state
            advantage = comparison.pit_now_advantage_seconds
            result = {
                "id": f"{season}:{race_id}:{driver}:{state.current_lap}:{tyre.value}",
                "season": season, "race_id": race_id, "race": session["event_name"],
                "driver": driver, "name": names[driver], "team": state.team,
                "lap": state.current_lap, "total_laps": total,
                "remaining_laps": candidate.request.remaining_laps,
                "current_tyre": state.current_compound.value, "target_tyre": tyre.value,
                "tyre_age": state.tyre_age_laps,
                "pit_now_seconds": comparison.pit_now.expected_remaining_time_seconds,
                "wait_seconds": comparison.stay_out.expected_remaining_time_seconds,
                "advantage_seconds": advantage,
                "point_favors": comparison.recommendation.value,
                "margin_per_path_seconds": margin,
                "band_low_seconds": advantage - 2 * margin,
                "band_high_seconds": advantage + 2 * margin,
                "verdict": "UNREVIEWED",
                "pit_loss_assumption_seconds": candidate.request.pit_loss.seconds,
                "position": state.previous_position,
                "last_lap_seconds": optional_number(row["previous_lap_time_seconds"]),
                "track_celsius": optional_number(row["track_temperature_celsius"]),
                "source_tier": "EXPLORATORY",
            }
            assert math.isclose(result["wait_seconds"] - result["pit_now_seconds"], advantage, abs_tol=1e-6)
            pair.append(result)
        assert pair[1]["lap"] == pair[0]["lap"] + 1
        output.extend(pair)
        selected.add(driver)
    return race_id, output


def main(bundle: Path, workers: int) -> None:
    assert bundle.is_dir()
    if (bundle / "data" / "datasets" / "f1_strategy" / "dataset_contract_version=1.0" / "season=2025").exists():
        raise ValueError("protected 2025 partition must stay sealed")
    from app.pipeline.serialization import sha256_file
    from app.ml import ModelArtifactPaths
    from app.simulation import Phase6ModelAdapter

    model_path = ModelArtifactPaths(bundle / "artifacts", "phase-6-final-audit-lap-time")
    adapter = Phase6ModelAdapter.from_paths(model_path)
    dataset_catalog = bundle / "data" / "datasets" / "f1_strategy" / "dataset_contract_version=1.0" / "catalog.parquet"
    assert adapter.artifact.provenance.dataset_build_identifier == sha256_file(dataset_catalog)
    source = json.loads((SITE / "dist" / "decisions.json").read_text())
    assert source["count"] == 124 and source["paired_checkpoints"] == 62
    margins = {row["margin_per_path_seconds"] for row in source["decisions"]}
    assert len(margins) == 1
    margin = margins.pop()
    assert math.isfinite(margin) and margin > 0
    audited = {}
    for row in source["decisions"]:
        audited.setdefault(row["race_id"], set()).add(row["driver"])
    names = driver_names(bundle / "backend" / "app" / "api" / "historical.py")
    from export_catalog import ADDITIONAL_NAMES
    names.update(ADDITIONAL_NAMES)
    folders = sorted((bundle / "data" / "processed" / "fastf1" / "cleaning_version=1.0").glob("season=*/round=*/session=R"))
    assert len(folders) == 68
    output = []
    with ProcessPoolExecutor(max_workers=workers, initializer=initialize, initargs=(str(bundle),)) as pool:
        tasks = {}
        for folder in folders:
            session = json.loads((folder / "manifest.json").read_text())["session"]
            task = pool.submit(export_session, str(bundle), str(folder), names, sorted(audited.get(session["identifier"], ())), margin)
            tasks[task] = session["identifier"]
        for index, task in enumerate(as_completed(tasks), start=1):
            race_id, records = task.result()
            assert race_id == tasks[task]
            output.extend(records)
            if index % 5 == 0 or index == len(tasks):
                print(f"Processed {index}/{len(tasks)} races, {len(output)//2} additional driver/race pairs", flush=True)
    output.sort(key=lambda row: (row["season"], row["race_id"], row["driver"], row["lap"]))
    pairs = {}
    for row in output:
        pairs.setdefault((row["race_id"], row["driver"]), []).append(row)
    assert all(len(pair) == 2 and pair[1]["lap"] == pair[0]["lap"] + 1 for pair in pairs.values())
    assert not {(row["race_id"], row["driver"]) for row in source["decisions"]} & set(pairs)
    payload = {
        "source": "Additional reconstructed dry pit windows; exploratory point estimates using frozen development model",
        "model_id": source["model_id"],
        "training_seasons": source["training_seasons"],
        "phase8_source_sha256": source["source_sha256"],
        "dataset_catalog_sha256": sha256_file(dataset_catalog),
        "count": len(output), "paired_checkpoints": len(pairs), "decisions": output,
    }
    destination = SITE / "dist" / "extended_decisions.json"
    destination.write_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n")
    print(f"Wrote {len(output)} exploratory point estimates at {len(pairs)} driver/race pairs", flush=True)


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        raise SystemExit("usage: python tools/export_extended.py /path/to/review-bundle [workers]")
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    bundle = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(bundle / "backend"))
    legacy_dependencies = os.environ.get("PITWALL_LEGACY_DEPENDENCIES")
    if legacy_dependencies:
        sys.path.append(legacy_dependencies)
    main(bundle, int(sys.argv[2]) if len(sys.argv) == 3 else 4)
