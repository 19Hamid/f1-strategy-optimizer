"""Tests for development-race observed-strategy replay evaluation."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from app.datasets.contracts import DEVELOPMENT_SEASONS
from app.ml import (
    APPROVED_FEATURE_COLUMNS,
    FINAL_DEVELOPMENT_FIT_ID,
    FULL_FEATURE_SET_ID,
    MODEL_CONTRACT_VERSION,
    LoadedModelArtifact,
    ModelFamily,
    ModelTarget,
    PredictionFormulation,
)
from app.simulation import (
    DryCompound,
    Phase6ModelAdapter,
    PitLossAssumption,
    PitLossSource,
    PlannedPitStop,
    RaceState,
    SimulationFeatureContext,
    SimulationMode,
    SimulationRequest,
    StrategyPlan,
)
from app.simulation.model_adapter import SELECTED_SIMULATOR_CANDIDATE_ID
from app.simulation.observed_replay import (
    ObservedReplayError,
    ObservedReplayEvaluation,
    ObservedReplayLap,
    ObservedStrategyReplay,
    ObservedStrategyTrace,
    ReplayHorizon,
    build_observed_replay_context,
    build_observed_strategy_trace,
    replay_observed_strategy,
)


class _LapNumberModel:
    def predict(self, features: pd.DataFrame) -> np.ndarray:
        assert tuple(features.columns) == APPROVED_FEATURE_COLUMNS
        laps = features["decision_lap"].to_numpy(dtype="float64")
        return 90.0 + (laps / 100.0)


def _artifact() -> LoadedModelArtifact:
    provenance = SimpleNamespace(
        model_contract_version=MODEL_CONTRACT_VERSION,
        fold_id=FINAL_DEVELOPMENT_FIT_ID,
        target=ModelTarget.LAP_TIME,
        formulation=PredictionFormulation.RESIDUAL_HYBRID,
        family=ModelFamily.XGBOOST,
        candidate_id=SELECTED_SIMULATOR_CANDIDATE_ID,
        feature_set_id=FULL_FEATURE_SET_ID,
        execution_device="cuda",
        feature_columns=APPROVED_FEATURE_COLUMNS,
        training_seasons=DEVELOPMENT_SEASONS,
        validation_session_ids=(),
    )
    return LoadedModelArtifact(
        model=_LapNumberModel(),  # type: ignore[arg-type]
        provenance=provenance,  # type: ignore[arg-type]
    )


def _base_features() -> pd.DataFrame:
    values: dict[str, object] = {
        "event_name": "Bahrain Grand Prix",
        "driver": "VER",
        "team": "Red Bull Racing",
        "decision_lap": 20,
        "current_compound": "MEDIUM",
        "tyre_age_laps": 19,
        "current_stint_laps_completed": 19,
        "completed_pit_stops": 0,
        "previous_position": 1,
        "previous_lap_was_target_eligible": True,
        "previous_lap_time_seconds": 94.0,
        "previous_sector1_time_seconds": 30.0,
        "previous_sector2_time_seconds": 31.0,
        "previous_sector3_time_seconds": 33.0,
        "eligible_laps_completed": 10,
        "rolling_lap_time_median_3": 93.0,
        "rolling_lap_time_median_5": 92.0,
        "rolling_lap_time_std_5": 1.414,
        "rolling_lap_time_trend_5": 1.0,
        "weather_age_seconds": 5.0,
        "air_temperature_celsius": 24.0,
        "humidity_percent": 40.0,
        "pressure_mbar": 1012.0,
        "track_temperature_celsius": 31.0,
        "wind_direction_degrees": 180.0,
        "wind_speed_mps": 2.5,
    }
    return pd.DataFrame([values], columns=APPROVED_FEATURE_COLUMNS)


def _context() -> SimulationFeatureContext:
    return SimulationFeatureContext(
        base_features=_base_features(),
        recent_lap_times_seconds=(90.0, 91.0, 92.0, 93.0, 94.0),
    )


def _decision_rows() -> pd.DataFrame:
    frame = _base_features()
    frame.insert(0, "session_id", "2024-01-R")
    frame.insert(1, "season", 2024)
    frame["is_decision_eligible"] = True
    return frame


def _processed_laps() -> pd.DataFrame:
    lap_numbers = tuple(range(15, 23))
    lap_times = (85.0, 86.0, 87.0, 88.0, 89.0, 90.0, 110.0, 90.5)
    return pd.DataFrame(
        {
            "Season": [2024] * len(lap_numbers),
            "SessionType": ["R"] * len(lap_numbers),
            "EventName": ["Bahrain Grand Prix"] * len(lap_numbers),
            "Driver": ["VER"] * len(lap_numbers),
            "Team": ["Red Bull Racing"] * len(lap_numbers),
            "LapNumber": lap_numbers,
            "LapTimeSeconds": lap_times,
            "Compound": ["MEDIUM"] * 7 + ["HARD"],
            "PitInTime": [pd.NaT] * 6
            + [pd.Timedelta(seconds=1), pd.NaT],
            "Rainfall": [False] * len(lap_numbers),
            "TrackStatus": ["1"] * len(lap_numbers),
            "IsEligible": [True] * len(lap_numbers),
        }
    )


def _request(
    *,
    total_laps: int = 22,
    session_id: str = "2024-01-R",
    strategy_id: str = "observed-medium-hard",
    stops: tuple[PlannedPitStop, ...] = (
        PlannedPitStop(21, DryCompound.HARD),
    ),
    mode: SimulationMode = SimulationMode.OBSERVED_STRATEGY_REPLAY,
) -> SimulationRequest:
    compounds = (
        (DryCompound.MEDIUM,)
        if stops
        else (DryCompound.HARD, DryCompound.MEDIUM)
    )
    return SimulationRequest(
        state=RaceState(
            season=2024,
            session_id=session_id,
            event_name="Bahrain Grand Prix",
            driver="VER",
            team="Red Bull Racing",
            current_lap=20,
            total_laps=total_laps,
            current_compound=DryCompound.MEDIUM,
            tyre_age_laps=19,
            current_stint_laps_completed=19,
            completed_pit_stops=0,
            compounds_used=compounds,
            previous_position=1,
        ),
        strategy=StrategyPlan(strategy_id=strategy_id, stops=stops),
        pit_loss=PitLossAssumption(
            seconds=20.0,
            source=PitLossSource.EXPLICIT_ASSUMPTION,
            evidence="observed replay test assumption",
        ),
        mode=mode,
    )


def _trace(
    *,
    total_laps: int = 22,
    session_id: str = "2024-01-R",
    stops: tuple[PlannedPitStop, ...] = (
        PlannedPitStop(21, DryCompound.HARD),
    ),
    observed_times: tuple[float, ...] | None = None,
) -> ObservedStrategyTrace:
    laps = tuple(range(20, total_laps + 1))
    times = observed_times or tuple(91.0 for _ in laps)
    stop_by_lap = {stop.after_lap: stop for stop in stops}
    return ObservedStrategyTrace(
        season=2024,
        session_id=session_id,
        event_name="Bahrain Grand Prix",
        driver="VER",
        team="Red Bull Racing",
        start_lap=20,
        total_laps=total_laps,
        laps=tuple(
            ObservedReplayLap(
                lap_number=lap_number,
                observed_total_lap_time_seconds=observed_time,
                pit_stop=stop_by_lap.get(lap_number),
            )
            for lap_number, observed_time in zip(laps, times, strict=True)
        ),
    )


def _replay(
    *,
    total_laps: int = 22,
    session_id: str = "2024-01-R",
    strategy_id: str = "observed-medium-hard",
    stops: tuple[PlannedPitStop, ...] = (
        PlannedPitStop(21, DryCompound.HARD),
    ),
    observed_times: tuple[float, ...] | None = None,
) -> ObservedStrategyReplay:
    return replay_observed_strategy(
        _request(
            total_laps=total_laps,
            session_id=session_id,
            strategy_id=strategy_id,
            stops=stops,
        ),
        context=_context(),
        adapter=Phase6ModelAdapter(_artifact()),
        observed=_trace(
            total_laps=total_laps,
            session_id=session_id,
            stops=stops,
            observed_times=observed_times,
        ),
    )


def test_trace_requires_complete_development_horizon() -> None:
    """Reject protected seasons, lap gaps and a stop after the finish."""
    trace = _trace()
    with pytest.raises(ObservedReplayError, match="development seasons"):
        replace(trace, season=2025)
    with pytest.raises(ObservedReplayError, match="complete consecutive"):
        replace(trace, laps=trace.laps[:-1])
    final_stop = PlannedPitStop(22, DryCompound.HARD)
    with pytest.raises(ObservedReplayError, match="final lap"):
        replace(
            trace,
            laps=(
                *trace.laps[:-1],
                replace(trace.laps[-1], pit_stop=final_stop),
            ),
        )


def test_builders_use_exact_processed_and_decision_evidence() -> None:
    """Build a replay seed and outcome directly from real table schemas."""
    request = _request()
    context = build_observed_replay_context(
        request,
        _decision_rows(),
        _processed_laps(),
    )
    trace = build_observed_strategy_trace(request, _processed_laps())

    assert tuple(context.base_features.columns) == APPROVED_FEATURE_COLUMNS
    assert context.base_features.equals(_base_features())
    assert context.recent_lap_times_seconds == (85.0, 86.0, 87.0, 88.0, 89.0)
    assert tuple(lap.lap_number for lap in trace.laps) == (20, 21, 22)
    assert tuple(
        lap.observed_total_lap_time_seconds for lap in trace.laps
    ) == (90.0, 110.0, 90.5)
    assert trace.pit_stops == request.strategy.stops


@pytest.mark.parametrize(
    ("column", "value", "message"),
    (
        ("Rainfall", True, "remain dry"),
        ("TrackStatus", "4", "remain green"),
    ),
)
def test_trace_builder_rejects_uncontrolled_conditions(
    column: str,
    value: object,
    message: str,
) -> None:
    """Keep observed validation inside the frozen dry, green V1 scope."""
    processed = _processed_laps()
    processed.loc[processed["LapNumber"] == 21, column] = value

    with pytest.raises(ObservedReplayError, match=message):
        build_observed_strategy_trace(_request(), processed)


def test_trace_builder_requires_exact_observed_stop_and_compound() -> None:
    """Reject a replay when the processed pit evidence contradicts the plan."""
    missing_stop = _processed_laps()
    missing_stop["PitInTime"] = pd.NaT
    with pytest.raises(ObservedReplayError, match="pit-in laps"):
        build_observed_strategy_trace(_request(), missing_stop)

    wrong_compound = _processed_laps()
    wrong_compound.loc[wrong_compound["LapNumber"] == 22, "Compound"] = "SOFT"
    with pytest.raises(ObservedReplayError, match="post-stop compound"):
        build_observed_strategy_trace(_request(), wrong_compound)


def test_context_builder_requires_one_eligible_decision() -> None:
    """Refuse ambiguous or ineligible model seeds."""
    ineligible = _decision_rows()
    ineligible["is_decision_eligible"] = False
    with pytest.raises(ObservedReplayError, match="must be eligible"):
        build_observed_replay_context(
            _request(),
            ineligible,
            _processed_laps(),
        )

    duplicate = pd.concat([_decision_rows(), _decision_rows()])
    with pytest.raises(ObservedReplayError, match="exactly one"):
        build_observed_replay_context(
            _request(),
            duplicate,
            _processed_laps(),
        )


def test_observed_replay_scores_laps_and_time_to_flag() -> None:
    """Keep signed lap and cumulative trajectory errors auditable."""
    replay = _replay(observed_times=(90.0, 110.0, 90.5))

    assert tuple(row.lap_number for row in replay.lap_errors) == (20, 21, 22)
    assert tuple(
        row.signed_lap_error_seconds for row in replay.lap_errors
    ) == pytest.approx((0.20, 0.21, -0.28))
    assert tuple(
        row.cumulative_signed_error_seconds for row in replay.lap_errors
    ) == pytest.approx((0.20, 0.41, 0.13))
    assert replay.lap_metrics.mean_absolute_error_seconds == pytest.approx(0.23)
    assert replay.predicted_remaining_time_seconds == pytest.approx(290.63)
    assert replay.observed_remaining_time_seconds == pytest.approx(290.5)
    assert replay.signed_remaining_time_error_seconds == pytest.approx(0.13)
    assert replay.absolute_remaining_time_error_seconds == pytest.approx(0.13)


def test_replay_keeps_model_time_pit_loss_and_observation_separate() -> None:
    """Never relabel observed total time as counterfactual net pit loss."""
    replay = _replay(observed_times=(90.0, 110.0, 90.5))
    pit_row = replay.lap_errors[1]

    assert pit_row.predicted_racing_time_seconds == pytest.approx(90.21)
    assert pit_row.applied_pit_loss_seconds == 20.0
    assert pit_row.predicted_total_lap_time_seconds == pytest.approx(110.21)
    assert pit_row.observed_total_lap_time_seconds == 110.0


def test_replay_requires_observed_mode_and_matching_identity() -> None:
    """Reject counterfactual mode and cross-session observed evidence."""
    adapter = Phase6ModelAdapter(_artifact())
    with pytest.raises(ObservedReplayError, match="requires"):
        replay_observed_strategy(
            _request(mode=SimulationMode.COUNTERFACTUAL_STRATEGY),
            context=_context(),
            adapter=adapter,
            observed=_trace(),
        )
    with pytest.raises(ObservedReplayError, match="session_id"):
        replay_observed_strategy(
            _request(),
            context=_context(),
            adapter=adapter,
            observed=_trace(session_id="different-session"),
        )


def test_replay_requires_exact_observed_stop_plan() -> None:
    """Do not score a simulated plan against a different historical plan."""
    with pytest.raises(ObservedReplayError, match="stops differ"):
        replay_observed_strategy(
            _request(),
            context=_context(),
            adapter=Phase6ModelAdapter(_artifact()),
            observed=_trace(stops=()),
        )


def test_replay_result_rejects_tampered_cumulative_evidence() -> None:
    """Fail closed when stored trajectory errors no longer add up."""
    replay = _replay(observed_times=(90.0, 110.0, 90.5))
    altered = replace(
        replay.lap_errors[1],
        cumulative_predicted_time_seconds=999.0,
        cumulative_signed_error_seconds=(
            999.0 - replay.lap_errors[1].cumulative_observed_time_seconds
        ),
    )
    with pytest.raises(ObservedReplayError, match="trajectory"):
        replace(
            replay,
            lap_errors=(replay.lap_errors[0], altered, replay.lap_errors[2]),
        )


def test_evaluation_pools_laps_and_weights_each_replay_once() -> None:
    """Distinguish pooled lap accuracy from finish-time accuracy."""
    first = _replay(observed_times=(90.0, 110.0, 90.5))
    second = _replay(
        session_id="2024-02-R",
        strategy_id="observed-no-stop",
        stops=(),
        observed_times=(90.2, 90.2, 90.2),
    )
    evaluation = ObservedReplayEvaluation((first, second))

    assert evaluation.replay_count == 2
    assert evaluation.lap_count == 6
    assert evaluation.lap_metrics.rows == 6
    assert evaluation.remaining_time_metrics.rows == 2
    assert evaluation.remaining_time_metrics.mean_absolute_error_seconds == (
        pytest.approx(0.08)
    )


def test_evaluation_reports_short_medium_and_long_horizons() -> None:
    """Expose error growth without mixing materially different horizons."""
    replays = (
        _replay(
            session_id="short",
            strategy_id="short",
            stops=(),
        ),
        _replay(
            total_laps=30,
            session_id="medium",
            strategy_id="medium",
            stops=(),
        ),
        _replay(
            total_laps=45,
            session_id="long",
            strategy_id="long",
            stops=(),
        ),
    )
    evaluation = ObservedReplayEvaluation(replays)

    assert tuple(item.horizon for item in evaluation.horizon_slices) == (
        ReplayHorizon.SHORT,
        ReplayHorizon.MEDIUM,
        ReplayHorizon.LONG,
    )
    assert tuple(item.replays for item in evaluation.horizon_slices) == (1, 1, 1)


def test_evaluation_rejects_duplicate_replay_identity() -> None:
    """Prevent one historical trajectory from receiving duplicate weight."""
    replay = _replay()
    with pytest.raises(ObservedReplayError, match="unique"):
        ObservedReplayEvaluation((replay, replay))
