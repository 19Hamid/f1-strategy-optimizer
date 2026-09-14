"""Convert verified analytical artifacts into exact database records."""

from __future__ import annotations

import math
from collections.abc import Iterator, Mapping
from datetime import UTC, date, datetime, timedelta
from numbers import Integral, Real
from typing import Final

import numpy as np
import pandas as pd
from sqlalchemy import ARRAY, Boolean, Date, DateTime, Float, Integer, Table
from sqlalchemy.sql.sqltypes import String

from app.db.quality_reasons import (
    QUALITY_REASON_CODES_BY_SCOPE,
    QUALITY_REASON_EXCLUSION_CODES_BY_SCOPE,
)

NANOSECOND_COLUMN_SUFFIX: Final = "_nanoseconds"


class DatabaseRecordError(ValueError):
    """Raised when a verified source value cannot be stored exactly."""


def iter_dataframe_records(
    frame: pd.DataFrame,
    table: Table,
    source_column_map: Mapping[str, str],
    *,
    constants: Mapping[str, object] | None = None,
) -> Iterator[dict[str, object]]:
    """Yield table-shaped records without changing analytical values."""
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("frame must be a pandas DataFrame")

    _require_table(table)
    mapping = _validate_source_mapping(
        frame=frame,
        table=table,
        source_column_map=source_column_map,
    )
    fixed_values = _validate_constants(
        table=table,
        constants=constants,
        mapped_destinations=frozenset(mapping.values()),
    )
    populated_columns = frozenset(mapping.values()) | frozenset(
        fixed_values
    )
    _require_insert_columns(table, populated_columns)

    source_columns = tuple(mapping)

    for source_values in frame.loc[:, source_columns].itertuples(
        index=False,
        name=None,
    ):
        record = dict(fixed_values)

        for source_column, value in zip(
            source_columns,
            source_values,
            strict=True,
        ):
            destination = mapping[source_column]
            record[destination] = _convert_value(
                table=table,
                column_name=destination,
                value=value,
            )

        yield record


def quality_reason_definition_records(
    dataset_contract_version: str,
) -> tuple[dict[str, object], ...]:
    """Return every frozen, versioned quality-reason definition."""
    if not isinstance(dataset_contract_version, str):
        raise TypeError("dataset_contract_version must be a string")

    if not dataset_contract_version:
        raise DatabaseRecordError(
            "dataset_contract_version must not be empty"
        )

    return tuple(
        {
            "dataset_contract_version": dataset_contract_version,
            "scope": scope,
            "reason_code": reason_code,
            "canonical_ordinal": ordinal,
            "is_exclusion": reason_code
            in QUALITY_REASON_EXCLUSION_CODES_BY_SCOPE[scope],
        }
        for scope, reason_codes in QUALITY_REASON_CODES_BY_SCOPE.items()
        for ordinal, reason_code in enumerate(reason_codes)
    )


def iter_quality_reason_link_records(
    frame: pd.DataFrame,
    table: Table,
    *,
    dataset_contract_version: str,
    scope: str,
    reason_column: str,
    count_column: str,
    identity_column_map: Mapping[str, str],
    constants: Mapping[str, object] | None = None,
) -> Iterator[dict[str, object]]:
    """Normalize one canonical pipe-delimited reason field into links."""
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("frame must be a pandas DataFrame")

    _require_table(table)
    if not isinstance(dataset_contract_version, str):
        raise TypeError("dataset_contract_version must be a string")

    if not dataset_contract_version:
        raise DatabaseRecordError(
            "dataset_contract_version must not be empty"
        )

    if scope not in QUALITY_REASON_CODES_BY_SCOPE:
        raise DatabaseRecordError(f"unknown quality-reason scope: {scope}")

    required_source_columns = {
        reason_column,
        count_column,
        *identity_column_map,
    }
    missing_source_columns = required_source_columns - set(frame.columns)

    if missing_source_columns:
        names = ", ".join(sorted(missing_source_columns))
        raise DatabaseRecordError(
            f"missing quality-link source columns: {names}"
        )

    fixed_values = _validate_constants(
        table=table,
        constants=constants,
        mapped_destinations=frozenset(identity_column_map.values())
        | {"dataset_contract_version", "scope"},
    )
    populated_columns = (
        frozenset(identity_column_map.values())
        | frozenset(fixed_values)
        | {
            "dataset_contract_version",
            "scope",
            "reason_code",
            "reason_ordinal",
        }
    )
    _require_insert_columns(table, populated_columns)
    canonical_codes = QUALITY_REASON_CODES_BY_SCOPE[scope]
    canonical_ordinals = {
        code: ordinal
        for ordinal, code in enumerate(canonical_codes)
    }

    for row_number, source_row in frame.iterrows():
        reasons = _parse_quality_reasons(
            source_row[reason_column],
            scope=scope,
            row_number=row_number,
            canonical_ordinals=canonical_ordinals,
        )
        recorded_count = _convert_integer(
            source_row[count_column],
            field_name=count_column,
        )

        if recorded_count != len(reasons):
            raise DatabaseRecordError(
                f"{scope} reason count differs at source row "
                f"{row_number!r}: recorded {recorded_count}, "
                f"parsed {len(reasons)}"
            )

        identity = {
            destination: _convert_value(
                table=table,
                column_name=destination,
                value=source_row[source_column],
            )
            for source_column, destination in identity_column_map.items()
        }

        for reason_ordinal, reason_code in enumerate(reasons):
            yield {
                **fixed_values,
                **identity,
                "dataset_contract_version": dataset_contract_version,
                "scope": scope,
                "reason_code": reason_code,
                "reason_ordinal": reason_ordinal,
            }


