"""Tests for exact artifact-to-database record conversion."""

from datetime import UTC, date, datetime

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import (
    ARRAY,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    Integer,
    MetaData,
    Table,
)
from sqlalchemy import String as SqlString

from app.db import ProcessedLapQualityReason
from app.db.records import (
    DatabaseRecordError,
    iter_dataframe_records,
    iter_quality_reason_link_records,
    quality_reason_definition_records,
)


def _record_table() -> Table:
    """Build a small table covering physical conversion types."""
    return Table(
        "record_values",
        MetaData(),
        Column("row_id", Integer, primary_key=True),
        Column("duration_nanoseconds", Integer, nullable=True),
        Column("observed_at_utc", DateTime(timezone=True), nullable=True),
        Column("event_date", Date, nullable=False),
        Column("enabled", Boolean, nullable=False),
        Column("measurement", Float, nullable=False),
        Column("label", SqlString, nullable=False),
        Column("seasons", ARRAY(Integer), nullable=False),
    )


def _record_frame() -> pd.DataFrame:
    """Build one source row with pandas and NumPy scalar types."""
    return pd.DataFrame(
        {
            "id": [np.int64(7)],
            "duration": [pd.Timedelta(1_250_000_000, unit="ns")],
            "observed": [pd.Timestamp("2024-03-02T01:00:00+01:00")],
            "date": ["2024-03-02"],
            "enabled": [np.bool_(True)],
            "measurement": [np.float64(12.5)],
            "label": ["VER"],
            "seasons": [(2022, np.int64(2023))],
        }
    )


def _record_mapping() -> dict[str, str]:
    """Return the complete source-to-destination mapping."""
    return {
        "id": "row_id",
        "duration": "duration_nanoseconds",
        "observed": "observed_at_utc",
        "date": "event_date",
        "enabled": "enabled",
        "measurement": "measurement",
        "label": "label",
        "seasons": "seasons",
    }


def test_dataframe_records_preserve_values_with_physical_conversions() -> None:
    """Convert only representations required by PostgreSQL columns."""
    records = list(
        iter_dataframe_records(
            _record_frame(),
            _record_table(),
            _record_mapping(),
        )
    )

    assert records == [
        {
            "row_id": 7,
            "duration_nanoseconds": 1_250_000_000,
            "observed_at_utc": datetime(
                2024,
                3,
                2,
                0,
                0,
                tzinfo=UTC,
            ),
            "event_date": date(2024, 3, 2),
            "enabled": True,
            "measurement": 12.5,
            "label": "VER",
            "seasons": [2022, 2023],
        }
    ]


def test_dataframe_records_convert_nullable_missing_scalars_to_none() -> None:
    """Translate pandas missing sentinels only for nullable fields."""
    frame = _record_frame()
    frame.loc[0, "duration"] = pd.NaT
    frame.loc[0, "observed"] = pd.NaT

    record = next(
        iter_dataframe_records(
            frame,
            _record_table(),
            _record_mapping(),
        )
    )

    assert record["duration_nanoseconds"] is None
    assert record["observed_at_utc"] is None


def test_dataframe_records_reject_naive_timestamps() -> None:
    """Never guess a timezone for a stored UTC timestamp."""
    frame = _record_frame()
    frame["observed"] = frame["observed"].astype(object)
    frame.loc[0, "observed"] = pd.Timestamp("2024-03-02T00:00:00")

    with pytest.raises(
        DatabaseRecordError,
        match="observed_at_utc must be timezone-aware",
    ):
        list(
            iter_dataframe_records(
                frame,
                _record_table(),
                _record_mapping(),
            )
        )


