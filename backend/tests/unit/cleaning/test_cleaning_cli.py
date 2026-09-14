"""Tests for the Phase 3 cleaning command-line interface."""

from collections.abc import Iterable
from pathlib import Path

import pandas as pd
import pytest

import app.cleaning.cli as cli_module
from app.cleaning.batch import (
    ProcessedBatchRunner,
    ProcessedBatchRunResult,
    ProcessedBatchSessionRecord,
)
from app.cleaning.catalog import (
    ProcessedCatalogBuilder,
    ProcessedCatalogBuildResult,
)
from app.cleaning.cli import (
    CleaningCliError,
    main,
)
from app.cleaning.integrity import (
    ProcessedIntegrityReport,
)
from app.cleaning.paths import ProcessedDataPaths
from app.pipeline.models import SessionKey
from app.pipeline.paths import RawDataPaths
from app.pipeline.serialization import (
    write_parquet_table,
)


def write_raw_catalog(
    tmp_path: Path,
) -> RawDataPaths:
    """Write a raw catalog containing development and holdout data."""
    raw_paths = RawDataPaths(
        tmp_path / "raw"
    )

    catalog = pd.DataFrame(
        {
            "session_id": [
                "2022-01-R",
                "2024-02-R",
                "2025-01-R",
            ],
            "season": [
                2022,
                2024,
                2025,
            ],
            "round_number": [
                1,
                2,
                1,
            ],
            "session_type": [
                "R",
                "R",
                "R",
            ],
        }
    )

    write_parquet_table(
        catalog,
        raw_paths.catalog,
    )

    return raw_paths


