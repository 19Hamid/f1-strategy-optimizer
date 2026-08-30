"""Profile raw development data without inspecting evaluation races."""

from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from app.pipeline.models import SessionKey
from app.pipeline.serialization import read_parquet_table

DEVELOPMENT_SEASONS = (2022, 2023, 2024)

CATALOG_REQUIRED_COLUMNS = (
    "session_id",
    "season",
    "round_number",
    "session_type",
)

LAP_IDENTITY_COLUMNS = (
    "Season",
    "RoundNumber",
    "SessionType",
    "Driver",
    "LapNumber",
)

REQUIRED_LAP_VALUE_COLUMNS = (
    "Driver",
    "Team",
    "LapNumber",
    "LapTime",
    "Stint",
    "Compound",
    "TyreLife",
    "TrackStatus",
    "LapStartTime",
    "IsAccurate",
)

SECTOR_TIME_COLUMNS = (
    "Sector1Time",
    "Sector2Time",
    "Sector3Time",
)

LAP_PROFILE_COLUMNS = (
    *LAP_IDENTITY_COLUMNS,
    *REQUIRED_LAP_VALUE_COLUMNS,
    *SECTOR_TIME_COLUMNS,
    "PitInTime",
    "PitOutTime",
    "Deleted",
    "FastF1Generated",
)

QUALITY_COUNT_KEYS = (
    "duplicate_laps",
    "missing_lap_times",
    "non_positive_lap_times",
    "inaccurate_laps",
    "missing_accuracy",
    "first_laps",
    "pit_in_laps",
    "pit_out_laps",
    "missing_sector_laps",
    "invalid_tyre_life",
    "deleted_laps",
    "generated_laps",
)

MISSING_VALUE_LABEL = "<MISSING>"
WET_COMPOUNDS = frozenset({"INTERMEDIATE", "WET"})


class DataProfileError(RuntimeError):
    """Indicate that development data cannot be profiled safely."""


@dataclass(frozen=True, slots=True)
class DevelopmentDataProfile:
    """Store aggregated quality information for development races."""

    session_count: int
    seasons: tuple[int, ...]
    row_counts: dict[str, int]
    quality_counts: dict[str, int]
    missing_required_lap_values: dict[str, int]
    track_status_counts: dict[str, int]
    compound_counts: dict[str, int]
    rainy_sessions: tuple[str, ...]
    wet_compound_sessions: tuple[str, ...]
    sessions_with_duplicate_laps: dict[str, int]
    sessions_with_missing_lap_times: dict[str, int]
    lap_dtype_conflicts: dict[str, tuple[str, ...]]
    result_status_counts: dict[str, int]


