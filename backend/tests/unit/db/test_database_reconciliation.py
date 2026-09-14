"""Tests for complete development-database reconciliation."""

import pytest
from sqlalchemy.orm import Session

from app.db import reconciliation
from app.db.reconciliation import (
    EXPECTED_DATABASE_TOTALS,
    DatabaseReconciliationError,
    DatabaseReconciliationReport,
    reconcile_development_database,
)


def test_frozen_database_totals_match_phase_four_contract() -> None:
    """Keep the database audit tied to the published real-data contract."""
    assert EXPECTED_DATABASE_TOTALS == {
        "sessions": 68,
        "season_2022_sessions": 22,
        "season_2023_sessions": 22,
        "season_2024_sessions": 24,
        "decision_rows": 73_251,
        "decision_labels": 73_251,
        "eligible_decisions": 55_943,
        "ineligible_decisions": 17_308,
        "eligible_pit_now": 1_776,
        "eligible_stay_out": 54_167,
        "eligible_lap_targets": 52_483,
        "pit_duration_observations": 2_693,
        "eligible_pit_duration_targets": 1_465,
        "split_assignments": 204,
        "future_weather_matches": 0,
        "protected_evaluation_rows": 0,
    }


def test_report_exposes_every_difference_and_fails_closed() -> None:
    """Report all drift rather than stopping at the first mismatched total."""
    actual = dict(EXPECTED_DATABASE_TOTALS)
    actual["sessions"] = 67
    actual["future_weather_matches"] = 1
    report = DatabaseReconciliationReport(
        dataset_contract_version="1.0",
        expected=dict(EXPECTED_DATABASE_TOTALS),
        actual=actual,
    )

    assert report.is_valid is False
    assert report.differences == {
        "sessions": (68, 67),
        "future_weather_matches": (0, 1),
    }
    with pytest.raises(
        DatabaseReconciliationError,
        match="future_weather_matches=expected:0/actual:1",
    ):
        report.raise_for_errors()


def test_complete_reconciliation_accepts_exact_database_totals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Return auditable evidence only when every physical count matches."""
    monkeypatch.setattr(
        reconciliation,
        "_database_totals",
        lambda session, *, dataset_contract_version: dict(
            EXPECTED_DATABASE_TOTALS
        ),
    )

    report = reconcile_development_database(Session())

    assert report.is_valid is True
    assert report.dataset_contract_version == "1.0"


def test_complete_reconciliation_rejects_protected_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Treat one protected 2025 row as a terminal audit failure."""
    actual = dict(EXPECTED_DATABASE_TOTALS)
    actual["protected_evaluation_rows"] = 1
    monkeypatch.setattr(
        reconciliation,
        "_database_totals",
        lambda session, *, dataset_contract_version: actual,
    )

    with pytest.raises(
        DatabaseReconciliationError,
        match="protected_evaluation_rows=expected:0/actual:1",
    ):
        reconcile_development_database(Session())
