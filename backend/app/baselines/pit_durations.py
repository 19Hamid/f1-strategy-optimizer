"""Training-only Phase 5 pit-lane-duration baselines."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

import numpy as np
import pandas as pd

from app.baselines.contracts import BaselineId, BaselineTask, baseline_spec

PIT_PREDICTION_COLUMNS: Final = (
    "pit_event_id",
    "baseline_id",
    "prediction_seconds",
    "prediction_available",
    "prediction_source",
)


class PitDurationBaselineError(ValueError):
    """Raised when pit-duration baseline input violates its contract."""


@dataclass(frozen=True, slots=True)
class PitDurationBaseline:
    """One fitted training-only pit-lane-duration estimator."""

    baseline_id: BaselineId
    global_median: float
    event_medians: dict[str, float] = field(default_factory=dict)
    transition_medians: dict[tuple[str, str], float] = field(
        default_factory=dict
    )
    event_transition_medians: dict[tuple[str, str, str], float] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        """Require a pit task and usable global fallback."""
        specification = baseline_spec(self.baseline_id)
        if specification.task != BaselineTask.PIT_DURATION:
            raise PitDurationBaselineError(
                f"{self.baseline_id} is not a pit-duration baseline"
            )
        if not _positive_finite(self.global_median):
            raise PitDurationBaselineError(
                "pit-duration baseline requires a positive global median"
            )

    def predict(self, rows: pd.DataFrame) -> pd.DataFrame:
        """Predict held-out events without reading their duration targets."""
        _require_frame(rows, source="prediction rows")
        required = ["pit_event_id"]
        if self.baseline_id != BaselineId.PIT_GLOBAL_MEDIAN:
            required.append("event_name")
        if self.baseline_id == BaselineId.PIT_CIRCUIT_TRANSITION_MEDIAN:
            required.extend(("compound_before", "compound_after"))
        _require_columns(rows, tuple(required), source="prediction rows")
        _require_unique_identity(rows)

        values = np.full(len(rows), self.global_median, dtype=float)
        sources = ["global_median"] * len(rows)
        if self.baseline_id == BaselineId.PIT_CIRCUIT_MEDIAN:
            values, sources = self._event_predictions(rows)
        elif (
            self.baseline_id
            == BaselineId.PIT_CIRCUIT_TRANSITION_MEDIAN
        ):
            values, sources = self._event_transition_predictions(rows)

        return pd.DataFrame(
            {
                "pit_event_id": rows["pit_event_id"].astype("string").array,
                "baseline_id": pd.array(
                    [self.baseline_id.value] * len(rows),
                    dtype="string",
                ),
                "prediction_seconds": pd.array(values, dtype="float64"),
                "prediction_available": pd.array(
                    [True] * len(rows),
                    dtype="boolean",
                ),
                "prediction_source": pd.array(sources, dtype="string"),
            },
            columns=PIT_PREDICTION_COLUMNS,
        )

    def _event_predictions(
        self,
        rows: pd.DataFrame,
    ) -> tuple[np.ndarray, list[str]]:
        """Use training event medians with global fallback."""
        values = np.full(len(rows), self.global_median, dtype=float)
        sources: list[str] = []
        for index, event in enumerate(rows["event_name"]):
            event_key = _text_key(event)
            if event_key is not None and event_key in self.event_medians:
                values[index] = self.event_medians[event_key]
                sources.append("event_median")
            else:
                sources.append("global_median_fallback")
        return values, sources

    def _event_transition_predictions(
        self,
        rows: pd.DataFrame,
    ) -> tuple[np.ndarray, list[str]]:
        """Apply event-transition, event, transition and global hierarchy."""
        values = np.full(len(rows), self.global_median, dtype=float)
        sources: list[str] = []
        source_rows = rows.loc[
            :, ["event_name", "compound_before", "compound_after"]
        ].itertuples(index=False, name=None)
        for index, (event, before, after) in enumerate(source_rows):
            event_key = _text_key(event)
            before_key = _text_key(before)
            after_key = _text_key(after)
            complete = (
                event_key is not None
                and before_key is not None
                and after_key is not None
            )
            event_transition_key = (
                (event_key, before_key, after_key)
                if complete
                else None
            )
            transition_key = (
                (before_key, after_key)
                if before_key is not None and after_key is not None
                else None
            )
            if (
                event_transition_key is not None
                and event_transition_key in self.event_transition_medians
            ):
                values[index] = self.event_transition_medians[
                    event_transition_key
                ]
                sources.append("event_transition_median")
            elif event_key is not None and event_key in self.event_medians:
                values[index] = self.event_medians[event_key]
                sources.append("event_median_fallback")
            elif (
                transition_key is not None
                and transition_key in self.transition_medians
            ):
                values[index] = self.transition_medians[transition_key]
                sources.append("transition_median_fallback")
            else:
                sources.append("global_median_fallback")
        return values, sources


def fit_pit_duration_baseline(
    baseline_id: BaselineId | str,
    training_rows: pd.DataFrame,
) -> PitDurationBaseline:
    """Fit one pit-duration estimator from eligible training events."""
    try:
        normalized = BaselineId(baseline_id)
    except (TypeError, ValueError) as error:
        raise PitDurationBaselineError(
            f"unknown pit-duration baseline: {baseline_id!r}"
        ) from error
    specification = baseline_spec(normalized)
    if specification.task != BaselineTask.PIT_DURATION:
        raise PitDurationBaselineError(
            f"{normalized} is not a pit-duration baseline"
        )
    eligible = _eligible_training_targets(training_rows)
    targets = eligible["pit_duration_target_seconds"]
    global_median = float(targets.median())
    event_medians = _median_mapping(eligible, ["event_name"])
    transition_medians = _median_mapping(
        eligible,
        ["compound_before", "compound_after"],
    )
    event_transition_medians = _median_mapping(
        eligible,
        ["event_name", "compound_before", "compound_after"],
    )
    return PitDurationBaseline(
        baseline_id=normalized,
        global_median=global_median,
        event_medians={
            str(key): value for key, value in event_medians.items()
        },
        transition_medians={
            (str(key[0]), str(key[1])): value
            for key, value in transition_medians.items()
        },
        event_transition_medians={
            (str(key[0]), str(key[1]), str(key[2])): value
            for key, value in event_transition_medians.items()
        },
    )


def _eligible_training_targets(rows: pd.DataFrame) -> pd.DataFrame:
    """Select complete eligible positive training observations."""
    _require_frame(rows, source="training rows")
    required = (
        "event_name",
        "compound_before",
        "compound_after",
        "is_pit_duration_target_eligible",
        "pit_duration_target_seconds",
    )
    _require_columns(rows, required, source="training rows")
    targets = pd.to_numeric(
        rows["pit_duration_target_seconds"],
        errors="coerce",
    )
    mask = (
        rows["is_pit_duration_target_eligible"].eq(True)
        & targets.notna()
        & np.isfinite(targets)
        & targets.gt(0)
        & rows["event_name"].notna()
        & rows["compound_before"].notna()
        & rows["compound_after"].notna()
    )
    eligible = rows.loc[mask, list(required)].copy()
    eligible["pit_duration_target_seconds"] = targets.loc[mask].astype(
        "float64"
    )
    if eligible.empty:
        raise PitDurationBaselineError(
            "training rows contain no eligible positive pit-duration targets"
        )
    return eligible


def _median_mapping(
    rows: pd.DataFrame,
    groups: list[str],
) -> dict[object, float]:
    """Return deterministic medians for one training-only grouping."""
    medians = (
        rows.groupby(groups, observed=True, dropna=False)[
            "pit_duration_target_seconds"
        ]
        .median()
        .to_dict()
    )
    return {key: float(value) for key, value in medians.items()}


def _text_key(value: object) -> str | None:
    """Normalize a grouping key without manufacturing missing text."""
    if pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def _positive_finite(value: object) -> bool:
    """Return whether a scalar is a usable positive duration."""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return False
    return bool(np.isfinite(numeric) and numeric > 0)


def _require_frame(value: object, *, source: str) -> None:
    """Require an explicit DataFrame."""
    if not isinstance(value, pd.DataFrame):
        raise TypeError(f"{source} must be a pandas DataFrame")


def _require_columns(
    rows: pd.DataFrame,
    required: tuple[str, ...],
    *,
    source: str,
) -> None:
    """Require every fit or prediction dependency."""
    missing = sorted(set(required).difference(rows.columns))
    if missing:
        raise PitDurationBaselineError(
            f"{source} missing required columns: {', '.join(missing)}"
        )


def _require_unique_identity(rows: pd.DataFrame) -> None:
    """Require one prediction per non-null pit event."""
    identity = rows["pit_event_id"]
    if identity.isna().any():
        raise PitDurationBaselineError(
            "prediction rows contain null pit_event_id"
        )
    if identity.astype("string").duplicated().any():
        raise PitDurationBaselineError(
            "prediction rows contain duplicate pit_event_id"
        )
