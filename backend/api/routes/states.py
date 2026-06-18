"""
State / UT routes.
==================

Listing and detail for all 28 states and 8 union territories, each with
aggregated MGNREGA metrics, composite risk, and its constituent districts.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from services import india_data

router = APIRouter(prefix="/api/states", tags=["States & UTs"])


class SortOrder(str, Enum):
    asc = "asc"
    desc = "desc"


@router.get("", summary="List all states and union territories")
async def list_states(
    region: Optional[str] = Query(None, description="North/South/East/West/Central/Northeast"),
    state_type: Optional[str] = Query(None, description="'State' or 'UT'"),
    search: Optional[str] = Query(None, description="Case-insensitive name match"),
    sort_by: str = Query("risk_score"),
    order: SortOrder = Query(SortOrder.desc),
) -> List[Dict[str, Any]]:
    """All states/UTs with aggregated metrics and risk, sortable/filterable."""
    return india_data.list_states(
        region=region, state_type=state_type, search=search,
        sort_by=sort_by, order=order.value,
    )


@router.get("/{state_code}", summary="State / UT detail with districts")
async def get_state(state_code: str) -> Dict[str, Any]:
    """Full state/UT detail including the list of its districts."""
    state = india_data.get_state(state_code)
    if not state:
        raise HTTPException(status_code=404, detail=f"State {state_code} not found")
    return state
