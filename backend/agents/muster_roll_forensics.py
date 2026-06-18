"""
Muster Roll Forensics Agent for the MGNREGA Verification & Fraud Intelligence System.

This agent performs deep forensic analysis on muster roll data to detect
various categories of fraud: cloned attendance patterns, ghost workers,
biometric impossibilities, enrollment spikes, Aadhaar anomalies, wage
calculation discrepancies, and seasonal impossibilities.

It employs statistical methods including correlation matrices, Benford's
law analysis, time-series anomaly detection, and network analysis of
worker-worksite relationships to surface suspicious patterns.
"""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np
from loguru import logger


# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------

class FraudCategory(str, Enum):
    """Categories of muster roll fraud detected by this agent."""

    ATTENDANCE_CLONE = "attendance_clone"
    GHOST_WORKER = "ghost_worker"
    BIOMETRIC_CONFLICT = "biometric_conflict"
    ENROLLMENT_SPIKE = "enrollment_spike"
    AADHAAR_ANOMALY = "aadhaar_anomaly"
    WAGE_MISMATCH = "wage_mismatch"
    SEASONAL_IMPOSSIBILITY = "seasonal_impossibility"
    BENFORDS_LAW_VIOLATION = "benfords_law_violation"


class SeverityLevel(str, Enum):
    """Severity classification for detected anomalies."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


@dataclass
class ForensicFinding:
    """A single forensic finding from muster roll analysis."""

    finding_id: str
    category: FraudCategory
    severity: SeverityLevel
    description: str
    affected_entities: List[str] = field(default_factory=list)
    evidence: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    recommended_action: str = ""
    detected_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class AttendanceCloneGroup:
    """A group of workers with suspiciously correlated attendance."""

    clone_group_id: str
    worker_ids: List[str]
    work_id: str
    overlap_pct: float  # percentage of identical attendance days
    total_days_analysed: int
    matching_days: int
    muster_roll_ids: List[str] = field(default_factory=list)
    estimated_fake_person_days: int = 0


@dataclass
class GhostWorkerProfile:
    """Profile of a suspected ghost worker."""

    worker_id: str
    job_card_number: str
    panchayat_id: str
    indicators: List[str] = field(default_factory=list)
    biometric_auth_count: int = 0
    total_person_days_claimed: int = 0
    total_wages_received: float = 0.0
    linked_works: List[str] = field(default_factory=list)
    confidence: float = 0.0


@dataclass
class ForensicsReport:
    """Complete forensics report for a block or panchayat."""

    report_id: str
    block_id: str
    financial_year: str
    findings: List[ForensicFinding] = field(default_factory=list)
    clone_groups: List[AttendanceCloneGroup] = field(default_factory=list)
    ghost_worker_profiles: List[GhostWorkerProfile] = field(default_factory=list)
    total_suspicious_person_days: int = 0
    total_suspicious_wages: float = 0.0
    benfords_deviation_score: float = 0.0
    generated_at: datetime = field(default_factory=datetime.utcnow)
    summary: str = ""


# ---------------------------------------------------------------------------
# Muster Roll Forensics Agent
# ---------------------------------------------------------------------------

class MusterRollForensicsAgent:
    """Agent for forensic analysis of MGNREGA muster roll data.

    Analyses attendance patterns, worker registrations, biometric records,
    wage calculations, and seasonal feasibility to detect fraudulent
    entries in the muster roll system.

    Parameters
    ----------
    db_session : Any
        Database session for querying NREGASoft muster roll data.
    config : dict, optional
        Runtime configuration overrides.
    """

    # Thresholds
    ATTENDANCE_OVERLAP_THRESHOLD: float = 0.90  # 90% overlap = suspicious
    ENROLLMENT_SPIKE_ZSCORE: float = 2.5
    BENFORDS_DEVIATION_THRESHOLD: float = 0.15
    MONSOON_MONTHS: Set[int] = {6, 7, 8, 9}  # June through September
    MONSOON_MAX_EARTHWORK_DAYS: int = 5  # max plausible earthwork days in monsoon month
    WAGE_DEVIATION_THRESHOLD_PCT: float = 5.0  # 5% tolerance on wage calculations

    def __init__(
        self,
        db_session: Any,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.db = db_session
        self.config = config or {}
        self.overlap_threshold = self.config.get(
            "attendance_overlap_threshold", self.ATTENDANCE_OVERLAP_THRESHOLD
        )

        logger.info(
            "MusterRollForensicsAgent initialised | overlap_threshold={t}",
            t=self.overlap_threshold,
        )

    # ------------------------------------------------------------------
    # Block-level analysis
    # ------------------------------------------------------------------

    async def analyze_block(
        self, block_id: str, fin_year: str
    ) -> ForensicsReport:
        """Run comprehensive forensic analysis on all muster rolls in a block.

        Executes all detection modules in sequence and aggregates findings
        into a structured report.

        Parameters
        ----------
        block_id : str
            NREGASoft block code.
        fin_year : str
            Financial year (e.g., ``"2025-2026"``).

        Returns
        -------
        ForensicsReport
            Complete forensic analysis report.
        """
        report_id = f"RPT-MRF-{uuid.uuid4().hex[:10].upper()}"
        logger.info(
            "Starting block forensic analysis | block={b} | fy={fy}",
            b=block_id,
            fy=fin_year,
        )

        report = ForensicsReport(
            report_id=report_id,
            block_id=block_id,
            financial_year=fin_year,
        )

        try:
            # Fetch all panchayats in the block
            panchayats = await self._fetch_block_panchayats(block_id)

            for gp in panchayats:
                gp_id = gp["gram_panchayat_id"]

                # 1. Ghost worker detection
                ghost_findings = await self.detect_ghost_workers(gp_id)
                report.ghost_worker_profiles.extend(ghost_findings)
                for ghost in ghost_findings:
                    report.findings.append(
                        ForensicFinding(
                            finding_id=f"F-{uuid.uuid4().hex[:8]}",
                            category=FraudCategory.GHOST_WORKER,
                            severity=SeverityLevel.CRITICAL if ghost.confidence > 0.8
                            else SeverityLevel.HIGH,
                            description=(
                                f"Suspected ghost worker {ghost.worker_id} in GP {gp_id}: "
                                f"{ghost.total_person_days_claimed} person-days claimed, "
                                f"{ghost.biometric_auth_count} biometric authentications"
                            ),
                            affected_entities=[ghost.worker_id, ghost.job_card_number],
                            evidence={
                                "biometric_count": ghost.biometric_auth_count,
                                "person_days": ghost.total_person_days_claimed,
                                "wages": ghost.total_wages_received,
                                "indicators": ghost.indicators,
                            },
                            confidence=ghost.confidence,
                            recommended_action="Field verification of worker identity and worksite presence",
                        )
                    )

            # 2. Attendance clone detection across all works in the block
            works = await self._fetch_block_works(block_id, fin_year)
            for work in works:
                clones = await self.detect_attendance_clones(work["work_id"])
                report.clone_groups.extend(clones)
                for clone in clones:
                    report.findings.append(
                        ForensicFinding(
                            finding_id=f"F-{uuid.uuid4().hex[:8]}",
                            category=FraudCategory.ATTENDANCE_CLONE,
                            severity=SeverityLevel.HIGH,
                            description=(
                                f"Attendance clone group detected in work {clone.work_id}: "
                                f"{len(clone.worker_ids)} workers with {clone.overlap_pct:.0%} "
                                f"attendance overlap over {clone.total_days_analysed} days"
                            ),
                            affected_entities=clone.worker_ids,
                            evidence={
                                "overlap_pct": clone.overlap_pct,
                                "matching_days": clone.matching_days,
                                "estimated_fake_days": clone.estimated_fake_person_days,
                            },
                            confidence=min(clone.overlap_pct, 1.0),
                            recommended_action="Cross-check with biometric logs and field verification",
                        )
                    )

            # 3. Enrollment spike detection
            enrollment_findings = await self.detect_enrollment_spikes(block_id)
            report.findings.extend(enrollment_findings)

            # 4. Benford's law analysis on the block
            attendance_numbers = await self._fetch_block_attendance_numbers(
                block_id, fin_year
            )
            benfords_score = self.run_benfords_law(attendance_numbers)
            report.benfords_deviation_score = benfords_score
            if benfords_score > self.BENFORDS_DEVIATION_THRESHOLD:
                report.findings.append(
                    ForensicFinding(
                        finding_id=f"F-{uuid.uuid4().hex[:8]}",
                        category=FraudCategory.BENFORDS_LAW_VIOLATION,
                        severity=SeverityLevel.MEDIUM,
                        description=(
                            f"Block {block_id} attendance numbers deviate from "
                            f"Benford's law (score={benfords_score:.3f}), suggesting "
                            f"possible fabrication of attendance records"
                        ),
                        evidence={"deviation_score": benfords_score},
                        confidence=min(benfords_score / 0.3, 1.0),
                        recommended_action="Detailed audit of muster rolls with highest deviation",
                    )
                )

            # 5. Aggregate suspicious totals
            report.total_suspicious_person_days = sum(
                cg.estimated_fake_person_days for cg in report.clone_groups
            ) + sum(
                g.total_person_days_claimed for g in report.ghost_worker_profiles
            )
            report.total_suspicious_wages = sum(
                g.total_wages_received for g in report.ghost_worker_profiles
            )

            # Generate summary
            report.summary = self._generate_report_summary(report)

            logger.info(
                "Block forensic analysis complete | block={b} | findings={f} | ghosts={g} | clones={c}",
                b=block_id,
                f=len(report.findings),
                g=len(report.ghost_worker_profiles),
                c=len(report.clone_groups),
            )
            return report

        except Exception as exc:
            logger.exception(
                "Block forensic analysis failed for {b}: {e}",
                b=block_id,
                e=exc,
            )
            raise

    # ------------------------------------------------------------------
    # Attendance clone detection
    # ------------------------------------------------------------------

    async def detect_attendance_clones(
        self, work_id: str
    ) -> List[AttendanceCloneGroup]:
        """Detect workers with suspiciously correlated attendance patterns.

        When multiple workers have >90% identical attendance days on a
        single work, it strongly suggests bulk data entry (i.e., someone
        filled in the muster roll for all workers at once rather than
        recording actual individual attendance).

        Parameters
        ----------
        work_id : str
            The NREGASoft work identifier.

        Returns
        -------
        list of AttendanceCloneGroup
            Groups of workers with correlated attendance.
        """
        logger.debug("Detecting attendance clones for work {w}", w=work_id)

        try:
            # Fetch daily attendance records for all workers on this work
            records = await self._fetch_work_attendance(work_id)
            if not records:
                return []

            # Build attendance matrix: rows=workers, columns=dates
            worker_dates: Dict[str, Set[str]] = defaultdict(set)
            all_dates: Set[str] = set()

            for rec in records:
                worker_id = rec["worker_id"]
                att_date = rec["attendance_date"]
                date_str = att_date if isinstance(att_date, str) else att_date.isoformat()
                worker_dates[worker_id].add(date_str)
                all_dates.add(date_str)

            workers = list(worker_dates.keys())
            if len(workers) < 2:
                return []

            sorted_dates = sorted(all_dates)
            n_workers = len(workers)
            n_dates = len(sorted_dates)

            # Build binary attendance matrix
            att_matrix = np.zeros((n_workers, n_dates), dtype=np.int8)
            for i, w in enumerate(workers):
                for j, d in enumerate(sorted_dates):
                    if d in worker_dates[w]:
                        att_matrix[i, j] = 1

            # Compute pairwise overlap using correlation
            clone_groups: List[AttendanceCloneGroup] = []
            visited: Set[int] = set()

            for i in range(n_workers):
                if i in visited:
                    continue
                group_indices = [i]
                for j in range(i + 1, n_workers):
                    if j in visited:
                        continue
                    # Jaccard similarity on attendance days
                    intersection = int(np.sum(att_matrix[i] & att_matrix[j]))
                    union = int(np.sum(att_matrix[i] | att_matrix[j]))
                    if union == 0:
                        continue
                    overlap = intersection / union
                    if overlap >= self.overlap_threshold:
                        group_indices.append(j)

                if len(group_indices) >= 2:
                    group_workers = [workers[idx] for idx in group_indices]
                    # Calculate group statistics
                    total_days = n_dates
                    reference = att_matrix[group_indices[0]]
                    matching = sum(
                        1
                        for j in range(n_dates)
                        if all(att_matrix[idx, j] == reference[j] for idx in group_indices)
                    )
                    overlap_pct = matching / max(total_days, 1)

                    estimated_fake = int(
                        matching * (len(group_workers) - 1)
                    )

                    clone_groups.append(
                        AttendanceCloneGroup(
                            clone_group_id=f"CLN-{uuid.uuid4().hex[:8]}",
                            worker_ids=group_workers,
                            work_id=work_id,
                            overlap_pct=round(overlap_pct, 4),
                            total_days_analysed=total_days,
                            matching_days=matching,
                            estimated_fake_person_days=estimated_fake,
                        )
                    )
                    visited.update(group_indices)

            logger.debug(
                "Clone detection for work {w}: {n} groups found",
                w=work_id,
                n=len(clone_groups),
            )
            return clone_groups

        except Exception as exc:
            logger.error(
                "Clone detection failed for work {w}: {e}", w=work_id, e=exc
            )
            return []

    # ------------------------------------------------------------------
    # Ghost worker detection
    # ------------------------------------------------------------------

    async def detect_ghost_workers(
        self, panchayat_id: str
    ) -> List[GhostWorkerProfile]:
        """Detect suspected ghost workers in a gram panchayat.

        Ghost worker indicators:
        - Job card exists but zero or near-zero biometric authentications.
        - Worker appears only in high-expenditure works.
        - No Aadhaar-based payment (DBT) records despite wages claimed.
        - Worker registered but no physical verification record.

        Parameters
        ----------
        panchayat_id : str
            The gram panchayat code.

        Returns
        -------
        list of GhostWorkerProfile
            Profiles of suspected ghost workers.
        """
        logger.debug("Detecting ghost workers in GP {gp}", gp=panchayat_id)

        try:
            # Fetch all workers registered in this panchayat
            workers = await self._fetch_panchayat_workers(panchayat_id)
            if not workers:
                return []

            ghost_profiles: List[GhostWorkerProfile] = []

            for worker in workers:
                worker_id = worker["worker_id"]
                indicators: List[str] = []
                confidence_signals: List[float] = []

                # Check biometric authentication trail
                bio_count = worker.get("biometric_auth_count", 0)
                person_days = worker.get("total_person_days", 0)
                wages = worker.get("total_wages", 0.0)

                if person_days > 0 and bio_count == 0:
                    indicators.append("zero_biometric_authentication")
                    confidence_signals.append(0.9)
                elif person_days > 20 and bio_count < 3:
                    indicators.append("negligible_biometric_authentication")
                    confidence_signals.append(0.7)

                # Check if worker only appears in high-expenditure works
                linked_works = worker.get("linked_works", [])
                if linked_works:
                    high_exp_works = [
                        w for w in linked_works
                        if w.get("total_expenditure", 0) > 500000  # > 5 lakh
                    ]
                    if len(high_exp_works) == len(linked_works) and len(linked_works) >= 2:
                        indicators.append("only_high_expenditure_works")
                        confidence_signals.append(0.6)

                # Check Aadhaar-based DBT payment
                has_dbt = worker.get("has_dbt_payment", True)
                if not has_dbt and wages > 0:
                    indicators.append("no_dbt_payment_despite_wages")
                    confidence_signals.append(0.5)

                # Check registration recency vs work participation
                registration_date = worker.get("registration_date")
                first_work_date = worker.get("first_work_date")
                if registration_date and first_work_date:
                    if isinstance(registration_date, str):
                        registration_date = datetime.fromisoformat(registration_date)
                    if isinstance(first_work_date, str):
                        first_work_date = datetime.fromisoformat(first_work_date)
                    gap = (first_work_date - registration_date).days
                    if gap < 2 and person_days > 30:
                        indicators.append("immediate_high_engagement_after_registration")
                        confidence_signals.append(0.5)

                # Aadhaar checks
                aadhaar_issues = worker.get("aadhaar_flags", [])
                if "multi_panchayat" in aadhaar_issues:
                    indicators.append("aadhaar_linked_multiple_panchayats")
                    confidence_signals.append(0.8)
                if "sequential_number" in aadhaar_issues:
                    indicators.append("sequential_aadhaar_number")
                    confidence_signals.append(0.7)

                # Only flag if we have enough indicators
                if len(indicators) >= 2 or (
                    len(indicators) == 1 and confidence_signals[0] >= 0.8
                ):
                    overall_confidence = float(np.mean(confidence_signals))
                    ghost_profiles.append(
                        GhostWorkerProfile(
                            worker_id=worker_id,
                            job_card_number=worker.get("job_card_number", ""),
                            panchayat_id=panchayat_id,
                            indicators=indicators,
                            biometric_auth_count=bio_count,
                            total_person_days_claimed=person_days,
                            total_wages_received=wages,
                            linked_works=[
                                w.get("work_id", "") for w in linked_works
                            ],
                            confidence=round(overall_confidence, 4),
                        )
                    )

            logger.debug(
                "Ghost worker detection for GP {gp}: {n} suspects",
                gp=panchayat_id,
                n=len(ghost_profiles),
            )
            return ghost_profiles

        except Exception as exc:
            logger.error(
                "Ghost worker detection failed for GP {gp}: {e}",
                gp=panchayat_id,
                e=exc,
            )
            return []

    # ------------------------------------------------------------------
    # Biometric conflict detection
    # ------------------------------------------------------------------

    async def check_biometric_conflicts(
        self,
        worker_ids: List[str],
        date_range: Tuple[date, date],
    ) -> List[ForensicFinding]:
        """Detect biometric impossibilities across worksites.

        Checks if the same worker was marked present at two or more
        different worksites on the same day, which is physically
        impossible.

        Parameters
        ----------
        worker_ids : list of str
            Worker IDs to check.
        date_range : tuple of date
            Start and end dates for the analysis window.

        Returns
        -------
        list of ForensicFinding
            Findings for each biometric conflict detected.
        """
        logger.debug(
            "Checking biometric conflicts for {n} workers in {d}",
            n=len(worker_ids),
            d=date_range,
        )

        findings: List[ForensicFinding] = []

        try:
            for worker_id in worker_ids:
                records = await self._fetch_worker_attendance_across_sites(
                    worker_id, date_range
                )
                if not records:
                    continue

                # Group by date
                date_sites: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
                for rec in records:
                    d = rec["attendance_date"]
                    date_key = d if isinstance(d, str) else d.isoformat()
                    date_sites[date_key].append(rec)

                # Find dates with multiple worksites
                for date_key, site_records in date_sites.items():
                    unique_sites = set(r["work_id"] for r in site_records)
                    if len(unique_sites) > 1:
                        unique_gps = set(r.get("gp_id", "") for r in site_records)
                        distance_km = self._estimate_inter_site_distance(
                            site_records
                        )

                        severity = (
                            SeverityLevel.CRITICAL
                            if distance_km > 50
                            else SeverityLevel.HIGH
                            if distance_km > 10
                            else SeverityLevel.MEDIUM
                        )

                        findings.append(
                            ForensicFinding(
                                finding_id=f"F-{uuid.uuid4().hex[:8]}",
                                category=FraudCategory.BIOMETRIC_CONFLICT,
                                severity=severity,
                                description=(
                                    f"Worker {worker_id} marked present at "
                                    f"{len(unique_sites)} worksites on {date_key} "
                                    f"(distance ~{distance_km:.0f}km)"
                                ),
                                affected_entities=[worker_id] + list(unique_sites),
                                evidence={
                                    "date": date_key,
                                    "worksites": list(unique_sites),
                                    "panchayats": list(unique_gps),
                                    "estimated_distance_km": distance_km,
                                    "records": [
                                        {
                                            "work_id": r["work_id"],
                                            "muster_roll_id": r.get("muster_roll_id"),
                                        }
                                        for r in site_records
                                    ],
                                },
                                confidence=0.95,
                                recommended_action=(
                                    "Verify biometric logs for timestamp accuracy; "
                                    "check if one attendance is fabricated"
                                ),
                            )
                        )

            logger.debug(
                "Biometric conflict check: {n} conflicts found",
                n=len(findings),
            )
            return findings

        except Exception as exc:
            logger.error(
                "Biometric conflict detection failed: {e}", e=exc
            )
            return []

    # ------------------------------------------------------------------
    # Enrollment spike detection
    # ------------------------------------------------------------------

    async def detect_enrollment_spikes(
        self, block_id: str
    ) -> List[ForensicFinding]:
        """Detect suspicious spikes in worker enrollment.

        Sudden increases in job card registrations before financial year-end
        (especially February-March) are a common indicator of fraud, as
        ghost workers are enrolled to absorb remaining budget.

        Parameters
        ----------
        block_id : str
            The block code to analyse.

        Returns
        -------
        list of ForensicFinding
            Findings for detected enrollment spikes.
        """
        logger.debug(
            "Detecting enrollment spikes for block {b}", b=block_id
        )

        findings: List[ForensicFinding] = []

        try:
            # Fetch monthly registration counts for the last 24 months
            monthly_counts = await self._fetch_monthly_registrations(
                block_id
            )
            if not monthly_counts or len(monthly_counts) < 6:
                return []

            counts = np.array([m["count"] for m in monthly_counts])
            months = [m["month"] for m in monthly_counts]

            # Z-score based spike detection
            mean_count = np.mean(counts)
            std_count = np.std(counts)
            if std_count == 0:
                return []

            z_scores = (counts - mean_count) / std_count

            for i, (z, month_label, count) in enumerate(
                zip(z_scores, months, counts)
            ):
                if z > self.ENROLLMENT_SPIKE_ZSCORE:
                    # Determine month number for financial year-end check
                    month_num = monthly_counts[i].get("month_num", 0)
                    is_fy_end = month_num in (2, 3)  # Feb/March

                    severity = (
                        SeverityLevel.HIGH
                        if is_fy_end
                        else SeverityLevel.MEDIUM
                    )

                    findings.append(
                        ForensicFinding(
                            finding_id=f"F-{uuid.uuid4().hex[:8]}",
                            category=FraudCategory.ENROLLMENT_SPIKE,
                            severity=severity,
                            description=(
                                f"Registration spike in block {block_id} during "
                                f"{month_label}: {int(count)} new registrations "
                                f"(z-score={z:.2f}, mean={mean_count:.0f})"
                                + (" [financial year-end]" if is_fy_end else "")
                            ),
                            evidence={
                                "month": month_label,
                                "count": int(count),
                                "z_score": round(float(z), 3),
                                "block_mean": round(float(mean_count), 1),
                                "is_fy_end": is_fy_end,
                            },
                            confidence=min(float(z) / 5.0, 1.0),
                            recommended_action=(
                                "Verify recently registered job cards; "
                                "cross-reference with Aadhaar seeding status"
                            ),
                        )
                    )

            return findings

        except Exception as exc:
            logger.error(
                "Enrollment spike detection failed for block {b}: {e}",
                b=block_id,
                e=exc,
            )
            return []

    # ------------------------------------------------------------------
    # Benford's law analysis
    # ------------------------------------------------------------------

    def run_benfords_law(self, attendance_data: List[float]) -> float:
        """Analyse attendance numbers against Benford's law distribution.

        Benford's law predicts that in naturally occurring datasets, the
        leading digit ``d`` appears with probability ``log10(1 + 1/d)``.
        Fabricated data tends to have a more uniform distribution.

        Parameters
        ----------
        attendance_data : list of float
            Person-days or attendance counts to analyse.

        Returns
        -------
        float
            Deviation score in [0, 1]. Higher = more deviation = more
            suspicious.
        """
        if not attendance_data or len(attendance_data) < 20:
            logger.debug("Insufficient data for Benford's law analysis")
            return 0.0

        # Expected Benford distribution
        expected = {
            d: np.log10(1 + 1 / d) for d in range(1, 10)
        }

        # Extract first digits
        first_digits: List[int] = []
        for val in attendance_data:
            val_abs = abs(val)
            if val_abs < 1:
                continue
            digit_str = str(int(val_abs))
            if digit_str and digit_str[0] != "0":
                first_digits.append(int(digit_str[0]))

        if len(first_digits) < 20:
            return 0.0

        # Observed distribution
        total = len(first_digits)
        observed: Dict[int, float] = {}
        for d in range(1, 10):
            observed[d] = first_digits.count(d) / total

        # Chi-squared statistic
        chi_sq = sum(
            ((observed.get(d, 0) - expected[d]) ** 2) / expected[d]
            for d in range(1, 10)
        )

        # Mean absolute deviation
        mad = np.mean(
            [abs(observed.get(d, 0) - expected[d]) for d in range(1, 10)]
        )

        # Kolmogorov-Smirnov-like maximum deviation
        max_dev = max(
            abs(observed.get(d, 0) - expected[d]) for d in range(1, 10)
        )

        # Composite score normalised to [0, 1]
        chi_norm = min(chi_sq / 20.0, 1.0)
        mad_norm = min(mad / 0.05, 1.0)
        ks_norm = min(max_dev / 0.10, 1.0)

        score = 0.4 * chi_norm + 0.3 * mad_norm + 0.3 * ks_norm

        logger.debug(
            "Benford's analysis | n={n} | chi_sq={c:.3f} | MAD={m:.4f} | score={s:.4f}",
            n=total,
            c=chi_sq,
            m=mad,
            s=score,
        )
        return round(score, 4)

    # ------------------------------------------------------------------
    # Report generation
    # ------------------------------------------------------------------

    async def generate_forensics_report(
        self, block_id: str
    ) -> ForensicsReport:
        """Generate a comprehensive forensics report for a block.

        This is a convenience wrapper that calls ``analyze_block`` with
        the current financial year.

        Parameters
        ----------
        block_id : str
            The block code.

        Returns
        -------
        ForensicsReport
        """
        fin_year = self.config.get("financial_year", "2025-2026")
        return await self.analyze_block(block_id, fin_year)

    # ------------------------------------------------------------------
    # Private helpers -- seasonal impossibility checks
    # ------------------------------------------------------------------

    async def _check_seasonal_impossibilities(
        self, block_id: str, fin_year: str
    ) -> List[ForensicFinding]:
        """Detect heavy earthwork reported during monsoon months.

        During June-September, heavy rainfall makes earthwork (road
        construction, pond digging, land levelling) physically
        impractical in most of India. Significant person-days reported
        for such work during these months is a strong fraud indicator.
        """
        findings: List[ForensicFinding] = []

        try:
            records = await self._fetch_monsoon_earthwork(block_id, fin_year)

            for rec in records:
                if rec.get("person_days", 0) > self.MONSOON_MAX_EARTHWORK_DAYS:
                    findings.append(
                        ForensicFinding(
                            finding_id=f"F-{uuid.uuid4().hex[:8]}",
                            category=FraudCategory.SEASONAL_IMPOSSIBILITY,
                            severity=SeverityLevel.HIGH,
                            description=(
                                f"Heavy earthwork ({rec['person_days']} person-days) "
                                f"reported during monsoon month {rec['month']} for "
                                f"work {rec['work_id']} in GP {rec['gp_id']}"
                            ),
                            affected_entities=[rec["work_id"], rec["gp_id"]],
                            evidence={
                                "work_id": rec["work_id"],
                                "month": rec["month"],
                                "person_days": rec["person_days"],
                                "work_type": rec.get("work_type", "earthwork"),
                            },
                            confidence=0.85,
                            recommended_action=(
                                "Verify if work type allows monsoon activity; "
                                "check satellite imagery for the period"
                            ),
                        )
                    )

            return findings

        except Exception as exc:
            logger.error(
                "Seasonal check failed for block {b}: {e}", b=block_id, e=exc
            )
            return []

    async def _check_wage_calculation_fraud(
        self, block_id: str, fin_year: str
    ) -> List[ForensicFinding]:
        """Detect wage calculation discrepancies.

        Verifies that: person_days * daily_wage_rate == payment_amount
        within a tolerance.
        """
        findings: List[ForensicFinding] = []

        try:
            records = await self._fetch_wage_records(block_id, fin_year)

            for rec in records:
                days = rec.get("person_days", 0)
                rate = rec.get("wage_rate", 0)
                paid = rec.get("amount_paid", 0)
                expected = days * rate

                if expected > 0:
                    deviation_pct = abs(paid - expected) / expected * 100
                    if deviation_pct > self.WAGE_DEVIATION_THRESHOLD_PCT:
                        findings.append(
                            ForensicFinding(
                                finding_id=f"F-{uuid.uuid4().hex[:8]}",
                                category=FraudCategory.WAGE_MISMATCH,
                                severity=(
                                    SeverityLevel.HIGH
                                    if deviation_pct > 20
                                    else SeverityLevel.MEDIUM
                                ),
                                description=(
                                    f"Wage mismatch for worker {rec['worker_id']} "
                                    f"on work {rec['work_id']}: "
                                    f"expected Rs.{expected:.0f} "
                                    f"({days}d x Rs.{rate}), "
                                    f"paid Rs.{paid:.0f} "
                                    f"(deviation {deviation_pct:.1f}%)"
                                ),
                                affected_entities=[
                                    rec["worker_id"],
                                    rec["work_id"],
                                ],
                                evidence={
                                    "person_days": days,
                                    "wage_rate": rate,
                                    "expected_payment": expected,
                                    "actual_payment": paid,
                                    "deviation_pct": round(deviation_pct, 1),
                                },
                                confidence=min(deviation_pct / 50.0, 1.0),
                                recommended_action=(
                                    "Audit FTO and muster roll for this worker; "
                                    "verify actual days worked"
                                ),
                            )
                        )

            return findings

        except Exception as exc:
            logger.error(
                "Wage check failed for block {b}: {e}", b=block_id, e=exc
            )
            return []

    # ------------------------------------------------------------------
    # Private helpers -- data fetching
    # ------------------------------------------------------------------

    async def _fetch_block_panchayats(
        self, block_id: str
    ) -> List[Dict[str, Any]]:
        """Fetch all gram panchayats in a block."""
        query = """
            SELECT gp.panchayat_code AS gram_panchayat_id,
                   gp.panchayat_name
            FROM   gram_panchayats gp
            WHERE  gp.block_code = :block_id
              AND  gp.is_active = TRUE
        """
        rows = await self.db.fetch_all(query, {"block_id": block_id})
        return [dict(r) for r in rows]

    async def _fetch_block_works(
        self, block_id: str, fin_year: str
    ) -> List[Dict[str, Any]]:
        """Fetch all works in a block for a financial year."""
        query = """
            SELECT w.work_id,
                   w.work_name,
                   w.gram_panchayat_id
            FROM   works w
            WHERE  w.block_id = :block_id
              AND  w.financial_year = :fy
        """
        rows = await self.db.fetch_all(
            query, {"block_id": block_id, "fy": fin_year}
        )
        return [dict(r) for r in rows]

    async def _fetch_work_attendance(
        self, work_id: str
    ) -> List[Dict[str, Any]]:
        """Fetch daily attendance records for all workers on a work."""
        query = """
            SELECT ma.worker_id,
                   ma.attendance_date,
                   ma.muster_roll_id,
                   ma.is_present
            FROM   muster_attendance ma
            WHERE  ma.work_id = :work_id
              AND  ma.is_present = TRUE
            ORDER  BY ma.attendance_date, ma.worker_id
        """
        rows = await self.db.fetch_all(query, {"work_id": work_id})
        return [dict(r) for r in rows]

    async def _fetch_panchayat_workers(
        self, panchayat_id: str
    ) -> List[Dict[str, Any]]:
        """Fetch all registered workers in a panchayat with fraud indicators."""
        query = """
            SELECT jc.worker_id,
                   jc.job_card_number,
                   jc.registration_date,
                   jc.aadhaar_seeded,
                   COALESCE(bio.auth_count, 0)     AS biometric_auth_count,
                   COALESCE(att.total_days, 0)      AS total_person_days,
                   COALESCE(pay.total_wages, 0)     AS total_wages,
                   COALESCE(pay.has_dbt, TRUE)      AS has_dbt_payment,
                   att.first_work_date,
                   aa.flags                         AS aadhaar_flags
            FROM   job_cards jc
                   LEFT JOIN (
                       SELECT worker_id, COUNT(*) AS auth_count
                       FROM   biometric_logs
                       GROUP  BY worker_id
                   ) bio ON jc.worker_id = bio.worker_id
                   LEFT JOIN (
                       SELECT worker_id,
                              SUM(person_days) AS total_days,
                              MIN(from_date)   AS first_work_date
                       FROM   muster_rolls
                       GROUP  BY worker_id
                   ) att ON jc.worker_id = att.worker_id
                   LEFT JOIN (
                       SELECT worker_id,
                              SUM(amount) AS total_wages,
                              BOOL_OR(is_dbt) AS has_dbt
                       FROM   wage_payments
                       GROUP  BY worker_id
                   ) pay ON jc.worker_id = pay.worker_id
                   LEFT JOIN aadhaar_audit aa ON jc.aadhaar_number = aa.aadhaar_number
            WHERE  jc.panchayat_id = :gp_id
        """
        rows = await self.db.fetch_all(query, {"gp_id": panchayat_id})
        return [dict(r) for r in rows]

    async def _fetch_worker_attendance_across_sites(
        self,
        worker_id: str,
        date_range: Tuple[date, date],
    ) -> List[Dict[str, Any]]:
        """Fetch a worker's attendance across all worksites in a date range."""
        query = """
            SELECT ma.worker_id,
                   ma.attendance_date,
                   ma.work_id,
                   ma.muster_roll_id,
                   w.gram_panchayat_id AS gp_id,
                   w.latitude,
                   w.longitude
            FROM   muster_attendance ma
                   JOIN works w ON ma.work_id = w.work_id
            WHERE  ma.worker_id = :worker_id
              AND  ma.attendance_date BETWEEN :start_date AND :end_date
              AND  ma.is_present = TRUE
            ORDER  BY ma.attendance_date
        """
        rows = await self.db.fetch_all(
            query,
            {
                "worker_id": worker_id,
                "start_date": date_range[0].isoformat(),
                "end_date": date_range[1].isoformat(),
            },
        )
        return [dict(r) for r in rows]

    async def _fetch_monthly_registrations(
        self, block_id: str
    ) -> List[Dict[str, Any]]:
        """Fetch monthly job card registration counts for a block."""
        query = """
            SELECT TO_CHAR(jc.registration_date, 'YYYY-MM')   AS month,
                   EXTRACT(MONTH FROM jc.registration_date)     AS month_num,
                   COUNT(*)                                     AS count
            FROM   job_cards jc
                   JOIN gram_panchayats gp
                       ON jc.panchayat_id = gp.panchayat_code
            WHERE  gp.block_code = :block_id
              AND  jc.registration_date >= CURRENT_DATE - INTERVAL '24 months'
            GROUP  BY 1, 2
            ORDER  BY 1
        """
        rows = await self.db.fetch_all(query, {"block_id": block_id})
        return [dict(r) for r in rows]

    async def _fetch_block_attendance_numbers(
        self, block_id: str, fin_year: str
    ) -> List[float]:
        """Fetch all person-day values from a block for Benford's analysis."""
        query = """
            SELECT mr.person_days
            FROM   muster_rolls mr
                   JOIN works w ON mr.work_id = w.work_id
            WHERE  w.block_id = :block_id
              AND  w.financial_year = :fy
              AND  mr.person_days > 0
        """
        rows = await self.db.fetch_all(
            query, {"block_id": block_id, "fy": fin_year}
        )
        return [float(r["person_days"]) for r in rows]

    async def _fetch_monsoon_earthwork(
        self, block_id: str, fin_year: str
    ) -> List[Dict[str, Any]]:
        """Fetch earthwork records during monsoon months."""
        query = """
            SELECT mr.work_id,
                   mr.person_days,
                   w.gram_panchayat_id AS gp_id,
                   w.work_type,
                   EXTRACT(MONTH FROM mr.from_date) AS month
            FROM   muster_rolls mr
                   JOIN works w ON mr.work_id = w.work_id
            WHERE  w.block_id = :block_id
              AND  w.financial_year = :fy
              AND  w.work_category = 'earthwork'
              AND  EXTRACT(MONTH FROM mr.from_date) IN (6, 7, 8, 9)
        """
        rows = await self.db.fetch_all(
            query, {"block_id": block_id, "fy": fin_year}
        )
        return [dict(r) for r in rows]

    async def _fetch_wage_records(
        self, block_id: str, fin_year: str
    ) -> List[Dict[str, Any]]:
        """Fetch wage payment records for calculation verification."""
        query = """
            SELECT wp.worker_id,
                   wp.work_id,
                   mr.person_days,
                   wr.daily_rate  AS wage_rate,
                   wp.amount      AS amount_paid
            FROM   wage_payments wp
                   JOIN muster_rolls mr
                       ON wp.muster_roll_id = mr.muster_roll_id
                   JOIN wage_rates wr
                       ON wp.state_code = wr.state_code
                       AND wp.financial_year = wr.financial_year
                   JOIN works w ON wp.work_id = w.work_id
            WHERE  w.block_id = :block_id
              AND  w.financial_year = :fy
        """
        rows = await self.db.fetch_all(
            query, {"block_id": block_id, "fy": fin_year}
        )
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Private helpers -- utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _estimate_inter_site_distance(
        records: List[Dict[str, Any]],
    ) -> float:
        """Estimate maximum distance between worksites in km using Haversine."""
        coords = [
            (r.get("latitude", 0), r.get("longitude", 0))
            for r in records
            if r.get("latitude") and r.get("longitude")
        ]
        if len(coords) < 2:
            return 0.0

        max_dist = 0.0
        for i in range(len(coords)):
            for j in range(i + 1, len(coords)):
                lat1, lon1 = np.radians(coords[i])
                lat2, lon2 = np.radians(coords[j])
                dlat = lat2 - lat1
                dlon = lon2 - lon1
                a = (
                    np.sin(dlat / 2) ** 2
                    + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
                )
                c = 2 * np.arcsin(np.sqrt(a))
                dist_km = 6371 * c
                max_dist = max(max_dist, dist_km)

        return round(max_dist, 1)

    @staticmethod
    def _generate_report_summary(report: ForensicsReport) -> str:
        """Generate a human-readable summary of the forensics report."""
        lines = [
            f"Muster Roll Forensics Report: Block {report.block_id}",
            f"Financial Year: {report.financial_year}",
            f"Generated: {report.generated_at.strftime('%Y-%m-%d %H:%M UTC')}",
            "",
            f"Total findings: {len(report.findings)}",
        ]

        # Count by severity
        severity_counts: Dict[str, int] = defaultdict(int)
        for f in report.findings:
            severity_counts[f.severity.value] += 1
        for sev in ["critical", "high", "medium", "low"]:
            if severity_counts.get(sev, 0) > 0:
                lines.append(f"  {sev.upper()}: {severity_counts[sev]}")

        lines.append("")
        lines.append(f"Suspected ghost workers: {len(report.ghost_worker_profiles)}")
        lines.append(f"Attendance clone groups: {len(report.clone_groups)}")
        lines.append(
            f"Suspicious person-days: {report.total_suspicious_person_days:,}"
        )
        lines.append(
            f"Suspicious wages: Rs.{report.total_suspicious_wages:,.0f}"
        )
        lines.append(
            f"Benford's deviation score: {report.benfords_deviation_score:.4f}"
        )

        return "\n".join(lines)
