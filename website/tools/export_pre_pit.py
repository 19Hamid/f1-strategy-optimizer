"""Export additional pre-pit comparisons without altering the frozen audit.

The tyre is taken from the driver's next *recorded* dry stint. A candidate
must have an eligible, dry, green decision lap and a complete race horizon.
These are exploratory counterfactuals, never observed strategy outcomes.

Usage: python tools/export_pre_pit.py /path/to/review-bundle [workers]
Run with the backend's locked dependencies and a verified processed archive.
"""

from __future__ import annotations

import json
import math
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import replace
from pathlib import Path

import pandas as pd

from export_catalog import ADDITIONAL_NAMES, SITE
from export_decisions import driver_names, optional_number, verified_file

MODEL = None
DRY = frozenset(("SOFT", "MEDIUM", "HARD"))


def initialize(bundle_str: str) -> None:
    global MODEL
    from app.ml import ModelArtifactPaths
    from app.simulation import Phase6ModelAdapter

    bundle = Path(bundle_str)
    MODEL = Phase6ModelAdapter.from_paths(
        ModelArtifactPaths(bundle / "artifacts", "phase-6-final-audit-lap-time")
    )


def candidate_rows(laps: pd.DataFrame, decisions: pd.DataFrame, driver: str, team: str):
    """Choose the latest safe pair, or one safe lap, before a recorded dry stop."""
    driver_laps = laps.loc[laps["Driver"].eq(driver) & laps["Team"].eq(team)].sort_values("LapNumber")
    decision_rows = decisions.loc[
        decisions["driver"].eq(driver) & decisions["team"].eq(team)
    ].sort_values("decision_lap")
    options = []
    pit_entries = driver_laps.loc[driver_laps["PitInTime"].notna()]
    for _, pit in pit_entries.iterrows():
        pit_lap = int(pit["LapNumber"])
        next_lap = driver_laps.loc[driver_laps["LapNumber"].eq(pit_lap + 1)]
        if len(next_lap) != 1 or str(next_lap.iloc[0]["Compound"]).upper() not in DRY:
            continue
        prior_stops = pit_entries.loc[pit_entries["LapNumber"].lt(pit_lap)]
        stint_start = int(prior_stops.iloc[-1]["LapNumber"]) + 1 if len(prior_stops) else 1
        # The next lap is checked too: the immediate choice is not illustrated
        # across a known wet or non-green lap in the historical record.
        green = {
            int(lap) for lap, status, rain in driver_laps[
                ["LapNumber", "TrackStatus", "Rainfall"]
            ].itertuples(index=False, name=None)
            if str(status).strip() == "1" and pd.notna(rain) and not bool(rain)
        }
        safe = {
            int(row["decision_lap"]): row
            for _, row in decision_rows.iterrows()
            if stint_start + 1 <= int(row["decision_lap"]) < pit_lap
            and bool(row["is_decision_eligible"])
            and int(row["tyre_age_laps"]) >= 2
            and str(row["current_compound"]).upper() in DRY
            and int(row["decision_lap"]) in green
            and int(row["decision_lap"]) + 1 in green
        }
        for lap, row in safe.items():
            if lap - 1 in safe:
                group = (safe[lap - 1], row)
            else:
                group = (row,)
            target = str(next_lap.iloc[0]["Compound"]).upper()
            used = {
                str(compound).upper() for compound in driver_laps.loc[
                    driver_laps["LapNumber"].le(int(group[0]["decision_lap"])), "Compound"
                ] if str(compound).upper() in DRY
            }
            if len(used | {target}) < 2:
                continue  # A dry-race strategy cannot use only one compound.
            options.append((group, pit_lap, target))
    if not options:
        return None
    # Prefer adjacent checkpoints, then the latest moment before the stop.
    return max(options, key=lambda option: (len(option[0]), int(option[0][-1]["decision_lap"])))


def verified_finish_horizon(laps: pd.DataFrame, driver_laps: pd.DataFrame):
    """Use the driver's recorded finish, including a timed lapped crossing.

    A shorter trace is only accepted when its last recorded crossing comes
    shortly after the leader's last crossing and has a recorded position.
    Otherwise retirement/early termination cannot be distinguished safely.
    """
    leader_laps = int(laps["LapNumber"].max())
    last = driver_laps.sort_values("LapNumber").iloc[-1]
    driver_total = int(last["LapNumber"])
    if driver_total == leader_laps:
        return driver_total, leader_laps, "LEADER_LAP_FINISH"
    leader_last = laps.loc[laps["LapNumber"].eq(leader_laps)].sort_values("Time")
    if not len(leader_last) or pd.isna(leader_last.iloc[0]["Time"]) or pd.isna(last["Time"]) or pd.isna(last["Position"]):
        return None
    seconds_after_leader = (last["Time"] - leader_last.iloc[0]["Time"]).total_seconds()
    if not 0 <= seconds_after_leader <= 180:
        return None
    return driver_total, leader_laps, "LAPPED_FINISH_TIMING"


