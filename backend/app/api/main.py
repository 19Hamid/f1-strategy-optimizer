from fastapi import FastAPI

app = FastAPI(
    title="F1 Race Strategy Optimizer API",
    description="API for F1 race analysis and strategy simulation.",
    version="0.1.0",
)


@app.get("/health", tags=["System"])
async def health_check() -> dict[str, str]:
    """Confirm that the API is running."""
    return {"status": "healthy"}