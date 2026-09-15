"""Tests for training-only Phase 6 feature preprocessing."""

import numpy as np
import pandas as pd
import pytest

from app.ml import (
    APPROVED_FEATURE_COLUMNS,
    BOOLEAN_FEATURE_COLUMNS,
    CATEGORICAL_FEATURE_COLUMNS,
    IDENTITY_ABLATION_FEATURE_COLUMNS,
    NUMERIC_FEATURE_COLUMNS,
    ModelFamily,
)
from app.ml.preprocessing import (
    MISSING_CATEGORY_TOKEN,
    FittedModelPreprocessor,
    PreprocessingError,
    fit_model_preprocessor,
)


def _features() -> pd.DataFrame:
    """Build the exact approved feature frame with realistic value types."""
    records: list[dict[str, object]] = []
    for index in range(3):
        record: dict[str, object] = {
            column: float(index + 1)
            for column in NUMERIC_FEATURE_COLUMNS
        }
        record.update(
            {
                "event_name": ("Bahrain GP", "Saudi GP", "Bahrain GP")[index],
                "driver": ("HAM", "LEC", "HAM")[index],
                "team": ("Ferrari", "Ferrari", "Mercedes")[index],
                "current_compound": ("MEDIUM", "SOFT", None)[index],
                "previous_lap_was_target_eligible": (True, False, True)[index],
            }
        )
        records.append(record)
    return pd.DataFrame.from_records(
        records,
        columns=APPROVED_FEATURE_COLUMNS,
    )


def test_ridge_fits_median_and_scaling_on_training_rows() -> None:
    """Impute and standardize numerics with training-fold statistics."""
    features = _features()
    features.loc[1, "tyre_age_laps"] = np.nan
    preprocessor = fit_model_preprocessor(
        features,
        family=ModelFamily.RIDGE,
    )
    transformed = preprocessor.transform(features)
    assert isinstance(preprocessor, FittedModelPreprocessor)
    assert dict(preprocessor.numeric_medians)["tyre_age_laps"] == 2.0
    assert transformed["decision_lap"].mean() == pytest.approx(0.0)
    assert transformed["decision_lap"].std(ddof=0) == pytest.approx(1.0)
    assert not transformed.isna().any().any()


def test_tree_preprocessing_imputes_without_scaling_numeric_values() -> None:
    """Keep tree numeric geometry while still eliminating missing values."""
    features = _features()
    features.loc[1, "tyre_age_laps"] = np.nan
    preprocessor = fit_model_preprocessor(
        features,
        family=ModelFamily.RANDOM_FOREST,
    )
    transformed = preprocessor.transform(features)
    assert tuple(transformed["decision_lap"]) == (1.0, 2.0, 3.0)
    assert tuple(transformed["tyre_age_laps"]) == (1.0, 2.0, 3.0)


def test_unknown_validation_category_does_not_refit_schema() -> None:
    """Encode unseen validation values as all-zero known indicators."""
    training = _features()
    preprocessor = fit_model_preprocessor(
        training,
        family=ModelFamily.HIST_GRADIENT_BOOSTING,
    )
    validation = training.iloc[[0]].copy()
    validation.loc[:, "event_name"] = "Never Seen GP"
    transformed = preprocessor.transform(validation)
    event_columns = [
        column
        for column in transformed
        if column.startswith("event_name==")
    ]
    assert event_columns
    assert transformed.loc[0, event_columns].eq(0.0).all()
    assert tuple(transformed.columns) == preprocessor.output_columns


def test_missing_category_has_explicit_indicator() -> None:
    """Distinguish missing input from every observed named category."""
    features = _features()
    preprocessor = fit_model_preprocessor(
        features,
        family=ModelFamily.RANDOM_FOREST,
    )
    transformed = preprocessor.transform(features)
    missing_column = f"current_compound=={MISSING_CATEGORY_TOKEN}"
    assert missing_column in transformed
    assert tuple(transformed[missing_column]) == (0.0, 0.0, 1.0)


def test_boolean_feature_becomes_zero_or_one() -> None:
    """Provide deterministic numeric booleans to every estimator."""
    features = _features()
    transformed = fit_model_preprocessor(
        features,
        family=ModelFamily.RANDOM_FOREST,
    ).transform(features)
    column = BOOLEAN_FEATURE_COLUMNS[0]
    assert tuple(transformed[column]) == (1.0, 0.0, 1.0)


