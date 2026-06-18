"""
Master Sentinel Agent for the MGNREGA Verification & Fraud Intelligence System.

This agent runs continuously, monitoring data streams from NREGASoft, GeoMGNREGA,
and satellite imagery. It performs anomaly detection across every gram panchayat,
generates daily risk scores, and spawns specialized investigation agents when
fraud indicators exceed configured thresholds.

The Sentinel operates at the national level, scanning all districts and blocks
on a rolling basis, maintaining a priority queue of flagged works for
downstream investigation.
"""

from __future__ import annotations

import asyncio
import heapq
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from loguru import logger


# ---------------------------------------------------------------------------
# Domain enumerations and data structures
# ---------------------------------------------------------------------------

class AnomalyType(str, Enum):
    """Categories of anomalies the Sentinel can detect."""

    EXPENDITURE = "expenditure_anomaly"
    ATTENDANCE = "attendance_anomaly"
    SATELLITE = "satellite_mismatch"
    PHOTO = "photo_anomaly"
    PAYMENT = "payment_anomaly"
    GHOST_WORKER = "ghost_worker"
    MUSTER_ROLL = "muster_roll_fraud"
    MATERIAL_RATIO = "material_ratio_violation"


class InvestigationStatus(str, Enum):
    """Lifecycle states for a spawned investigation."""

    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    AWAITING_SATELLITE = "awaiting_satellite"
    AWAITING_FIELD = "awaiting_field_verification"
    COMPLETED = "completed"
    ESCALATED = "escalated"
    CLOSED = "closed"


