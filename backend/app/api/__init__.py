"""Versioned REST API for the controlled F1 strategy system."""

from app.api.contracts import (
    API_CONTRACT_VERSION,
    API_PREFIX,
    ApiContractError,
    validate_api_contract,
)
from app.api.evidence import (
    DEFAULT_ARTIFACTS_ROOT,
    DEFAULT_CONCURRENT_SIMULATION_RUN_ID,
    DEFAULT_MODEL_ARTIFACT_ID,
    DEFAULT_OPTIMIZER_RUN_ID,
    DEFAULT_SIMULATION_RUN_ID,
    ApiEvidenceError,
    DevelopmentEvidenceBundle,
    EvidenceArtifactKind,
    VerifiedEvidenceArtifact,
    verify_development_evidence_bundle,
)
from app.api.reporting import (
    ConcurrentBenchmarkSummary,
    ConcurrentSimulationSummary,
    load_concurrent_simulation_summary,
)
from app.api.schemas import (
    ApiCapabilitiesResponse,
    ApiErrorResponse,
    ConcurrentBenchmarkResponse,
    ConcurrentSimulationSummaryResponse,
    DevelopmentEvidenceResponse,
    HealthResponse,
    ScenarioLimitsResponse,
    VerifiedEvidenceArtifactResponse,
    build_api_capabilities_response,
    build_concurrent_simulation_summary_response,
    build_development_evidence_response,
)

__all__ = [
    "API_CONTRACT_VERSION",
    "API_PREFIX",
    "DEFAULT_ARTIFACTS_ROOT",
    "DEFAULT_CONCURRENT_SIMULATION_RUN_ID",
    "DEFAULT_MODEL_ARTIFACT_ID",
    "DEFAULT_OPTIMIZER_RUN_ID",
    "DEFAULT_SIMULATION_RUN_ID",
    "ApiCapabilitiesResponse",
    "ApiContractError",
    "ApiErrorResponse",
    "ApiEvidenceError",
    "ConcurrentBenchmarkResponse",
    "ConcurrentBenchmarkSummary",
    "ConcurrentSimulationSummary",
    "ConcurrentSimulationSummaryResponse",
    "DevelopmentEvidenceBundle",
    "DevelopmentEvidenceResponse",
    "EvidenceArtifactKind",
    "HealthResponse",
    "ScenarioLimitsResponse",
    "VerifiedEvidenceArtifact",
    "VerifiedEvidenceArtifactResponse",
    "build_api_capabilities_response",
    "build_concurrent_simulation_summary_response",
    "build_development_evidence_response",
    "load_concurrent_simulation_summary",
    "validate_api_contract",
    "verify_development_evidence_bundle",
]
