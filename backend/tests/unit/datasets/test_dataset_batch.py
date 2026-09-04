"""Tests for complete development-dataset batch orchestration."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

import app.datasets.batch as batch_module
from app.cleaning.paths import ProcessedDataPaths
from app.datasets.batch import (
    DatasetBatchError,
    DatasetBatchRunner,
    DatasetBatchRunResult,
    DatasetBatchSessionRecord,
    _build_run_document,
    _publish_global_artifacts,
    _publish_splits,
    _validate_session_keys,
)
from app.datasets.contracts import (
    DATASET_CONTRACT_VERSION,
    EXPECTED_DEVELOPMENT_TOTALS,
    SPLITS_CONTRACT,
)
from app.datasets.paths import DatasetPaths
from app.datasets.runner import DatasetPipelineRunner
from app.datasets.splits import (
    TemporalSplitError,
    build_temporal_splits,
)
from app.pipeline.models import SessionKey
from app.pipeline.serialization import (
    read_json_document,
    read_parquet_table,
    sha256_file,
)


@pytest.fixture
def development_session_keys() -> tuple[
    SessionKey,
    ...,
]:
    """Return the frozen 22/22/24 development schedule."""
    return tuple(
        SessionKey(
            season=season,
            round_number=round_number,
            session_type="R",
        )
        for season, count in (
            (2022, 22),
            (2023, 22),
            (2024, 24),
        )
        for round_number in range(
            1,
            count + 1,
        )
    )


@pytest.fixture
def processed_paths(
    tmp_path: Path,
) -> ProcessedDataPaths:
    """Return isolated processed-data paths."""
    return ProcessedDataPaths(
        tmp_path / "processed"
    )


@pytest.fixture
def dataset_paths(
    tmp_path: Path,
) -> DatasetPaths:
    """Return isolated dataset paths."""
    return DatasetPaths(
        tmp_path / "datasets"
    )


@pytest.fixture
def session_runner(
    processed_paths: ProcessedDataPaths,
    dataset_paths: DatasetPaths,
) -> DatasetPipelineRunner:
    """Return a concrete single-session runner."""
    return DatasetPipelineRunner(
        processed_paths=processed_paths,
        dataset_paths=dataset_paths,
    )


@pytest.fixture
def batch_runner(
    dataset_paths: DatasetPaths,
    session_runner: DatasetPipelineRunner,
) -> DatasetBatchRunner:
    """Return one configured complete batch runner."""
    return DatasetBatchRunner(
        dataset_paths=dataset_paths,
        session_runner=session_runner,
    )


def _record(
    session_key: SessionKey,
    status: str,
    *,
    directory: Path | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
) -> DatasetBatchSessionRecord:
    """Build one concise batch-session record."""
    return DatasetBatchSessionRecord(
        session_key=session_key,
        status=status,  # type: ignore[arg-type]
        duration_seconds=1.25,
        directory=(
            directory
            if directory is not None
            else Path(session_key.identifier)
        ),
        error_type=error_type,
        error_message=error_message,
    )


def _successful_records(
    session_keys: tuple[SessionKey, ...],
) -> tuple[DatasetBatchSessionRecord, ...]:
    """Return successful records for every session."""
    return tuple(
        _record(session_key, "written")
        for session_key in session_keys
    )


def test_session_record_document_is_json_safe(
    development_session_keys: tuple[
        SessionKey,
        ...,
    ],
) -> None:
    """Session records expose complete auditable fields."""
    session_key = development_session_keys[0]
    record = _record(
        session_key,
        "failed",
        directory=Path("dataset/session"),
        error_type="RuntimeError",
        error_message="source failed",
    )

    assert record.to_document() == {
        "session_id": "2022-01-R",
        "season": 2022,
        "round_number": 1,
        "session_type": "R",
        "status": "failed",
        "duration_seconds": 1.25,
        "directory": "dataset/session",
        "error_type": "RuntimeError",
        "error_message": "source failed",
    }


@pytest.mark.parametrize(
    (
        "statuses",
        "expected_written",
        "expected_skipped",
        "expected_failed",
        "artifact_status",
        "expected_succeeded",
    ),
    (
        (
            ("written", "skipped"),
            1,
            1,
            0,
            "published",
            True,
        ),
        (
            ("written", "failed"),
            1,
            0,
            1,
            "not_published",
            False,
        ),
        (
            ("skipped", "skipped"),
            0,
            2,
            0,
            "failed",
            False,
        ),
    ),
)
def test_run_result_properties(
    development_session_keys: tuple[
        SessionKey,
        ...,
    ],
    statuses: tuple[str, ...],
    expected_written: int,
    expected_skipped: int,
    expected_failed: int,
    artifact_status: str,
    expected_succeeded: bool,
) -> None:
    """Batch summaries include both session and publication state."""
    records = tuple(
        _record(session_key, status)
        for session_key, status in zip(
            development_session_keys[
                : len(statuses)
            ],
            statuses,
            strict=True,
        )
    )
    result = DatasetBatchRunResult(
        run_id="run-1",
        records=records,
        record_path=Path("run.json"),
        global_artifact_status=(
            artifact_status  # type: ignore[arg-type]
        ),
    )

    assert result.session_count == 2
    assert result.written_count == expected_written
    assert result.skipped_count == expected_skipped
    assert result.failed_count == expected_failed
    assert result.succeeded is expected_succeeded


def test_batch_runner_accepts_matching_dependencies(
    batch_runner: DatasetBatchRunner,
    dataset_paths: DatasetPaths,
    session_runner: DatasetPipelineRunner,
) -> None:
    """Matching runner and storage roots form a valid batch."""
    assert batch_runner.dataset_paths == dataset_paths
    assert batch_runner.session_runner is session_runner


@pytest.mark.parametrize(
    ("field_name", "invalid", "message"),
    (
        (
            "dataset_paths",
            object(),
            "dataset_paths must be DatasetPaths",
        ),
        (
            "session_runner",
            object(),
            "session_runner must be a DatasetPipelineRunner",
        ),
    ),
)
def test_batch_runner_rejects_invalid_dependencies(
    field_name: str,
    invalid: object,
    message: str,
    dataset_paths: DatasetPaths,
    session_runner: DatasetPipelineRunner,
) -> None:
    """Batch dependencies cannot be arbitrary objects."""
    values: dict[str, object] = {
        "dataset_paths": dataset_paths,
        "session_runner": session_runner,
    }
    values[field_name] = invalid

    with pytest.raises(
        TypeError,
        match=message,
    ):
        DatasetBatchRunner(
            **values  # type: ignore[arg-type]
        )


def test_batch_runner_rejects_path_mismatch(
    tmp_path: Path,
    dataset_paths: DatasetPaths,
    processed_paths: ProcessedDataPaths,
) -> None:
    """Session writes cannot target a different dataset root."""
    session_runner = DatasetPipelineRunner(
        processed_paths=processed_paths,
        dataset_paths=DatasetPaths(
            tmp_path / "other-datasets"
        ),
    )

    with pytest.raises(
        ValueError,
        match=(
            "session runner and batch runner must use "
            "the same dataset paths"
        ),
    ):
        DatasetBatchRunner(
            dataset_paths=dataset_paths,
            session_runner=session_runner,
        )


@pytest.mark.parametrize(
    "invalid",
    ("sessions", b"sessions", 123, None),
)
def test_session_validation_rejects_non_iterables(
    invalid: object,
) -> None:
    """The schedule must be an iterable of SessionKey objects."""
    with pytest.raises(TypeError):
        _validate_session_keys(
            invalid  # type: ignore[arg-type]
        )


def test_session_validation_rejects_empty_schedule() -> None:
    """A complete build cannot operate on no sessions."""
    with pytest.raises(
        DatasetBatchError,
        match="at least one session key is required",
    ):
        _validate_session_keys(())


def test_session_validation_rejects_invalid_item(
    development_session_keys: tuple[
        SessionKey,
        ...,
    ],
) -> None:
    """Every item must carry a validated race identity."""
    invalid = (
        *development_session_keys[:-1],
        object(),
    )

    with pytest.raises(
        TypeError,
        match="every requested session must be a SessionKey",
    ):
        _validate_session_keys(
            invalid  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "season",
    (2021, 2025),
)
def test_session_validation_rejects_non_development_season(
    development_session_keys: tuple[
        SessionKey,
        ...,
    ],
    season: int,
) -> None:
    """Protected and unsupported years never enter a batch."""
    invalid = (
        *development_session_keys[:-1],
        SessionKey(
            season=season,
            round_number=24,
            session_type="R",
        ),
    )

    with pytest.raises(
        DatasetBatchError,
        match="support only seasons",
    ):
        _validate_session_keys(invalid)


def test_session_validation_rejects_duplicates(
    development_session_keys: tuple[
        SessionKey,
        ...,
    ],
) -> None:
    """Duplicate identities cannot inflate schedule coverage."""
    invalid = (
        *development_session_keys,
        development_session_keys[0],
    )

    with pytest.raises(
        DatasetBatchError,
        match="duplicate session keys",
    ):
        _validate_session_keys(invalid)


@pytest.mark.parametrize(
    "session_count",
    (1, 67, 69),
)
def test_session_validation_requires_exact_total(
    development_session_keys: tuple[
        SessionKey,
        ...,
    ],
    session_count: int,
) -> None:
    """Global publication requires exactly 68 sessions."""
    if session_count <= 68:
        invalid = development_session_keys[
            :session_count
        ]
    else:
        invalid = (
            *development_session_keys,
            SessionKey(
                season=2024,
                round_number=25,
                session_type="R",
            ),
        )

    with pytest.raises(
        DatasetBatchError,
        match="requires exactly 68 sessions",
    ):
        _validate_session_keys(invalid)


def test_session_validation_requires_exact_season_counts(
    development_session_keys: tuple[
        SessionKey,
        ...,
    ],
) -> None:
    """A 68-row schedule still needs the frozen 22/22/24 split."""
    invalid = (
        *development_session_keys[:-1],
        SessionKey(
            season=2023,
            round_number=23,
            session_type="R",
        ),
    )

    with pytest.raises(
        DatasetBatchError,
        match="season counts differ from the contract",
    ):
        _validate_session_keys(invalid)


def test_session_validation_sorts_complete_schedule(
    development_session_keys: tuple[
        SessionKey,
        ...,
    ],
) -> None:
    """Batch execution order is deterministic."""
    validated = _validate_session_keys(
        reversed(development_session_keys)
    )

    assert validated == development_session_keys
    assert len(validated) == (
        EXPECTED_DEVELOPMENT_TOTALS.sessions
    )


@pytest.mark.parametrize(
    "force",
    (None, 0, 1, "yes"),
)
def test_batch_rejects_non_boolean_force(
    batch_runner: DatasetBatchRunner,
    development_session_keys: tuple[
        SessionKey,
        ...,
    ],
    force: object,
) -> None:
    """Force must be an explicit boolean."""
    with pytest.raises(
        TypeError,
        match="force must be a boolean",
    ):
        batch_runner.run(
            development_session_keys,
            force=force,  # type: ignore[arg-type]
        )


def test_successful_batch_runs_sorted_sessions_and_publishes(
    batch_runner: DatasetBatchRunner,
    dataset_paths: DatasetPaths,
    development_session_keys: tuple[
        SessionKey,
        ...,
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Successful sessions trigger both global artifacts."""
    calls: list[tuple[str, bool]] = []
    catalog_path = dataset_paths.catalog
    splits_path = dataset_paths.splits

    def fake_run_session(
        runner: DatasetPipelineRunner,
        session_key: SessionKey,
        *,
        force: bool = False,
    ) -> SimpleNamespace:
        calls.append(
            (session_key.identifier, force)
        )
        status = (
            "written"
            if session_key.season != 2024
            else "skipped"
        )
        return SimpleNamespace(
            status=status,
            directory=(
                dataset_paths.for_session(
                    session_key
                ).directory
            ),
        )

    def fake_publish(
        *,
        dataset_paths: DatasetPaths,
        session_keys: tuple[SessionKey, ...],
        records: tuple[
            DatasetBatchSessionRecord,
            ...,
        ],
    ) -> tuple[
        str,
        Path,
        str,
        Path,
        str,
        None,
        None,
    ]:
        assert session_keys == development_session_keys
        assert len(records) == 68
        return (
            "published",
            catalog_path,
            "a" * 64,
            splits_path,
            "b" * 64,
            None,
            None,
        )

    monkeypatch.setattr(
        DatasetPipelineRunner,
        "run_session",
        fake_run_session,
    )
    monkeypatch.setattr(
        batch_module,
        "_publish_global_artifacts",
        fake_publish,
    )

    result = batch_runner.run(
        reversed(development_session_keys),
        force=True,
    )

    assert [
        session_id
        for session_id, _ in calls
    ] == [
        session_key.identifier
        for session_key in development_session_keys
    ]
    assert all(force for _, force in calls)
    assert result.session_count == 68
    assert result.written_count == 44
    assert result.skipped_count == 24
    assert result.failed_count == 0
    assert result.global_artifact_status == "published"
    assert result.catalog_path == catalog_path
    assert result.catalog_sha256 == "a" * 64
    assert result.splits_path == splits_path
    assert result.splits_sha256 == "b" * 64
    assert result.succeeded
    assert result.record_path.is_file()

    document = read_json_document(
        result.record_path
    )
    assert document["run_id"] == result.run_id
    assert document[
        "dataset_contract_version"
    ] == DATASET_CONTRACT_VERSION
    assert document["development_seasons"] == [
        2022,
        2023,
        2024,
    ]
    assert document["force"] is True
    assert document["requested_sessions"] == 68
    assert document["summary"] == {
        "written": 44,
        "skipped": 24,
        "failed": 0,
        "succeeded": True,
    }
    assert document["global_artifacts"] == {
        "status": "published",
        "catalog_path": str(catalog_path),
        "catalog_sha256": "a" * 64,
        "splits_path": str(splits_path),
        "splits_sha256": "b" * 64,
        "error_type": None,
        "error_message": None,
    }
    assert len(document["sessions"]) == 68


