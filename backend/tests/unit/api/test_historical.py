"""Historical analysis selection never crosses the protected data boundary."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from app.api import historical
from app.api.historical import (
    AnalysisSelectionError,
    HistoricalDecisionKey,
    load_verified_historical_analysis,
)
from app.concurrent_simulation.calibration import (
    UNCERTAINTY_CALIBRATION_METHOD_ID,
)


def _key() -> HistoricalDecisionKey:
    return HistoricalDecisionKey(2024, "2024-04-R", "HAM", 38, "MEDIUM")


def _phase9_row() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "calibration_id": "phase-9-audit-calibration",
                "calibration_method_id": UNCERTAINTY_CALIBRATION_METHOD_ID,
                "calibration_training_seasons_json": "[2022, 2023, 2024]",
                "shared_pace_scale_seconds": 0.439048,
                "pit_loss_scale_seconds": 5.0,
                "lap_time_residual_scale_seconds": 3.523793,
                "calibration_replay_count": 102,
                "calibration_lap_count": 1375,
                "calibration_pit_loss_profile_count": 68,
                "calibration_evidence": "verified development replay errors",
            }
        ]
    )


def test_protected_season_is_rejected_before_storage_access() -> None:
    with pytest.raises(AnalysisSelectionError, match="development seasons"):
        HistoricalDecisionKey(2025, "2025-04-R", "HAM", 38, "MEDIUM")


def test_selected_decision_must_exist_in_verified_phase8_report(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    key = _key()
    monkeypatch.setattr(
        historical,
        "verify_development_evidence_bundle",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        historical,
        "_load_catalog",
        lambda *args, **kwargs: pd.DataFrame([{"event_name": "Japanese Grand Prix"}]),
    )
    monkeypatch.setattr(historical, "_reconcile_catalogs", lambda *args: None)
    monkeypatch.setattr(historical, "_session_keys", lambda catalog: (key.session_key,))
    monkeypatch.setattr(
        historical,
        "verify_complete_dataset",
        lambda *args: SimpleNamespace(is_valid=True),
    )
    monkeypatch.setattr(
        historical,
        "read_parquet_table",
        lambda path: pd.DataFrame(
            [
                {
                    "season": 2024,
                    "session_id": "2024-04-R",
                    "driver": "HAM",
                    "decision_lap": 38,
                    "target_compound": "HARD",
                }
            ]
        ),
    )
    with pytest.raises(AnalysisSelectionError, match="Phase 8 candidate"):
        load_verified_historical_analysis(
            key,
            datasets_root=tmp_path / "datasets",
            processed_root=tmp_path / "processed",
            artifacts_root=tmp_path / "artifacts",
        )


def test_matching_decision_uses_verified_source_and_stored_calibration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    key = _key()
    request, context = object(), object()
    report = _phase9_row()
    monkeypatch.setattr(
        historical,
        "verify_development_evidence_bundle",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        historical,
        "_load_catalog",
        lambda *args, **kwargs: pd.DataFrame([{"event_name": "Japanese Grand Prix"}]),
    )
    monkeypatch.setattr(historical, "_reconcile_catalogs", lambda *args: None)
    monkeypatch.setattr(historical, "_session_keys", lambda catalog: (key.session_key,))
    monkeypatch.setattr(
        historical,
        "verify_complete_dataset",
        lambda *args: SimpleNamespace(is_valid=True),
    )
    monkeypatch.setattr(
        historical,
        "verify_processed_partition",
        lambda *args: SimpleNamespace(is_valid=True),
    )
    monkeypatch.setattr(historical, "_pit_loss_registry", lambda catalog: object())
    monkeypatch.setattr(
        historical,
        "build_session_optimizer_audit_candidates",
        lambda **kwargs: (
            SimpleNamespace(
                decision_key=key.identity,
                request=request,
                context=context,
            ),
        ),
    )
    monkeypatch.setattr(historical, "sha256_file", lambda path: "catalog-digest")
    monkeypatch.setattr(
        historical.Phase6ModelAdapter,
        "from_paths",
        lambda paths: SimpleNamespace(
            artifact=SimpleNamespace(
                provenance=SimpleNamespace(dataset_build_identifier="catalog-digest")
            )
        ),
    )

    def read_table(path):
        if path.name == "decisions.parquet":
            return pd.DataFrame(
                [
                    dict(
                        zip(
                            (
                                "season",
                                "session_id",
                                "driver",
                                "decision_lap",
                                "target_compound",
                            ),
                            key.identity,
                            strict=True,
                        )
                    )
                ]
            )
        if path.name == "decision.parquet":
            return report
        return pd.DataFrame()

    monkeypatch.setattr(historical, "read_parquet_table", read_table)
    result = load_verified_historical_analysis(
        key,
        datasets_root=tmp_path / "datasets",
        processed_root=tmp_path / "processed",
        artifacts_root=tmp_path / "artifacts",
    )

    assert result.decision is request
    assert result.context is context
    assert result.calibration.training_seasons == (2022, 2023, 2024)
    assert result.calibration.shared_pace_scale_seconds == pytest.approx(0.439048)
