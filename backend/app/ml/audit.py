"""Run the complete Phase 6 audit on verified development data."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

import pandas as pd

from app.datasets.contracts import (
    DATASET_CONTRACT_VERSION,
    EXPECTED_DEVELOPMENT_TOTALS,
    PROTECTED_EVALUATION_SEASON,
)
from app.ml.artifacts import (
    MODEL_ARTIFACT_MAX_VERIFICATION_ROWS,
    ModelArtifactPaths,
    ModelArtifactVerificationReport,
    load_model_artifact,
    model_artifact_provenance,
    verify_model_artifact,
    write_model_artifact,
)
from app.ml.contracts import MODEL_CONTRACT_VERSION, ModelTarget
from app.ml.diagnostics import build_selected_model_diagnostics
from app.ml.final_fit import (
    build_final_development_partition,
    fit_final_development_model,
)
from app.ml.matrices import build_development_training_matrices
from app.ml.reports import (
    ModelEvaluationProvenance,
    ModelReportPaths,
    ModelReportVerification,
    verify_model_report,
    write_model_report,
)
from app.ml.selection import (
    SelectedPrimaryCandidate,
    evaluate_primary_temporal_candidates,
)

ProgressCallback = Callable[[str], None]


class ModelAuditError(RuntimeError):
    """Raised when the real Phase 6 development audit cannot pass safely."""


@dataclass(frozen=True, slots=True)
class ModelAuditResult:
    """Verified model-selection report and final fitted model bundle."""

    report_paths: ModelReportPaths
    report_verification: ModelReportVerification
    model_paths: ModelArtifactPaths
    model_verification: ModelArtifactVerificationReport
    selected_candidate: SelectedPrimaryCandidate
    development_sessions: int
    contributing_training_sessions: int
    primary_target_rows: int
    auxiliary_target_rows: int
    protected_evaluation_rows: int


def run_development_model_audit(
    *,
    datasets_root: Path,
    artifacts_root: Path,
    run_id: str,
    dataset_build_identifier: str,
    progress: ProgressCallback | None = None,
) -> ModelAuditResult:
    """Verify 68 races, select candidates, refit and publish evidence."""
    from app.datasets.integrity import verify_complete_dataset
    from app.datasets.paths import DatasetPaths
    from app.pipeline.serialization import read_parquet_table

    _announce(progress, "Verifying all 68 development dataset partitions")
    dataset_paths = DatasetPaths(Path(datasets_root))
    catalog = _load_catalog(dataset_paths, reader=read_parquet_table)
    session_keys = _session_keys(catalog)
    integrity = verify_complete_dataset(dataset_paths, session_keys)
    if not integrity.is_valid:
        detail = "; ".join(issue.message for issue in integrity.issues[:5])
        raise ModelAuditError(f"dataset integrity failed: {detail}")

    _announce(progress, "Loading decision rows and targets for 68 races")
    decision_parts: list[pd.DataFrame] = []
    label_parts: list[pd.DataFrame] = []
    for key in session_keys:
        paths = dataset_paths.for_session(key)
        decision_parts.append(read_parquet_table(paths.decision_rows))
        label_parts.append(read_parquet_table(paths.decision_labels))
    decision_rows = pd.concat(decision_parts, ignore_index=True)
    decision_labels = pd.concat(label_parts, ignore_index=True)
    splits = read_parquet_table(dataset_paths.splits)
    return run_model_audit_from_frames(
        decision_rows=decision_rows,
        decision_labels=decision_labels,
        splits=splits,
        development_sessions=len(session_keys),
        artifacts_root=artifacts_root,
        run_id=run_id,
        dataset_build_identifier=dataset_build_identifier,
        expected_primary_target_rows=(EXPECTED_DEVELOPMENT_TOTALS.eligible_lap_targets),
        progress=progress,
    )


def run_model_audit_from_frames(
    *,
    decision_rows: pd.DataFrame,
    decision_labels: pd.DataFrame,
    splits: pd.DataFrame,
    development_sessions: int,
    artifacts_root: Path,
    run_id: str,
    dataset_build_identifier: str,
    expected_primary_target_rows: int | None = None,
    progress: ProgressCallback | None = None,
) -> ModelAuditResult:
    """Run the auditable modelling workflow from already verified frames."""
    _require_frame(decision_rows, source="decision_rows")
    _require_frame(decision_labels, source="decision_labels")
    _require_frame(splits, source="splits")
    protected_rows = _protected_row_count(decision_rows, decision_labels, splits)
    if protected_rows:
        raise ModelAuditError("protected 2025 data entered Phase 6")
    if development_sessions <= 0:
        raise ModelAuditError("development session count must be positive")
    source_session_ids = _reconcile_source_sessions(
        decision_rows,
        decision_labels,
        splits,
        expected_sessions=development_sessions,
    )

    model_paths = ModelArtifactPaths(
        Path(artifacts_root),
        f"{run_id}-lap-time",
    )
    report_paths = ModelReportPaths(Path(artifacts_root), run_id)
    if model_paths.root.exists():
        raise ModelAuditError(f"model artifact already exists: {model_paths.root}")
    if report_paths.root.exists():
        raise ModelAuditError(f"model report already exists: {report_paths.root}")

    _announce(progress, "Building leakage-safe primary and auxiliary matrices")
    primary_matrices = build_development_training_matrices(
        decision_rows=decision_rows,
        decision_labels=decision_labels,
        splits=splits,
        target=ModelTarget.LAP_TIME,
    )
    auxiliary_matrices = build_development_training_matrices(
        decision_rows=decision_rows,
        decision_labels=decision_labels,
        splits=splits,
        target=ModelTarget.LAP_TIME_DELTA,
    )
    final_primary = build_final_development_partition(primary_matrices)
    primary_rows = final_primary.row_count
    auxiliary_rows = _final_target_row_count(auxiliary_matrices)
    if (
        expected_primary_target_rows is not None
        and primary_rows != expected_primary_target_rows
    ):
        raise ModelAuditError(
            "primary target rows differ from the dataset contract; "
            f"expected={expected_primary_target_rows}, actual={primary_rows}"
        )
    session_ids = tuple(sorted(set(final_primary.identities["session_id"].astype(str))))
    if not set(session_ids).issubset(source_session_ids):
        raise ModelAuditError(
            "final training contains a session outside the verified catalog"
        )

    _announce(
        progress,
        "Comparing direct and residual-hybrid candidates with identity ablation",
    )
    evaluation_started = perf_counter()
    selection = evaluate_primary_temporal_candidates(
        primary_matrices,
        auxiliary_matrices=auxiliary_matrices,
        progress=progress,
    )
    selected = selection.selected_candidate
    if selected is None:
        for message in _selection_failure_messages(selection.selection):
            _announce(progress, message)
        raise ModelAuditError(
            "no candidate met the baseline, coverage and ablation gates"
        )

    _announce(progress, "Building held-out degradation and slice diagnostics")
    diagnostics = build_selected_model_diagnostics(
        primary_matrices=primary_matrices,
        auxiliary_matrices=auxiliary_matrices,
        selected_candidate=selected,
    )
    evaluation_duration = perf_counter() - evaluation_started

    _announce(progress, "Refitting the selected candidate on all 2022--2024 rows")
    final_fit = fit_final_development_model(
        matrices=primary_matrices,
        auxiliary_matrices=auxiliary_matrices,
        selected_candidate=selected,
    )
    if final_fit.training.row_count != primary_rows:
        raise ModelAuditError("final refit changed the primary target population")
    training_seasons = tuple(
        sorted(set(final_fit.training.identities["season"].astype(int)))
    )
    model_provenance = model_artifact_provenance(
        final_fit.model,
        dataset_contract_version=DATASET_CONTRACT_VERSION,
        dataset_build_identifier=dataset_build_identifier,
        training_session_ids=session_ids,
        training_seasons=training_seasons,
        fit_duration_seconds=final_fit.fit_duration_seconds,
    )

    _announce(progress, "Writing and reloading immutable model evidence")
    model_created = False
    try:
        write_model_artifact(
            paths=model_paths,
            model=final_fit.model,
            provenance=model_provenance,
            verification_features=final_fit.training.features.iloc[
                :MODEL_ARTIFACT_MAX_VERIFICATION_ROWS
            ].reset_index(drop=True),
        )
        model_created = True
        report_provenance = ModelEvaluationProvenance(
            model_contract_version=MODEL_CONTRACT_VERSION,
            dataset_contract_version=DATASET_CONTRACT_VERSION,
            dataset_build_identifier=dataset_build_identifier,
            development_sessions=development_sessions,
            contributing_training_sessions=len(session_ids),
            primary_target_rows=primary_rows,
            auxiliary_target_rows=auxiliary_rows,
            protected_evaluation_rows=protected_rows,
            selected_formulation=selected.formulation,
            selected_family=selected.family,
            selected_candidate_id=selected.candidate_id,
            selected_parameters=selected.parameters,
            final_model_artifact_id=model_paths.artifact_id,
            random_seed=model_provenance.random_seed,
            dependency_versions=model_provenance.dependency_versions,
            evaluation_duration_seconds=evaluation_duration,
            final_fit_duration_seconds=final_fit.fit_duration_seconds,
        )
        write_model_report(
            paths=report_paths,
            selection=selection,
            diagnostics=diagnostics,
            provenance=report_provenance,
        )
        model_verification = verify_model_artifact(model_paths)
        model_verification.raise_for_errors()
        report_verification = verify_model_report(report_paths)
        report_verification.raise_for_errors()
        loaded = load_model_artifact(model_paths)
        if loaded.provenance != model_provenance:
            raise ModelAuditError("reloaded model provenance changed")
    except Exception:
        if model_created:
            shutil.rmtree(model_paths.root, ignore_errors=True)
        shutil.rmtree(report_paths.root, ignore_errors=True)
        raise

    return ModelAuditResult(
        report_paths=report_paths,
        report_verification=report_verification,
        model_paths=model_paths,
        model_verification=model_verification,
        selected_candidate=selected,
        development_sessions=development_sessions,
        contributing_training_sessions=len(session_ids),
        primary_target_rows=primary_rows,
        auxiliary_target_rows=auxiliary_rows,
        protected_evaluation_rows=protected_rows,
    )


def _load_catalog(dataset_paths: object, *, reader: object) -> pd.DataFrame:
    """Load the authoritative development catalog without opening 2025."""
    protected = dataset_paths.version_root / f"season={PROTECTED_EVALUATION_SEASON}"
    if protected.exists():
        raise ModelAuditError(f"protected evaluation directory exists: {protected}")
    if not dataset_paths.catalog.is_file():
        raise ModelAuditError(
            f"dataset catalog does not exist: {dataset_paths.catalog}"
        )
    catalog = reader(dataset_paths.catalog)
    required = {"season", "round_number", "session_type"}
    missing = sorted(required.difference(catalog.columns))
    if missing:
        raise ModelAuditError("dataset catalog missing columns: " + ", ".join(missing))
    return catalog


def _session_keys(catalog: pd.DataFrame) -> tuple[object, ...]:
    """Build the exact canonical 68-race schedule."""
    from app.pipeline import SessionKey

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
        raise ModelAuditError(
            "model audit requires exactly "
            f"{EXPECTED_DEVELOPMENT_TOTALS.sessions} sessions"
        )
    if len(set(keys)) != len(keys):
        raise ModelAuditError("dataset catalog contains duplicate sessions")
    if any(key.season == PROTECTED_EVALUATION_SEASON for key in keys):
        raise ModelAuditError("dataset catalog contains protected 2025")
    return keys


def _final_target_row_count(matrices: tuple[object, ...]) -> int:
    """Count all final-fit rows from the last expanding temporal fold."""
    final = matrices[-1]
    return final.training.row_count + final.validation.row_count


def _reconcile_source_sessions(
    decision_rows: pd.DataFrame,
    decision_labels: pd.DataFrame,
    splits: pd.DataFrame,
    *,
    expected_sessions: int,
) -> frozenset[str]:
    """Require all source tables to cover the same audited race catalog."""
    session_sets: list[frozenset[str]] = []
    for name, frame in (
        ("decision_rows", decision_rows),
        ("decision_labels", decision_labels),
        ("splits", splits),
    ):
        if "session_id" not in frame.columns:
            raise ModelAuditError(f"{name} is missing session_id")
        values = frame["session_id"].astype("string")
        if values.isna().any() or values.str.strip().eq("").any():
            raise ModelAuditError(f"{name} contains invalid session_id")
        session_sets.append(frozenset(values.astype(str)))
    if len(set(session_sets)) != 1:
        raise ModelAuditError("audit source session sets differ")
    sessions = session_sets[0]
    if len(sessions) != expected_sessions:
        raise ModelAuditError(
            "audit source sessions differ from the verified catalog; "
            f"expected={expected_sessions}, actual={len(sessions)}"
        )
    return sessions


def _protected_row_count(*frames: pd.DataFrame) -> int:
    """Count protected rows before any development filtering can hide them."""
    total = 0
    for frame in frames:
        if "season" not in frame.columns:
            raise ModelAuditError("audit source is missing season")
        seasons = pd.to_numeric(frame["season"], errors="coerce")
        if seasons.isna().any():
            raise ModelAuditError("audit source contains invalid seasons")
        total += int(seasons.eq(PROTECTED_EVALUATION_SEASON).sum())
    return total


def _require_frame(value: object, *, source: str) -> None:
    """Require explicit DataFrame audit inputs."""
    if not isinstance(value, pd.DataFrame):
        raise TypeError(f"{source} must be a pandas DataFrame")


def _announce(progress: ProgressCallback | None, message: str) -> None:
    """Emit optional CLI progress without coupling library code to stdout."""
    if progress is not None:
        progress(message)


def _selection_failure_messages(selection: pd.DataFrame) -> tuple[str, ...]:
    """Summarize failed gates and strongest candidates without spin."""
    gate_columns = (
        "beats_frozen_baseline",
        "beats_comparable_baseline",
        "ablation_passes",
        "minimum_coverage_passes",
        "both_folds_present",
    )
    required = {
        "formulation",
        "candidate_id",
        "full_mean_absolute_error_seconds",
        "full_common_mean_absolute_error_seconds",
        "ablated_common_mean_absolute_error_seconds",
        "coverage_rate",
        *gate_columns,
    }
    missing = sorted(required.difference(selection.columns))
    if missing:
        raise ModelAuditError(
            "failed selection evidence is missing columns: " + ", ".join(missing)
        )
    counts = ", ".join(
        f"{column}={int(selection[column].eq(True).sum())}/{len(selection)}"
        for column in gate_columns
    )
    messages = [f"Selection gate pass counts: {counts}"]
    strongest = selection.sort_values(
        [
            "full_mean_absolute_error_seconds",
            "full_common_mean_absolute_error_seconds",
            "formulation",
            "candidate_id",
        ],
        kind="stable",
    ).head(5)
    for rank, row in enumerate(strongest.itertuples(index=False), start=1):
        failed = [column for column in gate_columns if not bool(getattr(row, column))]
        messages.append(
            f"Rejected candidate {rank}: {row.formulation}/"
            f"{row.candidate_id} "
            f"pooled_MAE={row.full_mean_absolute_error_seconds:.6f}s "
            "common_MAE="
            f"{row.full_common_mean_absolute_error_seconds:.6f}s "
            f"ablated_MAE={row.ablated_common_mean_absolute_error_seconds:.6f}s "
            f"coverage={row.coverage_rate:.6f} "
            f"failed={','.join(failed) or 'none'}"
        )
    return tuple(messages)
