"""Tests for validating one stored dataset session partition."""

from pathlib import Path

import pytest

import app.datasets.integrity as dataset_integrity
from app.datasets import (
    DATASET_CONTRACT_VERSION,
    DatasetPaths,
    validate_dataset_session_partition,
)
from app.pipeline import SessionKey


def test_dataset_session_validator_returns_verified_documents(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Expose the existing strict storage validator as a public boundary."""
    dataset_paths = DatasetPaths(tmp_path)
    session_key = SessionKey(2024, 3, "R")
    expected_manifest = {"dataset_contract_version": "1.0"}
    expected_report = {"validation": {"status": "passed"}}
    captured_paths: list[object] = []

    def fake_validate(session_paths: object) -> tuple[dict, dict]:
        captured_paths.append(session_paths)
        return expected_manifest, expected_report

    monkeypatch.setattr(
        dataset_integrity,
        "_validate_completed_partition",
        fake_validate,
    )

    manifest, report = validate_dataset_session_partition(
        dataset_paths,
        session_key,
    )

    assert manifest is expected_manifest
    assert report is expected_report
    assert len(captured_paths) == 1
    session_paths = captured_paths[0]
    assert session_paths.session_key == session_key
    assert (
        session_paths.dataset_contract_version
        == DATASET_CONTRACT_VERSION
    )


@pytest.mark.parametrize(
    ("dataset_paths", "session_key", "message"),
    [
        (object(), SessionKey(2024, 3, "R"), "dataset_paths"),
        (DatasetPaths(Path("datasets")), object(), "session_key"),
    ],
)
def test_dataset_session_validator_rejects_invalid_arguments(
    dataset_paths: object,
    session_key: object,
    message: str,
) -> None:
    """Reject values that cannot identify a dataset partition."""
    with pytest.raises(TypeError, match=message):
        validate_dataset_session_partition(
            dataset_paths,  # type: ignore[arg-type]
            session_key,  # type: ignore[arg-type]
        )
