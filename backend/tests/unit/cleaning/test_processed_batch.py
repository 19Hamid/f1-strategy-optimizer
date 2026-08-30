"""Tests for processed development-batch execution."""

from pathlib import Path

import pytest

from app.cleaning.batch import (
    ProcessedBatchRunner,
)
from app.cleaning.paths import ProcessedDataPaths
from app.cleaning.runner import (
    ProcessedPipelineRunner,
    ProcessedSessionRunResult,
)
from app.pipeline.models import SessionKey
from app.pipeline.paths import RawDataPaths
from app.pipeline.serialization import (
    read_json_document,
)


def make_batch_runner(
    tmp_path: Path,
) -> ProcessedBatchRunner:
    """Build one isolated processed batch runner."""
    processed_paths = ProcessedDataPaths(
        tmp_path / "processed"
    )
    session_runner = ProcessedPipelineRunner(
        raw_paths=RawDataPaths(
            tmp_path / "raw"
        ),
        processed_paths=processed_paths,
    )

    return ProcessedBatchRunner(
        processed_paths=processed_paths,
        session_runner=session_runner,
    )


def make_run_result(
    *,
    runner: ProcessedPipelineRunner,
    session_key: SessionKey,
    status: str,
) -> ProcessedSessionRunResult:
    """Build one simulated session-run result."""
    assert status in {
        "written",
        "skipped",
    }

    return ProcessedSessionRunResult(
        status=status,  # type: ignore[arg-type]
        session_key=session_key,
        directory=(
            runner.processed_paths
            .for_session(session_key)
            .directory
        ),
        manifest={
            "session": {
                "identifier": (
                    session_key.identifier
                ),
            }
        },
    )


def test_records_successful_batch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Written and skipped sessions must be summarized."""
    batch_runner = make_batch_runner(
        tmp_path
    )
    session_keys = (
        SessionKey(2022, 1),
        SessionKey(2022, 2),
    )

    def fake_run_session(
        runner: ProcessedPipelineRunner,
        session_key: SessionKey,
        *,
        force: bool = False,
    ) -> ProcessedSessionRunResult:
        assert not force

        status = (
            "written"
            if session_key.round_number == 1
            else "skipped"
        )

        return make_run_result(
            runner=runner,
            session_key=session_key,
            status=status,
        )

    monkeypatch.setattr(
        ProcessedPipelineRunner,
        "run_session",
        fake_run_session,
    )

    result = batch_runner.run(
        session_keys
    )

    assert result.session_count == 2
    assert result.written_count == 1
    assert result.skipped_count == 1
    assert result.failed_count == 0
    assert result.succeeded
    assert result.record_path.is_file()
    assert (
        result.record_path.parent
        == batch_runner.processed_paths.runs_directory
    )
    assert (
        result.record_path.stem
        == result.run_id
    )

    assert [
        record.session_key
        for record in result.records
    ] == list(session_keys)

    assert all(
        record.duration_seconds >= 0
        for record in result.records
    )

    document = read_json_document(
        result.record_path
    )

    assert document["run_id"] == result.run_id
    assert document["requested_sessions"] == 2
    assert document["force"] is False
    assert document["summary"] == {
        "written": 1,
        "skipped": 1,
        "failed": 0,
        "succeeded": True,
    }

    sessions = document["sessions"]

    assert isinstance(sessions, list)
    assert [
        session["session_id"]
        for session in sessions
    ] == [
        "2022-01-R",
        "2022-02-R",
    ]


def test_continues_after_session_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One failed race must not stop later races."""
    batch_runner = make_batch_runner(
        tmp_path
    )
    attempted_rounds: list[int] = []

    def fake_run_session(
        runner: ProcessedPipelineRunner,
        session_key: SessionKey,
        *,
        force: bool = False,
    ) -> ProcessedSessionRunResult:
        del force

        attempted_rounds.append(
            session_key.round_number
        )

        if session_key.round_number == 2:
            raise RuntimeError(
                "simulated processing failure"
            )

        return make_run_result(
            runner=runner,
            session_key=session_key,
            status="written",
        )

    monkeypatch.setattr(
        ProcessedPipelineRunner,
        "run_session",
        fake_run_session,
    )

    result = batch_runner.run(
        (
            SessionKey(2023, 1),
            SessionKey(2023, 2),
            SessionKey(2023, 3),
        )
    )

    assert attempted_rounds == [
        1,
        2,
        3,
    ]
    assert result.written_count == 2
    assert result.skipped_count == 0
    assert result.failed_count == 1
    assert not result.succeeded

    failed = result.records[1]

    assert failed.status == "failed"
    assert failed.error_type == "RuntimeError"
    assert (
        failed.error_message
        == "simulated processing failure"
    )

    document = read_json_document(
        result.record_path
    )
    summary = document["summary"]

    assert isinstance(summary, dict)
    assert summary["failed"] == 1
    assert summary["succeeded"] is False


