"""Build a self-contained progress viewer from verified project artifacts."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from app.ml.artifacts import ModelArtifactPaths, verify_model_artifact
from app.ml.reports import ModelReportPaths, verify_model_report
from app.optimizer.contracts import DECISION_EQUALITY_ABS_TOLERANCE_SECONDS
from app.optimizer.storage import OptimizerReportPaths, verify_optimizer_report
from app.progress_viewer.template import render_progress_viewer
from app.simulation.storage import SimulationReportPaths, verify_simulation_report

DEFAULT_MODEL_RUN_ID = "phase-6-final-audit"
DEFAULT_MODEL_ARTIFACT_ID = "phase-6-final-audit-lap-time"
DEFAULT_SIMULATION_RUN_ID = "phase-7-final-audit"
DEFAULT_OPTIMIZER_RUN_ID = "phase-8-final-audit"


class ProgressViewerError(RuntimeError):
    """Raised when verified evidence cannot produce an honest viewer."""


@dataclass(frozen=True, slots=True)
class ProgressViewerPaths:
    """Inputs and output used by one generated progress viewer."""

    project_root: Path
    artifacts_root: Path
    output_directory: Path
    roadmap: Path
    model_run_id: str = DEFAULT_MODEL_RUN_ID
    model_artifact_id: str = DEFAULT_MODEL_ARTIFACT_ID
    simulation_run_id: str = DEFAULT_SIMULATION_RUN_ID
    optimizer_run_id: str = DEFAULT_OPTIMIZER_RUN_ID

    def __post_init__(self) -> None:
        """Normalize filesystem inputs and validate artifact identifiers."""
        for name in (
            "project_root",
            "artifacts_root",
            "output_directory",
            "roadmap",
        ):
            object.__setattr__(self, name, Path(getattr(self, name)))
        for name in (
            "model_run_id",
            "model_artifact_id",
            "simulation_run_id",
            "optimizer_run_id",
        ):
            value = str(getattr(self, name)).strip()
            if (
                not value
                or value in {".", ".."}
                or Path(value).name != value
                or "/" in value
                or "\\" in value
            ):
                raise ProgressViewerError(f"{name} must be one safe path segment")
            object.__setattr__(self, name, value)

    @property
    def output_file(self) -> Path:
        """Return the generated browser entry point."""
        return self.output_directory / "index.html"


def build_progress_viewer(paths: ProgressViewerPaths) -> Path:
    """Verify artifacts and write one self-contained HTML report."""
    if not isinstance(paths, ProgressViewerPaths):
        raise TypeError("paths must be a ProgressViewerPaths")
    _verify_inputs(paths)
    payload = _viewer_payload(paths)
    rendered = render_progress_viewer(payload)
    paths.output_directory.mkdir(parents=True, exist_ok=True)
    temporary = paths.output_directory / ".index.html.tmp"
    temporary.write_text(rendered, encoding="utf-8")
    temporary.replace(paths.output_file)
    return paths.output_file


def _verify_inputs(paths: ProgressViewerPaths) -> None:
    """Fail closed before reading or presenting stored evidence."""
    model_report = verify_model_report(
        ModelReportPaths(paths.artifacts_root, paths.model_run_id)
    )
    model = verify_model_artifact(
        ModelArtifactPaths(paths.artifacts_root, paths.model_artifact_id)
    )
    simulation = verify_simulation_report(
        SimulationReportPaths(paths.artifacts_root, paths.simulation_run_id)
    )
    optimizer = verify_optimizer_report(
        OptimizerReportPaths(paths.artifacts_root, paths.optimizer_run_id)
    )
    issues = [
        *(f"Phase 6 report: {issue}" for issue in model_report.issues),
        *(f"Phase 6 model: {issue}" for issue in model.issues),
        *(f"Phase 7 report: {issue}" for issue in simulation.issues),
        *(f"Phase 8 report: {issue}" for issue in optimizer.issues),
    ]
    if issues:
        raise ProgressViewerError(
            "progress viewer requires valid immutable evidence: " + "; ".join(issues)
        )
    if not paths.roadmap.is_file():
        raise ProgressViewerError(f"roadmap does not exist: {paths.roadmap}")


def _viewer_payload(paths: ProgressViewerPaths) -> dict[str, object]:
    """Load the minimum verified evidence needed by the browser report."""
    model_root = ModelReportPaths(paths.artifacts_root, paths.model_run_id).root
    simulation_root = SimulationReportPaths(
        paths.artifacts_root,
        paths.simulation_run_id,
    ).root
    optimizer_root = OptimizerReportPaths(
        paths.artifacts_root,
        paths.optimizer_run_id,
    ).root
    model_provenance = _read_json(model_root / "provenance.json")
    simulation_provenance = _read_json(simulation_root / "provenance.json")
    optimizer_provenance = _read_json(optimizer_root / "provenance.json")
    selection = pd.read_parquet(model_root / "selection.parquet")
    degradation = pd.read_parquet(model_root / "degradation_curve.parquet")
    slices = pd.read_parquet(model_root / "slice_metrics.parquet")
    metrics = pd.read_parquet(simulation_root / "metrics.parquet")
    replays = pd.read_parquet(simulation_root / "replays.parquet")
    trajectories = pd.read_parquet(simulation_root / "trajectories.parquet")
    optimizer_decisions = pd.read_parquet(optimizer_root / "decisions.parquet")
    optimizer_cases = pd.read_parquet(optimizer_root / "cases.parquet")
    optimizer_summaries = pd.read_parquet(optimizer_root / "summaries.parquet")
    phases = _parse_roadmap(paths.roadmap)
    selected = selection.loc[selection["selected"].eq(True)]
    if len(selected) != 1:
        raise ProgressViewerError("model report must contain exactly one winner")
    winner = selected.iloc[0]
    overall_lap = _one_metric(metrics, "OVERALL_LAP", "ALL")
    overall_remaining = _one_metric(metrics, "OVERALL_REMAINING", "ALL")
    optimizer_overall = _one_optimizer_summary(optimizer_summaries)
    optimizer_layers = _optimizer_decision_layers(optimizer_decisions)
    completed_progress = _overall_progress_percent(phases)
    if sum(int(phase["weight_percent"]) for phase in phases) != 100:
        raise ProgressViewerError("roadmap phase weights must total 100%")

    integrity = {
        "model_report": "valid",
        "model_artifact": "valid",
        "simulation_report": "valid",
        "optimizer_report": "valid",
        "protected_2025_rows": int(
            model_provenance["protected_evaluation_rows"]
        )
        + int(simulation_provenance["protected_evaluation_rows"])
        + int(optimizer_provenance["protected_evaluation_rows"]),
    }
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "project": {
            "title": "F1 Race Strategy Optimizer",
            "progress_percent": completed_progress,
            "completed_phases": sum(
                phase["status"] == "Completed" for phase in phases
            ),
            "total_phases": len(phases),
            "phases": phases,
        },
        "integrity": integrity,
        "model": {
            "run_id": paths.model_run_id,
            "candidate_parameter_sets": int(selection["candidate_id"].nunique()),
            "candidate_formulation_runs": len(selection),
            "development_sessions": int(model_provenance["development_sessions"]),
            "training_sessions": int(
                model_provenance["contributing_training_sessions"]
            ),
            "primary_targets": int(model_provenance["primary_target_rows"]),
            "auxiliary_targets": int(model_provenance["auxiliary_target_rows"]),
            "execution_device": str(model_provenance["execution_device"]),
            "winner": {
                "candidate_id": str(winner["candidate_id"]),
                "family": str(winner["model_family"]),
                "formulation": str(winner["formulation"]),
                "mae_seconds": float(
                    winner["full_common_mean_absolute_error_seconds"]
                ),
                "all_row_mae_seconds": float(
                    winner["full_mean_absolute_error_seconds"]
                ),
                "ablated_mae_seconds": float(
                    winner["ablated_common_mean_absolute_error_seconds"]
                ),
                "baseline_mae_seconds": float(
                    winner["baseline_common_mean_absolute_error_seconds"]
                ),
                "coverage_rate": float(winner["coverage_rate"]),
                "relative_improvement_percent": _relative_improvement(winner),
                "parameters": json.loads(str(winner["parameters"])),
            },
            "leaderboard": _leaderboard(selection),
            "degradation": _degradation_records(degradation),
            "event_slices": _event_slice_records(slices),
        },
        "simulation": {
            "run_id": paths.simulation_run_id,
            "audited_sessions": int(model_provenance["development_sessions"]),
            "replay_sessions": int(simulation_provenance["development_sessions"]),
            "replays": len(replays),
            "trajectory_laps": len(trajectories),
            "lap_mae_seconds": float(overall_lap["mean_absolute_error_seconds"]),
            "remaining_mae_seconds": float(
                overall_remaining["mean_absolute_error_seconds"]
            ),
            "horizon_metrics": _records(
                metrics.loc[metrics["scope"].eq("HORIZON_REMAINING")],
                (
                    "value",
                    "replays",
                    "laps",
                    "mean_absolute_error_seconds",
                    "p90_absolute_error_seconds",
                ),
            ),
            "event_metrics": _event_metric_records(metrics),
            "replay_options": _replay_records(replays),
            "trajectories": _trajectory_records(trajectories),
        },
        "optimizer": {
            "run_id": paths.optimizer_run_id,
            "audited_sessions": int(model_provenance["development_sessions"]),
            "decision_sessions": int(optimizer_provenance["development_sessions"]),
            "decisions": len(optimizer_decisions),
            "sensitivity_cases": len(optimizer_cases),
            "cases_per_decision": len(optimizer_cases) // len(optimizer_decisions),
            "observed_pit_now": int(optimizer_overall["observed_pit_now"]),
            "observed_stay_out": int(optimizer_overall["observed_stay_out"]),
            **optimizer_layers,
            "stable_pit_now": int(optimizer_overall["stable_pit_now"]),
            "stable_stay_out": int(optimizer_overall["stable_stay_out"]),
            "no_clear_advantage": int(optimizer_overall["no_clear_advantage"]),
            "comparable_observed_actions": int(
                optimizer_overall["comparable_observed_action_rows"]
            ),
            "aligned_observed_actions": int(
                optimizer_overall["aligned_observed_actions"]
            ),
            "observed_action_alignment_rate": _json_scalar(
                optimizer_overall["observed_action_alignment_rate"]
            ),
            "action_time_margin_seconds": _one_optimizer_margin(
                optimizer_decisions
            ),
            "action_difference_margin_seconds": 2
            * _one_optimizer_margin(optimizer_decisions),
            "event_summaries": _records(
                optimizer_summaries.loc[optimizer_summaries["scope"].eq("EVENT")],
                (
                    "value",
                    "decisions",
                    "stable_pit_now",
                    "stable_stay_out",
                    "no_clear_advantage",
                    "observed_action_alignment_rate",
                ),
            ),
        },
    }


def _optimizer_decision_layers(decisions: pd.DataFrame) -> dict[str, int | float]:
    """Separate point estimates, sensitivity consistency and final stability."""
    if decisions.empty:
        raise ProgressViewerError("optimizer report has no decisions")
    nominal = decisions["nominal_recommendation"].astype(str)
    supported = {"PIT_NOW", "STAY_OUT", "NO_CLEAR_ADVANTAGE"}
    unexpected = sorted(set(nominal) - supported)
    if unexpected:
        raise ProgressViewerError(
            f"optimizer report has unsupported nominal outcomes: {unexpected}"
        )
    minimum = pd.to_numeric(
        decisions["sensitivity_min_advantage_seconds"],
        errors="coerce",
    )
    maximum = pd.to_numeric(
        decisions["sensitivity_max_advantage_seconds"],
        errors="coerce",
    )
    if (
        not np.isfinite(minimum.to_numpy(dtype=float)).all()
        or not np.isfinite(maximum.to_numpy(dtype=float)).all()
        or bool((minimum > maximum).any())
    ):
        raise ProgressViewerError("optimizer sensitivity bounds are invalid")
    decisive = (
        (minimum > DECISION_EQUALITY_ABS_TOLERANCE_SECONDS)
        | (maximum < -DECISION_EQUALITY_ABS_TOLERANCE_SECONDS)
    )
    decisive_count = int(decisive.sum())
    return {
        "nominal_pit_now": int(nominal.eq("PIT_NOW").sum()),
        "nominal_stay_out": int(nominal.eq("STAY_OUT").sum()),
        "nominal_no_clear_advantage": int(
            nominal.eq("NO_CLEAR_ADVANTAGE").sum()
        ),
        "sensitivity_decisive": decisive_count,
        "sensitivity_ambiguous": len(decisions) - decisive_count,
        "sensitivity_direction_consistency_rate": decisive_count
        / len(decisions),
    }


def _parse_roadmap(path: Path) -> list[dict[str, object]]:
    """Read the canonical development-roadmap table."""
    lines = path.read_text(encoding="utf-8").splitlines()
    header_index = next(
        (
            index
            for index, line in enumerate(lines)
            if line.strip().startswith("| Phase | Weight | Status |")
        ),
        None,
    )
    if header_index is None:
        raise ProgressViewerError("development roadmap table was not found")
    phases: list[dict[str, object]] = []
    for line in lines[header_index + 2 :]:
        if not line.strip().startswith("|"):
            break
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 4:
            raise ProgressViewerError("development roadmap row is malformed")
        phase_match = re.fullmatch(r"(\d+)\.\s+(.+)", cells[0])
        weight_match = re.fullmatch(r"(\d+)%", cells[1])
        if phase_match is None or weight_match is None:
            raise ProgressViewerError("development roadmap identity is malformed")
        completion_percent, status_class = _phase_status(cells[2])
        phases.append(
            {
                "number": int(phase_match.group(1)),
                "name": phase_match.group(2),
                "weight_percent": int(weight_match.group(1)),
                "status": cells[2],
                "status_class": status_class,
                "completion_percent": completion_percent,
                "result": cells[3],
            }
        )
    if not phases:
        raise ProgressViewerError("development roadmap has no phases")
    if [phase["number"] for phase in phases] != list(range(len(phases))):
        raise ProgressViewerError("development roadmap phase numbers are not contiguous")
    return phases


def _phase_status(status: str) -> tuple[int, str]:
    """Return validated within-phase completion and a safe CSS class."""
    if status == "Completed":
        return 100, "completed"
    if status == "Planned":
        return 0, "planned"
    match = re.fullmatch(r"In progress \((\d{1,3})%\)", status)
    if match is None:
        raise ProgressViewerError(f"unsupported roadmap phase status: {status!r}")
    completion_percent = int(match.group(1))
    if not 0 < completion_percent < 100:
        raise ProgressViewerError(
            "in-progress roadmap percentage must be between 1% and 99%"
        )
    return completion_percent, "in-progress"


def _overall_progress_percent(phases: list[dict[str, object]]) -> int | float:
    """Weight completed and partially completed phases from the roadmap."""
    progress = sum(
        int(phase["weight_percent"]) * int(phase["completion_percent"]) / 100
        for phase in phases
    )
    rounded = round(progress, 1)
    return int(rounded) if rounded.is_integer() else rounded


def _relative_improvement(winner: pd.Series) -> float:
    baseline = float(winner["baseline_common_mean_absolute_error_seconds"])
    selected = float(winner["full_common_mean_absolute_error_seconds"])
    if not math.isfinite(baseline) or baseline <= 0:
        raise ProgressViewerError("selected-model baseline must be positive")
    return (baseline - selected) / baseline * 100.0


def _leaderboard(selection: pd.DataFrame) -> list[dict[str, object]]:
    ordered = selection.sort_values(
        [
            "meets_selection_contract",
            "full_common_mean_absolute_error_seconds",
            "candidate_id",
        ],
        ascending=[False, True, True],
        kind="stable",
    ).head(12)
    return _records(
        ordered,
        (
            "candidate_id",
            "model_family",
            "formulation",
            "full_common_mean_absolute_error_seconds",
            "coverage_rate",
            "meets_selection_contract",
            "selected",
        ),
    )


def _degradation_records(frame: pd.DataFrame) -> list[dict[str, object]]:
    columns = (
        "mean_tyre_age_laps",
        "mean_observed_lap_time_delta_seconds",
        "mean_predicted_lap_time_delta_seconds",
        "mean_absolute_error_seconds",
    )
    records: list[dict[str, object]] = []
    for (compound, band), group in frame.groupby(
        ["current_compound", "tyre_age_band"],
        sort=True,
    ):
        weights = pd.to_numeric(group["rows"]).to_numpy(dtype="float64")
        record: dict[str, object] = {
            "compound": str(compound),
            "tyre_age_band": str(band),
            "rows": int(weights.sum()),
        }
        for column in columns:
            values = pd.to_numeric(group[column]).to_numpy(dtype="float64")
            record[column] = float(np.average(values, weights=weights))
        records.append(record)
    band_order = {"NEW_0_5": 0, "USED_6_15": 1, "OLD_16_PLUS": 2}
    records.sort(
        key=lambda item: (
            str(item["compound"]),
            band_order.get(str(item["tyre_age_band"]), 99),
        )
    )
    return records


def _event_slice_records(frame: pd.DataFrame) -> list[dict[str, object]]:
    selected = frame.loc[
        frame["dimension"].eq("event_name")
        & frame["feature_set_id"].eq("full")
    ]
    records: list[dict[str, object]] = []
    for event_name, group in selected.groupby("value", sort=True):
        weights = pd.to_numeric(group["rows"]).to_numpy(dtype="float64")
        values = pd.to_numeric(
            group["mean_absolute_error_seconds"]
        ).to_numpy(dtype="float64")
        records.append(
            {
                "event_name": str(event_name),
                "rows": int(weights.sum()),
                "mean_absolute_error_seconds": float(
                    np.average(values, weights=weights)
                ),
            }
        )
    records.sort(key=lambda item: -float(item["mean_absolute_error_seconds"]))
    return records[:12]


def _event_metric_records(metrics: pd.DataFrame) -> list[dict[str, object]]:
    selected = metrics.loc[metrics["scope"].eq("EVENT_REMAINING")].sort_values(
        "mean_absolute_error_seconds",
        ascending=False,
        kind="stable",
    )
    return _records(
        selected,
        (
            "value",
            "replays",
            "laps",
            "mean_absolute_error_seconds",
            "p90_absolute_error_seconds",
            "mean_signed_error_seconds",
        ),
    )


def _replay_records(frame: pd.DataFrame) -> list[dict[str, object]]:
    ordered = frame.sort_values(
        ["event_name", "driver", "remaining_laps", "replay_id"],
        kind="stable",
    )
    return _records(
        ordered,
        (
            "replay_id",
            "season",
            "event_name",
            "driver",
            "team",
            "start_lap",
            "total_laps",
            "remaining_laps",
            "horizon",
            "initial_compound",
            "planned_stops_json",
            "predicted_remaining_time_seconds",
            "observed_remaining_time_seconds",
            "absolute_remaining_time_error_seconds",
        ),
    )


def _trajectory_records(frame: pd.DataFrame) -> dict[str, list[dict[str, object]]]:
    records: dict[str, list[dict[str, object]]] = {}
    ordered = frame.sort_values(["replay_id", "lap_number"], kind="stable")
    columns = (
        "lap_number",
        "predicted_total_lap_time_seconds",
        "observed_total_lap_time_seconds",
        "cumulative_predicted_time_seconds",
        "cumulative_observed_time_seconds",
        "pit_stop_after_lap",
        "start_compound",
        "start_tyre_age_laps",
    )
    for replay_id, group in ordered.groupby("replay_id", sort=True):
        records[str(replay_id)] = _records(group, columns)
    return records


def _one_metric(frame: pd.DataFrame, scope: str, value: str) -> pd.Series:
    selected = frame.loc[frame["scope"].eq(scope) & frame["value"].eq(value)]
    if len(selected) != 1:
        raise ProgressViewerError(f"missing unique simulation metric: {scope}/{value}")
    return selected.iloc[0]


def _one_optimizer_summary(frame: pd.DataFrame) -> pd.Series:
    selected = frame.loc[frame["scope"].eq("OVERALL") & frame["value"].eq("ALL")]
    if len(selected) != 1:
        raise ProgressViewerError("missing unique overall optimizer summary")
    return selected.iloc[0]


def _one_optimizer_margin(frame: pd.DataFrame) -> float:
    margins = pd.to_numeric(frame["action_time_margin_seconds"]).unique()
    if len(margins) != 1 or not math.isfinite(float(margins[0])):
        raise ProgressViewerError("optimizer decisions do not share one finite margin")
    return float(margins[0])


def _records(
    frame: pd.DataFrame,
    columns: tuple[str, ...],
) -> list[dict[str, object]]:
    return [
        {column: _json_scalar(row[column]) for column in columns}
        for _, row in frame.loc[:, columns].iterrows()
    ]


def _json_scalar(value: Any) -> object:
    if isinstance(value, np.generic):
        value = value.item()
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProgressViewerError(f"could not read {path}: {error}") from error
    if not isinstance(document, dict):
        raise ProgressViewerError(f"JSON document must be an object: {path}")
    return document
