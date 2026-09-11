"""Transactionally load one verified development dataset session."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal

import numpy as np
import pandas as pd
from sqlalchemy import Table, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from app.cleaning import ProcessedDataPaths
from app.datasets import DatasetPaths
from app.db.artifacts import (
    PreparedSessionArtifacts,
    prepare_session_artifacts,
)
from app.db.base import DATABASE_SCHEMA_VERSION
from app.db.decision_labels import (
    DECISION_LABEL_SOURCE_COLUMN_MAP,
    DecisionLabel,
)
from app.db.decision_rows import (
    DECISION_ROW_SOURCE_COLUMN_MAP,
    DecisionRow,
)
from app.db.pit_duration_observations import (
    PIT_DURATION_OBSERVATION_SOURCE_COLUMN_MAP,
    PitDurationObservation,
)
from app.db.processed_laps import (
    PROCESSED_LAP_SOURCE_COLUMN_MAP,
    ProcessedLap,
)
from app.db.provenance import (
    DatasetBuild,
    DatasetSession,
    DatasetVersion,
    ProcessedSessionPartition,
)
from app.db.quality_reasons import (
    DecisionQualityReason,
    LapTargetQualityReason,
    PitDurationQualityReason,
    PitEventQualityReason,
    ProcessedLapQualityReason,
    QualityReason,
    StintQualityReason,
)
from app.db.reconstructed_pit_events import (
    RECONSTRUCTED_PIT_EVENT_SOURCE_COLUMN_MAP,
    ReconstructedPitEvent,
)
from app.db.reconstructed_stints import (
    RECONSTRUCTED_STINT_SOURCE_COLUMN_MAP,
    ReconstructedStint,
)
from app.db.records import (
    iter_dataframe_records,
    iter_quality_reason_link_records,
    quality_reason_definition_records,
)
from app.db.reference import (
    Circuit,
    Driver,
    Event,
    RaceSession,
    Season,
    SessionParticipant,
    Team,
)
from app.db.repositories import (
    ImmutableRepository,
    RepositoryWriteStatus,
    insert_rows,
)
from app.db.runtime import database_transaction
from app.pipeline import RawDataPaths, SessionKey

SessionLoadStatus = Literal["written", "verified"]


class DatabaseLoadError(RuntimeError):
    """Raised when a session cannot be loaded or reconciled exactly."""


@dataclass(frozen=True, slots=True)
class SessionLoadResult:
    """Summarize one committed or idempotently verified session load."""

    status: SessionLoadStatus
    session_id: str
    processed_partition_id: int
    processed_laps: int
    decision_rows: int
    decision_labels: int
    pit_duration_observations: int


@dataclass(frozen=True, slots=True)
class _TableLoad:
    """Hold expected rows and the predicate that isolates their parent."""

    table: Table
    rows: tuple[dict[str, object], ...]
    predicates: tuple[ColumnElement[bool], ...]


@dataclass(frozen=True, slots=True)
class SessionDatabaseLoader:
    """Load one session after a global dataset build has been opened."""

    session_factory: sessionmaker[Session]
    raw_paths: RawDataPaths
    processed_paths: ProcessedDataPaths
    dataset_paths: DatasetPaths

    def __post_init__(self) -> None:
        """Require explicit database and artifact path dependencies."""
        if not isinstance(self.session_factory, sessionmaker):
            raise TypeError("session_factory must be a sessionmaker")

        if not isinstance(self.raw_paths, RawDataPaths):
            raise TypeError("raw_paths must be RawDataPaths")

        if not isinstance(self.processed_paths, ProcessedDataPaths):
            raise TypeError("processed_paths must be ProcessedDataPaths")

        if not isinstance(self.dataset_paths, DatasetPaths):
            raise TypeError("dataset_paths must be DatasetPaths")

    def load(
        self,
        session_key: SessionKey,
        *,
        run_id: str,
    ) -> SessionLoadResult:
        """Prepare outside SQL, then write and reconcile one transaction."""
        if not isinstance(run_id, str):
            raise TypeError("run_id must be a string")

        if not run_id or run_id != run_id.strip():
            raise DatabaseLoadError("run_id must be non-blank canonical text")

        prepared = prepare_session_artifacts(
            raw_paths=self.raw_paths,
            processed_paths=self.processed_paths,
            dataset_paths=self.dataset_paths,
            session_key=session_key,
        )

        with database_transaction(self.session_factory) as session:
            return _load_prepared_session(
                session,
                prepared=prepared,
                run_id=run_id,
            )


def _load_prepared_session(
    session: Session,
    *,
    prepared: PreparedSessionArtifacts,
    run_id: str,
) -> SessionLoadResult:
    """Write one prepared session inside its caller-owned transaction."""
    dataset_version = _dataset_contract_version(prepared)
    _require_global_load_context(
        session,
        prepared=prepared,
        dataset_version=dataset_version,
        run_id=run_id,
    )
    driver_ids = _upsert_reference_rows(session, prepared)
    partition_result = ImmutableRepository(
        ProcessedSessionPartition.__table__,
        (
            "session_id",
            "source_contract_version",
            "processed_contract_version",
            "cleaning_rule_version",
        ),
    ).insert_or_verify(
        session,
        _processed_partition_record(prepared),
    )
    processed_partition_id = int(
        partition_result.row["processed_partition_id"]
    )
    processed_loads = _processed_table_loads(
        prepared,
        driver_ids=driver_ids,
        processed_partition_id=processed_partition_id,
    )
    _persist_and_reconcile(
        session,
        processed_loads,
        insert_new=partition_result.status == "inserted",
    )

    _upsert_quality_reason_definitions(
        session,
        dataset_contract_version=dataset_version,
    )
    existing_dataset_session = _existing_dataset_session(
        session,
        dataset_contract_version=dataset_version,
        session_id=prepared.session_key.identifier,
    )
    created_by_run_id = (
        str(existing_dataset_session["created_by_run_id"])
        if existing_dataset_session is not None
        else run_id
    )
    dataset_result = ImmutableRepository(
        DatasetSession.__table__,
        ("dataset_contract_version", "session_id"),
    ).insert_or_verify(
        session,
        _dataset_session_record(
            prepared,
            processed_partition_id=processed_partition_id,
            created_by_run_id=created_by_run_id,
        ),
    )
    dataset_loads = _dataset_table_loads(
        prepared,
        driver_ids=driver_ids,
        processed_partition_id=processed_partition_id,
    )
    _persist_and_reconcile(
        session,
        dataset_loads,
        insert_new=dataset_result.status == "inserted",
    )

    return SessionLoadResult(
        status=_load_status(dataset_result.status),
        session_id=prepared.session_key.identifier,
        processed_partition_id=processed_partition_id,
        processed_laps=len(prepared.processed_laps),
        decision_rows=len(prepared.decision_rows),
        decision_labels=len(prepared.decision_labels),
        pit_duration_observations=len(
            prepared.pit_duration_observations
        ),
    )


def _load_status(status: RepositoryWriteStatus) -> SessionLoadStatus:
    """Translate repository terminology into loader terminology."""
    return "written" if status == "inserted" else "verified"


def _require_global_load_context(
    session: Session,
    *,
    prepared: PreparedSessionArtifacts,
    dataset_version: str,
    run_id: str,
) -> None:
    """Require a compatible immutable version and open batch run."""
    version = (
        session.execute(
            select(*DatasetVersion.__table__.c).where(
                DatasetVersion.dataset_contract_version == dataset_version
            )
        )
        .mappings()
        .one_or_none()
    )
    if version is None:
        raise DatabaseLoadError(
            f"dataset version {dataset_version!r} is not initialized"
        )

    expected_versions = {
        "database_schema_version": DATABASE_SCHEMA_VERSION,
        "source_contract_version": _source_contract_version(prepared),
        "processed_contract_version": _processed_contract_version(prepared),
        "cleaning_rule_version": _cleaning_rule_version(prepared),
    }
    version_differences = {
        field: (expected, version[field])
        for field, expected in expected_versions.items()
        if version[field] != expected
    }
    if version_differences:
        fields = ", ".join(sorted(version_differences))
        raise DatabaseLoadError(
            f"dataset version context differs for fields: {fields}"
        )

    build = (
        session.execute(
            select(*DatasetBuild.__table__.c).where(
                DatasetBuild.run_id == run_id
            )
        )
        .mappings()
        .one_or_none()
    )
    if build is None:
        raise DatabaseLoadError(f"dataset build {run_id!r} is not initialized")

    if build["dataset_contract_version"] != dataset_version:
        raise DatabaseLoadError(
            "dataset build and session contract versions differ"
        )

    if build["status"] != "RUNNING":
        raise DatabaseLoadError("dataset build must be RUNNING while loading")


def _upsert_reference_rows(
    session: Session,
    prepared: PreparedSessionArtifacts,
) -> dict[str, int]:
    """Insert or verify event and participant reference identities."""
    session_key = prepared.session_key
    metadata = prepared.raw_metadata
    ImmutableRepository(Season.__table__, ("season",)).insert_or_verify(
        session,
        {"season": session_key.season},
    )
    circuit = ImmutableRepository(
        Circuit.__table__,
        ("country", "location"),
    ).insert_or_verify(
        session,
        {
            "country": _source_text(metadata, "country"),
            "location": _source_text(metadata, "location"),
        },
    )
    event = ImmutableRepository(
        Event.__table__,
        ("season", "round_number"),
    ).insert_or_verify(
        session,
        {
            "season": session_key.season,
            "round_number": session_key.round_number,
            "circuit_id": int(circuit.row["circuit_id"]),
            "event_name": _source_text(metadata, "event_name"),
            "official_event_name": _source_text(
                metadata,
                "official_event_name",
            ),
            "event_date": _source_date(metadata, "event_date"),
            "event_format": _source_text(metadata, "event_format"),
        },
    )
    ImmutableRepository(
        RaceSession.__table__,
        ("session_id",),
    ).insert_or_verify(
        session,
        {
            "session_id": session_key.identifier,
            "event_id": int(event.row["event_id"]),
            "season": session_key.season,
            "round_number": session_key.round_number,
            "session_type": session_key.session_type,
        },
    )

    driver_ids: dict[str, int] = {}
    for driver_code, driver_number, team_name in _participant_sources(
        prepared.processed_laps
    ):
        driver = ImmutableRepository(
            Driver.__table__,
            ("driver_code",),
        ).insert_or_verify(
            session,
            {"driver_code": driver_code},
        )
        team = ImmutableRepository(
            Team.__table__,
            ("team_name",),
        ).insert_or_verify(
            session,
            {"team_name": team_name},
        )
        driver_id = int(driver.row["driver_id"])
        ImmutableRepository(
            SessionParticipant.__table__,
            ("session_id", "driver_id"),
        ).insert_or_verify(
            session,
            {
                "session_id": session_key.identifier,
                "driver_id": driver_id,
                "team_id": int(team.row["team_id"]),
                "driver_number": driver_number,
            },
        )
        driver_ids[driver_code] = driver_id

    return driver_ids


def _participant_sources(
    processed_laps: pd.DataFrame,
) -> tuple[tuple[str, str, str], ...]:
    """Derive one immutable participant identity per processed driver."""
    required_columns = {"Driver", "DriverNumber", "Team"}
    missing_columns = required_columns - set(processed_laps.columns)
    if missing_columns:
        names = ", ".join(sorted(missing_columns))
        raise DatabaseLoadError(f"processed laps lack participant fields: {names}")

    sources_by_driver: dict[str, tuple[str, str]] = {}
    for row in processed_laps.loc[
        :, ["Driver", "DriverNumber", "Team"]
    ].itertuples(index=False, name=None):
        driver_code = _canonical_text(row[0], field_name="Driver")
        driver_number = _driver_number(row[1])
        team_name = _canonical_text(row[2], field_name="Team")
        identity = (driver_number, team_name)
        existing = sources_by_driver.setdefault(driver_code, identity)
        if existing != identity:
            raise DatabaseLoadError(
                f"processed participant identity changes for {driver_code}"
            )

    if not sources_by_driver:
        raise DatabaseLoadError("processed laps contain no participants")

    return tuple(
        (driver_code, *identity)
        for driver_code, identity in sorted(sources_by_driver.items())
    )


def _processed_partition_record(
    prepared: PreparedSessionArtifacts,
) -> dict[str, object]:
    """Build immutable provenance for one processed partition."""
    files = _document_mapping(
        prepared.processed_manifest,
        "files",
        source="processed manifest",
    )
    return {
        "session_id": prepared.session_key.identifier,
        "source_contract_version": _source_contract_version(prepared),
        "processed_contract_version": _processed_contract_version(prepared),
        "cleaning_rule_version": _cleaning_rule_version(prepared),
        "created_at_utc": _source_datetime(
            prepared.processed_manifest,
            "created_at_utc",
            source="processed manifest",
        ),
        "session_directory": str(prepared.processed_directory),
        "source_manifest_sha256": prepared.raw_manifest_sha256,
        "processed_manifest_sha256": prepared.processed_manifest_sha256,
        "laps_sha256": _file_hash(files, "laps.parquet"),
        "stints_sha256": _file_hash(files, "stints.parquet"),
        "pit_events_sha256": _file_hash(files, "pit_events.parquet"),
        "quality_report_sha256": _file_hash(
            files,
            "quality_report.json",
        ),
        "laps_rows": len(prepared.processed_laps),
        "stints_rows": len(prepared.reconstructed_stints),
        "pit_events_rows": len(prepared.reconstructed_pit_events),
        "total_size_bytes": _total_size_bytes(files),
    }


def _dataset_session_record(
    prepared: PreparedSessionArtifacts,
    *,
    processed_partition_id: int,
    created_by_run_id: str,
) -> dict[str, object]:
    """Build the source-backed dataset-session provenance row."""
    manifest = prepared.dataset_manifest
    files = _document_mapping(manifest, "files", source="dataset manifest")
    decision_quality = _document_mapping(
        prepared.dataset_quality_report,
        "decision_quality",
        source="dataset quality report",
    )
    target_quality = _document_mapping(
        prepared.dataset_quality_report,
        "target_quality",
        source="dataset quality report",
    )
    counts = _dataset_counts(prepared)
    _require_report_count(
        decision_quality,
        field="eligible_decisions",
        expected=counts["eligible_decisions"],
        source="decision quality",
    )
    _require_report_count(
        decision_quality,
        field="ineligible_decisions",
        expected=counts["ineligible_decisions"],
        source="decision quality",
    )
    _require_report_count(
        decision_quality,
        field="historical_pit_now_actions",
        expected=counts["pit_now_rows"],
        source="decision quality",
    )
    _require_report_count(
        decision_quality,
        field="historical_stay_out_actions",
        expected=counts["stay_out_rows"],
        source="decision quality",
    )
    _require_report_count(
        target_quality,
        field="lap_time_target_eligible_rows",
        expected=counts["lap_time_target_eligible_rows"],
        source="target quality",
    )
    _require_report_count(
        target_quality,
        field="pit_duration_target_eligible_rows",
        expected=counts["pit_duration_target_eligible_rows"],
        source="target quality",
    )
    return {
        "dataset_contract_version": _dataset_contract_version(prepared),
        "session_id": prepared.session_key.identifier,
        "processed_partition_id": processed_partition_id,
        "created_by_run_id": created_by_run_id,
        "created_at_utc": _source_datetime(
            manifest,
            "created_at_utc",
            source="dataset manifest",
        ),
        "session_directory": str(prepared.dataset_directory),
        "dataset_manifest_sha256": prepared.dataset_manifest_sha256,
        "decision_rows_sha256": _file_hash(
            files,
            "decision_rows.parquet",
        ),
        "decision_labels_sha256": _file_hash(
            files,
            "decision_labels.parquet",
        ),
        "pit_duration_observations_sha256": _file_hash(
            files,
            "pit_duration_observations.parquet",
        ),
        "quality_report_sha256": _file_hash(
            files,
            "quality_report.json",
        ),
        "decision_rows": len(prepared.decision_rows),
        "eligible_decisions": counts["eligible_decisions"],
        "ineligible_decisions": counts["ineligible_decisions"],
        "decision_label_rows": len(prepared.decision_labels),
        "lap_time_target_eligible_rows": counts[
            "lap_time_target_eligible_rows"
        ],
        "pit_now_rows": counts["pit_now_rows"],
        "stay_out_rows": counts["stay_out_rows"],
        "pit_duration_rows": len(prepared.pit_duration_observations),
        "pit_duration_target_eligible_rows": counts[
            "pit_duration_target_eligible_rows"
        ],
        "total_size_bytes": _total_size_bytes(files),
    }


def _dataset_counts(
    prepared: PreparedSessionArtifacts,
) -> dict[str, int]:
    """Derive dataset-session counts directly from authoritative tables."""
    required_columns = {
        "decision_rows": {"decision_id", "is_decision_eligible"},
        "decision_labels": {
            "decision_id",
            "historical_action",
            "is_lap_time_target_eligible",
        },
        "pit_duration_observations": {
            "is_pit_duration_target_eligible"
        },
    }
    frames = {
        "decision_rows": prepared.decision_rows,
        "decision_labels": prepared.decision_labels,
        "pit_duration_observations": prepared.pit_duration_observations,
    }
    for table_name, columns in required_columns.items():
        missing = columns - set(frames[table_name].columns)
        if missing:
            names = ", ".join(sorted(missing))
            raise DatabaseLoadError(
                f"{table_name} lacks count reconciliation fields: {names}"
            )

    decision_ids = tuple(
        prepared.decision_rows["decision_id"].astype(str)
    )
    label_ids = tuple(
        prepared.decision_labels["decision_id"].astype(str)
    )
    if len(set(decision_ids)) != len(decision_ids):
        raise DatabaseLoadError("decision row identities are not unique")

    if set(decision_ids) != set(label_ids) or len(label_ids) != len(
        decision_ids
    ):
        raise DatabaseLoadError("decision row and label identities differ")

    eligible_mask = prepared.decision_rows[
        "is_decision_eligible"
    ].eq(True)
    eligible_ids = set(
        prepared.decision_rows.loc[eligible_mask, "decision_id"].astype(str)
    )
    eligible_labels = prepared.decision_labels.loc[
        prepared.decision_labels["decision_id"].astype(str).isin(eligible_ids)
    ]
    eligible_decisions = int(eligible_mask.sum())
    return {
        "eligible_decisions": eligible_decisions,
        "ineligible_decisions": len(prepared.decision_rows)
        - eligible_decisions,
        "pit_now_rows": int(
            eligible_labels["historical_action"].eq("PIT_NOW").sum()
        ),
        "stay_out_rows": int(
            eligible_labels["historical_action"].eq("STAY_OUT").sum()
        ),
        "lap_time_target_eligible_rows": int(
            eligible_labels["is_lap_time_target_eligible"].eq(True).sum()
        ),
        "pit_duration_target_eligible_rows": int(
            prepared.pit_duration_observations[
                "is_pit_duration_target_eligible"
            ]
            .eq(True)
            .sum()
        ),
    }


def _require_report_count(
    document: Mapping[str, object],
    *,
    field: str,
    expected: int,
    source: str,
) -> None:
    """Reconcile one stored report count against its source table."""
    actual = _document_integer(document, field, source=source)
    if actual != expected:
        raise DatabaseLoadError(
            f"{source} {field} differs: expected {expected}, got {actual}"
        )


def _processed_table_loads(
    prepared: PreparedSessionArtifacts,
    *,
    driver_ids: Mapping[str, int],
    processed_partition_id: int,
) -> tuple[_TableLoad, ...]:
    """Build exact processed analytical rows and reconciliation scopes."""
    session_id = prepared.session_key.identifier
    laps = _with_driver_ids(
        prepared.processed_laps,
        source_column="Driver",
        driver_ids=driver_ids,
    )
    stints = _with_driver_ids(
        prepared.reconstructed_stints,
        source_column="driver",
        driver_ids=driver_ids,
    )
    pit_events = _with_driver_ids(
        prepared.reconstructed_pit_events,
        source_column="driver",
        driver_ids=driver_ids,
    )
    return (
        _analytical_load(
            ProcessedLap.__table__,
            laps,
            {
                **PROCESSED_LAP_SOURCE_COLUMN_MAP,
                "__driver_id": "driver_id",
            },
            constants={
                "processed_partition_id": processed_partition_id,
                "session_id": session_id,
            },
            predicates=(
                ProcessedLap.processed_partition_id
                == processed_partition_id,
            ),
        ),
        _analytical_load(
            ReconstructedStint.__table__,
            stints,
            {
                **RECONSTRUCTED_STINT_SOURCE_COLUMN_MAP,
                "__driver_id": "driver_id",
            },
            constants={
                "processed_partition_id": processed_partition_id,
                "session_id": session_id,
            },
            predicates=(
                ReconstructedStint.processed_partition_id
                == processed_partition_id,
            ),
        ),
        _analytical_load(
            ReconstructedPitEvent.__table__,
            pit_events,
            {
                **RECONSTRUCTED_PIT_EVENT_SOURCE_COLUMN_MAP,
                "__driver_id": "driver_id",
            },
            constants={
                "processed_partition_id": processed_partition_id,
                "session_id": session_id,
            },
            predicates=(
                ReconstructedPitEvent.processed_partition_id
                == processed_partition_id,
            ),
        ),
    )


def _dataset_table_loads(
    prepared: PreparedSessionArtifacts,
    *,
    driver_ids: Mapping[str, int],
    processed_partition_id: int,
) -> tuple[_TableLoad, ...]:
    """Build exact dataset and normalized quality-link rows."""
    dataset_version = _dataset_contract_version(prepared)
    session_id = prepared.session_key.identifier
    decision_rows = _with_driver_ids(
        prepared.decision_rows,
        source_column="driver",
        driver_ids=driver_ids,
    )
    pit_durations = _with_driver_ids(
        prepared.pit_duration_observations,
        source_column="driver",
        driver_ids=driver_ids,
    )
    analytical_loads = (
        _analytical_load(
            DecisionRow.__table__,
            decision_rows,
            {**DECISION_ROW_SOURCE_COLUMN_MAP, "__driver_id": "driver_id"},
            constants={"processed_partition_id": processed_partition_id},
            predicates=(
                DecisionRow.dataset_contract_version == dataset_version,
                DecisionRow.session_id == session_id,
            ),
        ),
        _analytical_load(
            DecisionLabel.__table__,
            prepared.decision_labels,
            DECISION_LABEL_SOURCE_COLUMN_MAP,
            constants={"processed_partition_id": processed_partition_id},
            predicates=(
                DecisionLabel.dataset_contract_version == dataset_version,
                DecisionLabel.session_id == session_id,
            ),
        ),
        _analytical_load(
            PitDurationObservation.__table__,
            pit_durations,
            {
                **PIT_DURATION_OBSERVATION_SOURCE_COLUMN_MAP,
                "__driver_id": "driver_id",
            },
            constants={"processed_partition_id": processed_partition_id},
            predicates=(
                PitDurationObservation.dataset_contract_version
                == dataset_version,
                PitDurationObservation.session_id == session_id,
            ),
        ),
    )
    quality_loads = _quality_link_loads(
        prepared,
        dataset_version=dataset_version,
        processed_partition_id=processed_partition_id,
        stint_frame=_with_driver_ids(
            prepared.reconstructed_stints,
            source_column="driver",
            driver_ids=driver_ids,
        ),
    )
    return (*analytical_loads, *quality_loads)


def _quality_link_loads(
    prepared: PreparedSessionArtifacts,
    *,
    dataset_version: str,
    processed_partition_id: int,
    stint_frame: pd.DataFrame,
) -> tuple[_TableLoad, ...]:
    """Build all six normalized quality-reason link populations."""
    decision_ids = tuple(prepared.decision_rows["decision_id"].astype(str))
    pit_event_ids = tuple(
        prepared.pit_duration_observations["pit_event_id"].astype(str)
    )
    def partition_predicates(
        table: Table,
    ) -> tuple[ColumnElement[bool], ...]:
        return (
            table.c.dataset_contract_version == dataset_version,
            table.c.processed_partition_id == processed_partition_id,
        )
    return (
        _quality_load(
            ProcessedLapQualityReason.__table__,
            prepared.processed_laps,
            dataset_version=dataset_version,
            scope="PROCESSED_LAP",
            reason_column="QualityFlags",
            count_column="QualityFlagCount",
            identity_column_map={"SourceRowNumber": "source_row_number"},
            constants={"processed_partition_id": processed_partition_id},
            predicates=partition_predicates(
                ProcessedLapQualityReason.__table__
            ),
        ),
        _quality_load(
            StintQualityReason.__table__,
            stint_frame,
            dataset_version=dataset_version,
            scope="RECONSTRUCTED_STINT",
            reason_column="warnings",
            count_column="warning_count",
            identity_column_map={
                "__driver_id": "driver_id",
                "stint_number": "stint_number",
            },
            constants={"processed_partition_id": processed_partition_id},
            predicates=partition_predicates(StintQualityReason.__table__),
        ),
        _quality_load(
            PitEventQualityReason.__table__,
            prepared.reconstructed_pit_events,
            dataset_version=dataset_version,
            scope="RECONSTRUCTED_PIT_EVENT",
            reason_column="warnings",
            count_column="warning_count",
            identity_column_map={"pit_event_id": "pit_event_id"},
            constants={"processed_partition_id": processed_partition_id},
            predicates=partition_predicates(PitEventQualityReason.__table__),
        ),
        _quality_load(
            DecisionQualityReason.__table__,
            prepared.decision_rows,
            dataset_version=dataset_version,
            scope="DECISION",
            reason_column="decision_exclusion_reasons",
            count_column="decision_exclusion_count",
            identity_column_map={"decision_id": "decision_id"},
            predicates=(
                DecisionQualityReason.dataset_contract_version
                == dataset_version,
                DecisionQualityReason.decision_id.in_(decision_ids),
            ),
        ),
        _quality_load(
            LapTargetQualityReason.__table__,
            prepared.decision_labels,
            dataset_version=dataset_version,
            scope="LAP_TARGET",
            reason_column="lap_target_exclusion_reasons",
            count_column="lap_target_exclusion_count",
            identity_column_map={"decision_id": "decision_id"},
            predicates=(
                LapTargetQualityReason.dataset_contract_version
                == dataset_version,
                LapTargetQualityReason.decision_id.in_(decision_ids),
            ),
        ),
        _quality_load(
            PitDurationQualityReason.__table__,
            prepared.pit_duration_observations,
            dataset_version=dataset_version,
            scope="PIT_DURATION_TARGET",
            reason_column="pit_duration_exclusion_reasons",
            count_column="pit_duration_exclusion_count",
            identity_column_map={"pit_event_id": "pit_event_id"},
            predicates=(
                PitDurationQualityReason.dataset_contract_version
                == dataset_version,
                PitDurationQualityReason.pit_event_id.in_(pit_event_ids),
            ),
        ),
    )


def _analytical_load(
    table: Table,
    frame: pd.DataFrame,
    source_column_map: Mapping[str, str],
    *,
    constants: Mapping[str, object],
    predicates: tuple[ColumnElement[bool], ...],
) -> _TableLoad:
    """Materialize one verified frame as exact database records."""
    return _TableLoad(
        table=table,
        rows=tuple(
            iter_dataframe_records(
                frame,
                table,
                source_column_map,
                constants=constants,
            )
        ),
        predicates=predicates,
    )


def _quality_load(
    table: Table,
    frame: pd.DataFrame,
    *,
    dataset_version: str,
    scope: str,
    reason_column: str,
    count_column: str,
    identity_column_map: Mapping[str, str],
    predicates: tuple[ColumnElement[bool], ...],
    constants: Mapping[str, object] | None = None,
) -> _TableLoad:
    """Materialize one normalized quality-link population."""
    return _TableLoad(
        table=table,
        rows=tuple(
            iter_quality_reason_link_records(
                frame,
                table,
                dataset_contract_version=dataset_version,
                scope=scope,
                reason_column=reason_column,
                count_column=count_column,
                identity_column_map=identity_column_map,
                constants=constants,
            )
        ),
        predicates=predicates,
    )


def _with_driver_ids(
    frame: pd.DataFrame,
    *,
    source_column: str,
    driver_ids: Mapping[str, int],
) -> pd.DataFrame:
    """Attach only the surrogate join key derived from source driver codes."""
    if source_column not in frame.columns:
        raise DatabaseLoadError(f"source table lacks {source_column}")

    driver_codes = frame[source_column].astype(str)
    unknown_codes = set(driver_codes) - set(driver_ids)
    if unknown_codes:
        names = ", ".join(sorted(unknown_codes))
        raise DatabaseLoadError(f"source table has unknown drivers: {names}")

    enriched = frame.copy(deep=False)
    enriched["__driver_id"] = driver_codes.map(driver_ids)
    return enriched


def _upsert_quality_reason_definitions(
    session: Session,
    *,
    dataset_contract_version: str,
) -> None:
    """Insert or verify the complete frozen reason dictionary."""
    repository = ImmutableRepository(
        QualityReason.__table__,
        ("dataset_contract_version", "scope", "reason_code"),
    )
    for record in quality_reason_definition_records(
        dataset_contract_version
    ):
        repository.insert_or_verify(session, record)


def _persist_and_reconcile(
    session: Session,
    loads: Sequence[_TableLoad],
    *,
    insert_new: bool,
) -> None:
    """Insert when new and always verify exact stored rows before commit."""
    for load in loads:
        if insert_new:
            insert_rows(session, load.table, load.rows)

        session.flush()
        _reconcile_exact_rows(session, load)


def _reconcile_exact_rows(session: Session, load: _TableLoad) -> None:
    """Require every stored value under one parent to match its source."""
    primary_key_columns = tuple(load.table.primary_key.columns)
    statement = select(*load.table.c).where(*load.predicates)
    if primary_key_columns:
        statement = statement.order_by(*primary_key_columns)

    actual_rows = [
        dict(row)
        for row in session.execute(statement).mappings().all()
    ]
    expected_rows = sorted(
        load.rows,
        key=lambda row: tuple(
            row[column.name]
            for column in primary_key_columns
        ),
    )
    if len(actual_rows) != len(expected_rows):
        raise DatabaseLoadError(
            f"{load.table.name} row count differs: "
            f"expected {len(expected_rows)}, got {len(actual_rows)}"
        )

    for row_number, (expected, actual) in enumerate(
        zip(expected_rows, actual_rows, strict=True)
    ):
        differences = {
            field: (value, actual[field])
            for field, value in expected.items()
            if actual[field] != value
        }
        if differences:
            fields = ", ".join(sorted(differences))
            raise DatabaseLoadError(
                f"{load.table.name} row {row_number} differs: {fields}"
            )


def _existing_dataset_session(
    session: Session,
    *,
    dataset_contract_version: str,
    session_id: str,
) -> Mapping[str, object] | None:
    """Return an existing immutable session so retries keep creator provenance."""
    return (
        session.execute(
            select(*DatasetSession.__table__.c).where(
                DatasetSession.dataset_contract_version
                == dataset_contract_version,
                DatasetSession.session_id == session_id,
            )
        )
        .mappings()
        .one_or_none()
    )


def _dataset_contract_version(prepared: PreparedSessionArtifacts) -> str:
    """Return the verified dataset contract version."""
    return _source_text(
        prepared.dataset_manifest,
        "dataset_contract_version",
    )


def _source_contract_version(prepared: PreparedSessionArtifacts) -> str:
    """Return the verified raw-source contract version."""
    return _source_text(
        prepared.processed_manifest,
        "source_contract_version",
    )


def _processed_contract_version(prepared: PreparedSessionArtifacts) -> str:
    """Return the verified processed contract version."""
    return _source_text(
        prepared.processed_manifest,
        "processed_contract_version",
    )


def _cleaning_rule_version(prepared: PreparedSessionArtifacts) -> str:
    """Return the verified cleaning-rule version."""
    return _source_text(
        prepared.processed_manifest,
        "cleaning_rule_version",
    )


def _file_hash(files: dict[str, object], filename: str) -> str:
    """Return one verified file SHA-256 record."""
    record = _document_mapping(files, filename, source="manifest files")
    return _source_text(record, "sha256")


def _total_size_bytes(files: dict[str, object]) -> int:
    """Sum the authoritative file sizes described by one manifest."""
    return sum(
        _document_integer(
            _document_mapping(files, filename, source="manifest files"),
            "size_bytes",
            source=f"manifest file {filename}",
        )
        for filename in files
    )


def _source_text(
    document: Mapping[str, object],
    field: str,
) -> str:
    """Return exact non-blank canonical source text."""
    return _canonical_text(document.get(field), field_name=field)


def _canonical_text(value: object, *, field_name: str) -> str:
    """Require text that needs no cleaning before database insertion."""
    if not isinstance(value, str) or not value or value != value.strip():
        raise DatabaseLoadError(
            f"{field_name} must be non-blank canonical text"
        )

    return value


def _driver_number(value: object) -> str:
    """Represent a source driver number losslessly as database text."""
    if isinstance(value, str):
        return _canonical_text(value, field_name="DriverNumber")

    if isinstance(value, (int, np.integer)) and not isinstance(value, bool):
        return str(int(value))

    raise DatabaseLoadError("DriverNumber must be canonical text or an integer")


def _source_date(document: Mapping[str, object], field: str) -> date:
    """Parse one source ISO calendar date without timezone inference."""
    value = _source_text(document, field)
    try:
        return date.fromisoformat(value)
    except ValueError:
        pass

    try:
        return datetime.fromisoformat(value).date()
    except ValueError as error:
        raise DatabaseLoadError(
            f"{field} must be an ISO date or datetime"
        ) from error


def _source_datetime(
    document: Mapping[str, object],
    field: str,
    *,
    source: str,
) -> datetime:
    """Parse one required timezone-aware timestamp and normalize to UTC."""
    value = _source_text(document, field)
    try:
        converted = datetime.fromisoformat(value)
    except ValueError as error:
        raise DatabaseLoadError(
            f"{source} {field} must be an ISO timestamp"
        ) from error

    if converted.tzinfo is None or converted.utcoffset() is None:
        raise DatabaseLoadError(f"{source} {field} must be timezone-aware")

    return converted.astimezone(UTC)


def _document_mapping(
    document: Mapping[str, object],
    field: str,
    *,
    source: str,
) -> dict[str, object]:
    """Return one required nested document object."""
    value = document.get(field)
    if not isinstance(value, dict):
        raise DatabaseLoadError(f"{source} {field} must be an object")

    return value


def _document_integer(
    document: Mapping[str, object],
    field: str,
    *,
    source: str,
) -> int:
    """Return one non-negative integer without truncation."""
    value = document.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise DatabaseLoadError(f"{source} {field} must be an integer")

    converted = int(value)
    if converted < 0:
        raise DatabaseLoadError(f"{source} {field} must be non-negative")

    return converted
