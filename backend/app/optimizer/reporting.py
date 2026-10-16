"""Reproducible Phase 8 optimizer reporting tables."""

from __future__ import annotations

import json
import math
import platform
from dataclasses import asdict, dataclass
from importlib.metadata import PackageNotFoundError, version
from typing import Final

import numpy as np
import pandas as pd

from app.datasets.contracts import DEVELOPMENT_SEASONS
from app.ml import MODEL_CONTRACT_VERSION
from app.optimizer.contracts import (
    DECISION_EQUALITY_ABS_TOLERANCE_SECONDS,
    OPTIMIZER_CONTRACT_VERSION,
    PitDecisionRecommendation,
)
from app.optimizer.diagnostics import (
    HistoricalDecisionDiagnostics,
    HistoricalDecisionSummary,
)
from app.simulation import (
    SIMULATION_CONTRACT_VERSION,
    SIMULATION_RANDOM_SEED,
    DryCompound,
    PitLossSource,
)

OPTIMIZER_DECISION_COLUMNS: Final = (
    "decision_id",
    "season",
    "session_id",
    "event_name",
    "driver",
    "team",
    "decision_lap",
    "total_laps",
    "remaining_laps",
    "current_compound",
    "current_tyre_age_laps",
    "current_stint_laps_completed",
    "completed_pit_stops",
    "compounds_used_json",
    "target_compound",
    "random_seed",
    "observed_action",
    "nominal_pit_now_time_seconds",
    "nominal_stay_out_time_seconds",
    "nominal_pit_now_advantage_seconds",
    "nominal_recommendation",
    "sensitivity_min_advantage_seconds",
    "sensitivity_max_advantage_seconds",
    "action_time_margin_seconds",
    "uncertainty_evidence",
    "conservative_min_advantage_seconds",
    "conservative_max_advantage_seconds",
    "stable_recommendation",
    "is_stable",
    "observed_action_alignment",
)
OPTIMIZER_CASE_COLUMNS: Final = (
    "decision_id",
    "tyre_age_scenario",
    "tyre_age_delta_laps",
    "pit_loss_scenario",
    "pit_loss_seconds",
    "pit_loss_source",
    "pit_loss_evidence",
    "pit_loss_training_seasons_json",
    "adjusted_tyre_age_laps",
    "adjusted_stint_laps_completed",
    "pit_now_time_seconds",
    "stay_out_time_seconds",
    "pit_now_advantage_seconds",
    "recommendation",
    "pit_now_regret_seconds",
    "stay_out_regret_seconds",
)
OPTIMIZER_SUMMARY_COLUMNS: Final = (
    "scope",
    "value",
    "decisions",
    "stable_pit_now",
    "stable_stay_out",
    "no_clear_advantage",
    "observed_action_rows",
    "observed_pit_now",
    "observed_stay_out",
    "comparable_observed_action_rows",
    "aligned_observed_actions",
    "different_observed_actions",
    "observed_action_alignment_rate",
    "mean_nominal_advantage_seconds",
    "median_nominal_advantage_seconds",
    "mean_conservative_interval_width_seconds",
)
_REQUIRED_DEPENDENCIES: Final = frozenset({"numpy", "pandas", "pyarrow", "python"})


class OptimizerReportingError(ValueError):
    """Raised when optimizer evidence cannot form an honest report."""


