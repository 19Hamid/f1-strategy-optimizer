"""Controlled remaining-race strategy simulation."""

from app.simulation.contracts import (
    DEVELOPMENT_SEASONS,
    MINIMUM_DRY_COMPOUNDS_PER_RACE,
    PROTECTED_EVALUATION_SEASON,
    SIMULATION_CONTRACT_VERSION,
    SIMULATION_RANDOM_SEED,
    DryCompound,
    PitLossAssumption,
    PitLossSource,
    PlannedPitStop,
    RaceState,
    SimulationContractError,
    SimulationMode,
    SimulationRequest,
    StrategyPlan,
    validate_simulation_contract,
)
from app.simulation.engine import (
    LapTransition,
    SimulationProgress,
    StateTransitionError,
    advance_one_lap,
    initialize_simulation_progress,
)

__all__ = [
    "DEVELOPMENT_SEASONS",
    "MINIMUM_DRY_COMPOUNDS_PER_RACE",
    "PROTECTED_EVALUATION_SEASON",
    "SIMULATION_CONTRACT_VERSION",
    "SIMULATION_RANDOM_SEED",
    "DryCompound",
    "LapTransition",
    "PitLossAssumption",
    "PitLossSource",
    "PlannedPitStop",
    "RaceState",
    "SimulationContractError",
    "SimulationMode",
    "SimulationProgress",
    "SimulationRequest",
    "StateTransitionError",
    "StrategyPlan",
    "advance_one_lap",
    "initialize_simulation_progress",
    "validate_simulation_contract",
]
