"""Paired uncertainty scenarios and concurrent race simulation."""

from app.concurrent_simulation.aggregation import (
    MINIMUM_STABILITY_SCENARIO_COUNT,
    SCENARIO_INTERVAL_LOWER_QUANTILE,
    SCENARIO_INTERVAL_UPPER_QUANTILE,
    SEQUENTIAL_AGGREGATOR_ID,
    ScenarioDistribution,
    ScenarioOutcome,
    ScenarioPreference,
    SequentialScenarioEvaluation,
    evaluate_scenario_batch_sequentially,
    summarize_scenario_distribution,
)
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
    "MINIMUM_STABILITY_SCENARIO_COUNT",
    "SCENARIO_INTERVAL_LOWER_QUANTILE",
    "SCENARIO_INTERVAL_UPPER_QUANTILE",
    "SEQUENTIAL_AGGREGATOR_ID",
    "SCENARIO_GENERATOR_ID",
    "UNCERTAINTY_CALIBRATION_METHOD_ID",
    "ConcurrentSimulationContractError",
    "PairedScenarioRollout",
    "PitLossRangeObservation",
    "ReplayLapErrorObservation",
    "ScenarioBatch",
    "ScenarioBatchRequest",
    "ScenarioDistribution",
    "ScenarioOutcome",
    "ScenarioPreference",
    "SequentialScenarioEvaluation",
    "StochasticActionRollout",
    "StochasticLap",
    "UncertaintyCalibration",
    "UncertaintyScenario",
    "calibrate_uncertainty",
    "evaluate_scenario_batch_sequentially",
    "generate_scenario_batch",
    "rollout_paired_scenario",
    "summarize_scenario_distribution",
    "validate_concurrent_simulation_contract",
)