def _require_table(table: Table) -> None:
    """Require a concrete SQLAlchemy table."""
    if not isinstance(table, Table):
        raise TypeError("table must be a SQLAlchemy Table")


def _validate_source_mapping(
    *,
    frame: pd.DataFrame,
    table: Table,
    source_column_map: Mapping[str, str],
) -> dict[str, str]:
    """Require an exact, one-to-one source-to-table mapping."""
    if not isinstance(source_column_map, Mapping):
        raise TypeError("source_column_map must be a mapping")

    mapping = dict(source_column_map)
    missing_sources = set(mapping) - set(frame.columns)
    unexpected_sources = set(frame.columns) - set(mapping)
    unknown_destinations = set(mapping.values()) - set(table.c.keys())

    if missing_sources:
        names = ", ".join(sorted(missing_sources))
        raise DatabaseRecordError(f"missing source columns: {names}")

    if unexpected_sources:
        names = ", ".join(sorted(unexpected_sources))
        raise DatabaseRecordError(f"unmapped source columns: {names}")

    if unknown_destinations:
        names = ", ".join(sorted(unknown_destinations))
        raise DatabaseRecordError(f"unknown destination columns: {names}")

    if len(set(mapping.values())) != len(mapping):
        raise DatabaseRecordError(
            "source_column_map destinations must be unique"
        )

    return mapping


def _validate_constants(
    *,
    table: Table,
    constants: Mapping[str, object] | None,
    mapped_destinations: frozenset[str],
) -> dict[str, object]:
    """Validate and convert fixed values supplied for every source row."""
    if constants is None:
        return {}

    if not isinstance(constants, Mapping):
        raise TypeError("constants must be a mapping")

    unknown_columns = set(constants) - set(table.c.keys())
    overlapping_columns = set(constants) & mapped_destinations

    if unknown_columns:
        names = ", ".join(sorted(unknown_columns))
        raise DatabaseRecordError(f"unknown constant columns: {names}")

    if overlapping_columns:
        names = ", ".join(sorted(overlapping_columns))
        raise DatabaseRecordError(
            f"constant columns overlap source mapping: {names}"
        )

    return {
        column_name: _convert_value(
            table=table,
            column_name=column_name,
            value=value,
        )
        for column_name, value in constants.items()
    }


def _require_insert_columns(
    table: Table,
    populated_columns: frozenset[str],
) -> None:
    """Reject records that omit required non-generated table values."""
    missing_columns = {
        column.name
        for column in table.c
        if not column.nullable
        and column.default is None
        and column.server_default is None
        and column.name not in populated_columns
    }

    if missing_columns:
        names = ", ".join(sorted(missing_columns))
        raise DatabaseRecordError(f"missing required database columns: {names}")


