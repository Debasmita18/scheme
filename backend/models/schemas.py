"""
Pydantic schemas for API request/response models.

These schemas handle serialization of PostGIS geometry fields and provide
validated, typed data transfer objects for the MGNREGA Verification API.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ===========================================================================
# Geometry helpers
# ===========================================================================

class GeoJSONPoint(BaseModel):
    """GeoJSON Point representation."""
    type: str = "Point"
    coordinates: list[float] = Field(
        ..., min_length=2, max_length=3,
        description="[longitude, latitude] or [longitude, latitude, altitude]",
    )


class GeoJSONPolygon(BaseModel):
    """GeoJSON Polygon representation."""
    type: str = "Polygon"
    coordinates: list[list[list[float]]] = Field(
        ..., description="Array of linear rings. First ring is exterior.",
    )


# ===========================================================================
# Enum mirrors (for schema docs -- re-exported from database module values)
# ===========================================================================

class WorkTypeSchema(str, Enum):
    ROAD_CONSTRUCTION = "road_construction"
    WATER_CONSERVATION = "water_conservation"
    LAND_DEVELOPMENT = "land_development"
    FLOOD_CONTROL = "flood_control"
    DROUGHT_PROOFING = "drought_proofing"
    MICRO_IRRIGATION = "micro_irrigation"
    RURAL_CONNECTIVITY = "rural_connectivity"
    PLANTATION = "plantation"
    HOUSE_CONSTRUCTION_IAY = "house_construction_iay"
    TOILET_CONSTRUCTION = "toilet_construction"
    CATTLE_SHED = "cattle_shed"
    FISHERY = "fishery"
    RURAL_SANITATION = "rural_sanitation"
    ANGANWADI_CONSTRUCTION = "anganwadi_construction"
    PLAY_FIELD = "play_field"
    OTHER = "other"


class WorkStatusSchema(str, Enum):
    SANCTIONED = "sanctioned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    INSPECTION_PENDING = "inspection_pending"
    VERIFIED = "verified"
    SUSPENDED = "suspended"
    CANCELLED = "cancelled"


class AnomalyTypeSchema(str, Enum):
    AREA_MISMATCH = "area_mismatch"
    GHOST_WORKER = "ghost_worker"
    DUPLICATE_PAYMENT = "duplicate_payment"
    INFLATED_MEASUREMENT = "inflated_measurement"
    ATTENDANCE_FRAUD = "attendance_fraud"
    GPS_SPOOFING = "gps_spoofing"
    PHOTO_MANIPULATION = "photo_manipulation"
    MATERIAL_COST_INFLATION = "material_cost_inflation"
    BENAMI_WORK = "benami_work"
    WORK_NOT_FOUND = "work_not_found"
    NDVI_NO_CHANGE = "ndvi_no_change"
    PAYMENT_TO_DECEASED = "payment_to_deceased"
    DUPLICATE_JOB_CARD = "duplicate_job_card"
    WAGE_LIST_TAMPERING = "wage_list_tampering"
    FTO_MISMATCH = "fto_mismatch"
    SUSPICIOUS_DATE_PATTERN = "suspicious_date_pattern"


class AnomalySeveritySchema(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AnomalyStatusSchema(str, Enum):
    DETECTED = "detected"
    UNDER_REVIEW = "under_review"
    CONFIRMED = "confirmed"
    FALSE_POSITIVE = "false_positive"
    ESCALATED = "escalated"
    RESOLVED = "resolved"


class VerificationStatusSchema(str, Enum):
    PENDING = "pending"
    VERIFIED = "verified"
    MISMATCH_DETECTED = "mismatch_detected"
    INCONCLUSIVE = "inconclusive"
    FAILED = "failed"


class InvestigationStatusSchema(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    EVIDENCE_COLLECTED = "evidence_collected"
    REPORT_GENERATED = "report_generated"
    SUBMITTED = "submitted"
    CLOSED_CONFIRMED = "closed_confirmed"
    CLOSED_CLEARED = "closed_cleared"


# ===========================================================================
# Administrative hierarchy responses
# ===========================================================================

class DistrictResponse(BaseModel):
    """Response schema for a District."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    state_code: str
    state_name: str
    district_code: str
    district_name: str
    is_active: bool
    created_at: datetime
    block_count: Optional[int] = Field(default=None, description="Number of blocks (populated when requested)")


