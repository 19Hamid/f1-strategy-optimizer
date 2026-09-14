"""Reconcile the complete development database with frozen Phase 4 totals."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.datasets import (
    DATASET_CONTRACT_VERSION,
    EXPECTED_DEVELOPMENT_TOTALS,
    EXPECTED_SEASON_TOTALS,
)
from app.db.decision_labels import DecisionLabel
from app.db.decision_rows import DecisionRow
from app.db.pit_duration_observations import PitDurationObservation
from app.db.provenance import DatasetSession
from app.db.reference import RaceSession
from app.db.temporal_splits import SessionSplitAssignment

_EXPECTED = EXPECTED_DEVELOPMENT_TOTALS
EXPECTED_DATABASE_TOTALS: Final[dict[str, int]] = {
    "sessions": _EXPECTED.sessions,
    "season_2022_sessions": EXPECTED_SEASON_TOTALS[0].sessions,
    "season_2023_sessions": EXPECTED_SEASON_TOTALS[1].sessions,
    "season_2024_sessions": EXPECTED_SEASON_TOTALS[2].sessions,
    "decision_rows": _EXPECTED.candidate_decisions,
    "decision_labels": _EXPECTED.candidate_decisions,
    "eligible_decisions": _EXPECTED.eligible_decisions,
    "ineligible_decisions": _EXPECTED.ineligible_decisions,
    "eligible_pit_now": _EXPECTED.eligible_pit_now,
    "eligible_stay_out": _EXPECTED.eligible_stay_out,
    "eligible_lap_targets": _EXPECTED.eligible_lap_targets,
    "pit_duration_observations": _EXPECTED.pit_duration_observations,
    "eligible_pit_duration_targets": _EXPECTED.eligible_pit_duration_targets,
    "split_assignments": _EXPECTED.split_rows,
    "future_weather_matches": 0,
    "protected_evaluation_rows": 0,
}


class DatabaseReconciliationError(RuntimeError):
    """Raised when PostgreSQL differs from authoritative dataset totals."""


@dataclass(frozen=True, slots=True)
class DatabaseReconciliationReport:
    """Contain frozen expectations and observed PostgreSQL totals."""

    dataset_contract_version: str
    expected: dict[str, int]
    actual: dict[str, int]

    @property
    def differences(self) -> dict[str, tuple[int, int]]:
        """Return fields whose expected and actual values differ."""
        return {
            field: (expected, self.actual.get(field, -1))
            for field, expected in self.expected.items()
            if self.actual.get(field) != expected
        }

    @property
    def is_valid(self) -> bool:
        """Return whether every frozen total reconciles exactly."""
        return not self.differences

    def raise_for_errors(self) -> None:
        """Fail closed with all mismatched fields."""
        if self.is_valid:
            return
        detail = ", ".join(
            f"{field}=expected:{expected}/actual:{actual}"
            for field, (expected, actual) in sorted(self.differences.items())
        )
        raise DatabaseReconciliationError(
            f"development database reconciliation failed: {detail}"
        )


def reconcile_development_database(
    session: Session,
    *,
    dataset_contract_version: str = DATASET_CONTRACT_VERSION,
) -> DatabaseReconciliationReport:
    """Compare physical PostgreSQL rows with the frozen development contract."""
    if not isinstance(session, Session):
        raise TypeError("session must be a SQLAlchemy Session")
    if (
        not isinstance(dataset_contract_version, str)
        or not dataset_contract_version
        or dataset_contract_version != dataset_contract_version.strip()
    ):
        raise DatabaseReconciliationError(
            "dataset_contract_version must be non-blank canonical text"
        )

    report = DatabaseReconciliationReport(
        dataset_contract_version=dataset_contract_version,
        expected=dict(EXPECTED_DATABASE_TOTALS),
        actual=_database_totals(
            session,
            dataset_contract_version=dataset_contract_version,
        ),
    )
    report.raise_for_errors()
    return report


def _count(session: Session, statement: object) -> int:
    """Execute one scalar count as a non-negative integer."""
    value = session.scalar(statement)
    if value is None:
        raise DatabaseReconciliationError("database count returned NULL")
    return int(value)


def _database_totals(
    session: Session,
    *,
    dataset_contract_version: str,
) -> dict[str, int]:
    """Read every required total from physical database rows."""
    version = dataset_contract_version
    decision_scope = DecisionRow.dataset_contract_version == version
    label_scope = DecisionLabel.dataset_contract_version == version
    pit_scope = PitDurationObservation.dataset_contract_version == version
    session_scope = DatasetSession.dataset_contract_version == version
    split_scope = SessionSplitAssignment.dataset_contract_version == version

    session_join = DatasetSession.__table__.join(
        RaceSession.__table__,
        DatasetSession.session_id == RaceSession.session_id,
    )
    decision_label_join = DecisionRow.__table__.join(
        DecisionLabel.__table__,
        (
            DecisionRow.dataset_contract_version
            == DecisionLabel.dataset_contract_version
        )
        & (DecisionRow.decision_id == DecisionLabel.decision_id),
    )

    totals = {
        "sessions": _count(
            session,
            select(func.count()).select_from(DatasetSession).where(session_scope),
        ),
        "decision_rows": _count(
            session,
            select(func.count()).select_from(DecisionRow).where(decision_scope),
        ),
        "decision_labels": _count(
            session,
            select(func.count()).select_from(DecisionLabel).where(label_scope),
        ),
        "eligible_decisions": _count(
            session,
            select(func.count()).select_from(DecisionRow).where(
                decision_scope,
                DecisionRow.is_decision_eligible.is_(True),
            ),
        ),
        "ineligible_decisions": _count(
            session,
            select(func.count()).select_from(DecisionRow).where(
                decision_scope,
                DecisionRow.is_decision_eligible.is_(False),
            ),
        ),
        "eligible_lap_targets": _count(
            session,
            select(func.count()).select_from(DecisionLabel).where(
                label_scope,
                DecisionLabel.is_lap_time_target_eligible.is_(True),
            ),
        ),
        "pit_duration_observations": _count(
            session,
            select(func.count()).select_from(PitDurationObservation).where(
                pit_scope
            ),
        ),
        "eligible_pit_duration_targets": _count(
            session,
            select(func.count()).select_from(PitDurationObservation).where(
                pit_scope,
                PitDurationObservation.is_pit_duration_target_eligible.is_(True),
            ),
        ),
        "split_assignments": _count(
            session,
            select(func.count()).select_from(SessionSplitAssignment).where(
                split_scope
            ),
        ),
        "future_weather_matches": _count(
            session,
            select(func.count()).select_from(DecisionRow).where(
                decision_scope,
                DecisionRow.weather_observation_time_seconds
                > DecisionRow.decision_time_seconds,
            ),
        ),
        "protected_evaluation_rows": _count(
            session,
            select(func.count()).select_from(session_join).where(
                session_scope,
                RaceSession.season == 2025,
            ),
        ),
    }

    for season_total in EXPECTED_SEASON_TOTALS:
        totals[f"season_{season_total.season}_sessions"] = _count(
            session,
            select(func.count()).select_from(session_join).where(
                session_scope,
                RaceSession.season == season_total.season,
            ),
        )

    for action, field in (
        ("PIT_NOW", "eligible_pit_now"),
        ("STAY_OUT", "eligible_stay_out"),
    ):
        totals[field] = _count(
            session,
            select(func.count()).select_from(decision_label_join).where(
                decision_scope,
                DecisionRow.is_decision_eligible.is_(True),
                DecisionLabel.historical_action == action,
            ),
        )

    return totals
