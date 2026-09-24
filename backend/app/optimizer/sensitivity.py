"""Controlled Phase 8 pit-loss and tyre-age decision sensitivity."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Final

from app.optimizer.comparison import (
    PitDecisionComparison,
    compare_pit_decision,
)
from app.optimizer.contracts import OptimizerContractError, PitDecisionRequest
from app.simulation import (
    Phase6ModelAdapter,
    PitLossRegistry,
    PitLossResolution,
    PitLossScenario,
    SimulationFeatureContext,
)

TYRE_AGE_SENSITIVITY_DELTA_LAPS: Final = 2


class TyreAgeSensitivityScenario(StrEnum):
    """Controlled current-stint exposure around the observed decision state."""

    YOUNGER = "YOUNGER"
    NOMINAL = "NOMINAL"
    OLDER = "OLDER"


@dataclass(frozen=True, slots=True)
class PitDecisionSensitivityCase:
    """One reconciled cell in the canonical three-by-three sensitivity grid."""

    tyre_age_scenario: TyreAgeSensitivityScenario
    tyre_age_delta_laps: int
    pit_loss_resolution: PitLossResolution
    comparison: PitDecisionComparison

    def __post_init__(self) -> None:
        """Require canonical axes and matching comparison evidence."""
        scenario = _tyre_age_scenario(self.tyre_age_scenario)
        if self.tyre_age_delta_laps != _tyre_age_delta(scenario):
            raise OptimizerContractError(
                "tyre-age delta differs from the declared sensitivity scenario"
            )
        if not isinstance(self.pit_loss_resolution, PitLossResolution):
            raise TypeError("pit_loss_resolution must be a PitLossResolution")
        if not isinstance(self.comparison, PitDecisionComparison):
            raise TypeError("comparison must be a PitDecisionComparison")
        request = self.comparison.request
        resolution = self.pit_loss_resolution
        if request.pit_loss != resolution.assumption:
            raise OptimizerContractError(
                "comparison pit loss differs from its sensitivity resolution"
            )
        if request.state.event_name.casefold() != resolution.event_name.casefold():
            raise OptimizerContractError(
                "comparison event differs from its pit-loss resolution"
            )
        object.__setattr__(self, "tyre_age_scenario", scenario)


@dataclass(frozen=True, slots=True)
class PitDecisionSensitivity:
    """Complete deterministic sensitivity grid for one base decision."""

    base_request: PitDecisionRequest
    cases: tuple[PitDecisionSensitivityCase, ...]

    def __post_init__(self) -> None:
        """Prove complete canonical coverage and shared decision identity."""
        if not isinstance(self.base_request, PitDecisionRequest):
            raise TypeError("base_request must be a PitDecisionRequest")
        if not isinstance(self.cases, tuple):
            raise OptimizerContractError("sensitivity cases must be a tuple")
        if any(
            not isinstance(case, PitDecisionSensitivityCase)
            for case in self.cases
        ):
            raise OptimizerContractError(
                "every sensitivity case must be a PitDecisionSensitivityCase"
            )
        expected_identities = tuple(
            (tyre_age, pit_loss)
            for tyre_age in TyreAgeSensitivityScenario
            for pit_loss in PitLossScenario
        )
        actual_identities = tuple(
            (
                case.tyre_age_scenario,
                case.pit_loss_resolution.scenario,
            )
            for case in self.cases
        )
        if actual_identities != expected_identities:
            raise OptimizerContractError(
                "sensitivity grid must contain the canonical nine cases"
            )
        for case in self.cases:
            request = case.comparison.request
            delta = case.tyre_age_delta_laps
            expected_state = replace(
                self.base_request.state,
                tyre_age_laps=self.base_request.state.tyre_age_laps + delta,
                current_stint_laps_completed=(
                    self.base_request.state.current_stint_laps_completed + delta
                ),
            )
            if request.state != expected_state:
                raise OptimizerContractError(
                    "sensitivity case changed more than current tyre exposure"
                )
            if request.target_compound is not self.base_request.target_compound:
                raise OptimizerContractError(
                    "sensitivity case changed the target compound"
                )
            if request.random_seed != self.base_request.random_seed:
                raise OptimizerContractError(
                    "sensitivity case changed the random seed"
                )

    @property
    def nominal(self) -> PitDecisionComparison:
        """Return the observed tyre state with nominal circuit pit loss."""
        return self.case_for(
            tyre_age_scenario=TyreAgeSensitivityScenario.NOMINAL,
            pit_loss_scenario=PitLossScenario.NOMINAL,
        ).comparison

    @property
    def pit_now_advantage_range_seconds(self) -> tuple[float, float]:
        """Return the minimum and maximum advantage across all nine cases."""
        advantages = tuple(
            case.comparison.pit_now_advantage_seconds for case in self.cases
        )
        return min(advantages), max(advantages)

    def case_for(
        self,
        *,
        tyre_age_scenario: TyreAgeSensitivityScenario | str,
        pit_loss_scenario: PitLossScenario | str,
    ) -> PitDecisionSensitivityCase:
        """Return one exact sensitivity cell without a silent fallback."""
        tyre_age = _tyre_age_scenario(tyre_age_scenario)
        try:
            pit_loss = PitLossScenario(pit_loss_scenario)
        except (TypeError, ValueError) as error:
            raise OptimizerContractError(
                f"unsupported pit-loss sensitivity scenario: "
                f"{pit_loss_scenario!r}"
            ) from error
        return next(
            case
            for case in self.cases
            if case.tyre_age_scenario is tyre_age
            and case.pit_loss_resolution.scenario is pit_loss
        )


def analyze_pit_decision_sensitivity(
    request: PitDecisionRequest,
    *,
    context: SimulationFeatureContext,
    adapter: Phase6ModelAdapter,
    pit_loss_registry: PitLossRegistry,
) -> PitDecisionSensitivity:
    """Evaluate the canonical pit-loss and current-tyre-exposure grid."""
    if not isinstance(request, PitDecisionRequest):
        raise TypeError("request must be a PitDecisionRequest")
    if not isinstance(context, SimulationFeatureContext):
        raise TypeError("context must be a SimulationFeatureContext")
    if not isinstance(adapter, Phase6ModelAdapter):
        raise TypeError("adapter must be a Phase6ModelAdapter")
    if not isinstance(pit_loss_registry, PitLossRegistry):
        raise TypeError("pit_loss_registry must be a PitLossRegistry")
    if context.simulated_lap_times_seconds:
        raise OptimizerContractError(
            "sensitivity context must start before any simulated laps"
        )
    _validate_base_feature_identity(request, context)
    minimum_age = TYRE_AGE_SENSITIVITY_DELTA_LAPS
    if (
        request.state.tyre_age_laps < minimum_age
        or request.state.current_stint_laps_completed < minimum_age
    ):
        raise OptimizerContractError(
            "full tyre-age sensitivity requires at least two completed "
            "laps on the current tyre and stint"
        )

    resolutions = tuple(
        pit_loss_registry.resolve(
            event_name=request.state.event_name,
            scenario=scenario,
        )
        for scenario in PitLossScenario
    )
    cases: list[PitDecisionSensitivityCase] = []
    for tyre_age_scenario in TyreAgeSensitivityScenario:
        aged_request, aged_context = _with_tyre_age_scenario(
            request,
            context,
            tyre_age_scenario,
        )
        for resolution in resolutions:
            scenario_request = replace(
                aged_request,
                pit_loss=resolution.assumption,
            )
            cases.append(
                PitDecisionSensitivityCase(
                    tyre_age_scenario=tyre_age_scenario,
                    tyre_age_delta_laps=_tyre_age_delta(tyre_age_scenario),
                    pit_loss_resolution=resolution,
                    comparison=compare_pit_decision(
                        scenario_request,
                        context=aged_context,
                        adapter=adapter,
                    ),
                )
            )
    return PitDecisionSensitivity(
        base_request=request,
        cases=tuple(cases),
    )


def _with_tyre_age_scenario(
    request: PitDecisionRequest,
    context: SimulationFeatureContext,
    scenario: TyreAgeSensitivityScenario,
) -> tuple[PitDecisionRequest, SimulationFeatureContext]:
    delta = _tyre_age_delta(scenario)
    state = replace(
        request.state,
        tyre_age_laps=request.state.tyre_age_laps + delta,
        current_stint_laps_completed=(
            request.state.current_stint_laps_completed + delta
        ),
    )
    features = context.base_features.copy(deep=True)
    row = features.index[0]
    features.at[row, "tyre_age_laps"] = state.tyre_age_laps
    features.at[row, "current_stint_laps_completed"] = (
        state.current_stint_laps_completed
    )
    return (
        replace(request, state=state),
        replace(context, base_features=features),
    )


def _validate_base_feature_identity(
    request: PitDecisionRequest,
    context: SimulationFeatureContext,
) -> None:
    row = context.base_features.iloc[0]
    identities = (
        ("event_name", row["event_name"], request.state.event_name),
        ("driver", row["driver"], request.state.driver),
        ("team", row["team"], request.state.team),
        ("decision_lap", row["decision_lap"], request.state.current_lap),
        (
            "current_compound",
            row["current_compound"],
            request.state.current_compound.value,
        ),
        ("tyre_age_laps", row["tyre_age_laps"], request.state.tyre_age_laps),
        (
            "current_stint_laps_completed",
            row["current_stint_laps_completed"],
            request.state.current_stint_laps_completed,
        ),
    )
    mismatches = [
        name for name, actual, expected in identities if actual != expected
    ]
    if mismatches:
        raise OptimizerContractError(
            "sensitivity feature seed differs from request state: "
            + ", ".join(mismatches)
        )


def _tyre_age_scenario(value: object) -> TyreAgeSensitivityScenario:
    try:
        return TyreAgeSensitivityScenario(value)
    except (TypeError, ValueError) as error:
        raise OptimizerContractError(
            f"unsupported tyre-age sensitivity scenario: {value!r}"
        ) from error


def _tyre_age_delta(scenario: TyreAgeSensitivityScenario) -> int:
    return {
        TyreAgeSensitivityScenario.YOUNGER: (
            -TYRE_AGE_SENSITIVITY_DELTA_LAPS
        ),
        TyreAgeSensitivityScenario.NOMINAL: 0,
        TyreAgeSensitivityScenario.OLDER: TYRE_AGE_SENSITIVITY_DELTA_LAPS,
    }[scenario]