class _ProfileAccumulator:
    """Accumulate profile statistics across multiple race sessions."""

    def __init__(self) -> None:
        self._row_counts: Counter[str] = Counter()
        self._quality_counts: Counter[str] = Counter()
        self._missing_lap_values: Counter[str] = Counter()
        self._track_status_counts: Counter[str] = Counter()
        self._compound_counts: Counter[str] = Counter()
        self._result_status_counts: Counter[str] = Counter()
        self._observed_lap_dtypes: defaultdict[str, set[str]] = (
            defaultdict(set)
        )
        self._rainy_sessions: set[str] = set()
        self._wet_compound_sessions: set[str] = set()
        self._duplicate_sessions: dict[str, int] = {}
        self._missing_lap_time_sessions: dict[str, int] = {}

    def add_laps(
        self,
        session_id: str,
        laps: pd.DataFrame,
    ) -> None:
        """Add one session's lap statistics."""
        _require_columns(
            laps,
            LAP_PROFILE_COLUMNS,
            table_name="laps",
        )

        self._row_counts["laps"] += len(laps)

        for column in REQUIRED_LAP_VALUE_COLUMNS:
            self._missing_lap_values[column] += int(
                laps[column].isna().sum()
            )

        for column, dtype in laps.dtypes.items():
            self._observed_lap_dtypes[column].add(str(dtype))

        duplicate_mask = laps.duplicated(
            subset=LAP_IDENTITY_COLUMNS,
            keep=False,
        )
        duplicate_count = _count_true(duplicate_mask)
        self._quality_counts["duplicate_laps"] += duplicate_count

        if duplicate_count:
            self._duplicate_sessions[session_id] = duplicate_count

        missing_lap_time_count = int(laps["LapTime"].isna().sum())
        self._quality_counts[
            "missing_lap_times"
        ] += missing_lap_time_count

        if missing_lap_time_count:
            self._missing_lap_time_sessions[
                session_id
            ] = missing_lap_time_count

        zero_duration = pd.to_timedelta(0, unit="s")

        self._quality_counts["non_positive_lap_times"] += _count_true(
            laps["LapTime"].notna()
            & laps["LapTime"].le(zero_duration)
        )
        self._quality_counts["inaccurate_laps"] += _count_true(
            laps["IsAccurate"].eq(False)
        )
        self._quality_counts["missing_accuracy"] += int(
            laps["IsAccurate"].isna().sum()
        )
        self._quality_counts["first_laps"] += _count_true(
            laps["LapNumber"].eq(1)
        )
        self._quality_counts["pit_in_laps"] += int(
            laps["PitInTime"].notna().sum()
        )
        self._quality_counts["pit_out_laps"] += int(
            laps["PitOutTime"].notna().sum()
        )
        self._quality_counts["missing_sector_laps"] += _count_true(
            laps.loc[:, [*SECTOR_TIME_COLUMNS]]
            .isna()
            .any(axis=1)
        )
        self._quality_counts["invalid_tyre_life"] += _count_true(
            laps["TyreLife"].notna()
            & laps["TyreLife"].le(0)
        )
        self._quality_counts["deleted_laps"] += _count_true(
            laps["Deleted"].eq(True)
        )
        self._quality_counts["generated_laps"] += _count_true(
            laps["FastF1Generated"].eq(True)
        )

        track_statuses = _string_values(laps["TrackStatus"])
        self._track_status_counts.update(track_statuses.tolist())

        compounds = _uppercase_string_values(laps["Compound"])
        self._compound_counts.update(compounds.tolist())

        if compounds.isin(WET_COMPOUNDS).any():
            self._wet_compound_sessions.add(session_id)

    def add_weather(
        self,
        session_id: str,
        weather: pd.DataFrame,
    ) -> None:
        """Add one session's weather statistics."""
        _require_columns(
            weather,
            ("Rainfall",),
            table_name="weather",
        )

        self._row_counts["weather"] += len(weather)

        if _count_true(weather["Rainfall"]):
            self._rainy_sessions.add(session_id)

    def add_results(self, results: pd.DataFrame) -> None:
        """Add one session's result statistics."""
        _require_columns(
            results,
            ("Status",),
            table_name="results",
        )

        self._row_counts["results"] += len(results)
        statuses = _string_values(results["Status"])
        self._result_status_counts.update(statuses.tolist())

    def build(
        self,
        *,
        session_count: int,
        seasons: tuple[int, ...],
    ) -> DevelopmentDataProfile:
        """Build an immutable profile from accumulated statistics."""
        dtype_conflicts = {
            column: tuple(sorted(dtypes))
            for column, dtypes in sorted(
                self._observed_lap_dtypes.items()
            )
            if len(dtypes) > 1
        }

        return DevelopmentDataProfile(
            session_count=session_count,
            seasons=seasons,
            row_counts={
                table_name: self._row_counts[table_name]
                for table_name in ("laps", "weather", "results")
            },
            quality_counts={
                key: self._quality_counts[key]
                for key in QUALITY_COUNT_KEYS
            },
            missing_required_lap_values={
                column: self._missing_lap_values[column]
                for column in REQUIRED_LAP_VALUE_COLUMNS
            },
            track_status_counts=_sorted_counter(
                self._track_status_counts
            ),
            compound_counts=_sorted_counter(
                self._compound_counts
            ),
            rainy_sessions=tuple(sorted(self._rainy_sessions)),
            wet_compound_sessions=tuple(
                sorted(self._wet_compound_sessions)
            ),
            sessions_with_duplicate_laps=dict(
                sorted(self._duplicate_sessions.items())
            ),
            sessions_with_missing_lap_times=dict(
                sorted(self._missing_lap_time_sessions.items())
            ),
            lap_dtype_conflicts=dtype_conflicts,
            result_status_counts=_sorted_counter(
                self._result_status_counts
            ),
        )