def test_identity_ablation_removes_driver_and_team_indicators() -> None:
    """Support the mandatory memorization-risk diagnostic."""
    features = _features()
    preprocessor = fit_model_preprocessor(
        features,
        family=ModelFamily.RIDGE,
        feature_columns=IDENTITY_ABLATION_FEATURE_COLUMNS,
    )
    transformed = preprocessor.transform(features)
    assert not any(
        column.startswith(("driver==", "team=="))
        for column in transformed
    )
    assert "event_name" in CATEGORICAL_FEATURE_COLUMNS
    assert any(
        column.startswith("event_name==")
        for column in transformed
    )


def test_transform_does_not_change_fitted_training_statistics() -> None:
    """Validation extremes cannot alter medians, means or output columns."""
    training = _features()
    preprocessor = fit_model_preprocessor(
        training,
        family=ModelFamily.RIDGE,
    )
    frozen_state = (
        preprocessor.numeric_medians,
        preprocessor.numeric_means,
        preprocessor.numeric_scales,
        preprocessor.category_levels,
        preprocessor.output_columns,
    )
    validation = training.iloc[[0]].copy()
    validation.loc[:, "decision_lap"] = 999999.0
    validation.loc[:, "driver"] = "NEW_DRIVER"
    preprocessor.transform(validation)
    assert frozen_state == (
        preprocessor.numeric_medians,
        preprocessor.numeric_means,
        preprocessor.numeric_scales,
        preprocessor.category_levels,
        preprocessor.output_columns,
    )


def test_shuffled_training_rows_keep_same_fitted_schema() -> None:
    """Make category and output ordering independent of input row order."""
    features = _features()
    original = fit_model_preprocessor(
        features,
        family=ModelFamily.RANDOM_FOREST,
    )
    shuffled = fit_model_preprocessor(
        features.sample(frac=1, random_state=42),
        family=ModelFamily.RANDOM_FOREST,
    )
    assert original.category_levels == shuffled.category_levels
    assert original.output_columns == shuffled.output_columns
    assert original.numeric_medians == shuffled.numeric_medians


def test_constant_ridge_numeric_feature_uses_unit_safe_scale() -> None:
    """Avoid division by zero for a constant training feature."""
    features = _features()
    features.loc[:, "pressure_mbar"] = 1000.0
    preprocessor = fit_model_preprocessor(
        features,
        family=ModelFamily.RIDGE,
    )
    assert dict(preprocessor.numeric_scales)["pressure_mbar"] == 1.0
    assert preprocessor.transform(features)["pressure_mbar"].eq(0.0).all()


def test_invalid_boolean_feature_is_rejected() -> None:
    """Refuse ambiguous truth values instead of silently coercing them."""
    features = _features()
    features.loc[0, BOOLEAN_FEATURE_COLUMNS[0]] = "yes"
    with pytest.raises(PreprocessingError, match="only true or false"):
        fit_model_preprocessor(
            features,
            family=ModelFamily.RIDGE,
        )


def test_entirely_missing_numeric_training_feature_is_rejected() -> None:
    """Do not invent an imputation value with no training evidence."""
    features = _features()
    features.loc[:, "rolling_lap_time_std_5"] = np.nan
    with pytest.raises(PreprocessingError, match="entirely missing"):
        fit_model_preprocessor(
            features,
            family=ModelFamily.RANDOM_FOREST,
        )


def test_source_feature_order_must_match_frozen_contract() -> None:
    """Catch missing, extra or reordered inputs before fitting."""
    features = _features()
    reordered = features.loc[:, tuple(reversed(APPROVED_FEATURE_COLUMNS))]
    with pytest.raises(PreprocessingError, match="ordered contract"):
        fit_model_preprocessor(
            reordered,
            family=ModelFamily.RIDGE,
        )


def test_reserved_missing_category_value_is_rejected() -> None:
    """Protect the explicit missing indicator from value collisions."""
    features = _features()
    features.loc[0, "current_compound"] = MISSING_CATEGORY_TOKEN
    with pytest.raises(PreprocessingError, match="reserved category"):
        fit_model_preprocessor(
            features,
            family=ModelFamily.RANDOM_FOREST,
        )


def test_unknown_model_family_is_rejected() -> None:
    """Keep preprocessing tied to the frozen candidate families."""
    with pytest.raises(PreprocessingError, match="unknown model family"):
        fit_model_preprocessor(
            _features(),
            family="neural_network",
        )
