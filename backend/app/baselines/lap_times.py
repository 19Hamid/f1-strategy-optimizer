"""Deterministic, leakage-safe Phase 5 lap-time baselines."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

import numpy as np
import pandas as pd

from app.baselines.contracts import BaselineId, BaselineTask, baseline_spec

PREDICTION_COLUMNS: Final = (
    "decision_id",
    "baseline_id",
    "prediction_seconds",
    "prediction_available",
    "prediction_source",
)


class LapTimeBaselineError(ValueError):
    """Raised when lap-time baseline input violates its contract."""


@dataclass(frozen=True, slots=True)
class LapTimeBaseline:
    """One fitted or decision-local lap-time reference method."""

    baseline_id: BaselineId
    event_compound_medians: dict[tuple[str, str], float] = field(
        default_factory=dict
    )
    compound_medians: dict[str, float] = field(default_factory=dict)
    global_median: float | None = None

    def __post_init__(self) -> None:
        """Require a lap-time identity and fitted state when applicable."""
        specification = baseline_spec(self.baseline_id)
        if specification.task != BaselineTask.LAP_TIME:
            raise LapTimeBaselineError(
                f"{self.baseline_id} is not a lap-time baseline"
            )
        if (
            self.baseline_id == BaselineId.CIRCUIT_COMPOUND_MEDIAN
            and not _positive_finite(self.global_median)
        ):
            raise LapTimeBaselineError(
                "circuit-compound baseline requires a fitted global median"
            )

    def predict(self, rows: pd.DataFrame) -> pd.DataFrame:
        """Predict rows without reading any validation target values."""
        _require_frame(rows, source="prediction rows")
        _require_columns(
            rows,
            ("decision_id",)
            + baseline_spec(self.baseline_id).required_columns,
            source="prediction rows",
            target_optional=True,
        )
        _require_unique_identity(rows)
        if self.baseline_id == BaselineId.PREVIOUS_VALID_LAP:
            values, sources = _previous_valid_lap(rows)
        elif self.baseline_id == BaselineId.ROLLING_MEDIAN_3:
            values, sources = _rolling_median(rows)
        elif self.baseline_id == BaselineId.STINT_LINEAR_TREND:
            values, sources = _stint_trend(rows)
        else:
            values, sources = self._historical_median(rows)

        available = np.isfinite(values) & (values > 0)
        prediction = pd.Series(values, index=rows.index, dtype="float64")
        prediction.loc[~available] = np.nan
        return pd.DataFrame(
            {
                "decision_id": rows["decision_id"].astype("string").array,
                "baseline_id": pd.array(
                    [self.baseline_id.value] * len(rows),
                    dtype="string",
                ),
                "prediction_seconds": prediction.array,
                "prediction_available": pd.array(
                    available,
                    dtype="boolean",
                ),
                "prediction_source": pd.array(sources, dtype="string"),
            },
            columns=PREDICTION_COLUMNS,
        )

    def _historical_median(
        self,
        rows: pd.DataFrame,
    ) -> tuple[np.ndarray, list[str]]:
        """Apply event-compound, compound and global training medians."""
        event_names = rows["event_name"].astype("string")
        compounds = rows["current_compound"].astype("string")
        values = np.full(len(rows), np.nan, dtype=float)
        sources: list[str] = []
        for index, (event_name, compound) in enumerate(
            zip(event_names, compounds, strict=True)
        ):
            event_key = (
                str(event_name),
                str(compound),
            )
            if event_key in self.event_compound_medians:
                values[index] = self.event_compound_medians[event_key]
                sources.append("event_compound_median")
            elif str(compound) in self.compound_medians:
                values[index] = self.compound_medians[str(compound)]
                sources.append("compound_median_fallback")
            else:
                values[index] = float(self.global_median)
                sources.append("global_median_fallback")
        return values, sources


def fit_lap_time_baseline(
    baseline_id: BaselineId | str,
    training_rows: pd.DataFrame | None = None,
) -> LapTimeBaseline:
    """Fit one baseline using training rows only when required."""
    try:
        normalized = BaselineId(baseline_id)
    except (TypeError, ValueError) as error:
        raise LapTimeBaselineError(
            f"unknown lap-time baseline: {baseline_id!r}"
        ) from error
    specification = baseline_spec(normalized)
    if specification.task != BaselineTask.LAP_TIME:
        raise LapTimeBaselineError(
            f"{normalized} is not a lap-time baseline"
        )
    if not specification.fit_required:
        if training_rows is not None:
            _require_frame(training_rows, source="training rows")
        return LapTimeBaseline(baseline_id=normalized)

    if training_rows is None:
        raise LapTimeBaselineError(
            f"{normalized} requires explicit training rows"
        )
    eligible = _eligible_training_targets(training_rows)
    targets = eligible["lap_time_target_seconds"].astype("float64")
    global_median = float(targets.median())
    event_compound = (
        eligible.groupby(
            ["event_name", "current_compound"],
            observed=True,
            dropna=False,
        )["lap_time_target_seconds"]
        .median()
        .to_dict()
    )
    compound = (
        eligible.groupby(
            "current_compound",
            observed=True,
            dropna=False,
        )["lap_time_target_seconds"]
        .median()
        .to_dict()
    )
    return LapTimeBaseline(
        baseline_id=normalized,
        event_compound_medians={
            (str(event), str(compound_name)): float(value)
            for (event, compound_name), value in event_compound.items()
        },
        compound_medians={
            str(compound_name): float(value)
            for compound_name, value in compound.items()
        },
        global_median=global_median,
    )


def _eligible_training_targets(rows: pd.DataFrame) -> pd.DataFrame:
    """Select the frozen intersection used to fit historical aggregates."""
    _require_frame(rows, source="training rows")
    required = (
        "event_name",
        "current_compound",
        "is_decision_eligible",
        "is_lap_time_target_eligible",
        "lap_time_target_seconds",
    )
    _require_columns(rows, required, source="training rows")
    decision_eligible = rows["is_decision_eligible"].eq(True)
    target_eligible = rows["is_lap_time_target_eligible"].eq(True)
    targets = pd.to_numeric(
        rows["lap_time_target_seconds"],
        errors="coerce",
    )
    mask = (
        decision_eligible
        & target_eligible
        & targets.notna()
        & np.isfinite(targets)
        & targets.gt(0)
        & rows["event_name"].notna()
        & rows["current_compound"].notna()
    )
    eligible = rows.loc[mask, list(required)].copy()
    eligible["lap_time_target_seconds"] = targets.loc[mask].astype("float64")
    if eligible.empty:
        raise LapTimeBaselineError(
            "training rows contain no eligible positive lap-time targets"
        )
    return eligible


def _previous_valid_lap(
    rows: pd.DataFrame,
) -> tuple[np.ndarray, list[str]]:
    """Use the immediately previous target-eligible completed lap."""
    values = _numeric(rows["previous_lap_time_seconds"])
    valid = (
        rows["previous_lap_was_target_eligible"]
        .eq(True)
        .fillna(False)
        .to_numpy(dtype=bool)
        & np.isfinite(values)
        & (values > 0)
    )
    predictions = np.where(valid, values, np.nan)
    sources = [
        "previous_valid_lap" if available else "unavailable"
        for available in valid
    ]
    return predictions, sources


def _rolling_median(
    rows: pd.DataFrame,
) -> tuple[np.ndarray, list[str]]:
    """Use the stored past-only median with previous-lap fallback."""
    rolling = _numeric(rows["rolling_lap_time_median_3"])
    previous, _ = _previous_valid_lap(rows)
    rolling_valid = np.isfinite(rolling) & (rolling > 0)
    previous_valid = np.isfinite(previous) & (previous > 0)
    predictions = np.where(
        rolling_valid,
        rolling,
        np.where(previous_valid, previous, np.nan),
    )
    sources = [
        (
            "rolling_median_3"
            if rolling_valid[index]
            else (
                "previous_valid_lap_fallback"
                if previous_valid[index]
                else "unavailable"
            )
        )
        for index in range(len(rows))
    ]
    return predictions, sources


def _stint_trend(
    rows: pd.DataFrame,
) -> tuple[np.ndarray, list[str]]:
    """Advance the prior lap by one past-only trend step."""
    previous, _ = _previous_valid_lap(rows)
    trend = _numeric(rows["rolling_lap_time_trend_5"])
    trend_prediction = previous + trend
    trend_valid = (
        np.isfinite(previous)
        & np.isfinite(trend)
        & np.isfinite(trend_prediction)
        & (trend_prediction > 0)
    )
    rolling, rolling_sources = _rolling_median(rows)
    rolling_valid = np.isfinite(rolling) & (rolling > 0)
    predictions = np.where(
        trend_valid,
        trend_prediction,
        np.where(rolling_valid, rolling, np.nan),
    )
    sources = [
        (
            "stint_linear_trend"
            if trend_valid[index]
            else (
                (
                    "rolling_median_3_fallback"
                    if rolling_sources[index] == "rolling_median_3"
                    else "previous_valid_lap_fallback"
                )
                if rolling_valid[index]
                else "unavailable"
            )
        )
        for index in range(len(rows))
    ]
    return predictions, sources


def _numeric(series: pd.Series) -> np.ndarray:
    """Coerce one source series to finite-checkable floating values."""
    return pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)


def _positive_finite(value: object) -> bool:
    """Return whether a scalar is a usable positive prediction."""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return False
    return bool(np.isfinite(numeric) and numeric > 0)


def _require_frame(value: object, *, source: str) -> None:
    """Require a DataFrame explicitly."""
    if not isinstance(value, pd.DataFrame):
        raise TypeError(f"{source} must be a pandas DataFrame")


def _require_columns(
    rows: pd.DataFrame,
    required: tuple[str, ...],
    *,
    source: str,
    target_optional: bool = False,
) -> None:
    """Require all columns consumed by a fit or prediction."""
    checked = tuple(
        column
        for column in required
        if not (
            target_optional
            and column == "lap_time_target_seconds"
        )
    )
    missing = sorted(set(checked).difference(rows.columns))
    if missing:
        raise LapTimeBaselineError(
            f"{source} missing required columns: {', '.join(missing)}"
        )


def _require_unique_identity(rows: pd.DataFrame) -> None:
    """Require non-null unique decision identities."""
    identity = rows["decision_id"]
    if identity.isna().any():
        raise LapTimeBaselineError("prediction rows contain null decision_id")
    if identity.astype("string").duplicated().any():
        raise LapTimeBaselineError(
            "prediction rows contain duplicate decision_id"
        )
