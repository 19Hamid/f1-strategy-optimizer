"""Observed-strategy replay and trajectory error measurement for Phase 7."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

import numpy as np
import pandas as pd

from app.baselines.metrics import RegressionMetrics, regression_metrics
from app.ml import APPROVED_FEATURE_COLUMNS
from app.simulation.contracts import (
    DEVELOPMENT_SEASONS,
    DryCompound,
    PlannedPitStop,
    SimulationContractError,
    SimulationMode,
    SimulationRequest,
)
from app.simulation.model_adapter import (
    Phase6ModelAdapter,
    SimulationFeatureContext,
)
from app.simulation.rollout import (
    StrategySimulationResult,
    simulate_strategy,
)


class ObservedReplayError(SimulationContractError):
    """Raised when historical replay evidence is invalid or inconsistent."""


_PROCESSED_REPLAY_COLUMNS = (
    "Season",
    "SessionType",
    "EventName",
    "Driver",
    "Team",
    "LapNumber",
    "LapTimeSeconds",
    "Compound",
    "PitInTime",
    "Rainfall",
    "TrackStatus",
    "IsEligible",
)

_DECISION_CONTEXT_COLUMNS = (
    "session_id",
    "season",
    "event_name",
    "driver",
    "team",
    "decision_lap",
    "is_decision_eligible",
    *APPROVED_FEATURE_COLUMNS,
)


class ReplayHorizon(StrEnum):
    """Stable remaining-lap groups for error-growth diagnostics."""

    SHORT = "SHORT_1_TO_10_LAPS"
    MEDIUM = "MEDIUM_11_TO_25_LAPS"
    LONG = "LONG_26_PLUS_LAPS"


@dataclass(frozen=True, slots=True)
class ObservedReplayLap:
    """One observed total lap time and any stop executed after that lap."""

    lap_number: int
    observed_total_lap_time_seconds: float
    pit_stop: PlannedPitStop | None = None

    def __post_init__(self) -> None:
        """Reject incomplete or contradictory historical lap evidence."""
        _integer(self.lap_number, "lap_number", minimum=1)
        object.__setattr__(
            self,
            "observed_total_lap_time_seconds",
            _positive(
                self.observed_total_lap_time_seconds,
                "observed_total_lap_time_seconds",
            ),
        )
        if self.pit_stop is not None:
            if not isinstance(self.pit_stop, PlannedPitStop):
                raise TypeError("pit_stop must be a PlannedPitStop or None")
            if self.pit_stop.after_lap != self.lap_number:
                raise ObservedReplayError(
                    "observed pit stop must occur after its recorded lap"
                )


@dataclass(frozen=True, slots=True)
class ObservedStrategyTrace:
    """Complete development-race outcome aligned to one rollout horizon."""

    season: int
    session_id: str
    event_name: str
    driver: str
    team: str
    start_lap: int
    total_laps: int
    laps: tuple[ObservedReplayLap, ...]

    def __post_init__(self) -> None:
        """Require a complete consecutive 2022–2024 historical trajectory."""
        _integer(self.season, "season", minimum=1950)
        if self.season not in DEVELOPMENT_SEASONS:
            raise ObservedReplayError(
                "observed replay is outside the development seasons"
            )
        for name in ("session_id", "event_name", "driver", "team"):
            _text(getattr(self, name), name)
        _integer(self.start_lap, "start_lap", minimum=1)
        _integer(self.total_laps, "total_laps", minimum=1)
        if self.start_lap > self.total_laps:
            raise ObservedReplayError("start_lap exceeds total_laps")
        if not isinstance(self.laps, tuple) or not self.laps:
            raise ObservedReplayError("laps must be a non-empty tuple")
        if any(not isinstance(lap, ObservedReplayLap) for lap in self.laps):
            raise ObservedReplayError(
                "every observed lap must be an ObservedReplayLap"
            )
        expected = tuple(range(self.start_lap, self.total_laps + 1))
        actual = tuple(lap.lap_number for lap in self.laps)
        if actual != expected:
            raise ObservedReplayError(
                "observed laps must cover the complete consecutive horizon"
            )
        if self.laps[-1].pit_stop is not None:
            raise ObservedReplayError(
                "observed strategy cannot stop after the final lap"
            )

    @property
    def pit_stops(self) -> tuple[PlannedPitStop, ...]:
        """Return the exact observed stops in chronological order."""
        return tuple(
            lap.pit_stop for lap in self.laps if lap.pit_stop is not None
        )

    @property
    def remaining_laps(self) -> int:
        """Return the evaluated trajectory length."""
        return len(self.laps)

    @property
    def observed_remaining_time_seconds(self) -> float:
        """Return observed total time across the replay horizon."""
        return math.fsum(
            lap.observed_total_lap_time_seconds for lap in self.laps
        )


@dataclass(frozen=True, slots=True)
class ReplayLapError:
    """Auditable lap and cumulative error at one replay checkpoint."""

    lap_number: int
    laps_remaining_after_lap: int
    predicted_racing_time_seconds: float
    applied_pit_loss_seconds: float
    predicted_total_lap_time_seconds: float
    observed_total_lap_time_seconds: float
    signed_lap_error_seconds: float
    cumulative_predicted_time_seconds: float
    cumulative_observed_time_seconds: float
    cumulative_signed_error_seconds: float

    def __post_init__(self) -> None:
        """Require every stored error identity to reconcile exactly."""
        _integer(self.lap_number, "lap_number", minimum=1)
        _integer(
            self.laps_remaining_after_lap,
            "laps_remaining_after_lap",
            minimum=0,
        )
        predicted_racing = _positive(
            self.predicted_racing_time_seconds,
            "predicted_racing_time_seconds",
        )
        pit_loss = _non_negative(
            self.applied_pit_loss_seconds,
            "applied_pit_loss_seconds",
        )
        predicted_total = _positive(
            self.predicted_total_lap_time_seconds,
            "predicted_total_lap_time_seconds",
        )
        observed_total = _positive(
            self.observed_total_lap_time_seconds,
            "observed_total_lap_time_seconds",
        )
        cumulative_predicted = _positive(
            self.cumulative_predicted_time_seconds,
            "cumulative_predicted_time_seconds",
        )
        cumulative_observed = _positive(
            self.cumulative_observed_time_seconds,
            "cumulative_observed_time_seconds",
        )
        _close(
            predicted_racing + pit_loss,
            predicted_total,
            "predicted lap total",
        )
        _close(
            predicted_total - observed_total,
            self.signed_lap_error_seconds,
            "signed lap error",
        )
        _close(
            cumulative_predicted - cumulative_observed,
            self.cumulative_signed_error_seconds,
            "cumulative signed error",
        )


@dataclass(frozen=True, slots=True)
class ObservedStrategyReplay:
    """One complete simulation aligned with its observed historical outcome."""

    simulation: StrategySimulationResult
    observed: ObservedStrategyTrace
    lap_errors: tuple[ReplayLapError, ...]

    def __post_init__(self) -> None:
        """Require complete one-to-one simulated and observed evidence."""
        if not isinstance(self.simulation, StrategySimulationResult):
            raise TypeError("simulation must be a StrategySimulationResult")
        if not isinstance(self.observed, ObservedStrategyTrace):
            raise TypeError("observed must be an ObservedStrategyTrace")
        if not isinstance(self.lap_errors, tuple) or not self.lap_errors:
            raise ObservedReplayError("lap_errors must be a non-empty tuple")
        if any(not isinstance(row, ReplayLapError) for row in self.lap_errors):
            raise ObservedReplayError(
                "every replay row must be a ReplayLapError"
            )
        request = self.simulation.request
        if request.mode is not SimulationMode.OBSERVED_STRATEGY_REPLAY:
            raise ObservedReplayError(
                "replay result requires OBSERVED_STRATEGY_REPLAY mode"
            )
        _verify_trace_identity(request, self.observed)
        if request.strategy.stops != self.observed.pit_stops:
            raise ObservedReplayError(
                "simulation stops differ from the observed strategy"
            )
        expected_numbers = tuple(
            lap.transition.lap_number for lap in self.simulation.laps
        )
        error_numbers = tuple(row.lap_number for row in self.lap_errors)
        observed_numbers = tuple(lap.lap_number for lap in self.observed.laps)
        if error_numbers != expected_numbers or error_numbers != observed_numbers:
            raise ObservedReplayError(
                "simulated, observed and scored lap identities differ"
            )
        if self.lap_errors[-1].laps_remaining_after_lap != 0:
            raise ObservedReplayError(
                "final replay row must have zero laps remaining"
            )
        predicted_elapsed = 0.0
        observed_elapsed = 0.0
        for index, (row, simulated_lap, observed_lap) in enumerate(
            zip(
                self.lap_errors,
                self.simulation.laps,
                self.observed.laps,
                strict=True,
            )
        ):
            if row.laps_remaining_after_lap != len(self.lap_errors) - index - 1:
                raise ObservedReplayError(
                    "replay rows contain an invalid remaining-lap count"
                )
            transition = simulated_lap.transition
            _close(
                row.predicted_racing_time_seconds,
                transition.predicted_lap_time_seconds,
                "scored racing-time prediction",
            )
            _close(
                row.applied_pit_loss_seconds,
                transition.pit_loss_seconds,
                "scored pit loss",
            )
            _close(
                row.predicted_total_lap_time_seconds,
                transition.total_lap_time_seconds,
                "scored total-lap prediction",
            )
            _close(
                row.observed_total_lap_time_seconds,
                observed_lap.observed_total_lap_time_seconds,
                "scored observed lap time",
            )
            predicted_elapsed += row.predicted_total_lap_time_seconds
            observed_elapsed += row.observed_total_lap_time_seconds
            _close(
                row.cumulative_predicted_time_seconds,
                predicted_elapsed,
                "cumulative predicted trajectory time",
            )
            _close(
                row.cumulative_observed_time_seconds,
                observed_elapsed,
                "cumulative observed trajectory time",
            )
        _close(
            self.lap_errors[-1].cumulative_predicted_time_seconds,
            self.simulation.remaining_time_seconds,
            "final predicted remaining time",
        )
        _close(
            self.lap_errors[-1].cumulative_observed_time_seconds,
            self.observed.observed_remaining_time_seconds,
            "final observed remaining time",
        )

    @property
    def replay_id(self) -> str:
        """Return a deterministic identity for aggregation and storage."""
        return (
            f"{self.observed.season}:{self.observed.session_id}:"
            f"{self.observed.driver}:{self.observed.team}:"
            f"{self.observed.start_lap}:"
            f"{self.simulation.strategy_id}"
        )

    @property
    def lap_metrics(self) -> RegressionMetrics:
        """Return pooled lap-level total-time errors for this trajectory."""
        return regression_metrics(
            np.asarray(
                [
                    row.observed_total_lap_time_seconds
                    for row in self.lap_errors
                ],
                dtype="float64",
            ),
            np.asarray(
                [
                    row.predicted_total_lap_time_seconds
                    for row in self.lap_errors
                ],
                dtype="float64",
            ),
        )

    @property
    def predicted_remaining_time_seconds(self) -> float:
        """Return predicted time from the replay start to the flag."""
        return self.simulation.remaining_time_seconds

    @property
    def observed_remaining_time_seconds(self) -> float:
        """Return observed time from the replay start to the flag."""
        return self.observed.observed_remaining_time_seconds

    @property
    def signed_remaining_time_error_seconds(self) -> float:
        """Return predicted minus observed finish-time error."""
        return (
            self.predicted_remaining_time_seconds
            - self.observed_remaining_time_seconds
        )

    @property
    def absolute_remaining_time_error_seconds(self) -> float:
        """Return absolute finish-time error."""
        return abs(self.signed_remaining_time_error_seconds)


@dataclass(frozen=True, slots=True)
class ReplaySliceMetrics:
    """Remaining-time accuracy for one stable start-horizon group."""

    horizon: ReplayHorizon
    replays: int
    metrics: RegressionMetrics

    def __post_init__(self) -> None:
        """Require one non-empty canonical replay slice."""
        if not isinstance(self.horizon, ReplayHorizon):
            raise TypeError("horizon must be a ReplayHorizon")
        _integer(self.replays, "replays", minimum=1)
        if not isinstance(self.metrics, RegressionMetrics):
            raise TypeError("metrics must be RegressionMetrics")


@dataclass(frozen=True, slots=True)
class ObservedReplayEvaluation:
    """Aggregate honest errors across distinct development-race replays."""

    replays: tuple[ObservedStrategyReplay, ...]

    def __post_init__(self) -> None:
        """Reject empty, malformed or duplicate replay populations."""
        if not isinstance(self.replays, tuple) or not self.replays:
            raise ObservedReplayError("replays must be a non-empty tuple")
        if any(
            not isinstance(replay, ObservedStrategyReplay)
            for replay in self.replays
        ):
            raise ObservedReplayError(
                "every replay must be an ObservedStrategyReplay"
            )
        identities = tuple(replay.replay_id for replay in self.replays)
        if len(identities) != len(set(identities)):
            raise ObservedReplayError("replay identities must be unique")

    @property
    def replay_count(self) -> int:
        """Return the number of complete historical trajectories."""
        return len(self.replays)

    @property
    def lap_count(self) -> int:
        """Return the number of aligned simulated and observed laps."""
        return sum(len(replay.lap_errors) for replay in self.replays)

    @property
    def lap_metrics(self) -> RegressionMetrics:
        """Return pooled total-lap-time errors across every trajectory."""
        actual, predicted = _lap_vectors(self.replays)
        return regression_metrics(actual, predicted)

    @property
    def remaining_time_metrics(self) -> RegressionMetrics:
        """Return finish-time errors with each replay weighted once."""
        actual, predicted = _remaining_time_vectors(self.replays)
        return regression_metrics(actual, predicted)

    @property
    def horizon_slices(self) -> tuple[ReplaySliceMetrics, ...]:
        """Report remaining-time error separately by trajectory length."""
        slices: list[ReplaySliceMetrics] = []
        for horizon in ReplayHorizon:
            selected = tuple(
                replay
                for replay in self.replays
                if _horizon(replay.observed.remaining_laps) is horizon
            )
            if not selected:
                continue
            actual, predicted = _remaining_time_vectors(selected)
            slices.append(
                ReplaySliceMetrics(
                    horizon=horizon,
                    replays=len(selected),
                    metrics=regression_metrics(actual, predicted),
                )
            )
        return tuple(slices)


def build_observed_strategy_trace(
    request: SimulationRequest,
    processed_laps: pd.DataFrame,
) -> ObservedStrategyTrace:
    """Build an exact dry, green replay trace from processed race laps."""
    if not isinstance(request, SimulationRequest):
        raise TypeError("request must be a SimulationRequest")
    _require_observed_mode(request)
    _require_frame_columns(
        processed_laps,
        _PROCESSED_REPLAY_COLUMNS,
        "processed_laps",
    )
    state = request.state
    selected = processed_laps.loc[
        _processed_identity_mask(processed_laps, request)
        & _integer_series(processed_laps["LapNumber"], "LapNumber").between(
            state.current_lap,
            state.total_laps,
        )
    ].copy()
    selected["LapNumber"] = _integer_series(
        selected["LapNumber"],
        "LapNumber",
    )
    selected = selected.sort_values("LapNumber", kind="stable")
    expected_laps = tuple(range(state.current_lap, state.total_laps + 1))
    actual_laps = tuple(selected["LapNumber"].tolist())
    if actual_laps != expected_laps:
        raise ObservedReplayError(
            "processed replay rows must cover the exact consecutive horizon"
        )
    if not all(
        _strict_flag(value, "Rainfall") is False
        for value in selected["Rainfall"]
    ):
        raise ObservedReplayError("observed replay must remain dry")
    if any(str(value).strip() != "1" for value in selected["TrackStatus"]):
        raise ObservedReplayError("observed replay must remain green")

    compounds = tuple(
        _dry_compound(value, "Compound") for value in selected["Compound"]
    )
    if compounds[0] is not state.current_compound:
        raise ObservedReplayError(
            "processed replay compound differs from the simulation state"
        )
    observed_times = tuple(
        _positive(value, "LapTimeSeconds")
        for value in selected["LapTimeSeconds"]
    )
    pit_laps = tuple(
        int(lap_number)
        for lap_number, pit_in_time in zip(
            selected["LapNumber"],
            selected["PitInTime"],
            strict=True,
        )
        if not pd.isna(pit_in_time)
    )
    expected_pit_laps = tuple(stop.after_lap for stop in request.strategy.stops)
    if pit_laps != expected_pit_laps:
        raise ObservedReplayError(
            "processed pit-in laps differ from the requested strategy"
        )
    stop_by_lap = {stop.after_lap: stop for stop in request.strategy.stops}
    compound_by_lap = dict(zip(actual_laps, compounds, strict=True))
    for stop in request.strategy.stops:
        if compound_by_lap[stop.after_lap + 1] is not stop.new_compound:
            raise ObservedReplayError(
                "processed post-stop compound differs from the requested strategy"
            )
    return ObservedStrategyTrace(
        season=state.season,
        session_id=state.session_id,
        event_name=state.event_name,
        driver=state.driver,
        team=state.team,
        start_lap=state.current_lap,
        total_laps=state.total_laps,
        laps=tuple(
            ObservedReplayLap(
                lap_number=lap_number,
                observed_total_lap_time_seconds=observed_time,
                pit_stop=stop_by_lap.get(lap_number),
            )
            for lap_number, observed_time in zip(
                actual_laps,
                observed_times,
                strict=True,
            )
        ),
    )


def build_observed_replay_context(
    request: SimulationRequest,
    decision_rows: pd.DataFrame,
    processed_laps: pd.DataFrame,
) -> SimulationFeatureContext:
    """Seed replay inference from one eligible decision and past-only laps."""
    if not isinstance(request, SimulationRequest):
        raise TypeError("request must be a SimulationRequest")
    _require_observed_mode(request)
    _require_frame_columns(
        decision_rows,
        _DECISION_CONTEXT_COLUMNS,
        "decision_rows",
    )
    _require_frame_columns(
        processed_laps,
        _PROCESSED_REPLAY_COLUMNS,
        "processed_laps",
    )
    state = request.state
    decision_laps = _integer_series(
        decision_rows["decision_lap"],
        "decision_lap",
    )
    selected = decision_rows.loc[
        (decision_rows["session_id"] == state.session_id)
        & (decision_rows["season"] == state.season)
        & (decision_rows["event_name"] == state.event_name)
        & (decision_rows["driver"] == state.driver)
        & (decision_rows["team"] == state.team)
        & (decision_laps == state.current_lap)
    ]
    if len(selected) != 1:
        raise ObservedReplayError(
            "replay context requires exactly one matching decision row"
        )
    row = selected.iloc[0]
    if not _strict_flag(
        row["is_decision_eligible"],
        "is_decision_eligible",
    ):
        raise ObservedReplayError("replay decision row must be eligible")

    processed_lap_numbers = _integer_series(
        processed_laps["LapNumber"],
        "LapNumber",
    )
    history = processed_laps.loc[
        _processed_identity_mask(processed_laps, request)
        & (processed_lap_numbers < state.current_lap)
    ].copy()
    history["LapNumber"] = _integer_series(history["LapNumber"], "LapNumber")
    history = history.sort_values("LapNumber", kind="stable")
    if history["LapNumber"].duplicated().any():
        raise ObservedReplayError(
            "processed lap history contains duplicate lap identities"
        )
    eligible_history = history.loc[
        [
            _strict_flag(value, "IsEligible")
            for value in history["IsEligible"]
        ]
    ]
    recent_lap_times = tuple(
        _positive(value, "historical LapTimeSeconds")
        for value in eligible_history["LapTimeSeconds"].tail(5)
    )
    return SimulationFeatureContext(
        base_features=(
            selected.loc[:, APPROVED_FEATURE_COLUMNS]
            .copy(deep=True)
            .reset_index(drop=True)
        ),
        recent_lap_times_seconds=recent_lap_times,
    )


def replay_observed_strategy(
    request: SimulationRequest,
    *,
    context: SimulationFeatureContext,
    adapter: Phase6ModelAdapter,
    observed: ObservedStrategyTrace,
) -> ObservedStrategyReplay:
    """Run one observed plan and score every lap and the time to the flag."""
    if not isinstance(request, SimulationRequest):
        raise TypeError("request must be a SimulationRequest")
    if not isinstance(observed, ObservedStrategyTrace):
        raise TypeError("observed must be an ObservedStrategyTrace")
    if request.mode is not SimulationMode.OBSERVED_STRATEGY_REPLAY:
        raise ObservedReplayError(
            "observed replay requires OBSERVED_STRATEGY_REPLAY mode"
        )
    _verify_trace_identity(request, observed)
    if request.strategy.stops != observed.pit_stops:
        raise ObservedReplayError(
            "requested stops differ from the observed strategy"
        )

    simulation = simulate_strategy(
        request,
        context=context,
        adapter=adapter,
    )
    predicted_elapsed = 0.0
    observed_elapsed = 0.0
    errors: list[ReplayLapError] = []
    for index, (simulated_lap, observed_lap) in enumerate(
        zip(simulation.laps, observed.laps, strict=True)
    ):
        transition = simulated_lap.transition
        predicted_elapsed += transition.total_lap_time_seconds
        observed_elapsed += observed_lap.observed_total_lap_time_seconds
        errors.append(
            ReplayLapError(
                lap_number=transition.lap_number,
                laps_remaining_after_lap=len(observed.laps) - index - 1,
                predicted_racing_time_seconds=(
                    transition.predicted_lap_time_seconds
                ),
                applied_pit_loss_seconds=transition.pit_loss_seconds,
                predicted_total_lap_time_seconds=(
                    transition.total_lap_time_seconds
                ),
                observed_total_lap_time_seconds=(
                    observed_lap.observed_total_lap_time_seconds
                ),
                signed_lap_error_seconds=(
                    transition.total_lap_time_seconds
                    - observed_lap.observed_total_lap_time_seconds
                ),
                cumulative_predicted_time_seconds=predicted_elapsed,
                cumulative_observed_time_seconds=observed_elapsed,
                cumulative_signed_error_seconds=(
                    predicted_elapsed - observed_elapsed
                ),
            )
        )
    return ObservedStrategyReplay(
        simulation=simulation,
        observed=observed,
        lap_errors=tuple(errors),
    )


def _require_frame_columns(
    frame: object,
    required: tuple[str, ...],
    field_name: str,
) -> None:
    if not isinstance(frame, pd.DataFrame):
        raise TypeError(f"{field_name} must be a pandas DataFrame")
    missing = sorted(set(required).difference(frame.columns))
    if missing:
        raise ObservedReplayError(
            f"{field_name} is missing required columns: {', '.join(missing)}"
        )


def _require_observed_mode(request: SimulationRequest) -> None:
    if request.mode is not SimulationMode.OBSERVED_STRATEGY_REPLAY:
        raise ObservedReplayError(
            "observed replay requires OBSERVED_STRATEGY_REPLAY mode"
        )


def _processed_identity_mask(
    processed_laps: pd.DataFrame,
    request: SimulationRequest,
) -> pd.Series:
    state = request.state
    return (
        (processed_laps["Season"] == state.season)
        & (processed_laps["SessionType"] == "R")
        & (processed_laps["EventName"] == state.event_name)
        & (processed_laps["Driver"] == state.driver)
        & (processed_laps["Team"] == state.team)
    )


def _integer_series(values: pd.Series, field_name: str) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.isna().any() or not np.isfinite(numeric.to_numpy()).all():
        raise ObservedReplayError(f"{field_name} must contain finite integers")
    if not np.equal(numeric.to_numpy() % 1, 0).all():
        raise ObservedReplayError(f"{field_name} must contain finite integers")
    return numeric.astype("int64")


def _strict_flag(value: object, field_name: str) -> bool:
    if not isinstance(value, (bool, np.bool_)):
        raise ObservedReplayError(f"{field_name} must contain booleans")
    return bool(value)


def _dry_compound(value: object, field_name: str) -> DryCompound:
    try:
        return DryCompound(str(value).strip().upper())
    except ValueError as error:
        raise ObservedReplayError(
            f"{field_name} contains an unsupported dry compound: {value!r}"
        ) from error


def _verify_trace_identity(
    request: SimulationRequest,
    observed: ObservedStrategyTrace,
) -> None:
    state = request.state
    identities = (
        ("season", state.season, observed.season),
        ("session_id", state.session_id, observed.session_id),
        ("event_name", state.event_name, observed.event_name),
        ("driver", state.driver, observed.driver),
        ("team", state.team, observed.team),
        ("start_lap", state.current_lap, observed.start_lap),
        ("total_laps", state.total_laps, observed.total_laps),
    )
    mismatches = [
        name for name, actual, expected in identities if actual != expected
    ]
    if mismatches:
        raise ObservedReplayError(
            "request and observed trace differ: " + ", ".join(mismatches)
        )


def _lap_vectors(
    replays: tuple[ObservedStrategyReplay, ...],
) -> tuple[np.ndarray, np.ndarray]:
    actual = np.asarray(
        [
            row.observed_total_lap_time_seconds
            for replay in replays
            for row in replay.lap_errors
        ],
        dtype="float64",
    )
    predicted = np.asarray(
        [
            row.predicted_total_lap_time_seconds
            for replay in replays
            for row in replay.lap_errors
        ],
        dtype="float64",
    )
    return actual, predicted


def _remaining_time_vectors(
    replays: tuple[ObservedStrategyReplay, ...],
) -> tuple[np.ndarray, np.ndarray]:
    actual = np.asarray(
        [replay.observed_remaining_time_seconds for replay in replays],
        dtype="float64",
    )
    predicted = np.asarray(
        [replay.predicted_remaining_time_seconds for replay in replays],
        dtype="float64",
    )
    return actual, predicted


def _horizon(remaining_laps: int) -> ReplayHorizon:
    if remaining_laps <= 10:
        return ReplayHorizon.SHORT
    if remaining_laps <= 25:
        return ReplayHorizon.MEDIUM
    return ReplayHorizon.LONG


def _integer(
    value: object,
    field_name: str,
    *,
    minimum: int,
) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ObservedReplayError(f"{field_name} must be an integer")
    if value < minimum:
        raise ObservedReplayError(
            f"{field_name} must be at least {minimum}"
        )


def _text(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ObservedReplayError(f"{field_name} must not be blank")


def _positive(value: object, field_name: str) -> float:
    normalized = _number(value, field_name)
    if normalized <= 0:
        raise ObservedReplayError(f"{field_name} must be positive")
    return normalized


def _non_negative(value: object, field_name: str) -> float:
    normalized = _number(value, field_name)
    if normalized < 0:
        raise ObservedReplayError(f"{field_name} must be non-negative")
    return normalized


def _number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(
        value,
        (int, float, np.integer, np.floating),
    ):
        raise ObservedReplayError(f"{field_name} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ObservedReplayError(f"{field_name} must be finite")
    return normalized


def _close(actual: object, expected: object, field_name: str) -> None:
    actual_number = _number(actual, field_name)
    expected_number = _number(expected, field_name)
    if not math.isclose(
        actual_number,
        expected_number,
        rel_tol=0.0,
        abs_tol=1e-9,
    ):
        raise ObservedReplayError(f"{field_name} does not reconcile")