def test_dataframe_records_reject_fractional_integers() -> None:
    """Do not truncate an analytical value to fit an integer column."""
    frame = _record_frame()
    frame["id"] = frame["id"].astype(object)
    frame.loc[0, "id"] = 7.5

    with pytest.raises(
        DatabaseRecordError,
        match="row_id must be an integer",
    ):
        list(
            iter_dataframe_records(
                frame,
                _record_table(),
                _record_mapping(),
            )
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda frame: frame.drop(columns="label"), "missing source columns"),
        (
            lambda frame: frame.assign(unexpected="value"),
            "unmapped source columns",
        ),
    ],
)
def test_dataframe_records_require_exact_source_columns(
    mutation: object,
    message: str,
) -> None:
    """Fail closed when the verified source schema and map diverge."""
    frame = mutation(_record_frame())  # type: ignore[operator]

    with pytest.raises(DatabaseRecordError, match=message):
        list(
            iter_dataframe_records(
                frame,
                _record_table(),
                _record_mapping(),
            )
        )


def test_dataframe_records_reject_null_required_values() -> None:
    """Reject source nulls for non-null database columns."""
    frame = _record_frame()
    frame.loc[0, "label"] = None

    with pytest.raises(
        DatabaseRecordError,
        match="record_values.label must not be null",
    ):
        list(
            iter_dataframe_records(
                frame,
                _record_table(),
                _record_mapping(),
            )
        )


def test_quality_reason_definitions_cover_frozen_scopes() -> None:
    """Build the complete versioned reason dictionary deterministically."""
    records = quality_reason_definition_records("1.0")

    assert len(records) == 72
    assert records[0] == {
        "dataset_contract_version": "1.0",
        "scope": "PROCESSED_LAP",
        "reason_code": "MISSING_IDENTITY",
        "canonical_ordinal": 0,
        "is_exclusion": True,
    }
    assert records[-1]["scope"] == "PIT_DURATION_TARGET"
    assert records[-1]["canonical_ordinal"] == 5


def test_quality_reason_links_preserve_source_order() -> None:
    """Expand canonical source reasons into normalized ordered links."""
    frame = pd.DataFrame(
        {
            "SourceRowNumber": [np.int64(9)],
            "QualityFlags": ["FIRST_LAP|MISSING_SECTOR_TIME"],
            "QualityFlagCount": [2],
        }
    )

    records = list(
        iter_quality_reason_link_records(
            frame,
            ProcessedLapQualityReason.__table__,
            dataset_contract_version="1.0",
            scope="PROCESSED_LAP",
            reason_column="QualityFlags",
            count_column="QualityFlagCount",
            identity_column_map={
                "SourceRowNumber": "source_row_number",
            },
            constants={"processed_partition_id": 42},
        )
    )

    assert records == [
        {
            "processed_partition_id": 42,
            "source_row_number": 9,
            "dataset_contract_version": "1.0",
            "scope": "PROCESSED_LAP",
            "reason_code": "FIRST_LAP",
            "reason_ordinal": 0,
        },
        {
            "processed_partition_id": 42,
            "source_row_number": 9,
            "dataset_contract_version": "1.0",
            "scope": "PROCESSED_LAP",
            "reason_code": "MISSING_SECTOR_TIME",
            "reason_ordinal": 1,
        },
    ]


@pytest.mark.parametrize(
    ("reasons", "count", "message"),
    [
        ("FIRST_LAP", 2, "reason count differs"),
        ("NOT_A_REASON", 1, "reasons are unknown"),
        (
            "MISSING_SECTOR_TIME|FIRST_LAP",
            2,
            "reasons are not in canonical order",
        ),
        ("FIRST_LAP|FIRST_LAP", 2, "reasons contain duplicates"),
    ],
)
def test_quality_reason_links_reject_noncanonical_sources(
    reasons: str,
    count: int,
    message: str,
) -> None:
    """Reject reason strings that disagree with their frozen contract."""
    frame = pd.DataFrame(
        {
            "SourceRowNumber": [9],
            "QualityFlags": [reasons],
            "QualityFlagCount": [count],
        }
    )

    with pytest.raises(DatabaseRecordError, match=message):
        list(
            iter_quality_reason_link_records(
                frame,
                ProcessedLapQualityReason.__table__,
                dataset_contract_version="1.0",
                scope="PROCESSED_LAP",
                reason_column="QualityFlags",
                count_column="QualityFlagCount",
                identity_column_map={
                    "SourceRowNumber": "source_row_number",
                },
                constants={"processed_partition_id": 42},
            )
        )
