"""Tests for immutable, reproducible Phase 6 model artifacts."""

import json

import numpy as np
import pandas as pd
import pytest

from app.ml import (
    APPROVED_FEATURE_COLUMNS,
    MODEL_CONTRACT_VERSION,
    NUMERIC_FEATURE_COLUMNS,
    FoldTrainingMatrix,
    ModelFamily,
    ModelTarget,
    TrainingMatrixPartition,
    model_spec,
    train_candidate_model,
)
from app.ml.artifacts import (
    MODEL_ARTIFACT_FILES,
    MODEL_ARTIFACT_FORMAT_VERSION,
    LoadedModelArtifact,
    ModelArtifactError,
    ModelArtifactPaths,
    load_model_artifact,
    model_artifact_provenance,
    runtime_model_dependency_versions,
    verify_model_artifact,
    write_model_artifact,
)


def _features(rows: int, *, offset: int = 0) -> pd.DataFrame:
    """Build an exact source feature frame with deterministic variation."""
    records: list[dict[str, object]] = []
    for index in range(rows):
        value = index + offset
        record: dict[str, object] = {
            column: float(value + column_index + 1)
            for column_index, column in enumerate(NUMERIC_FEATURE_COLUMNS)
        }
        record.update(
            {
                "event_name": ("Bahrain GP", "Saudi GP")[value % 2],
                "driver": ("HAM", "LEC", "RUS")[value % 3],
                "team": ("Ferrari", "Mercedes")[value % 2],
                "current_compound": ("SOFT", "MEDIUM", "HARD")[value % 3],
                "previous_lap_was_target_eligible": value % 2 == 0,
            }
        )
        records.append(record)
    return pd.DataFrame.from_records(records, columns=APPROVED_FEATURE_COLUMNS)


def _partition(
    rows: int,
    *,
    season: int,
    prefix: str,
    offset: int,
) -> TrainingMatrixPartition:
    """Build one aligned synthetic primary-target partition."""
    features = _features(rows, offset=offset)
    target = (
        70.0
        + features["decision_lap"] * 0.2
        + features["tyre_age_laps"] * 0.05
    )
    return TrainingMatrixPartition(
        identities=pd.DataFrame(
            {
                "decision_id": [f"{prefix}-{index}" for index in range(rows)],
                "session_id": [f"{season}-01-R"] * rows,
                "season": [season] * rows,
            }
        ),
        features=features,
        target=target.astype("float64").rename("lap_time_target_seconds"),
    )


def _matrix() -> FoldTrainingMatrix:
    """Build one chronological fold for artifact tests."""
    return FoldTrainingMatrix(
        fold_id="development_fold_1",
        target=ModelTarget.LAP_TIME,
        training=_partition(
            12,
            season=2022,
            prefix="train",
            offset=0,
        ),
        validation=_partition(
            5,
            season=2023,
            prefix="validation",
            offset=20,
        ),
    )


def _trained_model(*, candidate_index: int = 0):
    """Fit one fast deterministic Ridge candidate."""
    parameters = dict(
        model_spec(ModelFamily.RIDGE).parameter_grid[candidate_index]
    )
    return train_candidate_model(
        _matrix(),
        family=ModelFamily.RIDGE,
        parameters=parameters,
    ).model


def _provenance(model):
    """Build complete development-only provenance for a fitted model."""
    return model_artifact_provenance(
        model,
        dataset_contract_version="1.0",
        dataset_build_identifier="unit-test-build",
        training_session_ids=("2022-01-R",),
        training_seasons=(2022,),
        validation_session_ids=("2023-01-R",),
        fit_duration_seconds=0.25,
    )


def test_model_artifact_round_trip_reproduces_predictions(tmp_path) -> None:
    """Reload the estimator and preprocessing as one verified bundle."""
    model = _trained_model()
    features = _matrix().validation.features.iloc[:3].reset_index(drop=True)
    expected = model.predict(features)
    paths = ModelArtifactPaths(tmp_path, "ridge-primary")

    manifest = write_model_artifact(
        paths=paths,
        model=model,
        provenance=_provenance(model),
        verification_features=features,
    )
    loaded = load_model_artifact(paths)

    assert isinstance(loaded, LoadedModelArtifact)
    assert np.array_equal(loaded.predict(features), expected)
    assert loaded.provenance.model_contract_version == MODEL_CONTRACT_VERSION
    assert manifest["format_version"] == MODEL_ARTIFACT_FORMAT_VERSION
    assert set(manifest["artifacts"]) == set(MODEL_ARTIFACT_FILES)