@dataclass(frozen=True, slots=True)
class OptimizerReportProvenance:
    """Data, model, runtime and holdout identity for one Phase 8 report."""

    optimizer_contract_version: str
    simulation_contract_version: str
    model_contract_version: str
    model_artifact_id: str
    dataset_contract_version: str
    dataset_build_identifier: str
    development_sessions: int
    protected_evaluation_rows: int
    random_seed: int
    dependency_versions: tuple[tuple[str, str], ...]
    execution_duration_seconds: float

    def __post_init__(self) -> None:
        """Reject incomplete, protected or non-canonical provenance."""
        expected_versions = (
            (
                "optimizer_contract_version",
                self.optimizer_contract_version,
                OPTIMIZER_CONTRACT_VERSION,
            ),
            (
                "simulation_contract_version",
                self.simulation_contract_version,
                SIMULATION_CONTRACT_VERSION,
            ),
            (
                "model_contract_version",
                self.model_contract_version,
                MODEL_CONTRACT_VERSION,
            ),
        )
        for name, actual, expected in expected_versions:
            if actual != expected:
                raise OptimizerReportingError(f"unexpected {name}")
        for name in (
            "model_artifact_id",
            "dataset_contract_version",
            "dataset_build_identifier",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise OptimizerReportingError(f"{name} must not be blank")
        if (
            isinstance(self.development_sessions, bool)
            or not isinstance(self.development_sessions, int)
            or self.development_sessions < 1
        ):
            raise OptimizerReportingError(
                "development_sessions must be a positive integer"
            )
        if self.protected_evaluation_rows != 0:
            raise OptimizerReportingError("protected evaluation rows entered Phase 8")
        if self.random_seed != SIMULATION_RANDOM_SEED:
            raise OptimizerReportingError(
                "random seed differs from the simulation contract"
            )
        if tuple(sorted(self.dependency_versions)) != self.dependency_versions:
            raise OptimizerReportingError("dependency versions must be canonical")
        names = {name for name, _ in self.dependency_versions}
        if names != _REQUIRED_DEPENDENCIES:
            raise OptimizerReportingError("dependency version evidence is incomplete")
        if any(not name or not value for name, value in self.dependency_versions):
            raise OptimizerReportingError("dependency versions must not be blank")
        duration = self.execution_duration_seconds
        if (
            isinstance(duration, bool)
            or not isinstance(duration, (int, float))
            or not math.isfinite(duration)
            or duration < 0
        ):
            raise OptimizerReportingError(
                "execution_duration_seconds must be finite and non-negative"
            )


@dataclass(frozen=True, slots=True)
class OptimizerReportTables:
    """Normalized Phase 8 evidence ready for immutable storage."""

    decisions: pd.DataFrame
    cases: pd.DataFrame
    summaries: pd.DataFrame
    provenance: OptimizerReportProvenance

    def __post_init__(self) -> None:
        """Require explicit table and provenance objects."""
        for name in ("decisions", "cases", "summaries"):
            if not isinstance(getattr(self, name), pd.DataFrame):
                raise TypeError(f"{name} must be a pandas DataFrame")
        if not isinstance(self.provenance, OptimizerReportProvenance):
            raise TypeError("provenance must be an OptimizerReportProvenance")


def runtime_optimizer_dependency_versions() -> tuple[tuple[str, str], ...]:
    """Capture dependencies capable of changing stored numeric evidence."""
    dependencies = {"python": platform.python_version()}
    for package in ("numpy", "pandas", "pyarrow"):
        try:
            dependencies[package] = version(package)
        except PackageNotFoundError as error:
            raise OptimizerReportingError(
                f"required dependency is not installed: {package}"
            ) from error
    return tuple(sorted(dependencies.items()))


def build_optimizer_report(
    *,
    diagnostics: HistoricalDecisionDiagnostics,
    provenance: OptimizerReportProvenance,
) -> OptimizerReportTables:
    """Normalize decision, sensitivity-case and aggregate evidence."""
    if not isinstance(diagnostics, HistoricalDecisionDiagnostics):
        raise TypeError("diagnostics must be a HistoricalDecisionDiagnostics")
    if not isinstance(provenance, OptimizerReportProvenance):
        raise TypeError("provenance must be an OptimizerReportProvenance")
    decision_records: list[dict[str, object]] = []
    case_records: list[dict[str, object]] = []
    for diagnostic in sorted(
        diagnostics.decisions,
        key=lambda item: item.decision_key,
    ):
        request = diagnostic.request
        state = request.state
        stability = diagnostic.stability
        nominal = stability.sensitivity.nominal
        sensitivity_min, sensitivity_max = (
            stability.sensitivity.pit_now_advantage_range_seconds
        )
        conservative_min, conservative_max = (
            stability.conservative_advantage_interval_seconds
        )
        decision_id = _decision_id(diagnostic.decision_key)
        decision_records.append(
            {
                "decision_id": decision_id,
                "season": state.season,
                "session_id": state.session_id,
                "event_name": state.event_name,
                "driver": state.driver,
                "team": state.team,
                "decision_lap": state.current_lap,
                "total_laps": state.total_laps,
                "remaining_laps": request.remaining_laps,
                "current_compound": state.current_compound.value,
                "current_tyre_age_laps": state.tyre_age_laps,
                "current_stint_laps_completed": (state.current_stint_laps_completed),
                "completed_pit_stops": state.completed_pit_stops,
                "compounds_used_json": _json(
                    [compound.value for compound in state.compounds_used]
                ),
                "target_compound": request.target_compound.value,
                "random_seed": request.random_seed,
                "observed_action": (
                    None
                    if diagnostic.observed_action is None
                    else diagnostic.observed_action.value
                ),
                "nominal_pit_now_time_seconds": (
                    nominal.pit_now.expected_remaining_time_seconds
                ),
                "nominal_stay_out_time_seconds": (
                    nominal.stay_out.expected_remaining_time_seconds
                ),
                "nominal_pit_now_advantage_seconds": (
                    nominal.pit_now_advantage_seconds
                ),
                "nominal_recommendation": nominal.recommendation.value,
                "sensitivity_min_advantage_seconds": sensitivity_min,
                "sensitivity_max_advantage_seconds": sensitivity_max,
                "action_time_margin_seconds": (
                    stability.uncertainty.action_time_margin_seconds
                ),
                "uncertainty_evidence": stability.uncertainty.evidence,
                "conservative_min_advantage_seconds": conservative_min,
                "conservative_max_advantage_seconds": conservative_max,
                "stable_recommendation": stability.recommendation.value,
                "is_stable": stability.is_stable,
                "observed_action_alignment": (diagnostic.observed_action_alignment),
            }
        )
        for case in stability.sensitivity.cases:
            comparison = case.comparison
            resolution = case.pit_loss_resolution
            case_records.append(
                {
                    "decision_id": decision_id,
                    "tyre_age_scenario": case.tyre_age_scenario.value,
                    "tyre_age_delta_laps": case.tyre_age_delta_laps,
                    "pit_loss_scenario": resolution.scenario.value,
                    "pit_loss_seconds": resolution.assumption.seconds,
                    "pit_loss_source": resolution.assumption.source.value,
                    "pit_loss_evidence": resolution.assumption.evidence,
                    "pit_loss_training_seasons_json": _json(
                        resolution.training_seasons
                    ),
                    "adjusted_tyre_age_laps": (comparison.request.state.tyre_age_laps),
                    "adjusted_stint_laps_completed": (
                        comparison.request.state.current_stint_laps_completed
                    ),
                    "pit_now_time_seconds": (
                        comparison.pit_now.expected_remaining_time_seconds
                    ),
                    "stay_out_time_seconds": (
                        comparison.stay_out.expected_remaining_time_seconds
                    ),
                    "pit_now_advantage_seconds": (comparison.pit_now_advantage_seconds),
                    "recommendation": comparison.recommendation.value,
                    "pit_now_regret_seconds": comparison.regret_seconds("PIT_NOW"),
                    "stay_out_regret_seconds": comparison.regret_seconds("STAY_OUT"),
                }
            )
    decisions = pd.DataFrame.from_records(
        decision_records,
        columns=OPTIMIZER_DECISION_COLUMNS,
    )
    cases = pd.DataFrame.from_records(
        case_records,
        columns=OPTIMIZER_CASE_COLUMNS,
    )
    summaries = pd.DataFrame.from_records(
        [
            _summary_record(diagnostics.overall),
            *(_summary_record(summary) for summary in diagnostics.by_event),
        ],
        columns=OPTIMIZER_SUMMARY_COLUMNS,
    )
    tables = OptimizerReportTables(
        decisions=decisions,
        cases=cases,
        summaries=summaries,
        provenance=provenance,
    )
    validate_optimizer_report_tables(tables)
    return tables


def validate_optimizer_report_tables(tables: OptimizerReportTables) -> None:
    """Require exact schemas, identities and arithmetic reconciliation."""
    if not isinstance(tables, OptimizerReportTables):
        raise TypeError("tables must be an OptimizerReportTables")
    expected_columns = {
        "decisions": OPTIMIZER_DECISION_COLUMNS,
        "cases": OPTIMIZER_CASE_COLUMNS,
        "summaries": OPTIMIZER_SUMMARY_COLUMNS,
    }
    for name, columns in expected_columns.items():
        frame = getattr(tables, name)
        if tuple(frame.columns) != columns:
            raise OptimizerReportingError(
                f"{name} columns differ from the report contract"
            )
        if frame.empty:
            raise OptimizerReportingError(f"{name} must not be empty")

    decisions = tables.decisions
    cases = tables.cases
    if decisions["decision_id"].duplicated().any():
        raise OptimizerReportingError("decision identities must be unique")
    if decisions["decision_id"].astype(str).str.strip().eq("").any():
        raise OptimizerReportingError("decision identities must not be blank")
    case_identity = [
        "decision_id",
        "tyre_age_scenario",
        "pit_loss_scenario",
    ]
    if cases.loc[:, case_identity].duplicated().any():
        raise OptimizerReportingError("sensitivity case identities must be unique")
    seasons = set(pd.to_numeric(decisions["season"]).astype(int))
    if not seasons.issubset(DEVELOPMENT_SEASONS):
        raise OptimizerReportingError(
            "optimizer report contains rows outside development seasons"
        )
    session_count = len(decisions.loc[:, ["season", "session_id"]].drop_duplicates())
    if session_count != tables.provenance.development_sessions:
        raise OptimizerReportingError(
            "development session count differs from provenance"
        )
    if not decisions["random_seed"].eq(tables.provenance.random_seed).all():
        raise OptimizerReportingError("stored random seeds differ from provenance")
    expected_remaining_laps = (
        pd.to_numeric(decisions["total_laps"])
        - pd.to_numeric(decisions["decision_lap"])
        + 1
    )
    if not pd.to_numeric(decisions["remaining_laps"]).eq(expected_remaining_laps).all():
        raise OptimizerReportingError(
            "stored remaining laps differ from decision boundaries"
        )
    _require_finite_non_negative(
        decisions,
        (
            "decision_lap",
            "total_laps",
            "remaining_laps",
            "current_tyre_age_laps",
            "current_stint_laps_completed",
            "completed_pit_stops",
            "action_time_margin_seconds",
            "nominal_pit_now_time_seconds",
            "nominal_stay_out_time_seconds",
        ),
    )
    _require_finite(
        decisions,
        (
            "nominal_pit_now_advantage_seconds",
            "sensitivity_min_advantage_seconds",
            "sensitivity_max_advantage_seconds",
            "conservative_min_advantage_seconds",
            "conservative_max_advantage_seconds",
        ),
    )
    if decisions["uncertainty_evidence"].astype(str).str.strip().eq("").any():
        raise OptimizerReportingError("stored uncertainty evidence must not be blank")
    if not decisions["is_stable"].isin((True, False)).all():
        raise OptimizerReportingError("stored stability markers must be boolean")
    allowed_compounds = {compound.value for compound in DryCompound}
    if not set(decisions["current_compound"]).issubset(
        allowed_compounds
    ) or not set(decisions["target_compound"]).issubset(allowed_compounds):
        raise OptimizerReportingError("stored decision compound is unsupported")
    allowed_observed_actions = {None, "PIT_NOW", "STAY_OUT"}
    normalized_observed_actions = {
        None if pd.isna(value) else value
        for value in decisions["observed_action"]
    }
    if not normalized_observed_actions.issubset(allowed_observed_actions):
        raise OptimizerReportingError("stored observed action is unsupported")
    _require_finite_non_negative(
        cases,
        (
            "pit_loss_seconds",
            "adjusted_tyre_age_laps",
            "adjusted_stint_laps_completed",
            "pit_now_time_seconds",
            "stay_out_time_seconds",
            "pit_now_regret_seconds",
            "stay_out_regret_seconds",
        ),
    )
    _require_finite(cases, ("pit_now_advantage_seconds",))
    if (
        cases["pit_loss_evidence"].astype(str).str.strip().eq("").any()
        or cases["pit_loss_source"].astype(str).str.strip().eq("").any()
    ):
        raise OptimizerReportingError("stored pit-loss provenance must not be blank")
    allowed_pit_loss_sources = {source.value for source in PitLossSource}
    if not set(cases["pit_loss_source"]).issubset(allowed_pit_loss_sources):
        raise OptimizerReportingError("stored pit-loss source is unsupported")
    if set(cases["decision_id"]) != set(decisions["decision_id"]):
        raise OptimizerReportingError("decision and sensitivity case identities differ")

    expected_case_pairs = {
        (tyre_age, pit_loss)
        for tyre_age in ("YOUNGER", "NOMINAL", "OLDER")
        for pit_loss in ("LOW", "NOMINAL", "HIGH")
    }
    for decision in decisions.itertuples(index=False):
        expected_decision_id = _decision_id(
            (
                int(decision.season),
                str(decision.session_id),
                str(decision.driver),
                int(decision.decision_lap),
                str(decision.target_compound),
            )
        )
        if decision.decision_id != expected_decision_id:
            raise OptimizerReportingError(
                "stored decision identity differs from its fields"
            )
        compounds_used = _json_list(
            decision.compounds_used_json,
            "compounds_used_json",
        )
        if (
            not compounds_used
            or any(not isinstance(value, str) for value in compounds_used)
            or not set(compounds_used).issubset(allowed_compounds)
        ):
            raise OptimizerReportingError(
                "stored compounds-used evidence is unsupported"
            )
        selected = cases.loc[cases["decision_id"].eq(decision.decision_id)]
        actual_pairs = set(
            zip(
                selected["tyre_age_scenario"],
                selected["pit_loss_scenario"],
                strict=True,
            )
        )
        if actual_pairs != expected_case_pairs:
            raise OptimizerReportingError(
                "stored decision does not contain the canonical nine cases"
            )
        for case in selected.itertuples(index=False):
            training_seasons = _json_list(
                case.pit_loss_training_seasons_json,
                "pit_loss_training_seasons_json",
            )
            if (
                any(
                    isinstance(value, bool) or not isinstance(value, int)
                    for value in training_seasons
                )
                or training_seasons != sorted(set(training_seasons))
                or not set(training_seasons).issubset(DEVELOPMENT_SEASONS)
            ):
                raise OptimizerReportingError(
                    "stored pit-loss training seasons are invalid"
                )
            is_training_source = (
                case.pit_loss_source
                == PitLossSource.TRAINING_ONLY_CIRCUIT_ESTIMATE.value
            )
            if bool(training_seasons) != is_training_source:
                raise OptimizerReportingError(
                    "stored pit-loss source and training seasons differ"
                )
        expected_deltas = {"YOUNGER": -2, "NOMINAL": 0, "OLDER": 2}
        actual_deltas = selected["tyre_age_scenario"].map(expected_deltas)
        if not pd.to_numeric(selected["tyre_age_delta_laps"]).eq(actual_deltas).all():
            raise OptimizerReportingError(
                "stored tyre-age deltas differ from their scenarios"
            )
        expected_tyre_ages = float(decision.current_tyre_age_laps) + actual_deltas
        expected_stint_ages = (
            float(decision.current_stint_laps_completed) + actual_deltas
        )
        if (
            not pd.to_numeric(selected["adjusted_tyre_age_laps"])
            .eq(expected_tyre_ages)
            .all()
            or not pd.to_numeric(selected["adjusted_stint_laps_completed"])
            .eq(expected_stint_ages)
            .all()
        ):
            raise OptimizerReportingError(
                "stored adjusted tyre exposure differs from the base decision"
            )
        _close_series(
            selected["stay_out_time_seconds"] - selected["pit_now_time_seconds"],
            selected["pit_now_advantage_seconds"],
            "stored case advantages",
        )
        expected_pit_regret = np.maximum(
            -selected["pit_now_advantage_seconds"].to_numpy(dtype="float64"),
            0.0,
        )
        expected_stay_regret = np.maximum(
            selected["pit_now_advantage_seconds"].to_numpy(dtype="float64"),
            0.0,
        )
        _close_series(
            pd.Series(expected_pit_regret, index=selected.index),
            selected["pit_now_regret_seconds"],
            "stored PIT_NOW regret",
        )
        _close_series(
            pd.Series(expected_stay_regret, index=selected.index),
            selected["stay_out_regret_seconds"],
            "stored STAY_OUT regret",
        )
        expected_case_recommendations = selected["pit_now_advantage_seconds"].map(
            _point_recommendation
        )
        if not selected["recommendation"].eq(expected_case_recommendations).all():
            raise OptimizerReportingError(
                "stored case recommendation differs from its advantage"
            )
        nominal = selected.loc[
            selected["tyre_age_scenario"].eq("NOMINAL")
            & selected["pit_loss_scenario"].eq("NOMINAL")
        ].iloc[0]
        _close(
            nominal["pit_now_time_seconds"],
            decision.nominal_pit_now_time_seconds,
            "stored nominal PIT_NOW time",
        )
        _close(
            nominal["stay_out_time_seconds"],
            decision.nominal_stay_out_time_seconds,
            "stored nominal STAY_OUT time",
        )
        _close(
            nominal["pit_now_advantage_seconds"],
            decision.nominal_pit_now_advantage_seconds,
            "stored nominal advantage",
        )
        if nominal["recommendation"] != decision.nominal_recommendation:
            raise OptimizerReportingError(
                "stored nominal recommendation differs from nominal case"
            )
        minimum = float(selected["pit_now_advantage_seconds"].min())
        maximum = float(selected["pit_now_advantage_seconds"].max())
        _close(
            minimum,
            decision.sensitivity_min_advantage_seconds,
            "stored sensitivity minimum",
        )
        _close(
            maximum,
            decision.sensitivity_max_advantage_seconds,
            "stored sensitivity maximum",
        )
        margin = 2.0 * float(decision.action_time_margin_seconds)
        _close(
            minimum - margin,
            decision.conservative_min_advantage_seconds,
            "stored conservative minimum",
        )
        _close(
            maximum + margin,
            decision.conservative_max_advantage_seconds,
            "stored conservative maximum",
        )
        expected_recommendation = _stable_recommendation(
            float(decision.conservative_min_advantage_seconds),
            float(decision.conservative_max_advantage_seconds),
        )
        if decision.stable_recommendation != expected_recommendation:
            raise OptimizerReportingError(
                "stored stable recommendation differs from its interval"
            )
        if bool(decision.is_stable) != (
            expected_recommendation
            != PitDecisionRecommendation.NO_CLEAR_ADVANTAGE.value
        ):
            raise OptimizerReportingError(
                "stored stability marker differs from its recommendation"
            )
        observed_action = decision.observed_action
        if pd.isna(observed_action) or not bool(decision.is_stable):
            expected_alignment: bool | None = None
        else:
            expected_alignment = observed_action == expected_recommendation
        actual_alignment = decision.observed_action_alignment
        if pd.isna(actual_alignment):
            actual_alignment = None
        else:
            actual_alignment = bool(actual_alignment)
        if actual_alignment != expected_alignment:
            raise OptimizerReportingError(
                "stored observed-action alignment differs from its evidence"
            )

    expected_summaries = _summary_table_from_decisions(decisions)
    _compare_summary_tables(tables.summaries, expected_summaries)


def optimizer_provenance_document(
    tables: OptimizerReportTables,
) -> dict[str, object]:
    """Return deterministic JSON-compatible report provenance."""
    validate_optimizer_report_tables(tables)
    document = asdict(tables.provenance)
    document["decision_rows"] = len(tables.decisions)
    document["case_rows"] = len(tables.cases)
    document["summary_rows"] = len(tables.summaries)
    return document


def _summary_record(summary: HistoricalDecisionSummary) -> dict[str, object]:
    return {
        "scope": summary.scope.value,
        "value": summary.value,
        "decisions": summary.decisions,
        "stable_pit_now": summary.stable_pit_now,
        "stable_stay_out": summary.stable_stay_out,
        "no_clear_advantage": summary.no_clear_advantage,
        "observed_action_rows": summary.observed_action_rows,
        "observed_pit_now": summary.observed_pit_now,
        "observed_stay_out": summary.observed_stay_out,
        "comparable_observed_action_rows": (summary.comparable_observed_action_rows),
        "aligned_observed_actions": summary.aligned_observed_actions,
        "different_observed_actions": summary.different_observed_actions,
        "observed_action_alignment_rate": (summary.observed_action_alignment_rate),
        "mean_nominal_advantage_seconds": (summary.mean_nominal_advantage_seconds),
        "median_nominal_advantage_seconds": (summary.median_nominal_advantage_seconds),
        "mean_conservative_interval_width_seconds": (
            summary.mean_conservative_interval_width_seconds
        ),
    }


def _summary_table_from_decisions(decisions: pd.DataFrame) -> pd.DataFrame:
    records = [_summary_record_from_frame(decisions, scope="OVERALL", value="ALL")]
    for event_name in sorted(decisions["event_name"].astype(str).unique()):
        records.append(
            _summary_record_from_frame(
                decisions.loc[decisions["event_name"].eq(event_name)],
                scope="EVENT",
                value=event_name,
            )
        )
    return pd.DataFrame.from_records(records, columns=OPTIMIZER_SUMMARY_COLUMNS)


def _summary_record_from_frame(
    selected: pd.DataFrame,
    *,
    scope: str,
    value: str,
) -> dict[str, object]:
    recommendations = selected["stable_recommendation"]
    observed = selected["observed_action"].dropna()
    alignments = selected["observed_action_alignment"].dropna().astype(bool)
    interval_width = (
        selected["conservative_max_advantage_seconds"]
        - selected["conservative_min_advantage_seconds"]
    )
    return {
        "scope": scope,
        "value": value,
        "decisions": len(selected),
        "stable_pit_now": int(recommendations.eq("PIT_NOW").sum()),
        "stable_stay_out": int(recommendations.eq("STAY_OUT").sum()),
        "no_clear_advantage": int(recommendations.eq("NO_CLEAR_ADVANTAGE").sum()),
        "observed_action_rows": len(observed),
        "observed_pit_now": int(observed.eq("PIT_NOW").sum()),
        "observed_stay_out": int(observed.eq("STAY_OUT").sum()),
        "comparable_observed_action_rows": len(alignments),
        "aligned_observed_actions": int(alignments.sum()),
        "different_observed_actions": int((~alignments).sum()),
        "observed_action_alignment_rate": (
            None if alignments.empty else float(alignments.mean())
        ),
        "mean_nominal_advantage_seconds": float(
            selected["nominal_pit_now_advantage_seconds"].mean()
        ),
        "median_nominal_advantage_seconds": float(
            selected["nominal_pit_now_advantage_seconds"].median()
        ),
        "mean_conservative_interval_width_seconds": float(interval_width.mean()),
    }


def _compare_summary_tables(actual: pd.DataFrame, expected: pd.DataFrame) -> None:
    identity = list(OPTIMIZER_SUMMARY_COLUMNS[:12])
    if not actual.loc[:, identity].equals(expected.loc[:, identity]):
        raise OptimizerReportingError(
            "stored summary populations differ from decision evidence"
        )
    numeric = list(OPTIMIZER_SUMMARY_COLUMNS[12:])
    if not np.allclose(
        actual.loc[:, numeric].to_numpy(dtype="float64"),
        expected.loc[:, numeric].to_numpy(dtype="float64"),
        rtol=0.0,
        atol=1e-12,
        equal_nan=True,
    ):
        raise OptimizerReportingError("stored summaries differ from decision evidence")


def _stable_recommendation(lower: float, upper: float) -> str:
    tolerance = DECISION_EQUALITY_ABS_TOLERANCE_SECONDS
    if lower > tolerance:
        return PitDecisionRecommendation.PIT_NOW.value
    if upper < -tolerance:
        return PitDecisionRecommendation.STAY_OUT.value
    return PitDecisionRecommendation.NO_CLEAR_ADVANTAGE.value


def _point_recommendation(advantage: object) -> str:
    value = float(advantage)
    tolerance = DECISION_EQUALITY_ABS_TOLERANCE_SECONDS
    if value > tolerance:
        return PitDecisionRecommendation.PIT_NOW.value
    if value < -tolerance:
        return PitDecisionRecommendation.STAY_OUT.value
    return PitDecisionRecommendation.NO_CLEAR_ADVANTAGE.value


def _decision_id(key: tuple[int, str, str, int, str]) -> str:
    return ":".join(str(value) for value in key)


def _json(value: object) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _json_list(value: object, field_name: str) -> list[object]:
    if not isinstance(value, str):
        raise OptimizerReportingError(f"{field_name} must be JSON text")
    try:
        document = json.loads(value)
    except json.JSONDecodeError as error:
        raise OptimizerReportingError(
            f"{field_name} must contain valid JSON"
        ) from error
    if not isinstance(document, list):
        raise OptimizerReportingError(f"{field_name} must contain a JSON array")
    return document


def _close_series(
    actual: pd.Series,
    expected: pd.Series,
    field_name: str,
) -> None:
    if not np.allclose(
        actual.to_numpy(dtype="float64"),
        expected.to_numpy(dtype="float64"),
        rtol=0.0,
        atol=1e-9,
    ):
        raise OptimizerReportingError(f"{field_name} do not reconcile")


def _close(actual: object, expected: object, field_name: str) -> None:
    if not math.isclose(
        float(actual),
        float(expected),
        rel_tol=0.0,
        abs_tol=1e-9,
    ):
        raise OptimizerReportingError(f"{field_name} does not reconcile")


def _require_finite(frame: pd.DataFrame, columns: tuple[str, ...]) -> None:
    values = frame.loc[:, columns].apply(pd.to_numeric, errors="coerce")
    if not np.isfinite(values.to_numpy(dtype="float64")).all():
        raise OptimizerReportingError("stored numeric evidence must be finite")


def _require_finite_non_negative(
    frame: pd.DataFrame,
    columns: tuple[str, ...],
) -> None:
    _require_finite(frame, columns)
    if frame.loc[:, columns].apply(pd.to_numeric).lt(0).any().any():
        raise OptimizerReportingError("stored non-negative numeric evidence is invalid")
