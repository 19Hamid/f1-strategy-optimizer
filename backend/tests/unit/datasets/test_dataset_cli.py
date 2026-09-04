"""Tests for the Phase 4 modelling-dataset command-line interface."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

import app.datasets.cli as cli_module
from app.cleaning.paths import ProcessedDataPaths
from app.datasets.batch import (
    DatasetBatchRunResult,
    DatasetBatchSessionRecord,
)
from app.datasets.cli import (
    DEFAULT_DATASETS_ROOT,
    DEFAULT_PROCESSED_ROOT,
    DatasetCliError,
    _load_development_session_keys,
    _print_integrity_report,
    build_parser,
    main,
)
from app.datasets.integrity import (
    DatasetIntegrityIssue,
    DatasetIntegrityIssueCode,
    DatasetIntegrityReport,
)
from app.pipeline.models import SessionKey


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
        for season, session_count in (
            (2022, 22),
            (2023, 22),
            (2024, 24),
        )
        for round_number in range(
            1,
            session_count + 1,
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


def _identity_catalog(
    session_keys: tuple[SessionKey, ...],
) -> pd.DataFrame:
    """Build the processed identity columns consumed by the CLI."""
    return pd.DataFrame.from_records(
        [
            {
                "season": session_key.season,
                "round_number": (
                    session_key.round_number
                ),
                "session_type": (
                    session_key.session_type
                ),
            }
            for session_key in session_keys
        ]
    )


def _prepare_catalog(
    *,
    processed_paths: ProcessedDataPaths,
    catalog: pd.DataFrame,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Create a catalog marker and patch its Parquet read."""
    processed_paths.catalog.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    processed_paths.catalog.write_bytes(
        b"synthetic-processed-catalog"
    )
    monkeypatch.setattr(
        cli_module,
        "read_parquet_table",
        lambda path: catalog.copy(deep=True),
    )


def _integrity_report(
    tmp_path: Path,
    *,
    valid: bool,
) -> DatasetIntegrityReport:
    """Build a valid or invalid complete-dataset report."""
    issues = (
        ()
        if valid
        else (
            DatasetIntegrityIssue(
                code=(
                    DatasetIntegrityIssueCode
                    .INVALID_SESSION_PARTITION
                ),
                message="checksum mismatch",
                path=tmp_path / "season=2024",
                session_id="2024-01-R",
            ),
        )
    )

    return DatasetIntegrityReport(
        directory=tmp_path,
        requested_sessions=68,
        valid_sessions=68 if valid else 67,
        catalog_rows=68,
        split_rows=204,
        issues=issues,
    )


def _batch_result(
    *,
    tmp_path: Path,
    session_keys: tuple[SessionKey, ...],
    session_status: str = "written",
    artifact_status: str = "published",
    global_error_type: str | None = None,
    global_error_message: str | None = None,
) -> DatasetBatchRunResult:
    """Build one CLI-ready batch result."""
    records = tuple(
        DatasetBatchSessionRecord(
            session_key=session_key,
            status=session_status,  # type: ignore[arg-type]
            duration_seconds=0.25,
            directory=(
                tmp_path
                / session_key.identifier
            ),
            error_type=(
                "RuntimeError"
                if session_status == "failed"
                else None
            ),
            error_message=(
                "synthetic session failure"
                if session_status == "failed"
                else None
            ),
        )
        for session_key in session_keys
    )

    return DatasetBatchRunResult(
        run_id="dataset-run-001",
        records=records,
        record_path=tmp_path / "run.json",
        global_artifact_status=(
            artifact_status  # type: ignore[arg-type]
        ),
        catalog_path=(
            tmp_path / "catalog.parquet"
            if artifact_status == "published"
            else None
        ),
        catalog_sha256=(
            "a" * 64
            if artifact_status == "published"
            else None
        ),
        splits_path=(
            tmp_path / "splits.parquet"
            if artifact_status == "published"
            else None
        ),
        splits_sha256=(
            "b" * 64
            if artifact_status == "published"
            else None
        ),
        global_error_type=global_error_type,
        global_error_message=global_error_message,
    )


