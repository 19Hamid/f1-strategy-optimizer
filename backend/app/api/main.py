"""FastAPI application exposing the controlled V1 strategy system."""

from fastapi import FastAPI

from app.api.contracts import API_PREFIX
from app.api.schemas import (
    ApiCapabilitiesResponse,
    HealthResponse,
    build_api_capabilities_response,
)

app = FastAPI(
    title="F1 Race Strategy Optimizer API",
    description=(
        "Controlled dry-race pit-now versus stay-out decision support. "
        "Scenario shares are descriptive simulated-world evidence, not "
        "correctness probabilities."
    ),
    version="0.2.0",
)


@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["System"],
    summary="Check API liveness",
)
async def health_check() -> HealthResponse:
    """Confirm that the API process is running."""
    return HealthResponse()


@app.get(
    f"{API_PREFIX}/capabilities",
    response_model=ApiCapabilitiesResponse,
    tags=["System"],
    summary="Describe supported V1 behavior",
)
async def api_capabilities() -> ApiCapabilitiesResponse:
    """Publish the exact decision scope, evidence limits and holdout boundary."""
    return build_api_capabilities_response()
