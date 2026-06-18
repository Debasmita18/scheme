"""
Verification pipeline routes.
===============================

Endpoints for triggering individual and full-scan verification
pipelines, and for monitoring asynchronous job status and the
verification queue.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/verification", tags=["Verification"])


# -------------------------------------------------------------------------
# Enums
# -------------------------------------------------------------------------
class JobStatus(str, Enum):
    queued = "queued"
    in_progress = "in_progress"
    completed = "completed"
    failed = "failed"


class PipelineType(str, Enum):
    satellite = "satellite"
    muster_roll = "muster_roll"
    payment = "payment"
    photo = "photo"
    full_scan = "full_scan"


# -------------------------------------------------------------------------
# Pydantic schemas
# -------------------------------------------------------------------------
class VerificationTriggerResponse(BaseModel):
    job_id: str
    pipeline_type: str
    target_id: str
    status: str
    queued_at: str
    estimated_duration_minutes: int
    message: str


class JobStatusResponse(BaseModel):
    job_id: str
    pipeline_type: str
    target_id: str
    status: JobStatus
    progress_percent: float = Field(..., ge=0, le=100)
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    result_summary: Optional[str] = None
    anomalies_found: int = 0
    error_message: Optional[str] = None


class QueueItem(BaseModel):
    job_id: str
    pipeline_type: str
    target_id: str
    target_name: str
    status: JobStatus
    queued_at: str
    priority: int = Field(..., ge=1, le=5, description="1=highest, 5=lowest")
    estimated_duration_minutes: int


# -------------------------------------------------------------------------
# In-memory job store (mock)
# -------------------------------------------------------------------------
_MOCK_JOBS: Dict[str, Dict[str, Any]] = {
    "job-demo-001": {
        "job_id": "job-demo-001",
        "pipeline_type": "satellite",
        "target_id": "w-001",
        "status": "completed",
        "progress_percent": 100.0,
        "started_at": "2024-12-05T14:00:00",
        "completed_at": "2024-12-05T14:28:00",
        "result_summary": "Satellite verification complete. Area discrepancy of 30% detected. NDVI change confirms partial construction.",
        "anomalies_found": 1,
        "error_message": None,
    },
    "job-demo-002": {
        "job_id": "job-demo-002",
        "pipeline_type": "muster_roll",
        "target_id": "b-0101",
        "status": "completed",
        "progress_percent": 100.0,
        "started_at": "2024-12-06T09:30:00",
        "completed_at": "2024-12-06T10:15:00",
        "result_summary": "Muster roll forensics complete. Found 12 workers with identical attendance and 3 shared bank accounts.",
        "anomalies_found": 2,
        "error_message": None,
    },
    "job-demo-003": {
        "job_id": "job-demo-003",
        "pipeline_type": "full_scan",
        "target_id": "d-01",
        "status": "in_progress",
        "progress_percent": 62.5,
        "started_at": "2025-01-20T08:00:00",
        "completed_at": None,
        "result_summary": None,
        "anomalies_found": 5,
        "error_message": None,
    },
    "job-demo-004": {
        "job_id": "job-demo-004",
        "pipeline_type": "payment",
        "target_id": "d-01",
        "status": "queued",
        "progress_percent": 0.0,
        "started_at": None,
        "completed_at": None,
        "result_summary": None,
        "anomalies_found": 0,
        "error_message": None,
    },
}

_MOCK_QUEUE: List[Dict[str, Any]] = [
    {
        "job_id": "job-demo-003",
        "pipeline_type": "full_scan",
        "target_id": "d-01",
        "target_name": "Gumla (full scan)",
        "status": "in_progress",
        "queued_at": "2025-01-20T07:55:00",
        "priority": 1,
        "estimated_duration_minutes": 120,
    },
    {
        "job_id": "job-demo-004",
        "pipeline_type": "payment",
        "target_id": "d-01",
        "target_name": "Gumla (payment analysis)",
        "status": "queued",
        "queued_at": "2025-01-20T08:10:00",
        "priority": 2,
        "estimated_duration_minutes": 45,
    },
    {
        "job_id": str(uuid.uuid4()),
        "pipeline_type": "satellite",
        "target_id": "w-003",
        "target_name": "Check Dam Hesalong Nala (satellite)",
        "status": "queued",
        "queued_at": "2025-01-20T08:15:00",
        "priority": 3,
        "estimated_duration_minutes": 30,
    },
]


def _create_job(pipeline_type: str, target_id: str, est_minutes: int) -> Dict[str, Any]:
    """Create a new mock verification job."""
    job_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    job = {
        "job_id": job_id,
        "pipeline_type": pipeline_type,
        "target_id": target_id,
        "status": "queued",
        "queued_at": now,
        "estimated_duration_minutes": est_minutes,
        "message": (
            f"{pipeline_type.replace('_', ' ').title()} verification queued "
            f"for {target_id}. Estimated time: {est_minutes} minutes. "
            f"Track at /api/verification/status/{job_id}"
        ),
    }
    _MOCK_JOBS[job_id] = {
        **job,
        "progress_percent": 0.0,
        "started_at": None,
        "completed_at": None,
        "result_summary": None,
        "anomalies_found": 0,
        "error_message": None,
    }
    return job


# -------------------------------------------------------------------------
# Endpoints
# -------------------------------------------------------------------------


@router.post(
    "/satellite/{work_id}",
    response_model=VerificationTriggerResponse,
    status_code=202,
    summary="Run satellite verification for a work",
)
async def satellite_verification(work_id: str) -> Dict[str, Any]:
    """Queue satellite imagery analysis for a single work.

    Downloads before/after Sentinel-2 imagery, performs NDVI change
    detection and earthwork boundary measurement, and compares with
    reported dimensions.  Typical duration: 15-30 minutes.
    """
    return _create_job("satellite", work_id, est_minutes=25)


@router.post(
    "/muster-roll/{block_id}",
    response_model=VerificationTriggerResponse,
    status_code=202,
    summary="Run muster roll forensics for a block",
)
async def muster_roll_verification(block_id: str) -> Dict[str, Any]:
    """Queue muster roll forensic analysis for all works in a block.

    Checks for duplicate attendance, ghost workers, impossible
    patterns, shared bank accounts, and statistical outliers.
    Typical duration: 30-60 minutes depending on block size.
    """
    return _create_job("muster_roll", block_id, est_minutes=45)


@router.post(
    "/payment/{district_id}",
    response_model=VerificationTriggerResponse,
    status_code=202,
    summary="Run payment pattern analysis for a district",
)
async def payment_verification(district_id: str) -> Dict[str, Any]:
    """Queue payment network and pattern analysis for a district.

    Applies Benford's Law testing, payment graph community detection,
    duplicate detection, and wage anomaly scoring across all FTO
    records.  Typical duration: 30-60 minutes.
    """
    return _create_job("payment", district_id, est_minutes=50)


@router.post(
    "/photo/{work_id}",
    response_model=VerificationTriggerResponse,
    status_code=202,
    summary="Run photo verification for a work",
)
async def photo_verification(work_id: str) -> Dict[str, Any]:
    """Queue geotagged photo verification for a work.

    Validates EXIF metadata integrity, compares GPS coordinates
    with worksite location, runs reverse image search for duplicates,
    and generates AI descriptions.  Typical duration: 5-15 minutes.
    """
    return _create_job("photo", work_id, est_minutes=10)


@router.post(
    "/full-scan/{district_id}",
    response_model=VerificationTriggerResponse,
    status_code=202,
    summary="Run complete verification pipeline for a district",
)
async def full_scan(district_id: str) -> Dict[str, Any]:
    """Queue the full multi-dimensional verification pipeline for
    every work in a district.

    Runs satellite, muster roll, payment, and photo verification
    in sequence, then performs cross-correlation analysis.
    This is the most comprehensive but also the longest-running
    pipeline.  Typical duration: 2-4 hours for a medium district.
    """
    return _create_job("full_scan", district_id, est_minutes=180)


@router.get(
    "/status/{job_id}",
    response_model=JobStatusResponse,
    summary="Check verification job status",
)
async def get_job_status(job_id: str) -> Dict[str, Any]:
    """Poll the status of an asynchronous verification job.

    Returns progress percentage, result summary (if complete),
    number of anomalies found, and any error information.
    """
    job = _MOCK_JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    # Return relevant fields for the status response
    return {
        "job_id": job["job_id"],
        "pipeline_type": job["pipeline_type"],
        "target_id": job["target_id"],
        "status": job["status"],
        "progress_percent": job["progress_percent"],
        "started_at": job.get("started_at"),
        "completed_at": job.get("completed_at"),
        "result_summary": job.get("result_summary"),
        "anomalies_found": job.get("anomalies_found", 0),
        "error_message": job.get("error_message"),
    }


@router.get(
    "/queue",
    response_model=List[QueueItem],
    summary="Get pending verification jobs",
)
async def get_queue() -> List[Dict[str, Any]]:
    """Return all queued and in-progress verification jobs,
    sorted by priority (highest first) then queue time.
    """
    queue = sorted(
        _MOCK_QUEUE,
        key=lambda q: (q["priority"], q["queued_at"]),
    )
    return queue
