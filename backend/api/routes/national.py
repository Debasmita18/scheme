"""
National-level routes.
======================

Aggregated, all-India view across every state, UT and district: headline
KPIs, monthly anomaly-detection trend, anomaly breakdown by type, and the
highest-risk districts in the country.  Powers the landing dashboard.
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Query

from services import india_data

router = APIRouter(prefix="/api/national", tags=["National"])


@router.get("/summary", summary="National MGNREGA KPI summary")
async def get_national_summary() -> Dict[str, Any]:
    """Headline figures across all states/UTs: expenditure, person-days,
    works, flagged anomalies, estimated leakage, composite risk and
    coverage counts (states, UTs, districts)."""
    return india_data.national_summary()


@router.get("/trends", summary="National monthly anomaly trend")
async def get_national_trends() -> List[Dict[str, Any]]:
    """12-month detected / resolved / cumulative-pending anomaly trend."""
    return india_data.national_trend()


@router.get("/anomaly-breakdown", summary="National anomalies by type")
async def get_anomaly_breakdown() -> List[Dict[str, Any]]:
    """Anomaly counts by category with an estimated rupee impact (lakhs)."""
    return india_data.anomaly_breakdown()


@router.get("/top-districts", summary="Highest-risk districts nationwide")
async def get_top_districts(
    limit: int = Query(10, ge=1, le=25),
) -> List[Dict[str, Any]]:
    """Top-N districts by composite risk score across the whole country."""
    return india_data.top_risk_districts(limit)
