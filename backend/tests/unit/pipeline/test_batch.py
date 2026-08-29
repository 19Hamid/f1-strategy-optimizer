"""Tests for multi-session raw pipeline batches."""

from pathlib import Path

import pytest

from app.pipeline.batch import RawBatchRunner
from app.pipeline.models import SessionKey
from app.pipeline.paths import RawDataPaths
from app.pipeline.runner import SessionRunResult
from app.pipeline.serialization import read_json_document


class FakeSessionRunner:
    """Return configured outcomes for selected sessions."""

    def __init__(
        self,
        outcomes: dict[
            SessionKey,
            SessionRunResult | Exception,
        ],
    ) -> None:
        self.outcomes = outcomes
        self.calls: list[tuple[SessionKey, bool]] = []

    def run_session(
        self,
        session_key: SessionKey,
        *,
        force: bool = False,
    ) -> SessionRunResult:
        self.calls.append((session_key, force))
        outcome = self.outcomes[session_key]

        if isinstance(outcome, Exception):
            raise outcome

        return outcome


def make_result(
    tmp_path: Path,
    session_key: SessionKey,
    status: str,
) -> SessionRunResult:
    """Create one fake single-session result."""
    if status not in {"written", "skipped"}:
        raise ValueError("invalid test status")

    return SessionRunResult(
        session_key=session_key,
        status=status,  # type: ignore[arg-type]
        directory=tmp_path / session_key.identifier,
        manifest={"session_id": session_key.identifier},
    )


def test_records_written_skipped_and_failed_sessions(
    tmp_path: Path,
) -> None:
    first = SessionKey(2024, 1)
    second = SessionKey(2024, 2)
    third = SessionKey(2024, 3)

    session_runner = FakeSessionRunner(
        {
            first: make_result(tmp_path, first, "written"),
            second: RuntimeError("download failed"),
            third: make_result(tmp_path, third, "skipped"),
        }
    )

    batch_runner = RawBatchRunner(
        raw_paths=RawDataPaths(tmp_path / "raw"),
        session_runner=session_runner,
        run_id_factory=lambda: "test-run",
    )

    result = batch_runner.run(
        (first, second, third)
    )

    assert result.written_count == 1
    assert result.skipped_count == 1
    assert result.failed_count == 1
    assert result.succeeded is False

    assert [
        record.status
        for record in result.records
    ] == [
        "written",
        "failed",
        "skipped",
    ]

    assert result.records[1].error_type == "RuntimeError"
    assert result.records[1].error_message == "download failed"

    assert session_runner.calls == [
        (first, False),
        (second, False),
        (third, False),
    ]


def test_persists_complete_run_record(
    tmp_path: Path,
) -> None:
    session_key = SessionKey(2024, 1)
    raw_paths = RawDataPaths(tmp_path / "raw")
    session_runner = FakeSessionRunner(
        {
            session_key: make_result(
                tmp_path,
                session_key,
                "written",
            ),
        }
    )

    result = RawBatchRunner(
        raw_paths=raw_paths,
        session_runner=session_runner,
        run_id_factory=lambda: "recorded-run",
    ).run((session_key,))

    document = read_json_document(
        result.record_path
    )

    assert result.record_path == (
        raw_paths.runs_directory
        / "recorded-run.json"
    )
    assert document["run_id"] == "recorded-run"

    summary = document["summary"]
    assert isinstance(summary, dict)
    assert summary == {
        "total": 1,
        "written": 1,
        "skipped": 0,
        "failed": 0,
    }


def test_forwards_force_to_every_session(
    tmp_path: Path,
) -> None:
    first = SessionKey(2024, 1)
    second = SessionKey(2024, 2)
    session_runner = FakeSessionRunner(
        {
            first: make_result(tmp_path, first, "written"),
            second: make_result(tmp_path, second, "written"),
        }
    )

    RawBatchRunner(
        raw_paths=RawDataPaths(tmp_path / "raw"),
        session_runner=session_runner,
        run_id_factory=lambda: "forced-run",
    ).run(
        (first, second),
        force=True,
    )

    assert session_runner.calls == [
        (first, True),
        (second, True),
    ]


def test_rejects_empty_session_selection(
    tmp_path: Path,
) -> None:
    runner = RawBatchRunner(
        raw_paths=RawDataPaths(tmp_path / "raw"),
        session_runner=FakeSessionRunner({}),
    )

    with pytest.raises(
        ValueError,
        match="at least one session",
    ):
        runner.run(())


def test_rejects_duplicate_sessions(
    tmp_path: Path,
) -> None:
    session_key = SessionKey(2024, 1)
    session_runner = FakeSessionRunner(
        {
            session_key: make_result(
                tmp_path,
                session_key,
                "written",
            ),
        }
    )
    runner = RawBatchRunner(
        raw_paths=RawDataPaths(tmp_path / "raw"),
        session_runner=session_runner,
    )

    with pytest.raises(
        ValueError,
        match="must not contain duplicates",
    ):
        runner.run(
            (session_key, session_key)
        )