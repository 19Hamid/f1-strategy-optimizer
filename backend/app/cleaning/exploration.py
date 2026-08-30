"""Explore verified processed development data reproducibly."""

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import numpy as np
import pandas as pd

from app.cleaning.integrity import (
    verify_processed_partition,
)
from app.cleaning.paths import ProcessedDataPaths
from app.cleaning.profile import DEVELOPMENT_SEASONS
from app.pipeline.models import SessionKey
from app.pipeline.serialization import (
    read_parquet_table,
)

EXPLORATION_VERSION: Final = "1.0"
LAP_OUTLIER_POLICY: Final = "FLAG_ONLY"
ROBUST_OUTLIER_THRESHOLD: Final = 6.0
MINIMUM_CONTEXT_ROWS: Final = 5
SHARED_LAP_DRIVER_THRESHOLD: Final = 5

_LAP_COLUMNS: Final = (
    "Season",
    "RoundNumber",
    "SessionType",
    "EventName",
    "Driver",
    "Team",
    "LapNumber",
    "Compound",
    "TyreLife",
    "LapTimeSeconds",
    "TrackStatus",
    "Rainfall",
    "WeatherAgeSeconds",
    "FastF1Generated",
    "IsEligible",
)

_STINT_COLUMNS: Final = (
    "season",
    "round_number",
    "session_type",
    "event_name",
    "driver",
    "team",
    "stint_number",
    "compound",
    "start_lap",
    "end_lap",
    "recorded_laps",
    "is_complete",
)

_PIT_EVENT_COLUMNS: Final = (
    "season",
    "round_number",
    "session_type",
    "event_name",
    "driver",
    "team",
    "compound_before",
    "compound_after",
    "observed_pit_lane_duration_seconds",
    "is_duration_analysis_candidate",
)

_SESSION_SUMMARY_COLUMNS: Final = (
    "session_id",
    "season",
    "round_number",
    "event_name",
    "input_laps",
    "eligible_laps",
    "excluded_laps",
    "eligibility_rate",
    "potential_lap_outliers",
)

_COMPOUND_SUMMARY_COLUMNS: Final = (
    "compound",
    "eligible_laps",
    "median_lap_time_seconds",
    "median_tyre_life",
    "maximum_tyre_life",
    "potential_lap_outliers",
)

_STINT_SUMMARY_COLUMNS: Final = (
    "compound",
    "stints",
    "complete_stints",
    "median_recorded_laps",
    "mean_recorded_laps",
    "p95_recorded_laps",
    "maximum_recorded_laps",
)

_PIT_DURATION_SUMMARY_COLUMNS: Final = (
    "event_name",
    "events",
    "minimum_seconds",
    "p05_seconds",
    "median_seconds",
    "p95_seconds",
    "maximum_seconds",
)

_OUTLIER_COLUMNS: Final = (
    "session_id",
    "Season",
    "RoundNumber",
    "EventName",
    "Driver",
    "Team",
    "LapNumber",
    "Compound",
    "TyreLife",
    "LapTimeSeconds",
    "ContextRows",
    "ContextMedianLapTimeSeconds",
    "ContextLapDeltaSeconds",
    "ContextMadSeconds",
    "ContextRobustScore",
    "OutlierDirection",
    "SharedLapOutlierDrivers",
    "IsSharedLapCluster",
    "TrackStatus",
    "Rainfall",
    "WeatherAgeSeconds",
    "FastF1Generated",
)


class DevelopmentExplorationError(RuntimeError):
    """Raised when development exploration cannot be completed."""


@dataclass(frozen=True, slots=True)
class DevelopmentExplorationResult:
    """Contain reproducible development-data exploration results."""

    seasons: tuple[int, ...]
    exploration_version: str
    lap_outlier_policy: str
    session_count: int
    processed_lap_count: int
    eligible_lap_count: int
    excluded_lap_count: int
    stint_count: int
    dry_stint_count: int
    pit_event_count: int
    duration_analysis_candidate_count: int
    potential_lap_outlier_count: int
    shared_lap_outlier_count: int
    session_summary: pd.DataFrame
    compound_summary: pd.DataFrame
    stint_summary: pd.DataFrame
    pit_duration_summary: pd.DataFrame
    potential_lap_outliers: pd.DataFrame


