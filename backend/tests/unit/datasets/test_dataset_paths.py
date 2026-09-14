"""Tests for versioned modelling-dataset paths."""

from pathlib import Path

import pytest

from app.datasets.contracts import (
    DATASET_CONTRACT_VERSION,
    DATASET_DIRECTORY_NAME,
    DATASET_VERSION_DIRECTORY,
)
from app.datasets.paths import (
    DatasetPaths,
    DatasetSessionPaths,
)
from app.pipeline import SessionKey


@pytest.fixture
def session_key() -> SessionKey:
    """Return one development race identity."""
    return SessionKey(
        season=2024,
        round_number=1,
        session_type="R",
    )


@pytest.fixture
def dataset_paths(
    tmp_path: Path,
) -> DatasetPaths:
    """Return isolated top-level dataset paths."""
    return DatasetPaths(
        tmp_path / "data" / "datasets"
    )


@pytest.fixture
def session_paths(
    dataset_paths: DatasetPaths,
    session_key: SessionKey,
) -> DatasetSessionPaths:
    """Return isolated paths for one session."""
    return dataset_paths.for_session(
        session_key
    )


def test_dataset_paths_use_default_contract_version(
    dataset_paths: DatasetPaths,
) -> None:
    """The current executable contract selects the default root."""
    assert (
        dataset_paths.dataset_contract_version
        == DATASET_CONTRACT_VERSION
    )
    assert dataset_paths.dataset_root == (
        dataset_paths.datasets_root
        / DATASET_DIRECTORY_NAME
    )
    assert dataset_paths.version_root == (
        dataset_paths.dataset_root
        / DATASET_VERSION_DIRECTORY
    )


def test_dataset_paths_normalize_root_to_path(
    tmp_path: Path,
) -> None:
    """String-like root input becomes a pathlib path."""
    root = tmp_path / "datasets"
    paths = DatasetPaths(str(root))

    assert isinstance(paths.datasets_root, Path)
    assert paths.datasets_root == root


def test_dataset_paths_expose_global_files(
    dataset_paths: DatasetPaths,
) -> None:
    """Catalog, splits and run records share the version root."""
    assert dataset_paths.catalog == (
        dataset_paths.version_root
        / "catalog.parquet"
    )
    assert dataset_paths.splits == (
        dataset_paths.version_root
        / "splits.parquet"
    )
    assert dataset_paths.runs_directory == (
        dataset_paths.version_root
        / "runs"
    )
    assert dataset_paths.run_record(
        "build-001"
    ) == (
        dataset_paths.runs_directory
        / "build-001.json"
    )


def test_run_record_normalizes_surrounding_whitespace(
    dataset_paths: DatasetPaths,
) -> None:
    """Harmless whitespace does not alter run identity."""
    assert dataset_paths.run_record(
        "  build-001  "
    ) == (
        dataset_paths.runs_directory
        / "build-001.json"
    )


def test_session_partition_uses_two_digit_round(
    session_paths: DatasetSessionPaths,
) -> None:
    """Session partitions match the documented Hive layout."""
    assert session_paths.relative_directory == Path(
        "season=2024",
        "round=01",
        "session=R",
    )
    assert session_paths.directory == (
        session_paths.version_root
        / "season=2024"
        / "round=01"
        / "session=R"
    )


def test_session_paths_share_top_level_configuration(
    dataset_paths: DatasetPaths,
    session_paths: DatasetSessionPaths,
) -> None:
    """Derived session paths retain root and contract version."""
    assert (
        session_paths.datasets_root
        == dataset_paths.datasets_root
    )
    assert (
        session_paths.dataset_contract_version
        == dataset_paths.dataset_contract_version
    )
    assert (
        session_paths.dataset_root
        == dataset_paths.dataset_root
    )
    assert (
        session_paths.version_root
        == dataset_paths.version_root
    )


def test_session_paths_expose_all_authoritative_files(
    session_paths: DatasetSessionPaths,
) -> None:
    """Every contract file has one deterministic location."""
    assert session_paths.decision_rows == (
        session_paths.directory
        / "decision_rows.parquet"
    )
    assert session_paths.decision_labels == (
        session_paths.directory
        / "decision_labels.parquet"
    )
    assert (
        session_paths.pit_duration_observations
        == session_paths.directory
        / "pit_duration_observations.parquet"
    )
    assert session_paths.quality_report == (
        session_paths.directory
        / "quality_report.json"
    )
    assert session_paths.manifest == (
        session_paths.directory
        / "manifest.json"
    )


def test_session_table_mapping_is_complete(
    session_paths: DatasetSessionPaths,
) -> None:
    """Storage can iterate all session tables by stable names."""
    assert session_paths.table_paths == {
        "decision_rows": (
            session_paths.decision_rows
        ),
        "decision_labels": (
            session_paths.decision_labels
        ),
        "pit_duration_observations": (
            session_paths
            .pit_duration_observations
        ),
    }


def test_session_document_mapping_is_complete(
    session_paths: DatasetSessionPaths,
) -> None:
    """Storage can iterate all authoritative JSON documents."""
    assert session_paths.document_paths == {
        "quality_report": (
            session_paths.quality_report
        ),
        "manifest": session_paths.manifest,
    }


def test_temporary_and_backup_paths_are_isolated(
    session_paths: DatasetSessionPaths,
) -> None:
    """Atomic writes never target the authoritative partition."""
    identifier = (
        session_paths.session_key.identifier
    )

    assert session_paths.temporary_directory == (
        session_paths.version_root
        / ".tmp"
        / identifier
    )
    assert session_paths.backup_directory == (
        session_paths.version_root
        / ".backup"
        / identifier
    )
    assert (
        session_paths.temporary_directory
        != session_paths.directory
    )
    assert (
        session_paths.backup_directory
        != session_paths.directory
    )
    assert (
        session_paths.temporary_directory
        != session_paths.backup_directory
    )


