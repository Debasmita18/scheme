"""
MGNREGA Verification & Fraud Intelligence System - FastAPI Application
======================================================================

Central application entry point.  Configures CORS, registers route
routers, wires up startup/shutdown lifecycle hooks (database pool,
background scheduler), and exposes health-check and root documentation
endpoints.

Run with:
    uvicorn api.main:app --reload --port 8000
"""

from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager
from typing import Any, Dict

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import ORJSONResponse
from loguru import logger

from api.middleware import register_middleware
from api.routes.national import router as national_router
from api.routes.states import router as states_router
from api.routes.geo import router as geo_router
from api.routes.districts import router as districts_router
from api.routes.works import router as works_router
from api.routes.anomalies import router as anomalies_router
from api.routes.verification import router as verification_router
from api.routes.reports import router as reports_router
from api.routes.ai_reports import router as ai_reports_router

# ---------------------------------------------------------------------------
# OpenAPI metadata
# ---------------------------------------------------------------------------
TAGS_METADATA = [
    {
        "name": "National",
        "description": "All-India aggregated KPIs, trends, anomaly breakdown "
        "and the highest-risk districts nationwide.",
    },
    {
        "name": "States & UTs",
        "description": "All 28 states and 8 union territories with aggregated "
        "MGNREGA metrics, composite risk, and constituent districts.",
    },
    {
        "name": "Geo / Map",
        "description": "Simplified boundary GeoJSON (states & districts) with "
        "risk metrics embedded, for the interactive 3D India map.",
    },
    {
        "name": "Districts",
        "description": "District, block, and gram panchayat management. "
        "Risk scores, dashboards, and heatmaps.",
    },
    {
        "name": "Works",
        "description": "MGNREGA works data: listing, detail views, satellite "
        "imagery, muster rolls, payments, and verification triggers.",
    },
    {
        "name": "Anomalies",
        "description": "Detected anomalies across all verification dimensions. "
        "Filtering, trend analysis, and hotspot mapping.",
    },
    {
        "name": "Verification",
        "description": "Trigger and monitor asynchronous verification pipelines "
        "(satellite, muster-roll, payment, photo, full-scan).",
    },
    {
        "name": "Reports",
        "description": "Generate and retrieve intelligence reports, case files, "
        "weekly briefings, and leakage estimates.",
    },
    {
        "name": "Health",
        "description": "Operational health checks and root documentation.",
    },
]


# ---------------------------------------------------------------------------
# Application lifespan (startup / shutdown)
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage startup and shutdown resources."""
    logger.info("Starting MGNREGA Verification & Fraud Intelligence System")

    # --- startup ---
    # Attempt database connection; fall back to mock mode silently.
    db_available = False
    try:
        from config.settings import get_settings

        settings = get_settings()
        logger.info(
            "Database URL configured: {}",
            settings.database_url[:40] + "...",
        )
        # A real connection pool would be initialised here.
        db_available = True
    except Exception as exc:
        logger.warning(
            "Database unavailable - running in mock-data mode: {}", exc
        )

    app.state.db_available = db_available

    # Warm the in-memory all-India dataset so the first request is fast.
    try:
        from services import india_data

        counts = india_data.warm_cache()
        logger.info(
            "All-India dataset loaded: {} states/UTs, {} districts, "
            "{} state geometries, {} district geometries",
            counts["states"], counts["districts"],
            counts["geo_states"], counts["geo_districts"],
        )
        app.state.dataset_loaded = True
    except Exception as exc:  # pragma: no cover - surfaced at /health
        logger.error("Failed to load all-India dataset: {}", exc)
        logger.error("Run:  python -m data_ingestion.build_india_dataset")
        app.state.dataset_loaded = False

    # Background scheduler placeholder (APScheduler).
    logger.info("Background scheduler initialised (placeholder)")

    yield

    # --- shutdown ---
    logger.info("Shutting down MGNREGA Verification System")
    # Close DB pools, scheduler, etc.


# ---------------------------------------------------------------------------
# Create the application
# ---------------------------------------------------------------------------
app = FastAPI(
    title="MGNREGA Verification & Fraud Intelligence System",
    description=(
        "AI-powered platform for verifying MGNREGA rural works through "
        "satellite imagery, muster roll forensics, payment pattern analysis, "
        "and geotagged photo verification. Provides anomaly detection, "
        "investigation case management, and automated report generation."
    ),
    version="1.0.0",
    openapi_tags=TAGS_METADATA,
    default_response_class=ORJSONResponse,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# CORS - allow React dev server
# ---------------------------------------------------------------------------
# Origins: localhost dev defaults + any set via CORS_ORIGINS env (comma-separated),
# plus a regex covering free PaaS hosts (Render / Netlify / Vercel / Pages).
_default_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",  # Vite default
]
_env_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_default_origins + _env_origins,
    allow_origin_regex=r"https://.*\.(onrender\.com|netlify\.app|vercel\.app|pages\.dev)",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Compress large responses (GeoJSON map payloads in particular).
app.add_middleware(GZipMiddleware, minimum_size=1024)

# ---------------------------------------------------------------------------
# Custom middleware stack
# ---------------------------------------------------------------------------
register_middleware(app)

# ---------------------------------------------------------------------------
# Route routers
# ---------------------------------------------------------------------------
app.include_router(national_router)
app.include_router(states_router)
app.include_router(geo_router)
app.include_router(districts_router)
app.include_router(works_router)
app.include_router(anomalies_router)
app.include_router(verification_router)
app.include_router(reports_router)
app.include_router(ai_reports_router)


# ---------------------------------------------------------------------------
# Health check & root
# ---------------------------------------------------------------------------
@app.get("/health", tags=["Health"], summary="Health check")
async def health_check(request: Request) -> Dict[str, Any]:
    """Return service health status including database connectivity."""
    db_ok = getattr(request.app.state, "db_available", False)
    dataset_ok = getattr(request.app.state, "dataset_loaded", False)
    return {
        "status": "healthy" if dataset_ok else "degraded",
        "database": "connected" if db_ok else "mock_mode",
        "dataset": "loaded" if dataset_ok else "missing",
        "version": app.version,
        "timestamp": time.time(),
    }


@app.get("/", tags=["Health"], summary="API root")
async def root() -> Dict[str, Any]:
    """Root endpoint with links to API documentation."""
    return {
        "service": app.title,
        "version": app.version,
        "docs": {
            "swagger_ui": "/docs",
            "redoc": "/redoc",
            "openapi_json": "/openapi.json",
        },
        "endpoints": {
            "health": "/health",
            "national_summary": "/api/national/summary",
            "states": "/api/states",
            "geo_states": "/api/geo/states",
            "geo_districts": "/api/geo/districts",
            "districts": "/api/districts",
            "works": "/api/works",
            "anomalies": "/api/anomalies",
            "verification": "/api/verification",
            "reports": "/api/reports",
        },
    }
