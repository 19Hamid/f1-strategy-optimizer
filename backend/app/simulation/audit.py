"""Run the complete Phase 7 audit on verified development races."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Final

import numpy as np
import pandas as pd

from app.cleaning.integrity import verify_processed_partition
from app.cleaning.paths import ProcessedDataPaths
from app.datasets.contracts import (
    DATASET_CONTRACT_VERSION,
    EXPECTED_DEVELOPMENT_TOTALS,
    PROTECTED_EVALUATION_SEASON,
)
from app.datasets.integrity import verify_complete_dataset
from app.datasets.paths import DatasetPaths
from app.ml import MODEL_CONTRACT_VERSION, ModelArtifactPaths
from app.pipeline import SessionKey
from app.pipeline.serialization import read_parquet_table, sha256_file
from app.simulation.contracts import (
    SIMULATION_CONTRACT_VERSION,
    SIMULATION_RANDOM_SEED,
    DryCompound,
    PitLossSource,
    PlannedPitStop,
    RaceState,
    SimulationContractError,
    SimulationMode,
    SimulationRequest,
    StrategyPlan,
)
from app.simulation.model_adapter import (
    Phase6ModelAdapter,
    SimulationFeatureContext,
)
from app.simulation.observed_replay import (
    ObservedReplayEvaluation,
    ObservedStrategyReplay,
    ObservedStrategyTrace,
    ReplayHorizon,
    build_observed_replay_context,
    build_observed_strategy_trace,
    replay_observed_strategy,
)
from app.simulation.pit_loss import (
    CircuitPitLossProfile,
    PitLossRegistry,
    PitLossScenario,
)
from app.simulation.reporting import (
    SimulationReportProvenance,
    build_simulation_report,
    runtime_simulation_dependency_versions,
)
from app.simulation.storage import (
    SimulationReportPaths,
    SimulationReportVerification,
    verify_simulation_report,
    write_simulation_report,
)

ProgressCallback = Callable[[str], None]

AUDIT_HORIZON_LAPS: Final = (5, 15, 30)
AUDIT_PIT_LOSS_SECONDS: Final = (15.0, 20.0, 25.0)
_PIT_LOSS_EVIDENCE: Final = (
    "controlled Phase 7 final-audit sensitivity assumption; "
    "not an observed net pit-loss label"
)


class SimulationAuditError(RuntimeError):
    """Raised when the real Phase 7 development audit cannot pass safely."""


@dataclass(frozen=True, slots=True)
class SimulationAuditCandidate:
    """One deterministic historical suffix ready for observed replay."""

    request: SimulationRequest
    context: SimulationFeatureContext
    observed: ObservedStrategyTrace
    horizon: ReplayHorizon

    def __post_init__(self) -> None:
        """Require the declared horizon to match the exact trace length."""
        if not isinstance(self.request, SimulationRequest):
            raise TypeError("request must be a SimulationRequest")
        if not isinstance(self.context, SimulationFeatureContext):
            raise TypeError("context must be a SimulationFeatureContext")
        if not isinstance(self.observed, ObservedStrategyTrace):
            raise TypeError("observed must be an ObservedStrategyTrace")
        if not isinstance(self.horizon, ReplayHorizon):
            raise TypeError("horizon must be a ReplayHorizon")
        if _horizon(self.observed.remaining_laps) is not self.horizon:
            raise SimulationAuditError("candidate horizon does not match its trace")


@dataclass(frozen=True, slots=True)
class SimulationAuditResult:
    """Verified replay population and its immutable report evidence."""

    report_paths: SimulationReportPaths
    report_verification: SimulationReportVerification
    evaluation: ObservedReplayEvaluation
    audited_development_sessions: int
    replay_development_sessions: int
    candidate_slots: int
    selected_replays: int
    excluded_candidate_slots: int
    horizon_counts: tuple[tuple[ReplayHorizon, int], ...]
    protected_evaluation_rows: int
    deterministic_replay_passes: int


def run_development_simulation_audit(
    *,
    datasets_root: Path,
    processed_root: Path,
    artifacts_root: Path,
    run_id: str,
    model_artifact_id: str,
    progress: ProgressCallback | None = None,
) -> SimulationAuditResult:
    """Verify 68 races, replay controlled suffixes and publish evidence."""
    dataset_paths = DatasetPaths(Path(datasets_root))
    processed_paths = ProcessedDataPaths(Path(processed_root))
    report_paths = SimulationReportPaths(Path(artifacts_root), run_id)
    if report_paths.root.exists():
        raise SimulationAuditError(
            f"simulation report already exists: {report_paths.root}"
        )

    _announce(progress, "Verifying the 68-race dataset catalog and partitions")
    dataset_catalog = _load_catalog(
        dataset_paths.catalog,
        protected_root=dataset_paths.version_root
        / f"season={PROTECTED_EVALUATION_SEASON}",
        source="dataset",
    )
    session_keys = _session_keys(dataset_catalog)
    dataset_integrity = verify_complete_dataset(dataset_paths, session_keys)
    if not dataset_integrity.is_valid:
        detail = "; ".join(issue.message for issue in dataset_integrity.issues[:5])
        raise SimulationAuditError(f"dataset integrity failed: {detail}")

    _announce(progress, "Verifying the matching processed-race catalog")
    processed_catalog = _load_catalog(
        processed_paths.catalog,
        protected_root=processed_paths.version_root
        / f"season={PROTECTED_EVALUATION_SEASON}",
        source="processed",
    )
    _reconcile_catalogs(dataset_catalog, processed_catalog)
    protected_rows = _protected_row_count(
        (dataset_catalog, "season"),
        (processed_catalog, "season"),
    )
    if protected_rows:
        raise SimulationAuditError("protected 2025 rows entered Phase 7")

    dataset_build_identifier = sha256_file(dataset_paths.catalog)
    model_paths = ModelArtifactPaths(Path(artifacts_root), model_artifact_id)
    _announce(progress, "Loading the verified final Phase 6 model artifact")
    adapter = Phase6ModelAdapter.from_paths(model_paths)
    model_provenance = adapter.artifact.provenance
    if model_provenance.dataset_contract_version != DATASET_CONTRACT_VERSION:
        raise SimulationAuditError(
            "model and simulation dataset contract versions differ"
        )
    if model_provenance.dataset_build_identifier != dataset_build_identifier:
        raise SimulationAuditError(
            "model artifact was not fitted from the verified dataset catalog"
        )

    registry = _pit_loss_registry(processed_catalog)
    candidates: list[SimulationAuditCandidate] = []
    _announce(progress, "Selecting exact 5-, 15- and 30-lap replay suffixes")
    for index, session_key in enumerate(session_keys, start=1):
        integrity = verify_processed_partition(processed_paths, session_key)
        if not integrity.is_valid:
            detail = "; ".join(issue.message for issue in integrity.issues[:5])
            raise SimulationAuditError(
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
            build_session_audit_candidates(
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
        raise SimulationAuditError("protected 2025 rows entered Phase 7")

    candidate_slots = len(session_keys) * len(AUDIT_HORIZON_LAPS)
    _validate_candidate_population(candidates)
    _announce(
        progress,
        f"Replaying {len(candidates)} selected trajectories twice",
    )
    started = perf_counter()
    evaluation = replay_audit_candidates(
        tuple(candidates),
        adapter=adapter,
    )
    execution_duration = perf_counter() - started
    replay_sessions = len(
        {
            (replay.observed.season, replay.observed.session_id)
            for replay in evaluation.replays
        }
    )
    report_provenance = SimulationReportProvenance(
        simulation_contract_version=SIMULATION_CONTRACT_VERSION,
        model_contract_version=MODEL_CONTRACT_VERSION,
        model_artifact_id=model_paths.artifact_id,
        dataset_contract_version=DATASET_CONTRACT_VERSION,
        dataset_build_identifier=dataset_build_identifier,
        development_sessions=replay_sessions,
        protected_evaluation_rows=protected_rows,
        random_seed=SIMULATION_RANDOM_SEED,
        dependency_versions=runtime_simulation_dependency_versions(),
        execution_duration_seconds=execution_duration,
    )
    _announce(progress, "Writing and reloading immutable simulation evidence")
    tables = build_simulation_report(
        evaluation=evaluation,
        provenance=report_provenance,
    )
    write_simulation_report(paths=report_paths, tables=tables)
    verification = verify_simulation_report(report_paths)
    verification.raise_for_errors()

    counts = tuple(
        (horizon, sum(candidate.horizon is horizon for candidate in candidates))
        for horizon in ReplayHorizon
    )
    return SimulationAuditResult(
        report_paths=report_paths,
        report_verification=verification,
        evaluation=evaluation,
        audited_development_sessions=len(session_keys),
        replay_development_sessions=replay_sessions,
        candidate_slots=candidate_slots,
        selected_replays=len(candidates),
        excluded_candidate_slots=candidate_slots - len(candidates),
        horizon_counts=counts,
        protected_evaluation_rows=protected_rows,
        deterministic_replay_passes=2,
    )


def build_session_audit_candidates(
    *,
    session_key: SessionKey,
    decision_rows: pd.DataFrame,
    processed_laps: pd.DataFrame,
    pit_loss_registry: PitLossRegistry,
) -> tuple[SimulationAuditCandidate, ...]:
    """Choose at most one deterministic valid driver per audit horizon."""
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
            "LapTimeSeconds",
            "Compound",
            "PitInTime",
            "Rainfall",
            "TrackStatus",
            "IsEligible",
        },
        source="processed_laps",
    )
    if not decision_rows["session_id"].astype(str).eq(session_key.identifier).all():
        raise SimulationAuditError("decision rows differ from the session key")
    if (
        not pd.to_numeric(decision_rows["season"], errors="coerce")
        .eq(session_key.season)
        .all()
    ):
        raise SimulationAuditError("decision-row season differs from the session key")

    choices: list[SimulationAuditCandidate] = []
    for remaining_laps in AUDIT_HORIZON_LAPS:
        ranked = _rank_driver_suffixes(
            decision_rows=decision_rows,
            processed_laps=processed_laps,
            remaining_laps=remaining_laps,
        )
        selected: SimulationAuditCandidate | None = None
        for row, total_laps in ranked:
            try:
                selected = _build_candidate(
                    session_key=session_key,
                    row=row,
                    total_laps=total_laps,
                    remaining_laps=remaining_laps,
                    decision_rows=decision_rows,
                    processed_laps=processed_laps,
                    pit_loss_registry=pit_loss_registry,
                )
            except SimulationContractError:
                continue
            if selected is not None:
                break
        if selected is not None:
            choices.append(selected)
    return tuple(choices)


def replay_audit_candidates(
    candidates: tuple[SimulationAuditCandidate, ...],
    *,
    adapter: Phase6ModelAdapter,
) -> ObservedReplayEvaluation:
    """Replay each candidate twice and reject any scalar difference."""
    if not isinstance(candidates, tuple) or not candidates:
        raise SimulationAuditError("audit candidates must be a non-empty tuple")
    if any(not isinstance(item, SimulationAuditCandidate) for item in candidates):
        raise TypeError("every audit candidate must be a SimulationAuditCandidate")
    if not isinstance(adapter, Phase6ModelAdapter):
        raise TypeError("adapter must be a Phase6ModelAdapter")
    replays: list[ObservedStrategyReplay] = []
    for candidate in candidates:
        first = replay_observed_strategy(
            candidate.request,
            context=candidate.context,
            adapter=adapter,
            observed=candidate.observed,
        )
        second = replay_observed_strategy(
            candidate.request,
            context=candidate.context,
            adapter=adapter,
            observed=candidate.observed,
        )
        if first != second:
            raise SimulationAuditError(
                f"non-deterministic replay output: {first.replay_id}"
            )
        replays.append(first)
    return ObservedReplayEvaluation(tuple(replays))


def _rank_driver_suffixes(
    *,
    decision_rows: pd.DataFrame,
    processed_laps: pd.DataFrame,
    remaining_laps: int,
) -> tuple[tuple[pd.Series, int], ...]:
    ranked: list[tuple[tuple[float, str, str], pd.Series, int]] = []
    lap_numbers = _integer_series(processed_laps["LapNumber"], "LapNumber")
    source = processed_laps.assign(_audit_lap_number=lap_numbers)
    session_total_laps = int(source["_audit_lap_number"].max())
    start_lap = session_total_laps - remaining_laps + 1
    if start_lap < 2:
        return ()
    for (driver, team), laps in source.groupby(["Driver", "Team"], sort=True):
        if int(laps["_audit_lap_number"].max()) != session_total_laps:
            continue
        decision_laps = _integer_series(decision_rows["decision_lap"], "decision_lap")
        matches = decision_rows.loc[
            decision_rows["driver"].astype(str).eq(str(driver))
            & decision_rows["team"].astype(str).eq(str(team))
            & decision_laps.eq(start_lap)
        ]
        if len(matches) != 1:
            continue
        row = matches.iloc[0]
        if not isinstance(row["is_decision_eligible"], (bool, np.bool_)):
            raise SimulationAuditError("is_decision_eligible must contain booleans")
        if not bool(row["is_decision_eligible"]):
            continue
        position = _optional_integer(row["previous_position"], "previous_position")
        rank = (
            float("inf") if position is None else float(position),
            str(driver),
            str(team),
        )
        ranked.append((rank, row, session_total_laps))
    ranked.sort(key=lambda item: item[0])
    return tuple((row, total_laps) for _, row, total_laps in ranked)


def _build_candidate(
    *,
    session_key: SessionKey,
    row: pd.Series,
    total_laps: int,
    remaining_laps: int,
    decision_rows: pd.DataFrame,
    processed_laps: pd.DataFrame,
    pit_loss_registry: PitLossRegistry,
) -> SimulationAuditCandidate:
    start_lap = total_laps - remaining_laps + 1
    event_name = str(row["event_name"])
    driver = str(row["driver"])
    team = str(row["team"])
    identity = (
        pd.to_numeric(processed_laps["Season"], errors="coerce").eq(session_key.season)
        & processed_laps["SessionType"].astype(str).eq(session_key.session_type)
        & processed_laps["EventName"].astype(str).eq(event_name)
        & processed_laps["Driver"].astype(str).eq(driver)
        & processed_laps["Team"].astype(str).eq(team)
    )
    lap_numbers = _integer_series(processed_laps["LapNumber"], "LapNumber")
    driver_laps = processed_laps.loc[identity].copy()
    driver_laps["_audit_lap_number"] = lap_numbers.loc[identity]
    driver_laps = driver_laps.sort_values("_audit_lap_number", kind="stable")
    horizon_rows = driver_laps.loc[
        driver_laps["_audit_lap_number"].between(start_lap, total_laps)
    ]
    if tuple(horizon_rows["_audit_lap_number"]) != tuple(
        range(start_lap, total_laps + 1)
    ):
        raise SimulationContractError("audit suffix is not complete and consecutive")
    compounds = tuple(_compound(value) for value in horizon_rows["Compound"])
    pit_laps = tuple(
        int(lap)
        for lap, pit_time in zip(
            horizon_rows["_audit_lap_number"],
            horizon_rows["PitInTime"],
            strict=True,
        )
        if not pd.isna(pit_time)
    )
    if any(lap >= total_laps for lap in pit_laps):
        raise SimulationContractError("audit suffix pits after its final lap")
    compound_by_lap = dict(
        zip(horizon_rows["_audit_lap_number"], compounds, strict=True)
    )
    stops = tuple(
        PlannedPitStop(
            after_lap=lap,
            new_compound=compound_by_lap[lap + 1],
        )
        for lap in pit_laps
    )
    current_compound = _compound(row["current_compound"])
    prior_compounds = [
        _compound(value)
        for value in driver_laps.loc[
            driver_laps["_audit_lap_number"].lt(start_lap), "Compound"
        ]
        if str(value).strip().upper() in {item.value for item in DryCompound}
    ]
    compounds_used = tuple(dict.fromkeys((*prior_compounds, current_compound)))
    resolution = pit_loss_registry.resolve(
        event_name=event_name,
        scenario=PitLossScenario.NOMINAL,
    )
    request = SimulationRequest(
        state=RaceState(
            season=session_key.season,
            session_id=session_key.identifier,
            event_name=event_name,
            driver=driver,
            team=team,
            current_lap=start_lap,
            total_laps=total_laps,
            current_compound=current_compound,
            tyre_age_laps=_required_integer(row["tyre_age_laps"], "tyre_age_laps"),
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
        strategy=StrategyPlan(
            strategy_id=f"observed-{remaining_laps}-lap-suffix",
            stops=stops,
        ),
        pit_loss=resolution.assumption,
        mode=SimulationMode.OBSERVED_STRATEGY_REPLAY,
    )
    context = build_observed_replay_context(
        request,
        decision_rows,
        processed_laps,
    )
    observed = build_observed_strategy_trace(request, processed_laps)
    return SimulationAuditCandidate(
        request=request,
        context=context,
        observed=observed,
        horizon=_horizon(remaining_laps),
    )


def _pit_loss_registry(catalog: pd.DataFrame) -> PitLossRegistry:
    _require_columns(catalog, {"event_name"}, source="processed catalog")
    events = tuple(sorted(set(catalog["event_name"].astype(str))))
    if not events or any(not event.strip() for event in events):
        raise SimulationAuditError("processed catalog contains invalid events")
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
        raise SimulationAuditError(
            f"protected evaluation directory exists: {protected_root}"
        )
    if not path.is_file():
        raise SimulationAuditError(f"{source} catalog does not exist: {path}")
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
        raise SimulationAuditError(
            f"simulation audit requires exactly {expected} sessions"
        )
    if len(set(keys)) != len(keys):
        raise SimulationAuditError("dataset catalog contains duplicate sessions")
    if any(key.season == PROTECTED_EVALUATION_SEASON for key in keys):
        raise SimulationAuditError("dataset catalog contains protected 2025")
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
        raise SimulationAuditError(
            "dataset and processed catalogs describe different races"
        ) from error


def _validate_candidate_population(
    candidates: list[SimulationAuditCandidate],
) -> None:
    if not candidates:
        raise SimulationAuditError("no valid observed replay candidates were found")
    represented_horizons = {candidate.horizon for candidate in candidates}
    if represented_horizons != set(ReplayHorizon):
        raise SimulationAuditError("audit population does not cover every horizon")
    represented_seasons = {candidate.request.state.season for candidate in candidates}
    if represented_seasons != {2022, 2023, 2024}:
        raise SimulationAuditError(
            "audit population does not cover every development season"
        )


def _protected_row_count(
    *frames: tuple[pd.DataFrame, str],
) -> int:
    count = 0
    for frame, column in frames:
        if column not in frame.columns:
            raise SimulationAuditError(f"audit source is missing {column}")
        seasons = pd.to_numeric(frame[column], errors="coerce")
        if seasons.isna().any():
            raise SimulationAuditError("audit source contains invalid seasons")
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
        raise SimulationAuditError(f"{source} is missing columns: {', '.join(missing)}")


def _integer_series(values: pd.Series, field_name: str) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.isna().any() or not np.isfinite(numeric.to_numpy()).all():
        raise SimulationAuditError(f"{field_name} must contain finite integers")
    if not np.equal(numeric.to_numpy() % 1, 0).all():
        raise SimulationAuditError(f"{field_name} must contain finite integers")
    return numeric.astype("int64")


def _required_integer(value: object, field_name: str) -> int:
    normalized = _optional_integer(value, field_name)
    if normalized is None:
        raise SimulationAuditError(f"{field_name} must not be missing")
    return normalized


def _optional_integer(value: object, field_name: str) -> int | None:
    if pd.isna(value):
        return None
    if isinstance(value, (bool, np.bool_)) or not isinstance(
        value, (int, float, np.integer, np.floating)
    ):
        raise SimulationAuditError(f"{field_name} must be an integer")
    numeric = float(value)
    if not math.isfinite(numeric) or not numeric.is_integer():
        raise SimulationAuditError(f"{field_name} must be an integer")
    return int(numeric)


def _compound(value: object) -> DryCompound:
    try:
        return DryCompound(str(value).strip().upper())
    except ValueError as error:
        raise SimulationContractError(
            f"unsupported dry compound in audit suffix: {value!r}"
        ) from error


def _horizon(remaining_laps: int) -> ReplayHorizon:
    if remaining_laps <= 10:
        return ReplayHorizon.SHORT
    if remaining_laps <= 25:
        return ReplayHorizon.MEDIUM
    return ReplayHorizon.LONG


def _announce(progress: ProgressCallback | None, message: str) -> None:
    if progress is not None:
        progress(message)
