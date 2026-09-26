"""Reconstruct one verified development decision for on-demand analysis."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pandas as pd

from app.api.evidence import (
    DEFAULT_ARTIFACTS_ROOT,
    DEFAULT_CONCURRENT_SIMULATION_RUN_ID,
    DEFAULT_MODEL_ARTIFACT_ID,
    DEFAULT_OPTIMIZER_RUN_ID,
    PROJECT_ROOT,
    ApiEvidenceError,
    verify_development_evidence_bundle,
)
from app.cleaning.integrity import verify_processed_partition
from app.cleaning.paths import ProcessedDataPaths
from app.concurrent_simulation.calibration import UncertaintyCalibration
from app.concurrent_simulation.storage import ConcurrentSimulationReportPaths
from app.datasets.contracts import DEVELOPMENT_SEASONS
from app.datasets.integrity import verify_complete_dataset
from app.datasets.paths import DatasetPaths
from app.ml import ModelArtifactPaths
from app.optimizer.audit import (
    _load_catalog,
    _pit_loss_registry,
    _reconcile_catalogs,
    _session_keys,
    build_session_optimizer_audit_candidates,
)
from app.optimizer.contracts import PitDecisionRequest
from app.optimizer.storage import OptimizerReportPaths
from app.pipeline import SessionKey
from app.pipeline.serialization import read_parquet_table, sha256_file
from app.simulation import (
    DryCompound,
    Phase6ModelAdapter,
    SimulationFeatureContext,
)

DEFAULT_DATASETS_ROOT: Final = PROJECT_ROOT / "data" / "datasets"
DEFAULT_PROCESSED_ROOT: Final = PROJECT_ROOT / "data" / "processed" / "fastf1"
_SESSION_PATTERN: Final = re.compile(r"^(20\d{2})-(\d{2})-R$")


class AnalysisSelectionError(ValueError):
    """The requested decision is outside the verified development population."""


@dataclass(frozen=True, slots=True)
class HistoricalDecisionKey:
    """Exact identity of a recorded Phase 8 development decision."""

    season: int
    session_id: str
    driver: str
    decision_lap: int
    target_compound: DryCompound

    def __post_init__(self) -> None:
        if (
            isinstance(self.season, bool)
            or not isinstance(self.season, int)
            or self.season not in DEVELOPMENT_SEASONS
        ):
            raise AnalysisSelectionError("only development seasons are supported")
        match = (
            _SESSION_PATTERN.fullmatch(self.session_id)
            if isinstance(self.session_id, str)
            else None
        )
        if match is None or int(match.group(1)) != self.season:
            raise AnalysisSelectionError("session identity differs from season")
        if (
            not isinstance(self.driver, str)
            or re.fullmatch(r"[A-Z]{3}", self.driver) is None
        ):
            raise AnalysisSelectionError("driver must be a three-letter code")
        if (
            isinstance(self.decision_lap, bool)
            or not isinstance(self.decision_lap, int)
            or self.decision_lap < 1
        ):
            raise AnalysisSelectionError("decision_lap must be positive")
        try:
            compound = DryCompound(self.target_compound)
        except (TypeError, ValueError) as error:
            raise AnalysisSelectionError("unsupported target compound") from error
        object.__setattr__(self, "target_compound", compound)

    @property
    def session_key(self) -> SessionKey:
        match = _SESSION_PATTERN.fullmatch(self.session_id)
        assert match is not None  # already validated at construction
        return SessionKey(self.season, int(match.group(2)), "R")

    @property
    def identity(self) -> tuple[int, str, str, int, str]:
        return (
            self.season,
            self.session_id,
            self.driver,
            self.decision_lap,
            self.target_compound.value,
        )


@dataclass(frozen=True, slots=True)
class VerifiedHistoricalAnalysis:
    """Trusted model, decision seed and development-only uncertainty scales."""

    decision: PitDecisionRequest
    context: SimulationFeatureContext
    adapter: Phase6ModelAdapter
    calibration: UncertaintyCalibration


def load_verified_historical_analysis(
    key: HistoricalDecisionKey,
    *,
    datasets_root: Path = DEFAULT_DATASETS_ROOT,
    processed_root: Path = DEFAULT_PROCESSED_ROOT,
    artifacts_root: Path = DEFAULT_ARTIFACTS_ROOT,
) -> VerifiedHistoricalAnalysis:
    """Load only a Phase 8 decision after verifying source and report identity."""
    if not isinstance(key, HistoricalDecisionKey):
        raise TypeError("key must be a HistoricalDecisionKey")
    dataset_paths = DatasetPaths(Path(datasets_root))
    processed_paths = ProcessedDataPaths(Path(processed_root))
    root = Path(artifacts_root)
    verify_development_evidence_bundle(artifacts_root=root)

    try:
        dataset_catalog = _load_catalog(
            dataset_paths.catalog,
            protected_root=dataset_paths.version_root / "season=2025",
            source="dataset",
        )
        processed_catalog = _load_catalog(
            processed_paths.catalog,
            protected_root=processed_paths.version_root / "season=2025",
            source="processed",
        )
        _reconcile_catalogs(dataset_catalog, processed_catalog)
        session_keys = _session_keys(dataset_catalog)
        integrity = verify_complete_dataset(dataset_paths, session_keys)
        if not integrity.is_valid:
            raise ApiEvidenceError("development dataset integrity failed")
        if key.session_key not in session_keys:
            raise AnalysisSelectionError("decision session is not in development")

        optimizer_paths = OptimizerReportPaths(root, DEFAULT_OPTIMIZER_RUN_ID)
        stored = read_parquet_table(optimizer_paths.root / "decisions.parquet")
        fields = key.identity
        columns = (
            "season",
            "session_id",
            "driver",
            "decision_lap",
            "target_compound",
        )
        if not set(columns).issubset(stored.columns):
            raise ApiEvidenceError("verified Phase 8 decision schema is incomplete")
        mask = pd.Series(True, index=stored.index)
        for name, value in zip(columns, fields, strict=True):
            mask &= stored[name].eq(value)
        matches = stored.loc[mask]
        if len(matches) != 1:
            raise AnalysisSelectionError("decision is not a unique Phase 8 candidate")

        processed_integrity = verify_processed_partition(
            processed_paths, key.session_key
        )
        if not processed_integrity.is_valid:
            raise ApiEvidenceError("selected processed race integrity failed")
        decision_rows = read_parquet_table(
            dataset_paths.for_session(key.session_key).decision_rows
        )
        processed_laps = read_parquet_table(
            processed_paths.for_session(key.session_key).laps
        )
        candidates = build_session_optimizer_audit_candidates(
            session_key=key.session_key,
            decision_rows=decision_rows,
            processed_laps=processed_laps,
            pit_loss_registry=_pit_loss_registry(processed_catalog),
        )
        selected = [item for item in candidates if item.decision_key == key.identity]
        if len(selected) != 1:
            raise ApiEvidenceError("historical decision cannot be reconstructed")

        adapter = Phase6ModelAdapter.from_paths(
            ModelArtifactPaths(root, DEFAULT_MODEL_ARTIFACT_ID)
        )
        if adapter.artifact.provenance.dataset_build_identifier != sha256_file(
            dataset_paths.catalog
        ):
            raise ApiEvidenceError("model and decision datasets differ")
        report_paths = ConcurrentSimulationReportPaths(
            root, DEFAULT_CONCURRENT_SIMULATION_RUN_ID
        )
        report = read_parquet_table(report_paths.root / "decision.parquet")
        if len(report) != 1:
            raise ApiEvidenceError("verified Phase 9 calibration is ambiguous")
        calibration = _stored_calibration(report.iloc[0])
        return VerifiedHistoricalAnalysis(
            decision=selected[0].request,
            context=selected[0].context,
            adapter=adapter,
            calibration=calibration,
        )
    except AnalysisSelectionError:
        raise
    except ApiEvidenceError:
        raise
    except Exception as error:
        raise ApiEvidenceError(
            "historical analysis inputs could not be verified"
        ) from error


def _stored_calibration(row: pd.Series) -> UncertaintyCalibration:
    """Rebuild the exact calibration recorded in the verified Phase 9 report."""
    seasons = json.loads(str(row["calibration_training_seasons_json"]))
    if seasons != list(DEVELOPMENT_SEASONS):
        raise ApiEvidenceError("stored calibration includes an invalid season")
    return UncertaintyCalibration(
        calibration_id=str(row["calibration_id"]),
        method_id=str(row["calibration_method_id"]),
        training_seasons=tuple(seasons),
        shared_pace_scale_seconds=float(row["shared_pace_scale_seconds"]),
        pit_loss_scale_seconds=float(row["pit_loss_scale_seconds"]),
        lap_time_residual_scale_seconds=float(
            row["lap_time_residual_scale_seconds"]
        ),
        replay_count=int(row["calibration_replay_count"]),
        lap_count=int(row["calibration_lap_count"]),
        pit_loss_profile_count=int(row["calibration_pit_loss_profile_count"]),
        evidence=str(row["calibration_evidence"]),
    )
