"""Tests for transaction-safe verified session loading."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import Column, Integer, MetaData, Table
from sqlalchemy.orm import sessionmaker

import app.db.loading as database_loading
from app.cleaning import ProcessedDataPaths
from app.datasets import DatasetPaths
from app.db.artifacts import (
    DatabaseArtifactError,
    PreparedSessionArtifacts,
)
from app.db.loading import (
    DatabaseLoadError,
    SessionDatabaseLoader,
    SessionLoadResult,
)
from app.pipeline import RawDataPaths, SessionKey


def _prepared_artifacts() -> PreparedSessionArtifacts:
    """Build compact source documents for provenance record tests."""
    digest = "a" * 64
    processed_files = {
        "laps.parquet": {"sha256": digest, "size_bytes": 100},
        "stints.parquet": {"sha256": digest, "size_bytes": 20},
        "pit_events.parquet": {"sha256": digest, "size_bytes": 30},
        "quality_report.json": {"sha256": digest, "size_bytes": 10},
    }
    dataset_files = {
        "decision_rows.parquet": {"sha256": digest, "size_bytes": 80},
        "decision_labels.parquet": {"sha256": digest, "size_bytes": 40},
        "pit_duration_observations.parquet": {
            "sha256": digest,
            "size_bytes": 15,
        },
        "quality_report.json": {"sha256": digest, "size_bytes": 5},
    }
    return PreparedSessionArtifacts(
        session_key=SessionKey(2024, 3, "R"),
        raw_directory=Path("raw/session"),
        raw_manifest_path=Path("raw/session/manifest.json"),
        raw_manifest_sha256="b" * 64,
        raw_manifest={"contract_version": "1.0"},
        raw_metadata={
            "event_name": "Australian Grand Prix",
            "official_event_name": "Formula 1 Australian Grand Prix 2024",
            "country": "Australia",
            "location": "Melbourne",
            "event_format": "conventional",
            "event_date": "2024-03-24T00:00:00",
        },
        processed_directory=Path("processed/session"),
        processed_manifest_path=Path("processed/session/manifest.json"),
        processed_manifest_sha256="b" * 64,
        processed_manifest={
            "source_contract_version": "1.0",
            "processed_contract_version": "1.0",
            "cleaning_rule_version": "1.0",
            "created_at_utc": "2024-04-01T00:00:00Z",
            "files": processed_files,
        },
        processed_quality_report={},
        processed_laps=pd.DataFrame(index=range(4)),
        reconstructed_stints=pd.DataFrame(index=range(2)),
        reconstructed_pit_events=pd.DataFrame(index=range(1)),
        dataset_directory=Path("datasets/session"),
        dataset_manifest_path=Path("datasets/session/manifest.json"),
        dataset_manifest_sha256="b" * 64,
        dataset_manifest={
            "dataset_contract_version": "1.0",
            "created_at_utc": "2024-04-02T00:00:00Z",
            "files": dataset_files,
        },
        dataset_quality_report={
            "decision_quality": {
                "eligible_decisions": 2,
                "ineligible_decisions": 1,
                "historical_pit_now_actions": 1,
                "historical_stay_out_actions": 1,
            },
            "target_quality": {
                "lap_time_target_eligible_rows": 1,
                "pit_duration_target_eligible_rows": 1,
            },
        },
        decision_rows=pd.DataFrame(
            {
                "decision_id": ["d1", "d2", "d3"],
                "is_decision_eligible": [True, True, False],
            }
        ),
        decision_labels=pd.DataFrame(
            {
                "decision_id": ["d1", "d2", "d3"],
                "historical_action": ["PIT_NOW", "STAY_OUT", "STAY_OUT"],
                "is_lap_time_target_eligible": [True, False, False],
            }
        ),
        pit_duration_observations=pd.DataFrame(
            {"is_pit_duration_target_eligible": [True]}
        ),
    )


def test_loader_prepares_artifacts_before_opening_transaction(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Keep filesystem verification outside the SQL write boundary."""
    calls: list[str] = []
    expected = SessionLoadResult(
        status="written",
        session_id="2024-03-R",
        processed_partition_id=9,
        processed_laps=4,
        decision_rows=3,
        decision_labels=3,
        pit_duration_observations=1,
    )

    def prepare(**kwargs: object) -> object:
        calls.append("prepare")
        return object()

    @contextmanager
    def transaction(factory: object) -> Iterator[object]:
        calls.append("transaction")
        yield object()

    def load_prepared(
        session: object,
        *,
        prepared: object,
        run_id: str,
    ) -> SessionLoadResult:
        calls.append("load")
        assert run_id == "dataset-run-1"
        return expected

    monkeypatch.setattr(database_loading, "prepare_session_artifacts", prepare)
    monkeypatch.setattr(database_loading, "database_transaction", transaction)
    monkeypatch.setattr(
        database_loading,
        "_load_prepared_session",
        load_prepared,
    )
    loader = SessionDatabaseLoader(
        session_factory=sessionmaker(),
        raw_paths=RawDataPaths(tmp_path / "raw"),
        processed_paths=ProcessedDataPaths(tmp_path / "processed"),
        dataset_paths=DatasetPaths(tmp_path / "datasets"),
    )

    result = loader.load(SessionKey(2024, 3, "R"), run_id="dataset-run-1")

    assert result is expected
    assert calls == ["prepare", "transaction", "load"]