def make_request(row, *, season, race_id, race, total_laps, target, laps, decisions, registry):
    from app.optimizer.contracts import PitDecisionAction, PitDecisionRequest
    from app.simulation import DryCompound, RaceState, SimulationMode
    from app.simulation.observed_replay import build_observed_replay_context

    driver = str(row["driver"])
    team = str(row["team"])
    lap = int(row["decision_lap"])
    history = laps.loc[
        laps["Driver"].eq(driver) & laps["Team"].eq(team) & laps["LapNumber"].le(lap)
    ].sort_values("LapNumber")
    current = DryCompound(str(row["current_compound"]).upper())
    assert len(history) and str(history.iloc[-1]["Compound"]).upper() == current.value
    used = tuple(dict.fromkeys(
        DryCompound(str(value).upper()) for value in history["Compound"]
        if str(value).upper() in DRY
    ))
    state = RaceState(
        season=season, session_id=race_id, event_name=race, driver=driver, team=team,
        current_lap=lap, total_laps=total_laps, current_compound=current,
        tyre_age_laps=int(row["tyre_age_laps"]),
        current_stint_laps_completed=int(row["current_stint_laps_completed"]),
        completed_pit_stops=int(row["completed_pit_stops"]),
        compounds_used=used,
        previous_position=int(row["previous_position"]) if pd.notna(row["previous_position"]) else None,
    )
    request = PitDecisionRequest(
        state=state, target_compound=DryCompound(target),
        pit_loss=registry.resolve(event_name=race, scenario="NOMINAL").assumption,
    )
    # This context uses only measurements available up to the selected lap;
    # the recorded later tyre is a declared scenario assumption, not a feature.
    context = build_observed_replay_context(
        replace(request.simulation_request_for(PitDecisionAction.PIT_NOW), mode=SimulationMode.OBSERVED_STRATEGY_REPLAY),
        decisions, laps,
    )
    return request, context


def export_session(bundle_str: str, folder_str: str, names: dict, existing: list[str], margin: float):
    from app.optimizer.audit import _pit_loss_registry
    from app.optimizer.comparison import compare_pit_decision

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
    dataset = bundle / "data/datasets/f1_strategy/dataset_contract_version=1.0" / f"season={season}" / f"round={session['round_number']:02d}" / "session=R"
    dm = json.loads((dataset / "manifest.json").read_text())
    assert dm["session"]["identifier"] == race_id and dm["validation"]["status"] == "passed"
    assert dm["validation"]["protected_evaluation_season_accessed"] is False
    decisions = pd.read_parquet(verified_file(dataset, "decision_rows.parquet", dm["files"]["decision_rows.parquet"]))
    registry = _pit_loss_registry(pd.DataFrame({"event_name": [session["event_name"]]}))
    output = []
    unavailable = []
    for (driver, team), driver_laps in laps.groupby(["Driver", "Team"], sort=True):
        if driver in existing:
            continue
        finish = verified_finish_horizon(laps, driver_laps)
        if finish is None:
            unavailable.append((driver, "INCOMPLETE_HORIZON"))
            continue
        total_laps, leader_total_laps, finish_evidence = finish
        transitions = driver_laps.loc[driver_laps["PitInTime"].notna(), "LapNumber"]
        has_dry_transition = any(
            str(driver_laps.loc[driver_laps["LapNumber"].eq(int(pit) + 1), "Compound"].iloc[0]).upper() in DRY
            for pit in transitions
            if len(driver_laps.loc[driver_laps["LapNumber"].eq(int(pit) + 1)]) == 1
        )
        if not has_dry_transition:
            unavailable.append((driver, "NO_RECORDED_DRY_TYRE"))
            continue
        option = candidate_rows(laps, decisions, driver, team)
        if option is None:
            unavailable.append((driver, "NO_SAFE_DECISION_LAP"))
            continue
        pair, recorded_pit_lap, target = option
        results = []
        for row in pair:
            request, context = make_request(
                row, season=season, race_id=race_id,
                race=session["event_name"], total_laps=total_laps, target=target,
                laps=laps, decisions=decisions, registry=registry,
            )
            comparison = compare_pit_decision(request, context=context, adapter=MODEL)
            state = request.state
            advantage = comparison.pit_now_advantage_seconds
            item = {
                "id": f"{season}:{race_id}:{driver}:{state.current_lap}:{target}",
                "season": season, "race_id": race_id, "race": session["event_name"],
                "driver": driver, "name": names[driver], "team": team,
                "lap": state.current_lap, "total_laps": total_laps,
                "leader_total_laps": leader_total_laps,
                "finish_evidence": finish_evidence,
                "remaining_laps": request.remaining_laps,
                "current_tyre": state.current_compound.value, "target_tyre": target,
                "tyre_age": state.tyre_age_laps,
                "pit_now_seconds": comparison.pit_now.expected_remaining_time_seconds,
                "wait_seconds": comparison.stay_out.expected_remaining_time_seconds,
                "advantage_seconds": advantage,
                "point_favors": comparison.recommendation.value,
                "margin_per_path_seconds": margin,
                "band_low_seconds": advantage - 2 * margin,
                "band_high_seconds": advantage + 2 * margin,
                "verdict": "UNREVIEWED",
                "pit_loss_assumption_seconds": request.pit_loss.seconds,
                "position": state.previous_position,
                "last_lap_seconds": optional_number(row["previous_lap_time_seconds"]),
                "track_celsius": optional_number(row["track_temperature_celsius"]),
                "source_tier": "PRE_PIT_EXPLORATORY",
                "recorded_pit_lap": recorded_pit_lap,
            }
            assert math.isclose(item["wait_seconds"] - item["pit_now_seconds"], advantage, abs_tol=1e-6)
            results.append(item)
        output.extend(results)
    return race_id, output, unavailable


