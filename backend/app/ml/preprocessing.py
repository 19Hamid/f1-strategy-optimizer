"""Fit deterministic preprocessing on training races only."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import numpy as np
import pandas as pd

from app.ml.contracts import (
    APPROVED_FEATURE_COLUMNS,
    BOOLEAN_FEATURE_COLUMNS,
    CATEGORICAL_FEATURE_COLUMNS,
    FORBIDDEN_MODEL_COLUMNS,
    IDENTITY_ABLATION_FEATURE_COLUMNS,
    NUMERIC_FEATURE_COLUMNS,
    ModelFamily,
)

MISSING_CATEGORY_TOKEN: Final = "__MISSING__"
_ALLOWED_FEATURE_SETS: Final = (
    APPROVED_FEATURE_COLUMNS,
    IDENTITY_ABLATION_FEATURE_COLUMNS,
)


class PreprocessingError(ValueError):
    """Raised when features cannot be transformed without leakage."""


@dataclass(frozen=True, slots=True)
class FittedModelPreprocessor:
    """Immutable statistics learned from one training-fold feature matrix."""

    family: ModelFamily
    feature_columns: tuple[str, ...]
    numeric_medians: tuple[tuple[str, float], ...]
    numeric_means: tuple[tuple[str, float], ...]
    numeric_scales: tuple[tuple[str, float], ...]
    category_levels: tuple[tuple[str, tuple[str, ...]], ...]
    output_columns: tuple[str, ...]

    def transform(self, features: pd.DataFrame) -> pd.DataFrame:
        """Apply frozen training statistics without learning new values."""
        _require_approved_source_frame(features)
        transformed = _transform_features(
            features=features,
            family=self.family,
            feature_columns=self.feature_columns,
            numeric_medians=dict(self.numeric_medians),
            numeric_means=dict(self.numeric_means),
            numeric_scales=dict(self.numeric_scales),
            category_levels=dict(self.category_levels),
        )
        if tuple(transformed.columns) != self.output_columns:
            raise PreprocessingError("transformed columns differ from fitted schema")
        return transformed


def fit_model_preprocessor(
    training_features: pd.DataFrame,
    *,
    family: ModelFamily | str,
    feature_columns: tuple[str, ...] = APPROVED_FEATURE_COLUMNS,
) -> FittedModelPreprocessor:
    """Fit medians, optional scaling and categories on training rows only."""
    _require_approved_source_frame(training_features)
    normalized_family = _normalize_family(family)
    selected = tuple(feature_columns)
    if selected not in _ALLOWED_FEATURE_SETS:
        raise PreprocessingError(
            "features must use the full contract or driver/team ablation"
        )
    if set(selected) & FORBIDDEN_MODEL_COLUMNS:
        raise PreprocessingError("forbidden columns entered preprocessing")

    numeric_columns = _selected(NUMERIC_FEATURE_COLUMNS, selected)
    boolean_columns = _selected(BOOLEAN_FEATURE_COLUMNS, selected)
    categorical_columns = _selected(CATEGORICAL_FEATURE_COLUMNS, selected)
    numeric = _numeric_frame(training_features, numeric_columns)
    _validate_boolean_columns(training_features, boolean_columns)

    medians: list[tuple[str, float]] = []
    means: list[tuple[str, float]] = []
    scales: list[tuple[str, float]] = []
    for column in numeric_columns:
        values = numeric[column]
        if values.isna().all():
            raise PreprocessingError(
                f"training numeric feature is entirely missing: {column}"
            )
        median = float(values.median())
        filled = values.fillna(median)
        medians.append((column, median))
        if normalized_family == ModelFamily.RIDGE:
            mean = float(filled.mean())
            scale = float(filled.std(ddof=0))
            if not np.isfinite(scale) or scale == 0:
                scale = 1.0
        else:
            mean = 0.0
            scale = 1.0
        means.append((column, mean))
        scales.append((column, scale))

    levels = tuple(
        (
            column,
            _training_category_levels(training_features[column], column=column),
        )
        for column in categorical_columns
    )
    transformed = _transform_features(
        features=training_features,
        family=normalized_family,
        feature_columns=selected,
        numeric_medians=dict(medians),
        numeric_means=dict(means),
        numeric_scales=dict(scales),
        category_levels=dict(levels),
    )
    if transformed.empty:
        raise PreprocessingError("training preprocessing produced no rows")
    if transformed.isna().any().any():
        raise PreprocessingError("training preprocessing produced missing values")
    values = transformed.to_numpy(dtype="float64")
    if not np.isfinite(values).all():
        raise PreprocessingError("training preprocessing produced non-finite values")

    return FittedModelPreprocessor(
        family=normalized_family,
        feature_columns=selected,
        numeric_medians=tuple(medians),
        numeric_means=tuple(means),
        numeric_scales=tuple(scales),
        category_levels=levels,
        output_columns=tuple(transformed.columns),
    )


def _transform_features(
    *,
    features: pd.DataFrame,
    family: ModelFamily,
    feature_columns: tuple[str, ...],
    numeric_medians: dict[str, float],
    numeric_means: dict[str, float],
    numeric_scales: dict[str, float],
    category_levels: dict[str, tuple[str, ...]],
) -> pd.DataFrame:
    """Apply one frozen preprocessing schema in approved feature order."""
    source = features.reset_index(drop=True)
    result: dict[str, pd.Series] = {}
    for column in feature_columns:
        if column in numeric_medians:
            values = pd.to_numeric(source[column], errors="coerce").replace(
                [np.inf, -np.inf],
                np.nan,
            )
            values = values.fillna(numeric_medians[column]).astype("float64")
            if family == ModelFamily.RIDGE:
                values = (
                    values - numeric_means[column]
                ) / numeric_scales[column]
            result[column] = values
        elif column in BOOLEAN_FEATURE_COLUMNS:
            _validate_boolean_columns(source, (column,))
            result[column] = source[column].astype("float64")
        elif column in category_levels:
            values = _categorical_values(source[column])
            for level in category_levels[column]:
                output_column = _category_output_column(column, level)
                result[output_column] = values.eq(level).astype("float64")
        else:
            raise PreprocessingError(
                f"no fitted transformation for feature: {column}"
            )

    transformed = pd.DataFrame(result, index=source.index)
    if transformed.isna().any().any():
        raise PreprocessingError("preprocessing produced missing values")
    values = transformed.to_numpy(dtype="float64")
    if not np.isfinite(values).all():
        raise PreprocessingError("preprocessing produced non-finite values")
    return transformed


def _training_category_levels(
    values: pd.Series,
    *,
    column: str,
) -> tuple[str, ...]:
    """Freeze sorted training categories plus an explicit missing level."""
    normalized = _categorical_values(values)
    observed = set(normalized.dropna().astype(str))
    if MISSING_CATEGORY_TOKEN in set(
        values.dropna().astype("string").astype(str)
    ):
        raise PreprocessingError(
            f"{column} contains reserved category {MISSING_CATEGORY_TOKEN}"
        )
    observed.discard(MISSING_CATEGORY_TOKEN)
    return (MISSING_CATEGORY_TOKEN, *sorted(observed))


def _categorical_values(values: pd.Series) -> pd.Series:
    """Normalize missing categories without learning validation levels."""
    return values.astype("string").fillna(MISSING_CATEGORY_TOKEN)


def _category_output_column(column: str, level: str) -> str:
    """Build an unambiguous deterministic indicator-column name."""
    return f"{column}=={level}"


def _numeric_frame(
    features: pd.DataFrame,
    columns: tuple[str, ...],
) -> pd.DataFrame:
    """Coerce numeric inputs and treat infinities as missing."""
    return pd.DataFrame(
        {
            column: pd.to_numeric(features[column], errors="coerce").replace(
                [np.inf, -np.inf],
                np.nan,
            )
            for column in columns
        },
        index=features.index,
    )


def _validate_boolean_columns(
    features: pd.DataFrame,
    columns: tuple[str, ...],
) -> None:
    """Require non-null explicit booleans."""
    for column in columns:
        values = features[column]
        if values.isna().any() or not values.isin([True, False]).all():
            raise PreprocessingError(
                f"boolean feature must contain only true or false: {column}"
            )


def _require_approved_source_frame(features: pd.DataFrame) -> None:
    """Require the exact ordered Phase 4 feature frame."""
    if not isinstance(features, pd.DataFrame):
        raise TypeError("features must be a pandas DataFrame")
    if tuple(features.columns) != APPROVED_FEATURE_COLUMNS:
        raise PreprocessingError(
            "source features differ from the approved ordered contract"
        )
    if features.empty:
        raise PreprocessingError("feature frame must not be empty")


def _normalize_family(family: ModelFamily | str) -> ModelFamily:
    """Return one approved model family."""
    try:
        return ModelFamily(family)
    except (TypeError, ValueError) as error:
        raise PreprocessingError(
            f"unknown model family: {family!r}"
        ) from error


def _selected(
    candidates: tuple[str, ...],
    feature_columns: tuple[str, ...],
) -> tuple[str, ...]:
    """Keep a typed subset in canonical contract order."""
    selected = set(feature_columns)
    return tuple(column for column in candidates if column in selected)