def test_plan_filters_development_sessions(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Plan must select only requested development races."""
    raw_paths = write_raw_catalog(
        tmp_path
    )

    exit_code = main(
        [
            "plan",
            "--raw-root",
            str(raw_paths.raw_root),
            "--season",
            "2024",
        ]
    )

    output = capsys.readouterr().out

    assert exit_code == 0
    assert "2024: 1 race sessions" in output
    assert "Total: 1 race sessions" in output
    assert "2022:" not in output
    assert "2025:" not in output


def test_plan_excludes_holdout_by_default(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An unrestricted plan still excludes 2025."""
    raw_paths = write_raw_catalog(
        tmp_path
    )

    exit_code = main(
        [
            "plan",
            "--raw-root",
            str(raw_paths.raw_root),
        ]
    )

    output = capsys.readouterr().out

    assert exit_code == 0
    assert "2022: 1 race sessions" in output
    assert "2024: 1 race sessions" in output
    assert "Total: 2 race sessions" in output
    assert "2025:" not in output


def test_parser_rejects_evaluation_season(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """CLI choices must reject 2025 before execution."""
    with pytest.raises(
        SystemExit
    ) as error:
        main(
            [
                "plan",
                "--season",
                "2025",
            ]
        )

    captured = capsys.readouterr()

    assert error.value.code == 2
    assert "invalid choice" in captured.err
    assert "2025" in captured.err
    assert "2022, 2023, 2024" in captured.err.replace("'", "")


def test_verify_reports_missing_partition(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verify must return failure for absent output."""
    processed_root = (
        tmp_path / "processed"
    )

    exit_code = main(
        [
            "verify",
            "--processed-root",
            str(processed_root),
            "--season",
            "2024",
            "--round",
            "1",
        ]
    )

    output = capsys.readouterr().out

    assert exit_code == 1
    assert "2024-01-R: invalid" in output
    assert "[MISSING_DIRECTORY]" in output


def test_verify_reports_valid_partition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verify must return success for valid output."""
    def fake_verify_processed_partition(
        processed_paths: ProcessedDataPaths,
        session_key: SessionKey,
    ) -> ProcessedIntegrityReport:
        return ProcessedIntegrityReport(
            session_key=session_key,
            directory=(
                processed_paths
                .for_session(session_key)
                .directory
            ),
            issues=(),
            manifest={
                "session": {
                    "identifier": (
                        session_key.identifier
                    ),
                }
            },
        )

    monkeypatch.setattr(
        cli_module,
        "verify_processed_partition",
        fake_verify_processed_partition,
    )

    exit_code = main(
        [
            "verify",
            "--processed-root",
            str(tmp_path / "processed"),
            "--season",
            "2024",
            "--round",
            "1",
        ]
    )

    output = capsys.readouterr().out

    assert exit_code == 0
    assert "2024-01-R: valid" in output


def test_process_runs_batch_and_catalog(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Process must execute, summarize and rebuild catalog."""
    raw_paths = write_raw_catalog(
        tmp_path
    )
    processed_root = (
        tmp_path / "processed"
    )
    selected_key = SessionKey(2022, 1)

    def fake_batch_run(
        runner: ProcessedBatchRunner,
        session_keys: Iterable[SessionKey],
        *,
        force: bool = False,
    ) -> ProcessedBatchRunResult:
        assert force
        assert tuple(session_keys) == (
            selected_key,
        )

        directory = (
            runner.processed_paths
            .for_session(selected_key)
            .directory
        )

        return ProcessedBatchRunResult(
            run_id="test-run",
            records=(
                ProcessedBatchSessionRecord(
                    session_key=selected_key,
                    status="written",
                    duration_seconds=0.125,
                    directory=directory,
                ),
            ),
            record_path=(
                runner.processed_paths
                .runs_directory
                / "test-run.json"
            ),
        )

    def fake_find_valid_sessions(
        *,
        processed_paths: ProcessedDataPaths,
        session_keys: tuple[
            SessionKey,
            ...,
        ],
    ) -> tuple[SessionKey, ...]:
        assert processed_paths.processed_root == (
            processed_root
        )
        assert [
            key.season
            for key in session_keys
        ] == [
            2022,
            2024,
        ]

        return session_keys

    def fake_catalog_build(
        builder: ProcessedCatalogBuilder,
        session_keys: Iterable[SessionKey],
    ) -> ProcessedCatalogBuildResult:
        keys = tuple(session_keys)

        return ProcessedCatalogBuildResult(
            catalog=pd.DataFrame(
                {
                    "session_id": [
                        key.identifier
                        for key in keys
                    ],
                }
            ),
            path=builder.processed_paths.catalog,
            sha256="catalog-checksum",
        )

    monkeypatch.setattr(
        ProcessedBatchRunner,
        "run",
        fake_batch_run,
    )
    monkeypatch.setattr(
        cli_module,
        "_find_valid_processed_sessions",
        fake_find_valid_sessions,
    )
    monkeypatch.setattr(
        ProcessedCatalogBuilder,
        "build",
        fake_catalog_build,
    )

    exit_code = main(
        [
            "process",
            "--raw-root",
            str(raw_paths.raw_root),
            "--processed-root",
            str(processed_root),
            "--season",
            "2022",
            "--force",
        ]
    )

    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Run ID: test-run" in output
    assert "2022-01-R: written (0.125s)" in output
    assert (
        "Summary: 1 written, 0 skipped, 0 failed"
        in output
    )
    assert "Catalog: 2 sessions at" in output


def test_process_returns_failure_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A failed batch must produce a non-zero exit code."""
    raw_paths = write_raw_catalog(
        tmp_path
    )
    session_key = SessionKey(2022, 1)

    def fake_batch_run(
        runner: ProcessedBatchRunner,
        session_keys: Iterable[SessionKey],
        *,
        force: bool = False,
    ) -> ProcessedBatchRunResult:
        del session_keys, force

        return ProcessedBatchRunResult(
            run_id="failed-run",
            records=(
                ProcessedBatchSessionRecord(
                    session_key=session_key,
                    status="failed",
                    duration_seconds=0.25,
                    directory=(
                        runner.processed_paths
                        .for_session(session_key)
                        .directory
                    ),
                    error_type="RuntimeError",
                    error_message=(
                        "simulated failure"
                    ),
                ),
            ),
            record_path=(
                runner.processed_paths
                .runs_directory
                / "failed-run.json"
            ),
        )

    def fake_find_valid_sessions(
        *,
        processed_paths: ProcessedDataPaths,
        session_keys: tuple[
            SessionKey,
            ...,
        ],
    ) -> tuple[SessionKey, ...]:
        del processed_paths, session_keys
        return ()

    monkeypatch.setattr(
        ProcessedBatchRunner,
        "run",
        fake_batch_run,
    )
    monkeypatch.setattr(
        cli_module,
        "_find_valid_processed_sessions",
        fake_find_valid_sessions,
    )

    exit_code = main(
        [
            "process",
            "--raw-root",
            str(raw_paths.raw_root),
            "--processed-root",
            str(tmp_path / "processed"),
            "--season",
            "2022",
        ]
    )

    output = capsys.readouterr().out

    assert exit_code == 1
    assert "2022-01-R: failed" in output
    assert (
        "RuntimeError: simulated failure"
        in output
    )
    assert (
        "Catalog: no valid processed "
        "sessions available"
        in output
    )


def test_catalog_command_builds_available_sessions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Catalog command must publish valid development rows."""
    raw_paths = write_raw_catalog(
        tmp_path
    )

    def fake_find_valid_sessions(
        *,
        processed_paths: ProcessedDataPaths,
        session_keys: tuple[
            SessionKey,
            ...,
        ],
    ) -> tuple[SessionKey, ...]:
        del processed_paths
        return session_keys

    def fake_catalog_build(
        builder: ProcessedCatalogBuilder,
        session_keys: Iterable[SessionKey],
    ) -> ProcessedCatalogBuildResult:
        keys = tuple(session_keys)

        return ProcessedCatalogBuildResult(
            catalog=pd.DataFrame(
                {
                    "session_id": [
                        key.identifier
                        for key in keys
                    ],
                }
            ),
            path=builder.processed_paths.catalog,
            sha256="abc123",
        )

    monkeypatch.setattr(
        cli_module,
        "_find_valid_processed_sessions",
        fake_find_valid_sessions,
    )
    monkeypatch.setattr(
        ProcessedCatalogBuilder,
        "build",
        fake_catalog_build,
    )

    exit_code = main(
        [
            "catalog",
            "--raw-root",
            str(raw_paths.raw_root),
            "--processed-root",
            str(tmp_path / "processed"),
        ]
    )

    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Catalog built: 2 sessions" in output
    assert "SHA-256: abc123" in output


def test_missing_raw_catalog_is_reported(
    tmp_path: Path,
) -> None:
    """Commands requiring the raw catalog must fail clearly."""
    with pytest.raises(
        CleaningCliError,
        match="raw data catalog does not exist",
    ):
        main(
            [
                "plan",
                "--raw-root",
                str(tmp_path / "missing"),
            ]
        )


def test_empty_selection_is_rejected(
    tmp_path: Path,
) -> None:
    """A valid filter with no matching race must fail."""
    raw_paths = write_raw_catalog(
        tmp_path
    )

    with pytest.raises(
        CleaningCliError,
        match="no development sessions",
    ):
        main(
            [
                "plan",
                "--raw-root",
                str(raw_paths.raw_root),
                "--season",
                "2022",
                "--round",
                "30",
            ]
        )