class BlockResponse(BaseModel):
    """Response schema for a Block."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    district_id: int
    block_code: str
    block_name: str
    is_active: bool
    created_at: datetime
    district_name: Optional[str] = None
    gp_count: Optional[int] = Field(default=None, description="Number of gram panchayats")


class GPResponse(BaseModel):
    """Response schema for a Gram Panchayat."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    block_id: int
    gp_code: str
    gp_name: str
    total_job_cards: Optional[int] = None
    total_workers: Optional[int] = None
    is_active: bool
    created_at: datetime
    block_name: Optional[str] = None
    district_name: Optional[str] = None
    work_count: Optional[int] = Field(default=None, description="Number of works in this GP")


# ===========================================================================
# Work schemas
# ===========================================================================

class WorkCreate(BaseModel):
    """Schema for creating a new MGNREGA work entry."""

    gp_id: int = Field(..., description="Gram Panchayat ID")
    work_code: str = Field(..., min_length=5, max_length=50, description="Unique NREGA work code")
    work_name: str = Field(..., min_length=3, max_length=500)
    work_type: WorkTypeSchema
    work_category: Optional[str] = None
    financial_year: str = Field(..., pattern=r"^\d{4}-\d{4}$", description="e.g. 2024-2025")

    sanctioned_amount: float = Field(..., gt=0, description="Amount sanctioned in INR")
    expenditure_amount: Optional[float] = Field(default=None, ge=0)
    wage_component: Optional[float] = Field(default=None, ge=0)
    material_component: Optional[float] = Field(default=None, ge=0)

    reported_length_m: Optional[float] = Field(default=None, ge=0)
    reported_width_m: Optional[float] = Field(default=None, ge=0)
    reported_depth_m: Optional[float] = Field(default=None, ge=0)
    reported_area_sqm: Optional[float] = Field(default=None, ge=0)
    reported_volume_cum: Optional[float] = Field(default=None, ge=0)

    sanction_date: Optional[date] = None
    start_date: Optional[date] = None
    completion_date: Optional[date] = None

    reported_latitude: Optional[float] = Field(default=None, ge=6.0, le=37.0, description="Latitude within India")
    reported_longitude: Optional[float] = Field(default=None, ge=68.0, le=98.0, description="Longitude within India")
    work_boundary: Optional[GeoJSONPolygon] = Field(default=None, description="GeoJSON polygon of the work boundary")

    status: WorkStatusSchema = WorkStatusSchema.SANCTIONED
    total_person_days: Optional[int] = Field(default=None, ge=0)
    total_workers_employed: Optional[int] = Field(default=None, ge=0)

    @field_validator("financial_year")
    @classmethod
    def _validate_financial_year(cls, v: str) -> str:
        parts = v.split("-")
        start, end = int(parts[0]), int(parts[1])
        if end != start + 1:
            raise ValueError("Financial year end must be start + 1 (e.g. 2024-2025)")
        if start < 2006:
            raise ValueError("MGNREGA was enacted in 2006; financial year cannot predate it")
        return v


class WorkResponse(BaseModel):
    """Response schema for a work entry."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    gp_id: int
    work_code: str
    work_name: str
    work_type: WorkTypeSchema
    work_category: Optional[str] = None
    financial_year: str

    sanctioned_amount: float
    expenditure_amount: Optional[float] = None
    wage_component: Optional[float] = None
    material_component: Optional[float] = None

    reported_length_m: Optional[float] = None
    reported_width_m: Optional[float] = None
    reported_depth_m: Optional[float] = None
    reported_area_sqm: Optional[float] = None
    reported_volume_cum: Optional[float] = None

    sanction_date: Optional[date] = None
    start_date: Optional[date] = None
    completion_date: Optional[date] = None

    reported_latitude: Optional[float] = None
    reported_longitude: Optional[float] = None
    location: Optional[GeoJSONPoint] = None

    status: WorkStatusSchema
    total_person_days: Optional[int] = None
    total_workers_employed: Optional[int] = None
    risk_score: Optional[float] = None

    created_at: datetime
    updated_at: datetime

    # Populated from relationships on demand
    gp_name: Optional[str] = None
    block_name: Optional[str] = None
    district_name: Optional[str] = None
    anomaly_count: Optional[int] = None


class WorkWithVerification(WorkResponse):
    """Extended work response including satellite verification and anomaly details."""

    satellite_verifications: list["SatelliteComparisonResponse"] = Field(default_factory=list)
    anomalies: list["AnomalyResponse"] = Field(default_factory=list)
    photo_records: list["PhotoRecordResponse"] = Field(default_factory=list)


# ===========================================================================
# Anomaly schemas
# ===========================================================================

class AnomalyResponse(BaseModel):
    """Summary response for an anomaly record."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    work_id: int
    anomaly_type: AnomalyTypeSchema
    severity: AnomalySeveritySchema
    status: AnomalyStatusSchema
    title: str
    confidence_score: Optional[float] = None
    estimated_loss_inr: Optional[float] = None
    detected_at: datetime
    created_at: datetime


