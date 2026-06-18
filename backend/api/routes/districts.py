"""
District routes.
================

Listing and detail for all ~725 districts across India, served from the
in-memory all-India dataset.  Supports filtering by state, region, risk
band and free-text search, plus sorting and pagination for the data grid.
Also exposes a heatmap endpoint for risk visualisation.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from services import india_data

router = APIRouter(prefix="/api/districts", tags=["Districts"])


class SortOrder(str, Enum):
    asc = "asc"
    desc = "desc"


@router.get("", summary="List districts (all India)")
async def list_districts(
    state: Optional[str] = Query(None, description="State code or name filter"),
    region: Optional[str] = Query(None, description="Regional filter"),
    risk_band: Optional[str] = Query(None, description="critical/high/medium/low"),
    search: Optional[str] = Query(None, description="District or state name search"),
    active_only: bool = Query(False, description="Only MGNREGA-active districts"),
    sort_by: str = Query("risk_score"),
    order: SortOrder = Query(SortOrder.desc),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=1000),
) -> Dict[str, Any]:
    """Paginated, filterable, sortable list of districts with risk scores."""
    return india_data.list_districts(
        state=state, region=region, risk_band=risk_band, search=search,
        active_only=active_only, sort_by=sort_by, order=order.value,
        skip=skip, limit=limit,
    )


@router.get("/{district_id}", summary="District detail")
async def get_district(district_id: str) -> Dict[str, Any]:
    """Full district detail: expenditure, person-days, works-by-type,
    verification breakdown, participation metrics and risk."""
    d = india_data.get_district(district_id)
    if not d:
        raise HTTPException(status_code=404, detail=f"District {district_id} not found")
    return d


@router.get("/{district_id}/heatmap", summary="District risk heatmap points")
async def get_heatmap(district_id: str) -> List[Dict[str, Any]]:
    """Synthetic gram-panchayat-level risk points around the district
    centroid, suitable for a Leaflet/Mapbox heatmap overlay."""
    import random

    d = india_data.get_district(district_id)
    if not d:
        raise HTTPException(status_code=404, detail=f"District {district_id} not found")

    rng = random.Random(int(d["district_code"]) if d["district_code"].isdigit() else hash(district_id))
    n = max(8, min(40, d["total_panchayats"] // 8)) if d["mgnrega_active"] else 0
    points = []
    for i in range(n):
        points.append({
            "panchayat_id": f"{d['id']}-gp-{i:03d}",
            "latitude": round(d["lat"] + rng.uniform(-0.45, 0.45), 5),
            "longitude": round(d["lng"] + rng.uniform(-0.45, 0.45), 5),
            "risk_score": round(max(2, min(99, d["risk_score"] + rng.uniform(-22, 22))), 1),
            "total_works": rng.randint(8, 60),
        })
    return points
