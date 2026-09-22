"""Reproducible reporting tables for Phase 7 observed-strategy replays."""

from __future__ import annotations

import json
import math
import platform
from dataclasses import asdict, dataclass
from enum import StrEnum
from importlib.metadata import PackageNotFoundError, version
from typing import Final

import numpy as np
import pandas as pd

from app.baselines.metrics import RegressionMetrics, regression_metrics
from app.ml import APPROVED_FEATURE_COLUMNS, MODEL_CONTRACT_VERSION
from app.simulation.contracts import (
    DEVELOPMENT_SEASONS,
    SIMULATION_CONTRACT_VERSION,
    SIMULATION_RANDOM_SEED,
    SimulationContractError,
)
from app.simulation.observed_replay import (
    ObservedReplayEvaluation,
    ReplayHorizon,
)

SIMULATION_METRIC_COLUMNS: Final = (
    "scope",
    "value",
    "replays",
    "laps",
    "mean_absolute_error_seconds",
    "root_mean_squared_error_seconds",
    "median_absolute_error_seconds",
    "p90_absolute_error_seconds",
    "mean_signed_error_seconds",
)
SIMULATION_REPLAY_COLUMNS: Final = (
    "replay_id",
    "season",
    "session_id",
    "event_name",
    "driver",
    "team",
    "start_lap",
    "total_laps",
    "remaining_laps",
    "horizon",
    "strategy_id",
    "simulation_mode",
    "random_seed",
    "initial_compound",
    "initial_tyre_age_laps",
    "initial_stint_laps_completed",
    "initial_completed_pit_stops",
    "compounds_used_json",
    "planned_stops_json",
    "pit_loss_seconds_per_stop",
    "pit_loss_source",
    "pit_loss_evidence",
    "pit_stops_simulated",
    "predicted_racing_time_seconds",
    "applied_pit_loss_seconds",
    "predicted_remaining_time_seconds",
    "observed_remaining_time_seconds",
    "signed_remaining_time_error_seconds",
    "absolute_remaining_time_error_seconds",
)
SIMULATION_TRAJECTORY_COLUMNS: Final = (
    "replay_id",
    "lap_number",
    "laps_remaining_after_lap",
    "start_compound",
    "start_tyre_age_laps",
    "start_stint_laps_completed",
    "pit_stop_after_lap",
    "new_compound",
    "next_compound",
    "next_tyre_age_laps",
    "next_stint_laps_completed",
    "predicted_racing_time_seconds",
    "applied_pit_loss_seconds",
    "predicted_total_lap_time_seconds",
    "observed_total_lap_time_seconds",
    "signed_lap_error_seconds",
    "cumulative_predicted_time_seconds",
    "cumulative_observed_time_seconds",
    "cumulative_signed_error_seconds",
    "elapsed_time_after_lap_seconds",
    "finished",
    "model_features_json",
)
_REQUIRED_DEPENDENCIES: Final = frozenset({"numpy", "pandas", "pyarrow", "python"})


class SimulationReportingError(SimulationContractError):
    """Raised when replay evidence cannot form an honest report."""


class SimulationMetricScope(StrEnum):
    """Stable aggregate and diagnostic report populations."""

    OVERALL_LAP = "OVERALL_LAP"
    OVERALL_REMAINING = "OVERALL_REMAINING"
    HORIZON_REMAINING = "HORIZON_REMAINING"
    EVENT_LAP = "EVENT_LAP"
    EVENT_REMAINING = "EVENT_REMAINING"