def test_verification_reports_exact_artifact_and_row_counts(tmp_path) -> None:
    """Expose compact successful integrity evidence."""
    model = _trained_model()
    paths = ModelArtifactPaths(tmp_path, "verified")
    write_model_artifact(
        paths=paths,
        model=model,
        provenance=_provenance(model),
        verification_features=_matrix().validation.features.iloc[:2],
    )

    report = verify_model_artifact(paths)

    assert report.valid is True
    assert report.artifact_count == 3
    assert report.verification_rows == 2
    assert report.issues == ()


def test_hash_tampering_is_detected_before_model_loading(tmp_path) -> None:
    """Fail closed when any payload differs from its manifest."""
    model = _trained_model()
    paths = ModelArtifactPaths(tmp_path, "tampered")
    write_model_artifact(
        paths=paths,
        model=model,
        provenance=_provenance(model),
        verification_features=_matrix().validation.features.iloc[:2],
    )
    with (paths.root / "verification.parquet").open("ab") as stream:
        stream.write(b"tampered")

    report = verify_model_artifact(paths)

    assert report.valid is False
    assert any("mismatch: verification.parquet" in issue for issue in report.issues)
    with pytest.raises(ModelArtifactError, match="verification failed"):
        load_model_artifact(paths)


def test_existing_artifact_is_immutable(tmp_path) -> None:
    """Reject replacement instead of silently changing a model identity."""
    model = _trained_model()
    paths = ModelArtifactPaths(tmp_path, "immutable")
    arguments = {
        "paths": paths,
        "model": model,
        "provenance": _provenance(model),
        "verification_features": _matrix().validation.features.iloc[:2],
    }
    write_model_artifact(**arguments)

    with pytest.raises(ModelArtifactError, match="already exists"):
        write_model_artifact(**arguments)


@pytest.mark.parametrize("artifact_id", ("", ".", "../escape", "a/b"))
def test_artifact_identity_rejects_unsafe_paths(
    tmp_path,
    artifact_id: str,
) -> None:
    """Keep generated files inside the canonical model root."""
    with pytest.raises(ModelArtifactError, match="safe path segment"):
        ModelArtifactPaths(tmp_path, artifact_id)


def test_provenance_rejects_protected_training_season() -> None:
    """Prevent a serialized model from claiming protected data as training."""
    model = _trained_model()
    with pytest.raises(ModelArtifactError, match="protected 2025"):
        model_artifact_provenance(
            model,
            dataset_contract_version="1.0",
            dataset_build_identifier="bad-build",
            training_session_ids=("2025-01-R",),
            training_seasons=(2025,),
        )


def test_model_and_provenance_must_reconcile(tmp_path) -> None:
    """Reject a bundle whose JSON describes a different fitted candidate."""
    first = _trained_model(candidate_index=0)
    second = _trained_model(candidate_index=1)
    with pytest.raises(ModelArtifactError, match="model and provenance differ"):
        write_model_artifact(
            paths=ModelArtifactPaths(tmp_path, "mismatch"),
            model=second,
            provenance=_provenance(first),
            verification_features=_matrix().validation.features.iloc[:2],
        )


def test_verification_features_require_exact_source_contract(tmp_path) -> None:
    """Do not create a fingerprint from incomplete inference inputs."""
    model = _trained_model()
    invalid = _matrix().validation.features.drop(columns="team")
    with pytest.raises(ModelArtifactError, match="source schema"):
        write_model_artifact(
            paths=ModelArtifactPaths(tmp_path, "bad-schema"),
            model=model,
            provenance=_provenance(model),
            verification_features=invalid,
        )


def test_runtime_dependency_versions_are_complete_and_canonical() -> None:
    """Record every runtime capable of changing serialized predictions."""
    dependencies = runtime_model_dependency_versions()
    assert dependencies == tuple(sorted(dependencies))
    assert {name for name, _ in dependencies} == {
        "joblib",
        "numpy",
        "pandas",
        "python",
        "scikit-learn",
    }


def test_provenance_json_is_stable_and_complete(tmp_path) -> None:
    """Keep human-readable model identity beside the opaque binary."""
    model = _trained_model()
    paths = ModelArtifactPaths(tmp_path, "provenance")
    write_model_artifact(
        paths=paths,
        model=model,
        provenance=_provenance(model),
        verification_features=_matrix().validation.features.iloc[:2],
    )

    document = json.loads(
        (paths.root / "provenance.json").read_text(encoding="utf-8")
    )
    assert document["candidate_id"] == "ridge_01"
    assert document["training_seasons"] == [2022]
    assert document["validation_session_ids"] == ["2023-01-R"]
    assert document["feature_columns"] == list(APPROVED_FEATURE_COLUMNS)