class AnomalyDetail(AnomalyResponse):
    """Detailed anomaly record including evidence and resolution info."""

    description: Optional[str] = None
    evidence_json: Optional[dict[str, Any]] = None
    resolved_by: Optional[str] = None
    resolved_at: Optional[datetime] = None
    resolution_notes: Optional[str] = None
    work_code: Optional[str] = None
    work_name: Optional[str] = None
    gp_name: Optional[str] = None


# ===========================================================================
# Verification / Satellite schemas
# ===========================================================================

class VerificationResponse(BaseModel):
    """Response schema for a satellite verification entry."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    work_id: int
    satellite_source: str
    before_image_date: Optional[date] = None
    after_image_date: Optional[date] = None
    detected_area_sqm: Optional[float] = None
    reported_area_sqm: Optional[float] = None
    area_deviation_pct: Optional[float] = None
    ndvi_before: Optional[float] = None
    ndvi_after: Optional[float] = None
    ndvi_change: Optional[float] = None
    confidence_score: Optional[float] = None
    verification_status: VerificationStatusSchema
    verified_at: Optional[datetime] = None
    created_at: datetime


class SatelliteComparisonResponse(VerificationResponse):
    """Extended verification response with image URLs for side-by-side comparison."""

    before_image_url: Optional[str] = None
    after_image_url: Optional[str] = None
    cloud_cover_pct: Optional[float] = None
    verification_notes: Optional[str] = None
    detected_boundary: Optional[GeoJSONPolygon] = None


# ===========================================================================
# Muster roll anomaly
# ===========================================================================

class MusterRollAnomalyResponse(BaseModel):
    """Detected anomalies in muster roll / attendance data."""
    model_config = ConfigDict(from_attributes=True)

    work_id: int
    work_code: str
    anomaly_type: AnomalyTypeSchema
    severity: AnomalySeveritySchema
    affected_workers: list[dict[str, Any]] = Field(
        default_factory=list,
        description="List of workers involved: [{worker_id, name, job_card_number, days_flagged}]",
    )
    suspicious_dates: list[date] = Field(
        default_factory=list,
        description="Dates with suspicious attendance patterns",
    )
    description: str
    total_suspicious_person_days: Optional[float] = None
    estimated_wage_loss_inr: Optional[float] = None


# ===========================================================================
# Payment anomaly
# ===========================================================================

class PaymentAnomalyResponse(BaseModel):
    """Detected anomalies in payment / FTO data."""
    model_config = ConfigDict(from_attributes=True)

    work_id: int
    work_code: str
    anomaly_type: AnomalyTypeSchema
    severity: AnomalySeveritySchema
    description: str
    affected_payments: list[dict[str, Any]] = Field(
        default_factory=list,
        description="List of flagged payments: [{fto_number, beneficiary_id, amount, reason}]",
    )
    total_flagged_amount_inr: Optional[float] = None
    duplicate_count: Optional[int] = None
    zscore: Optional[float] = Field(default=None, description="Statistical z-score for outlier payments")


# ===========================================================================
# Risk score
# ===========================================================================

class RiskScoreResponse(BaseModel):
    """Composite risk score for a work or gram panchayat."""

    entity_id: int = Field(..., description="ID of the work or GP being scored")
    entity_type: str = Field(..., description="'work' or 'gram_panchayat'")
    overall_risk_score: float = Field(..., ge=0.0, le=100.0, description="0 = clean, 100 = highest risk")

    component_scores: dict[str, float] = Field(
        default_factory=dict,
        description="Breakdown: {satellite_mismatch, payment_anomaly, attendance_anomaly, photo_verification, measurement_inflation}",
    )
    anomaly_count: int = Field(default=0)
    critical_anomaly_count: int = Field(default=0)
    total_flagged_amount_inr: Optional[float] = None
    last_assessed_at: Optional[datetime] = None
    recommendation: Optional[str] = Field(default=None, description="Human-readable recommended action")


# ===========================================================================
# Investigation case
# ===========================================================================

class InvestigationCaseResponse(BaseModel):
    """Response schema for an investigation case."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    work_id: int
    case_number: str
    status: InvestigationStatusSchema
    anomaly_ids: Optional[list[int]] = None
    assigned_to: Optional[str] = None
    assigned_at: Optional[datetime] = None
    evidence_report_url: Optional[str] = None
    summary: Optional[str] = None
    estimated_fraud_amount: Optional[float] = None
    outcome_notes: Optional[str] = None
    closed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    # Enriched fields
    work_code: Optional[str] = None
    work_name: Optional[str] = None
    gp_name: Optional[str] = None
    district_name: Optional[str] = None


