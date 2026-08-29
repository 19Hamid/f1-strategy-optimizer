"""Tests for the single-session raw pipeline runner."""

from pathlib import Path

import pandas as pd
import pytest

from app.pipeline.integrity import (
    IntegrityIssue,
    IntegrityReport,
    SessionIntegrityError,
)
from app.pipeline.models import SessionKey
from app.pipeline.paths import RawDataPaths
from app.pipeline.runner import RawPipelineRunner
from app.pipeline.serialization import write_json_document
from app.pipeline.source import RawSessionData
from app.pipeline.storage import SessionWriteResult


class FakeSource:
    """Record extraction requests without network access."""

    def __init__(
        self,
        raw_session: RawSessionData,
    ) -> None:
        self.raw_session = raw_session
        self.calls: list[SessionKey] = []

    def extract(
        self,
        session_key: SessionKey,
    ) -> RawSessionData:
        self.calls.append(session_key)
        return self.raw_session


class FakeWriter:
    """Record storage requests without writing data."""

    def __init__(
        self,
        result: SessionWriteResult,
    ) -> None:
        self.result = result
        self.calls: list[tuple[RawSessionData, bool]] = []

    def write(
        self,
        raw_session: RawSessionData,
        *,
        force: bool = False,
    ) -> SessionWriteResult:
        self.calls.append((raw_session, force))
        return self.result


def make_empty_raw_session(
    session_key: SessionKey,
) -> RawSessionData:
    """Create lightweight data for isolated runner tests."""
    return RawSessionData(
        session_key=session_key,
        laps=pd.DataFrame(),
        weather=pd.DataFrame(),
        results=pd.DataFrame(),
        metadata={},
    )


def make_runner(
    tmp_path: Path,
) -> tuple[
    RawPipelineRunner,
    FakeSource,
    FakeWriter,
    RawDataPaths,
    SessionKey,
]:
    """Create a runner with isolated fake dependencies."""
    raw_paths = RawDataPaths(tmp_path / "raw")
    session_key = SessionKey(2024, 1)
    raw_session = make_empty_raw_session(session_key)
    source = FakeSource(raw_session)

    write_result = SessionWriteResult(
        status="written",
        directory=raw_paths.for_session(
            session_key
        ).directory,
        manifest={"contract_version": "1.0"},
    )
    writer = FakeWriter(write_result)

    runner = RawPipelineRunner(
        raw_paths=raw_paths,
        source=source,
        writer=writer,
    )

    return (
        runner,
        source,
        writer,
        raw_paths,
        session_key,
    )


def test_extracts_and_writes_missing_session(
    tmp_path: Path,
) -> None:
    (
        runner,
        source,
        writer,
        raw_paths,
        session_key,
    ) = make_runner(tmp_path)

    result = runner.run_session(session_key)

    assert result.status == "written"
    assert source.calls == [session_key]
    assert writer.calls == [
        (source.raw_session, False)
    ]
    assert result.directory == (
        raw_paths.for_session(session_key).directory
    )


def test_skips_valid_existing_session_before_extraction(
    tmp_path: Path,
) -> None:
    (
        runner,
        source,
        writer,
        raw_paths,
        session_key,
    ) = make_runner(tmp_path)

    session_paths = raw_paths.for_session(session_key)
    session_paths.directory.mkdir(
        parents=True,
    )
    manifest = {
        "contract_version": "1.0",
        "session": {
            "identifier": session_key.identifier,
        },
    }
    write_json_document(
        manifest,
        session_paths.manifest,
    )

    checker_calls: list[SessionKey] = []

    def valid_checker(
        checked_paths: RawDataPaths,
        checked_key: SessionKey,
    ) -> IntegrityReport:
        assert checked_paths == raw_paths
        checker_calls.append(checked_key)
        return IntegrityReport(
            session_key=checked_key,
            issues=(),
        )

    runner.integrity_checker = valid_checker

    result = runner.run_session(session_key)

    assert result.status == "skipped"
    assert result.manifest == manifest
    assert checker_calls == [session_key]
    assert source.calls == []
    assert writer.calls == []


def test_rejects_corrupted_existing_session(
    tmp_path: Path,
) -> None:
    (
        runner,
        source,
        writer,
        raw_paths,
        session_key,
    ) = make_runner(tmp_path)

    session_paths = raw_paths.for_session(session_key)
    session_paths.directory.mkdir(
        parents=True,
    )

    def invalid_checker(
        checked_paths: RawDataPaths,
        checked_key: SessionKey,
    ) -> IntegrityReport:
        assert checked_paths == raw_paths
        return IntegrityReport(
            session_key=checked_key,
            issues=(
                IntegrityIssue(
                    code="checksum_mismatch",
                    message="laps.parquet is corrupted",
                ),
            ),
        )

    runner.integrity_checker = invalid_checker

    with pytest.raises(
        SessionIntegrityError,
        match="checksum_mismatch",
    ):
        runner.run_session(session_key)

    assert source.calls == []
    assert writer.calls == []


def test_force_bypasses_existing_integrity_check(
    tmp_path: Path,
) -> None:
    (
        runner,
        source,
        writer,
        raw_paths,
        session_key,
    ) = make_runner(tmp_path)

    session_paths = raw_paths.for_session(session_key)
    session_paths.directory.mkdir(
        parents=True,
    )

    checker_calls: list[SessionKey] = []

    def checker(
        checked_paths: RawDataPaths,
        checked_key: SessionKey,
    ) -> IntegrityReport:
        del checked_paths
        checker_calls.append(checked_key)
        return IntegrityReport(
            session_key=checked_key,
            issues=(),
        )

    runner.integrity_checker = checker

    result = runner.run_session(
        session_key,
        force=True,
    )

    assert result.status == "written"
    assert checker_calls == []
    assert source.calls == [session_key]
    assert writer.calls == [
        (source.raw_session, True)
    ]


def test_rejects_non_boolean_force_value(
    tmp_path: Path,
) -> None:
    runner, _, _, _, session_key = make_runner(tmp_path)

    with pytest.raises(
        TypeError,
        match="force must be a boolean",
    ):
        runner.run_session(
            session_key,
            force="yes",  # type: ignore[arg-type]
        )