@dataclass(order=True)
class FlaggedWork:
    """Entry in the Sentinel's priority queue.

    Ordering is by *negative* risk score so that ``heapq`` (a min-heap)
    pops the highest-risk item first.
    """

    priority: float = field(compare=True)
    work_id: str = field(compare=False)
    gram_panchayat_id: str = field(compare=False)
    block_id: str = field(compare=False)
    district_id: str = field(compare=False)
    state_code: str = field(compare=False)
    anomaly_types: List[AnomalyType] = field(compare=False, default_factory=list)
    risk_score: float = field(compare=False, default=0.0)
    flagged_at: datetime = field(compare=False, default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(compare=False, default_factory=dict)


@dataclass
class RiskScoreBreakdown:
    """Detailed breakdown of a gram panchayat's composite risk score."""

    gram_panchayat_id: str
    block_id: str
    district_id: str
    state_code: str
    expenditure_score: float = 0.0
    attendance_score: float = 0.0
    satellite_score: float = 0.0
    photo_score: float = 0.0
    payment_score: float = 0.0
    composite_score: float = 0.0
    anomaly_flags: List[str] = field(default_factory=list)
    computed_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Investigation:
    """Tracks a spawned investigation."""

    investigation_id: str
    anomaly_type: AnomalyType
    target_id: str
    target_type: str  # "work", "panchayat", "block", "district"
    status: InvestigationStatus
    spawned_at: datetime
    assigned_agents: List[str] = field(default_factory=list)
    findings: Dict[str, Any] = field(default_factory=dict)
    completed_at: Optional[datetime] = None


@dataclass
class NationalDashboardStats:
    """Aggregate statistics for the national monitoring dashboard."""

    scan_date: datetime
    total_gram_panchayats_scanned: int = 0
    total_works_flagged: int = 0
    active_investigations: int = 0
    high_risk_districts: int = 0
    medium_risk_districts: int = 0
    low_risk_districts: int = 0
    top_anomaly_types: Dict[str, int] = field(default_factory=dict)
    estimated_leakage_crores: float = 0.0
    states_covered: int = 0
    blocks_scanned: int = 0
    district_scores: Dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Sentinel Agent
# ---------------------------------------------------------------------------

class SentinelAgent:
    """Master Sentinel Agent -- the always-running national watchdog.

    The Sentinel continuously ingests data from three primary streams:

    1. **NREGASoft** -- official MIS data (muster rolls, FTOs, job cards,
       expenditure reports, work completion records).
    2. **GeoMGNREGA** -- geotagged photographs uploaded at work sites.
    3. **Satellite imagery** -- Sentinel-2 / Cartosat imagery for physical
       verification of reported works.

    It computes a composite risk score for every gram panchayat by
    aggregating five fraud signal dimensions, then maintains a priority
    queue of flagged works and spawns specialised investigation agents
    whenever a configurable threshold is breached.

    Parameters
    ----------
    db_session : Any
        Active database session for querying the MGNREGA data warehouse.
    config : dict, optional
        Runtime configuration overrides.
    """

    # Default scoring weights (must sum to 1.0)
    DEFAULT_WEIGHTS: Dict[str, float] = {
        "expenditure": 0.25,
        "attendance": 0.25,
        "satellite": 0.20,
        "photo": 0.15,
        "payment": 0.15,
    }

    # Risk thresholds
    HIGH_RISK_THRESHOLD: float = 0.75
    MEDIUM_RISK_THRESHOLD: float = 0.50
    INVESTIGATION_THRESHOLD: float = 0.70

    def __init__(
        self,
        db_session: Any,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.db = db_session
        self.config = config or {}
        self.weights = self.config.get("scoring_weights", self.DEFAULT_WEIGHTS)
        self.investigation_threshold = self.config.get(
            "investigation_threshold", self.INVESTIGATION_THRESHOLD
        )

        # Internal state
        self._priority_queue: List[FlaggedWork] = []
        self._investigations: Dict[str, Investigation] = {}
        self._daily_scores: Dict[str, RiskScoreBreakdown] = {}
        self._district_scores: Dict[str, float] = defaultdict(float)
        self._block_scores: Dict[str, float] = defaultdict(float)
        self._scan_history: List[Dict[str, Any]] = []

        logger.info(
            "SentinelAgent initialised | weights={w} | threshold={t}",
            w=self.weights,
            t=self.investigation_threshold,
        )

    # ------------------------------------------------------------------
    # Core scanning
    # ------------------------------------------------------------------

    async def run_daily_scan(self) -> NationalDashboardStats:
        """Execute the full national daily scan.

        This is the Sentinel's primary heartbeat. It iterates over every
        active gram panchayat, computes risk scores, flags anomalies, and
        spawns investigations as needed.

        Returns
        -------
        NationalDashboardStats
            Aggregated national-level statistics for the scan.
        """
        scan_start = datetime.utcnow()
        logger.info("Daily scan started at {t}", t=scan_start.isoformat())

        stats = NationalDashboardStats(scan_date=scan_start)

        try:
            # Step 1 -- Fetch the list of all active gram panchayats
            gram_panchayats = await self._fetch_active_gram_panchayats()
            stats.total_gram_panchayats_scanned = len(gram_panchayats)
            logger.info(
                "Fetched {n} active gram panchayats for scanning",
                n=len(gram_panchayats),
            )

            # Step 2 -- Score each GP in parallel batches
            batch_size = self.config.get("scan_batch_size", 100)
            for i in range(0, len(gram_panchayats), batch_size):
                batch = gram_panchayats[i : i + batch_size]
                tasks = [
                    self.calculate_risk_score(gp["gram_panchayat_id"])
                    for gp in batch
                ]
                batch_results = await asyncio.gather(*tasks, return_exceptions=True)

                for gp, result in zip(batch, batch_results):
                    if isinstance(result, Exception):
                        logger.error(
                            "Risk scoring failed for GP {gp}: {e}",
                            gp=gp["gram_panchayat_id"],
                            e=result,
                        )
                        continue
                    self._process_risk_score(result, stats)

            # Step 3 -- Aggregate district and block level scores
            self._aggregate_hierarchical_scores(stats)

            # Step 4 -- Count active investigations
            stats.active_investigations = sum(
                1
                for inv in self._investigations.values()
                if inv.status
                in (InvestigationStatus.IN_PROGRESS, InvestigationStatus.QUEUED)
            )

            # Step 5 -- Estimate leakage from flagged works
            stats.estimated_leakage_crores = self._estimate_leakage()

            # Record scan history
            self._scan_history.append(
                {
                    "date": scan_start.isoformat(),
                    "gps_scanned": stats.total_gram_panchayats_scanned,
                    "works_flagged": stats.total_works_flagged,
                    "duration_seconds": (
                        datetime.utcnow() - scan_start
                    ).total_seconds(),
                }
            )

            logger.info(
                "Daily scan completed | GPs={gps} | flagged={f} | investigations={i}",
                gps=stats.total_gram_panchayats_scanned,
                f=stats.total_works_flagged,
                i=stats.active_investigations,
            )
            return stats

        except Exception as exc:
            logger.exception("Daily scan failed catastrophically: {e}", e=exc)
            raise

    # ------------------------------------------------------------------
    # Risk scoring
    # ------------------------------------------------------------------

    async def calculate_risk_score(
        self, gram_panchayat_id: str
    ) -> RiskScoreBreakdown:
        """Compute the composite risk score for a single gram panchayat.

        The composite score is a weighted combination of five sub-scores:

        - **Expenditure anomaly** -- statistical outlier detection (z-score,
          IQR) on per-work and per-GP spending compared to block/district
          averages and historical trends.
        - **Attendance anomaly** -- correlation analysis on muster rolls,
          Benford's law on reported days, and seasonal feasibility checks.
        - **Satellite verification** -- ratio of works where satellite
          imagery contradicts reported physical progress.
        - **Photo anomaly** -- GPS mismatches, duplicate hashes, and
          content-type mismatches in GeoMGNREGA photos.
        - **Payment anomaly** -- network centrality of suspicious accounts,
          ratio violations, and circular flow indicators.

        Parameters
        ----------
        gram_panchayat_id : str
            The unique NREGASoft panchayat code (e.g., ``"3401002003"``).

        Returns
        -------
        RiskScoreBreakdown
            Detailed per-dimension scores and the composite result.
        """
        logger.debug(
            "Calculating risk score for GP {gp}", gp=gram_panchayat_id
        )

        try:
            # Fetch GP metadata
            gp_meta = await self._fetch_gp_metadata(gram_panchayat_id)

            # Compute each sub-score concurrently
            (
                expenditure_score,
                attendance_score,
                satellite_score,
                photo_score,
                payment_score,
            ) = await asyncio.gather(
                self._score_expenditure_anomaly(gram_panchayat_id),
                self._score_attendance_anomaly(gram_panchayat_id),
                self._score_satellite_verification(gram_panchayat_id),
                self._score_photo_anomaly(gram_panchayat_id),
                self._score_payment_anomaly(gram_panchayat_id),
            )

            # Weighted composite
            composite = (
                self.weights["expenditure"] * expenditure_score
                + self.weights["attendance"] * attendance_score
                + self.weights["satellite"] * satellite_score
                + self.weights["photo"] * photo_score
                + self.weights["payment"] * payment_score
            )

            # Identify which dimensions are flagged
            anomaly_flags: List[str] = []
            dim_threshold = self.config.get("dimension_flag_threshold", 0.60)
            if expenditure_score >= dim_threshold:
                anomaly_flags.append(AnomalyType.EXPENDITURE.value)
            if attendance_score >= dim_threshold:
                anomaly_flags.append(AnomalyType.ATTENDANCE.value)
            if satellite_score >= dim_threshold:
                anomaly_flags.append(AnomalyType.SATELLITE.value)
            if photo_score >= dim_threshold:
                anomaly_flags.append(AnomalyType.PHOTO.value)
            if payment_score >= dim_threshold:
                anomaly_flags.append(AnomalyType.PAYMENT.value)

            breakdown = RiskScoreBreakdown(
                gram_panchayat_id=gram_panchayat_id,
                block_id=gp_meta.get("block_id", ""),
                district_id=gp_meta.get("district_id", ""),
                state_code=gp_meta.get("state_code", ""),
                expenditure_score=round(expenditure_score, 4),
                attendance_score=round(attendance_score, 4),
                satellite_score=round(satellite_score, 4),
                photo_score=round(photo_score, 4),
                payment_score=round(payment_score, 4),
                composite_score=round(composite, 4),
                anomaly_flags=anomaly_flags,
            )

            # Cache the score
            self._daily_scores[gram_panchayat_id] = breakdown

            logger.debug(
                "GP {gp} risk score = {s:.4f} | flags = {f}",
                gp=gram_panchayat_id,
                s=composite,
                f=anomaly_flags,
            )
            return breakdown

        except Exception as exc:
            logger.error(
                "Failed to score GP {gp}: {e}", gp=gram_panchayat_id, e=exc
            )
            raise

    # ------------------------------------------------------------------
    # Investigation spawning
    # ------------------------------------------------------------------

    async def spawn_investigation(
        self,
        anomaly_type: AnomalyType,
        target_id: str,
        target_type: str = "work",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Investigation:
        """Spawn a specialised investigation for a detected anomaly.

        Depending on *anomaly_type*, the Sentinel routes the investigation
        to the appropriate downstream agent:

        - ``SATELLITE`` -> ``SatelliteVerificationAgent``
        - ``ATTENDANCE`` / ``GHOST_WORKER`` / ``MUSTER_ROLL`` ->
          ``MusterRollForensicsAgent``
        - ``PAYMENT`` / ``MATERIAL_RATIO`` -> ``PaymentPatternAgent``
        - ``PHOTO`` -> ``PhotoVerificationAgent``

        Results are collected asynchronously and compiled into a case file
        by the ``CaseFileAgent``.

        Parameters
        ----------
        anomaly_type : AnomalyType
            The category of anomaly that triggered the investigation.
        target_id : str
            Identifier of the entity under investigation (work ID,
            panchayat code, block code, etc.).
        target_type : str
            Granularity level -- ``"work"``, ``"panchayat"``, ``"block"``,
            or ``"district"``.
        metadata : dict, optional
            Additional context from the detection phase.

        Returns
        -------
        Investigation
            The newly created investigation record.
        """
        investigation_id = f"INV-{uuid.uuid4().hex[:12].upper()}"
        now = datetime.utcnow()

        # Determine which agents are needed
        agent_routing: Dict[AnomalyType, List[str]] = {
            AnomalyType.SATELLITE: [
                "SatelliteVerificationAgent",
                "CaseFileAgent",
            ],
            AnomalyType.ATTENDANCE: [
                "MusterRollForensicsAgent",
                "CaseFileAgent",
            ],
            AnomalyType.GHOST_WORKER: [
                "MusterRollForensicsAgent",
                "PaymentPatternAgent",
                "CaseFileAgent",
            ],
            AnomalyType.MUSTER_ROLL: [
                "MusterRollForensicsAgent",
                "CaseFileAgent",
            ],
            AnomalyType.PAYMENT: [
                "PaymentPatternAgent",
                "CaseFileAgent",
            ],
            AnomalyType.MATERIAL_RATIO: [
                "PaymentPatternAgent",
                "CaseFileAgent",
            ],
            AnomalyType.PHOTO: [
                "PhotoVerificationAgent",
                "CaseFileAgent",
            ],
            AnomalyType.EXPENDITURE: [
                "PaymentPatternAgent",
                "SatelliteVerificationAgent",
                "CaseFileAgent",
            ],
        }

        assigned = agent_routing.get(
            anomaly_type, ["CaseFileAgent"]
        )

        investigation = Investigation(
            investigation_id=investigation_id,
            anomaly_type=anomaly_type,
            target_id=target_id,
            target_type=target_type,
            status=InvestigationStatus.QUEUED,
            spawned_at=now,
            assigned_agents=assigned,
            findings=metadata or {},
        )

        self._investigations[investigation_id] = investigation

        logger.info(
            "Spawned investigation {id} | type={t} | target={tgt} ({tt}) | agents={a}",
            id=investigation_id,
            t=anomaly_type.value,
            tgt=target_id,
            tt=target_type,
            a=assigned,
        )

        return investigation

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------

    def get_national_dashboard_stats(self) -> NationalDashboardStats:
        """Return current national-level monitoring statistics.

        Aggregates cached daily scores, investigation counts, and
        district-level risk classifications for the monitoring dashboard.

        Returns
        -------
        NationalDashboardStats
            Latest aggregated statistics.
        """
        stats = NationalDashboardStats(scan_date=datetime.utcnow())
        stats.total_gram_panchayats_scanned = len(self._daily_scores)

        # Count flagged works in the priority queue
        stats.total_works_flagged = len(self._priority_queue)

        # Classify districts
        for district_id, score in self._district_scores.items():
            stats.district_scores[district_id] = round(score, 4)
            if score >= self.HIGH_RISK_THRESHOLD:
                stats.high_risk_districts += 1
            elif score >= self.MEDIUM_RISK_THRESHOLD:
                stats.medium_risk_districts += 1
            else:
                stats.low_risk_districts += 1

        # Active investigations
        stats.active_investigations = sum(
            1
            for inv in self._investigations.values()
            if inv.status
            in (InvestigationStatus.IN_PROGRESS, InvestigationStatus.QUEUED)
        )

        # Anomaly type distribution
        anomaly_counts: Dict[str, int] = defaultdict(int)
        for breakdown in self._daily_scores.values():
            for flag in breakdown.anomaly_flags:
                anomaly_counts[flag] += 1
        stats.top_anomaly_types = dict(
            sorted(anomaly_counts.items(), key=lambda x: x[1], reverse=True)
        )

        # Count unique states and blocks
        states = set()
        blocks = set()
        for breakdown in self._daily_scores.values():
            states.add(breakdown.state_code)
            blocks.add(breakdown.block_id)
        stats.states_covered = len(states)
        stats.blocks_scanned = len(blocks)

        stats.estimated_leakage_crores = self._estimate_leakage()

        logger.info(
            "Dashboard stats generated | GPs={gps} | high_risk_districts={hd}",
            gps=stats.total_gram_panchayats_scanned,
            hd=stats.high_risk_districts,
        )
        return stats

    # ------------------------------------------------------------------
    # Priority queue management
    # ------------------------------------------------------------------

    def get_priority_queue(self, limit: int = 50) -> List[FlaggedWork]:
        """Return the top-N highest-risk flagged works.

        Parameters
        ----------
        limit : int
            Maximum number of items to return.

        Returns
        -------
        list of FlaggedWork
        """
        return sorted(
            self._priority_queue, key=lambda fw: fw.risk_score, reverse=True
        )[:limit]

    # ------------------------------------------------------------------
    # Private helpers -- data fetching
    # ------------------------------------------------------------------

    async def _fetch_active_gram_panchayats(self) -> List[Dict[str, Any]]:
        """Fetch the list of all active gram panchayats from NREGASoft.

        Returns a list of dicts with keys: ``gram_panchayat_id``,
        ``block_id``, ``district_id``, ``state_code``, ``panchayat_name``.
        """
        try:
            query = """
                SELECT gp.panchayat_code AS gram_panchayat_id,
                       gp.block_code     AS block_id,
                       gp.district_code  AS district_id,
                       gp.state_code     AS state_code,
                       gp.panchayat_name AS panchayat_name
                FROM   gram_panchayats gp
                WHERE  gp.is_active = TRUE
                ORDER  BY gp.state_code, gp.district_code, gp.block_code
            """
            results = await self.db.fetch_all(query)
            return [dict(row) for row in results]
        except Exception as exc:
            logger.error("Failed to fetch active GPs: {e}", e=exc)
            raise

    async def _fetch_gp_metadata(
        self, gram_panchayat_id: str
    ) -> Dict[str, Any]:
        """Return metadata for a single gram panchayat."""
        try:
            query = """
                SELECT gp.panchayat_code AS gram_panchayat_id,
                       gp.block_code     AS block_id,
                       gp.district_code  AS district_id,
                       gp.state_code     AS state_code,
                       gp.panchayat_name AS panchayat_name
                FROM   gram_panchayats gp
                WHERE  gp.panchayat_code = :gp_id
            """
            row = await self.db.fetch_one(
                query, {"gp_id": gram_panchayat_id}
            )
            return dict(row) if row else {}
        except Exception as exc:
            logger.error(
                "Failed to fetch GP metadata for {gp}: {e}",
                gp=gram_panchayat_id,
                e=exc,
            )
            raise

    # ------------------------------------------------------------------
    # Private helpers -- sub-score computation
    # ------------------------------------------------------------------

    async def _score_expenditure_anomaly(
        self, gram_panchayat_id: str
    ) -> float:
        """Compute the expenditure anomaly sub-score for a GP.

        Methodology:
        1. Fetch per-work expenditure for the GP in the current FY.
        2. Compare each work's cost against the block-level median for the
           same scheme/work-type using z-scores.
        3. Apply IQR-based outlier detection on the GP's own spending
           distribution.
        4. Check for suspicious year-end expenditure spikes (March surge).
        5. Normalise to [0, 1] where 1 = extreme anomaly.
        """
        try:
            # Fetch expenditure data
            expenditure_data = await self._fetch_expenditure_data(
                gram_panchayat_id
            )
            if not expenditure_data:
                return 0.0

            amounts = np.array(
                [record["total_expenditure"] for record in expenditure_data]
            )

            scores: List[float] = []

            # Z-score outlier detection
            if len(amounts) > 2:
                mean = np.mean(amounts)
                std = np.std(amounts)
                if std > 0:
                    z_scores = np.abs((amounts - mean) / std)
                    outlier_ratio = np.sum(z_scores > 2.0) / len(z_scores)
                    scores.append(min(outlier_ratio * 2.0, 1.0))

            # IQR-based detection
            if len(amounts) >= 4:
                q1, q3 = np.percentile(amounts, [25, 75])
                iqr = q3 - q1
                if iqr > 0:
                    upper_fence = q3 + 1.5 * iqr
                    iqr_outliers = np.sum(amounts > upper_fence) / len(amounts)
                    scores.append(min(iqr_outliers * 2.5, 1.0))

            # March surge detection
            march_data = [
                r
                for r in expenditure_data
                if r.get("month") == 3
            ]
            non_march = [
                r
                for r in expenditure_data
                if r.get("month") != 3
            ]
            if march_data and non_march:
                march_total = sum(
                    r["total_expenditure"] for r in march_data
                )
                non_march_avg = np.mean(
                    [r["total_expenditure"] for r in non_march]
                )
                if non_march_avg > 0:
                    march_ratio = march_total / (non_march_avg * len(march_data))
                    surge_score = min(max(march_ratio - 2.0, 0.0) / 3.0, 1.0)
                    scores.append(surge_score)

            return float(np.mean(scores)) if scores else 0.0

        except Exception as exc:
            logger.error(
                "Expenditure scoring failed for GP {gp}: {e}",
                gp=gram_panchayat_id,
                e=exc,
            )
            return 0.0

    async def _score_attendance_anomaly(
        self, gram_panchayat_id: str
    ) -> float:
        """Compute the attendance anomaly sub-score.

        Checks:
        - Muster roll attendance correlation (clone detection).
        - Benford's law deviation on reported person-days.
        - Seasonal feasibility (earthwork during peak monsoon).
        - Biometric authentication rate vs total person-days.
        """
        try:
            attendance_data = await self._fetch_attendance_data(
                gram_panchayat_id
            )
            if not attendance_data:
                return 0.0

            scores: List[float] = []

            # Benford's law on person-days
            person_days = [
                r["person_days"]
                for r in attendance_data
                if r.get("person_days", 0) > 0
            ]
            if person_days:
                benford_score = self._benford_deviation(person_days)
                scores.append(benford_score)

            # Biometric authentication gap
            total_days = sum(
                r.get("person_days", 0) for r in attendance_data
            )
            bio_days = sum(
                r.get("biometric_verified_days", 0) for r in attendance_data
            )
            if total_days > 0:
                bio_gap = 1.0 - (bio_days / total_days)
                scores.append(min(bio_gap * 1.5, 1.0))

            # Monsoon work detection (June-September)
            monsoon_earthwork = [
                r
                for r in attendance_data
                if r.get("month") in (6, 7, 8, 9)
                and r.get("work_category") == "earthwork"
                and r.get("person_days", 0) > 50
            ]
            if attendance_data:
                monsoon_ratio = len(monsoon_earthwork) / max(
                    len(attendance_data), 1
                )
                scores.append(min(monsoon_ratio * 5.0, 1.0))

            return float(np.mean(scores)) if scores else 0.0

        except Exception as exc:
            logger.error(
                "Attendance scoring failed for GP {gp}: {e}",
                gp=gram_panchayat_id,
                e=exc,
            )
            return 0.0

    async def _score_satellite_verification(
        self, gram_panchayat_id: str
    ) -> float:
        """Score based on satellite verification results.

        Pulls cached satellite verification outcomes and computes the
        fraction of works with measurement mismatches or unverifiable
        ground truth.
        """
        try:
            verifications = await self._fetch_satellite_results(
                gram_panchayat_id
            )
            if not verifications:
                return 0.0

            mismatch_count = sum(
                1
                for v in verifications
                if v.get("verification_status") == "mismatch"
                or v.get("confidence_score", 1.0) < 0.5
            )
            not_detected_count = sum(
                1
                for v in verifications
                if v.get("verification_status") == "not_detected"
            )

            total = len(verifications)
            mismatch_ratio = mismatch_count / total
            not_detected_ratio = not_detected_count / total

            # Combine: full weight for mismatches, partial for not-detected
            score = min(mismatch_ratio + 0.5 * not_detected_ratio, 1.0)
            return score

        except Exception as exc:
            logger.error(
                "Satellite scoring failed for GP {gp}: {e}",
                gp=gram_panchayat_id,
                e=exc,
            )
            return 0.0

    async def _score_photo_anomaly(
        self, gram_panchayat_id: str
    ) -> float:
        """Score based on GeoMGNREGA photo verification results.

        Considers GPS mismatches, duplicate photos, content-type mismatches,
        and bulk upload indicators.
        """
        try:
            photo_results = await self._fetch_photo_results(
                gram_panchayat_id
            )
            if not photo_results:
                return 0.0

            total = len(photo_results)
            gps_mismatches = sum(
                1 for p in photo_results if p.get("gps_mismatch")
            )
            duplicates = sum(
                1 for p in photo_results if p.get("is_duplicate")
            )
            type_mismatches = sum(
                1 for p in photo_results if p.get("type_mismatch")
            )
            bulk_flags = sum(
                1 for p in photo_results if p.get("bulk_upload_flag")
            )

            # Weighted combination of photo issue ratios
            score = (
                0.3 * (gps_mismatches / total)
                + 0.3 * (duplicates / total)
                + 0.25 * (type_mismatches / total)
                + 0.15 * (bulk_flags / total)
            )
            return min(score * 2.0, 1.0)  # amplify signal

        except Exception as exc:
            logger.error(
                "Photo scoring failed for GP {gp}: {e}",
                gp=gram_panchayat_id,
                e=exc,
            )
            return 0.0

    async def _score_payment_anomaly(
        self, gram_panchayat_id: str
    ) -> float:
        """Score based on payment pattern analysis.

        Incorporates labor-material ratio violations, shell beneficiary
        indicators, and payment splitting flags.
        """
        try:
            payment_data = await self._fetch_payment_data(
                gram_panchayat_id
            )
            if not payment_data:
                return 0.0

            scores: List[float] = []

            # Labor-material ratio check (MGNREGA mandates >= 60% labor)
            for work in payment_data:
                labour = work.get("labour_expenditure", 0)
                material = work.get("material_expenditure", 0)
                total = labour + material
                if total > 0:
                    labour_ratio = labour / total
                    if labour_ratio < 0.60:
                        violation_severity = (0.60 - labour_ratio) / 0.60
                        scores.append(min(violation_severity * 2.0, 1.0))

            # Shell beneficiary indicator
            shell_count = sum(
                1
                for w in payment_data
                if w.get("multi_panchayat_account", False)
            )
            if payment_data:
                scores.append(
                    min(shell_count / len(payment_data) * 3.0, 1.0)
                )

            # Payment splitting detection
            split_flags = sum(
                1 for w in payment_data if w.get("split_payment_flag", False)
            )
            if payment_data:
                scores.append(
                    min(split_flags / len(payment_data) * 2.5, 1.0)
                )

            return float(np.mean(scores)) if scores else 0.0

        except Exception as exc:
            logger.error(
                "Payment scoring failed for GP {gp}: {e}",
                gp=gram_panchayat_id,
                e=exc,
            )
            return 0.0

    # ------------------------------------------------------------------
    # Private helpers -- statistical utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _benford_deviation(values: List[float]) -> float:
        """Compute deviation from Benford's law for first-digit distribution.

        Parameters
        ----------
        values : list of float
            Non-zero positive numerical values.

        Returns
        -------
        float
            Score in [0, 1] where 1 = maximum deviation from Benford's.
        """
        expected = {
            d: np.log10(1 + 1 / d) for d in range(1, 10)
        }

        first_digits = []
        for v in values:
            s = str(abs(int(v)))
            if s and s[0] != "0":
                first_digits.append(int(s[0]))

        if len(first_digits) < 10:
            return 0.0

        observed: Dict[int, float] = {}
        total = len(first_digits)
        for d in range(1, 10):
            observed[d] = first_digits.count(d) / total

        # Chi-squared-like deviation
        deviation = sum(
            (observed.get(d, 0) - expected[d]) ** 2 / expected[d]
            for d in range(1, 10)
        )

        # Normalise to [0, 1] -- empirical scaling
        normalised = min(deviation / 0.1, 1.0)
        return normalised

    # ------------------------------------------------------------------
    # Private helpers -- aggregation and processing
    # ------------------------------------------------------------------

    def _process_risk_score(
        self, breakdown: RiskScoreBreakdown, stats: NationalDashboardStats
    ) -> None:
        """Process a single GP risk score: update caches and queue."""
        # Update district / block aggregation
        self._district_scores[breakdown.district_id] = max(
            self._district_scores.get(breakdown.district_id, 0.0),
            breakdown.composite_score,
        )
        self._block_scores[breakdown.block_id] = max(
            self._block_scores.get(breakdown.block_id, 0.0),
            breakdown.composite_score,
        )

        # Flag works exceeding the investigation threshold
        if breakdown.composite_score >= self.investigation_threshold:
            flagged = FlaggedWork(
                priority=-breakdown.composite_score,  # min-heap inversion
                work_id=f"GP-{breakdown.gram_panchayat_id}",
                gram_panchayat_id=breakdown.gram_panchayat_id,
                block_id=breakdown.block_id,
                district_id=breakdown.district_id,
                state_code=breakdown.state_code,
                anomaly_types=[
                    AnomalyType(f) for f in breakdown.anomaly_flags
                ],
                risk_score=breakdown.composite_score,
                metadata={"breakdown": breakdown.__dict__},
            )
            heapq.heappush(self._priority_queue, flagged)
            stats.total_works_flagged += 1

    def _aggregate_hierarchical_scores(
        self, stats: NationalDashboardStats
    ) -> None:
        """Classify districts into risk tiers and record in stats."""
        for district_id, score in self._district_scores.items():
            stats.district_scores[district_id] = round(score, 4)
            if score >= self.HIGH_RISK_THRESHOLD:
                stats.high_risk_districts += 1
            elif score >= self.MEDIUM_RISK_THRESHOLD:
                stats.medium_risk_districts += 1
            else:
                stats.low_risk_districts += 1

    def _estimate_leakage(self) -> float:
        """Rough estimate of financial leakage from flagged GPs.

        Uses a heuristic: for each flagged GP, leakage ~ composite_score
        multiplied by the GP's annual expenditure. Returns value in crores.
        """
        total_leakage = 0.0
        for breakdown in self._daily_scores.values():
            if breakdown.composite_score >= self.MEDIUM_RISK_THRESHOLD:
                # Placeholder: in production, multiply by actual GP expenditure
                estimated_gp_expenditure_lakhs = 50.0  # average MGNREGA GP spend
                leakage_fraction = breakdown.composite_score * 0.3
                total_leakage += (
                    estimated_gp_expenditure_lakhs * leakage_fraction
                )
        return round(total_leakage / 100.0, 2)  # convert lakhs to crores

    # ------------------------------------------------------------------
    # Private helpers -- data layer stubs (to be wired to real DB)
    # ------------------------------------------------------------------

    async def _fetch_expenditure_data(
        self, gram_panchayat_id: str
    ) -> List[Dict[str, Any]]:
        """Fetch monthly expenditure records for a GP."""
        query = """
            SELECT w.work_id,
                   w.total_expenditure,
                   EXTRACT(MONTH FROM w.expenditure_date) AS month,
                   w.work_type,
                   w.scheme_name
            FROM   works w
            WHERE  w.gram_panchayat_id = :gp_id
              AND  w.financial_year = :fy
            ORDER  BY w.expenditure_date
        """
        fin_year = self.config.get("financial_year", "2025-2026")
        rows = await self.db.fetch_all(
            query, {"gp_id": gram_panchayat_id, "fy": fin_year}
        )
        return [dict(r) for r in rows]

    async def _fetch_attendance_data(
        self, gram_panchayat_id: str
    ) -> List[Dict[str, Any]]:
        """Fetch muster roll attendance summaries for a GP."""
        query = """
            SELECT mr.muster_roll_id,
                   mr.work_id,
                   mr.person_days,
                   mr.biometric_verified_days,
                   mr.work_category,
                   EXTRACT(MONTH FROM mr.from_date) AS month
            FROM   muster_rolls mr
                   JOIN works w ON mr.work_id = w.work_id
            WHERE  w.gram_panchayat_id = :gp_id
              AND  w.financial_year = :fy
        """
        fin_year = self.config.get("financial_year", "2025-2026")
        rows = await self.db.fetch_all(
            query, {"gp_id": gram_panchayat_id, "fy": fin_year}
        )
        return [dict(r) for r in rows]

    async def _fetch_satellite_results(
        self, gram_panchayat_id: str
    ) -> List[Dict[str, Any]]:
        """Fetch cached satellite verification results."""
        query = """
            SELECT sv.work_id,
                   sv.verification_status,
                   sv.confidence_score,
                   sv.measurement_deviation_pct
            FROM   satellite_verifications sv
                   JOIN works w ON sv.work_id = w.work_id
            WHERE  w.gram_panchayat_id = :gp_id
              AND  w.financial_year = :fy
        """
        fin_year = self.config.get("financial_year", "2025-2026")
        rows = await self.db.fetch_all(
            query, {"gp_id": gram_panchayat_id, "fy": fin_year}
        )
        return [dict(r) for r in rows]

    async def _fetch_photo_results(
        self, gram_panchayat_id: str
    ) -> List[Dict[str, Any]]:
        """Fetch cached photo verification results."""
        query = """
            SELECT pv.photo_id,
                   pv.work_id,
                   pv.gps_mismatch,
                   pv.is_duplicate,
                   pv.type_mismatch,
                   pv.bulk_upload_flag
            FROM   photo_verifications pv
                   JOIN works w ON pv.work_id = w.work_id
            WHERE  w.gram_panchayat_id = :gp_id
              AND  w.financial_year = :fy
        """
        fin_year = self.config.get("financial_year", "2025-2026")
        rows = await self.db.fetch_all(
            query, {"gp_id": gram_panchayat_id, "fy": fin_year}
        )
        return [dict(r) for r in rows]

    async def _fetch_payment_data(
        self, gram_panchayat_id: str
    ) -> List[Dict[str, Any]]:
        """Fetch payment and expenditure breakdown for a GP's works."""
        query = """
            SELECT w.work_id,
                   w.labour_expenditure,
                   w.material_expenditure,
                   w.total_expenditure,
                   CASE WHEN ba.multi_panchayat THEN TRUE ELSE FALSE END
                       AS multi_panchayat_account,
                   w.split_payment_flag
            FROM   works w
                   LEFT JOIN bank_accounts ba
                       ON w.primary_account_id = ba.account_id
            WHERE  w.gram_panchayat_id = :gp_id
              AND  w.financial_year = :fy
        """
        fin_year = self.config.get("financial_year", "2025-2026")
        rows = await self.db.fetch_all(
            query, {"gp_id": gram_panchayat_id, "fy": fin_year}
        )
        return [dict(r) for r in rows]