def _patch_build_dependencies(
    *,
    monkeypatch: pytest.MonkeyPatch,
    session_keys: tuple[SessionKey, ...],
    result: DatasetBatchRunResult,
    report: DatasetIntegrityReport,
) -> dict[str, object]:
    """Patch heavy build dependencies and return call state."""
    state: dict[str, object] = {
        "force": None,
        "requested": None,
        "integrity_calls": 0,
    }
    session_runner = object()

    class FakeBatchRunner:
        """Record the CLI batch invocation."""

        def run(
            self,
            requested: tuple[SessionKey, ...],
            *,
            force: bool,
        ) -> DatasetBatchRunResult:
            state["requested"] = requested
            state["force"] = force
            return result

    def fake_integrity(
        dataset_paths: object,
        requested: tuple[SessionKey, ...],
    ) -> DatasetIntegrityReport:
        state["integrity_calls"] = (
            int(state["integrity_calls"])
            + 1
        )
        state["integrity_requested"] = requested
        state["integrity_paths"] = dataset_paths
        return report

    monkeypatch.setattr(
        cli_module,
        "_load_development_session_keys",
        lambda processed: session_keys,
    )
    monkeypatch.setattr(
        cli_module,
        "DatasetPipelineRunner",
        lambda **kwargs: session_runner,
    )
    monkeypatch.setattr(
        cli_module,
        "DatasetBatchRunner",
        lambda **kwargs: FakeBatchRunner(),
    )
    monkeypatch.setattr(
        cli_module,
        "verify_complete_dataset",
        fake_integrity,
    )

    return state


def test_parser_requires_a_command() -> None:
    """The CLI cannot run without an explicit operation."""
    parser = build_parser()

    with pytest.raises(SystemExit) as raised:
        parser.parse_args([])

    assert raised.value.code == 2


@pytest.mark.parametrize(
    "command",
    ("plan", "build", "verify"),
)
def test_parser_accepts_every_command(
    command: str,
) -> None:
    """Every declared CLI command has a callable handler."""
    arguments = build_parser().parse_args(
        [command]
    )

    assert arguments.command == command
    assert isinstance(
        arguments.processed_root,
        Path,
    )
    assert isinstance(
        arguments.datasets_root,
        Path,
    )
    assert callable(arguments.handler)


def test_parser_uses_project_defaults() -> None:
    """Plan defaults point to the repository data roots."""
    arguments = build_parser().parse_args(
        ["plan"]
    )

    assert (
        arguments.processed_root
        == DEFAULT_PROCESSED_ROOT
    )
    assert (
        arguments.datasets_root
        == DEFAULT_DATASETS_ROOT
    )


def test_parser_accepts_root_overrides(
    tmp_path: Path,
) -> None:
    """All filesystem roots can be selected explicitly."""
    processed_root = tmp_path / "processed"
    datasets_root = tmp_path / "datasets"
    arguments = build_parser().parse_args(
        [
            "verify",
            "--processed-root",
            str(processed_root),
            "--datasets-root",
            str(datasets_root),
        ]
    )

    assert arguments.processed_root == processed_root
    assert arguments.datasets_root == datasets_root


@pytest.mark.parametrize(
    ("extra_arguments", "expected_force"),
    (
        ((), False),
        (("--force",), True),
    ),
)
def test_build_force_flag(
    extra_arguments: tuple[str, ...],
    expected_force: bool,
) -> None:
    """Force rebuilding is opt-in and boolean."""
    arguments = build_parser().parse_args(
        ["build", *extra_arguments]
    )

    assert arguments.force is expected_force


def test_main_dispatches_selected_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Main returns the selected command's exit code."""
    calls = []

    def fake_plan(
        arguments: object,
    ) -> int:
        calls.append(arguments)
        return 7

    monkeypatch.setattr(
        cli_module,
        "_run_plan",
        fake_plan,
    )

    assert main(["plan"]) == 7
    assert len(calls) == 1


def test_loader_requires_processed_paths() -> None:
    """Schedule loading requires canonical processed paths."""
    with pytest.raises(
        TypeError,
        match="processed_paths must be ProcessedDataPaths",
    ):
        _load_development_session_keys(
            object()  # type: ignore[arg-type]
        )


def test_loader_rejects_protected_directory(
    processed_paths: ProcessedDataPaths,
) -> None:
    """A processed 2025 directory blocks every CLI command."""
    protected = (
        processed_paths.version_root
        / "season=2025"
    )
    protected.mkdir(parents=True)

    with pytest.raises(
        DatasetCliError,
        match="protected evaluation-season",
    ):
        _load_development_session_keys(
            processed_paths
        )


