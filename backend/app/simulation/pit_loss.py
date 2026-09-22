"""Circuit-aware explicit pit-loss sensitivity for Phase 7."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from enum import StrEnum

from app.datasets.contracts import DEVELOPMENT_SEASONS
from app.simulation.contracts import (
    PROTECTED_EVALUATION_SEASON,
    PitLossAssumption,
    PitLossSource,
    SimulationContractError,
    SimulationRequest,
)


class PitLossError(SimulationContractError):
    """Raised when circuit pit-loss evidence or resolution is invalid."""


class PitLossScenario(StrEnum):
    """Ordered deterministic sensitivity cases around one circuit estimate."""

    LOW = "LOW"
    NOMINAL = "NOMINAL"
    HIGH = "HIGH"


@dataclass(frozen=True, slots=True)
class CircuitPitLossProfile:
    """Explicit counterfactual pit costs for one circuit identity."""

    event_name: str
    low_seconds: float
    nominal_seconds: float
    high_seconds: float
    source: PitLossSource
    evidence: str
    training_seasons: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        """Require ordered costs and honest source provenance."""
        event_name = _text(self.event_name, "event_name")
        evidence = _text(self.evidence, "evidence")
        low = _finite_non_negative(self.low_seconds, "low_seconds")
        nominal = _finite_non_negative(
            self.nominal_seconds,
            "nominal_seconds",
        )
        high = _finite_non_negative(self.high_seconds, "high_seconds")
        if not low <= nominal <= high:
            raise PitLossError(
                "pit-loss seconds must satisfy low <= nominal <= high"
            )
        try:
            source = PitLossSource(self.source)
        except (TypeError, ValueError) as error:
            raise PitLossError(
                f"unsupported pit-loss source: {self.source!r}"
            ) from error
        seasons = _training_seasons(self.training_seasons)
        if source == PitLossSource.TRAINING_ONLY_CIRCUIT_ESTIMATE:
            if not seasons:
                raise PitLossError(
                    "training-only circuit estimate requires training seasons"
                )
        elif seasons:
            raise PitLossError(
                "explicit assumption must not claim training seasons"
            )
        object.__setattr__(self, "event_name", event_name)
        object.__setattr__(self, "low_seconds", low)
        object.__setattr__(self, "nominal_seconds", nominal)
        object.__setattr__(self, "high_seconds", high)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "evidence", evidence)
        object.__setattr__(self, "training_seasons", seasons)

    def seconds_for(self, scenario: PitLossScenario | str) -> float:
        """Return the declared seconds for one sensitivity scenario."""
        normalized = _scenario(scenario)
        return {
            PitLossScenario.LOW: self.low_seconds,
            PitLossScenario.NOMINAL: self.nominal_seconds,
            PitLossScenario.HIGH: self.high_seconds,
        }[normalized]


@dataclass(frozen=True, slots=True)
class PitLossResolution:
    """Auditable circuit and sensitivity identity used by one request."""

    event_name: str
    scenario: PitLossScenario
    assumption: PitLossAssumption
    training_seasons: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class PitLossRegistry:
    """Exact circuit profiles with no silent global fallback."""

    profiles: tuple[CircuitPitLossProfile, ...]

    def __post_init__(self) -> None:
        """Reject mutable, empty or ambiguous circuit configuration."""
        if not isinstance(self.profiles, tuple):
            raise PitLossError("profiles must be a tuple")
        if not self.profiles:
            raise PitLossError("profiles must not be empty")
        if any(
            not isinstance(profile, CircuitPitLossProfile)
            for profile in self.profiles
        ):
            raise PitLossError(
                "every profile must be a CircuitPitLossProfile"
            )
        identities = tuple(
            profile.event_name.casefold() for profile in self.profiles
        )
        if len(identities) != len(set(identities)):
            raise PitLossError("circuit pit-loss profiles must be unique")

    def resolve(
        self,
        *,
        event_name: str,
        scenario: PitLossScenario | str,
    ) -> PitLossResolution:
        """Resolve one exact event and expose all supporting evidence."""
        requested_event = _text(event_name, "event_name")
        normalized_scenario = _scenario(scenario)
        profile = next(
            (
                candidate
                for candidate in self.profiles
                if candidate.event_name.casefold()
                == requested_event.casefold()
            ),
            None,
        )
        if profile is None:
            raise PitLossError(
                f"no circuit pit-loss profile for {requested_event!r}"
            )
        seconds = profile.seconds_for(normalized_scenario)
        evidence = (
            f"{profile.evidence}; event={profile.event_name}; "
            f"scenario={normalized_scenario.value}; "
            f"range_seconds={profile.low_seconds:.6f}/"
            f"{profile.nominal_seconds:.6f}/{profile.high_seconds:.6f}"
        )
        return PitLossResolution(
            event_name=profile.event_name,
            scenario=normalized_scenario,
            assumption=PitLossAssumption(
                seconds=seconds,
                source=profile.source,
                evidence=evidence,
            ),
            training_seasons=profile.training_seasons,
        )


def apply_pit_loss_scenario(
    request: SimulationRequest,
    *,
    registry: PitLossRegistry,
    scenario: PitLossScenario | str,
) -> tuple[SimulationRequest, PitLossResolution]:
    """Return an immutable request carrying its resolved circuit assumption."""
    if not isinstance(request, SimulationRequest):
        raise TypeError("request must be a SimulationRequest")
    if not isinstance(registry, PitLossRegistry):
        raise TypeError("registry must be a PitLossRegistry")
    resolution = registry.resolve(
        event_name=request.state.event_name,
        scenario=scenario,
    )
    return (
        replace(request, pit_loss=resolution.assumption),
        resolution,
    )


def _training_seasons(values: object) -> tuple[int, ...]:
    if not isinstance(values, tuple):
        raise PitLossError("training_seasons must be a tuple")
    if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
        raise PitLossError("training_seasons must contain integers")
    if tuple(sorted(set(values))) != values:
        raise PitLossError("training_seasons must be canonical")
    if PROTECTED_EVALUATION_SEASON in values:
        raise PitLossError(
            "protected 2025 cannot enter pit-loss calibration"
        )
    unknown = set(values).difference(DEVELOPMENT_SEASONS)
    if unknown:
        raise PitLossError(
            f"pit-loss calibration contains unknown seasons: {sorted(unknown)}"
        )
    return values


def _scenario(value: object) -> PitLossScenario:
    try:
        return PitLossScenario(value)
    except (TypeError, ValueError) as error:
        raise PitLossError(
            f"unsupported pit-loss scenario: {value!r}"
        ) from error


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PitLossError(f"{field_name} must not be blank")
    return value.strip()


def _finite_non_negative(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PitLossError(f"{field_name} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0:
        raise PitLossError(
            f"{field_name} must be finite and non-negative"
        )
    return normalized