def test_passes_force_to_every_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Controlled rebuilding must reach each session runner."""
    batch_runner = make_batch_runner(
        tmp_path
    )
    received_force: list[bool] = []

    def fake_run_session(
        runner: ProcessedPipelineRunner,
        session_key: SessionKey,
        *,
        force: bool = False,
    ) -> ProcessedSessionRunResult:
        received_force.append(force)

        return make_run_result(
            runner=runner,
            session_key=session_key,
            status="written",
        )

    monkeypatch.setattr(
        ProcessedPipelineRunner,
        "run_session",
        fake_run_session,
    )

    result = batch_runner.run(
        (
            SessionKey(2024, 1),
            SessionKey(2024, 2),
        ),
        force=True,
    )

    assert received_force == [
        True,
        True,
    ]
    assert result.written_count == 2

    document = read_json_document(
        result.record_path
    )

    assert document["force"] is True


def test_rejects_evaluation_season(
    tmp_path: Path,
) -> None:
    """The protected 2025 season cannot enter development."""
    batch_runner = make_batch_runner(
        tmp_path
    )

    with pytest.raises(
        ValueError,
        match="only seasons: 2022, 2023, 2024",
    ):
        batch_runner.run(
            (
                SessionKey(2024, 1),
                SessionKey(2025, 1),
            )
        )


def test_rejects_duplicate_sessions(
    tmp_path: Path,
) -> None:
    """One session must not appear twice in a run."""
    batch_runner = make_batch_runner(
        tmp_path
    )
    session_key = SessionKey(2024, 1)

    with pytest.raises(
        ValueError,
        match="duplicate session keys",
    ):
        batch_runner.run(
            (
                session_key,
                session_key,
            )
        )


@pytest.mark.parametrize(
    "session_keys",
    [
        (),
        [],
    ],
)
def test_rejects_empty_batch(
    tmp_path: Path,
    session_keys: object,
) -> None:
    """A batch must request at least one race."""
    batch_runner = make_batch_runner(
        tmp_path
    )

    with pytest.raises(
        ValueError,
        match="at least one session",
    ):
        batch_runner.run(
            session_keys,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "session_keys",
    [
        ("2024-01-R",),
        "2024-01-R",
    ],
)
def test_rejects_invalid_session_collection(
    tmp_path: Path,
    session_keys: object,
) -> None:
    """Every requested item must be a SessionKey."""
    batch_runner = make_batch_runner(
        tmp_path
    )

    with pytest.raises(TypeError):
        batch_runner.run(
            session_keys,  # type: ignore[arg-type]
        )


def test_rejects_non_boolean_force(
    tmp_path: Path,
) -> None:
    """Force must be a real boolean."""
    batch_runner = make_batch_runner(
        tmp_path
    )

    with pytest.raises(TypeError):
        batch_runner.run(
            (
                SessionKey(2024, 1),
            ),
            force=1,  # type: ignore[arg-type]
        )


def test_rejects_invalid_dependencies(
    tmp_path: Path,
) -> None:
    """Batch dependencies must use validated models."""
    processed_paths = ProcessedDataPaths(
        tmp_path / "processed"
    )
    session_runner = ProcessedPipelineRunner(
        raw_paths=RawDataPaths(
            tmp_path / "raw"
        ),
        processed_paths=processed_paths,
    )

    with pytest.raises(TypeError):
        ProcessedBatchRunner(
            processed_paths=tmp_path,  # type: ignore[arg-type]
            session_runner=session_runner,
        )

    with pytest.raises(TypeError):
        ProcessedBatchRunner(
            processed_paths=processed_paths,
            session_runner="runner",  # type: ignore[arg-type]
        )


def test_rejects_mismatched_processed_roots(
    tmp_path: Path,
) -> None:
    """Batch and session runners must share one output root."""
    batch_paths = ProcessedDataPaths(
        tmp_path / "batch-processed"
    )
    session_paths = ProcessedDataPaths(
        tmp_path / "session-processed"
    )
    session_runner = ProcessedPipelineRunner(
        raw_paths=RawDataPaths(
            tmp_path / "raw"
        ),
        processed_paths=session_paths,
    )

    with pytest.raises(
        ValueError,
        match="same processed paths",
    ):
        ProcessedBatchRunner(
            processed_paths=batch_paths,
            session_runner=session_runner,
        )