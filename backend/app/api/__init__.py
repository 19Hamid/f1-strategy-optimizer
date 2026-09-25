"""Versioned REST API for the controlled F1 strategy system."""

from app.api.contracts import (
    API_CONTRACT_VERSION,
    API_PREFIX,
    ApiContractError,
    validate_api_contract,
)
from app.api.schemas import (
    ApiCapabilitiesResponse,
    HealthResponse,
    ScenarioLimitsResponse,
    build_api_capabilities_response,
)

__all__ = [
    "API_CONTRACT_VERSION",
    "API_PREFIX",
    "ApiCapabilitiesResponse",
    "ApiContractError",
    "HealthResponse",
    "ScenarioLimitsResponse",
    "build_api_capabilities_response",
    "validate_api_contract",
]
