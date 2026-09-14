"""Tests for single-session modelling-dataset orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest

import app.datasets.runner as runner_module
from app.cleaning.paths import ProcessedDataPaths
from app.datasets.contracts import (
    SOURCE_CLEANING_RULE_VERSION,
    SOURCE_PROCESSED_CONTRACT_VERSION,
)
from app.datasets.paths import DatasetPaths
from app.datasets.runner import (
    DatasetPipelineError,
    DatasetPipelineRunner,
    DatasetSessionRunResult,
    _build_source_reference,
    _require_manifest_text,
)
from app.datasets.storage import (
    DatasetSessionData,
    DatasetSessionWriter,
    DatasetStorageError,
    ProcessedSourceReference,
)
from app.pipeline.models import SessionKey
from app.pipeline.serialization import sha256_file


@dataclass
class _FakeIntegrityReport:
    """Minimal successful processed-integrity result."""

    manifest: dict[str, object] | None
    error: Exception | None = None
    checked: bool = False

    def raise_for_errors(self) -> None:
        """Raise the configured error or record validation."""
        self.checked = True

        if self.error is not None:
            raise self.error


@dataclass
class _FakeValidationReport:
    """Minimal decision or pit-duration validation result."""

    name: str
    events: list[str]
    error: Exception | None = None

    def raise_for_errors(self) -> None:
        """Record validation and raise a configured error."""
        self.events.append(
            f"validate:{self.name}"
        )

        if self.error is not None:
            raise self.error


@pytest.fixture
def session_key() -> SessionKey:
    """Return one supported development race."""
    return SessionKey(
        season=2024,
        round_number=1,
        session_type="R",
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
    """Return isolated modelling-dataset paths."""
    return DatasetPaths(
        tmp_path / "datasets"
    )


@pytest.fixture
def runner(
    processed_paths: ProcessedDataPaths,
    dataset_paths: DatasetPaths,
) -> DatasetPipelineRunner:
    """Return one configured dataset runner."""
    return DatasetPipelineRunner(
        processed_paths=processed_paths,
        dataset_paths=dataset_paths,
    )


def _source_manifest() -> dict[str, object]:
    """Return the required processed provenance fields."""
    return {
        "cleaning_rule_version": (
            SOURCE_CLEANING_RULE_VERSION
        ),
        "processed_contract_version": (
            SOURCE_PROCESSED_CONTRACT_VERSION
        ),
    }


def _create_processed_files(
    processed_paths: ProcessedDataPaths,
    session_key: SessionKey,
) -> None:
    """Create bytes used by real provenance hashing."""
    paths = processed_paths.for_session(
        session_key
    )
    paths.directory.mkdir(
        parents=True,
        exist_ok=True,
    )
    paths.manifest.write_bytes(b"processed-manifest")
    paths.laps.write_bytes(b"processed-laps")
    paths.stints.write_bytes(b"processed-stints")
    paths.pit_events.write_bytes(
        b"processed-pit-events"
    )


def _patch_successful_run(
    monkeypatch: pytest.MonkeyPatch,
    *,
    processed_paths: ProcessedDataPaths,
    dataset_paths: DatasetPaths,
    session_key: SessionKey,
    events: list[str],
    status: str = "written",
) -> dict[str, Any]:
    """Patch collaborators while retaining runner control flow."""
    _create_processed_files(
        processed_paths,
        session_key,
    )
    integrity = _FakeIntegrityReport(
        manifest=_source_manifest()
    )
    source_paths = processed_paths.for_session(
        session_key
    )
    source_tables = {
        source_paths.laps: pd.DataFrame(
            {"source": ["laps"]}
        ),
        source_paths.stints: pd.DataFrame(
            {"source": ["stints"]}
        ),
        source_paths.pit_events: pd.DataFrame(
            {"source": ["pit_events"]}
        ),
    }
    normalized = SimpleNamespace(
        session_key=session_key,
        event_name="Bahrain Grand Prix",
        laps=pd.DataFrame(
            {"lap": [1, 2, 3, 4]}
        ),
    )
    decisions = object()
    pit_durations = object()
    captured: dict[str, Any] = {
        "integrity": integrity,
        "normalized": normalized,
        "decisions": decisions,
        "pit_durations": pit_durations,
    }

    def fake_integrity(
        actual_paths: ProcessedDataPaths,
        actual_key: SessionKey,
    ) -> _FakeIntegrityReport:
        assert actual_paths == processed_paths
        assert actual_key == session_key
        events.append("processed-integrity")
        return integrity

    def fake_read(path: Path) -> pd.DataFrame:
        events.append(f"read:{path.name}")
        return source_tables[path].copy(
            deep=True
        )

    def fake_normalize(
        *,
        laps: pd.DataFrame,
        stints: pd.DataFrame,
        pit_events: pd.DataFrame,
        session_key: SessionKey,
    ) -> SimpleNamespace:
        assert session_key == captured[
            "normalized"
        ].session_key
        assert laps.equals(
            source_tables[source_paths.laps]
        )
        assert stints.equals(
            source_tables[source_paths.stints]
        )
        assert pit_events.equals(
            source_tables[source_paths.pit_events]
        )
        events.append("normalize")
        return normalized

    def fake_build_decisions(
        source: object,
    ) -> object:
        assert source is normalized
        events.append("build-decisions")
        return decisions

    def fake_validate_decisions(
        data: object,
    ) -> _FakeValidationReport:
        assert data is decisions
        events.append("decision-report")
        return _FakeValidationReport(
            "decisions",
            events,
        )

    def fake_build_pits(
        source: object,
    ) -> object:
        assert source is normalized
        events.append("build-pits")
        return pit_durations

    def fake_validate_pits(
        data: object,
    ) -> _FakeValidationReport:
        assert data is pit_durations
        events.append("pit-report")
        return _FakeValidationReport(
            "pits",
            events,
        )

    def fake_write(
        writer: DatasetSessionWriter,
        data: DatasetSessionData,
        *,
        force: bool = False,
    ) -> SimpleNamespace:
        assert writer.dataset_paths == dataset_paths
        events.append("write")
        captured["data"] = data
        captured["force"] = force
        return SimpleNamespace(
            status=status,
            directory=(
                dataset_paths.for_session(
                    session_key
                ).directory
            ),
        )

    final_manifest = {
        "dataset_contract_version": "1.0"
    }
    final_quality = {
        "validation": {"status": "passed"}
    }

    def fake_final_validation(
        session_paths: object,
    ) -> tuple[
        dict[str, object],
        dict[str, object],
    ]:
        assert (
            session_paths.directory
            == dataset_paths.for_session(
                session_key
            ).directory
        )
        events.append("final-validation")
        return final_manifest, final_quality

    monkeypatch.setattr(
        runner_module,
        "verify_processed_partition",
        fake_integrity,
    )
    monkeypatch.setattr(
        runner_module,
        "read_parquet_table",
        fake_read,
    )
    monkeypatch.setattr(
        runner_module,
        "normalize_processed_session_tables",
        fake_normalize,
    )
    monkeypatch.setattr(
        runner_module,
        "build_session_decisions",
        fake_build_decisions,
    )
    monkeypatch.setattr(
        runner_module,
        "validate_decision_session",
        fake_validate_decisions,
    )
    monkeypatch.setattr(
        runner_module,
        "build_pit_duration_observations",
        fake_build_pits,
    )
    monkeypatch.setattr(
        runner_module,
        "validate_pit_duration_session",
        fake_validate_pits,
    )
    monkeypatch.setattr(
        DatasetSessionWriter,
        "write",
        fake_write,
    )
    monkeypatch.setattr(
        runner_module,
        "_validate_completed_partition",
        fake_final_validation,
    )

    captured["manifest"] = final_manifest
    captured["quality_report"] = final_quality
    return captured


def test_runner_creates_default_writer(
    runner: DatasetPipelineRunner,
    dataset_paths: DatasetPaths,
) -> None:
    """The runner constructs its atomic writer by default."""
    assert isinstance(
        runner.writer,
        DatasetSessionWriter,
    )
    assert runner.writer.dataset_paths == dataset_paths


@pytest.mark.parametrize(
    ("field_name", "invalid", "message"),
    (
        (
            "processed_paths",
            object(),
            "processed_paths must be ProcessedDataPaths",
        ),
        (
            "dataset_paths",
            object(),
            "dataset_paths must be DatasetPaths",
        ),
    ),
)
def test_runner_rejects_invalid_paths(
    field_name: str,
    invalid: object,
    message: str,
    processed_paths: ProcessedDataPaths,
    dataset_paths: DatasetPaths,
) -> None:
    """Runner path dependencies are concrete path objects."""
    values: dict[str, object] = {
        "processed_paths": processed_paths,
        "dataset_paths": dataset_paths,
    }
    values[field_name] = invalid

    with pytest.raises(
        TypeError,
        match=message,
    ):
        DatasetPipelineRunner(
            **values  # type: ignore[arg-type]
        )


def test_runner_rejects_invalid_writer(
    processed_paths: ProcessedDataPaths,
    dataset_paths: DatasetPaths,
) -> None:
    """Arbitrary writer objects cannot bypass storage checks."""
    with pytest.raises(
        TypeError,
        match="writer must be a DatasetSessionWriter",
    ):
        DatasetPipelineRunner(
            processed_paths=processed_paths,
            dataset_paths=dataset_paths,
            writer=object(),  # type: ignore[arg-type]
        )


def test_runner_rejects_writer_path_mismatch(
    tmp_path: Path,
    processed_paths: ProcessedDataPaths,
    dataset_paths: DatasetPaths,
) -> None:
    """A writer cannot publish under a different root."""
    writer = DatasetSessionWriter(
        DatasetPaths(
            tmp_path / "other-datasets"
        )
    )

    with pytest.raises(
        ValueError,
        match="writer and runner must use the same dataset paths",
    ):
        DatasetPipelineRunner(
            processed_paths=processed_paths,
            dataset_paths=dataset_paths,
            writer=writer,
        )


def test_run_rejects_invalid_session_key(
    runner: DatasetPipelineRunner,
) -> None:
    """Session construction requires a SessionKey."""
    with pytest.raises(
        TypeError,
        match="session_key must be a SessionKey",
    ):
        runner.run_session(  # type: ignore[arg-type]
            object()
        )


@pytest.mark.parametrize(
    "season",
    (2021, 2025),
)
def test_run_rejects_non_development_season_before_access(
    season: int,
    runner: DatasetPipelineRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unsupported seasons fail before source or target access."""
    accessed = False

    def fail_on_access(*args: object) -> object:
        nonlocal accessed
        accessed = True
        raise AssertionError(
            "protected source was accessed"
        )

    monkeypatch.setattr(
        runner_module,
        "verify_processed_partition",
        fail_on_access,
    )

    with pytest.raises(
        DatasetPipelineError,
        match="supports only development seasons",
    ):
        runner.run_session(
            SessionKey(
                season=season,
                round_number=1,
                session_type="R",
            )
        )

    assert accessed is False