def explore_development_data(
    processed_paths: ProcessedDataPaths,
    seasons: Iterable[int] = DEVELOPMENT_SEASONS,
) -> DevelopmentExplorationResult:
    """Explore verified processed development partitions."""
    if not isinstance(
        processed_paths,
        ProcessedDataPaths,
    ):
        raise TypeError(
            "processed_paths must be ProcessedDataPaths"
        )

    selected_seasons = _validate_seasons(seasons)
    catalog = _load_catalog(
        processed_paths=processed_paths,
        seasons=selected_seasons,
    )

    lap_tables: list[pd.DataFrame] = []
    stint_tables: list[pd.DataFrame] = []
    pit_event_tables: list[pd.DataFrame] = []

    for row in catalog.itertuples(index=False):
        session_key = SessionKey(
            season=int(row.season),
            round_number=int(row.round_number),
            session_type=str(row.session_type),
        )

        _verify_session(
            processed_paths=processed_paths,
            session_key=session_key,
        )

        session_paths = processed_paths.for_session(
            session_key
        )

        laps = _load_required_table(
            path=session_paths.laps,
            columns=_LAP_COLUMNS,
            table_name="laps",
        )
        stints = _load_required_table(
            path=session_paths.stints,
            columns=_STINT_COLUMNS,
            table_name="stints",
        )
        pit_events = _load_required_table(
            path=session_paths.pit_events,
            columns=_PIT_EVENT_COLUMNS,
            table_name="pit events",
        )

        _validate_session_table_counts(
            session_key=session_key,
            laps=laps,
            expected_laps=int(row.laps_rows),
            stints=stints,
            expected_stints=int(row.stints_rows),
            pit_events=pit_events,
            expected_pit_events=int(
                row.pit_events_rows
            ),
        )

        session_id = session_key.identifier

        lap_tables.append(
            laps.assign(session_id=session_id)
        )
        stint_tables.append(
            stints.assign(session_id=session_id)
        )
        pit_event_tables.append(
            pit_events.assign(
                session_id=session_id
            )
        )

    laps = pd.concat(
        lap_tables,
        ignore_index=True,
    )
    stints = pd.concat(
        stint_tables,
        ignore_index=True,
    )
    pit_events = pd.concat(
        pit_event_tables,
        ignore_index=True,
    )

    _validate_combined_counts(
        catalog=catalog,
        laps=laps,
        stints=stints,
        pit_events=pit_events,
    )

    eligible_laps = _prepare_eligible_laps(laps)
    potential_outliers = _identify_lap_outliers(
        eligible_laps
    )

    session_summary = _build_session_summary(
        laps=laps,
        potential_outliers=potential_outliers,
    )
    compound_summary = _build_compound_summary(
        eligible_laps=eligible_laps,
        potential_outliers=potential_outliers,
    )

    dry_stints = stints.loc[
        stints["compound"].isin(
            ["SOFT", "MEDIUM", "HARD"]
        )
    ].copy()

    stint_summary = _build_stint_summary(
        dry_stints
    )

    duration_candidates = pit_events.loc[
        pit_events[
            "is_duration_analysis_candidate"
        ]
    ].copy()

    pit_duration_summary = (
        _build_pit_duration_summary(
            duration_candidates
        )
    )

    eligible_lap_count = len(eligible_laps)
    excluded_lap_count = (
        len(laps) - eligible_lap_count
    )
    shared_lap_outlier_count = int(
        potential_outliers[
            "IsSharedLapCluster"
        ].sum()
    )

    _validate_result_counts(
        catalog=catalog,
        processed_lap_count=len(laps),
        eligible_lap_count=eligible_lap_count,
        excluded_lap_count=excluded_lap_count,
        stint_count=len(stints),
        pit_event_count=len(pit_events),
        duration_candidate_count=(
            len(duration_candidates)
        ),
    )

    return DevelopmentExplorationResult(
        seasons=selected_seasons,
        exploration_version=EXPLORATION_VERSION,
        lap_outlier_policy=LAP_OUTLIER_POLICY,
        session_count=len(catalog),
        processed_lap_count=len(laps),
        eligible_lap_count=eligible_lap_count,
        excluded_lap_count=excluded_lap_count,
        stint_count=len(stints),
        dry_stint_count=len(dry_stints),
        pit_event_count=len(pit_events),
        duration_analysis_candidate_count=(
            len(duration_candidates)
        ),
        potential_lap_outlier_count=(
            len(potential_outliers)
        ),
        shared_lap_outlier_count=(
            shared_lap_outlier_count
        ),
        session_summary=session_summary,
        compound_summary=compound_summary,
        stint_summary=stint_summary,
        pit_duration_summary=pit_duration_summary,
        potential_lap_outliers=(
            potential_outliers
        ),
    )


