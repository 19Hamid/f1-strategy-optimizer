"""FastAPI application exposing the controlled V1 strategy system."""

from contextlib import asynccontextmanager
from os import environ
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import FastAPI, Path, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.analysis import run_strategy_analysis
from app.api.contracts import API_PREFIX
from app.api.evidence import (
    ApiEvidenceError,
    verify_development_evidence_bundle,
)
from app.api.historical import (
    AnalysisSelectionError,
    HistoricalDecisionKey,
    list_verified_historical_decisions,
    load_verified_historical_analysis,
)
from app.api.jobs import (
    JobNotFoundError,
    JobQueueFullError,
    PairedJobRequest,
    get_job_manager,
    shutdown_job_manager,
)
from app.api.reporting import load_concurrent_simulation_summary
from app.api.schemas import (
    ApiCapabilitiesResponse,
    ApiErrorResponse,
    ConcurrentSimulationSummaryResponse,
    DeterministicAnalysisResponse,
    DevelopmentEvidenceResponse,
    HealthResponse,
    HistoricalDecisionCatalogResponse,
    HistoricalDecisionOptionResponse,
    HistoricalDecisionRequest,
    PairedJobRequestBody,
    PairedJobResponse,
    build_api_capabilities_response,
    build_concurrent_simulation_summary_response,
    build_deterministic_analysis_response,
    build_development_evidence_response,
    build_paired_job_response,
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Cancel and join bounded workers before the API process shuts down."""
    try:
        yield
    finally:
        shutdown_job_manager()


app = FastAPI(
    title="F1 Race Strategy Optimizer API",
    description=(
        "Controlled dry-race pit-now versus stay-out decision support. "
        "Scenario shares are descriptive simulated-world evidence, not "
        "correctness probabilities."
    ),
    version="0.5.0",
    lifespan=lifespan,
)


def dashboard_origins() -> tuple[str, ...]:
    """Allow only explicitly configured browser origins for a separate UI host."""
    origins = tuple(
        item.strip()
        for item in environ.get("F1_DASHBOARD_ORIGINS", "").split(",")
        if item.strip()
    )
    for origin in origins:
        parsed = urlsplit(origin)
        if (
            parsed.scheme not in {"https", "http"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or "*" in origin
            or origin != f"{parsed.scheme}://{parsed.netloc}"
        ):
            raise ValueError("F1_DASHBOARD_ORIGINS must contain only HTTP(S) origins")
    return origins


app.add_middleware(
    CORSMiddleware,
    allow_origins=dashboard_origins(),
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type"],
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


@app.exception_handler(AnalysisSelectionError)
async def analysis_selection_error_handler(
    _request: Request,
    _error: AnalysisSelectionError,
) -> JSONResponse:
    """Do not expose filesystem or hidden population details for bad keys."""
    return JSONResponse(
        status_code=404,
        content={
            "code": "DECISION_NOT_AVAILABLE",
            "message": "The selected development decision is unavailable.",
        },
    )


@app.exception_handler(JobQueueFullError)
async def job_queue_full_handler(
    _request: Request,
    _error: JobQueueFullError,
) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={
            "code": "ANALYSIS_QUEUE_FULL",
            "message": "The analysis queue is full; try again later.",
        },
    )


@app.exception_handler(JobNotFoundError)
async def job_not_found_handler(
    _request: Request,
    _error: JobNotFoundError,
) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={
            "code": "JOB_NOT_FOUND",
            "message": "The analysis job is unavailable.",
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


@app.get(
    f"{API_PREFIX}/analysis/decisions",
    response_model=HistoricalDecisionCatalogResponse,
    responses={503: {"model": ApiErrorResponse}},
    tags=["Analysis"],
    summary="Browse verified historical development decisions",
)
def historical_decisions() -> HistoricalDecisionCatalogResponse:
    """Expose only exact keys from the verified Phase 8 decision report."""
    return HistoricalDecisionCatalogResponse(
        decisions=tuple(
            HistoricalDecisionOptionResponse(**row)
            for row in list_verified_historical_decisions()
        )
    )


@app.post(
    f"{API_PREFIX}/analysis/deterministic",
    response_model=DeterministicAnalysisResponse,
    responses={
        404: {"model": ApiErrorResponse},
        503: {"model": ApiErrorResponse},
    },
    tags=["Analysis"],
    summary="Compare two full-horizon actions for a verified historical decision",
)
def deterministic_analysis(
    request: HistoricalDecisionRequest,
) -> DeterministicAnalysisResponse:
    """Run the verified point comparison without stability or confidence claims."""
    key = HistoricalDecisionKey(
        season=request.season,
        session_id=request.session_id,
        driver=request.driver,
        decision_lap=request.decision_lap,
        target_compound=request.target_compound,
    )
    inputs = load_verified_historical_analysis(key)
    try:
        result = run_strategy_analysis(
            inputs.decision,
            context=inputs.context,
            adapter=inputs.adapter,
        )
        return build_deterministic_analysis_response(result)
    except Exception as error:
        raise ApiEvidenceError("deterministic analysis failed") from error


@app.post(
    f"{API_PREFIX}/analysis/paired/jobs",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=PairedJobResponse,
    responses={404: {"model": ApiErrorResponse}, 429: {"model": ApiErrorResponse}},
    tags=["Analysis"],
    summary="Queue one bounded paired-scenario analysis",
)
def start_paired_analysis(body: PairedJobRequestBody) -> PairedJobResponse:
    """Schedule a development decision for cancellable background evaluation."""
    key = HistoricalDecisionKey(
        season=body.season,
        session_id=body.session_id,
        driver=body.driver,
        decision_lap=body.decision_lap,
        target_compound=body.target_compound,
    )
    if key.identity not in {
        (
            row["season"],
            row["session_id"],
            row["driver"],
            row["decision_lap"],
            row["target_compound"],
        )
        for row in list_verified_historical_decisions()
    }:
        raise AnalysisSelectionError("decision is not in the verified catalog")
    snapshot = get_job_manager().submit(
        PairedJobRequest(
            key=key,
            scenario_count=body.scenario_count,
            root_seed=body.root_seed,
            max_workers=body.max_workers,
        )
    )
    return build_paired_job_response(snapshot)


@app.get(
    f"{API_PREFIX}/analysis/paired/jobs/{{job_id}}",
    response_model=PairedJobResponse,
    responses={404: {"model": ApiErrorResponse}},
    tags=["Analysis"],
    summary="Read paired-scenario job progress or a complete result",
)
def paired_analysis_status(
    job_id: Annotated[str, Path(pattern=r"^[a-f0-9]{32}$")],
) -> PairedJobResponse:
    return build_paired_job_response(get_job_manager().status(job_id))


@app.delete(
    f"{API_PREFIX}/analysis/paired/jobs/{{job_id}}",
    response_model=PairedJobResponse,
    responses={404: {"model": ApiErrorResponse}},
    tags=["Analysis"],
    summary="Request cancellation of a paired-scenario job",
)
def cancel_paired_analysis(
    job_id: Annotated[str, Path(pattern=r"^[a-f0-9]{32}$")],
) -> PairedJobResponse:
    return build_paired_job_response(get_job_manager().cancel(job_id))