def test_batch_continues_after_session_failure(
    batch_runner: DatasetBatchRunner,
    development_session_keys: tuple[
        SessionKey,
        ...,
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One failed race is recorded while later races continue."""
    failed_key = development_session_keys[10]
    attempted: list[SessionKey] = []

    def fake_run_session(
        runner: DatasetPipelineRunner,
        session_key: SessionKey,
        *,
        force: bool = False,
    ) -> SimpleNamespace:
        attempted.append(session_key)

        if session_key == failed_key:
            raise RuntimeError(
                "synthetic session failure"
            )

        return SimpleNamespace(
            status="written",
            directory=Path(
                session_key.identifier
            ),
        )

    def forbidden_global_build(
        *args: object,
        **kwargs: object,
    ) -> object:
        raise AssertionError(
            "global artifacts must not be built"
        )

    monkeypatch.setattr(
        DatasetPipelineRunner,
        "run_session",
        fake_run_session,
    )
    monkeypatch.setattr(
        batch_module,
        "build_temporal_splits",
        forbidden_global_build,
    )

    result = batch_runner.run(
        development_session_keys
    )

    assert attempted == list(
        development_session_keys
    )
    assert result.session_count == 68
    assert result.written_count == 67
    assert result.failed_count == 1
    assert result.global_artifact_status == (
        "not_published"
    )
    assert result.catalog_path is None
    assert result.splits_path is None
    assert not result.succeeded

    failed_record = next(
        record
        for record in result.records
        if record.status == "failed"
    )
    assert failed_record.session_key == failed_key
    assert failed_record.error_type == "RuntimeError"
    assert failed_record.error_message == (
        "synthetic session failure"
    )

    document = read_json_document(
        result.record_path
    )
    assert document["summary"]["failed"] == 1
    assert document["summary"]["succeeded"] is False
    assert document[
        "global_artifacts"
    ]["status"] == "not_published"


def test_global_publication_failure_is_recorded(
    batch_runner: DatasetBatchRunner,
    development_session_keys: tuple[
        SessionKey,
        ...,
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Session success cannot hide a global-artifact failure."""
    def fake_run_session(
        runner: DatasetPipelineRunner,
        session_key: SessionKey,
        *,
        force: bool = False,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            status="skipped",
            directory=Path(
                session_key.identifier
            ),
        )

    monkeypatch.setattr(
        DatasetPipelineRunner,
        "run_session",
        fake_run_session,
    )
    monkeypatch.setattr(
        batch_module,
        "_publish_global_artifacts",
        lambda **kwargs: (
            "failed",
            None,
            None,
            None,
            None,
            "DatasetCatalogError",
            "catalog checksum failed",
        ),
    )

    result = batch_runner.run(
        development_session_keys
    )

    assert result.failed_count == 0
    assert result.skipped_count == 68
    assert result.global_artifact_status == "failed"
    assert result.global_error_type == (
        "DatasetCatalogError"
    )
    assert result.global_error_message == (
        "catalog checksum failed"
    )
    assert not result.succeeded

    document = read_json_document(
        result.record_path
    )
    assert document["summary"]["failed"] == 0
    assert document["summary"]["succeeded"] is False
    assert document[
        "global_artifacts"
    ]["status"] == "failed"


def test_failed_records_block_global_publication(
    dataset_paths: DatasetPaths,
    development_session_keys: tuple[
        SessionKey,
        ...,
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Global builders are never called after a session failure."""
    records = list(
        _successful_records(
            development_session_keys
        )
    )
    records[0] = _record(
        development_session_keys[0],
        "failed",
    )

    monkeypatch.setattr(
        batch_module,
        "build_temporal_splits",
        lambda keys: pytest.fail(
            "splits were built after failure"
        ),
    )

    result = _publish_global_artifacts(
        dataset_paths=dataset_paths,
        session_keys=development_session_keys,
        records=tuple(records),
    )

    assert result == (
        "not_published",
        None,
        None,
        None,
        None,
        None,
        None,
    )


def test_successful_records_publish_splits_then_catalog(
    dataset_paths: DatasetPaths,
    development_session_keys: tuple[
        SessionKey,
        ...,
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Global publication uses validated split and catalog builders."""
    events: list[str] = []
    split_result = build_temporal_splits(
        development_session_keys
    )

    def fake_build_splits(
        keys: tuple[SessionKey, ...],
    ) -> SimpleNamespace:
        assert keys == development_session_keys
        events.append("build-splits")
        return SimpleNamespace(
            splits=split_result.splits
        )

    def fake_publish_splits(
        *,
        dataset_paths: DatasetPaths,
        session_keys: tuple[SessionKey, ...],
        splits: pd.DataFrame,
    ) -> str:
        assert session_keys == development_session_keys
        assert splits.equals(split_result.splits)
        events.append("publish-splits")
        return "b" * 64

    class FakeCatalogBuilder:
        """Record catalog construction without stored sessions."""

        def __init__(
            self,
            paths: DatasetPaths,
        ) -> None:
            assert paths == dataset_paths

        def build(
            self,
            keys: tuple[SessionKey, ...],
        ) -> SimpleNamespace:
            assert keys == development_session_keys
            events.append("publish-catalog")
            return SimpleNamespace(
                path=dataset_paths.catalog,
                sha256="a" * 64,
            )

    monkeypatch.setattr(
        batch_module,
        "build_temporal_splits",
        fake_build_splits,
    )
    monkeypatch.setattr(
        batch_module,
        "_publish_splits",
        fake_publish_splits,
    )
    monkeypatch.setattr(
        batch_module,
        "DatasetCatalogBuilder",
        FakeCatalogBuilder,
    )

    result = _publish_global_artifacts(
        dataset_paths=dataset_paths,
        session_keys=development_session_keys,
        records=_successful_records(
            development_session_keys
        ),
    )

    assert events == [
        "build-splits",
        "publish-splits",
        "publish-catalog",
    ]
    assert result == (
        "published",
        dataset_paths.catalog,
        "a" * 64,
        dataset_paths.splits,
        "b" * 64,
        None,
        None,
    )


def test_global_builder_error_becomes_failed_status(
    dataset_paths: DatasetPaths,
    development_session_keys: tuple[
        SessionKey,
        ...,
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Global exceptions become auditable result fields."""
    def fail_splits(
        keys: tuple[SessionKey, ...],
    ) -> object:
        raise TemporalSplitError(
            "split construction failed"
        )

    monkeypatch.setattr(
        batch_module,
        "build_temporal_splits",
        fail_splits,
    )

    result = _publish_global_artifacts(
        dataset_paths=dataset_paths,
        session_keys=development_session_keys,
        records=_successful_records(
            development_session_keys
        ),
    )

    assert result == (
        "failed",
        None,
        None,
        None,
        None,
        "TemporalSplitError",
        "split construction failed",
    )


def test_catalog_failure_reports_already_published_splits(
    dataset_paths: DatasetPaths,
    development_session_keys: tuple[
        SessionKey,
        ...,
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A partial global failure reports the valid split artifact."""
    split_result = build_temporal_splits(
        development_session_keys
    )

    def publish_splits(
        **kwargs: object,
    ) -> str:
        dataset_paths.splits.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        dataset_paths.splits.write_bytes(
            b"published-splits"
        )
        return sha256_file(
            dataset_paths.splits
        )

    class FailingCatalogBuilder:
        """Raise after the split artifact is published."""

        def __init__(
            self,
            paths: DatasetPaths,
        ) -> None:
            assert paths == dataset_paths

        def build(
            self,
            keys: tuple[SessionKey, ...],
        ) -> object:
            raise RuntimeError(
                "catalog publication failed"
            )

    monkeypatch.setattr(
        batch_module,
        "build_temporal_splits",
        lambda keys: split_result,
    )
    monkeypatch.setattr(
        batch_module,
        "_publish_splits",
        publish_splits,
    )
    monkeypatch.setattr(
        batch_module,
        "DatasetCatalogBuilder",
        FailingCatalogBuilder,
    )

    result = _publish_global_artifacts(
        dataset_paths=dataset_paths,
        session_keys=development_session_keys,
        records=_successful_records(
            development_session_keys
        ),
    )

    assert result[0] == "failed"
    assert result[1] is None
    assert result[2] is None
    assert result[3] == dataset_paths.splits
    assert result[4] == sha256_file(
        dataset_paths.splits
    )
    assert result[5] == "RuntimeError"
    assert result[6] == (
        "catalog publication failed"
    )


def test_split_publication_writes_valid_atomic_artifact(
    dataset_paths: DatasetPaths,
    development_session_keys: tuple[
        SessionKey,
        ...,
    ],
) -> None:
    """Frozen splits survive Parquet readback unchanged."""
    splits = build_temporal_splits(
        development_session_keys
    ).splits

    digest = _publish_splits(
        dataset_paths=dataset_paths,
        session_keys=development_session_keys,
        splits=splits,
    )

    restored = read_parquet_table(
        dataset_paths.splits
    )
    pd.testing.assert_frame_equal(
        restored,
        splits,
    )
    assert list(restored.columns) == [
        column.name
        for column in SPLITS_CONTRACT.columns
    ]
    assert len(restored) == 204
    assert digest == sha256_file(
        dataset_paths.splits
    )
    assert not (
        dataset_paths.version_root
        / ".tmp"
        / SPLITS_CONTRACT.file_name
    ).exists()


def test_split_publication_is_deterministic(
    dataset_paths: DatasetPaths,
    development_session_keys: tuple[
        SessionKey,
        ...,
    ],
) -> None:
    """Equivalent split builds produce identical Parquet bytes."""
    splits = build_temporal_splits(
        development_session_keys
    ).splits

    first_digest = _publish_splits(
        dataset_paths=dataset_paths,
        session_keys=development_session_keys,
        splits=splits,
    )
    second_digest = _publish_splits(
        dataset_paths=dataset_paths,
        session_keys=development_session_keys,
        splits=splits.copy(deep=True),
    )

    assert second_digest == first_digest


def test_invalid_splits_fail_before_publication(
    dataset_paths: DatasetPaths,
    development_session_keys: tuple[
        SessionKey,
        ...,
    ],
) -> None:
    """Invalid split rows cannot reach authoritative storage."""
    invalid = build_temporal_splits(
        development_session_keys
    ).splits.iloc[:-1].copy()

    with pytest.raises(TemporalSplitError):
        _publish_splits(
            dataset_paths=dataset_paths,
            session_keys=development_session_keys,
            splits=invalid,
        )

    assert not dataset_paths.splits.exists()


def test_split_readback_failure_preserves_existing_artifact(
    dataset_paths: DatasetPaths,
    development_session_keys: tuple[
        SessionKey,
        ...,
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A changed readback never replaces the previous split file."""
    splits = build_temporal_splits(
        development_session_keys
    ).splits
    dataset_paths.splits.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    dataset_paths.splits.write_bytes(
        b"previous-splits"
    )
    changed = splits.copy(deep=True)
    changed.loc[0, "role"] = "EXCLUDED"

    monkeypatch.setattr(
        batch_module,
        "read_parquet_table",
        lambda path: changed,
    )

    with pytest.raises(
        DatasetBatchError,
        match="Parquet readback differs",
    ):
        _publish_splits(
            dataset_paths=dataset_paths,
            session_keys=development_session_keys,
            splits=splits,
        )

    assert dataset_paths.splits.read_bytes() == (
        b"previous-splits"
    )
    assert not (
        dataset_paths.version_root
        / ".tmp"
        / SPLITS_CONTRACT.file_name
    ).exists()


def test_split_write_failure_cleans_temporary_file(
    dataset_paths: DatasetPaths,
    development_session_keys: tuple[
        SessionKey,
        ...,
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failed temporary writes leave no misleading artifact."""
    splits = build_temporal_splits(
        development_session_keys
    ).splits
    temporary_path = (
        dataset_paths.version_root
        / ".tmp"
        / SPLITS_CONTRACT.file_name
    )

    def fail_write(
        table: pd.DataFrame,
        path: Path,
    ) -> None:
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        path.write_bytes(b"partial")
        raise OSError("disk full")

    monkeypatch.setattr(
        batch_module,
        "write_parquet_table",
        fail_write,
    )

    with pytest.raises(
        OSError,
        match="disk full",
    ):
        _publish_splits(
            dataset_paths=dataset_paths,
            session_keys=development_session_keys,
            splits=splits,
        )

    assert not temporary_path.exists()
    assert not dataset_paths.splits.exists()


def test_run_document_contains_global_failure(
    development_session_keys: tuple[
        SessionKey,
        ...,
    ],
) -> None:
    """Global errors are preserved independently from session counts."""
    result = DatasetBatchRunResult(
        run_id="run-1",
        records=(
            _record(
                development_session_keys[0],
                "skipped",
            ),
        ),
        record_path=Path("run-1.json"),
        global_artifact_status="failed",
        splits_path=Path("splits.parquet"),
        splits_sha256="b" * 64,
        global_error_type="RuntimeError",
        global_error_message="catalog failed",
    )

    document = _build_run_document(
        result=result,
        started_at_utc="2026-09-04T00:00:00Z",
        completed_at_utc="2026-09-04T00:00:01Z",
        duration_seconds=1.0,
        force=False,
    )

    assert document["summary"] == {
        "written": 0,
        "skipped": 1,
        "failed": 0,
        "succeeded": False,
    }
    assert document["global_artifacts"] == {
        "status": "failed",
        "catalog_path": None,
        "catalog_sha256": None,
        "splits_path": "splits.parquet",
        "splits_sha256": "b" * 64,
        "error_type": "RuntimeError",
        "error_message": "catalog failed",
    }
    assert document["sessions"] == [
        result.records[0].to_document()
    ]