def _convert_value(
    *,
    table: Table,
    column_name: str,
    value: object,
) -> object:
    """Convert one scalar only as required by its physical SQL type."""
    column = table.c[column_name]

    if _is_missing_scalar(value):
        if not column.nullable:
            raise DatabaseRecordError(
                f"{table.name}.{column_name} must not be null"
            )

        return None

    if column_name.endswith(NANOSECOND_COLUMN_SUFFIX):
        value = _convert_nanoseconds(value, field_name=column_name)

    column_type = column.type

    if isinstance(column_type, Boolean):
        if isinstance(value, (bool, np.bool_)):
            return bool(value)

        raise DatabaseRecordError(f"{column_name} must be a boolean")

    if isinstance(column_type, Integer):
        return _convert_integer(value, field_name=column_name)

    if isinstance(column_type, Float):
        if isinstance(value, bool) or not isinstance(value, Real):
            raise DatabaseRecordError(f"{column_name} must be numeric")

        converted = float(value)
        if not math.isfinite(converted):
            raise DatabaseRecordError(f"{column_name} must be finite")

        return converted

    if isinstance(column_type, DateTime):
        return _convert_datetime(
            value,
            field_name=column_name,
            timezone_required=bool(column_type.timezone),
        )

    if isinstance(column_type, Date):
        return _convert_date(value, field_name=column_name)

    if isinstance(column_type, String):
        if not isinstance(value, str):
            raise DatabaseRecordError(f"{column_name} must be a string")

        return value

    if isinstance(column_type, ARRAY):
        if not isinstance(value, (list, tuple)):
            raise DatabaseRecordError(f"{column_name} must be an array")

        return [
            _convert_integer(item, field_name=column_name)
            for item in value
        ]

    if isinstance(value, np.generic):
        return value.item()

    return value


def _is_missing_scalar(value: object) -> bool:
    """Return whether one scalar is a pandas-style missing value."""
    if value is None or value is pd.NA or value is pd.NaT:
        return True

    try:
        missing = pd.isna(value)
    except (TypeError, ValueError):
        return False

    return isinstance(missing, (bool, np.bool_)) and bool(missing)


def _convert_nanoseconds(value: object, *, field_name: str) -> int:
    """Convert an exact duration scalar to integer nanoseconds."""
    if isinstance(value, pd.Timedelta):
        return int(value.value)

    if isinstance(value, np.timedelta64):
        return int(pd.Timedelta(value).value)

    if isinstance(value, timedelta):
        return (
            (value.days * 86_400 + value.seconds) * 1_000_000_000
            + value.microseconds * 1_000
        )

    return _convert_integer(value, field_name=field_name)


def _convert_integer(value: object, *, field_name: str) -> int:
    """Convert integral numeric scalars without truncation."""
    if isinstance(value, bool):
        raise DatabaseRecordError(f"{field_name} must be an integer")

    if isinstance(value, Integral):
        return int(value)

    if isinstance(value, Real):
        converted = float(value)
        if math.isfinite(converted) and converted.is_integer():
            return int(converted)

    raise DatabaseRecordError(f"{field_name} must be an integer")


def _convert_datetime(
    value: object,
    *,
    field_name: str,
    timezone_required: bool,
) -> datetime:
    """Convert a timestamp and enforce timezone-aware UTC storage."""
    if isinstance(value, pd.Timestamp):
        converted = value.to_pydatetime()
    elif isinstance(value, datetime):
        converted = value
    else:
        raise DatabaseRecordError(f"{field_name} must be a datetime")

    if timezone_required:
        if converted.tzinfo is None or converted.utcoffset() is None:
            raise DatabaseRecordError(
                f"{field_name} must be timezone-aware"
            )

        return converted.astimezone(UTC)

    return converted


def _convert_date(value: object, *, field_name: str) -> date:
    """Convert a source date without guessing a non-ISO representation."""
    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass

    raise DatabaseRecordError(f"{field_name} must be an ISO date")


def _parse_quality_reasons(
    value: object,
    *,
    scope: str,
    row_number: object,
    canonical_ordinals: Mapping[str, int],
) -> tuple[str, ...]:
    """Validate a canonical pipe-delimited quality-reason sequence."""
    if not isinstance(value, str):
        raise DatabaseRecordError(
            f"{scope} reasons must be text at source row {row_number!r}"
        )

    reasons = () if not value else tuple(value.split("|"))
    if len(reasons) != len(set(reasons)):
        raise DatabaseRecordError(
            f"{scope} reasons contain duplicates at source row "
            f"{row_number!r}"
        )

    unknown_reasons = set(reasons) - set(canonical_ordinals)
    if unknown_reasons:
        names = ", ".join(sorted(unknown_reasons))
        raise DatabaseRecordError(
            f"{scope} reasons are unknown at source row "
            f"{row_number!r}: {names}"
        )

    expected = tuple(
        sorted(reasons, key=canonical_ordinals.__getitem__)
    )
    if reasons != expected:
        raise DatabaseRecordError(
            f"{scope} reasons are not in canonical order at source row "
            f"{row_number!r}"
        )

    return reasons
