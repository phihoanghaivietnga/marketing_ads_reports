"""FastAPI application entrypoint.

Registers routers, middleware, and lifecycle hooks.
Phase D — full API layer with metrics, campaigns endpoints.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routers.metrics import router as metrics_router
from app.api.routers.campaigns import router as campaigns_router
from app.infra.redis_client import close_redis, init_redis


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle: init Redis on startup, close on shutdown.

    Redis connection failure is non-fatal — the API still starts for local dev.
    """
    try:
        await init_redis()
    except Exception:
        # Redis may not be available in local dev — app still starts
        pass
    yield
    try:
        await close_redis()
    except Exception:
        pass


app = FastAPI(
    title="Marketing Analytics Dashboard API",
    version="0.1.0",
    docs_url="/docs",
    lifespan=lifespan,
)

# ------------------------------------------------------------------
# Routers
# ------------------------------------------------------------------

app.include_router(metrics_router)
app.include_router(campaigns_router)


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint — returns 200 when the service is running."""
    return {"status": "ok"}