def main(bundle: Path, workers: int):
    from app.ml import ModelArtifactPaths
    from app.pipeline.serialization import sha256_file
    from app.simulation import Phase6ModelAdapter

    assert bundle.is_dir() and 1 <= workers <= 8
    assert not (bundle / "data/datasets/f1_strategy/dataset_contract_version=1.0/season=2025").exists()
    audited = json.loads((SITE / "dist/decisions.json").read_text())
    extended = json.loads((SITE / "dist/extended_decisions.json").read_text())
    assert audited["count"] == 124 and extended["count"] == 1028
    dataset_catalog = bundle / "data/datasets/f1_strategy/dataset_contract_version=1.0/catalog.parquet"
    adapter = Phase6ModelAdapter.from_paths(ModelArtifactPaths(bundle / "artifacts", "phase-6-final-audit-lap-time"))
    assert adapter.artifact.provenance.dataset_build_identifier == sha256_file(dataset_catalog)
    existing = {}
    for row in (*audited["decisions"], *extended["decisions"]):
        existing.setdefault(row["race_id"], set()).add(row["driver"])
    margin_values = {row["margin_per_path_seconds"] for row in audited["decisions"]}
    assert len(margin_values) == 1
    margin = margin_values.pop()
    names = driver_names(bundle / "backend/app/api/historical.py")
    names.update(ADDITIONAL_NAMES)
    folders = sorted((bundle / "data/processed/fastf1/cleaning_version=1.0").glob("season=*/round=*/session=R"))
    assert len(folders) == 68
    output, missing = [], {}
    with ProcessPoolExecutor(max_workers=workers, initializer=initialize, initargs=(str(bundle),)) as pool:
        jobs = {}
        for folder in folders:
            session = json.loads((folder / "manifest.json").read_text())["session"]
            jobs[pool.submit(export_session, str(bundle), str(folder), names, sorted(existing.get(session["identifier"], ())), margin)] = session["identifier"]
        for index, job in enumerate(as_completed(jobs), start=1):
            race_id, records, unavailable = job.result()
            assert race_id == jobs[job]
            output.extend(records)
            for driver, reason in unavailable:
                assert (race_id, driver) not in missing
                missing[(race_id, driver)] = reason
            if index % 5 == 0 or index == len(jobs):
                print(f"Processed {index}/68 races; {len(output)} additional moments", flush=True)
    output.sort(key=lambda row: (row["season"], row["race_id"], row["driver"], row["lap"]))
    cases = {}
    for row in output:
        cases.setdefault((row["race_id"], row["driver"]), []).append(row)
    assert all(len(group) in (1, 2) for group in cases.values())
    assert all(len(group) == 1 or group[1]["lap"] == group[0]["lap"] + 1 for group in cases.values())
    assert all(group[-1]["lap"] < group[-1]["recorded_pit_lap"] for group in cases.values())
    assert not set(cases) & {(row["race_id"], row["driver"]) for row in (*audited["decisions"], *extended["decisions"])}
    assert not set(cases) & set(missing)
    payload = {
        "source": "Earlier eligible dry green laps, using the tyre later fitted by that driver; exploratory model estimates",
        "model_id": audited["model_id"], "phase8_source_sha256": audited["source_sha256"],
        "dataset_catalog_sha256": sha256_file(dataset_catalog),
        "count": len(output), "case_count": len(cases),
        "paired_checkpoints": sum(len(group) == 2 for group in cases.values()),
        "single_checkpoints": sum(len(group) == 1 for group in cases.values()),
        "decisions": output,
        "unavailable": [{"race_id": race, "driver": driver, "reason": reason} for (race, driver), reason in sorted(missing.items())],
    }
    destination = SITE / "dist/pre_pit_decisions.json"
    destination.write_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n")
    print(f"Wrote {len(cases)} additional driver/race comparisons; {len(missing)} still unavailable")


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        raise SystemExit("usage: python tools/export_pre_pit.py /path/to/review-bundle [workers]")
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    bundle = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(bundle / "backend"))
    legacy = os.environ.get("PITWALL_LEGACY_DEPENDENCIES")
    if legacy:
        sys.path.append(legacy)
    main(bundle, int(sys.argv[2]) if len(sys.argv) == 3 else 4)
