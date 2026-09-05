from __future__ import annotations

import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from apps.api.app.api.v1.routes import router
from apps.api.app.api.v1.schemas import HealthResponse
from apps.api.app.core.config import get_settings
from apps.api.app.core.errors import COMMON_ERROR_RESPONSES, install_error_handlers
from apps.api.app.core.logging import configure_logging
from apps.api.app.state import new_id

logger = configure_logging(logger_name="effica.api")
EXPECTED_DB_REVISION = "0017_remove_obsolete_storage"


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    settings.assert_safe_runtime()
    if settings.app_backend == "mariadb":
        from apps.api.app.db.session import create_engine, session_factory
        from apps.api.app.repositories.platform import MariaDBPlatformRepository

        create_engine(settings.database_url)
        factory = session_factory()
        async with factory() as session:
            repository = MariaDBPlatformRepository(
                session,
                encryption_secret=settings.session_secret,
            )
            await repository.bootstrap_policy_records()
    try:
        yield
    finally:
        if settings.app_backend == "mariadb":
            from apps.api.app.db.session import dispose_engine

            await dispose_engine()


app = FastAPI(
    title="EFFICA API",
    version="1.0.1",
    summary="Balanced issue comparison, engagement, scoring and operations API",
    description=(
        "The executable MAS_B contract. Coordinates are observations with uncertainty, not political "
        "identity or truth labels. Article text is never exposed by this API."
    ),
    lifespan=lifespan,
    openapi_tags=[
        {"name": "health", "description": "Liveness and MariaDB/config readiness"},
        {"name": "v1", "description": "Version 1 product and administration contract"},
    ],
)
install_error_handlers(app)
app.include_router(router, tags=["v1"])


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or new_id()
    request.state.request_id = request_id
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception(
            "request_failed",
            extra={"request_id": request_id, "method": request.method, "path": request.url.path},
        )
        raise
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "request_complete",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "latency_ms": round((time.perf_counter() - started) * 1000, 3),
        },
    )
    return response


@app.get(
    "/health/live",
    response_model=HealthResponse,
    responses=COMMON_ERROR_RESPONSES,
    tags=["health"],
    operation_id="health_live",
)
async def health_live() -> dict:
    return {"status": "live", "checks": {"process": "ok"}, "timestamp": datetime.now(UTC)}


@app.get(
    "/health/ready",
    response_model=HealthResponse,
    responses=COMMON_ERROR_RESPONSES,
    tags=["health"],
    operation_id="health_ready",
)
async def health_ready() -> JSONResponse | dict:
    settings = get_settings()
    checks = {"configuration": "ok", "backend": settings.app_backend}
    if settings.app_backend == "memory":
        checks["database"] = "not-required-local-memory"
        return {"status": "ready", "checks": checks, "timestamp": datetime.now(UTC)}
    try:
        from apps.api.app.db.session import get_engine

        async with get_engine().connect() as connection:
            await connection.execute(text("SELECT 1"))
            revision = (
                await connection.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one()
            if str(revision) != EXPECTED_DB_REVISION:
                checks["schema_revision"] = f"expected:{EXPECTED_DB_REVISION},actual:{revision}"
                body = HealthResponse(
                    status="not_ready", checks=checks, timestamp=datetime.now(UTC)
                )
                return JSONResponse(status_code=503, content=body.model_dump(mode="json"))
        checks["database"] = "ok"
        checks["schema_revision"] = EXPECTED_DB_REVISION
        return {"status": "ready", "checks": checks, "timestamp": datetime.now(UTC)}
    except Exception:
        checks["database"] = "unavailable"
        body = HealthResponse(status="not_ready", checks=checks, timestamp=datetime.now(UTC))
        return JSONResponse(status_code=503, content=body.model_dump(mode="json"))
