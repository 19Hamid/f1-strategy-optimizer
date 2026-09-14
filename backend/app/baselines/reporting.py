"""Build reproducible aggregate and sliced Phase 5 baseline reports."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from importlib.metadata import PackageNotFoundError, version
from typing import Any

import pandas as pd

from app.baselines.contracts import (
    BASELINE_CONTRACT_VERSION,
    BASELINE_RANDOM_SEED,
    PIT_REQUIRED_SLICE_DIMENSIONS,
    REQUIRED_SLICE_DIMENSIONS,
    BaselineTask,
)
from app.baselines.evaluation import TemporalEvaluationReport
from app.baselines.metrics import regression_metrics

SUMMARY_COLUMNS = (
    "fold_id",
    "task",
    "baseline_id",
    "eligible_targets",
    "available_predictions",
    "scored_predictions",
    "coverage_rate",
    "mean_absolute_error_seconds",
    "root_mean_squared_error_seconds",
    "median_absolute_error_seconds",
    "p90_absolute_error_seconds",
    "mean_signed_error_seconds",
)
SLICE_COLUMNS = (
    "fold_id",
    "task",
    "baseline_id",
    "dimension",
    "value",
    "rows",
    "mean_absolute_error_seconds",
    "root_mean_squared_error_seconds",
    "median_absolute_error_seconds",
    "p90_absolute_error_seconds",
    "mean_signed_error_seconds",
)


class BaselineReportingError(ValueError):
    """Raised when evaluation evidence cannot form an honest report."""


@dataclass(frozen=True, slots=True)
class BaselineExperimentProvenance:
    """Stable identifiers and runtime evidence for one report."""

    dataset_contract_version: str
    dataset_build_identifier: str
    execution_time_seconds: float
    dependency_versions: dict[str, str]
    baseline_contract_version: str = BASELINE_CONTRACT_VERSION
    random_seed: int = BASELINE_RANDOM_SEED

    def __post_init__(self) -> None:
        """Reject incomplete or invalid experiment identity."""
        if not self.dataset_contract_version.strip():
            raise BaselineReportingError(
                "dataset_contract_version must not be blank"
            )
        if not self.dataset_build_identifier.strip():
            raise BaselineReportingError(
                "dataset_build_identifier must not be blank"
            )
        if self.execution_time_seconds < 0:
            raise BaselineReportingError(
                "execution_time_seconds must be non-negative"
            )
        if not self.dependency_versions:
            raise BaselineReportingError(
                "dependency_versions must not be empty"
            )


@dataclass(frozen=True, slots=True)
class BaselineEvaluationTables:
    """Normalized tables and provenance ready for immutable storage."""

    summary: pd.DataFrame
    slices: pd.DataFrame
    predictions: pd.DataFrame
    provenance: BaselineExperimentProvenance


def runtime_dependency_versions() -> dict[str, str]:
    """Capture the small dependency set that can change numeric results."""
    dependencies: dict[str, str] = {}
    for package in ("numpy", "pandas", "pyarrow"):
        try:
            dependencies[package] = version(package)
        except PackageNotFoundError as error:
            raise BaselineReportingError(
                f"required dependency is not installed: {package}"
            ) from error
    return dependencies


def build_evaluation_tables(
    *,
    report: TemporalEvaluationReport,
    lap_rows: pd.DataFrame,
    pit_rows: pd.DataFrame,
    provenance: BaselineExperimentProvenance,
) -> BaselineEvaluationTables:
    """Normalize aggregate, slice and row-level evaluation evidence."""
    if not isinstance(report, TemporalEvaluationReport):
        raise TypeError("report must be a TemporalEvaluationReport")
    _require_frame(lap_rows, source="lap_rows")
    _require_frame(pit_rows, source="pit_rows")

    summaries: list[dict[str, Any]] = []
    slices: list[dict[str, Any]] = []
    predictions: list[pd.DataFrame] = []
    for evaluation in report.evaluations:
        metrics = evaluation.scored.metrics
        coverage = evaluation.scored.coverage
        summaries.append(
            {
                "fold_id": evaluation.fold_id,
                "task": evaluation.task.value,
                "baseline_id": evaluation.baseline_id.value,
                "eligible_targets": coverage.eligible_targets,
                "available_predictions": coverage.available_predictions,
                "scored_predictions": coverage.scored_predictions,
                "coverage_rate": coverage.coverage_rate,
                **_metric_values(metrics),
            }
        )
        source, identity, dimensions = _task_source(
            evaluation.task,
            lap_rows=lap_rows,
            pit_rows=pit_rows,
        )
        scored = evaluation.scored.rows.merge(
            source,
            left_on="row_id",
            right_on=identity,
            how="left",
            validate="one_to_one",
        )
        if scored[identity].isna().any():
            raise BaselineReportingError(
                "scored predictions cannot be joined to source rows"
            )
        evidence = evaluation.scored.rows.copy()
        evidence.insert(0, "baseline_id", evaluation.baseline_id.value)
        evidence.insert(0, "task", evaluation.task.value)
        evidence.insert(0, "fold_id", evaluation.fold_id)
        predictions.append(evidence)
        for dimension in dimensions:
            if dimension not in scored.columns:
                raise BaselineReportingError(
                    f"missing required slice dimension: {dimension}"
                )
            slices.extend(
                _slice_rows(
                    scored,
                    dimension=dimension,
                    fold_id=evaluation.fold_id,
                    task=evaluation.task,
                    baseline_id=evaluation.baseline_id.value,
                )
            )

    summary = pd.DataFrame.from_records(summaries, columns=SUMMARY_COLUMNS)
    slice_table = pd.DataFrame.from_records(slices, columns=SLICE_COLUMNS)
    prediction_table = pd.concat(predictions, ignore_index=True)
    if len(summary) != 14:
        raise BaselineReportingError("expected exactly 14 aggregate results")
    if summary.loc[:, ["fold_id", "baseline_id"]].duplicated().any():
        raise BaselineReportingError("aggregate result identities are not unique")
    return BaselineEvaluationTables(
        summary=summary,
        slices=slice_table,
        predictions=prediction_table,
        provenance=provenance,
    )


def provenance_document(
    tables: BaselineEvaluationTables,
) -> dict[str, Any]:
    """Return deterministic JSON-compatible experiment provenance."""
    document = asdict(tables.provenance)
    document["summary_rows"] = len(tables.summary)
    document["slice_rows"] = len(tables.slices)
    document["prediction_rows"] = len(tables.predictions)
    return document


def _task_source(
    task: BaselineTask,
    *,
    lap_rows: pd.DataFrame,
    pit_rows: pd.DataFrame,
) -> tuple[pd.DataFrame, str, tuple[str, ...]]:
    """Return identity and required dimensions for a task."""
    if task == BaselineTask.LAP_TIME:
        return lap_rows, "decision_id", REQUIRED_SLICE_DIMENSIONS
    source = pit_rows.copy()
    required = ("compound_before", "compound_after")
    missing = sorted(set(required).difference(source.columns))
    if missing:
        raise BaselineReportingError(
            "pit_rows missing compound transition columns: "
            + ", ".join(missing)
        )
    source["compound_transition"] = (
        source["compound_before"].astype("string")
        + "->"
        + source["compound_after"].astype("string")
    )
    return source, "pit_event_id", PIT_REQUIRED_SLICE_DIMENSIONS


def _slice_rows(
    scored: pd.DataFrame,
    *,
    dimension: str,
    fold_id: str,
    task: BaselineTask,
    baseline_id: str,
) -> list[dict[str, Any]]:
    """Calculate metrics for every observed value of one dimension."""
    rows: list[dict[str, Any]] = []
    values = scored[dimension].astype("string").fillna("<MISSING>")
    for value in sorted(values.unique()):
        group = scored.loc[values.eq(value)]
        metrics = regression_metrics(
            group["target_seconds"],
            group["prediction_seconds"],
        )
        rows.append(
            {
                "fold_id": fold_id,
                "task": task.value,
                "baseline_id": baseline_id,
                "dimension": dimension,
                "value": str(value),
                "rows": len(group),
                **_metric_values(metrics),
            }
        )
    return rows


def _metric_values(metrics: Any) -> dict[str, float]:
    """Extract the frozen metric names without duplicating formulas."""
    return {
        "mean_absolute_error_seconds": metrics.mean_absolute_error_seconds,
        "root_mean_squared_error_seconds": (
            metrics.root_mean_squared_error_seconds
        ),
        "median_absolute_error_seconds": (
            metrics.median_absolute_error_seconds
        ),
        "p90_absolute_error_seconds": metrics.p90_absolute_error_seconds,
        "mean_signed_error_seconds": metrics.mean_signed_error_seconds,
    }


def _require_frame(value: object, *, source: str) -> None:
    """Require explicit tabular report inputs."""
    if not isinstance(value, pd.DataFrame):
        raise TypeError(f"{source} must be a pandas DataFrame")