def _validate_seasons(
    seasons: Iterable[int],
) -> tuple[int, ...]:
    """Validate and normalize requested development seasons."""
    if isinstance(
        seasons,
        (
            str,
            bytes,
        ),
    ):
        raise TypeError(
            "seasons must be an iterable of integers"
        )

    try:
        requested = tuple(seasons)
    except TypeError as error:
        raise TypeError(
            "seasons must be an iterable of integers"
        ) from error

    if not requested:
        raise ValueError(
            "at least one development season is required"
        )

    normalized: list[int] = []

    for season in requested:
        if (
            not isinstance(season, int)
            or isinstance(season, bool)
        ):
            raise TypeError(
                "every season must be an integer"
            )

        if season not in DEVELOPMENT_SEASONS:
            raise ValueError(
                "exploration is restricted to development "
                f"seasons {DEVELOPMENT_SEASONS}"
            )

        if season in normalized:
            raise ValueError(
                f"duplicate season requested: {season}"
            )

        normalized.append(season)

    return tuple(sorted(normalized))


def _load_catalog(
    *,
    processed_paths: ProcessedDataPaths,
    seasons: tuple[int, ...],
) -> pd.DataFrame:
    """Load and validate the processed development catalog."""
    if not processed_paths.catalog.is_file():
        raise DevelopmentExplorationError(
            "processed catalog does not exist: "
            f"{processed_paths.catalog}"
        )

    catalog = read_parquet_table(
        processed_paths.catalog
    )

    required_columns = {
        "session_id",
        "season",
        "round_number",
        "session_type",
        "event_name",
        "laps_rows",
        "eligible_laps",
        "excluded_laps",
        "stints_rows",
        "pit_events_rows",
        "duration_analysis_candidates",
    }

    missing_columns = sorted(
        required_columns.difference(
            catalog.columns
        )
    )

    if missing_columns:
        raise DevelopmentExplorationError(
            "processed catalog lacks required columns: "
            f"{missing_columns}"
        )

    catalog_seasons = set(
        pd.to_numeric(
            catalog["season"],
            errors="raise",
        ).astype(int)
    )

    unsupported_seasons = (
        catalog_seasons.difference(
            DEVELOPMENT_SEASONS
        )
    )

    if unsupported_seasons:
        raise DevelopmentExplorationError(
            "processed catalog contains evaluation or "
            "unsupported seasons: "
            f"{sorted(unsupported_seasons)}"
        )

    selected = catalog.loc[
        catalog["season"].isin(seasons)
    ].copy()

    if selected.empty:
        raise DevelopmentExplorationError(
            "processed catalog contains no requested "
            "development sessions"
        )

    missing_seasons = set(seasons).difference(
        set(selected["season"])
    )

    if missing_seasons:
        raise DevelopmentExplorationError(
            "processed catalog lacks requested seasons: "
            f"{sorted(missing_seasons)}"
        )

    if selected["session_id"].duplicated().any():
        raise DevelopmentExplorationError(
            "processed catalog contains duplicate "
            "session IDs"
        )

    session_types = set(
        selected["session_type"]
        .astype(str)
        .str.strip()
        .str.upper()
    )

    if session_types != {"R"}:
        raise DevelopmentExplorationError(
            "development exploration supports race "
            "sessions only"
        )

    return selected.sort_values(
        [
            "season",
            "round_number",
            "session_type",
        ],
        kind="stable",
    ).reset_index(drop=True)


def _verify_session(
    *,
    processed_paths: ProcessedDataPaths,
    session_key: SessionKey,
) -> None:
    """Require one processed session to pass integrity."""
    report = verify_processed_partition(
        processed_paths,
        session_key,
    )

    if report.is_valid:
        return

    details = "; ".join(
        (
            f"{issue.code}: {issue.message}"
        )
        for issue in report.issues
    )

    raise DevelopmentExplorationError(
        "processed partition failed integrity for "
        f"{session_key.identifier}: {details}"
    )


def _load_required_table(
    *,
    path: Path,
    columns: tuple[str, ...],
    table_name: str,
) -> pd.DataFrame:
    """Load only columns required for exploration."""
    table = read_parquet_table(path)

    missing_columns = sorted(
        set(columns).difference(table.columns)
    )

    if missing_columns:
        raise DevelopmentExplorationError(
            f"{table_name} table lacks required columns: "
            f"{missing_columns}"
        )

    return table.loc[
        :,
        list(columns),
    ].copy()