@pytest.mark.parametrize(
    "force",
    (None, 0, 1, "yes"),
)
def test_run_rejects_non_boolean_force(
    runner: DatasetPipelineRunner,
    session_key: SessionKey,
    force: object,
) -> None:
    """Force must be an explicit boolean switch."""
    with pytest.raises(
        TypeError,
        match="force must be a boolean",
    ):
        runner.run_session(
            session_key,
            force=force,  # type: ignore[arg-type]
        )


def test_existing_valid_partition_is_verified_and_skipped(
    runner: DatasetPipelineRunner,
    dataset_paths: DatasetPaths,
    session_key: SessionKey,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A valid completed target skips all processed reads."""
    paths = dataset_paths.for_session(
        session_key
    )
    paths.directory.mkdir(
        parents=True
    )
    paths.manifest.write_text(
        "{}",
        encoding="utf-8",
    )
    manifest = {"stored": True}
    quality_report = {"validation": "passed"}
    validation_calls = 0

    def fake_validation(
        actual_paths: object,
    ) -> tuple[
        dict[str, object],
        dict[str, object],
    ]:
        nonlocal validation_calls
        validation_calls += 1
        assert actual_paths.directory == paths.directory
        return manifest, quality_report

    def forbidden_source_access(*args: object) -> object:
        raise AssertionError(
            "processed source should not be accessed"
        )

    monkeypatch.setattr(
        runner_module,
        "_validate_completed_partition",
        fake_validation,
    )
    monkeypatch.setattr(
        runner_module,
        "verify_processed_partition",
        forbidden_source_access,
    )

    result = runner.run_session(
        session_key
    )

    assert result == DatasetSessionRunResult(
        status="skipped",
        session_key=session_key,
        directory=paths.directory,
        manifest=manifest,
        quality_report=quality_report,
    )
    assert validation_calls == 1


def test_existing_incomplete_partition_fails_closed(
    runner: DatasetPipelineRunner,
    dataset_paths: DatasetPaths,
    session_key: SessionKey,
) -> None:
    """A directory without a manifest cannot be skipped."""
    paths = dataset_paths.for_session(
        session_key
    )
    paths.directory.mkdir(
        parents=True
    )

    with pytest.raises(
        DatasetPipelineError,
        match="exists without a completed manifest",
    ):
        runner.run_session(session_key)


def test_existing_invalid_partition_fails_closed(
    runner: DatasetPipelineRunner,
    dataset_paths: DatasetPaths,
    session_key: SessionKey,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An invalid completed target requires an explicit rebuild."""
    paths = dataset_paths.for_session(
        session_key
    )
    paths.directory.mkdir(
        parents=True
    )
    paths.manifest.write_text(
        "{}",
        encoding="utf-8",
    )

    def fail_validation(
        actual_paths: object,
    ) -> tuple[
        dict[str, object],
        dict[str, object],
    ]:
        raise DatasetStorageError(
            "checksum mismatch"
        )

    monkeypatch.setattr(
        runner_module,
        "_validate_completed_partition",
        fail_validation,
    )

    with pytest.raises(
        DatasetPipelineError,
        match=(
            "existing dataset partition failed integrity.*"
            "Use force=True"
        ),
    ):
        runner.run_session(session_key)


def test_successful_run_executes_complete_pipeline(
    runner: DatasetPipelineRunner,
    processed_paths: ProcessedDataPaths,
    dataset_paths: DatasetPaths,
    session_key: SessionKey,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every construction and validation boundary executes in order."""
    events: list[str] = []
    captured = _patch_successful_run(
        monkeypatch,
        processed_paths=processed_paths,
        dataset_paths=dataset_paths,
        session_key=session_key,
        events=events,
    )

    result = runner.run_session(
        session_key
    )

    assert events == [
        "processed-integrity",
        "read:laps.parquet",
        "read:stints.parquet",
        "read:pit_events.parquet",
        "normalize",
        "build-decisions",
        "decision-report",
        "validate:decisions",
        "build-pits",
        "pit-report",
        "validate:pits",
        "write",
        "final-validation",
    ]
    assert captured["integrity"].checked is True
    assert captured["force"] is False
    assert result.status == "written"
    assert result.session_key == session_key
    assert result.manifest is captured["manifest"]
    assert (
        result.quality_report
        is captured["quality_report"]
    )


def test_successful_run_builds_exact_storage_input(
    runner: DatasetPipelineRunner,
    processed_paths: ProcessedDataPaths,
    dataset_paths: DatasetPaths,
    session_key: SessionKey,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The writer receives tables, counts and immutable provenance."""
    captured = _patch_successful_run(
        monkeypatch,
        processed_paths=processed_paths,
        dataset_paths=dataset_paths,
        session_key=session_key,
        events=[],
    )

    runner.run_session(session_key)
    data = captured["data"]

    assert isinstance(data, DatasetSessionData)
    assert data.source_lap_count == 4
    assert data.decisions is captured["decisions"]
    assert (
        data.pit_durations
        is captured["pit_durations"]
    )
    assert isinstance(
        data.source,
        ProcessedSourceReference,
    )

    source_paths = processed_paths.for_session(
        session_key
    )
    assert data.source.session_directory == str(
        source_paths.directory
    )
    assert data.source.manifest_sha256 == sha256_file(
        source_paths.manifest
    )
    assert data.source.laps_sha256 == sha256_file(
        source_paths.laps
    )
    assert data.source.stints_sha256 == sha256_file(
        source_paths.stints
    )
    assert (
        data.source.pit_events_sha256
        == sha256_file(
            source_paths.pit_events
        )
    )


def test_force_bypasses_existing_partition_and_rebuilds(
    runner: DatasetPipelineRunner,
    processed_paths: ProcessedDataPaths,
    dataset_paths: DatasetPaths,
    session_key: SessionKey,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Force rebuild does not accept an existing partition as a skip."""
    target_paths = dataset_paths.for_session(
        session_key
    )
    target_paths.directory.mkdir(
        parents=True
    )
    target_paths.manifest.write_text(
        "invalid old manifest",
        encoding="utf-8",
    )
    captured = _patch_successful_run(
        monkeypatch,
        processed_paths=processed_paths,
        dataset_paths=dataset_paths,
        session_key=session_key,
        events=[],
    )

    result = runner.run_session(
        session_key,
        force=True,
    )

    assert result.status == "written"
    assert captured["force"] is True


def test_processed_integrity_failure_stops_before_reads(
    runner: DatasetPipelineRunner,
    session_key: SessionKey,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invalid processed input cannot reach normalization."""
    integrity = _FakeIntegrityReport(
        manifest=None,
        error=RuntimeError(
            "processed checksum failed"
        ),
    )

    monkeypatch.setattr(
        runner_module,
        "verify_processed_partition",
        lambda *args: integrity,
    )
    monkeypatch.setattr(
        runner_module,
        "read_parquet_table",
        lambda path: pytest.fail(
            "invalid processed data was read"
        ),
    )

    with pytest.raises(
        RuntimeError,
        match="processed checksum failed",
    ):
        runner.run_session(session_key)

    assert integrity.checked is True


def test_missing_processed_manifest_fails_closed(
    runner: DatasetPipelineRunner,
    session_key: SessionKey,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A supposedly valid source must still expose its manifest."""
    integrity = _FakeIntegrityReport(
        manifest=None
    )
    monkeypatch.setattr(
        runner_module,
        "verify_processed_partition",
        lambda *args: integrity,
    )

    with pytest.raises(
        DatasetPipelineError,
        match="valid processed partition has no manifest",
    ):
        runner.run_session(session_key)


@pytest.mark.parametrize(
    "field",
    (
        "cleaning_rule_version",
        "processed_contract_version",
    ),
)
@pytest.mark.parametrize(
    "invalid",
    (None, 1, "", "   "),
)
def test_manifest_text_must_be_non_empty(
    field: str,
    invalid: object,
) -> None:
    """Processed provenance fields cannot be silently coerced."""
    manifest = _source_manifest()
    manifest[field] = invalid

    with pytest.raises(
        DatasetPipelineError,
        match=f"processed manifest {field}",
    ):
        _require_manifest_text(
            manifest,
            field,
        )


def test_source_reference_hashes_exact_files(
    tmp_path: Path,
) -> None:
    """Source provenance uses the bytes actually consumed."""
    directory = tmp_path / "source"
    directory.mkdir()
    paths = {
        "manifest": directory / "manifest.json",
        "laps": directory / "laps.parquet",
        "stints": directory / "stints.parquet",
        "pits": directory / "pit_events.parquet",
    }

    for name, path in paths.items():
        path.write_bytes(
            f"{name}-content".encode()
        )

    reference = _build_source_reference(
        manifest=_source_manifest(),
        directory=directory,
        manifest_path=paths["manifest"],
        laps_path=paths["laps"],
        stints_path=paths["stints"],
        pit_events_path=paths["pits"],
    )

    assert reference.session_directory == str(
        directory
    )
    assert reference.manifest_sha256 == sha256_file(
        paths["manifest"]
    )
    assert reference.laps_sha256 == sha256_file(
        paths["laps"]
    )
    assert reference.stints_sha256 == sha256_file(
        paths["stints"]
    )
    assert reference.pit_events_sha256 == sha256_file(
        paths["pits"]
    )


def test_writer_failure_does_not_run_final_validation(
    runner: DatasetPipelineRunner,
    processed_paths: ProcessedDataPaths,
    dataset_paths: DatasetPaths,
    session_key: SessionKey,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed atomic write is never reported as complete."""
    events: list[str] = []
    _patch_successful_run(
        monkeypatch,
        processed_paths=processed_paths,
        dataset_paths=dataset_paths,
        session_key=session_key,
        events=events,
    )

    def fail_write(
        writer: DatasetSessionWriter,
        data: DatasetSessionData,
        *,
        force: bool = False,
    ) -> object:
        events.append("write-failed")
        raise DatasetStorageError(
            "atomic publication failed"
        )

    monkeypatch.setattr(
        DatasetSessionWriter,
        "write",
        fail_write,
    )

    with pytest.raises(
        DatasetStorageError,
        match="atomic publication failed",
    ):
        runner.run_session(session_key)

    assert "final-validation" not in events


def test_final_validation_failure_is_propagated(
    runner: DatasetPipelineRunner,
    processed_paths: ProcessedDataPaths,
    dataset_paths: DatasetPaths,
    session_key: SessionKey,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Success requires validation of the authoritative output."""
    _patch_successful_run(
        monkeypatch,
        processed_paths=processed_paths,
        dataset_paths=dataset_paths,
        session_key=session_key,
        events=[],
    )

    def fail_final_validation(
        session_paths: object,
    ) -> tuple[
        dict[str, object],
        dict[str, object],
    ]:
        raise DatasetStorageError(
            "final checksum failed"
        )

    monkeypatch.setattr(
        runner_module,
        "_validate_completed_partition",
        fail_final_validation,
    )

    with pytest.raises(
        DatasetStorageError,
        match="final checksum failed",
    ):
        runner.run_session(session_key)


def test_missing_writer_fails_before_publication(
    runner: DatasetPipelineRunner,
    processed_paths: ProcessedDataPaths,
    dataset_paths: DatasetPaths,
    session_key: SessionKey,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The defensive unavailable-writer branch fails closed."""
    _patch_successful_run(
        monkeypatch,
        processed_paths=processed_paths,
        dataset_paths=dataset_paths,
        session_key=session_key,
        events=[],
    )
    object.__setattr__(
        runner,
        "writer",
        None,
    )

    with pytest.raises(
        DatasetPipelineError,
        match="dataset writer is unavailable",
    ):
        runner.run_session(session_key)