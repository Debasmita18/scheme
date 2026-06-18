"""
Anomaly detection routes.
==========================

Endpoints for listing, filtering, and investigating detected anomalies
across satellite, muster-roll, payment, and photo verification
dimensions.  Includes trend analysis and geographic hotspot mapping.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/anomalies", tags=["Anomalies"])


# -------------------------------------------------------------------------
# Enums
# -------------------------------------------------------------------------
class AnomalyType(str, Enum):
    measurement_discrepancy = "measurement_discrepancy"
    ghost_workers = "ghost_workers"
    duplicate_payments = "duplicate_payments"
    attendance_fraud = "attendance_fraud"
    photo_metadata_tampered = "photo_metadata_tampered"
    inflated_expenditure = "inflated_expenditure"
    benford_violation = "benford_violation"
    payment_clustering = "payment_clustering"
    gps_mismatch = "gps_mismatch"
    work_not_found = "work_not_found"


class AnomalySeverity(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class AnomalyStatusEnum(str, Enum):
    flagged = "flagged"
    investigating = "investigating"
    confirmed = "confirmed"
    dismissed = "dismissed"


# -------------------------------------------------------------------------
# Pydantic schemas
# -------------------------------------------------------------------------
class AnomalySummary(BaseModel):
    id: str
    anomaly_type: AnomalyType
    severity: AnomalySeverity
    status: AnomalyStatusEnum
    title: str
    district_name: str
    panchayat_name: str
    work_id: Optional[str] = None
    work_name: Optional[str] = None
    estimated_amount_lakhs: float
    detected_at: str
    confidence_score: float = Field(..., ge=0, le=1)


class AnomalyDetail(BaseModel):
    id: str
    anomaly_type: AnomalyType
    severity: AnomalySeverity
    status: AnomalyStatusEnum
    title: str
    description: str
    district_name: str
    district_id: str
    block_name: str
    panchayat_name: str
    panchayat_id: str
    work_id: Optional[str] = None
    work_name: Optional[str] = None
    estimated_amount_lakhs: float
    detected_at: str
    confidence_score: float
    evidence: List[Dict[str, Any]]
    related_anomaly_ids: List[str]
    investigation_notes: Optional[str] = None


class AnomalyStats(BaseModel):
    total_anomalies: int
    by_type: Dict[str, int]
    by_severity: Dict[str, int]
    by_status: Dict[str, int]
    total_estimated_amount_lakhs: float
    avg_confidence_score: float


class AnomalyTypeInfo(BaseModel):
    anomaly_type: str
    display_name: str
    description: str
    count: int
    avg_amount_lakhs: float


class StatusUpdateRequest(BaseModel):
    status: AnomalyStatusEnum
    notes: Optional[str] = Field(None, max_length=2000, description="Investigation notes")


class StatusUpdateResponse(BaseModel):
    id: str
    previous_status: str
    new_status: str
    updated_at: str


class TrendPoint(BaseModel):
    period: str
    total_detected: int
    by_type: Dict[str, int]
    estimated_amount_lakhs: float


class HotspotCluster(BaseModel):
    cluster_id: str
    latitude: float
    longitude: float
    radius_km: float
    anomaly_count: int
    dominant_type: AnomalyType
    severity_breakdown: Dict[str, int]
    total_estimated_lakhs: float
    panchayats: List[str]


class PaginatedResponse(BaseModel):
    total: int
    skip: int
    limit: int
    data: List[Any]


# -------------------------------------------------------------------------
# Mock data
# -------------------------------------------------------------------------
_MOCK_ANOMALIES: List[Dict[str, Any]] = [
    {
        "id": "anom-001",
        "anomaly_type": "measurement_discrepancy",
        "severity": "critical",
        "status": "investigating",
        "title": "Road length inflated by 30% at Bargaon",
        "description": "Satellite measurement of rural road JH-34-3407-001-2425 shows actual construction of 2.24 km against reported 3.2 km. The road surface width also measures 2.8m vs reported 3.5m. Total area discrepancy is 30%, indicating possible over-reporting of physical work.",
        "district_name": "Gumla",
        "district_id": "d-01",
        "block_name": "Bishunpur",
        "panchayat_name": "Bargaon",
        "panchayat_id": "gp-010101",
        "work_id": "w-001",
        "work_name": "Rural Road Bargaon to Hesalong (3.2 km)",
        "estimated_amount_lakhs": 5.35,
        "detected_at": "2024-12-05T14:30:00",
        "confidence_score": 0.87,
        "evidence": [
            {"type": "satellite_comparison", "description": "Sentinel-2 imagery from 2024-12-01 shows road length 2.24 km", "source": "Copernicus Sentinel-2"},
            {"type": "area_measurement", "description": "Measured area 7840 sqm vs reported 11200 sqm", "source": "GeoTIFF analysis"},
            {"type": "ndvi_analysis", "description": "NDVI change confirms land disturbance along shorter path only", "source": "NDVI pipeline"},
        ],
        "related_anomaly_ids": ["anom-002"],
        "investigation_notes": "Field inspection recommended. Local informant reports incomplete road section near km 2.5.",
    },
    {
        "id": "anom-002",
        "anomaly_type": "attendance_fraud",
        "severity": "high",
        "status": "flagged",
        "title": "Identical attendance patterns for 12 workers at Bargaon road",
        "description": "Muster roll analysis for work JH-34-3407-001-2425 reveals 12 workers with perfectly identical attendance records across 45 days. Statistical probability of this pattern occurring naturally is less than 0.001%. Three of these workers share the same bank account.",
        "district_name": "Gumla",
        "district_id": "d-01",
        "block_name": "Bishunpur",
        "panchayat_name": "Bargaon",
        "panchayat_id": "gp-010101",
        "work_id": "w-001",
        "work_name": "Rural Road Bargaon to Hesalong (3.2 km)",
        "estimated_amount_lakhs": 1.73,
        "detected_at": "2024-12-06T10:15:00",
        "confidence_score": 0.94,
        "evidence": [
            {"type": "attendance_analysis", "description": "12 workers with 100% identical attendance for 45 days", "source": "Muster roll forensics"},
            {"type": "bank_account_link", "description": "3 job cards (JH-34-001-00145, 00178, 00199) credited to same account ending 7823", "source": "Payment analysis"},
            {"type": "statistical_test", "description": "Chi-squared test p-value < 0.001 for attendance correlation", "source": "Statistical engine"},
        ],
        "related_anomaly_ids": ["anom-001"],
        "investigation_notes": None,
    },
    {
        "id": "anom-003",
        "anomaly_type": "ghost_workers",
        "severity": "critical",
        "status": "confirmed",
        "title": "5 workers aged 82-91 on Hesalong check dam muster roll",
        "description": "Muster roll for check dam construction at Hesalong Nala shows 5 workers with ages between 82 and 91 years performing heavy manual labor continuously for 21 days. Cross-reference with Aadhaar records shows 2 of these individuals are deceased.",
        "district_name": "Gumla",
        "district_id": "d-01",
        "block_name": "Chainpur",
        "panchayat_name": "Hesalong",
        "panchayat_id": "gp-010103",
        "work_id": "w-003",
        "work_name": "Check Dam Construction at Hesalong Nala",
        "estimated_amount_lakhs": 0.96,
        "detected_at": "2025-01-10T09:45:00",
        "confidence_score": 0.98,
        "evidence": [
            {"type": "age_verification", "description": "5 workers aged 82-91 on manual labor muster roll", "source": "NREGA demographic data"},
            {"type": "mortality_crosscheck", "description": "2 workers confirmed deceased per civil records", "source": "Registrar General cross-reference"},
            {"type": "continuous_attendance", "description": "All 5 show 21/21 day attendance", "source": "Muster roll forensics"},
        ],
        "related_anomaly_ids": ["anom-005"],
        "investigation_notes": "Confirmed ghost workers. Case file generated. FIR recommended.",
    },
    {
        "id": "anom-004",
        "anomaly_type": "photo_metadata_tampered",
        "severity": "medium",
        "status": "flagged",
        "title": "Completion photo GPS 3.2 km from worksite at Bargaon",
        "description": "The completion photo for Bargaon road work has stripped EXIF metadata and the GPS coordinates place it 3.2 km away from the actual worksite. The photo appears to be a stock or reused image from a different project.",
        "district_name": "Gumla",
        "district_id": "d-01",
        "block_name": "Bishunpur",
        "panchayat_name": "Bargaon",
        "panchayat_id": "gp-010101",
        "work_id": "w-001",
        "work_name": "Rural Road Bargaon to Hesalong (3.2 km)",
        "estimated_amount_lakhs": 0.0,
        "detected_at": "2024-12-07T16:20:00",
        "confidence_score": 0.82,
        "evidence": [
            {"type": "gps_analysis", "description": "Photo GPS: 23.098, 84.578 vs worksite: 23.045, 84.532 (3.2 km)", "source": "Photo verification"},
            {"type": "metadata_check", "description": "EXIF metadata stripped, no camera model or timestamp", "source": "Metadata analyzer"},
            {"type": "reverse_image_search", "description": "No duplicate found, but image quality inconsistent with field photo", "source": "Image analysis"},
        ],
        "related_anomaly_ids": ["anom-001"],
        "investigation_notes": None,
    },
    {
        "id": "anom-005",
        "anomaly_type": "inflated_expenditure",
        "severity": "high",
        "status": "investigating",
        "title": "Check dam expenditure 75% without visible progress",
        "description": "Work JH-34-3407-003-2425 shows 75.4% expenditure (9.65L of 12.80L sanctioned) but satellite imagery shows construction progress of approximately 30%. The expenditure-to-progress ratio is 2.5x the district average for similar works.",
        "district_name": "Gumla",
        "district_id": "d-01",
        "block_name": "Chainpur",
        "panchayat_name": "Hesalong",
        "panchayat_id": "gp-010103",
        "work_id": "w-003",
        "work_name": "Check Dam Construction at Hesalong Nala",
        "estimated_amount_lakhs": 5.79,
        "detected_at": "2025-01-15T11:30:00",
        "confidence_score": 0.79,
        "evidence": [
            {"type": "expenditure_analysis", "description": "75.4% expenditure vs ~30% physical progress", "source": "Financial analysis"},
            {"type": "satellite_progress", "description": "Sentinel-2 change detection shows limited construction activity", "source": "Satellite pipeline"},
            {"type": "benchmark_comparison", "description": "Expenditure ratio 2.5x district average for check dams", "source": "Statistical benchmarking"},
        ],
        "related_anomaly_ids": ["anom-003"],
        "investigation_notes": "Under investigation. Material costs audit in progress.",
    },
    {
        "id": "anom-006",
        "anomaly_type": "benford_violation",
        "severity": "medium",
        "status": "flagged",
        "title": "Payment amounts violate Benford's Law in Gumla block",
        "description": "Analysis of 402 payment records in Gumla block reveals significant deviation from Benford's Law for first-digit distribution. Leading digit '3' appears 28.4% of the time (expected ~12.5%), suggesting systematic manipulation of payment amounts.",
        "district_name": "Gumla",
        "district_id": "d-01",
        "block_name": "Gumla",
        "panchayat_name": "Maheshpur",
        "panchayat_id": "gp-010106",
        "work_id": None,
        "work_name": None,
        "estimated_amount_lakhs": 8.12,
        "detected_at": "2025-01-20T08:00:00",
        "confidence_score": 0.71,
        "evidence": [
            {"type": "benford_test", "description": "Chi-squared p=0.002 for first-digit distribution; digit 3 at 28.4%", "source": "Statistical anomaly engine"},
            {"type": "payment_histogram", "description": "Clustering of payments around Rs 3200 (daily wage x 10 days)", "source": "Payment analysis"},
        ],
        "related_anomaly_ids": [],
        "investigation_notes": None,
    },
    {
        "id": "anom-007",
        "anomaly_type": "payment_clustering",
        "severity": "high",
        "status": "flagged",
        "title": "8 payments on same date to sequential bank accounts in Maheshpur",
        "description": "Eight payments totalling Rs 76,800 were made on the same date to bank accounts with sequential account numbers. This pattern is consistent with fake beneficiaries created at the same branch.",
        "district_name": "Gumla",
        "district_id": "d-01",
        "block_name": "Gumla",
        "panchayat_name": "Maheshpur",
        "panchayat_id": "gp-010106",
        "work_id": "w-005",
        "work_name": "Land Levelling at Maheshpur (12 acres)",
        "estimated_amount_lakhs": 0.77,
        "detected_at": "2025-01-22T14:15:00",
        "confidence_score": 0.88,
        "evidence": [
            {"type": "account_analysis", "description": "8 accounts with sequential numbers at SBI Gumla branch", "source": "Payment network analysis"},
            {"type": "timing_analysis", "description": "All 8 payments in same FTO batch on 2024-09-15", "source": "FTO analysis"},
            {"type": "graph_clustering", "description": "Community detection identified tight cluster in payment graph", "source": "NetworkX graph engine"},
        ],
        "related_anomaly_ids": ["anom-006"],
        "investigation_notes": None,
    },
    {
        "id": "anom-008",
        "anomaly_type": "work_not_found",
        "severity": "critical",
        "status": "flagged",
        "title": "No land-use change detected for Kisko plantation (50 ha)",
        "description": "Satellite NDVI analysis of the 50-hectare Kisko Hills plantation area shows negligible vegetation change between the reported planting period and 6 months later. Expected NDVI increase of 0.15-0.25 not observed. The area appears largely unchanged.",
        "district_name": "Gumla",
        "district_id": "d-01",
        "block_name": "Ghaghra",
        "panchayat_name": "Kisko",
        "panchayat_id": "gp-010105",
        "work_id": "w-004",
        "work_name": "Plantation Drive Kisko Hills (50 hectares)",
        "estimated_amount_lakhs": 8.35,
        "detected_at": "2025-01-08T10:00:00",
        "confidence_score": 0.76,
        "evidence": [
            {"type": "ndvi_analysis", "description": "NDVI change: +0.02 (expected +0.15 to +0.25 for successful plantation)", "source": "NDVI pipeline"},
            {"type": "area_comparison", "description": "Only 35% of reported 50-hectare area shows any vegetation change", "source": "Satellite analysis"},
        ],
        "related_anomaly_ids": [],
        "investigation_notes": None,
    },
]

_ANOMALY_TYPE_INFO: List[Dict[str, Any]] = [
    {"anomaly_type": "measurement_discrepancy", "display_name": "Measurement Discrepancy", "description": "Reported physical dimensions (length, area, volume) differ significantly from satellite measurements.", "count": 1, "avg_amount_lakhs": 5.35},
    {"anomaly_type": "ghost_workers", "display_name": "Ghost Workers", "description": "Workers on muster rolls who are deceased, underage, overage, or otherwise unable to perform the recorded work.", "count": 1, "avg_amount_lakhs": 0.96},
    {"anomaly_type": "duplicate_payments", "display_name": "Duplicate Payments", "description": "Multiple payments to the same beneficiary for the same period or identical amounts paid repeatedly.", "count": 0, "avg_amount_lakhs": 0.0},
    {"anomaly_type": "attendance_fraud", "display_name": "Attendance Fraud", "description": "Statistically improbable attendance patterns such as identical records across multiple workers.", "count": 1, "avg_amount_lakhs": 1.73},
    {"anomaly_type": "photo_metadata_tampered", "display_name": "Photo Metadata Tampered", "description": "Geotagged photos with stripped metadata, impossible GPS coordinates, or evidence of reuse.", "count": 1, "avg_amount_lakhs": 0.0},
    {"anomaly_type": "inflated_expenditure", "display_name": "Inflated Expenditure", "description": "Expenditure significantly exceeds physical progress as measured by satellite or field inspection.", "count": 1, "avg_amount_lakhs": 5.79},
    {"anomaly_type": "benford_violation", "display_name": "Benford's Law Violation", "description": "Payment or expenditure amounts deviate from expected first-digit distribution, suggesting data fabrication.", "count": 1, "avg_amount_lakhs": 8.12},
    {"anomaly_type": "payment_clustering", "display_name": "Payment Clustering", "description": "Suspicious patterns in payment networks such as sequential accounts, round amounts, or timing clusters.", "count": 1, "avg_amount_lakhs": 0.77},
    {"anomaly_type": "gps_mismatch", "display_name": "GPS Mismatch", "description": "Reported worksite GPS coordinates do not match satellite-detected construction activity.", "count": 0, "avg_amount_lakhs": 0.0},
    {"anomaly_type": "work_not_found", "display_name": "Work Not Found", "description": "Satellite analysis finds no evidence of reported construction or land modification at the worksite.", "count": 1, "avg_amount_lakhs": 8.35},
]


def _get_mock_anomaly(anomaly_id: str) -> Optional[Dict[str, Any]]:
    return next((a for a in _MOCK_ANOMALIES if a["id"] == anomaly_id), None)


# -------------------------------------------------------------------------
# Endpoints
# -------------------------------------------------------------------------


@router.get(
    "",
    summary="List all detected anomalies",
)
async def list_anomalies(
    anomaly_type: Optional[AnomalyType] = Query(None, description="Filter by anomaly type"),
    severity: Optional[AnomalySeverity] = Query(None, description="Filter by severity"),
    district: Optional[str] = Query(None, description="Filter by district name"),
    status: Optional[AnomalyStatusEnum] = Query(None, description="Filter by status"),
    date_from: Optional[str] = Query(None, description="Start date (ISO format)"),
    date_to: Optional[str] = Query(None, description="End date (ISO format)"),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
) -> Dict[str, Any]:
    """List all detected anomalies with comprehensive filtering.

    Filter by anomaly type, severity level, district, investigation
    status, and date range.  Results are sorted by detection date
    (newest first) and paginated.
    """
    data = list(_MOCK_ANOMALIES)

    if anomaly_type:
        data = [a for a in data if a["anomaly_type"] == anomaly_type.value]
    if severity:
        data = [a for a in data if a["severity"] == severity.value]
    if district:
        data = [a for a in data if district.lower() in a["district_name"].lower()]
    if status:
        data = [a for a in data if a["status"] == status.value]
    if date_from:
        data = [a for a in data if a["detected_at"] >= date_from]
    if date_to:
        data = [a for a in data if a["detected_at"] <= date_to]

    # Sort by detection date descending
    data.sort(key=lambda a: a["detected_at"], reverse=True)

    total = len(data)
    page = data[skip : skip + limit]

    # Strip heavy fields for list view
    summary_fields = set(AnomalySummary.model_fields.keys())
    summaries = [{k: v for k, v in a.items() if k in summary_fields} for a in page]

    return {"total": total, "skip": skip, "limit": limit, "data": summaries}


@router.get(
    "/summary",
    response_model=AnomalyStats,
    summary="Aggregated anomaly statistics",
)
async def anomaly_summary() -> Dict[str, Any]:
    """Return aggregated anomaly counts by type, severity, and status,
    along with the total estimated financial impact.
    """
    by_type: Dict[str, int] = {}
    by_severity: Dict[str, int] = {}
    by_status: Dict[str, int] = {}
    total_amount = 0.0
    total_confidence = 0.0

    for a in _MOCK_ANOMALIES:
        by_type[a["anomaly_type"]] = by_type.get(a["anomaly_type"], 0) + 1
        by_severity[a["severity"]] = by_severity.get(a["severity"], 0) + 1
        by_status[a["status"]] = by_status.get(a["status"], 0) + 1
        total_amount += a["estimated_amount_lakhs"]
        total_confidence += a["confidence_score"]

    n = len(_MOCK_ANOMALIES) or 1
    return {
        "total_anomalies": len(_MOCK_ANOMALIES),
        "by_type": by_type,
        "by_severity": by_severity,
        "by_status": by_status,
        "total_estimated_amount_lakhs": round(total_amount, 2),
        "avg_confidence_score": round(total_confidence / n, 3),
    }


@router.get(
    "/types",
    response_model=List[AnomalyTypeInfo],
    summary="Anomaly types with descriptions and counts",
)
async def anomaly_types() -> List[Dict[str, Any]]:
    """Return all anomaly type definitions with human-readable names,
    descriptions, current counts, and average financial impact.
    """
    return _ANOMALY_TYPE_INFO


@router.get(
    "/trends",
    response_model=List[TrendPoint],
    summary="Time-series of anomaly detection rates",
)
async def anomaly_trends(
    months: int = Query(6, ge=1, le=24, description="Number of months of trend data"),
) -> List[Dict[str, Any]]:
    """Return monthly anomaly detection counts and estimated amounts
    for trend visualisation on the dashboard.
    """
    import random

    random.seed(42)  # deterministic mock data
    base_months = [
        "2024-08", "2024-09", "2024-10", "2024-11", "2024-12", "2025-01",
        "2025-02", "2025-03", "2025-04", "2025-05", "2025-06", "2025-07",
    ]
    selected = base_months[:months]
    trends = []
    for m in selected:
        total = random.randint(3, 18)
        trends.append({
            "period": m,
            "total_detected": total,
            "by_type": {
                "measurement_discrepancy": random.randint(0, 4),
                "ghost_workers": random.randint(0, 3),
                "attendance_fraud": random.randint(0, 5),
                "inflated_expenditure": random.randint(0, 3),
                "payment_clustering": random.randint(0, 2),
                "benford_violation": random.randint(0, 2),
            },
            "estimated_amount_lakhs": round(random.uniform(2.0, 25.0), 2),
        })
    return trends


@router.get(
    "/hotspots",
    response_model=List[HotspotCluster],
    summary="Geographic clusters of anomalies",
)
async def anomaly_hotspots() -> List[Dict[str, Any]]:
    """Return geographic anomaly clusters for heatmap/cluster
    visualisation.  Each cluster has a centre point, radius,
    dominant anomaly type, and affected panchayats.
    """
    return [
        {
            "cluster_id": "hs-01",
            "latitude": 23.055,
            "longitude": 84.535,
            "radius_km": 5.2,
            "anomaly_count": 4,
            "dominant_type": "measurement_discrepancy",
            "severity_breakdown": {"critical": 1, "high": 1, "medium": 2},
            "total_estimated_lakhs": 7.08,
            "panchayats": ["Bargaon", "Dumardaga"],
        },
        {
            "cluster_id": "hs-02",
            "latitude": 23.095,
            "longitude": 84.510,
            "radius_km": 3.8,
            "anomaly_count": 3,
            "dominant_type": "ghost_workers",
            "severity_breakdown": {"critical": 2, "high": 1},
            "total_estimated_lakhs": 6.75,
            "panchayats": ["Hesalong", "Jurmu"],
        },
        {
            "cluster_id": "hs-03",
            "latitude": 23.020,
            "longitude": 84.590,
            "radius_km": 4.5,
            "anomaly_count": 3,
            "dominant_type": "payment_clustering",
            "severity_breakdown": {"high": 2, "medium": 1},
            "total_estimated_lakhs": 8.89,
            "panchayats": ["Maheshpur", "Nagri"],
        },
    ]


@router.get(
    "/{anomaly_id}",
    response_model=AnomalyDetail,
    summary="Get anomaly detail with full evidence",
)
async def get_anomaly(anomaly_id: str) -> Dict[str, Any]:
    """Return the full detail for a single anomaly, including all
    evidence records, related anomaly cross-references, and
    investigation notes.
    """
    anomaly = _get_mock_anomaly(anomaly_id)
    if not anomaly:
        raise HTTPException(status_code=404, detail=f"Anomaly {anomaly_id} not found")
    return anomaly


@router.put(
    "/{anomaly_id}/status",
    response_model=StatusUpdateResponse,
    summary="Update anomaly investigation status",
)
async def update_anomaly_status(
    anomaly_id: str,
    body: StatusUpdateRequest,
) -> Dict[str, Any]:
    """Update the investigation status of an anomaly.

    Valid transitions: flagged -> investigating -> confirmed/dismissed.
    Optionally attach investigation notes.
    """
    anomaly = _get_mock_anomaly(anomaly_id)
    if not anomaly:
        raise HTTPException(status_code=404, detail=f"Anomaly {anomaly_id} not found")

    previous = anomaly["status"]

    # In mock mode, just update in-memory
    anomaly["status"] = body.status.value
    if body.notes:
        anomaly["investigation_notes"] = body.notes

    return {
        "id": anomaly_id,
        "previous_status": previous,
        "new_status": body.status.value,
        "updated_at": datetime.utcnow().isoformat(),
    }
