"""
Work management routes.
========================

Endpoints for listing MGNREGA works, viewing details, satellite
verification imagery, muster rolls, payments, geotagged photos,
triggering verification, and surfacing top discrepancies.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/works", tags=["Works"])


# -------------------------------------------------------------------------
# Enums
# -------------------------------------------------------------------------
class WorkType(str, Enum):
    road_construction = "road_construction"
    pond_excavation = "pond_excavation"
    land_levelling = "land_levelling"
    water_conservation = "water_conservation"
    plantation = "plantation"
    building_construction = "building_construction"
    flood_control = "flood_control"
    other = "other"


class WorkStatus(str, Enum):
    not_started = "not_started"
    in_progress = "in_progress"
    completed = "completed"
    closed = "closed"


class VerificationStatus(str, Enum):
    pending = "pending"
    in_progress = "in_progress"
    verified_clean = "verified_clean"
    verified_flagged = "verified_flagged"


# -------------------------------------------------------------------------
# Pydantic schemas
# -------------------------------------------------------------------------
class WorkSummary(BaseModel):
    id: str
    work_name: str
    work_code: str
    work_type: WorkType
    status: WorkStatus
    verification_status: VerificationStatus
    district_name: str
    block_name: str
    panchayat_name: str
    sanctioned_amount_lakhs: float
    expenditure_lakhs: float
    fin_year: str
    risk_score: float = Field(..., ge=0, le=100)
    start_date: Optional[str] = None
    completion_date: Optional[str] = None


class SatelliteData(BaseModel):
    work_id: str
    before_image_url: str = Field(..., description="Pre-construction satellite image URL")
    after_image_url: str = Field(..., description="Post-construction satellite image URL")
    before_date: str
    after_date: str
    reported_area_sqm: float
    measured_area_sqm: float
    area_discrepancy_percent: float
    ndvi_before: float
    ndvi_after: float
    ndvi_change: float
    land_use_change_detected: bool
    confidence_score: float = Field(..., ge=0, le=1)
    verification_result: str


class MusterRollRecord(BaseModel):
    id: str
    muster_roll_number: str
    date_from: str
    date_to: str
    total_workers: int
    total_person_days: int
    total_wages_rs: float
    avg_daily_wage_rs: float
    suspicious_patterns: List[str]
    duplicate_entries: int


class PaymentRecord(BaseModel):
    id: str
    beneficiary_name: str
    job_card_number: str
    bank_account_last4: str
    amount_rs: float
    payment_date: str
    fto_number: str
    payment_mode: str
    days_worked: int
    daily_wage_rs: float
    anomaly_flags: List[str]


class PhotoRecord(BaseModel):
    id: str
    photo_url: str
    capture_date: str
    latitude: float
    longitude: float
    distance_from_worksite_m: float
    metadata_intact: bool
    exif_timestamp_match: bool
    verification_status: str
    ai_description: Optional[str] = None


class WorkDetail(BaseModel):
    id: str
    work_name: str
    work_code: str
    work_type: WorkType
    status: WorkStatus
    verification_status: VerificationStatus
    district_name: str
    district_id: str
    block_name: str
    block_id: str
    panchayat_name: str
    panchayat_id: str
    sanctioned_amount_lakhs: float
    expenditure_lakhs: float
    fin_year: str
    risk_score: float
    start_date: str
    completion_date: Optional[str]
    latitude: float
    longitude: float
    description: str
    total_person_days: int
    total_workers: int
    satellite_verified: bool
    muster_roll_verified: bool
    payment_verified: bool
    photo_verified: bool
    anomaly_count: int


class DiscrepancyItem(BaseModel):
    work_id: str
    work_name: str
    district_name: str
    panchayat_name: str
    reported_measurement: float
    satellite_measurement: float
    discrepancy_percent: float
    estimated_excess_lakhs: float
    verification_date: str


class PaginatedResponse(BaseModel):
    total: int
    skip: int
    limit: int
    data: List[Any]


class VerifyResponse(BaseModel):
    job_id: str
    work_id: str
    status: str
    message: str


# -------------------------------------------------------------------------
# Mock data
# -------------------------------------------------------------------------
_MOCK_WORKS: List[Dict[str, Any]] = [
    {
        "id": "w-001",
        "work_name": "Rural Road Bargaon to Hesalong (3.2 km)",
        "work_code": "JH-34-3407-001-2425",
        "work_type": "road_construction",
        "status": "completed",
        "verification_status": "verified_flagged",
        "district_name": "Gumla",
        "district_id": "d-01",
        "block_name": "Bishunpur",
        "block_id": "b-0101",
        "panchayat_name": "Bargaon",
        "panchayat_id": "gp-010101",
        "sanctioned_amount_lakhs": 18.50,
        "expenditure_lakhs": 17.82,
        "fin_year": "2024-2025",
        "risk_score": 82.3,
        "start_date": "2024-06-15",
        "completion_date": "2024-11-28",
        "latitude": 23.0451,
        "longitude": 84.5321,
        "description": "Construction of rural road from Bargaon village to Hesalong, 3.2 km with 3.5m width gravel surface.",
        "total_person_days": 4820,
        "total_workers": 187,
        "satellite_verified": True,
        "muster_roll_verified": True,
        "payment_verified": True,
        "photo_verified": False,
        "anomaly_count": 3,
    },
    {
        "id": "w-002",
        "work_name": "Farm Pond Excavation at Dumardaga",
        "work_code": "JH-34-3407-002-2425",
        "work_type": "pond_excavation",
        "status": "completed",
        "verification_status": "verified_clean",
        "district_name": "Gumla",
        "district_id": "d-01",
        "block_name": "Bishunpur",
        "block_id": "b-0101",
        "panchayat_name": "Dumardaga",
        "panchayat_id": "gp-010102",
        "sanctioned_amount_lakhs": 5.20,
        "expenditure_lakhs": 4.95,
        "fin_year": "2024-2025",
        "risk_score": 12.1,
        "start_date": "2024-07-01",
        "completion_date": "2024-09-15",
        "latitude": 23.0612,
        "longitude": 84.5487,
        "description": "Excavation of farm pond 20m x 15m x 3m depth at Dumardaga for irrigation water storage.",
        "total_person_days": 1250,
        "total_workers": 62,
        "satellite_verified": True,
        "muster_roll_verified": True,
        "payment_verified": True,
        "photo_verified": True,
        "anomaly_count": 0,
    },
    {
        "id": "w-003",
        "work_name": "Check Dam Construction at Hesalong Nala",
        "work_code": "JH-34-3407-003-2425",
        "work_type": "water_conservation",
        "status": "in_progress",
        "verification_status": "in_progress",
        "district_name": "Gumla",
        "district_id": "d-01",
        "block_name": "Chainpur",
        "block_id": "b-0102",
        "panchayat_name": "Hesalong",
        "panchayat_id": "gp-010103",
        "sanctioned_amount_lakhs": 12.80,
        "expenditure_lakhs": 9.65,
        "fin_year": "2024-2025",
        "risk_score": 91.7,
        "start_date": "2024-08-10",
        "completion_date": None,
        "latitude": 23.0823,
        "longitude": 84.5102,
        "description": "Construction of check dam on Hesalong nala for water conservation and groundwater recharge.",
        "total_person_days": 3100,
        "total_workers": 143,
        "satellite_verified": True,
        "muster_roll_verified": False,
        "payment_verified": False,
        "photo_verified": False,
        "anomaly_count": 5,
    },
    {
        "id": "w-004",
        "work_name": "Plantation Drive Kisko Hills (50 hectares)",
        "work_code": "JH-34-3407-004-2425",
        "work_type": "plantation",
        "status": "completed",
        "verification_status": "verified_flagged",
        "district_name": "Gumla",
        "district_id": "d-01",
        "block_name": "Ghaghra",
        "block_id": "b-0103",
        "panchayat_name": "Kisko",
        "panchayat_id": "gp-010105",
        "sanctioned_amount_lakhs": 8.40,
        "expenditure_lakhs": 8.35,
        "fin_year": "2024-2025",
        "risk_score": 68.5,
        "start_date": "2024-07-15",
        "completion_date": "2024-12-20",
        "latitude": 23.1287,
        "longitude": 84.5678,
        "description": "Plantation of 15000 saplings over 50 hectares on degraded forest land at Kisko Hills.",
        "total_person_days": 2800,
        "total_workers": 120,
        "satellite_verified": True,
        "muster_roll_verified": True,
        "payment_verified": True,
        "photo_verified": True,
        "anomaly_count": 2,
    },
    {
        "id": "w-005",
        "work_name": "Land Levelling at Maheshpur (12 acres)",
        "work_code": "JH-34-3407-005-2425",
        "work_type": "land_levelling",
        "status": "completed",
        "verification_status": "verified_flagged",
        "district_name": "Gumla",
        "district_id": "d-01",
        "block_name": "Gumla",
        "block_id": "b-0104",
        "panchayat_name": "Maheshpur",
        "panchayat_id": "gp-010106",
        "sanctioned_amount_lakhs": 6.75,
        "expenditure_lakhs": 6.70,
        "fin_year": "2024-2025",
        "risk_score": 95.2,
        "start_date": "2024-05-20",
        "completion_date": "2024-08-30",
        "latitude": 23.0156,
        "longitude": 84.5834,
        "description": "Land levelling for 12 acres of agricultural land at Maheshpur GP for improved cultivation.",
        "total_person_days": 1800,
        "total_workers": 95,
        "satellite_verified": True,
        "muster_roll_verified": True,
        "payment_verified": True,
        "photo_verified": True,
        "anomaly_count": 4,
    },
]

_MOCK_SATELLITE: Dict[str, Dict[str, Any]] = {
    "w-001": {
        "work_id": "w-001",
        "before_image_url": "/static/satellite/w001_before_20240601.tif",
        "after_image_url": "/static/satellite/w001_after_20241201.tif",
        "before_date": "2024-06-01",
        "after_date": "2024-12-01",
        "reported_area_sqm": 11200.0,
        "measured_area_sqm": 7840.0,
        "area_discrepancy_percent": 30.0,
        "ndvi_before": 0.42,
        "ndvi_after": 0.18,
        "ndvi_change": -0.24,
        "land_use_change_detected": True,
        "confidence_score": 0.87,
        "verification_result": "FLAGGED - Reported road dimensions exceed satellite measurements by 30%. Possible inflated measurements.",
    },
    "w-002": {
        "work_id": "w-002",
        "before_image_url": "/static/satellite/w002_before_20240615.tif",
        "after_image_url": "/static/satellite/w002_after_20241001.tif",
        "before_date": "2024-06-15",
        "after_date": "2024-10-01",
        "reported_area_sqm": 300.0,
        "measured_area_sqm": 285.0,
        "area_discrepancy_percent": 5.0,
        "ndvi_before": 0.38,
        "ndvi_after": 0.05,
        "ndvi_change": -0.33,
        "land_use_change_detected": True,
        "confidence_score": 0.93,
        "verification_result": "CLEAN - Pond dimensions within acceptable tolerance. Clear excavation visible.",
    },
}

_MOCK_MUSTER_ROLLS: Dict[str, List[Dict[str, Any]]] = {
    "w-001": [
        {
            "id": "mr-001-01",
            "muster_roll_number": "MR/3407/2024/001-01",
            "date_from": "2024-06-15",
            "date_to": "2024-06-30",
            "total_workers": 45,
            "total_person_days": 540,
            "total_wages_rs": 172800.0,
            "avg_daily_wage_rs": 320.0,
            "suspicious_patterns": [
                "12 workers with identical attendance patterns",
                "3 job cards linked to same bank account",
            ],
            "duplicate_entries": 3,
        },
        {
            "id": "mr-001-02",
            "muster_roll_number": "MR/3407/2024/001-02",
            "date_from": "2024-07-01",
            "date_to": "2024-07-15",
            "total_workers": 52,
            "total_person_days": 624,
            "total_wages_rs": 199680.0,
            "avg_daily_wage_rs": 320.0,
            "suspicious_patterns": ["Weekend attendance recorded for 8 workers"],
            "duplicate_entries": 0,
        },
    ],
    "w-003": [
        {
            "id": "mr-003-01",
            "muster_roll_number": "MR/3407/2024/003-01",
            "date_from": "2024-08-10",
            "date_to": "2024-08-31",
            "total_workers": 68,
            "total_person_days": 952,
            "total_wages_rs": 304640.0,
            "avg_daily_wage_rs": 320.0,
            "suspicious_patterns": [
                "22 workers with 100% attendance over 21 days",
                "Spike in worker count coincides with election period",
                "5 workers aged above 80 years",
            ],
            "duplicate_entries": 7,
        },
    ],
}

_MOCK_PAYMENTS: Dict[str, List[Dict[str, Any]]] = {
    "w-001": [
        {
            "id": "pay-001-01",
            "beneficiary_name": "Ramesh Oraon",
            "job_card_number": "JH-34-001-00145",
            "bank_account_last4": "7823",
            "amount_rs": 9600.0,
            "payment_date": "2024-07-15",
            "fto_number": "FTO/3407/2024/0012",
            "payment_mode": "DBT",
            "days_worked": 30,
            "daily_wage_rs": 320.0,
            "anomaly_flags": [],
        },
        {
            "id": "pay-001-02",
            "beneficiary_name": "Sita Devi Munda",
            "job_card_number": "JH-34-001-00178",
            "bank_account_last4": "7823",
            "amount_rs": 9600.0,
            "payment_date": "2024-07-15",
            "fto_number": "FTO/3407/2024/0012",
            "payment_mode": "DBT",
            "days_worked": 30,
            "daily_wage_rs": 320.0,
            "anomaly_flags": [
                "Same bank account as another beneficiary",
                "Maximum possible attendance",
            ],
        },
        {
            "id": "pay-001-03",
            "beneficiary_name": "Birsa Lakra",
            "job_card_number": "JH-34-001-00212",
            "bank_account_last4": "4561",
            "amount_rs": 6400.0,
            "payment_date": "2024-07-15",
            "fto_number": "FTO/3407/2024/0012",
            "payment_mode": "DBT",
            "days_worked": 20,
            "daily_wage_rs": 320.0,
            "anomaly_flags": [],
        },
    ],
}

_MOCK_PHOTOS: Dict[str, List[Dict[str, Any]]] = {
    "w-001": [
        {
            "id": "ph-001-01",
            "photo_url": "/static/photos/w001_start_20240615.jpg",
            "capture_date": "2024-06-15",
            "latitude": 23.0453,
            "longitude": 84.5319,
            "distance_from_worksite_m": 25.0,
            "metadata_intact": True,
            "exif_timestamp_match": True,
            "verification_status": "verified_clean",
            "ai_description": "Clear ground-level image showing initial road marking and clearing activity. Workers visible with tools.",
        },
        {
            "id": "ph-001-02",
            "photo_url": "/static/photos/w001_mid_20240815.jpg",
            "capture_date": "2024-08-15",
            "latitude": 23.0460,
            "longitude": 84.5330,
            "distance_from_worksite_m": 45.0,
            "metadata_intact": True,
            "exif_timestamp_match": True,
            "verification_status": "verified_clean",
            "ai_description": "Road construction in progress. Gravel surface partially laid. Workers and equipment visible.",
        },
        {
            "id": "ph-001-03",
            "photo_url": "/static/photos/w001_end_20241128.jpg",
            "capture_date": "2024-11-28",
            "latitude": 23.0980,
            "longitude": 84.5780,
            "distance_from_worksite_m": 3200.0,
            "metadata_intact": False,
            "exif_timestamp_match": False,
            "verification_status": "verified_flagged",
            "ai_description": "Photo metadata stripped. GPS location 3.2 km from worksite. Possible stock image or photo from different location.",
        },
    ],
}


def _filter_works(
    district: Optional[str],
    block: Optional[str],
    panchayat: Optional[str],
    work_type: Optional[WorkType],
    status: Optional[WorkStatus],
    fin_year: Optional[str],
    verification_status: Optional[VerificationStatus],
    min_amount: Optional[float],
    max_amount: Optional[float],
) -> List[Dict[str, Any]]:
    results = list(_MOCK_WORKS)
    if district:
        results = [w for w in results if district.lower() in w["district_name"].lower()]
    if block:
        results = [w for w in results if block.lower() in w["block_name"].lower()]
    if panchayat:
        results = [w for w in results if panchayat.lower() in w["panchayat_name"].lower()]
    if work_type:
        results = [w for w in results if w["work_type"] == work_type.value]
    if status:
        results = [w for w in results if w["status"] == status.value]
    if fin_year:
        results = [w for w in results if w["fin_year"] == fin_year]
    if verification_status:
        results = [w for w in results if w["verification_status"] == verification_status.value]
    if min_amount is not None:
        results = [w for w in results if w["expenditure_lakhs"] >= min_amount]
    if max_amount is not None:
        results = [w for w in results if w["expenditure_lakhs"] <= max_amount]
    return results


# -------------------------------------------------------------------------
# Endpoints
# -------------------------------------------------------------------------


@router.get(
    "",
    summary="List works with filtering",
)
async def list_works(
    district: Optional[str] = Query(None, description="Filter by district name"),
    block: Optional[str] = Query(None, description="Filter by block name"),
    panchayat: Optional[str] = Query(None, description="Filter by panchayat name"),
    work_type: Optional[WorkType] = Query(None, description="Filter by work type"),
    status: Optional[WorkStatus] = Query(None, description="Filter by work status"),
    fin_year: Optional[str] = Query(None, pattern=r"^\d{4}-\d{4}$", description="Financial year"),
    verification_status: Optional[VerificationStatus] = Query(None, description="Verification status filter"),
    min_amount: Optional[float] = Query(None, ge=0, description="Min expenditure in lakhs"),
    max_amount: Optional[float] = Query(None, ge=0, description="Max expenditure in lakhs"),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
) -> Dict[str, Any]:
    """List all MGNREGA works with comprehensive filtering.

    Supports filtering by geography (district, block, panchayat),
    work type, status, financial year, verification state, and
    expenditure range.  Returns paginated results.
    """
    filtered = _filter_works(
        district, block, panchayat, work_type, status,
        fin_year, verification_status, min_amount, max_amount,
    )
    total = len(filtered)
    page = filtered[skip : skip + limit]

    # Strip detail-only fields for the list view
    summary_fields = set(WorkSummary.model_fields.keys())
    summaries = [
        {k: v for k, v in w.items() if k in summary_fields}
        for w in page
    ]
    return {"total": total, "skip": skip, "limit": limit, "data": summaries}


@router.get(
    "/top-discrepancies",
    response_model=List[DiscrepancyItem],
    summary="Works with largest measurement discrepancies",
)
async def top_discrepancies(
    limit: int = Query(10, ge=1, le=50, description="Number of results"),
) -> List[Dict[str, Any]]:
    """Return works with the largest gap between reported and
    satellite-measured dimensions, sorted by discrepancy percentage.

    Useful for prioritising investigation resources.
    """
    mock_discrepancies = [
        {
            "work_id": "w-001",
            "work_name": "Rural Road Bargaon to Hesalong (3.2 km)",
            "district_name": "Gumla",
            "panchayat_name": "Bargaon",
            "reported_measurement": 11200.0,
            "satellite_measurement": 7840.0,
            "discrepancy_percent": 30.0,
            "estimated_excess_lakhs": 5.35,
            "verification_date": "2024-12-05",
        },
        {
            "work_id": "w-005",
            "work_name": "Land Levelling at Maheshpur (12 acres)",
            "district_name": "Gumla",
            "panchayat_name": "Maheshpur",
            "reported_measurement": 48562.0,
            "satellite_measurement": 28200.0,
            "discrepancy_percent": 42.0,
            "estimated_excess_lakhs": 2.82,
            "verification_date": "2024-12-10",
        },
        {
            "work_id": "w-003",
            "work_name": "Check Dam Construction at Hesalong Nala",
            "district_name": "Gumla",
            "panchayat_name": "Hesalong",
            "reported_measurement": 850.0,
            "satellite_measurement": 510.0,
            "discrepancy_percent": 40.0,
            "estimated_excess_lakhs": 3.86,
            "verification_date": "2025-01-15",
        },
        {
            "work_id": "w-004",
            "work_name": "Plantation Drive Kisko Hills (50 hectares)",
            "district_name": "Gumla",
            "panchayat_name": "Kisko",
            "reported_measurement": 500000.0,
            "satellite_measurement": 325000.0,
            "discrepancy_percent": 35.0,
            "estimated_excess_lakhs": 2.94,
            "verification_date": "2025-01-08",
        },
    ]
    mock_discrepancies.sort(key=lambda d: d["discrepancy_percent"], reverse=True)
    return mock_discrepancies[:limit]


@router.get(
    "/{work_id}",
    response_model=WorkDetail,
    summary="Get work detail",
)
async def get_work(work_id: str) -> Dict[str, Any]:
    """Return full detail for a single MGNREGA work including all
    verification data and anomaly count.
    """
    work = next((w for w in _MOCK_WORKS if w["id"] == work_id), None)
    if not work:
        raise HTTPException(status_code=404, detail=f"Work {work_id} not found")
    return work


@router.get(
    "/{work_id}/satellite",
    response_model=SatelliteData,
    summary="Satellite verification data",
)
async def get_satellite_data(work_id: str) -> Dict[str, Any]:
    """Return satellite verification data for a work.

    Includes before/after image references, area measurements,
    NDVI values, and the verification conclusion.
    """
    data = _MOCK_SATELLITE.get(work_id)
    if not data:
        # Generate a generic placeholder for works without explicit satellite data
        work = next((w for w in _MOCK_WORKS if w["id"] == work_id), None)
        if not work:
            raise HTTPException(status_code=404, detail=f"Work {work_id} not found")
        data = {
            "work_id": work_id,
            "before_image_url": f"/static/satellite/{work_id}_before.tif",
            "after_image_url": f"/static/satellite/{work_id}_after.tif",
            "before_date": work.get("start_date", "2024-06-01"),
            "after_date": work.get("completion_date", "2024-12-01") or "2025-01-01",
            "reported_area_sqm": 5000.0,
            "measured_area_sqm": 4200.0,
            "area_discrepancy_percent": 16.0,
            "ndvi_before": 0.40,
            "ndvi_after": 0.25,
            "ndvi_change": -0.15,
            "land_use_change_detected": True,
            "confidence_score": 0.75,
            "verification_result": "PENDING - Satellite analysis in progress.",
        }
    return data


@router.get(
    "/{work_id}/muster-rolls",
    summary="Muster roll data for a work",
)
async def get_muster_rolls(
    work_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
) -> Dict[str, Any]:
    """Return muster roll records associated with a work.

    Includes suspicious pattern flags and duplicate entry counts
    for forensic review.
    """
    rolls = _MOCK_MUSTER_ROLLS.get(work_id, [])
    if not rolls:
        work = next((w for w in _MOCK_WORKS if w["id"] == work_id), None)
        if not work:
            raise HTTPException(status_code=404, detail=f"Work {work_id} not found")
    total = len(rolls)
    page = rolls[skip : skip + limit]
    return {"total": total, "skip": skip, "limit": limit, "data": page}


@router.get(
    "/{work_id}/payments",
    summary="Payment records for a work",
)
async def get_payments(
    work_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> Dict[str, Any]:
    """Return payment records for a work with anomaly flags.

    Each record includes beneficiary info, FTO reference,
    payment details, and any flagged anomalies such as
    shared bank accounts or impossible attendance.
    """
    payments = _MOCK_PAYMENTS.get(work_id, [])
    if not payments:
        work = next((w for w in _MOCK_WORKS if w["id"] == work_id), None)
        if not work:
            raise HTTPException(status_code=404, detail=f"Work {work_id} not found")
    total = len(payments)
    page = payments[skip : skip + limit]
    return {"total": total, "skip": skip, "limit": limit, "data": page}


@router.get(
    "/{work_id}/photos",
    response_model=List[PhotoRecord],
    summary="Geotagged photos with verification status",
)
async def get_photos(work_id: str) -> List[Dict[str, Any]]:
    """Return all geotagged photos for a work with metadata
    verification status and AI-generated descriptions.
    """
    photos = _MOCK_PHOTOS.get(work_id, [])
    if not photos:
        work = next((w for w in _MOCK_WORKS if w["id"] == work_id), None)
        if not work:
            raise HTTPException(status_code=404, detail=f"Work {work_id} not found")
    return photos


@router.post(
    "/{work_id}/verify",
    response_model=VerifyResponse,
    status_code=202,
    summary="Trigger verification pipeline for a work",
)
async def trigger_work_verification(work_id: str) -> Dict[str, Any]:
    """Queue a full verification pipeline (satellite, muster roll,
    payment, photo) for a single work.  Returns a job ID for
    tracking progress.
    """
    work = next((w for w in _MOCK_WORKS if w["id"] == work_id), None)
    if not work:
        raise HTTPException(status_code=404, detail=f"Work {work_id} not found")

    job_id = str(uuid.uuid4())
    return {
        "job_id": job_id,
        "work_id": work_id,
        "status": "queued",
        "message": (
            f"Verification pipeline queued for work {work_id}. "
            f"Track at /api/verification/status/{job_id}"
        ),
    }
