"""Development-only uncertainty-scale calibration for Phase 9."""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from statistics import fmean, pstdev
from typing import Final

from app.concurrent_simulation.contracts import ConcurrentSimulationContractError
from app.simulation import DEVELOPMENT_SEASONS, PROTECTED_EVALUATION_SEASON

UNCERTAINTY_CALIBRATION_METHOD_ID: Final = (
    "development-replay-decomposition-and-pit-range-v1"
)


@dataclass(frozen=True, slots=True)
class ReplayLapErrorObservation:
    """One signed observed-minus-predicted lap error from a development replay."""

    season: int
    replay_id: str
    lap_number: int
    signed_error_seconds: float

    def __post_init__(self) -> None:
        _development_season(self.season)
        _text(self.replay_id, "replay_id")
        _integer_at_least(self.lap_number, "lap_number", 1)
        _finite(self.signed_error_seconds, "signed_error_seconds")


@dataclass(frozen=True, slots=True)
class PitLossRangeObservation:
    """One development-only low/nominal/high circuit pit-loss profile."""

    season: int
    event_name: str
    low_seconds: float
    nominal_seconds: float
    high_seconds: float

    def __post_init__(self) -> None:
        _development_season(self.season)
        _text(self.event_name, "event_name")
        low = _non_negative(self.low_seconds, "low_seconds")
        nominal = _non_negative(self.nominal_seconds, "nominal_seconds")
        high = _non_negative(self.high_seconds, "high_seconds")
        if not low <= nominal <= high:
            raise ConcurrentSimulationContractError(
                "pit-loss range must satisfy low <= nominal <= high"
            )


@dataclass(frozen=True, slots=True)
class UncertaintyCalibration:
    """Auditable conversion from standardized coordinates to seconds."""

    calibration_id: str
    method_id: str
    training_seasons: tuple[int, ...]
    shared_pace_scale_seconds: float
    pit_loss_scale_seconds: float
    lap_time_residual_scale_seconds: float
    replay_count: int
    lap_count: int
    pit_loss_profile_count: int
    evidence: str

    def __post_init__(self) -> None:
        _text(self.calibration_id, "calibration_id")
        if self.method_id != UNCERTAINTY_CALIBRATION_METHOD_ID:
            raise ConcurrentSimulationContractError(
                "uncertainty calibration method differs from the frozen contract"
            )
        if not isinstance(self.training_seasons, tuple):
            raise ConcurrentSimulationContractError(
                "training_seasons must be a tuple"
            )
        if tuple(sorted(set(self.training_seasons))) != self.training_seasons:
            raise ConcurrentSimulationContractError(
                "training_seasons must be unique and ordered"
            )
        if not self.training_seasons:
            raise ConcurrentSimulationContractError(
                "training_seasons must not be empty"
            )
        for season in self.training_seasons:
            _development_season(season)
        _positive(
            self.shared_pace_scale_seconds,
            "shared_pace_scale_seconds",
        )
        _positive(self.pit_loss_scale_seconds, "pit_loss_scale_seconds")
        _positive(
            self.lap_time_residual_scale_seconds,
            "lap_time_residual_scale_seconds",
        )
        _integer_at_least(self.replay_count, "replay_count", 2)
        _integer_at_least(self.lap_count, "lap_count", self.replay_count)
        _integer_at_least(
            self.pit_loss_profile_count,
            "pit_loss_profile_count",
            1,
        )
        _text(self.evidence, "evidence")


