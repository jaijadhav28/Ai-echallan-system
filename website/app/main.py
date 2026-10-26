"""FastAPI application entry point.

Run from the ``backend`` folder with:
    uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import BACKEND_DIR, settings
from .database import database
from .routers import (
    alerts,
    api_config,
    auth,
    cameras,
    challans,
    dashboard,
    network,
    payments,
    public_notice,
    reports,
    rules,
    settings_router,
    users,
    vehicles,
    violations,
)
from .services.app_settings import apply_runtime_overrides, get_settings_document
from .services.pipeline import pipeline
from .services.rules_service import ensure_rules
from .utils import utcnow_iso

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("rto")

# One-folder deploy keeps the built pages in ui/. Development uses frontend/dist.
_bundled_ui = BACKEND_DIR / "ui"
_dev_ui = BACKEND_DIR.parent / "frontend" / "dist"
FRONTEND_DIST = _bundled_ui if (_bundled_ui / "index.html").is_file() else _dev_ui
FRONTEND_INDEX = FRONTEND_DIST / "index.html"


class CachedStaticFiles(StaticFiles):
    """Hashed Vite assets can be cached aggressively by the browser."""

    def file_response(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response

DESCRIPTION = """
Backend for the **AI Driven Camera Detected RTO E-Challan System**.

* Multi camera capture (RTSP / demo video / demo image / synthetic) - one worker thread each
* AI violation detection (Groq vision) with an OpenCV heuristic fallback
* ANPR through Plate Recognizer, SMS through Fast2SMS, payments through Razorpay Test Mode
* JWT auth with Administrator and Traffic Officer roles

All API keys are read from `backend/.env` on the server. Missing keys put the
related feature into DEMO MODE instead of faking a third-party response.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    await database.connect()
    await ensure_rules()
    apply_runtime_overrides(await get_settings_document())

    from .bootstrap import bootstrap_if_empty

    await bootstrap_if_empty()

    from .services.gpu_accel import enable_gpu

    gpu_info = enable_gpu(settings.use_gpu)
    await pipeline.start()
    logger.info(
        "Backend ready | database=%s | GPU=%s | AI=%s ANPR=%s SMS=%s Payments=%s",
        database.backend,
        gpu_info.get("backend", "cpu"),
        "on" if settings.ai_configured else "demo",
        "on" if settings.anpr_configured else "demo",
        "on" if settings.sms_configured else "demo",
        "on" if settings.payment_configured else "demo",
    )
    try:
        yield
    finally:
        await pipeline.stop()
        await database.close()


app = FastAPI(
    title="AI Driven Camera Detected RTO E-Challan System",
    description=DESCRIPTION,
    version=__version__,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list
    or [
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "*",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in (
    auth,
    dashboard,
    cameras,
    violations,
    challans,
    payments,
    public_notice,
    vehicles,
    reports,
    api_config,
    network,
    alerts,
    rules,
    users,
    settings_router,
):
    app.include_router(module.router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "detail": f"Internal server error: {type(exc).__name__}: {exc}",
            "path": request.url.path,
        },
    )


@app.get("/api/health", tags=["System"])
async def health() -> dict:
    from .services.camera_manager import camera_manager
    from .services.gpu_accel import gpu_status

    return {
        "status": "ok",
        "version": __version__,
        "environment": settings.app_env,
        "database": await database.health(),
        "cameras": camera_manager.summary(),
        "pipeline": pipeline.status(),
        "integrations": {
            "groq_ai": settings.ai_configured,
            "plate_recognizer_anpr": settings.anpr_configured,
            "sms": settings.sms_configured,
            "razorpay": settings.payment_configured,
        },
        "gpu": {**gpu_status(), "preferred": settings.use_gpu},
        "frontend_bundled": FRONTEND_INDEX.is_file(),
        "checked_at": utcnow_iso(),
    }


def _mount_frontend() -> None:
    """Serve the React build from this same FastAPI process (one HTTP link)."""
    if not FRONTEND_INDEX.is_file():
        logger.warning(
            "Frontend build not found at %s — run: cd frontend && npm run build",
            FRONTEND_DIST,
        )

        @app.get("/", tags=["System"])
        async def root_api_only() -> dict:
            return {
                "application": "AI Driven Camera Detected RTO E-Challan System",
                "version": __version__,
                "docs": "/docs",
                "health": "/api/health",
                "hint": "Build the frontend (npm run build) then restart for a single-link UI.",
            }

        return

    assets_dir = FRONTEND_DIST / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", CachedStaticFiles(directory=assets_dir), name="assets")

    @app.get("/", include_in_schema=False)
    async def spa_root() -> FileResponse:
        return FileResponse(
            FRONTEND_INDEX,
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str) -> FileResponse:
        # API / docs routes are registered above and take priority.
        reserved = ("api", "docs", "redoc", "openapi.json")
        first = (full_path or "").split("/", 1)[0]
        if first in reserved:
            raise HTTPException(status_code=404, detail="Not found")

        candidate = (FRONTEND_DIST / full_path).resolve()
        try:
            candidate.relative_to(FRONTEND_DIST.resolve())
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Not found") from exc

        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(
            FRONTEND_INDEX,
            headers={"Cache-Control": "no-cache"},
        )

    logger.info("Serving website UI from %s (open http://127.0.0.1:8000/)", FRONTEND_DIST)


_mount_frontend()
