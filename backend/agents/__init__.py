"""
MGNREGA Verification & Fraud Intelligence System -- Agent Package.

This package contains the AI agent modules that collectively form the
automated fraud detection and verification pipeline for MGNREGA works.

Agent hierarchy:
    SentinelAgent (always running)
        |
        +-- SatelliteVerificationAgent   (remote sensing verification)
        +-- MusterRollForensicsAgent     (attendance and worker fraud)
        +-- PaymentPatternAgent          (financial flow analysis)
        +-- PhotoVerificationAgent       (GeoMGNREGA photo analysis)
        +-- CaseFileAgent               (evidence compilation & reporting)
        |
    AgentOrchestrator (workflow coordinator)

Usage::

    from agents import (
        AgentOrchestrator,
        CaseFileAgent,
        MusterRollForensicsAgent,
        PaymentPatternAgent,
        PhotoVerificationAgent,
        SatelliteVerificationAgent,
        SentinelAgent,
    )
"""

from .case_file_agent import (
    BhashiniLanguage,
    CAGObservation,
    CaseFile,
    CaseFileAgent,
    CaseStatus,
    DistrictBriefing,
    EvidenceChain,
    EvidenceItem,
    EvidenceType,
    ReportFormat,
    WeeklySummary,
)
from .muster_roll_forensics import (
    AttendanceCloneGroup,
    ForensicFinding,
    ForensicsReport,
    FraudCategory,
    GhostWorkerProfile,
    MusterRollForensicsAgent,
    SeverityLevel,
)
from .orchestrator import (
    AgentOrchestrator,
    InvestigationContext,
    InvestigationPhase,
    InvestigationStatus,
    WorkflowNode,
    WorkflowState,
)
from .payment_pattern import (
    CircularFlow,
    NodeType,
    PaymentFinding,
    PaymentFraudType,
    PaymentPatternAgent,
    PaymentReport,
    ShellBeneficiary,
    VendorCollusionCluster,
)
from .photo_verification import (
    BulkUploadCluster,
    PhotoMetadata,
    PhotoVerificationAgent,
    PhotoVerificationReport,
    PhotoVerificationResult,
    PhotoVerificationStatus,
    WorkTypeLabel,
)
from .satellite_verification import (
    BoundingBox,
    ComparisonReport,
    MeasurementEstimate,
    SatelliteImage,
    SatelliteVerificationAgent,
    VerificationResult,
    VerificationStatus,
    WorkType,
)
from .sentinel_agent import (
    AnomalyType,
    FlaggedWork,
    Investigation,
    NationalDashboardStats,
    RiskScoreBreakdown,
    SentinelAgent,
)

__all__ = [
    # Sentinel Agent
    "SentinelAgent",
    "AnomalyType",
    "FlaggedWork",
    "Investigation",
    "NationalDashboardStats",
    "RiskScoreBreakdown",
    # Satellite Verification Agent
    "SatelliteVerificationAgent",
    "BoundingBox",
    "ComparisonReport",
    "MeasurementEstimate",
    "SatelliteImage",
    "VerificationResult",
    "VerificationStatus",
    "WorkType",
    # Muster Roll Forensics Agent
    "MusterRollForensicsAgent",
    "AttendanceCloneGroup",
    "ForensicFinding",
    "ForensicsReport",
    "FraudCategory",
    "GhostWorkerProfile",
    "SeverityLevel",
    # Payment Pattern Agent
    "PaymentPatternAgent",
    "CircularFlow",
    "NodeType",
    "PaymentFinding",
    "PaymentFraudType",
    "PaymentReport",
    "ShellBeneficiary",
    "VendorCollusionCluster",
    # Photo Verification Agent
    "PhotoVerificationAgent",
    "BulkUploadCluster",
    "PhotoMetadata",
    "PhotoVerificationReport",
    "PhotoVerificationResult",
    "PhotoVerificationStatus",
    "WorkTypeLabel",
    # Case File Agent
    "CaseFileAgent",
    "BhashiniLanguage",
    "CAGObservation",
    "CaseFile",
    "CaseStatus",
    "DistrictBriefing",
    "EvidenceChain",
    "EvidenceItem",
    "EvidenceType",
    "ReportFormat",
    "WeeklySummary",
    # Orchestrator
    "AgentOrchestrator",
    "InvestigationContext",
    "InvestigationPhase",
    "InvestigationStatus",
    "WorkflowNode",
    "WorkflowState",
]
