"""Tests for development-only Phase 9 uncertainty calibration."""

from dataclasses import replace

import pytest

from app.concurrent_simulation import (
    UNCERTAINTY_CALIBRATION_METHOD_ID,
    ConcurrentSimulationContractError,
    PitLossRangeObservation,
    ReplayLapErrorObservation,
    calibrate_uncertainty,
)


def _lap_errors() -> tuple[ReplayLapErrorObservation, ...]:
    return (
        ReplayLapErrorObservation(2023, "replay-a", 10, 1.0),
        ReplayLapErrorObservation(2023, "replay-a", 11, 3.0),
        ReplayLapErrorObservation(2024, "replay-b", 20, -3.0),
        ReplayLapErrorObservation(2024, "replay-b", 21, -1.0),
    )


def _pit_ranges() -> tuple[PitLossRangeObservation, ...]:
    return (
        PitLossRangeObservation(
            season=2024,
            event_name="Bahrain Grand Prix",
            low_seconds=18.0,
            nominal_seconds=20.0,
            high_seconds=23.0,
        ),
    )


def _calibration():
    return calibrate_uncertainty(
        calibration_id="unit-calibration",
        replay_lap_errors=_lap_errors(),
        pit_loss_ranges=_pit_ranges(),
        evidence="synthetic unit-test development evidence",
    )


def test_calibration_decomposes_shared_and_within_replay_error() -> None:
    calibration = _calibration()

    assert calibration.method_id == UNCERTAINTY_CALIBRATION_METHOD_ID
    assert calibration.training_seasons == (2023, 2024)
    assert calibration.shared_pace_scale_seconds == pytest.approx(2.0)
    assert calibration.lap_time_residual_scale_seconds == pytest.approx(1.0)
    assert calibration.pit_loss_scale_seconds == pytest.approx(6.5**0.5)
    assert calibration.replay_count == 2
    assert calibration.lap_count == 4
    assert calibration.pit_loss_profile_count == 1


def test_calibration_is_exactly_deterministic() -> None:
    assert _calibration() == _calibration()


def test_calibration_rejects_duplicate_replay_laps() -> None:
    duplicate = (*_lap_errors(), _lap_errors()[0])

    with pytest.raises(ConcurrentSimulationContractError, match="unique"):
        calibrate_uncertainty(
            calibration_id="duplicate",
            replay_lap_errors=duplicate,
            pit_loss_ranges=_pit_ranges(),
            evidence="duplicate test",
        )


def test_calibration_rejects_duplicate_pit_profiles() -> None:
    duplicate = (*_pit_ranges(), _pit_ranges()[0])

    with pytest.raises(ConcurrentSimulationContractError, match="unique"):
        calibrate_uncertainty(
            calibration_id="duplicate",
            replay_lap_errors=_lap_errors(),
            pit_loss_ranges=duplicate,
            evidence="duplicate test",
        )


def test_calibration_requires_multiple_replays() -> None:
    with pytest.raises(ConcurrentSimulationContractError, match="two replays"):
        calibrate_uncertainty(
            calibration_id="one-replay",
            replay_lap_errors=_lap_errors()[:2],
            pit_loss_ranges=_pit_ranges(),
            evidence="insufficient test",
        )


def test_calibration_requires_pit_loss_evidence() -> None:
    with pytest.raises(ConcurrentSimulationContractError, match="pit-loss ranges"):
        calibrate_uncertainty(
            calibration_id="no-pit-range",
            replay_lap_errors=_lap_errors(),
            pit_loss_ranges=(),
            evidence="insufficient test",
        )


@pytest.mark.parametrize("season", [2025, 2021, True])
def test_calibration_observations_reject_non_development_seasons(
    season: object,
) -> None:
    with pytest.raises(ConcurrentSimulationContractError, match="season|2025"):
        ReplayLapErrorObservation(  # type: ignore[arg-type]
            season,
            "forbidden",
            1,
            0.0,
        )


def test_calibration_rejects_flat_uninformative_evidence() -> None:
    flat = tuple(replace(item, signed_error_seconds=0.0) for item in _lap_errors())

    with pytest.raises(ConcurrentSimulationContractError, match="positive"):
        calibrate_uncertainty(
            calibration_id="flat",
            replay_lap_errors=flat,
            pit_loss_ranges=_pit_ranges(),
            evidence="flat test",
        )


def test_pit_loss_range_must_be_ordered() -> None:
    with pytest.raises(ConcurrentSimulationContractError, match="low <= nominal"):
        PitLossRangeObservation(2024, "Test Grand Prix", 21.0, 20.0, 22.0)