def test_loader_rejects_2025_before_opening_transaction(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Never open SQL when a protected evaluation session is requested."""
    transaction_opened = False

    @contextmanager
    def transaction(factory: object) -> Iterator[object]:
        nonlocal transaction_opened
        transaction_opened = True
        yield object()

    monkeypatch.setattr(database_loading, "database_transaction", transaction)
    loader = SessionDatabaseLoader(
        session_factory=sessionmaker(),
        raw_paths=RawDataPaths(tmp_path / "raw"),
        processed_paths=ProcessedDataPaths(tmp_path / "processed"),
        dataset_paths=DatasetPaths(tmp_path / "datasets"),
    )

    with pytest.raises(DatabaseArtifactError, match="development seasons"):
        loader.load(SessionKey(2025, 1, "R"), run_id="dataset-run-1")

    assert transaction_opened is False


def test_loader_requires_a_real_session_factory(tmp_path: Path) -> None:
    """Reject a dependency that cannot provide transactional sessions."""
    with pytest.raises(TypeError, match="session_factory"):
        SessionDatabaseLoader(
            session_factory=object(),  # type: ignore[arg-type]
            raw_paths=RawDataPaths(tmp_path / "raw"),
            processed_paths=ProcessedDataPaths(tmp_path / "processed"),
            dataset_paths=DatasetPaths(tmp_path / "datasets"),
        )


def test_participants_come_from_processed_lap_identities() -> None:
    """Collapse repeated laps into deterministic participant references."""
    laps = pd.DataFrame(
        {
            "Driver": ["VER", "NOR", "VER"],
            "DriverNumber": [1, "4", 1],
            "Team": ["Red Bull Racing", "McLaren", "Red Bull Racing"],
        }
    )

    assert database_loading._participant_sources(laps) == (
        ("NOR", "4", "McLaren"),
        ("VER", "1", "Red Bull Racing"),
    )


def test_participants_reject_identity_changes_within_session() -> None:
    """Fail instead of selecting one of two conflicting source teams."""
    laps = pd.DataFrame(
        {
            "Driver": ["VER", "VER"],
            "DriverNumber": [1, 1],
            "Team": ["Red Bull Racing", "Different Team"],
        }
    )

    with pytest.raises(DatabaseLoadError, match="identity changes for VER"):
        database_loading._participant_sources(laps)


def test_event_date_preserves_calendar_date_from_raw_iso_datetime() -> None:
    """Store the raw event calendar date without timezone inference."""
    prepared = _prepared_artifacts()

    assert database_loading._source_date(
        prepared.raw_metadata,
        "event_date",
    ).isoformat() == "2024-03-24"


def test_provenance_records_use_manifest_counts_hashes_and_sizes() -> None:
    """Build database provenance from authoritative stored documents."""
    prepared = _prepared_artifacts()
    digest = "b" * 64

    processed = database_loading._processed_partition_record(prepared)
    dataset = database_loading._dataset_session_record(
        prepared,
        processed_partition_id=11,
        created_by_run_id="dataset-run-1",
    )

    assert processed["source_manifest_sha256"] == digest
    assert processed["processed_manifest_sha256"] == digest
    assert processed["laps_rows"] == 4
    assert processed["total_size_bytes"] == 160
    assert dataset["dataset_manifest_sha256"] == digest
    assert dataset["processed_partition_id"] == 11
    assert dataset["decision_rows"] == 3
    assert dataset["eligible_decisions"] == 2
    assert dataset["pit_now_rows"] == 1
    assert dataset["total_size_bytes"] == 140


def test_dataset_provenance_rejects_quality_report_count_mismatch() -> None:
    """Never persist report totals that disagree with analytical rows."""
    prepared = _prepared_artifacts()
    decision_quality = prepared.dataset_quality_report["decision_quality"]
    assert isinstance(decision_quality, dict)
    decision_quality["eligible_decisions"] = 3

    with pytest.raises(
        DatabaseLoadError,
        match="eligible_decisions differs: expected 2, got 3",
    ):
        database_loading._dataset_session_record(
            prepared,
            processed_partition_id=11,
            created_by_run_id="dataset-run-1",
        )


def test_reconciliation_rejects_value_differences() -> None:
    """A retry must compare stored values, not only row counts."""
    table = Table(
        "example_rows",
        MetaData(),
        Column("row_id", Integer, primary_key=True),
        Column("value", Integer, nullable=False),
    )

    class _Mappings:
        def all(self) -> list[dict[str, int]]:
            return [{"row_id": 1, "value": 99}]

    class _Result:
        def mappings(self) -> _Mappings:
            return _Mappings()

    class _Session:
        def execute(self, statement: object) -> _Result:
            return _Result()

    load = database_loading._TableLoad(
        table=table,
        rows=({"row_id": 1, "value": 10},),
        predicates=(),
    )

    with pytest.raises(DatabaseLoadError, match="row 0 differs: value"):
        database_loading._reconcile_exact_rows(
            _Session(),  # type: ignore[arg-type]
            load,
        )