def profile_development_data(
    raw_root: Path,
    *,
    seasons: tuple[int, ...] = DEVELOPMENT_SEASONS,
) -> DevelopmentDataProfile:
    """Profile selected development seasons from the raw-data store."""
    normalized_seasons = _normalize_seasons(seasons)
    raw_root = Path(raw_root)

    catalog = _read_required_table(
        raw_root / "catalog.parquet",
        table_name="catalog",
    )
    _require_columns(
        catalog,
        CATALOG_REQUIRED_COLUMNS,
        table_name="catalog",
    )

    selected_catalog = (
        catalog.loc[catalog["season"].isin(normalized_seasons)]
        .sort_values(["season", "round_number"])
        .reset_index(drop=True)
    )

    if selected_catalog.empty:
        raise DataProfileError(
            "catalog contains no sessions for the selected "
            "development seasons"
        )

    accumulator = _ProfileAccumulator()

    for record in selected_catalog.itertuples(index=False):
        session_key = SessionKey(
            season=int(record.season),
            round_number=int(record.round_number),
            session_type=str(record.session_type),
        )
        session_id = str(record.session_id)

        if session_id != session_key.identifier:
            raise DataProfileError(
                "catalog session identity does not match its "
                f"partition fields: {session_id}"
            )

        session_directory = raw_root.joinpath(
            *session_key.partition_parts
        )

        accumulator.add_laps(
            session_id,
            _read_required_table(
                session_directory / "laps.parquet",
                table_name="laps",
            ),
        )
        accumulator.add_weather(
            session_id,
            _read_required_table(
                session_directory / "weather.parquet",
                table_name="weather",
            ),
        )
        accumulator.add_results(
            _read_required_table(
                session_directory / "results.parquet",
                table_name="results",
            )
        )

    return accumulator.build(
        session_count=len(selected_catalog),
        seasons=normalized_seasons,
    )


def _normalize_seasons(
    seasons: tuple[int, ...],
) -> tuple[int, ...]:
    """Validate and normalize development-season selection."""
    if not seasons:
        raise ValueError("at least one development season is required")

    normalized: list[int] = []

    for season in seasons:
        if isinstance(season, bool) or not isinstance(season, int):
            raise TypeError("every season must be an integer")

        if season not in DEVELOPMENT_SEASONS:
            raise ValueError(
                "profiling is restricted to development seasons "
                "2022, 2023 and 2024"
            )

        normalized.append(season)

    if len(normalized) != len(set(normalized)):
        raise ValueError("development seasons must not contain duplicates")

    return tuple(sorted(normalized))


def _read_required_table(
    path: Path,
    *,
    table_name: str,
) -> pd.DataFrame:
    """Read a required Parquet table."""
    if not path.is_file():
        raise DataProfileError(
            f"{table_name} table does not exist: {path}"
        )

    return read_parquet_table(path)


def _require_columns(
    table: pd.DataFrame,
    required_columns: tuple[str, ...],
    *,
    table_name: str,
) -> None:
    """Confirm that a table contains all required profile columns."""
    missing_columns = sorted(
        set(required_columns).difference(table.columns)
    )

    if missing_columns:
        missing_text = ", ".join(missing_columns)
        raise DataProfileError(
            f"{table_name} table is missing required columns: "
            f"{missing_text}"
        )


def _count_true(mask: pd.Series) -> int:
    """Count true values while treating missing values as false."""
    normalized = mask.astype("boolean").fillna(False)
    return int(normalized.sum())


def _string_values(values: pd.Series) -> pd.Series:
    """Convert values to consistent nullable strings."""
    return values.astype("string").fillna(MISSING_VALUE_LABEL)


def _uppercase_string_values(values: pd.Series) -> pd.Series:
    """Convert values to normalized uppercase strings."""
    return _string_values(values).str.upper()


def _sorted_counter(counter: Counter[str]) -> dict[str, int]:
    """Convert a Counter into a deterministic dictionary."""
    return dict(sorted(counter.items()))