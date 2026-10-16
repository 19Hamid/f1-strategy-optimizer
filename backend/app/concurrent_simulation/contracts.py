"""Frozen contracts for paired Phase 9 uncertainty scenarios."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

from app.optimizer.contracts import PitDecisionRequest
from app.simulation.contracts import SIMULATION_RANDOM_SEED

CONCURRENT_SIMULATION_CONTRACT_VERSION: Final = "1.0"
SCENARIO_GENERATOR_ID: Final = "sha256-box-muller-standard-normal-v1"
DEFAULT_SCENARIO_COUNT: Final = 10_000
MAXIMUM_SCENARIO_COUNT: Final = 100_000
_MAXIMUM_ROOT_SEED: Final = 2**32 - 1
_MAXIMUM_SCENARIO_SEED: Final = 2**64 - 1


class ConcurrentSimulationContractError(ValueError):
    """Raised when a Phase 9 scenario batch violates its frozen contract."""


@dataclass(frozen=True, slots=True)
class ScenarioBatchRequest:
    """One deterministic request for paired uncertainty scenario draws."""

    decision_request: PitDecisionRequest
    scenario_count: int = DEFAULT_SCENARIO_COUNT
    root_seed: int = SIMULATION_RANDOM_SEED

    def __post_init__(self) -> None:
        """Require a verified Phase 8 decision and a bounded batch identity."""
        if not isinstance(self.decision_request, PitDecisionRequest):
            raise TypeError("decision_request must be a PitDecisionRequest")
        _integer_between(
            self.scenario_count,
            "scenario_count",
            minimum=1,
            maximum=MAXIMUM_SCENARIO_COUNT,
        )
        _integer_between(
            self.root_seed,
            "root_seed",
            minimum=0,
            maximum=_MAXIMUM_ROOT_SEED,
        )

    @property
    def lap_numbers(self) -> tuple[int, ...]:
        """Return the shared absolute-lap coordinates for both actions."""
        state = self.decision_request.state
        return tuple(range(state.current_lap, state.total_laps + 1))


@dataclass(frozen=True, slots=True)
class UncertaintyScenario:
    """Standardized shared draws for one paired pit-now/stay-out world."""

    scenario_index: int
    scenario_seed: int
    shared_pace_z: float
    pit_loss_z: float
    lap_time_residual_z: tuple[tuple[int, float], ...]

    def __post_init__(self) -> None:
        """Reject incomplete, non-finite or non-canonical scenario evidence."""
        _integer_between(
            self.scenario_index,
            "scenario_index",
            minimum=0,
            maximum=MAXIMUM_SCENARIO_COUNT - 1,
        )
        _integer_between(
            self.scenario_seed,
            "scenario_seed",
            minimum=0,
            maximum=_MAXIMUM_SCENARIO_SEED,
        )
        _finite(self.shared_pace_z, "shared_pace_z")
        _finite(self.pit_loss_z, "pit_loss_z")
        if not isinstance(self.lap_time_residual_z, tuple):
            raise ConcurrentSimulationContractError(
                "lap_time_residual_z must be a tuple"
            )
        if not self.lap_time_residual_z:
            raise ConcurrentSimulationContractError(
                "lap_time_residual_z must not be empty"
            )
        if any(
            not isinstance(item, tuple) or len(item) != 2
            for item in self.lap_time_residual_z
        ):
            raise ConcurrentSimulationContractError(
                "lap_time_residual_z entries must be (lap, z) tuples"
            )
        laps: list[int] = []
        for lap_number, z_score in self.lap_time_residual_z:
            _integer_at_least(
                lap_number,
                "lap_time_residual_z lap",
                minimum=1,
            )
            _finite(z_score, "lap_time_residual_z value")
            laps.append(lap_number)
        if tuple(laps) != tuple(range(laps[0], laps[-1] + 1)):
            raise ConcurrentSimulationContractError(
                "lap_time_residual_z laps must be unique and contiguous"
            )

    @property
    def lap_numbers(self) -> tuple[int, ...]:
        """Return the absolute laps addressed by the residual draws."""
        return tuple(lap for lap, _ in self.lap_time_residual_z)

    def lap_time_z_for(self, lap_number: int) -> float:
        """Return the standardized residual for one absolute race lap."""
        _integer_at_least(
            lap_number,
            "lap_number",
            minimum=1,
        )
        for candidate, z_score in self.lap_time_residual_z:
            if candidate == lap_number:
                return z_score
        raise ConcurrentSimulationContractError(
            f"scenario has no residual draw for lap {lap_number}"
        )


@dataclass(frozen=True, slots=True)
class ScenarioBatch:
    """A reconciled deterministic set of paired standardized scenarios."""

    request: ScenarioBatchRequest
    generator_id: str
    scenarios: tuple[UncertaintyScenario, ...]

    def __post_init__(self) -> None:
        """Prove batch count, order, horizon and seed uniqueness."""
        if not isinstance(self.request, ScenarioBatchRequest):
            raise TypeError("request must be a ScenarioBatchRequest")
        if self.generator_id != SCENARIO_GENERATOR_ID:
            raise ConcurrentSimulationContractError(
                "scenario generator differs from the frozen contract"
            )
        if not isinstance(self.scenarios, tuple):
            raise ConcurrentSimulationContractError("scenarios must be a tuple")
        if len(self.scenarios) != self.request.scenario_count:
            raise ConcurrentSimulationContractError(
                "scenario count differs from the batch request"
            )
        if any(
            not isinstance(scenario, UncertaintyScenario)
            for scenario in self.scenarios
        ):
            raise ConcurrentSimulationContractError(
                "every scenario must be an UncertaintyScenario"
            )
        if tuple(
            scenario.scenario_index for scenario in self.scenarios
        ) != tuple(range(self.request.scenario_count)):
            raise ConcurrentSimulationContractError(
                "scenario indices must be contiguous and ordered"
            )
        seeds = tuple(scenario.scenario_seed for scenario in self.scenarios)
        if len(seeds) != len(set(seeds)):
            raise ConcurrentSimulationContractError(
                "scenario seeds must be unique within a batch"
            )
        if any(
            scenario.lap_numbers != self.request.lap_numbers
            for scenario in self.scenarios
        ):
            raise ConcurrentSimulationContractError(
                "scenario lap coordinates differ from the decision horizon"
            )

    def scenario_for(self, scenario_index: int) -> UncertaintyScenario:
        """Return one scenario by its stable zero-based identity."""
        _integer_between(
            scenario_index,
            "scenario_index",
            minimum=0,
            maximum=self.request.scenario_count - 1,
        )
        return self.scenarios[scenario_index]


def validate_concurrent_simulation_contract() -> None:
    """Assert stable Phase 9 identities used by future execution layers."""
    if CONCURRENT_SIMULATION_CONTRACT_VERSION != "1.0":
        raise ConcurrentSimulationContractError(
            "concurrent simulation contract version changed"
        )
    if SCENARIO_GENERATOR_ID != "sha256-box-muller-standard-normal-v1":
        raise ConcurrentSimulationContractError("scenario generator changed")
    if DEFAULT_SCENARIO_COUNT != 10_000:
        raise ConcurrentSimulationContractError(
            "default scenario benchmark count changed"
        )
    if MAXIMUM_SCENARIO_COUNT < DEFAULT_SCENARIO_COUNT:
        raise ConcurrentSimulationContractError(
            "maximum scenario count is below the benchmark target"
        )


def _integer_between(
    value: object,
    field_name: str,
    *,
    minimum: int,
    maximum: int,
) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < minimum
        or value > maximum
    ):
        raise ConcurrentSimulationContractError(
            f"{field_name} must be an integer between {minimum} and {maximum}"
        )


def _finite(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConcurrentSimulationContractError(f"{field_name} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ConcurrentSimulationContractError(
            f"{field_name} must be finite"
        )
    return normalized


def _integer_at_least(
    value: object,
    field_name: str,
    *,
    minimum: int,
) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ConcurrentSimulationContractError(
            f"{field_name} must be an integer of at least {minimum}"
        )
