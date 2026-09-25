"""FastAPI application exposing the controlled V1 strategy system."""

from typing import Annotated

from fastapi import FastAPI, Path, Request
from fastapi.responses import JSONResponse

from app.api.contracts import API_PREFIX
from app.api.evidence import (
    ApiEvidenceError,
    verify_development_evidence_bundle,
)
from app.api.reporting import load_concurrent_simulation_summary
from app.api.schemas import (
    ApiCapabilitiesResponse,
    ApiErrorResponse,
    ConcurrentSimulationSummaryResponse,
    DevelopmentEvidenceResponse,
    HealthResponse,
    build_api_capabilities_response,
    build_concurrent_simulation_summary_response,
    build_development_evidence_response,
)

app = FastAPI(
    title="F1 Race Strategy Optimizer API",
    description=(
        "Controlled dry-race pit-now versus stay-out decision support. "
        "Scenario shares are descriptive simulated-world evidence, not "
        "correctness probabilities."
    ),
    version="0.3.0",
)


@app.exception_handler(ApiEvidenceError)
async def api_evidence_error_handler(
    _request: Request,
    _error: ApiEvidenceError,
) -> JSONResponse:
    """Return one stable unavailable response without leaking local paths."""
    return JSONResponse(
        status_code=503,
        content={
            "code": "EVIDENCE_UNAVAILABLE",
            "message": "Verified development evidence is unavailable.",
        },
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


@app.get(
    f"{API_PREFIX}/evidence/development",
    response_model=DevelopmentEvidenceResponse,
    responses={503: {"model": ApiErrorResponse}},
    tags=["Evidence"],
    summary="Verify complete development evidence",
)
def development_evidence() -> DevelopmentEvidenceResponse:
    """Verify Phase 6-9 artifacts before exposing their identities."""
    bundle = verify_development_evidence_bundle()
    return build_development_evidence_response(bundle)


@app.get(
    f"{API_PREFIX}/reports/concurrent-simulation/{{run_id}}",
    response_model=ConcurrentSimulationSummaryResponse,
    responses={503: {"model": ApiErrorResponse}},
    tags=["Evidence"],
    summary="Read a verified concurrent-simulation report",
)
def concurrent_simulation_report(
    run_id: Annotated[
        str,
        Path(
            min_length=1,
            max_length=100,
            pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
        ),
    ],
) -> ConcurrentSimulationSummaryResponse:
    """Expose one compact Phase 9 summary after complete verification."""
    summary = load_concurrent_simulation_summary(run_id=run_id)
    return build_concurrent_simulation_summary_response(summary)