def test_path_construction_has_no_filesystem_side_effects(
    tmp_path: Path,
    session_key: SessionKey,
) -> None:
    """Merely resolving paths creates no directories or files."""
    datasets_root = (
        tmp_path / "missing" / "datasets"
    )
    paths = DatasetPaths(datasets_root)
    session = paths.for_session(session_key)

    _ = (
        paths.catalog,
        paths.splits,
        paths.run_record("audit"),
        session.table_paths,
        session.document_paths,
        session.temporary_directory,
        session.backup_directory,
    )

    assert not datasets_root.exists()


def test_different_sessions_have_distinct_directories(
    dataset_paths: DatasetPaths,
) -> None:
    """Season and round identities cannot collide."""
    first = dataset_paths.for_session(
        SessionKey(2022, 1, "R")
    )
    second = dataset_paths.for_session(
        SessionKey(2022, 2, "R")
    )
    third = dataset_paths.for_session(
        SessionKey(2023, 1, "R")
    )

    assert len(
        {
            first.directory,
            second.directory,
            third.directory,
        }
    ) == 3


def test_contract_versions_have_distinct_roots(
    tmp_path: Path,
) -> None:
    """Artifacts from different contracts cannot overwrite each other."""
    current = DatasetPaths(
        tmp_path,
        dataset_contract_version="1.0",
    )
    future = DatasetPaths(
        tmp_path,
        dataset_contract_version="2.0",
    )

    assert current.version_root != future.version_root
    assert current.catalog != future.catalog
    assert current.splits != future.splits


def test_contract_version_is_trimmed(
    tmp_path: Path,
) -> None:
    """Version whitespace is normalized before path construction."""
    paths = DatasetPaths(
        tmp_path,
        dataset_contract_version=" 1.0 ",
    )

    assert paths.dataset_contract_version == "1.0"
    assert paths.version_root.name == (
        "dataset_contract_version=1.0"
    )


@pytest.mark.parametrize(
    "invalid_version",
    [
        "",
        "   ",
        ".",
        "..",
        "versions/1.0",
        "versions\\1.0",
        "/absolute",
    ],
)
def test_dataset_paths_reject_invalid_contract_version(
    tmp_path: Path,
    invalid_version: str,
) -> None:
    """Contract versions cannot escape their path segment."""
    with pytest.raises(ValueError):
        DatasetPaths(
            tmp_path,
            dataset_contract_version=(
                invalid_version
            ),
        )


@pytest.mark.parametrize(
    "invalid_version",
    [None, 1, True, Path("1.0")],
)
def test_dataset_paths_require_string_contract_version(
    tmp_path: Path,
    invalid_version: object,
) -> None:
    """Implicit version coercion is forbidden."""
    with pytest.raises(
        TypeError,
        match="dataset_contract_version must be a string",
    ):
        DatasetPaths(
            tmp_path,
            dataset_contract_version=(  # type: ignore[arg-type]
                invalid_version
            ),
        )


@pytest.mark.parametrize(
    "invalid_run_id",
    [
        "",
        "   ",
        ".",
        "..",
        "runs/build",
        "runs\\build",
        "/absolute",
    ],
)
def test_run_record_rejects_invalid_path_segment(
    dataset_paths: DatasetPaths,
    invalid_run_id: str,
) -> None:
    """Run identities cannot traverse outside the runs directory."""
    with pytest.raises(ValueError):
        dataset_paths.run_record(
            invalid_run_id
        )


@pytest.mark.parametrize(
    "invalid_run_id",
    [None, 1, True, Path("build")],
)
def test_run_record_requires_string_identifier(
    dataset_paths: DatasetPaths,
    invalid_run_id: object,
) -> None:
    """Run identifiers are explicit strings."""
    with pytest.raises(
        TypeError,
        match="run_id must be a string",
    ):
        dataset_paths.run_record(  # type: ignore[arg-type]
            invalid_run_id
        )


def test_for_session_rejects_wrong_type(
    dataset_paths: DatasetPaths,
) -> None:
    """Untyped identities cannot create dataset partitions."""
    with pytest.raises(
        TypeError,
        match="session_key must be a SessionKey",
    ):
        dataset_paths.for_session(  # type: ignore[arg-type]
            "2024-01-R"
        )


def test_for_session_rejects_protected_evaluation_season(
    dataset_paths: DatasetPaths,
) -> None:
    """Resolving a 2025 development path fails before any I/O."""
    with pytest.raises(
        ValueError,
        match="protected evaluation season",
    ):
        dataset_paths.for_session(
            SessionKey(2025, 1, "R")
        )


def test_for_session_rejects_unsupported_season(
    dataset_paths: DatasetPaths,
) -> None:
    """Only frozen development seasons receive partitions."""
    with pytest.raises(
        ValueError,
        match="outside the development seasons",
    ):
        dataset_paths.for_session(
            SessionKey(2021, 1, "R")
        )


def test_direct_session_paths_apply_same_validation(
    tmp_path: Path,
) -> None:
    """Direct construction cannot bypass the protected boundary."""
    with pytest.raises(
        ValueError,
        match="protected evaluation season",
    ):
        DatasetSessionPaths(
            datasets_root=tmp_path,
            dataset_contract_version="1.0",
            session_key=SessionKey(
                2025,
                1,
                "R",
            ),
        )