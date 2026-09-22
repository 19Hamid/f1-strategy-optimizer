"""Verified Phase 6 model inference for deterministic Phase 7 rollouts."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Final

import numpy as np
import pandas as pd

from app.datasets.contracts import DEVELOPMENT_SEASONS
from app.ml import (
    APPROVED_FEATURE_COLUMNS,
    FINAL_DEVELOPMENT_FIT_ID,
    FULL_FEATURE_SET_ID,
    MODEL_CONTRACT_VERSION,
    LoadedModelArtifact,
    ModelArtifactPaths,
    ModelFamily,
    ModelTarget,
    PredictionFormulation,
    load_model_artifact,
)
from app.simulation.engine import SimulationProgress

SELECTED_SIMULATOR_CANDIDATE_ID: Final = "xgboost_02"


class ModelAdapterError(ValueError):
    """Raised when model identity or simulator inference is unsafe."""


@dataclass(frozen=True, slots=True)
class SimulationFeatureContext:
    """Frozen historical seed plus prior simulated racing-lap predictions."""

    base_features: pd.DataFrame
    recent_lap_times_seconds: tuple[float, ...]
    simulated_lap_times_seconds: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        """Copy and validate exact Phase 6 feature and lap-history identity."""
        if not isinstance(self.base_features, pd.DataFrame):
            raise TypeError("base_features must be a pandas DataFrame")
        if tuple(self.base_features.columns) != APPROVED_FEATURE_COLUMNS:
            raise ModelAdapterError(
                "base feature columns differ from the Phase 6 contract"
            )
        if len(self.base_features) != 1:
            raise ModelAdapterError("base_features must contain exactly one row")
        recent = _lap_times(
            self.recent_lap_times_seconds,
            "recent_lap_times_seconds",
        )
        simulated = _lap_times(
            self.simulated_lap_times_seconds,
            "simulated_lap_times_seconds",
        )
        object.__setattr__(
            self,
            "base_features",
            self.base_features.copy(deep=True).reset_index(drop=True),
        )
        object.__setattr__(self, "recent_lap_times_seconds", recent[-5:])
        object.__setattr__(self, "simulated_lap_times_seconds", simulated)

    def record_simulated_lap(
        self,
        predicted_lap_time_seconds: float,
    ) -> SimulationFeatureContext:
        """Return a new context containing one controlled model prediction."""
        prediction = _positive_finite(
            predicted_lap_time_seconds,
            "predicted_lap_time_seconds",
        )
        return replace(
            self,
            simulated_lap_times_seconds=(
                *self.simulated_lap_times_seconds,
                prediction,
            ),
        )


@dataclass(frozen=True, slots=True)
class ModelLapPrediction:
    """One positive prediction and the exact feature row supplied to the model."""

    seconds: float
    features: pd.DataFrame


@dataclass(frozen=True, slots=True)
class Phase6ModelAdapter:
    """Inference-only adapter for the selected verified Phase 6 artifact."""

    artifact: LoadedModelArtifact

    def __post_init__(self) -> None:
        """Require the exact final selected artifact and full feature schema."""
        if not isinstance(self.artifact, LoadedModelArtifact):
            raise TypeError("artifact must be a LoadedModelArtifact")
        provenance = self.artifact.provenance
        checks = (
            (
                "model contract version",
                provenance.model_contract_version,
                MODEL_CONTRACT_VERSION,
            ),
            ("fold", provenance.fold_id, FINAL_DEVELOPMENT_FIT_ID),
            ("target", provenance.target, ModelTarget.LAP_TIME),
            (
                "formulation",
                provenance.formulation,
                PredictionFormulation.RESIDUAL_HYBRID,
            ),
            ("family", provenance.family, ModelFamily.XGBOOST),
            (
                "candidate",
                provenance.candidate_id,
                SELECTED_SIMULATOR_CANDIDATE_ID,
            ),
            ("feature set", provenance.feature_set_id, FULL_FEATURE_SET_ID),
            (
                "features",
                provenance.feature_columns,
                APPROVED_FEATURE_COLUMNS,
            ),
            (
                "training seasons",
                provenance.training_seasons,
                DEVELOPMENT_SEASONS,
            ),
        )
        mismatches = [
            name
            for name, actual, expected in checks
            if actual != expected
        ]
        if mismatches:
            raise ModelAdapterError(
                "artifact differs from selected Phase 6 model: "
                + ", ".join(mismatches)
            )
        if provenance.validation_session_ids:
            raise ModelAdapterError(
                "final simulator artifact must not retain validation sessions"
            )

    @classmethod
    def from_paths(
        cls,
        paths: ModelArtifactPaths,
    ) -> Phase6ModelAdapter:
        """Load only through Phase 6 integrity and prediction verification."""
        if not isinstance(paths, ModelArtifactPaths):
            raise TypeError("paths must be ModelArtifactPaths")
        return cls(artifact=load_model_artifact(paths))

    def predict_next_lap(
        self,
        *,
        context: SimulationFeatureContext,
        progress: SimulationProgress,
    ) -> ModelLapPrediction:
        """Build one safe future row and run verified model inference."""
        features = build_simulation_features(
            context=context,
            progress=progress,
        )
        predictions = np.asarray(
            self.artifact.predict(features),
            dtype="float64",
        ).reshape(-1)
        if predictions.shape != (1,):
            raise ModelAdapterError(
                "Phase 6 artifact returned the wrong prediction count"
            )
        seconds = _positive_finite(
            float(predictions[0]),
            "model prediction",
        )
        return ModelLapPrediction(
            seconds=seconds,
            features=features.copy(deep=True),
        )


def build_simulation_features(
    *,
    context: SimulationFeatureContext,
    progress: SimulationProgress,
) -> pd.DataFrame:
    """Build one future feature row without reading post-decision race data."""
    if not isinstance(context, SimulationFeatureContext):
        raise TypeError("context must be a SimulationFeatureContext")
    if not isinstance(progress, SimulationProgress):
        raise TypeError("progress must be SimulationProgress")
    if len(context.simulated_lap_times_seconds) != (
        progress.completed_simulation_laps
    ):
        raise ModelAdapterError(
            "simulated feature history differs from engine progress"
        )

    base = context.base_features.iloc[0]
    _verify_seed_identity(base, progress)
    features = context.base_features.copy(deep=True)
    row = features.index[0]
    features.at[row, "decision_lap"] = progress.next_lap
    features.at[row, "current_compound"] = progress.current_compound.value
    features.at[row, "tyre_age_laps"] = progress.tyre_age_laps
    features.at[
        row,
        "current_stint_laps_completed",
    ] = progress.current_stint_laps_completed
    features.at[row, "completed_pit_stops"] = progress.completed_pit_stops
    features.at[row, "weather_age_seconds"] = (
        _finite_non_negative(
            base["weather_age_seconds"],
            "base weather_age_seconds",
        )
        + progress.elapsed_time_seconds
    )

    if context.simulated_lap_times_seconds:
        can_use_previous = progress.current_stint_laps_completed > 0
        previous_prediction = context.simulated_lap_times_seconds[-1]
        features.at[
            row,
            "previous_lap_was_target_eligible",
        ] = can_use_previous
        features.at[row, "previous_lap_time_seconds"] = (
            previous_prediction if can_use_previous else float("nan")
        )
        for column in (
            "previous_sector1_time_seconds",
            "previous_sector2_time_seconds",
            "previous_sector3_time_seconds",
        ):
            features.at[row, column] = float("nan")
        features.at[row, "eligible_laps_completed"] = (
            _non_negative_integer(
                base["eligible_laps_completed"],
                "base eligible_laps_completed",
            )
            + len(context.simulated_lap_times_seconds)
        )
        rolling = _rolling_statistics(
            (
                *context.recent_lap_times_seconds,
                *context.simulated_lap_times_seconds,
            )
        )
        for column, value in zip(
            (
                "rolling_lap_time_median_3",
                "rolling_lap_time_median_5",
                "rolling_lap_time_std_5",
                "rolling_lap_time_trend_5",
            ),
            rolling,
            strict=True,
        ):
            features.at[row, column] = value

    return features.loc[:, APPROVED_FEATURE_COLUMNS]


def _verify_seed_identity(
    base: pd.Series,
    progress: SimulationProgress,
) -> None:
    identities = (
        ("event_name", base["event_name"], progress.event_name),
        ("driver", base["driver"], progress.driver),
        ("team", base["team"], progress.team),
        ("decision_lap", base["decision_lap"], progress.start_lap),
    )
    mismatches = [
        name
        for name, actual, expected in identities
        if actual != expected
    ]
    if progress.completed_simulation_laps == 0:
        initial = (
            (
                "current_compound",
                base["current_compound"],
                progress.current_compound.value,
            ),
            ("tyre_age_laps", base["tyre_age_laps"], progress.tyre_age_laps),
            (
                "current_stint_laps_completed",
                base["current_stint_laps_completed"],
                progress.current_stint_laps_completed,
            ),
            (
                "completed_pit_stops",
                base["completed_pit_stops"],
                progress.completed_pit_stops,
            ),
        )
        mismatches.extend(
            name
            for name, actual, expected in initial
            if actual != expected
        )
    if mismatches:
        raise ModelAdapterError(
            "base feature seed differs from simulation state: "
            + ", ".join(mismatches)
        )


def _rolling_statistics(
    lap_times: tuple[float, ...],
) -> tuple[float, float, float, float]:
    """Reproduce the frozen Phase 4 past-only rolling definitions."""
    if len(lap_times) < 3:
        missing = float("nan")
        return missing, missing, missing, missing
    latest_three = np.asarray(lap_times[-3:], dtype="float64")
    latest_five = np.asarray(lap_times[-5:], dtype="float64")
    positions = np.arange(len(latest_five), dtype="float64")
    centered_positions = positions - positions.mean()
    centered_times = latest_five - latest_five.mean()
    denominator = float(np.square(centered_positions).sum())
    trend = (
        float("nan")
        if denominator <= 0
        else float((centered_positions * centered_times).sum() / denominator)
    )
    return (
        float(np.median(latest_three)),
        float(np.median(latest_five)),
        float(np.std(latest_five, ddof=0)),
        trend,
    )


def _lap_times(values: object, field_name: str) -> tuple[float, ...]:
    if not isinstance(values, tuple):
        raise ModelAdapterError(f"{field_name} must be a tuple")
    return tuple(
        _positive_finite(value, f"{field_name}[{index}]")
        for index, value in enumerate(values)
    )


def _positive_finite(value: object, field_name: str) -> float:
    normalized = _number(value, field_name)
    if normalized <= 0:
        raise ModelAdapterError(f"{field_name} must be positive")
    return normalized


def _finite_non_negative(value: object, field_name: str) -> float:
    normalized = _number(value, field_name)
    if normalized < 0:
        raise ModelAdapterError(f"{field_name} must be non-negative")
    return normalized


def _number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(
        value,
        (int, float, np.integer, np.floating),
    ):
        raise ModelAdapterError(f"{field_name} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ModelAdapterError(f"{field_name} must be finite")
    return normalized


def _non_negative_integer(value: object, field_name: str) -> int:
    normalized = _number(value, field_name)
    if not normalized.is_integer() or normalized < 0:
        raise ModelAdapterError(
            f"{field_name} must be a non-negative integer"
        )
    return int(normalized)
