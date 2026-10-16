"""Run the complete Phase 8 audit on verified development races."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from time import perf_counter
from typing import Final

import numpy as np
import pandas as pd

from app.cleaning.integrity import verify_processed_partition
from app.cleaning.paths import ProcessedDataPaths
from app.datasets.contracts import (
    DATASET_CONTRACT_VERSION,
    DEVELOPMENT_SEASONS,
    EXPECTED_DEVELOPMENT_TOTALS,
    PROTECTED_EVALUATION_SEASON,
)
from app.datasets.integrity import verify_complete_dataset
from app.datasets.paths import DatasetPaths
from app.ml import (
    APPROVED_FEATURE_COLUMNS,
    MODEL_CONTRACT_VERSION,
    ModelArtifactPaths,
)
from app.optimizer.contracts import (
    OPTIMIZER_CONTRACT_VERSION,
    OptimizerContractError,
    PitDecisionAction,
    PitDecisionRequest,
)
from app.optimizer.diagnostics import (
    HistoricalDecisionDiagnostic,
    HistoricalDecisionDiagnostics,
    build_historical_decision_diagnostics,
)
from app.optimizer.reporting import (
    OptimizerReportProvenance,
    build_optimizer_report,
    runtime_optimizer_dependency_versions,
)
from app.optimizer.sensitivity import analyze_pit_decision_sensitivity
from app.optimizer.stability import (
    DecisionUncertaintyAssumption,
    assess_recommendation_stability,
)
from app.optimizer.storage import (
    OptimizerReportPaths,
    OptimizerReportVerification,
    verify_optimizer_report,
    write_optimizer_report,
)
from app.pipeline import SessionKey
from app.pipeline.serialization import (
    read_json_document,
    read_parquet_table,
    sha256_file,
)
from app.simulation import (
    AUDIT_PIT_LOSS_SECONDS,
    SIMULATION_CONTRACT_VERSION,
    SIMULATION_RANDOM_SEED,
    CircuitPitLossProfile,
    DryCompound,
    Phase6ModelAdapter,
    PitLossRegistry,
    PitLossScenario,
    PitLossSource,
    RaceState,
    SimulationContractError,
    SimulationFeatureContext,
    SimulationMode,
    SimulationReportPaths,
    build_observed_replay_context,
    verify_simulation_report,
)

ProgressCallback = Callable[[str], None]

_PIT_LOSS_EVIDENCE: Final = (
    "controlled Phase 8 final-audit sensitivity assumption inherited from "
    "the Phase 7 audit; not an observed net pit-loss label"
)


class OptimizerAuditError(RuntimeError):
    """Raised when the real Phase 8 development audit cannot pass safely."""


@dataclass(frozen=True, slots=True)
class OptimizerAuditCandidate:
    """One historical pit-window decision ready for controlled comparison."""

    request: PitDecisionRequest
    context: SimulationFeatureContext
    observed_action: PitDecisionAction
    observed_pit_lap: int

    def __post_init__(self) -> None:
        """Bind the immediate action to the exact observed pit window."""
        if not isinstance(self.request, PitDecisionRequest):
            raise TypeError("request must be a PitDecisionRequest")
        if not isinstance(self.context, SimulationFeatureContext):
            raise TypeError("context must be a SimulationFeatureContext")
        try:
            action = PitDecisionAction(self.observed_action)
        except (TypeError, ValueError) as error:
            raise OptimizerAuditError(
                f"unsupported observed action: {self.observed_action!r}"
            ) from error
        if (
            isinstance(self.observed_pit_lap, bool)
            or not isinstance(self.observed_pit_lap, int)
        ):
            raise OptimizerAuditError("observed_pit_lap must be an integer")
        expected_pit_lap = self.request.state.current_lap + (
            0 if action is PitDecisionAction.PIT_NOW else 1
        )
        if self.observed_pit_lap != expected_pit_lap:
            raise OptimizerAuditError(
                "observed action does not match the declared pit window"
            )
        object.__setattr__(self, "observed_action", action)

    @property
    def decision_key(self) -> tuple[int, str, str, int, str]:
        """Return the report identity generated from this candidate."""
        state = self.request.state
        return (
            state.season,
            state.session_id,
            state.driver,
            state.current_lap,
            self.request.target_compound.value,
        )


@dataclass(frozen=True, slots=True)
class OptimizerAuditResult:
    """Verified decision population and its immutable report evidence."""

    report_paths: OptimizerReportPaths
    report_verification: OptimizerReportVerification
    diagnostics: HistoricalDecisionDiagnostics
    audited_development_sessions: int
    decision_development_sessions: int
    candidate_pair_slots: int
    selected_decision_pairs: int
    excluded_pair_slots: int
    selected_decisions: int
    observed_pit_now: int
    observed_stay_out: int
    protected_evaluation_rows: int
    deterministic_decision_passes: int
    action_time_margin_seconds: float


def run_development_optimizer_audit(
    *,
    datasets_root: Path,
    processed_root: Path,
    artifacts_root: Path,
    run_id: str,
    model_artifact_id: str,
    simulation_run_id: str,
    progress: ProgressCallback | None = None,
) -> OptimizerAuditResult:
    """Verify 68 races, compare paired pit decisions and publish evidence."""
    dataset_paths = DatasetPaths(Path(datasets_root))
    processed_paths = ProcessedDataPaths(Path(processed_root))
    report_paths = OptimizerReportPaths(Path(artifacts_root), run_id)
    if report_paths.root.exists():
        raise OptimizerAuditError(
            f"optimizer report already exists: {report_paths.root}"
        )

    _announce(progress, "Verifying the 68-race dataset catalog and partitions")
    dataset_catalog = _load_catalog(
        dataset_paths.catalog,
        protected_root=(
            dataset_paths.version_root
            / f"season={PROTECTED_EVALUATION_SEASON}"
        ),
        source="dataset",
    )
    session_keys = _session_keys(dataset_catalog)
    dataset_integrity = verify_complete_dataset(dataset_paths, session_keys)
    if not dataset_integrity.is_valid:
        detail = "; ".join(issue.message for issue in dataset_integrity.issues[:5])
        raise OptimizerAuditError(f"dataset integrity failed: {detail}")

    _announce(progress, "Verifying the matching processed-race catalog")
    processed_catalog = _load_catalog(
        processed_paths.catalog,
        protected_root=(
            processed_paths.version_root
            / f"season={PROTECTED_EVALUATION_SEASON}"
        ),
        source="processed",
    )
    _reconcile_catalogs(dataset_catalog, processed_catalog)
    protected_rows = _protected_row_count(
        (dataset_catalog, "season"),
        (processed_catalog, "season"),
    )
    if protected_rows:
        raise OptimizerAuditError("protected 2025 rows entered Phase 8")

    dataset_build_identifier = sha256_file(dataset_paths.catalog)
    model_paths = ModelArtifactPaths(Path(artifacts_root), model_artifact_id)
    _announce(progress, "Loading the verified final Phase 6 model artifact")
    adapter = Phase6ModelAdapter.from_paths(model_paths)
    model_provenance = adapter.artifact.provenance
    if model_provenance.dataset_contract_version != DATASET_CONTRACT_VERSION:
        raise OptimizerAuditError(
            "model and optimizer dataset contract versions differ"
        )
    if model_provenance.dataset_build_identifier != dataset_build_identifier:
        raise OptimizerAuditError(
            "model artifact was not fitted from the verified dataset catalog"
        )

    _announce(progress, "Loading verified Phase 7 uncertainty evidence")
    uncertainty = _simulation_uncertainty(
        artifacts_root=Path(artifacts_root),
        simulation_run_id=simulation_run_id,
        model_artifact_id=model_artifact_id,
        dataset_build_identifier=dataset_build_identifier,
    )
    registry = _pit_loss_registry(processed_catalog)

    candidates: list[OptimizerAuditCandidate] = []
    _announce(progress, "Selecting paired stay-out and pit-now decisions")
    for index, session_key in enumerate(session_keys, start=1):
        integrity = verify_processed_partition(processed_paths, session_key)
        if not integrity.is_valid:
            detail = "; ".join(issue.message for issue in integrity.issues[:5])
            raise OptimizerAuditError(
                f"processed integrity failed for {session_key.identifier}: {detail}"
            )
        decision_rows = read_parquet_table(
            dataset_paths.for_session(session_key).decision_rows
        )
        processed_laps = read_parquet_table(
            processed_paths.for_session(session_key).laps
        )
        protected_rows += _protected_row_count(
            (decision_rows, "season"),
            (processed_laps, "Season"),
        )
        candidates.extend(
            build_session_optimizer_audit_candidates(
                session_key=session_key,
                decision_rows=decision_rows,
                processed_laps=processed_laps,
                pit_loss_registry=registry,
            )
        )
        if index % 10 == 0 or index == len(session_keys):
            _announce(
                progress,
                f"Scanned {index}/{len(session_keys)} development races",
            )
    if protected_rows:
        raise OptimizerAuditError("protected 2025 rows entered Phase 8")

    _validate_candidate_population(candidates)
    _announce(
        progress,
        f"Evaluating {len(candidates)} historical decisions twice",
    )
    started = perf_counter()
    diagnostics = evaluate_optimizer_audit_candidates(
        tuple(candidates),
        adapter=adapter,
        pit_loss_registry=registry,
        uncertainty=uncertainty,
    )
    execution_duration = perf_counter() - started
    decision_sessions = len(
        {
            (decision.request.state.season, decision.request.state.session_id)
            for decision in diagnostics.decisions
        }
    )
    report_provenance = OptimizerReportProvenance(
        optimizer_contract_version=OPTIMIZER_CONTRACT_VERSION,
        simulation_contract_version=SIMULATION_CONTRACT_VERSION,
        model_contract_version=MODEL_CONTRACT_VERSION,
        model_artifact_id=model_paths.artifact_id,
        dataset_contract_version=DATASET_CONTRACT_VERSION,
        dataset_build_identifier=dataset_build_identifier,
        development_sessions=decision_sessions,
        protected_evaluation_rows=protected_rows,
        random_seed=SIMULATION_RANDOM_SEED,
        dependency_versions=runtime_optimizer_dependency_versions(),
        execution_duration_seconds=execution_duration,
    )
    _announce(progress, "Writing and reloading immutable optimizer evidence")
    tables = build_optimizer_report(
        diagnostics=diagnostics,
        provenance=report_provenance,
    )
    write_optimizer_report(paths=report_paths, tables=tables)
    verification = verify_optimizer_report(report_paths)
    verification.raise_for_errors()

    selected_pairs = len(candidates) // 2
    return OptimizerAuditResult(
        report_paths=report_paths,
        report_verification=verification,
        diagnostics=diagnostics,
        audited_development_sessions=len(session_keys),
        decision_development_sessions=decision_sessions,
        candidate_pair_slots=len(session_keys),
        selected_decision_pairs=selected_pairs,
        excluded_pair_slots=len(session_keys) - selected_pairs,
        selected_decisions=len(candidates),
        observed_pit_now=sum(
            item.observed_action is PitDecisionAction.PIT_NOW
            for item in candidates
        ),
        observed_stay_out=sum(
            item.observed_action is PitDecisionAction.STAY_OUT
            for item in candidates
        ),
        protected_evaluation_rows=protected_rows,
        deterministic_decision_passes=2,
        action_time_margin_seconds=uncertainty.action_time_margin_seconds,
    )


def build_session_optimizer_audit_candidates(
    *,
    session_key: SessionKey,
    decision_rows: pd.DataFrame,
    processed_laps: pd.DataFrame,
    pit_loss_registry: PitLossRegistry,
) -> tuple[OptimizerAuditCandidate, ...]:
    """Select one complete historical stay-out/pit-now pair per race."""
    if not isinstance(session_key, SessionKey):
        raise TypeError("session_key must be a SessionKey")
    if not isinstance(decision_rows, pd.DataFrame):
        raise TypeError("decision_rows must be a pandas DataFrame")
    if not isinstance(processed_laps, pd.DataFrame):
        raise TypeError("processed_laps must be a pandas DataFrame")
    if not isinstance(pit_loss_registry, PitLossRegistry):
        raise TypeError("pit_loss_registry must be a PitLossRegistry")
    _require_columns(
        decision_rows,
        {
            "session_id",
            "season",
            "event_name",
            "driver",
            "team",
            "decision_lap",
            "is_decision_eligible",
            "current_compound",
            "tyre_age_laps",
            "current_stint_laps_completed",
            "completed_pit_stops",
            "previous_position",
            *APPROVED_FEATURE_COLUMNS,
        },
        source="decision_rows",
    )
    _require_columns(
        processed_laps,
        {
            "Season",
            "SessionType",
            "EventName",
            "Driver",
            "Team",
            "LapNumber",
            "Compound",
            "PitInTime",
            "Rainfall",
            "TrackStatus",
            "IsEligible",
            "LapTimeSeconds",
        },
        source="processed_laps",
    )
    if not decision_rows["session_id"].astype(str).eq(session_key.identifier).all():
        raise OptimizerAuditError("decision rows differ from the session key")
    if (
        not pd.to_numeric(decision_rows["season"], errors="coerce")
        .eq(session_key.season)
        .all()
    ):
        raise OptimizerAuditError(
            "decision-row season differs from the session key"
        )

    for stay_row, pit_row, pit_lap, total_laps, target_compound in _rank_pit_pairs(
        decision_rows=decision_rows,
        processed_laps=processed_laps,
    ):
        try:
            stay_out = _build_candidate(
                session_key=session_key,
                row=stay_row,
                total_laps=total_laps,
                pit_lap=pit_lap,
                target_compound=target_compound,
                observed_action=PitDecisionAction.STAY_OUT,
                decision_rows=decision_rows,
                processed_laps=processed_laps,
                pit_loss_registry=pit_loss_registry,
            )
            pit_now = _build_candidate(
                session_key=session_key,
                row=pit_row,
                total_laps=total_laps,
                pit_lap=pit_lap,
                target_compound=target_compound,
                observed_action=PitDecisionAction.PIT_NOW,
                decision_rows=decision_rows,
                processed_laps=processed_laps,
                pit_loss_registry=pit_loss_registry,
            )
        except (OptimizerContractError, SimulationContractError):
            continue
        return (stay_out, pit_now)
    return ()


def evaluate_optimizer_audit_candidates(
    candidates: tuple[OptimizerAuditCandidate, ...],
    *,
    adapter: Phase6ModelAdapter,
    pit_loss_registry: PitLossRegistry,
    uncertainty: DecisionUncertaintyAssumption,
) -> HistoricalDecisionDiagnostics:
    """Evaluate every candidate twice and reject any scalar difference."""
    if not isinstance(candidates, tuple) or not candidates:
        raise OptimizerAuditError("audit candidates must be a non-empty tuple")
    if any(not isinstance(item, OptimizerAuditCandidate) for item in candidates):
        raise TypeError("every audit candidate must be an OptimizerAuditCandidate")
    if not isinstance(adapter, Phase6ModelAdapter):
        raise TypeError("adapter must be a Phase6ModelAdapter")
    if not isinstance(pit_loss_registry, PitLossRegistry):
        raise TypeError("pit_loss_registry must be a PitLossRegistry")
    if not isinstance(uncertainty, DecisionUncertaintyAssumption):
        raise TypeError("uncertainty must be a DecisionUncertaintyAssumption")

    decisions: list[HistoricalDecisionDiagnostic] = []
    for candidate in candidates:
        first = _evaluate_candidate(
            candidate,
            adapter=adapter,
            pit_loss_registry=pit_loss_registry,
            uncertainty=uncertainty,
        )
        second = _evaluate_candidate(
            candidate,
            adapter=adapter,
            pit_loss_registry=pit_loss_registry,
            uncertainty=uncertainty,
        )
        if first != second:
            raise OptimizerAuditError(
                f"non-deterministic optimizer output: {candidate.decision_key}"
            )
        decisions.append(
            HistoricalDecisionDiagnostic(
                stability=first,
                observed_action=candidate.observed_action,
            )
        )
    return build_historical_decision_diagnostics(tuple(decisions))


def _evaluate_candidate(
    candidate: OptimizerAuditCandidate,
    *,
    adapter: Phase6ModelAdapter,
    pit_loss_registry: PitLossRegistry,
    uncertainty: DecisionUncertaintyAssumption,
):
    sensitivity = analyze_pit_decision_sensitivity(
        candidate.request,
        context=candidate.context,
        adapter=adapter,
        pit_loss_registry=pit_loss_registry,
    )
    return assess_recommendation_stability(
        sensitivity,
        uncertainty=uncertainty,
    )


def _rank_pit_pairs(
    *,
    decision_rows: pd.DataFrame,
    processed_laps: pd.DataFrame,
) -> tuple[tuple[pd.Series, pd.Series, int, int, DryCompound], ...]:
    lap_numbers = _integer_series(processed_laps["LapNumber"], "LapNumber")
    source = processed_laps.assign(_audit_lap_number=lap_numbers)
    session_total_laps = int(source["_audit_lap_number"].max())
    decision_laps = _integer_series(decision_rows["decision_lap"], "decision_lap")
    ranked: list[
        tuple[
            tuple[float, float, str, str],
            pd.Series,
            pd.Series,
            int,
            int,
            DryCompound,
        ]
    ] = []
    for (driver, team), laps in source.groupby(["Driver", "Team"], sort=True):
        laps = laps.sort_values("_audit_lap_number", kind="stable")
        if int(laps["_audit_lap_number"].max()) != session_total_laps:
            continue
        for _, pit_row in laps.loc[laps["PitInTime"].notna()].iterrows():
            pit_lap = int(pit_row["_audit_lap_number"])
            if pit_lap < 2 or pit_lap > session_total_laps - 2:
                continue
            window = laps.loc[
                laps["_audit_lap_number"].between(pit_lap - 1, pit_lap + 1)
            ]
            if tuple(window["_audit_lap_number"]) != (
                pit_lap - 1,
                pit_lap,
                pit_lap + 1,
            ):
                continue
            if any(_strict_bool(value, "Rainfall") for value in window["Rainfall"]):
                continue
            if any(str(value).strip() != "1" for value in window["TrackStatus"]):
                continue
            try:
                tuple(_compound(value) for value in window["Compound"])
                target_compound = _compound(window.iloc[-1]["Compound"])
            except SimulationContractError:
                continue
            matching = decision_rows.loc[
                decision_rows["driver"].astype(str).eq(str(driver))
                & decision_rows["team"].astype(str).eq(str(team))
                & decision_laps.isin((pit_lap - 1, pit_lap))
            ]
            stay_rows = matching.loc[decision_laps.loc[matching.index].eq(pit_lap - 1)]
            pit_rows = matching.loc[decision_laps.loc[matching.index].eq(pit_lap)]
            if len(stay_rows) != 1 or len(pit_rows) != 1:
                continue
            stay = stay_rows.iloc[0]
            pit = pit_rows.iloc[0]
            if not _eligible_decision(stay) or not _eligible_decision(pit):
                continue
            position = _optional_integer(pit["previous_position"], "previous_position")
            rank = (
                -float(pit_lap),
                float("inf") if position is None else float(position),
                str(driver),
                str(team),
            )
            ranked.append(
                (
                    rank,
                    stay,
                    pit,
                    pit_lap,
                    session_total_laps,
                    target_compound,
                )
            )
    ranked.sort(key=lambda item: item[0])
    return tuple(
        (stay, pit, pit_lap, total_laps, target)
        for _, stay, pit, pit_lap, total_laps, target in ranked
    )


def _eligible_decision(row: pd.Series) -> bool:
    if not isinstance(row["is_decision_eligible"], (bool, np.bool_)):
        raise OptimizerAuditError("is_decision_eligible must contain booleans")
    if not bool(row["is_decision_eligible"]):
        return False
    return (
        _required_integer(row["tyre_age_laps"], "tyre_age_laps") >= 2
        and _required_integer(
            row["current_stint_laps_completed"],
            "current_stint_laps_completed",
        )
        >= 2
    )


def _build_candidate(
    *,
    session_key: SessionKey,
    row: pd.Series,
    total_laps: int,
    pit_lap: int,
    target_compound: DryCompound,
    observed_action: PitDecisionAction,
    decision_rows: pd.DataFrame,
    processed_laps: pd.DataFrame,
    pit_loss_registry: PitLossRegistry,
) -> OptimizerAuditCandidate:
    event_name = str(row["event_name"])
    driver = str(row["driver"])
    team = str(row["team"])
    current_lap = _required_integer(row["decision_lap"], "decision_lap")
    identity = (
        pd.to_numeric(processed_laps["Season"], errors="coerce").eq(
            session_key.season
        )
        & processed_laps["SessionType"].astype(str).eq(session_key.session_type)
        & processed_laps["EventName"].astype(str).eq(event_name)
        & processed_laps["Driver"].astype(str).eq(driver)
        & processed_laps["Team"].astype(str).eq(team)
    )
    lap_numbers = _integer_series(processed_laps["LapNumber"], "LapNumber")
    driver_laps = processed_laps.loc[identity].copy()
    driver_laps["_audit_lap_number"] = lap_numbers.loc[identity]
    current_compound = _compound(row["current_compound"])
    current_rows = driver_laps.loc[
        driver_laps["_audit_lap_number"].eq(current_lap)
    ]
    if len(current_rows) != 1 or _compound(
        current_rows.iloc[0]["Compound"]
    ) is not current_compound:
        raise OptimizerAuditError(
            "decision compound differs from the processed current lap"
        )
    prior_compounds = [
        _compound(value)
        for value in driver_laps.loc[
            driver_laps["_audit_lap_number"].lt(current_lap), "Compound"
        ]
        if str(value).strip().upper() in {item.value for item in DryCompound}
    ]
    compounds_used = tuple(dict.fromkeys((*prior_compounds, current_compound)))
    resolution = pit_loss_registry.resolve(
        event_name=event_name,
        scenario=PitLossScenario.NOMINAL,
    )
    request = PitDecisionRequest(
        state=RaceState(
            season=session_key.season,
            session_id=session_key.identifier,
            event_name=event_name,
            driver=driver,
            team=team,
            current_lap=current_lap,
            total_laps=total_laps,
            current_compound=current_compound,
            tyre_age_laps=_required_integer(
                row["tyre_age_laps"],
                "tyre_age_laps",
            ),
            current_stint_laps_completed=_required_integer(
                row["current_stint_laps_completed"],
                "current_stint_laps_completed",
            ),
            completed_pit_stops=_required_integer(
                row["completed_pit_stops"],
                "completed_pit_stops",
            ),
            compounds_used=compounds_used,
            previous_position=_optional_integer(
                row["previous_position"],
                "previous_position",
            ),
        ),
        target_compound=target_compound,
        pit_loss=resolution.assumption,
    )
    observed_request = replace(
        request.simulation_request_for(observed_action),
        mode=SimulationMode.OBSERVED_STRATEGY_REPLAY,
    )
    context = build_observed_replay_context(
        observed_request,
        decision_rows,
        processed_laps,
    )
    return OptimizerAuditCandidate(
        request=request,
        context=context,
        observed_action=observed_action,
        observed_pit_lap=pit_lap,
    )


def _simulation_uncertainty(
    *,
    artifacts_root: Path,
    simulation_run_id: str,
    model_artifact_id: str,
    dataset_build_identifier: str,
) -> DecisionUncertaintyAssumption:
    paths = SimulationReportPaths(artifacts_root, simulation_run_id)
    verification = verify_simulation_report(paths)
    if not verification.valid:
        detail = "; ".join(verification.issues[:5])
        raise OptimizerAuditError(
            f"Phase 7 simulation report integrity failed: {detail}"
        )
    provenance = read_json_document(paths.root / "provenance.json")
    expected = {
        "model_artifact_id": model_artifact_id,
        "dataset_contract_version": DATASET_CONTRACT_VERSION,
        "dataset_build_identifier": dataset_build_identifier,
        "protected_evaluation_rows": 0,
    }
    mismatches = [
        name for name, value in expected.items() if provenance.get(name) != value
    ]
    if mismatches:
        raise OptimizerAuditError(
            "Phase 7 evidence differs from Phase 8 inputs: "
            + ", ".join(mismatches)
        )
    metrics = read_parquet_table(paths.root / "metrics.parquet")
    _require_columns(
        metrics,
        {"scope", "value", "mean_absolute_error_seconds"},
        source="Phase 7 metrics",
    )
    selected = metrics.loc[
        metrics["scope"].astype(str).eq("OVERALL_REMAINING")
        & metrics["value"].astype(str).eq("ALL")
    ]
    if len(selected) != 1:
        raise OptimizerAuditError(
            "Phase 7 report must contain one overall remaining-time metric"
        )
    margin = float(selected.iloc[0]["mean_absolute_error_seconds"])
    if not math.isfinite(margin) or margin < 0:
        raise OptimizerAuditError("Phase 7 remaining-time MAE is invalid")
    return DecisionUncertaintyAssumption(
        action_time_margin_seconds=margin,
        evidence=(
            "Phase 7 immutable development replay overall remaining-time MAE; "
            f"run_id={simulation_run_id}; descriptive robustness margin, not "
            "a calibrated probability or confidence interval"
        ),
    )


def _pit_loss_registry(catalog: pd.DataFrame) -> PitLossRegistry:
    _require_columns(catalog, {"event_name"}, source="processed catalog")
    events = tuple(sorted(set(catalog["event_name"].astype(str))))
    if not events or any(not event.strip() for event in events):
        raise OptimizerAuditError("processed catalog contains invalid events")
    low, nominal, high = AUDIT_PIT_LOSS_SECONDS
    return PitLossRegistry(
        tuple(
            CircuitPitLossProfile(
                event_name=event,
                low_seconds=low,
                nominal_seconds=nominal,
                high_seconds=high,
                source=PitLossSource.EXPLICIT_ASSUMPTION,
                evidence=_PIT_LOSS_EVIDENCE,
            )
            for event in events
        )
    )


def _load_catalog(
    path: Path,
    *,
    protected_root: Path,
    source: str,
) -> pd.DataFrame:
    if protected_root.exists():
        raise OptimizerAuditError(
            f"protected evaluation directory exists: {protected_root}"
        )
    if not path.is_file():
        raise OptimizerAuditError(f"{source} catalog does not exist: {path}")
    catalog = read_parquet_table(path)
    _require_columns(
        catalog,
        {"season", "round_number", "session_type", "event_name"},
        source=f"{source} catalog",
    )
    return catalog


def _session_keys(catalog: pd.DataFrame) -> tuple[SessionKey, ...]:
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
            key=lambda key: (key.season, key.round_number, key.session_type),
        )
    )
    expected = EXPECTED_DEVELOPMENT_TOTALS.sessions
    if len(keys) != expected:
        raise OptimizerAuditError(
            f"optimizer audit requires exactly {expected} sessions"
        )
    if len(set(keys)) != len(keys):
        raise OptimizerAuditError("dataset catalog contains duplicate sessions")
    if any(key.season == PROTECTED_EVALUATION_SEASON for key in keys):
        raise OptimizerAuditError("dataset catalog contains protected 2025")
    return keys


def _reconcile_catalogs(dataset: pd.DataFrame, processed: pd.DataFrame) -> None:
    columns = ["season", "round_number", "session_type", "event_name"]
    left = dataset.loc[:, columns].copy()
    right = processed.loc[:, columns].copy()
    for frame in (left, right):
        frame["season"] = pd.to_numeric(frame["season"], errors="raise").astype(int)
        frame["round_number"] = pd.to_numeric(
            frame["round_number"], errors="raise"
        ).astype(int)
        frame["session_type"] = frame["session_type"].astype(str)
        frame["event_name"] = frame["event_name"].astype(str)
        frame.sort_values(columns[:3], kind="stable", inplace=True)
        frame.reset_index(drop=True, inplace=True)
    try:
        pd.testing.assert_frame_equal(left, right)
    except AssertionError as error:
        raise OptimizerAuditError(
            "dataset and processed catalogs describe different races"
        ) from error


def _validate_candidate_population(
    candidates: list[OptimizerAuditCandidate],
) -> None:
    if not candidates or len(candidates) % 2:
        raise OptimizerAuditError(
            "optimizer audit requires complete non-empty decision pairs"
        )
    keys = tuple(candidate.decision_key for candidate in candidates)
    if len(keys) != len(set(keys)):
        raise OptimizerAuditError("optimizer audit decisions must be unique")
    represented_seasons = {candidate.request.state.season for candidate in candidates}
    if represented_seasons != set(DEVELOPMENT_SEASONS):
        raise OptimizerAuditError(
            "optimizer audit population does not cover every development season"
        )
    grouped: dict[tuple[int, str], list[OptimizerAuditCandidate]] = {}
    for candidate in candidates:
        state = candidate.request.state
        grouped.setdefault((state.season, state.session_id), []).append(candidate)
    for pair in grouped.values():
        if len(pair) != 2 or {item.observed_action for item in pair} != set(
            PitDecisionAction
        ):
            raise OptimizerAuditError(
                "every represented session must contain one complete action pair"
            )
        ordered = sorted(pair, key=lambda item: item.request.state.current_lap)
        stay_out, pit_now = ordered
        if (
            stay_out.observed_action is not PitDecisionAction.STAY_OUT
            or pit_now.observed_action is not PitDecisionAction.PIT_NOW
            or pit_now.request.state.current_lap
            != stay_out.request.state.current_lap + 1
            or pit_now.observed_pit_lap != stay_out.observed_pit_lap
            or pit_now.request.state.driver != stay_out.request.state.driver
            or pit_now.request.target_compound is not stay_out.request.target_compound
        ):
            raise OptimizerAuditError(
                "stored historical decision pair is not symmetric"
            )


def _protected_row_count(*frames: tuple[pd.DataFrame, str]) -> int:
    count = 0
    for frame, column in frames:
        if column not in frame.columns:
            raise OptimizerAuditError(f"audit source is missing {column}")
        seasons = pd.to_numeric(frame[column], errors="coerce")
        if seasons.isna().any():
            raise OptimizerAuditError("audit source contains invalid seasons")
        count += int(seasons.eq(PROTECTED_EVALUATION_SEASON).sum())
    return count


def _require_columns(
    frame: pd.DataFrame,
    required: set[str],
    *,
    source: str,
) -> None:
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise OptimizerAuditError(
            f"{source} is missing columns: {', '.join(missing)}"
        )


def _integer_series(values: pd.Series, field_name: str) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.isna().any() or not np.isfinite(numeric.to_numpy()).all():
        raise OptimizerAuditError(f"{field_name} must contain finite integers")
    if not np.equal(numeric.to_numpy() % 1, 0).all():
        raise OptimizerAuditError(f"{field_name} must contain finite integers")
    return numeric.astype("int64")


def _required_integer(value: object, field_name: str) -> int:
    normalized = _optional_integer(value, field_name)
    if normalized is None:
        raise OptimizerAuditError(f"{field_name} must not be missing")
    return normalized


def _optional_integer(value: object, field_name: str) -> int | None:
    if pd.isna(value):
        return None
    if isinstance(value, (bool, np.bool_)) or not isinstance(
        value,
        (int, float, np.integer, np.floating),
    ):
        raise OptimizerAuditError(f"{field_name} must be an integer")
    numeric = float(value)
    if not math.isfinite(numeric) or not numeric.is_integer():
        raise OptimizerAuditError(f"{field_name} must be an integer")
    return int(numeric)


def _compound(value: object) -> DryCompound:
    try:
        return DryCompound(str(value).strip().upper())
    except ValueError as error:
        raise SimulationContractError(
            f"unsupported dry compound in optimizer audit: {value!r}"
        ) from error


def _strict_bool(value: object, field_name: str) -> bool:
    if not isinstance(value, (bool, np.bool_)):
        raise OptimizerAuditError(f"{field_name} must contain booleans")
    return bool(value)


def _announce(progress: ProgressCallback | None, message: str) -> None:
    if progress is not None:
        progress(message)