def _validate_session_table_counts(
    *,
    session_key: SessionKey,
    laps: pd.DataFrame,
    expected_laps: int,
    stints: pd.DataFrame,
    expected_stints: int,
    pit_events: pd.DataFrame,
    expected_pit_events: int,
) -> None:
    """Reconcile loaded tables with their catalog row."""
    actual_counts = {
        "laps": len(laps),
        "stints": len(stints),
        "pit events": len(pit_events),
    }
    expected_counts = {
        "laps": expected_laps,
        "stints": expected_stints,
        "pit events": expected_pit_events,
    }

    for table_name, actual_count in (
        actual_counts.items()
    ):
        expected_count = expected_counts[table_name]

        if actual_count != expected_count:
            raise DevelopmentExplorationError(
                f"{session_key.identifier} "
                f"{table_name} count is "
                f"{actual_count}; expected "
                f"{expected_count}"
            )


def _validate_combined_counts(
    *,
    catalog: pd.DataFrame,
    laps: pd.DataFrame,
    stints: pd.DataFrame,
    pit_events: pd.DataFrame,
) -> None:
    """Reconcile combined tables with catalog totals."""
    expected_laps = int(
        catalog["laps_rows"].sum()
    )
    expected_stints = int(
        catalog["stints_rows"].sum()
    )
    expected_pit_events = int(
        catalog["pit_events_rows"].sum()
    )

    if len(laps) != expected_laps:
        raise DevelopmentExplorationError(
            "combined lap count differs from catalog"
        )

    if len(stints) != expected_stints:
        raise DevelopmentExplorationError(
            "combined stint count differs from catalog"
        )

    if len(pit_events) != expected_pit_events:
        raise DevelopmentExplorationError(
            "combined pit-event count differs from catalog"
        )


def _prepare_eligible_laps(
    laps: pd.DataFrame,
) -> pd.DataFrame:
    """Select and validate eligible dry analysis laps."""
    if laps["IsEligible"].isna().any():
        raise DevelopmentExplorationError(
            "processed eligibility contains missing values"
        )

    eligible_laps = laps.loc[
        laps["IsEligible"]
    ].copy()

    if eligible_laps.empty:
        raise DevelopmentExplorationError(
            "requested development data has no eligible laps"
        )

    eligible_laps["Compound"] = (
        eligible_laps["Compound"]
        .astype("string")
        .str.strip()
        .str.upper()
    )

    compounds = set(
        eligible_laps["Compound"].dropna()
    )

    unsupported_compounds = compounds.difference(
        {
            "SOFT",
            "MEDIUM",
            "HARD",
        }
    )

    if unsupported_compounds:
        raise DevelopmentExplorationError(
            "eligible laps contain unsupported compounds: "
            f"{sorted(unsupported_compounds)}"
        )

    lap_times = pd.to_numeric(
        eligible_laps["LapTimeSeconds"],
        errors="coerce",
    )

    if (
        lap_times.isna().any()
        or lap_times.le(0).any()
    ):
        raise DevelopmentExplorationError(
            "eligible laps contain invalid lap times"
        )

    eligible_laps["LapTimeSeconds"] = lap_times

    return eligible_laps


