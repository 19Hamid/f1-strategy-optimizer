"""Run the complete Phase 5 baseline audit on verified development data."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

import pandas as pd

from app.baselines.contracts import BaselineTask
from app.baselines.evaluation import evaluate_development_folds
from app.baselines.reporting import (
    BaselineExperimentProvenance,
    build_evaluation_tables,
    runtime_dependency_versions,
)
from app.baselines.storage import (
    BaselineReportPaths,
    BaselineVerificationReport,
    verify_baseline_report,
    write_baseline_report,
)
from app.datasets.contracts import (
    DATASET_CONTRACT_VERSION,
    EXPECTED_DEVELOPMENT_TOTALS,
    PROTECTED_EVALUATION_SEASON,
)
from app.datasets.integrity import verify_complete_dataset
from app.datasets.paths import DatasetPaths
from app.pipeline import SessionKey
from app.pipeline.serialization import read_parquet_table

TYRE_AGE_BINS = (-1, 5, 15, float("inf"))
TYRE_AGE_LABELS = ("NEW_0_5", "USED_6_15", "OLD_16_PLUS")
RACE_PROGRESS_BINS = (-0.001, 1 / 3, 2 / 3, 1.001)
RACE_PROGRESS_LABELS = ("EARLY", "MIDDLE", "LATE")


class BaselineAuditError(RuntimeError):
    """Raised when the real development audit cannot proceed safely."""


@dataclass(frozen=True, slots=True)
class SelectedBaseline:
    """Strongest baseline for one task under the frozen primary metric."""

    task: BaselineTask
    baseline_id: str
    pooled_rows: int
    pooled_mean_absolute_error_seconds: float
    coverage_rate: float


@dataclass(frozen=True, slots=True)
class BaselineAuditResult:
    """Completed, verified real-data Phase 5 audit."""

    report_paths: BaselineReportPaths
    verification: BaselineVerificationReport
    selected_baselines: tuple[SelectedBaseline, ...]
    development_sessions: int
    lap_target_rows: int
    pit_target_rows: int


def run_development_baseline_audit(
    *,
    datasets_root: Path,
    artifacts_root: Path,
    run_id: str,
    dataset_build_identifier: str,
) -> BaselineAuditResult:
    """Verify 68 races, evaluate folds and publish immutable evidence."""
    dataset_paths = DatasetPaths(Path(datasets_root))
    catalog = _load_catalog(dataset_paths)
    session_keys = _session_keys(catalog)
    integrity = verify_complete_dataset(dataset_paths, session_keys)
    if not integrity.is_valid:
        detail = "; ".join(issue.message for issue in integrity.issues[:5])
        raise BaselineAuditError(f"dataset integrity failed: {detail}")

    lap_parts: list[pd.DataFrame] = []
    pit_parts: list[pd.DataFrame] = []
    for key in session_keys:
        paths = dataset_paths.for_session(key)
        decisions = read_parquet_table(paths.decision_rows)
        labels = read_parquet_table(paths.decision_labels)
        pits = read_parquet_table(paths.pit_duration_observations)
        lap_parts.append(_join_decisions_and_targets(decisions, labels))
        pit_parts.append(pits)

    lap_rows = _add_reporting_bands(pd.concat(lap_parts, ignore_index=True))
    pit_rows = pd.concat(pit_parts, ignore_index=True)
    splits = read_parquet_table(dataset_paths.splits)
    if (
        lap_rows["season"].eq(PROTECTED_EVALUATION_SEASON).any()
        or pit_rows["season"].eq(PROTECTED_EVALUATION_SEASON).any()
        or splits["season"].eq(PROTECTED_EVALUATION_SEASON).any()
    ):
        raise BaselineAuditError("protected 2025 data entered Phase 5")

    started = perf_counter()
    evaluation = evaluate_development_folds(
        lap_rows=lap_rows,
        pit_rows=pit_rows,
        splits=splits,
    )
    elapsed = perf_counter() - started
    provenance = BaselineExperimentProvenance(
        dataset_contract_version=DATASET_CONTRACT_VERSION,
        dataset_build_identifier=dataset_build_identifier,
        execution_time_seconds=elapsed,
        dependency_versions=runtime_dependency_versions(),
    )
    tables = build_evaluation_tables(
        report=evaluation,
        lap_rows=lap_rows,
        pit_rows=pit_rows,
        provenance=provenance,
    )
    report_paths = BaselineReportPaths(Path(artifacts_root), run_id)
    write_baseline_report(paths=report_paths, tables=tables)
    verification = verify_baseline_report(report_paths)
    verification.raise_for_errors()
    return BaselineAuditResult(
        report_paths=report_paths,
        verification=verification,
        selected_baselines=_select_baselines(tables.predictions, tables.summary),
        development_sessions=len(session_keys),
        lap_target_rows=int(
            (
                lap_rows["is_decision_eligible"].eq(True)
                & lap_rows["is_lap_time_target_eligible"].eq(True)
            ).sum()
        ),
        pit_target_rows=int(
            pit_rows["is_pit_duration_target_eligible"].eq(True).sum()
        ),
    )


def _load_catalog(dataset_paths: DatasetPaths) -> pd.DataFrame:
    """Load the authoritative development catalog."""
    protected = (
        dataset_paths.version_root
        / f"season={PROTECTED_EVALUATION_SEASON}"
    )
    if protected.exists():
        raise BaselineAuditError(
            f"protected evaluation directory exists: {protected}"
        )
    if not dataset_paths.catalog.is_file():
        raise BaselineAuditError(
            f"dataset catalog does not exist: {dataset_paths.catalog}"
        )
    catalog = read_parquet_table(dataset_paths.catalog)
    required = {"season", "round_number", "session_type"}
    missing = sorted(required.difference(catalog.columns))
    if missing:
        raise BaselineAuditError(
            "dataset catalog missing columns: " + ", ".join(missing)
        )
    return catalog


def _session_keys(catalog: pd.DataFrame) -> tuple[SessionKey, ...]:
    """Build the exact canonical 68-race schedule."""
    keys = tuple(
        sorted(
            (
                SessionKey(
                    season=int(row.season),
                    round_number=int(row.round_number),
                    session_type=str(row.session_type),
                )
                for row in catalog.itertuples(index=False)
            ),
            key=lambda key: (
                key.season,
                key.round_number,
                key.session_type,
            ),
        )
    )
    if len(keys) != EXPECTED_DEVELOPMENT_TOTALS.sessions:
        raise BaselineAuditError(
            "baseline audit requires exactly "
            f"{EXPECTED_DEVELOPMENT_TOTALS.sessions} sessions"
        )
    if len(set(keys)) != len(keys):
        raise BaselineAuditError("dataset catalog contains duplicate sessions")
    if any(
        key.season == PROTECTED_EVALUATION_SEASON
        for key in keys
    ):
        raise BaselineAuditError("dataset catalog contains protected 2025")
    return keys


def _join_decisions_and_targets(
    decisions: pd.DataFrame,
    labels: pd.DataFrame,
) -> pd.DataFrame:
    """Restore targets without importing diagnostic action labels."""
    target_columns = (
        "decision_id",
        "is_lap_time_target_eligible",
        "lap_time_target_seconds",
    )
    missing = sorted(set(target_columns).difference(labels.columns))
    if missing:
        raise BaselineAuditError(
            "decision labels missing target columns: " + ", ".join(missing)
        )
    if decisions["decision_id"].duplicated().any():
        raise BaselineAuditError("decision rows contain duplicate identities")
    if labels["decision_id"].duplicated().any():
        raise BaselineAuditError("decision labels contain duplicate identities")
    joined = decisions.merge(
        labels.loc[:, target_columns],
        on="decision_id",
        how="left",
        validate="one_to_one",
    )
    if joined["is_lap_time_target_eligible"].isna().any():
        raise BaselineAuditError("decision rows and labels do not reconcile")
    return joined


def _add_reporting_bands(rows: pd.DataFrame) -> pd.DataFrame:
    """Derive documented reporting-only groups without model inputs."""
    required = {"session_id", "decision_lap", "tyre_age_laps"}
    missing = sorted(required.difference(rows.columns))
    if missing:
        raise BaselineAuditError(
            "decision rows missing reporting columns: " + ", ".join(missing)
        )
    result = rows.copy()
    result["tyre_age_band"] = pd.cut(
        pd.to_numeric(result["tyre_age_laps"], errors="coerce"),
        bins=TYRE_AGE_BINS,
        labels=TYRE_AGE_LABELS,
    ).astype("string")
    maximum_lap = result.groupby("session_id")["decision_lap"].transform("max")
    progress = result["decision_lap"] / maximum_lap
    result["race_progress_band"] = pd.cut(
        progress,
        bins=RACE_PROGRESS_BINS,
        labels=RACE_PROGRESS_LABELS,
        include_lowest=True,
    ).astype("string")
    return result


def _select_baselines(
    predictions: pd.DataFrame,
    summary: pd.DataFrame,
) -> tuple[SelectedBaseline, ...]:
    """Select by pooled validation MAE, then higher coverage and stable ID."""
    selected: list[SelectedBaseline] = []
    for task in BaselineTask:
        task_predictions = predictions.loc[predictions["task"].eq(task.value)]
        task_summary = summary.loc[summary["task"].eq(task.value)]
        eligible = int(task_summary.groupby("baseline_id")["eligible_targets"].sum().max())
        candidates: list[SelectedBaseline] = []
        for baseline_id, rows in task_predictions.groupby("baseline_id", sort=True):
            pooled_mae = float(rows["absolute_error_seconds"].mean())
            coverage = len(rows) / eligible
            candidates.append(
                SelectedBaseline(
                    task=task,
                    baseline_id=str(baseline_id),
                    pooled_rows=len(rows),
                    pooled_mean_absolute_error_seconds=pooled_mae,
                    coverage_rate=coverage,
                )
            )
        if not candidates:
            raise BaselineAuditError(f"no scored baselines for {task.value}")
        selected.append(
            min(
                candidates,
                key=lambda item: (
                    item.pooled_mean_absolute_error_seconds,
                    -item.coverage_rate,
                    item.baseline_id,
                ),
            )
        )
    return tuple(selected)
