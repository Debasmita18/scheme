"""
Geo routes.
===========

Serve simplified boundary geometry (GeoJSON) with risk metrics embedded,
used to render the interactive 3D India map and state-level drill-downs.
Responses are large but static, so they are gzip-compressed by middleware
and cached aggressively on the client.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Query, Response

from services import india_data

router = APIRouter(prefix="/api/geo", tags=["Geo / Map"])

# 1 day browser cache - geometry is static between dataset rebuilds.
_CACHE = "public, max-age=86400"


@router.get("/states", summary="State/UT boundaries (GeoJSON + risk)")
async def get_states_geojson(response: Response) -> Dict[str, Any]:
    """Dissolved, simplified state/UT polygons with risk metrics in
    ``properties`` - drives the national 3D India map."""
    response.headers["Cache-Control"] = _CACHE
    return india_data.states_geojson()


@router.get("/districts", summary="District boundaries (GeoJSON + risk)")
async def get_districts_geojson(
    response: Response,
    state: Optional[str] = Query(
        None, description="Filter to one state by code or name (recommended)"
    ),
) -> Dict[str, Any]:
    """Simplified district polygons with risk metrics in ``properties``.
    Pass ``?state=`` to fetch just one state's districts (much smaller)."""
    response.headers["Cache-Control"] = _CACHE
    return india_data.districts_geojson(state=state)