def _identify_lap_outliers(
    eligible_laps: pd.DataFrame,
) -> pd.DataFrame:
    """Flag contextual extremes without excluding them."""
    context_columns = [
        "session_id",
        "Driver",
        "Compound",
    ]

    context_group = eligible_laps.groupby(
        context_columns,
        dropna=False,
    )["LapTimeSeconds"]

    eligible_laps["ContextRows"] = (
        context_group.transform("count")
    )
    eligible_laps[
        "ContextMedianLapTimeSeconds"
    ] = context_group.transform("median")
    eligible_laps["ContextLapDeltaSeconds"] = (
        eligible_laps["LapTimeSeconds"]
        - eligible_laps[
            "ContextMedianLapTimeSeconds"
        ]
    )
    eligible_laps["_AbsoluteContextDeviation"] = (
        eligible_laps[
            "ContextLapDeltaSeconds"
        ].abs()
    )
    eligible_laps["ContextMadSeconds"] = (
        eligible_laps.groupby(
            context_columns,
            dropna=False,
        )["_AbsoluteContextDeviation"]
        .transform("median")
    )

    valid_context = (
        eligible_laps["ContextRows"].ge(
            MINIMUM_CONTEXT_ROWS
        )
        & eligible_laps[
            "ContextMadSeconds"
        ].gt(0)
        & eligible_laps[
            "ContextMadSeconds"
        ].notna()
    )

    eligible_laps["ContextRobustScore"] = (
        pd.Series(
            np.nan,
            index=eligible_laps.index,
            dtype=float,
        )
    )

    eligible_laps.loc[
        valid_context,
        "ContextRobustScore",
    ] = (
        0.67448975
        * eligible_laps.loc[
            valid_context,
            "_AbsoluteContextDeviation",
        ]
        / eligible_laps.loc[
            valid_context,
            "ContextMadSeconds",
        ]
    )

    outliers = eligible_laps.loc[
        eligible_laps[
            "ContextRobustScore"
        ].ge(ROBUST_OUTLIER_THRESHOLD)
    ].copy()

    outliers["OutlierDirection"] = np.where(
        outliers[
            "ContextLapDeltaSeconds"
        ].gt(0),
        "SLOW",
        "FAST",
    )

    outliers["SharedLapOutlierDrivers"] = (
        outliers.groupby(
            [
                "session_id",
                "LapNumber",
            ],
            dropna=False,
        )["Driver"]
        .transform("nunique")
        .astype(int)
    )
    outliers["IsSharedLapCluster"] = (
        outliers[
            "SharedLapOutlierDrivers"
        ].ge(SHARED_LAP_DRIVER_THRESHOLD)
    )

    return outliers.loc[
        :,
        list(_OUTLIER_COLUMNS),
    ].sort_values(
        [
            "ContextRobustScore",
            "session_id",
            "LapNumber",
            "Driver",
        ],
        ascending=[
            False,
            True,
            True,
            True,
        ],
        kind="stable",
    ).reset_index(drop=True)


def _build_session_summary(
    *,
    laps: pd.DataFrame,
    potential_outliers: pd.DataFrame,
) -> pd.DataFrame:
    """Summarize eligibility and outliers by session."""
    summary = (
        laps.groupby(
            [
                "session_id",
                "Season",
                "RoundNumber",
                "EventName",
            ],
            as_index=False,
        )
        .agg(
            input_laps=("IsEligible", "size"),
            eligible_laps=("IsEligible", "sum"),
        )
        .rename(
            columns={
                "Season": "season",
                "RoundNumber": "round_number",
                "EventName": "event_name",
            }
        )
    )

    summary["eligible_laps"] = (
        summary["eligible_laps"].astype(int)
    )
    summary["excluded_laps"] = (
        summary["input_laps"]
        - summary["eligible_laps"]
    )
    summary["eligibility_rate"] = (
        summary["eligible_laps"]
        / summary["input_laps"]
    )

    outlier_counts = (
        potential_outliers.groupby(
            "session_id"
        ).size().to_dict()
    )

    summary["potential_lap_outliers"] = [
        int(outlier_counts.get(session_id, 0))
        for session_id in summary["session_id"]
    ]

    return summary.loc[
        :,
        list(_SESSION_SUMMARY_COLUMNS),
    ].sort_values(
        [
            "season",
            "round_number",
        ],
        kind="stable",
    ).reset_index(drop=True)


def _build_compound_summary(
    *,
    eligible_laps: pd.DataFrame,
    potential_outliers: pd.DataFrame,
) -> pd.DataFrame:
    """Summarize eligible laps by dry tyre compound."""
    summary = (
        eligible_laps.groupby(
            "Compound",
            as_index=False,
            dropna=False,
        )
        .agg(
            eligible_laps=(
                "LapTimeSeconds",
                "size",
            ),
            median_lap_time_seconds=(
                "LapTimeSeconds",
                "median",
            ),
            median_tyre_life=(
                "TyreLife",
                "median",
            ),
            maximum_tyre_life=(
                "TyreLife",
                "max",
            ),
        )
        .rename(
            columns={
                "Compound": "compound",
            }
        )
    )

    outlier_counts = (
        potential_outliers.groupby(
            "Compound"
        ).size().to_dict()
    )

    summary["potential_lap_outliers"] = [
        int(outlier_counts.get(compound, 0))
        for compound in summary["compound"]
    ]

    return summary.loc[
        :,
        list(_COMPOUND_SUMMARY_COLUMNS),
    ].sort_values(
        [
            "eligible_laps",
            "compound",
        ],
        ascending=[
            False,
            True,
        ],
        kind="stable",
    ).reset_index(drop=True)