@dataclass(frozen=True, slots=True)
class SimulationReportProvenance:
    """Data, model, runtime and holdout identity for one Phase 7 report."""

    simulation_contract_version: str
    model_contract_version: str
    model_artifact_id: str
    dataset_contract_version: str
    dataset_build_identifier: str
    development_sessions: int
    protected_evaluation_rows: int
    random_seed: int
    dependency_versions: tuple[tuple[str, str], ...]
    execution_duration_seconds: float

    def __post_init__(self) -> None:
        """Reject incomplete, protected or non-canonical provenance."""
        if self.simulation_contract_version != SIMULATION_CONTRACT_VERSION:
            raise SimulationReportingError("unexpected simulation contract version")
        if self.model_contract_version != MODEL_CONTRACT_VERSION:
            raise SimulationReportingError("unexpected model contract version")
        for name in (
            "model_artifact_id",
            "dataset_contract_version",
            "dataset_build_identifier",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise SimulationReportingError(f"{name} must not be blank")
        if (
            isinstance(self.development_sessions, bool)
            or not isinstance(self.development_sessions, int)
            or self.development_sessions < 1
        ):
            raise SimulationReportingError(
                "development_sessions must be a positive integer"
            )
        if self.protected_evaluation_rows != 0:
            raise SimulationReportingError("protected evaluation rows entered Phase 7")
        if self.random_seed != SIMULATION_RANDOM_SEED:
            raise SimulationReportingError(
                "random seed differs from the simulation contract"
            )
        if tuple(sorted(self.dependency_versions)) != self.dependency_versions:
            raise SimulationReportingError("dependency versions must be canonical")
        names = {name for name, _ in self.dependency_versions}
        if names != _REQUIRED_DEPENDENCIES:
            raise SimulationReportingError("dependency version evidence is incomplete")
        if any(not name or not value for name, value in self.dependency_versions):
            raise SimulationReportingError("dependency versions must not be blank")
        if (
            isinstance(self.execution_duration_seconds, bool)
            or not isinstance(self.execution_duration_seconds, (int, float))
            or not math.isfinite(self.execution_duration_seconds)
            or self.execution_duration_seconds < 0
        ):
            raise SimulationReportingError(
                "execution_duration_seconds must be finite and non-negative"
            )


@dataclass(frozen=True, slots=True)
class SimulationReportTables:
    """Normalized replay evidence ready for immutable storage."""

    metrics: pd.DataFrame
    replays: pd.DataFrame
    trajectories: pd.DataFrame
    provenance: SimulationReportProvenance

    def __post_init__(self) -> None:
        """Require explicit table and provenance objects."""
        for name in ("metrics", "replays", "trajectories"):
            if not isinstance(getattr(self, name), pd.DataFrame):
                raise TypeError(f"{name} must be a pandas DataFrame")
        if not isinstance(self.provenance, SimulationReportProvenance):
            raise TypeError("provenance must be a SimulationReportProvenance")


def runtime_simulation_dependency_versions() -> tuple[tuple[str, str], ...]:
    """Capture dependencies capable of changing stored numeric evidence."""
    dependencies = {"python": platform.python_version()}
    for package in ("numpy", "pandas", "pyarrow"):
        try:
            dependencies[package] = version(package)
        except PackageNotFoundError as error:
            raise SimulationReportingError(
                f"required dependency is not installed: {package}"
            ) from error
    return tuple(sorted(dependencies.items()))


def build_simulation_report(
    *,
    evaluation: ObservedReplayEvaluation,
    provenance: SimulationReportProvenance,
) -> SimulationReportTables:
    """Normalize aggregate, replay and complete lap-level evidence."""
    if not isinstance(evaluation, ObservedReplayEvaluation):
        raise TypeError("evaluation must be an ObservedReplayEvaluation")
    if not isinstance(provenance, SimulationReportProvenance):
        raise TypeError("provenance must be a SimulationReportProvenance")

    replay_records: list[dict[str, object]] = []
    trajectory_records: list[dict[str, object]] = []
    for replay in sorted(evaluation.replays, key=lambda item: item.replay_id):
        request = replay.simulation.request
        state = request.state
        replay_records.append(
            {
                "replay_id": replay.replay_id,
                "season": state.season,
                "session_id": state.session_id,
                "event_name": state.event_name,
                "driver": state.driver,
                "team": state.team,
                "start_lap": state.current_lap,
                "total_laps": state.total_laps,
                "remaining_laps": replay.observed.remaining_laps,
                "horizon": _horizon(replay.observed.remaining_laps).value,
                "strategy_id": request.strategy.strategy_id,
                "simulation_mode": request.mode.value,
                "random_seed": request.random_seed,
                "initial_compound": state.current_compound.value,
                "initial_tyre_age_laps": state.tyre_age_laps,
                "initial_stint_laps_completed": (state.current_stint_laps_completed),
                "initial_completed_pit_stops": state.completed_pit_stops,
                "compounds_used_json": _json(
                    [compound.value for compound in state.compounds_used]
                ),
                "planned_stops_json": _json(
                    [
                        {
                            "after_lap": stop.after_lap,
                            "new_compound": stop.new_compound.value,
                        }
                        for stop in request.strategy.stops
                    ]
                ),
                "pit_loss_seconds_per_stop": request.pit_loss.seconds,
                "pit_loss_source": request.pit_loss.source.value,
                "pit_loss_evidence": request.pit_loss.evidence,
                "pit_stops_simulated": replay.simulation.pit_stops_simulated,
                "predicted_racing_time_seconds": (
                    replay.simulation.racing_time_seconds
                ),
                "applied_pit_loss_seconds": replay.simulation.pit_loss_seconds,
                "predicted_remaining_time_seconds": (
                    replay.predicted_remaining_time_seconds
                ),
                "observed_remaining_time_seconds": (
                    replay.observed_remaining_time_seconds
                ),
                "signed_remaining_time_error_seconds": (
                    replay.signed_remaining_time_error_seconds
                ),
                "absolute_remaining_time_error_seconds": (
                    replay.absolute_remaining_time_error_seconds
                ),
            }
        )
        for simulation_lap, error in zip(
            replay.simulation.laps,
            replay.lap_errors,
            strict=True,
        ):
            transition = simulation_lap.transition
            stop = transition.pit_stop
            trajectory_records.append(
                {
                    "replay_id": replay.replay_id,
                    "lap_number": transition.lap_number,
                    "laps_remaining_after_lap": (error.laps_remaining_after_lap),
                    "start_compound": transition.start_compound.value,
                    "start_tyre_age_laps": transition.start_tyre_age_laps,
                    "start_stint_laps_completed": (
                        transition.start_stint_laps_completed
                    ),
                    "pit_stop_after_lap": stop is not None,
                    "new_compound": (None if stop is None else stop.new_compound.value),
                    "next_compound": transition.next_compound.value,
                    "next_tyre_age_laps": transition.next_tyre_age_laps,
                    "next_stint_laps_completed": (transition.next_stint_laps_completed),
                    "predicted_racing_time_seconds": (
                        error.predicted_racing_time_seconds
                    ),
                    "applied_pit_loss_seconds": (error.applied_pit_loss_seconds),
                    "predicted_total_lap_time_seconds": (
                        error.predicted_total_lap_time_seconds
                    ),
                    "observed_total_lap_time_seconds": (
                        error.observed_total_lap_time_seconds
                    ),
                    "signed_lap_error_seconds": error.signed_lap_error_seconds,
                    "cumulative_predicted_time_seconds": (
                        error.cumulative_predicted_time_seconds
                    ),
                    "cumulative_observed_time_seconds": (
                        error.cumulative_observed_time_seconds
                    ),
                    "cumulative_signed_error_seconds": (
                        error.cumulative_signed_error_seconds
                    ),
                    "elapsed_time_after_lap_seconds": (
                        transition.elapsed_time_after_lap_seconds
                    ),
                    "finished": transition.finished,
                    "model_features_json": _json(simulation_lap.model_features),
                }
            )

    replays = pd.DataFrame.from_records(
        replay_records,
        columns=SIMULATION_REPLAY_COLUMNS,
    )
    trajectories = pd.DataFrame.from_records(
        trajectory_records,
        columns=SIMULATION_TRAJECTORY_COLUMNS,
    )
    metrics = _metric_table(replays, trajectories)
    tables = SimulationReportTables(
        metrics=metrics,
        replays=replays,
        trajectories=trajectories,
        provenance=provenance,
    )
    validate_simulation_report_tables(tables)
    return tables


def validate_simulation_report_tables(
    tables: SimulationReportTables,
) -> None:
    """Require exact schemas, identities and arithmetic reconciliation."""
    if not isinstance(tables, SimulationReportTables):
        raise TypeError("tables must be a SimulationReportTables")
    expected_columns = {
        "metrics": SIMULATION_METRIC_COLUMNS,
        "replays": SIMULATION_REPLAY_COLUMNS,
        "trajectories": SIMULATION_TRAJECTORY_COLUMNS,
    }
    for name, columns in expected_columns.items():
        frame = getattr(tables, name)
        if tuple(frame.columns) != columns:
            raise SimulationReportingError(
                f"{name} columns differ from the report contract"
            )
        if frame.empty:
            raise SimulationReportingError(f"{name} must not be empty")

    replays = tables.replays
    trajectories = tables.trajectories
    if replays["replay_id"].duplicated().any():
        raise SimulationReportingError("replay identities must be unique")
    if trajectories.loc[:, ["replay_id", "lap_number"]].duplicated().any():
        raise SimulationReportingError("trajectory lap identities must be unique")
    seasons = set(pd.to_numeric(replays["season"]).astype(int))
    if not seasons.issubset(DEVELOPMENT_SEASONS):
        raise SimulationReportingError(
            "report contains rows outside development seasons"
        )
    session_count = len(replays.loc[:, ["season", "session_id"]].drop_duplicates())
    if session_count != tables.provenance.development_sessions:
        raise SimulationReportingError(
            "development session count differs from provenance"
        )
    if not replays["random_seed"].eq(tables.provenance.random_seed).all():
        raise SimulationReportingError(
            "stored random seeds differ from provenance"
        )
    if not replays["simulation_mode"].eq(
        "OBSERVED_STRATEGY_REPLAY"
    ).all():
        raise SimulationReportingError(
            "report contains a non-replay simulation mode"
        )
    if set(trajectories["replay_id"]) != set(replays["replay_id"]):
        raise SimulationReportingError("replay and trajectory identities differ")

    for replay in replays.itertuples(index=False):
        rows = trajectories.loc[
            trajectories["replay_id"].eq(replay.replay_id)
        ].sort_values("lap_number", kind="stable")
        expected_laps = tuple(range(int(replay.start_lap), int(replay.total_laps) + 1))
        if tuple(rows["lap_number"]) != expected_laps:
            raise SimulationReportingError(
                "stored trajectory does not cover its complete horizon"
            )
        if len(rows) != int(replay.remaining_laps):
            raise SimulationReportingError(
                "stored trajectory count differs from replay summary"
            )
        if replay.horizon != _horizon(int(replay.remaining_laps)).value:
            raise SimulationReportingError(
                "stored horizon differs from remaining laps"
            )
        if tuple(rows["finished"]) != (
            *(False for _ in range(len(rows) - 1)),
            True,
        ):
            raise SimulationReportingError(
                "stored finished markers do not identify only the final lap"
            )
        planned_stops = json.loads(str(replay.planned_stops_json))
        if not isinstance(planned_stops, list):
            raise SimulationReportingError(
                "stored planned stops must be a JSON list"
            )
        if len(planned_stops) != int(replay.pit_stops_simulated):
            raise SimulationReportingError(
                "stored planned stop count differs from replay summary"
            )
        if int(rows["pit_stop_after_lap"].sum()) != int(
            replay.pit_stops_simulated
        ):
            raise SimulationReportingError(
                "stored trajectory stop count differs from replay summary"
            )
        _close_series(
            rows["predicted_racing_time_seconds"] + rows["applied_pit_loss_seconds"],
            rows["predicted_total_lap_time_seconds"],
            "stored lap totals",
        )
        _close_series(
            rows["predicted_total_lap_time_seconds"]
            - rows["observed_total_lap_time_seconds"],
            rows["signed_lap_error_seconds"],
            "stored lap errors",
        )
        _close(
            rows["predicted_racing_time_seconds"].sum(),
            replay.predicted_racing_time_seconds,
            "stored predicted racing time",
        )
        _close(
            rows["applied_pit_loss_seconds"].sum(),
            replay.applied_pit_loss_seconds,
            "stored applied pit loss",
        )
        _close(
            replay.pit_loss_seconds_per_stop * replay.pit_stops_simulated,
            replay.applied_pit_loss_seconds,
            "stored pit-loss assumption",
        )
        _close(
            replay.predicted_racing_time_seconds
            + replay.applied_pit_loss_seconds,
            replay.predicted_remaining_time_seconds,
            "stored replay total",
        )
        _close(
            replay.predicted_remaining_time_seconds
            - replay.observed_remaining_time_seconds,
            replay.signed_remaining_time_error_seconds,
            "stored remaining-time error",
        )
        _close(
            abs(replay.signed_remaining_time_error_seconds),
            replay.absolute_remaining_time_error_seconds,
            "stored absolute remaining-time error",
        )
        _close_series(
            rows["predicted_total_lap_time_seconds"].cumsum(),
            rows["cumulative_predicted_time_seconds"],
            "stored cumulative predicted times",
        )
        _close_series(
            rows["observed_total_lap_time_seconds"].cumsum(),
            rows["cumulative_observed_time_seconds"],
            "stored cumulative observed times",
        )
        _close_series(
            rows["cumulative_predicted_time_seconds"]
            - rows["cumulative_observed_time_seconds"],
            rows["cumulative_signed_error_seconds"],
            "stored cumulative errors",
        )
        _close_series(
            rows["cumulative_predicted_time_seconds"],
            rows["elapsed_time_after_lap_seconds"],
            "stored engine elapsed times",
        )
        if len(rows) > 1:
            starts = tuple(rows["start_compound"].iloc[1:])
            previous_next = tuple(rows["next_compound"].iloc[:-1])
            if starts != previous_next:
                raise SimulationReportingError(
                    "stored compound states do not form one trajectory"
                )
        final = rows.iloc[-1]
        _close(
            final["cumulative_predicted_time_seconds"],
            replay.predicted_remaining_time_seconds,
            "stored predicted remaining time",
        )
        _close(
            final["cumulative_observed_time_seconds"],
            replay.observed_remaining_time_seconds,
            "stored observed remaining time",
        )
        for serialized in rows["model_features_json"]:
            features = json.loads(str(serialized))
            if tuple(item[0] for item in features) != APPROVED_FEATURE_COLUMNS:
                raise SimulationReportingError(
                    "stored model feature order differs from Phase 6"
                )

    expected_metrics = _metric_table(replays, trajectories)
    _compare_metric_tables(tables.metrics, expected_metrics)


def simulation_provenance_document(
    tables: SimulationReportTables,
) -> dict[str, object]:
    """Return deterministic JSON-compatible report provenance."""
    validate_simulation_report_tables(tables)
    document = asdict(tables.provenance)
    document["metric_rows"] = len(tables.metrics)
    document["replay_rows"] = len(tables.replays)
    document["trajectory_rows"] = len(tables.trajectories)
    return document


def _metric_table(
    replays: pd.DataFrame,
    trajectories: pd.DataFrame,
) -> pd.DataFrame:
    records = [
        _metric_record(
            scope=SimulationMetricScope.OVERALL_LAP,
            value="ALL",
            replays=len(replays),
            laps=len(trajectories),
            metrics=regression_metrics(
                trajectories["observed_total_lap_time_seconds"],
                trajectories["predicted_total_lap_time_seconds"],
            ),
        ),
        _metric_record(
            scope=SimulationMetricScope.OVERALL_REMAINING,
            value="ALL",
            replays=len(replays),
            laps=len(trajectories),
            metrics=regression_metrics(
                replays["observed_remaining_time_seconds"],
                replays["predicted_remaining_time_seconds"],
            ),
        ),
    ]
    for horizon in ReplayHorizon:
        selected = replays.loc[replays["horizon"].eq(horizon.value)]
        if selected.empty:
            continue
        replay_ids = set(selected["replay_id"])
        lap_count = int(trajectories["replay_id"].isin(replay_ids).sum())
        records.append(
            _metric_record(
                scope=SimulationMetricScope.HORIZON_REMAINING,
                value=horizon.value,
                replays=len(selected),
                laps=lap_count,
                metrics=regression_metrics(
                    selected["observed_remaining_time_seconds"],
                    selected["predicted_remaining_time_seconds"],
                ),
            )
        )
    for event_name in sorted(replays["event_name"].astype(str).unique()):
        selected = replays.loc[replays["event_name"].eq(event_name)]
        replay_ids = set(selected["replay_id"])
        laps = trajectories.loc[trajectories["replay_id"].isin(replay_ids)]
        records.extend(
            (
                _metric_record(
                    scope=SimulationMetricScope.EVENT_LAP,
                    value=event_name,
                    replays=len(selected),
                    laps=len(laps),
                    metrics=regression_metrics(
                        laps["observed_total_lap_time_seconds"],
                        laps["predicted_total_lap_time_seconds"],
                    ),
                ),
                _metric_record(
                    scope=SimulationMetricScope.EVENT_REMAINING,
                    value=event_name,
                    replays=len(selected),
                    laps=len(laps),
                    metrics=regression_metrics(
                        selected["observed_remaining_time_seconds"],
                        selected["predicted_remaining_time_seconds"],
                    ),
                ),
            )
        )
    return pd.DataFrame.from_records(
        records,
        columns=SIMULATION_METRIC_COLUMNS,
    )


def _metric_record(
    *,
    scope: SimulationMetricScope,
    value: str,
    replays: int,
    laps: int,
    metrics: RegressionMetrics,
) -> dict[str, object]:
    return {
        "scope": scope.value,
        "value": value,
        "replays": replays,
        "laps": laps,
        "mean_absolute_error_seconds": metrics.mean_absolute_error_seconds,
        "root_mean_squared_error_seconds": (metrics.root_mean_squared_error_seconds),
        "median_absolute_error_seconds": (metrics.median_absolute_error_seconds),
        "p90_absolute_error_seconds": metrics.p90_absolute_error_seconds,
        "mean_signed_error_seconds": metrics.mean_signed_error_seconds,
    }


def _compare_metric_tables(
    actual: pd.DataFrame,
    expected: pd.DataFrame,
) -> None:
    identity = ["scope", "value", "replays", "laps"]
    if not actual.loc[:, identity].equals(expected.loc[:, identity]):
        raise SimulationReportingError(
            "stored metric populations differ from replay evidence"
        )
    numeric = list(SIMULATION_METRIC_COLUMNS[4:])
    if not np.allclose(
        actual.loc[:, numeric].to_numpy(dtype="float64"),
        expected.loc[:, numeric].to_numpy(dtype="float64"),
        rtol=0.0,
        atol=1e-12,
    ):
        raise SimulationReportingError("stored metrics differ from replay evidence")


def _horizon(remaining_laps: int) -> ReplayHorizon:
    if remaining_laps <= 10:
        return ReplayHorizon.SHORT
    if remaining_laps <= 25:
        return ReplayHorizon.MEDIUM
    return ReplayHorizon.LONG


def _json(value: object) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _close_series(
    actual: pd.Series,
    expected: pd.Series,
    field_name: str,
) -> None:
    if not np.allclose(
        actual.to_numpy(dtype="float64"),
        expected.to_numpy(dtype="float64"),
        rtol=0.0,
        atol=1e-9,
    ):
        raise SimulationReportingError(f"{field_name} do not reconcile")


def _close(actual: object, expected: object, field_name: str) -> None:
    if not math.isclose(
        float(actual),
        float(expected),
        rel_tol=0.0,
        abs_tol=1e-9,
    ):
        raise SimulationReportingError(f"{field_name} does not reconcile")