def test_loader_requires_processed_catalog(
    processed_paths: ProcessedDataPaths,
) -> None:
    """The processed catalog is the frozen schedule source."""
    with pytest.raises(
        DatasetCliError,
        match="processed data catalog does not exist",
    ):
        _load_development_session_keys(
            processed_paths
        )


def test_loader_wraps_catalog_read_failure(
    processed_paths: ProcessedDataPaths,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unreadable processed catalogs fail with CLI context."""
    processed_paths.catalog.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    processed_paths.catalog.write_bytes(b"invalid")
    monkeypatch.setattr(
        cli_module,
        "read_parquet_table",
        lambda path: (_ for _ in ()).throw(
            OSError("cannot decode parquet")
        ),
    )

    with pytest.raises(
        DatasetCliError,
        match=(
            "processed data catalog could not be read: "
            "OSError: cannot decode parquet"
        ),
    ):
        _load_development_session_keys(
            processed_paths
        )


@pytest.mark.parametrize(
    "missing_column",
    ("season", "round_number", "session_type"),
)
def test_loader_requires_identity_columns(
    processed_paths: ProcessedDataPaths,
    development_session_keys: tuple[
        SessionKey,
        ...,
    ],
    monkeypatch: pytest.MonkeyPatch,
    missing_column: str,
) -> None:
    """Every identity field is required before construction."""
    catalog = _identity_catalog(
        development_session_keys
    ).drop(columns=missing_column)
    _prepare_catalog(
        processed_paths=processed_paths,
        catalog=catalog,
        monkeypatch=monkeypatch,
    )

    with pytest.raises(
        DatasetCliError,
        match=(
            "processed catalog is missing columns: "
            f"{missing_column}"
        ),
    ):
        _load_development_session_keys(
            processed_paths
        )


def test_loader_rejects_empty_catalog(
    processed_paths: ProcessedDataPaths,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty processed catalog is never complete."""
    catalog = pd.DataFrame(
        columns=(
            "season",
            "round_number",
            "session_type",
        )
    )
    _prepare_catalog(
        processed_paths=processed_paths,
        catalog=catalog,
        monkeypatch=monkeypatch,
    )

    with pytest.raises(
        DatasetCliError,
        match="processed catalog contains no sessions",
    ):
        _load_development_session_keys(
            processed_paths
        )


def test_loader_wraps_invalid_identity(
    processed_paths: ProcessedDataPaths,
    development_session_keys: tuple[
        SessionKey,
        ...,
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Malformed catalog identities fail before path access."""
    catalog = _identity_catalog(
        development_session_keys
    )
    catalog.loc[0, "session_type"] = "Q"
    _prepare_catalog(
        processed_paths=processed_paths,
        catalog=catalog,
        monkeypatch=monkeypatch,
    )

    with pytest.raises(
        DatasetCliError,
        match=(
            "processed catalog contains an invalid "
            "session identity"
        ),
    ):
        _load_development_session_keys(
            processed_paths
        )


def test_loader_rejects_duplicate_sessions(
    processed_paths: ProcessedDataPaths,
    development_session_keys: tuple[
        SessionKey,
        ...,
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Duplicate catalog rows cannot fake complete coverage."""
    duplicated = (
        *development_session_keys[:-1],
        development_session_keys[0],
    )
    _prepare_catalog(
        processed_paths=processed_paths,
        catalog=_identity_catalog(duplicated),
        monkeypatch=monkeypatch,
    )

    with pytest.raises(
        DatasetCliError,
        match="processed catalog contains duplicate sessions",
    ):
        _load_development_session_keys(
            processed_paths
        )


def test_loader_rejects_non_development_season(
    processed_paths: ProcessedDataPaths,
    development_session_keys: tuple[
        SessionKey,
        ...,
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catalog rows from 2025 are never silently filtered."""
    invalid = (
        *development_session_keys[:-1],
        SessionKey(
            season=2025,
            round_number=24,
            session_type="R",
        ),
    )
    _prepare_catalog(
        processed_paths=processed_paths,
        catalog=_identity_catalog(invalid),
        monkeypatch=monkeypatch,
    )

    with pytest.raises(
        DatasetCliError,
        match=(
            "processed catalog contains "
            "non-development seasons: 2025"
        ),
    ):
        _load_development_session_keys(
            processed_paths
        )


@pytest.mark.parametrize(
    "session_count",
    (1, 67),
)
def test_loader_requires_exact_session_total(
    processed_paths: ProcessedDataPaths,
    development_session_keys: tuple[
        SessionKey,
        ...,
    ],
    monkeypatch: pytest.MonkeyPatch,
    session_count: int,
) -> None:
    """Partial processed catalogs cannot drive Phase 4."""
    catalog = _identity_catalog(
        development_session_keys[
            :session_count
        ]
    )
    _prepare_catalog(
        processed_paths=processed_paths,
        catalog=catalog,
        monkeypatch=monkeypatch,
    )

    with pytest.raises(
        DatasetCliError,
        match=(
            "complete dataset construction requires "
            "exactly 68 processed sessions"
        ),
    ):
        _load_development_session_keys(
            processed_paths
        )


def test_loader_requires_exact_season_counts(
    processed_paths: ProcessedDataPaths,
    development_session_keys: tuple[
        SessionKey,
        ...,
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sixty-eight rows must still preserve 22/22/24."""
    invalid = (
        *development_session_keys[:-1],
        SessionKey(
            season=2023,
            round_number=23,
            session_type="R",
        ),
    )
    _prepare_catalog(
        processed_paths=processed_paths,
        catalog=_identity_catalog(invalid),
        monkeypatch=monkeypatch,
    )

    with pytest.raises(
        DatasetCliError,
        match=(
            "processed catalog season counts differ "
            "from the contract"
        ),
    ):
        _load_development_session_keys(
            processed_paths
        )


def test_loader_returns_canonical_order(
    processed_paths: ProcessedDataPaths,
    development_session_keys: tuple[
        SessionKey,
        ...,
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catalog storage order cannot change execution order."""
    reversed_keys = tuple(
        reversed(development_session_keys)
    )
    _prepare_catalog(
        processed_paths=processed_paths,
        catalog=_identity_catalog(reversed_keys),
        monkeypatch=monkeypatch,
    )

    assert _load_development_session_keys(
        processed_paths
    ) == development_session_keys


def test_plan_prints_frozen_schedule(
    development_session_keys: tuple[
        SessionKey,
        ...,
    ],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Plan reports exact season and protected-holdout scope."""
    monkeypatch.setattr(
        cli_module,
        "_load_development_session_keys",
        lambda processed: development_session_keys,
    )

    exit_code = main(["plan"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "DEVELOPMENT DATASET PLAN" in output
    assert "Dataset contract: 1.0" in output
    assert "2022: 22 races" in output
    assert "2023: 22 races" in output
    assert "2024: 24 races" in output
    assert "Total: 68 race sessions" in output
    assert (
        "Protected evaluation season: 2025 excluded"
        in output
    )


def test_valid_integrity_report_output(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Valid reports print complete totals without issues."""
    _print_integrity_report(
        _integrity_report(
            tmp_path,
            valid=True,
        )
    )
    output = capsys.readouterr().out

    assert "Integrity status: valid" in output
    assert "Requested sessions: 68" in output
    assert "Valid sessions: 68" in output
    assert "Catalog rows: 68" in output
    assert "Split rows: 204" in output
    assert "Issues: 0" in output


def test_invalid_integrity_report_output(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Invalid reports expose code, session, path and message."""
    _print_integrity_report(
        _integrity_report(
            tmp_path,
            valid=False,
        )
    )
    output = capsys.readouterr().out

    assert "Integrity status: invalid" in output
    assert "Valid sessions: 67" in output
    assert "Issues: 1" in output
    assert "[INVALID_SESSION_PARTITION]" in output
    assert "session=2024-01-R" in output
    assert "checksum mismatch" in output


@pytest.mark.parametrize(
    ("force_arguments", "expected_force"),
    (
        ((), False),
        (("--force",), True),
    ),
)
def test_successful_build_runs_post_build_integrity(
    tmp_path: Path,
    development_session_keys: tuple[
        SessionKey,
        ...,
    ],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    force_arguments: tuple[str, ...],
    expected_force: bool,
) -> None:
    """Successful batches must pass complete integrity."""
    result = _batch_result(
        tmp_path=tmp_path,
        session_keys=development_session_keys,
    )
    report = _integrity_report(
        tmp_path,
        valid=True,
    )
    state = _patch_build_dependencies(
        monkeypatch=monkeypatch,
        session_keys=development_session_keys,
        result=result,
        report=report,
    )

    exit_code = main(
        [
            "build",
            "--datasets-root",
            str(tmp_path),
            *force_arguments,
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert state["force"] is expected_force
    assert (
        state["requested"]
        == development_session_keys
    )
    assert state["integrity_calls"] == 1
    assert (
        state["integrity_requested"]
        == development_session_keys
    )
    assert "DEVELOPMENT DATASET BUILD" in output
    assert "Summary: 68 written, 0 skipped, 0 failed" in output
    assert "Global artifacts: published" in output
    assert "Integrity status: valid" in output


def test_batch_failure_returns_nonzero_without_integrity(
    tmp_path: Path,
    development_session_keys: tuple[
        SessionKey,
        ...,
    ],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Failed session batches cannot claim global validity."""
    result = _batch_result(
        tmp_path=tmp_path,
        session_keys=development_session_keys,
        session_status="failed",
        artifact_status="not_published",
    )
    state = _patch_build_dependencies(
        monkeypatch=monkeypatch,
        session_keys=development_session_keys,
        result=result,
        report=_integrity_report(
            tmp_path,
            valid=True,
        ),
    )

    exit_code = main(["build"])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert state["integrity_calls"] == 0
    assert "68 failed" in output
    assert "synthetic session failure" in output
    assert "Global artifacts: not_published" in output
    assert "Post-build integrity: not run" in output


def test_global_publication_failure_is_printed(
    tmp_path: Path,
    development_session_keys: tuple[
        SessionKey,
        ...,
    ],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Global publication failures remain visible and nonzero."""
    result = _batch_result(
        tmp_path=tmp_path,
        session_keys=development_session_keys,
        session_status="written",
        artifact_status="failed",
        global_error_type="DatasetCatalogError",
        global_error_message="catalog mismatch",
    )
    state = _patch_build_dependencies(
        monkeypatch=monkeypatch,
        session_keys=development_session_keys,
        result=result,
        report=_integrity_report(
            tmp_path,
            valid=True,
        ),
    )

    exit_code = main(["build"])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert state["integrity_calls"] == 0
    assert "Global artifacts: failed" in output
    assert (
        "Global error: DatasetCatalogError: "
        "catalog mismatch"
        in output
    )


def test_post_build_integrity_failure_returns_nonzero(
    tmp_path: Path,
    development_session_keys: tuple[
        SessionKey,
        ...,
    ],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A published batch still fails when read-back is invalid."""
    result = _batch_result(
        tmp_path=tmp_path,
        session_keys=development_session_keys,
    )
    state = _patch_build_dependencies(
        monkeypatch=monkeypatch,
        session_keys=development_session_keys,
        result=result,
        report=_integrity_report(
            tmp_path,
            valid=False,
        ),
    )

    exit_code = main(["build"])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert state["integrity_calls"] == 1
    assert "Integrity status: invalid" in output
    assert "[INVALID_SESSION_PARTITION]" in output


@pytest.mark.parametrize(
    ("valid", "expected_exit_code"),
    (
        (True, 0),
        (False, 1),
    ),
)
def test_verify_command_returns_integrity_status(
    tmp_path: Path,
    development_session_keys: tuple[
        SessionKey,
        ...,
    ],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    valid: bool,
    expected_exit_code: int,
) -> None:
    """Verify uses report validity as its process exit code."""
    report = _integrity_report(
        tmp_path,
        valid=valid,
    )
    calls: list[
        tuple[object, tuple[SessionKey, ...]]
    ] = []

    def fake_verify(
        dataset_paths: object,
        session_keys: tuple[SessionKey, ...],
    ) -> DatasetIntegrityReport:
        calls.append(
            (dataset_paths, session_keys)
        )
        return report

    monkeypatch.setattr(
        cli_module,
        "_load_development_session_keys",
        lambda processed: development_session_keys,
    )
    monkeypatch.setattr(
        cli_module,
        "verify_complete_dataset",
        fake_verify,
    )

    exit_code = main(
        [
            "verify",
            "--datasets-root",
            str(tmp_path),
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == expected_exit_code
    assert len(calls) == 1
    assert calls[0][1] == development_session_keys
    assert "DEVELOPMENT DATASET INTEGRITY" in output
    assert (
        f"Integrity status: "
        f"{'valid' if valid else 'invalid'}"
        in output
    )