# ===========================================================================
# Photo record
# ===========================================================================

class PhotoRecordResponse(BaseModel):
    """Response schema for a geotagged photo record."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    work_id: int
    photo_url: str
    photo_type: Optional[str] = None
    gps_lat: Optional[float] = None
    gps_lon: Optional[float] = None
    gps_accuracy_m: Optional[float] = None
    capture_timestamp: Optional[datetime] = None
    device_model: Optional[str] = None
    verification_status: VerificationStatusSchema
    distance_from_site_m: Optional[float] = None
    tampering_detected: Optional[bool] = None
    verification_notes: Optional[str] = None
    uploaded_at: datetime


# ===========================================================================
# Report request / response
# ===========================================================================

class ReportRequest(BaseModel):
    """Request body to generate a verification report."""

    report_type: str = Field(
        ...,
        description="Type of report: 'work_verification', 'gp_summary', 'district_dashboard', 'investigation_brief'",
    )
    entity_id: int = Field(..., description="ID of the target entity (work, GP, district)")
    financial_year: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{4}$")
    include_satellite_images: bool = Field(default=True)
    include_anomaly_details: bool = Field(default=True)
    language: str = Field(default="en", description="Report language code: en, hi, ta, te, bn, etc.")
    format: str = Field(default="pdf", description="Output format: pdf, html, json")


class ReportResponse(BaseModel):
    """Response after generating a report."""

    report_id: str
    report_type: str
    status: str = Field(..., description="'generating', 'completed', 'failed'")
    download_url: Optional[str] = None
    generated_at: Optional[datetime] = None
    page_count: Optional[int] = None
    summary: Optional[str] = Field(default=None, description="Brief AI-generated summary of findings")


# ===========================================================================
# Dashboard statistics
# ===========================================================================

class DashboardStats(BaseModel):
    """Aggregate statistics for the main dashboard."""

    # Scope
    financial_year: str
    scope_type: str = Field(..., description="'national', 'state', 'district', 'block', 'gp'")
    scope_id: Optional[int] = None
    scope_name: Optional[str] = None

    # Work statistics
    total_works: int = 0
    works_verified: int = 0
    works_with_anomalies: int = 0
    verification_rate_pct: float = 0.0

    # Financial
    total_sanctioned_amount_inr: float = 0.0
    total_expenditure_inr: float = 0.0
    total_flagged_amount_inr: float = 0.0
    potential_savings_inr: float = 0.0

    # Anomalies
    total_anomalies: int = 0
    critical_anomalies: int = 0
    high_anomalies: int = 0
    medium_anomalies: int = 0
    low_anomalies: int = 0

    # Breakdown by type
    anomalies_by_type: dict[str, int] = Field(
        default_factory=dict,
        description="Count of anomalies keyed by AnomalyType value",
    )

    # Satellite verification
    satellite_checks_completed: int = 0
    satellite_mismatches_found: int = 0
    average_area_deviation_pct: Optional[float] = None

    # Muster roll
    muster_rolls_scanned: int = 0
    ghost_workers_detected: int = 0
    suspicious_attendance_count: int = 0

    # Investigations
    open_investigations: int = 0
    closed_investigations: int = 0

    # Top-risk entities
    top_risk_gps: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Top gram panchayats by risk: [{gp_id, gp_name, risk_score, anomaly_count}]",
    )
    top_risk_works: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Top works by risk: [{work_id, work_code, risk_score, anomaly_types}]",
    )

    # Timestamp
    computed_at: datetime = Field(default_factory=datetime.utcnow)


# ===========================================================================
# Rebuild forward references
# ===========================================================================

WorkWithVerification.model_rebuild()