def _build_stint_summary(
    dry_stints: pd.DataFrame,
) -> pd.DataFrame:
    """Summarize reconstructed dry-compound stints."""
    if dry_stints.empty:
        return pd.DataFrame(
            columns=_STINT_SUMMARY_COLUMNS
        )

    summary = (
        dry_stints.groupby(
            "compound",
            as_index=False,
        )
        .agg(
            stints=("recorded_laps", "size"),
            complete_stints=(
                "is_complete",
                "sum",
            ),
            median_recorded_laps=(
                "recorded_laps",
                "median",
            ),
            mean_recorded_laps=(
                "recorded_laps",
                "mean",
            ),
            p95_recorded_laps=(
                "recorded_laps",
                lambda values: float(
                    values.quantile(0.95)
                ),
            ),
            maximum_recorded_laps=(
                "recorded_laps",
                "max",
            ),
        )
    )

    summary["complete_stints"] = (
        summary["complete_stints"].astype(int)
    )

    return summary.loc[
        :,
        list(_STINT_SUMMARY_COLUMNS),
    ].sort_values(
        [
            "stints",
            "compound",
        ],
        ascending=[
            False,
            True,
        ],
        kind="stable",
    ).reset_index(drop=True)


def _build_pit_duration_summary(
    duration_candidates: pd.DataFrame,
) -> pd.DataFrame:
    """Summarize candidate durations by circuit event."""
    if duration_candidates.empty:
        return pd.DataFrame(
            columns=_PIT_DURATION_SUMMARY_COLUMNS
        )

    durations = pd.to_numeric(
        duration_candidates[
            "observed_pit_lane_duration_seconds"
        ],
        errors="coerce",
    )

    if (
        durations.isna().any()
        or durations.le(0).any()
    ):
        raise DevelopmentExplorationError(
            "duration-analysis candidates contain "
            "invalid durations"
        )

    duration_candidates = (
        duration_candidates.copy()
    )
    duration_candidates[
        "observed_pit_lane_duration_seconds"
    ] = durations

    summary = (
        duration_candidates.groupby(
            "event_name",
            as_index=False,
        )
        .agg(
            events=(
                "observed_pit_lane_duration_seconds",
                "size",
            ),
            minimum_seconds=(
                "observed_pit_lane_duration_seconds",
                "min",
            ),
            p05_seconds=(
                "observed_pit_lane_duration_seconds",
                lambda values: float(
                    values.quantile(0.05)
                ),
            ),
            median_seconds=(
                "observed_pit_lane_duration_seconds",
                "median",
            ),
            p95_seconds=(
                "observed_pit_lane_duration_seconds",
                lambda values: float(
                    values.quantile(0.95)
                ),
            ),
            maximum_seconds=(
                "observed_pit_lane_duration_seconds",
                "max",
            ),
        )
    )

    return summary.loc[
        :,
        list(_PIT_DURATION_SUMMARY_COLUMNS),
    ].sort_values(
        [
            "median_seconds",
            "event_name",
        ],
        kind="stable",
    ).reset_index(drop=True)


def _validate_result_counts(
    *,
    catalog: pd.DataFrame,
    processed_lap_count: int,
    eligible_lap_count: int,
    excluded_lap_count: int,
    stint_count: int,
    pit_event_count: int,
    duration_candidate_count: int,
) -> None:
    """Reconcile exploration totals with the catalog."""
    expected_eligible = int(
        catalog["eligible_laps"].sum()
    )
    expected_excluded = int(
        catalog["excluded_laps"].sum()
    )
    expected_stints = int(
        catalog["stints_rows"].sum()
    )
    expected_pit_events = int(
        catalog["pit_events_rows"].sum()
    )
    expected_candidates = int(
        catalog[
            "duration_analysis_candidates"
        ].sum()
    )

    if (
        eligible_lap_count
        + excluded_lap_count
        != processed_lap_count
    ):
        raise DevelopmentExplorationError(
            "eligible and excluded exploration laps do "
            "not cover every processed lap"
        )

    actual_expected_pairs = (
        (
            "eligible lap",
            eligible_lap_count,
            expected_eligible,
        ),
        (
            "excluded lap",
            excluded_lap_count,
            expected_excluded,
        ),
        (
            "stint",
            stint_count,
            expected_stints,
        ),
        (
            "pit-event",
            pit_event_count,
            expected_pit_events,
        ),
        (
            "duration candidate",
            duration_candidate_count,
            expected_candidates,
        ),
    )

    for (
        label,
        actual_count,
        expected_count,
    ) in actual_expected_pairs:
        if actual_count != expected_count:
            raise DevelopmentExplorationError(
                f"{label} count is {actual_count}; "
                f"catalog expects {expected_count}"
            )