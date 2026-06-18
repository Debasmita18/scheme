"""
SQLAlchemy ORM models with PostGIS geometry support for the
MGNREGA Verification & Fraud Intelligence System.

Hierarchy: District -> Block -> GramPanchayat -> Work
Each work entry can have muster rolls, satellite verifications,
anomaly records, payment records, photo records, and investigation cases.
"""

from __future__ import annotations

import enum
from datetime import date, datetime
from typing import Any, Optional

from geoalchemy2 import Geometry
from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
    sessionmaker,
)
from sqlalchemy import create_engine

from config.settings import get_settings


# ===========================================================================
# Enumerations
# ===========================================================================

class WorkType(str, enum.Enum):
    """Types of works sanctioned under MGNREGA."""
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


class WorkStatus(str, enum.Enum):
    """Lifecycle status of a work entry."""
    SANCTIONED = "sanctioned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    INSPECTION_PENDING = "inspection_pending"
    VERIFIED = "verified"
    SUSPENDED = "suspended"
    CANCELLED = "cancelled"


class AnomalyType(str, enum.Enum):
    """Categories of detected fraud / anomalies."""
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


class AnomalySeverity(str, enum.Enum):
    """Severity classification for an anomaly."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AnomalyStatus(str, enum.Enum):
    """Processing status of an anomaly record."""
    DETECTED = "detected"
    UNDER_REVIEW = "under_review"
    CONFIRMED = "confirmed"
    FALSE_POSITIVE = "false_positive"
    ESCALATED = "escalated"
    RESOLVED = "resolved"


class VerificationStatus(str, enum.Enum):
    """Outcome of a satellite or photo verification."""
    PENDING = "pending"
    VERIFIED = "verified"
    MISMATCH_DETECTED = "mismatch_detected"
    INCONCLUSIVE = "inconclusive"
    FAILED = "failed"


class InvestigationStatus(str, enum.Enum):
    """Status of a formal investigation case."""
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    EVIDENCE_COLLECTED = "evidence_collected"
    REPORT_GENERATED = "report_generated"
    SUBMITTED = "submitted"
    CLOSED_CONFIRMED = "closed_confirmed"
    CLOSED_CLEARED = "closed_cleared"


# ===========================================================================
# Base class
# ===========================================================================

class Base(DeclarativeBase):
    """Declarative base for all ORM models."""
    pass


# ===========================================================================
# Administrative Hierarchy
# ===========================================================================

class District(Base):
    """District-level administrative unit."""

    __tablename__ = "districts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    state_code: Mapped[str] = mapped_column(String(2), nullable=False, index=True, comment="NREGA 2-digit state code")
    state_name: Mapped[str] = mapped_column(String(100), nullable=False)
    district_code: Mapped[str] = mapped_column(String(4), nullable=False, unique=True, comment="NREGA 4-digit district code")
    district_name: Mapped[str] = mapped_column(String(200), nullable=False)
    boundary: Mapped[Optional[Any]] = mapped_column(
        Geometry("MULTIPOLYGON", srid=4326), nullable=True, comment="District boundary polygon"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    blocks: Mapped[list["Block"]] = relationship("Block", back_populates="district", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_districts_state_district", "state_code", "district_code"),
    )

    def __repr__(self) -> str:
        return f"<District(id={self.id}, code={self.district_code}, name={self.district_name})>"


class Block(Base):
    """Block-level administrative unit within a District."""

    __tablename__ = "blocks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    district_id: Mapped[int] = mapped_column(Integer, ForeignKey("districts.id", ondelete="CASCADE"), nullable=False, index=True)
    block_code: Mapped[str] = mapped_column(String(7), nullable=False, unique=True, comment="NREGA 7-digit block code")
    block_name: Mapped[str] = mapped_column(String(200), nullable=False)
    boundary: Mapped[Optional[Any]] = mapped_column(
        Geometry("MULTIPOLYGON", srid=4326), nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    district: Mapped["District"] = relationship("District", back_populates="blocks")
    gram_panchayats: Mapped[list["GramPanchayat"]] = relationship("GramPanchayat", back_populates="block", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_blocks_district_block", "district_id", "block_code"),
    )

    def __repr__(self) -> str:
        return f"<Block(id={self.id}, code={self.block_code}, name={self.block_name})>"


class GramPanchayat(Base):
    """Gram Panchayat -- the lowest tier of the NREGA hierarchy."""

    __tablename__ = "gram_panchayats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    block_id: Mapped[int] = mapped_column(Integer, ForeignKey("blocks.id", ondelete="CASCADE"), nullable=False, index=True)
    gp_code: Mapped[str] = mapped_column(String(10), nullable=False, unique=True, comment="NREGA GP code")
    gp_name: Mapped[str] = mapped_column(String(200), nullable=False)
    boundary: Mapped[Optional[Any]] = mapped_column(
        Geometry("MULTIPOLYGON", srid=4326), nullable=True,
    )
    total_job_cards: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="Total registered job cards")
    total_workers: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="Total registered workers")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    block: Mapped["Block"] = relationship("Block", back_populates="gram_panchayats")
    works: Mapped[list["Work"]] = relationship("Work", back_populates="gram_panchayat", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<GramPanchayat(id={self.id}, code={self.gp_code}, name={self.gp_name})>"


# ===========================================================================
# MGNREGA Work
# ===========================================================================

class Work(Base):
    """A single MGNREGA work (project) with its measurements and geometry."""

    __tablename__ = "works"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    gp_id: Mapped[int] = mapped_column(Integer, ForeignKey("gram_panchayats.id", ondelete="CASCADE"), nullable=False, index=True)

    # NREGA identifiers
    work_code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, comment="Unique NREGA work code e.g. 2702002001/RC/1234567890")
    work_name: Mapped[str] = mapped_column(String(500), nullable=False)
    work_type: Mapped[WorkType] = mapped_column(Enum(WorkType, name="work_type_enum", create_constraint=True), nullable=False, index=True)
    work_category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, comment="NREGA sub-category")
    financial_year: Mapped[str] = mapped_column(String(9), nullable=False, index=True, comment="e.g. 2024-2025")

    # Financial details
    sanctioned_amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, comment="Amount sanctioned in INR")
    expenditure_amount: Mapped[Optional[float]] = mapped_column(Numeric(14, 2), nullable=True, comment="Total expenditure so far")
    wage_component: Mapped[Optional[float]] = mapped_column(Numeric(14, 2), nullable=True, comment="Wage expenditure in INR")
    material_component: Mapped[Optional[float]] = mapped_column(Numeric(14, 2), nullable=True, comment="Material expenditure in INR")

    # Measurement details (reported by functionaries)
    reported_length_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="Reported length in metres")
    reported_width_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="Reported width in metres")
    reported_depth_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="Reported depth in metres")
    reported_area_sqm: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="Reported area in sq metres")
    reported_volume_cum: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="Reported volume in cubic metres")

    # Dates
    sanction_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    completion_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    # Geospatial
    location: Mapped[Optional[Any]] = mapped_column(
        Geometry("POINT", srid=4326), nullable=True, comment="Centroid GPS of work site"
    )
    work_boundary: Mapped[Optional[Any]] = mapped_column(
        Geometry("POLYGON", srid=4326), nullable=True, comment="Polygon boundary of work site"
    )
    reported_latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    reported_longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Status
    status: Mapped[WorkStatus] = mapped_column(
        Enum(WorkStatus, name="work_status_enum", create_constraint=True),
        default=WorkStatus.SANCTIONED,
        nullable=False,
        index=True,
    )
    total_person_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="Total person-days generated")
    total_workers_employed: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Risk
    risk_score: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="Computed fraud risk score 0-100"
    )

    # Audit
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    gram_panchayat: Mapped["GramPanchayat"] = relationship("GramPanchayat", back_populates="works")
    muster_rolls: Mapped[list["MusterRoll"]] = relationship("MusterRoll", back_populates="work", cascade="all, delete-orphan")
    satellite_verifications: Mapped[list["SatelliteVerification"]] = relationship("SatelliteVerification", back_populates="work", cascade="all, delete-orphan")
    anomaly_records: Mapped[list["AnomalyRecord"]] = relationship("AnomalyRecord", back_populates="work", cascade="all, delete-orphan")
    payment_records: Mapped[list["PaymentRecord"]] = relationship("PaymentRecord", back_populates="work", cascade="all, delete-orphan")
    photo_records: Mapped[list["PhotoRecord"]] = relationship("PhotoRecord", back_populates="work", cascade="all, delete-orphan")
    investigation_cases: Mapped[list["InvestigationCase"]] = relationship("InvestigationCase", back_populates="work", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_works_gp_fy", "gp_id", "financial_year"),
        Index("ix_works_risk_score", "risk_score"),
        Index("ix_works_location", "location", postgresql_using="gist"),
    )

    def __repr__(self) -> str:
        return f"<Work(id={self.id}, code={self.work_code}, type={self.work_type.value})>"


# ===========================================================================
# Muster Roll
# ===========================================================================

class MusterRoll(Base):
    """Muster roll entry linking a worker to attendance on a work."""

    __tablename__ = "muster_rolls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    work_id: Mapped[int] = mapped_column(Integer, ForeignKey("works.id", ondelete="CASCADE"), nullable=False, index=True)

    # Worker identity
    worker_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True, comment="NREGA worker ID")
    worker_name: Mapped[str] = mapped_column(String(200), nullable=False)
    job_card_number: Mapped[str] = mapped_column(String(30), nullable=False, index=True, comment="e.g. RJ-01-001-001-001/1")
    aadhaar_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True, comment="SHA-256 hash of Aadhaar for dedup, never store raw")

    # Muster details
    muster_roll_number: Mapped[str] = mapped_column(String(30), nullable=False, comment="NREGA muster roll number")
    date_from: Mapped[date] = mapped_column(Date, nullable=False)
    date_to: Mapped[date] = mapped_column(Date, nullable=False)
    days_worked: Mapped[float] = mapped_column(Float, nullable=False, comment="Days present (supports half-days)")
    attendance_dates: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True, comment='JSON map of date -> "P"/"A"/"H" (Present/Absent/Half)'
    )

    # Payment
    daily_wage_rate: Mapped[float] = mapped_column(Numeric(8, 2), nullable=False, comment="Applicable wage rate in INR")
    total_wage: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, comment="Total wage for this muster period")

    # Audit
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    work: Mapped["Work"] = relationship("Work", back_populates="muster_rolls")

    __table_args__ = (
        Index("ix_muster_worker_dates", "worker_id", "date_from", "date_to"),
        Index("ix_muster_job_card", "job_card_number"),
        UniqueConstraint("muster_roll_number", "worker_id", name="uq_muster_worker"),
    )

    def __repr__(self) -> str:
        return f"<MusterRoll(id={self.id}, worker={self.worker_id}, days={self.days_worked})>"


# ===========================================================================
# Satellite Verification
# ===========================================================================

class SatelliteVerification(Base):
    """Result of satellite-based verification for a work site."""

    __tablename__ = "satellite_verifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    work_id: Mapped[int] = mapped_column(Integer, ForeignKey("works.id", ondelete="CASCADE"), nullable=False, index=True)

    # Imagery references
    satellite_source: Mapped[str] = mapped_column(String(50), nullable=False, default="Sentinel-2", comment="e.g. Sentinel-2, Bhuvan")
    before_image_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    after_image_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    before_image_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    after_image_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cloud_cover_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="Cloud cover % in the imagery")

    # Measurement comparison
    detected_area_sqm: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="Area detected from satellite")
    reported_area_sqm: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="Area claimed by functionary")
    area_deviation_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="Percentage deviation")

    # NDVI analysis
    ndvi_before: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="NDVI value before work")
    ndvi_after: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="NDVI value after work")
    ndvi_change: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="Change in NDVI")

    # Confidence
    confidence_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="Algorithm confidence 0.0-1.0")
    verification_status: Mapped[VerificationStatus] = mapped_column(
        Enum(VerificationStatus, name="verification_status_enum", create_constraint=True),
        default=VerificationStatus.PENDING,
        nullable=False,
        index=True,
    )
    verification_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Detected boundary from satellite
    detected_boundary: Mapped[Optional[Any]] = mapped_column(
        Geometry("POLYGON", srid=4326), nullable=True,
    )

    # Audit
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    work: Mapped["Work"] = relationship("Work", back_populates="satellite_verifications")

    __table_args__ = (
        Index("ix_satver_work_status", "work_id", "verification_status"),
    )

    def __repr__(self) -> str:
        return f"<SatelliteVerification(id={self.id}, work_id={self.work_id}, status={self.verification_status.value})>"


# ===========================================================================
# Anomaly Record
# ===========================================================================

class AnomalyRecord(Base):
    """A detected anomaly / fraud indicator linked to a work."""

    __tablename__ = "anomaly_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    work_id: Mapped[int] = mapped_column(Integer, ForeignKey("works.id", ondelete="CASCADE"), nullable=False, index=True)

    anomaly_type: Mapped[AnomalyType] = mapped_column(
        Enum(AnomalyType, name="anomaly_type_enum", create_constraint=True),
        nullable=False,
        index=True,
    )
    severity: Mapped[AnomalySeverity] = mapped_column(
        Enum(AnomalySeverity, name="anomaly_severity_enum", create_constraint=True),
        nullable=False,
        index=True,
    )
    status: Mapped[AnomalyStatus] = mapped_column(
        Enum(AnomalyStatus, name="anomaly_status_enum", create_constraint=True),
        default=AnomalyStatus.DETECTED,
        nullable=False,
        index=True,
    )

    # Description & evidence
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    evidence_json: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True,
        comment="Structured evidence: measurements, screenshots, data points",
    )
    confidence_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="Detection confidence 0.0-1.0")

    # Financial impact
    estimated_loss_inr: Mapped[Optional[float]] = mapped_column(Numeric(14, 2), nullable=True, comment="Estimated financial loss")

    # Resolution
    resolved_by: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Audit
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    work: Mapped["Work"] = relationship("Work", back_populates="anomaly_records")

    __table_args__ = (
        Index("ix_anomaly_type_severity", "anomaly_type", "severity"),
        Index("ix_anomaly_work_status", "work_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<AnomalyRecord(id={self.id}, type={self.anomaly_type.value}, severity={self.severity.value})>"


# ===========================================================================
# Payment Record
# ===========================================================================

class PaymentRecord(Base):
    """Payment disbursed against a work via the NREGA FTO process."""

    __tablename__ = "payment_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    work_id: Mapped[int] = mapped_column(Integer, ForeignKey("works.id", ondelete="CASCADE"), nullable=False, index=True)

    # Beneficiary
    beneficiary_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True, comment="NREGA beneficiary registration ID")
    beneficiary_name: Mapped[str] = mapped_column(String(200), nullable=False)
    job_card_number: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    bank_account_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, comment="SHA-256 hash of account number")
    bank_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    ifsc_code: Mapped[Optional[str]] = mapped_column(String(11), nullable=True)

    # FTO details
    fto_number: Mapped[str] = mapped_column(String(50), nullable=False, index=True, comment="Fund Transfer Order number")
    fto_stage: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, comment="e.g. first_sign, second_sign, sent_to_bank")

    # Amount
    amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, comment="Payment amount in INR")
    payment_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)
    credit_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, comment="Date amount credited to beneficiary account")
    payment_status: Mapped[Optional[str]] = mapped_column(String(30), nullable=True, comment="e.g. processed, credited, rejected")

    # Audit
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    work: Mapped["Work"] = relationship("Work", back_populates="payment_records")

    __table_args__ = (
        Index("ix_payment_fto", "fto_number"),
        Index("ix_payment_beneficiary_date", "beneficiary_id", "payment_date"),
    )

    def __repr__(self) -> str:
        return f"<PaymentRecord(id={self.id}, fto={self.fto_number}, amount={self.amount})>"


# ===========================================================================
# Investigation Case
# ===========================================================================

class InvestigationCase(Base):
    """Formal investigation case aggregating one or more anomalies for a work."""

    __tablename__ = "investigation_cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    work_id: Mapped[int] = mapped_column(Integer, ForeignKey("works.id", ondelete="CASCADE"), nullable=False, index=True)

    case_number: Mapped[str] = mapped_column(String(30), nullable=False, unique=True, comment="System-generated case number e.g. INV-2024-00123")
    status: Mapped[InvestigationStatus] = mapped_column(
        Enum(InvestigationStatus, name="investigation_status_enum", create_constraint=True),
        default=InvestigationStatus.OPEN,
        nullable=False,
        index=True,
    )

    # Linked anomalies (stored as list of anomaly IDs for flexibility)
    anomaly_ids: Mapped[Optional[list]] = mapped_column(JSON, nullable=True, comment="List of related AnomalyRecord IDs")

    # Assignment
    assigned_to: Mapped[Optional[str]] = mapped_column(String(200), nullable=True, comment="Name/ID of investigating officer")
    assigned_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Evidence & reporting
    evidence_report_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="URL/path to the generated evidence report")
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="AI-generated or manual case summary")
    estimated_fraud_amount: Mapped[Optional[float]] = mapped_column(Numeric(14, 2), nullable=True)

    # Outcome
    outcome_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Audit
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    work: Mapped["Work"] = relationship("Work", back_populates="investigation_cases")

    __table_args__ = (
        Index("ix_investigation_status", "status"),
    )

    def __repr__(self) -> str:
        return f"<InvestigationCase(id={self.id}, case={self.case_number}, status={self.status.value})>"


# ===========================================================================
# Photo Record
# ===========================================================================

class PhotoRecord(Base):
    """Geotagged photograph taken at a work site for verification."""

    __tablename__ = "photo_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    work_id: Mapped[int] = mapped_column(Integer, ForeignKey("works.id", ondelete="CASCADE"), nullable=False, index=True)

    photo_url: Mapped[str] = mapped_column(Text, nullable=False, comment="Storage URL of the photograph")
    photo_type: Mapped[Optional[str]] = mapped_column(
        String(30), nullable=True, comment="e.g. before, during, after, inspection"
    )

    # GPS from EXIF
    gps_lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    gps_lon: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    gps_point: Mapped[Optional[Any]] = mapped_column(
        Geometry("POINT", srid=4326), nullable=True,
    )
    gps_accuracy_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="GPS accuracy in metres from EXIF")

    # EXIF metadata
    exif_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, comment="Full EXIF metadata as JSON")
    capture_timestamp: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, comment="Timestamp from EXIF")
    device_model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Verification
    verification_status: Mapped[VerificationStatus] = mapped_column(
        Enum(VerificationStatus, name="photo_verification_status_enum", create_constraint=True),
        default=VerificationStatus.PENDING,
        nullable=False,
        index=True,
    )
    distance_from_site_m: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="Distance between photo GPS and registered work site GPS"
    )
    tampering_detected: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True, comment="True if photo manipulation detected")
    verification_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Audit
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    work: Mapped["Work"] = relationship("Work", back_populates="photo_records")

    __table_args__ = (
        Index("ix_photo_work_status", "work_id", "verification_status"),
    )

    def __repr__(self) -> str:
        return f"<PhotoRecord(id={self.id}, work_id={self.work_id}, status={self.verification_status.value})>"


# ===========================================================================
# Engine & Session helpers
# ===========================================================================

def get_engine(settings=None):
    """Create a SQLAlchemy engine from application settings.

    Args:
        settings: Optional Settings instance. Uses ``get_settings()`` by default.

    Returns:
        A SQLAlchemy ``Engine`` instance.
    """
    if settings is None:
        settings = get_settings()
    return create_engine(
        settings.database_url,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        echo=settings.database_echo,
        pool_pre_ping=True,
    )


def get_session_factory(engine=None) -> sessionmaker[Session]:
    """Return a ``sessionmaker`` bound to the given (or default) engine.

    Args:
        engine: Optional SQLAlchemy ``Engine``. Created from settings if *None*.

    Returns:
        A ``sessionmaker`` that produces ``Session`` instances.
    """
    if engine is None:
        engine = get_engine()
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)
