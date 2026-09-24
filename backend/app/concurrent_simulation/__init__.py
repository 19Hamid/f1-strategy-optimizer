"""Paired uncertainty scenarios and concurrent race simulation."""

from app.concurrent_simulation.calibration import (
    UNCERTAINTY_CALIBRATION_METHOD_ID,
    PitLossRangeObservation,
    ReplayLapErrorObservation,
    UncertaintyCalibration,
    calibrate_uncertainty,
)
from app.concurrent_simulation.contracts import (
    CONCURRENT_SIMULATION_CONTRACT_VERSION,
    DEFAULT_SCENARIO_COUNT,
    MAXIMUM_SCENARIO_COUNT,
    SCENARIO_GENERATOR_ID,
    ConcurrentSimulationContractError,
    ScenarioBatch,
    ScenarioBatchRequest,
    UncertaintyScenario,
    validate_concurrent_simulation_contract,
)
from app.concurrent_simulation.rollout import (
    MINIMUM_REALIZED_LAP_TIME_SECONDS,
    PairedScenarioRollout,
    StochasticActionRollout,
    StochasticLap,
    rollout_paired_scenario,
)
from app.concurrent_simulation.scenarios import generate_scenario_batch

__all__ = (
    "CONCURRENT_SIMULATION_CONTRACT_VERSION",
    "DEFAULT_SCENARIO_COUNT",
    "MAXIMUM_SCENARIO_COUNT",
    "MINIMUM_REALIZED_LAP_TIME_SECONDS",
    "SCENARIO_GENERATOR_ID",
    "UNCERTAINTY_CALIBRATION_METHOD_ID",
    "ConcurrentSimulationContractError",
    "PairedScenarioRollout",
    "PitLossRangeObservation",
    "ReplayLapErrorObservation",
    "ScenarioBatch",
    "ScenarioBatchRequest",
    "StochasticActionRollout",
    "StochasticLap",
    "UncertaintyCalibration",
    "UncertaintyScenario",
    "calibrate_uncertainty",
    "generate_scenario_batch",
    "rollout_paired_scenario",
    "validate_concurrent_simulation_contract",
)
