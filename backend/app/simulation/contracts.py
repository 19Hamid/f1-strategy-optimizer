"""Frozen contracts for the controlled Phase 7 race simulator."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

SIMULATION_CONTRACT_VERSION: Final = "1.2"
SIMULATION_RANDOM_SEED: Final = 42
DEVELOPMENT_SEASONS: Final = (2022, 2023, 2024)
PROTECTED_EVALUATION_SEASON: Final = 2025
MINIMUM_DRY_COMPOUNDS_PER_RACE: Final = 2


class SimulationContractError(ValueError):
    """Raised when a simulation request violates the frozen V1 contract."""


class DryCompound(StrEnum):
    """Supported slick tyre compounds for the controlled dry-race scope."""

    SOFT = "SOFT"
    MEDIUM = "MEDIUM"
    HARD = "HARD"


class SimulationMode(StrEnum):
    """Supported purposes for a deterministic Phase 7 rollout."""

    OBSERVED_STRATEGY_REPLAY = "OBSERVED_STRATEGY_REPLAY"
    COUNTERFACTUAL_STRATEGY = "COUNTERFACTUAL_STRATEGY"


class PitLossSource(StrEnum):
    """Defensible sources for an explicit additive pit-loss assumption."""

    EXPLICIT_ASSUMPTION = "EXPLICIT_ASSUMPTION"
    TRAINING_ONLY_CIRCUIT_ESTIMATE = "TRAINING_ONLY_CIRCUIT_ESTIMATE"


@dataclass(frozen=True, slots=True)
class RaceState:
    """Information known at the start of the current simulated lap."""

    season: int
    session_id: str
    event_name: str
    driver: str
    team: str
    current_lap: int
    total_laps: int
    current_compound: DryCompound
    tyre_age_laps: int
    current_stint_laps_completed: int
    completed_pit_stops: int
    compounds_used: tuple[DryCompound, ...]
    previous_position: int | None = None

    def __post_init__(self) -> None:
        """Normalize enum values and fail closed on impossible race state."""
        _require_development_season(self.season)
        for field_name in ("session_id", "event_name", "driver", "team"):
            _require_text(getattr(self, field_name), field_name)
        _require_integer(self.current_lap, "current_lap", minimum=1)
        _require_integer(self.total_laps, "total_laps", minimum=1)
        if self.current_lap > self.total_laps:
            raise SimulationContractError(
                "current_lap must not exceed total_laps"
            )
        _require_integer(self.tyre_age_laps, "tyre_age_laps", minimum=0)
        _require_integer(
            self.current_stint_laps_completed,
            "current_stint_laps_completed",
            minimum=0,
        )
        _require_integer(
            self.completed_pit_stops,
            "completed_pit_stops",
            minimum=0,
        )
        if self.previous_position is not None:
            _require_integer(
                self.previous_position,
                "previous_position",
                minimum=1,
                maximum=20,
            )

        compound = _compound(self.current_compound, "current_compound")
        compounds_used = tuple(
            _compound(value, "compounds_used") for value in self.compounds_used
        )
        if not compounds_used:
            raise SimulationContractError("compounds_used must not be empty")
        if compound not in compounds_used:
            raise SimulationContractError(
                "current_compound must appear in compounds_used"
            )
        object.__setattr__(self, "current_compound", compound)
        object.__setattr__(self, "compounds_used", compounds_used)


@dataclass(frozen=True, slots=True)
class PlannedPitStop:
    """One tyre change performed after completing a specified lap."""

    after_lap: int
    new_compound: DryCompound

    def __post_init__(self) -> None:
        """Normalize the compound and reject impossible lap identities."""
        _require_integer(self.after_lap, "after_lap", minimum=1)
        object.__setattr__(
            self,
            "new_compound",
            _compound(self.new_compound, "new_compound"),
        )


@dataclass(frozen=True, slots=True)
class StrategyPlan:
    """A complete remaining-race pit schedule, not an optimized decision."""

    strategy_id: str
    stops: tuple[PlannedPitStop, ...] = ()

    def __post_init__(self) -> None:
        """Require a canonical, deterministic stop order."""
        _require_text(self.strategy_id, "strategy_id")
        if not isinstance(self.stops, tuple):
            raise SimulationContractError("stops must be a tuple")
        if any(not isinstance(stop, PlannedPitStop) for stop in self.stops):
            raise SimulationContractError(
                "every strategy stop must be a PlannedPitStop"
            )
        laps = tuple(stop.after_lap for stop in self.stops)
        if laps != tuple(sorted(laps)):
            raise SimulationContractError(
                "planned pit stops must be sorted by after_lap"
            )
        if len(laps) != len(set(laps)):
            raise SimulationContractError(
                "planned pit stops must use unique lap numbers"
            )

    def validate_for(self, state: RaceState) -> None:
        """Validate every stop against the requested remaining-race horizon."""
        if not isinstance(state, RaceState):
            raise TypeError("state must be a RaceState")
        for stop in self.stops:
            if stop.after_lap < state.current_lap:
                raise SimulationContractError(
                    "planned pit stop precedes the current lap"
                )
            if stop.after_lap >= state.total_laps:
                raise SimulationContractError(
                    "planned pit stop must occur before the final lap"
                )


@dataclass(frozen=True, slots=True)
class PitLossAssumption:
    """An explicit additive pit cost kept distinct from observed duration."""

    seconds: float
    source: PitLossSource
    evidence: str

    def __post_init__(self) -> None:
        """Normalize the source and reject hidden or invalid assumptions."""
        seconds = _finite_non_negative(self.seconds, "pit loss seconds")
        try:
            source = PitLossSource(self.source)
        except (TypeError, ValueError) as error:
            raise SimulationContractError(
                f"unsupported pit loss source: {self.source!r}"
            ) from error
        _require_text(self.evidence, "pit loss evidence")
        object.__setattr__(self, "seconds", seconds)
        object.__setattr__(self, "source", source)


@dataclass(frozen=True, slots=True)
class SimulationRequest:
    """Complete deterministic input for one controlled strategy rollout."""

    state: RaceState
    strategy: StrategyPlan
    pit_loss: PitLossAssumption
    mode: SimulationMode
    random_seed: int = SIMULATION_RANDOM_SEED

    def __post_init__(self) -> None:
        """Validate scope, horizon, tyre rule and deterministic seed."""
        if not isinstance(self.state, RaceState):
            raise TypeError("state must be a RaceState")
        if not isinstance(self.strategy, StrategyPlan):
            raise TypeError("strategy must be a StrategyPlan")
        if not isinstance(self.pit_loss, PitLossAssumption):
            raise TypeError("pit_loss must be a PitLossAssumption")
        try:
            mode = SimulationMode(self.mode)
        except (TypeError, ValueError) as error:
            raise SimulationContractError(
                f"unsupported simulation mode: {self.mode!r}"
            ) from error
        _require_integer(
            self.random_seed,
            "random_seed",
            minimum=0,
            maximum=2**32 - 1,
        )
        self.strategy.validate_for(self.state)
        final_compounds = {
            *self.state.compounds_used,
            *(stop.new_compound for stop in self.strategy.stops),
        }
        if len(final_compounds) < MINIMUM_DRY_COMPOUNDS_PER_RACE:
            raise SimulationContractError(
                "complete dry-race strategy must use at least two compounds"
            )
        object.__setattr__(self, "mode", mode)


def validate_simulation_contract() -> None:
    """Assert the stable V1 identities used by downstream simulator code."""
    if DEVELOPMENT_SEASONS != (2022, 2023, 2024):
        raise SimulationContractError("development seasons changed")
    if PROTECTED_EVALUATION_SEASON in DEVELOPMENT_SEASONS:
        raise SimulationContractError(
            "protected evaluation season entered development scope"
        )
    if set(DryCompound) != {
        DryCompound.SOFT,
        DryCompound.MEDIUM,
        DryCompound.HARD,
    }:
        raise SimulationContractError("dry compound scope changed")
    if set(PitLossSource) != {
        PitLossSource.EXPLICIT_ASSUMPTION,
        PitLossSource.TRAINING_ONLY_CIRCUIT_ESTIMATE,
    }:
        raise SimulationContractError("pit loss source scope changed")


def _require_development_season(season: object) -> None:
    _require_integer(season, "season", minimum=1950)
    if season == PROTECTED_EVALUATION_SEASON:
        raise SimulationContractError(
            "protected 2025 data is forbidden during simulator development"
        )
    if season not in DEVELOPMENT_SEASONS:
        raise SimulationContractError(
            f"season is outside the Phase 7 development scope: {season}"
        )


def _require_integer(
    value: object,
    field_name: str,
    *,
    minimum: int,
    maximum: int | None = None,
) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SimulationContractError(f"{field_name} must be an integer")
    if value < minimum or (maximum is not None and value > maximum):
        if maximum is None:
            requirement = f"at least {minimum}"
        else:
            requirement = f"between {minimum} and {maximum}"
        raise SimulationContractError(
            f"{field_name} must be {requirement}"
        )


def _require_text(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise SimulationContractError(f"{field_name} must not be blank")


def _compound(value: object, field_name: str) -> DryCompound:
    try:
        return DryCompound(value)
    except (TypeError, ValueError) as error:
        raise SimulationContractError(
            f"{field_name} contains an unsupported dry compound: {value!r}"
        ) from error


def _finite_non_negative(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SimulationContractError(f"{field_name} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0:
        raise SimulationContractError(
            f"{field_name} must be finite and non-negative"
        )
    return normalized