def calibrate_uncertainty(
    *,
    calibration_id: str,
    replay_lap_errors: tuple[ReplayLapErrorObservation, ...],
    pit_loss_ranges: tuple[PitLossRangeObservation, ...],
    evidence: str,
) -> UncertaintyCalibration:
    """Decompose development replay error without using protected rows.

    Replay-level mean signed errors define the shared pace scale. Deviations
    around each replay mean define the lap residual scale. Declared circuit
    low/high pit-loss distances from nominal define the pit-loss scale. These
    are perturbation scales, not calibrated probabilities of correctness.
    """
    if not isinstance(replay_lap_errors, tuple):
        raise ConcurrentSimulationContractError(
            "replay_lap_errors must be a tuple"
        )
    if not isinstance(pit_loss_ranges, tuple):
        raise ConcurrentSimulationContractError(
            "pit_loss_ranges must be a tuple"
        )
    if any(
        not isinstance(item, ReplayLapErrorObservation)
        for item in replay_lap_errors
    ):
        raise ConcurrentSimulationContractError(
            "every replay error must be a ReplayLapErrorObservation"
        )
    if any(
        not isinstance(item, PitLossRangeObservation)
        for item in pit_loss_ranges
    ):
        raise ConcurrentSimulationContractError(
            "every pit-loss range must be a PitLossRangeObservation"
        )

    identities = tuple(
        (item.replay_id, item.lap_number) for item in replay_lap_errors
    )
    if len(identities) != len(set(identities)):
        raise ConcurrentSimulationContractError(
            "replay lap-error identities must be unique"
        )
    pit_identities = tuple(
        (item.season, item.event_name.casefold()) for item in pit_loss_ranges
    )
    if len(pit_identities) != len(set(pit_identities)):
        raise ConcurrentSimulationContractError(
            "pit-loss range identities must be unique"
        )

    grouped: dict[str, list[float]] = defaultdict(list)
    seasons: set[int] = set()
    for item in replay_lap_errors:
        grouped[item.replay_id].append(float(item.signed_error_seconds))
        seasons.add(item.season)
    for item in pit_loss_ranges:
        seasons.add(item.season)

    if len(grouped) < 2:
        raise ConcurrentSimulationContractError(
            "uncertainty calibration requires at least two replays"
        )
    if not pit_loss_ranges:
        raise ConcurrentSimulationContractError(
            "uncertainty calibration requires pit-loss ranges"
        )

    replay_means = tuple(fmean(values) for values in grouped.values())
    within_replay_residuals = tuple(
        error - fmean(grouped[replay_id])
        for replay_id, errors in grouped.items()
        for error in errors
    )
    pit_deviations = tuple(
        deviation
        for item in pit_loss_ranges
        for deviation in (
            float(item.low_seconds) - float(item.nominal_seconds),
            float(item.high_seconds) - float(item.nominal_seconds),
        )
    )
    pit_scale = math.sqrt(fmean(value * value for value in pit_deviations))

    return UncertaintyCalibration(
        calibration_id=calibration_id,
        method_id=UNCERTAINTY_CALIBRATION_METHOD_ID,
        training_seasons=tuple(sorted(seasons)),
        shared_pace_scale_seconds=pstdev(replay_means),
        pit_loss_scale_seconds=pit_scale,
        lap_time_residual_scale_seconds=pstdev(within_replay_residuals),
        replay_count=len(grouped),
        lap_count=len(replay_lap_errors),
        pit_loss_profile_count=len(pit_loss_ranges),
        evidence=evidence,
    )


def _development_season(value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConcurrentSimulationContractError("season must be an integer")
    if value == PROTECTED_EVALUATION_SEASON:
        raise ConcurrentSimulationContractError(
            "protected 2025 cannot enter uncertainty calibration"
        )
    if value not in DEVELOPMENT_SEASONS:
        raise ConcurrentSimulationContractError(
            f"season is outside development scope: {value}"
        )


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConcurrentSimulationContractError(
            f"{field_name} must not be blank"
        )
    return value.strip()


def _finite(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConcurrentSimulationContractError(f"{field_name} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ConcurrentSimulationContractError(f"{field_name} must be finite")
    return normalized


def _non_negative(value: object, field_name: str) -> float:
    normalized = _finite(value, field_name)
    if normalized < 0:
        raise ConcurrentSimulationContractError(
            f"{field_name} must be non-negative"
        )
    return normalized


def _positive(value: object, field_name: str) -> float:
    normalized = _finite(value, field_name)
    if normalized <= 0:
        raise ConcurrentSimulationContractError(f"{field_name} must be positive")
    return normalized


def _integer_at_least(value: object, field_name: str, minimum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ConcurrentSimulationContractError(
            f"{field_name} must be an integer of at least {minimum}"
        )
