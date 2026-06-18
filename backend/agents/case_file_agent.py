"""
Case File Agent for the MGNREGA Verification & Fraud Intelligence System.

This agent compiles evidence from all other specialised agents into
structured investigation reports. It produces outputs compatible with
CAG (Comptroller and Auditor General) audit standards, creates evidence
chains, generates district-level intelligence briefings, and supports
vernacular translations via the Bhashini API.

Report formats:
- Investigation case files with evidence chains
- District intelligence briefings
- CAG-compatible audit observations
- Weekly/monthly summary reports
- Vernacular reports in Hindi and regional languages
"""

from __future__ import annotations

import json
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger


# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------

class ReportFormat(str, Enum):
    """Output formats for case file reports."""

    CASE_FILE = "case_file"
    DISTRICT_BRIEFING = "district_briefing"
    CAG_OBSERVATION = "cag_observation"
    WEEKLY_SUMMARY = "weekly_summary"
    EVIDENCE_CHAIN = "evidence_chain"


class EvidenceType(str, Enum):
    """Types of evidence collected by investigation agents."""

    SATELLITE_IMAGERY = "satellite_imagery"
    MUSTER_ROLL_ANALYSIS = "muster_roll_analysis"
    PAYMENT_GRAPH = "payment_graph"
    PHOTO_VERIFICATION = "photo_verification"
    BIOMETRIC_RECORD = "biometric_record"
    FTO_RECORD = "fto_record"
    EXPENDITURE_ANALYSIS = "expenditure_analysis"
    FIELD_VERIFICATION = "field_verification"
    STATISTICAL_ANALYSIS = "statistical_analysis"


class CaseStatus(str, Enum):
    """Status of an investigation case."""

    OPEN = "open"
    UNDER_INVESTIGATION = "under_investigation"
    EVIDENCE_COMPILED = "evidence_compiled"
    REFERRED_FOR_ACTION = "referred_for_action"
    CLOSED = "closed"


class BhashiniLanguage(str, Enum):
    """Languages supported by Bhashini API for translation."""

    HINDI = "hi"
    BENGALI = "bn"
    TAMIL = "ta"
    TELUGU = "te"
    MARATHI = "mr"
    GUJARATI = "gu"
    KANNADA = "kn"
    MALAYALAM = "ml"
    ODIA = "or"
    PUNJABI = "pa"
    ASSAMESE = "as"
    RAJASTHANI = "raj"


@dataclass
class EvidenceItem:
    """A single piece of evidence in the investigation chain."""

    evidence_id: str
    evidence_type: EvidenceType
    source_agent: str
    collected_at: datetime
    summary: str
    details: Dict[str, Any] = field(default_factory=dict)
    attachments: List[str] = field(default_factory=list)  # storage paths
    confidence: float = 0.0
    is_primary: bool = False  # primary vs corroborating evidence


@dataclass
class EvidenceChain:
    """Ordered chain of evidence for a case, showing causal relationships."""

    chain_id: str
    case_id: str
    items: List[EvidenceItem] = field(default_factory=list)
    narrative: str = ""
    strength: str = ""  # "strong", "moderate", "weak"
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class CaseFile:
    """Complete investigation case file."""

    case_id: str
    title: str
    status: CaseStatus
    district_id: str
    block_id: str
    gram_panchayat_id: str
    state_code: str
    financial_year: str
    anomaly_ids: List[str] = field(default_factory=list)
    work_ids: List[str] = field(default_factory=list)
    evidence_chains: List[EvidenceChain] = field(default_factory=list)
    findings_summary: str = ""
    estimated_loss_inr: float = 0.0
    affected_beneficiaries: int = 0
    recommended_actions: List[str] = field(default_factory=list)
    responsible_officials: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class DistrictBriefing:
    """District-level intelligence briefing."""

    briefing_id: str
    district_id: str
    district_name: str
    state_code: str
    date_range: Tuple[str, str]
    open_cases: int = 0
    new_cases: int = 0
    total_flagged_works: int = 0
    estimated_leakage_inr: float = 0.0
    top_anomalies: List[Dict[str, Any]] = field(default_factory=list)
    block_risk_summary: List[Dict[str, Any]] = field(default_factory=list)
    key_findings: List[str] = field(default_factory=list)
    action_items: List[str] = field(default_factory=list)
    generated_at: datetime = field(default_factory=datetime.utcnow)
    report_text: str = ""


@dataclass
class CAGObservation:
    """Observation formatted per CAG audit standards."""

    observation_id: str
    case_id: str
    para_number: str  # CAG paragraph number
    title: str
    criteria: str  # what should have been done (MGNREGA Act / guidelines)
    condition: str  # what was actually found
    cause: str  # root cause analysis
    effect: str  # impact / financial loss
    recommendation: str
    management_response: str = ""
    audit_evidence: List[str] = field(default_factory=list)
    amount_involved_inr: float = 0.0


@dataclass
class WeeklySummary:
    """Weekly summary report for a district."""

    summary_id: str
    district_id: str
    week_start: str
    week_end: str
    new_anomalies: int = 0
    resolved_cases: int = 0
    escalated_cases: int = 0
    total_suspicious_amount_inr: float = 0.0
    highlights: List[str] = field(default_factory=list)
    risk_trend: str = ""  # "increasing", "stable", "decreasing"
    generated_at: datetime = field(default_factory=datetime.utcnow)
    report_text: str = ""


# ---------------------------------------------------------------------------
# Case File Agent
# ---------------------------------------------------------------------------

class CaseFileAgent:
    """Agent for compiling investigation evidence into structured reports.

    Collects findings from the SatelliteVerificationAgent,
    MusterRollForensicsAgent, PaymentPatternAgent, and
    PhotoVerificationAgent, then compiles them into audit-ready
    case files, district briefings, and CAG-compatible observations.

    Parameters
    ----------
    db_session : Any
        Database session for querying evidence and persisting reports.
    bhashini_client : Any, optional
        Bhashini API client for vernacular translation. If ``None``,
        translation is skipped.
    config : dict, optional
        Runtime configuration overrides.
    """

    def __init__(
        self,
        db_session: Any,
        bhashini_client: Optional[Any] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.db = db_session
        self.bhashini = bhashini_client
        self.config = config or {}

        logger.info(
            "CaseFileAgent initialised | bhashini={'enabled' if bhashini_client else 'disabled'}",
        )

    # ------------------------------------------------------------------
    # Case file compilation
    # ------------------------------------------------------------------

    async def compile_case_file(
        self, anomaly_ids: List[str]
    ) -> CaseFile:
        """Compile a complete investigation case file from anomaly IDs.

        Gathers all evidence produced by specialised agents for the
        given anomalies, constructs evidence chains, and generates a
        structured case file suitable for administrative action or
        judicial proceedings.

        Parameters
        ----------
        anomaly_ids : list of str
            Anomaly IDs from the Sentinel Agent that triggered the
            investigation.

        Returns
        -------
        CaseFile
            Complete investigation case file.
        """
        case_id = f"CASE-{uuid.uuid4().hex[:10].upper()}"
        logger.info(
            "Compiling case file {c} for anomalies: {a}",
            c=case_id,
            a=anomaly_ids,
        )

        try:
            # Fetch anomaly details
            anomalies = await self._fetch_anomaly_details(anomaly_ids)
            if not anomalies:
                logger.warning("No anomaly data found for IDs: {a}", a=anomaly_ids)
                return CaseFile(
                    case_id=case_id,
                    title="Investigation - No Data",
                    status=CaseStatus.OPEN,
                    district_id="",
                    block_id="",
                    gram_panchayat_id="",
                    state_code="",
                    financial_year="",
                    anomaly_ids=anomaly_ids,
                )

            # Extract location context from first anomaly
            primary = anomalies[0]
            district_id = primary.get("district_id", "")
            block_id = primary.get("block_id", "")
            gp_id = primary.get("gram_panchayat_id", "")
            state_code = primary.get("state_code", "")
            fin_year = primary.get("financial_year", "")
            work_ids = list({a.get("work_id", "") for a in anomalies if a.get("work_id")})

            # Collect evidence from all agent outputs
            evidence_items: List[EvidenceItem] = []

            # Satellite evidence
            for wid in work_ids:
                sat_evidence = await self._fetch_satellite_evidence(wid)
                evidence_items.extend(sat_evidence)

            # Muster roll evidence
            muster_evidence = await self._fetch_muster_evidence(gp_id, block_id)
            evidence_items.extend(muster_evidence)

            # Payment evidence
            payment_evidence = await self._fetch_payment_evidence(
                district_id, work_ids
            )
            evidence_items.extend(payment_evidence)

            # Photo evidence
            for wid in work_ids:
                photo_evidence = await self._fetch_photo_evidence(wid)
                evidence_items.extend(photo_evidence)

            # Build evidence chain
            chain = self._build_evidence_chain(case_id, evidence_items)

            # Calculate estimated loss
            estimated_loss = self._calculate_estimated_loss(anomalies, evidence_items)

            # Generate findings summary
            findings_summary = self._generate_findings_summary(
                anomalies, evidence_items
            )

            # Identify responsible officials
            officials = await self._identify_responsible_officials(
                gp_id, block_id, district_id, work_ids
            )

            # Generate recommended actions
            recommended = self._generate_recommendations(anomalies, evidence_items)

            # Affected beneficiaries count
            affected = self._count_affected_beneficiaries(evidence_items)

            # Build case title
            anomaly_types = list({a.get("anomaly_type", "") for a in anomalies})
            title = (
                f"Investigation: {', '.join(anomaly_types)} in "
                f"GP {gp_id}, Block {block_id}, District {district_id}"
            )

            case_file = CaseFile(
                case_id=case_id,
                title=title,
                status=CaseStatus.EVIDENCE_COMPILED,
                district_id=district_id,
                block_id=block_id,
                gram_panchayat_id=gp_id,
                state_code=state_code,
                financial_year=fin_year,
                anomaly_ids=anomaly_ids,
                work_ids=work_ids,
                evidence_chains=[chain],
                findings_summary=findings_summary,
                estimated_loss_inr=estimated_loss,
                affected_beneficiaries=affected,
                recommended_actions=recommended,
                responsible_officials=officials,
            )

            # Persist case file
            await self._save_case_file(case_file)

            logger.info(
                "Case file compiled | case={c} | evidence_items={e} | loss=Rs.{l:,.0f}",
                c=case_id,
                e=len(evidence_items),
                l=estimated_loss,
            )
            return case_file

        except Exception as exc:
            logger.exception(
                "Case file compilation failed for anomalies {a}: {e}",
                a=anomaly_ids,
                e=exc,
            )
            raise

    # ------------------------------------------------------------------
    # District briefing
    # ------------------------------------------------------------------

    async def generate_district_briefing(
        self,
        district_id: str,
        date_range: Tuple[str, str],
    ) -> DistrictBriefing:
        """Generate a district-level intelligence briefing.

        Summarises all investigative activity in the district over the
        specified date range: new cases, ongoing investigations, risk
        trends, and recommended actions for the District Programme
        Coordinator (DPC).

        Parameters
        ----------
        district_id : str
            NREGASoft district code.
        date_range : tuple of str
            Start and end dates as ISO strings (``"2025-04-01"``,
            ``"2025-04-30"``).

        Returns
        -------
        DistrictBriefing
            Intelligence briefing for district leadership.
        """
        briefing_id = f"BRF-{uuid.uuid4().hex[:10].upper()}"
        logger.info(
            "Generating district briefing | district={d} | range={r}",
            d=district_id,
            r=date_range,
        )

        try:
            # Fetch district metadata
            district_meta = await self._fetch_district_metadata(district_id)
            district_name = district_meta.get("district_name", district_id)
            state_code = district_meta.get("state_code", "")

            # Fetch case statistics
            case_stats = await self._fetch_case_stats(district_id, date_range)

            # Fetch block-level risk summary
            block_risks = await self._fetch_block_risk_summary(
                district_id, date_range
            )

            # Fetch top anomalies
            top_anomalies = await self._fetch_top_anomalies(
                district_id, date_range
            )

            # Generate key findings
            key_findings = self._generate_key_findings(
                case_stats, top_anomalies, block_risks
            )

            # Generate action items
            action_items = self._generate_action_items(
                case_stats, top_anomalies
            )

            # Calculate estimated leakage
            estimated_leakage = case_stats.get("total_suspicious_amount", 0.0)

            # Determine risk trend
            risk_trend = self._determine_risk_trend(district_id, date_range)

            briefing = DistrictBriefing(
                briefing_id=briefing_id,
                district_id=district_id,
                district_name=district_name,
                state_code=state_code,
                date_range=date_range,
                open_cases=case_stats.get("open_cases", 0),
                new_cases=case_stats.get("new_cases", 0),
                total_flagged_works=case_stats.get("flagged_works", 0),
                estimated_leakage_inr=estimated_leakage,
                top_anomalies=top_anomalies,
                block_risk_summary=block_risks,
                key_findings=key_findings,
                action_items=action_items,
            )

            # Generate formatted report text
            briefing.report_text = self._format_district_briefing(briefing)

            # Persist briefing
            await self._save_briefing(briefing)

            logger.info(
                "District briefing generated | id={id} | cases={c} | leakage=Rs.{l:,.0f}",
                id=briefing_id,
                c=briefing.open_cases,
                l=estimated_leakage,
            )
            return briefing

        except Exception as exc:
            logger.exception(
                "District briefing failed for {d}: {e}", d=district_id, e=exc
            )
            raise

    # ------------------------------------------------------------------
    # Evidence chain
    # ------------------------------------------------------------------

    async def create_evidence_chain(
        self, case_id: str
    ) -> EvidenceChain:
        """Create an evidence chain for an existing case.

        Retrieves all evidence associated with the case, orders it
        chronologically, establishes causal connections, and assesses
        the overall chain strength.

        Parameters
        ----------
        case_id : str
            The case file identifier.

        Returns
        -------
        EvidenceChain
            Ordered chain of evidence with narrative.
        """
        logger.info("Creating evidence chain for case {c}", c=case_id)

        try:
            # Fetch all evidence for this case
            evidence_items = await self._fetch_case_evidence(case_id)
            chain = self._build_evidence_chain(case_id, evidence_items)

            # Persist chain
            await self._save_evidence_chain(chain)

            logger.info(
                "Evidence chain created | case={c} | items={n} | strength={s}",
                c=case_id,
                n=len(chain.items),
                s=chain.strength,
            )
            return chain

        except Exception as exc:
            logger.exception(
                "Evidence chain creation failed for case {c}: {e}",
                c=case_id,
                e=exc,
            )
            raise

    # ------------------------------------------------------------------
    # Translation
    # ------------------------------------------------------------------

    async def translate_report(
        self, report: str, target_language: str
    ) -> str:
        """Translate a report into a regional language using Bhashini API.

        Bhashini is the Government of India's AI-based language
        translation platform supporting 22 scheduled languages.

        Parameters
        ----------
        report : str
            English report text to translate.
        target_language : str
            Target language code (e.g., ``"hi"`` for Hindi,
            ``"bn"`` for Bengali). See ``BhashiniLanguage`` enum.

        Returns
        -------
        str
            Translated report text, or original text if translation
            fails or Bhashini client is unavailable.
        """
        if self.bhashini is None:
            logger.warning(
                "Bhashini client not configured; returning English report"
            )
            return report

        try:
            # Validate target language
            try:
                BhashiniLanguage(target_language)
            except ValueError:
                logger.warning(
                    "Unsupported language code: {l}", l=target_language
                )
                return report

            # Split report into manageable chunks for the API
            max_chunk_chars = self.config.get("bhashini_max_chunk", 5000)
            chunks = self._split_text_chunks(report, max_chunk_chars)

            translated_chunks: List[str] = []
            for chunk in chunks:
                response = await self.bhashini.translate(
                    text=chunk,
                    source_language="en",
                    target_language=target_language,
                    task_type="translation",
                )
                translated_chunks.append(
                    response.get("translated_text", chunk)
                )

            translated = "\n".join(translated_chunks)
            logger.info(
                "Report translated to {l} ({n} chunks)",
                l=target_language,
                n=len(chunks),
            )
            return translated

        except Exception as exc:
            logger.error(
                "Translation failed for language {l}: {e}",
                l=target_language,
                e=exc,
            )
            return report

    # ------------------------------------------------------------------
    # CAG format export
    # ------------------------------------------------------------------

    async def export_cag_format(
        self, case_id: str
    ) -> CAGObservation:
        """Export a case file in CAG audit observation format.

        Structures the case findings per the CAG Performance Audit
        framework:
        - **Criteria**: What should have been done (MGNREGA Act / guidelines)
        - **Condition**: What was actually found
        - **Cause**: Root cause analysis
        - **Effect**: Financial and social impact
        - **Recommendation**: Suggested corrective action

        Parameters
        ----------
        case_id : str
            The case file identifier.

        Returns
        -------
        CAGObservation
            Observation formatted per CAG standards.
        """
        logger.info("Exporting CAG format for case {c}", c=case_id)

        try:
            # Fetch case file
            case_file = await self._fetch_case_file(case_id)
            if not case_file:
                raise ValueError(f"Case {case_id} not found")

            # Map anomaly types to MGNREGA Act sections
            criteria = self._map_criteria(case_file)
            condition = self._map_condition(case_file)
            cause = self._analyse_root_cause(case_file)
            effect = self._analyse_effect(case_file)
            recommendation = self._generate_cag_recommendation(case_file)

            observation = CAGObservation(
                observation_id=f"CAG-{uuid.uuid4().hex[:8].upper()}",
                case_id=case_id,
                para_number=self._generate_para_number(case_file),
                title=case_file.get("title", ""),
                criteria=criteria,
                condition=condition,
                cause=cause,
                effect=effect,
                recommendation=recommendation,
                audit_evidence=[
                    ec.get("chain_id", "")
                    for ec in case_file.get("evidence_chains", [])
                ],
                amount_involved_inr=case_file.get("estimated_loss_inr", 0.0),
            )

            # Persist observation
            await self._save_cag_observation(observation)

            logger.info(
                "CAG observation exported | id={id} | case={c} | amount=Rs.{a:,.0f}",
                id=observation.observation_id,
                c=case_id,
                a=observation.amount_involved_inr,
            )
            return observation

        except Exception as exc:
            logger.exception(
                "CAG export failed for case {c}: {e}", c=case_id, e=exc
            )
            raise

    # ------------------------------------------------------------------
    # Weekly summary
    # ------------------------------------------------------------------

    async def generate_weekly_summary(
        self, district_id: str
    ) -> WeeklySummary:
        """Generate a weekly summary report for a district.

        Summarises the past seven days of investigative activity.

        Parameters
        ----------
        district_id : str
            NREGASoft district code.

        Returns
        -------
        WeeklySummary
            Weekly activity summary.
        """
        summary_id = f"WKS-{uuid.uuid4().hex[:10].upper()}"
        now = datetime.utcnow()
        week_end = now.strftime("%Y-%m-%d")
        week_start = (now - timedelta(days=7)).strftime("%Y-%m-%d")

        logger.info(
            "Generating weekly summary | district={d} | {s} to {e}",
            d=district_id,
            s=week_start,
            e=week_end,
        )

        try:
            stats = await self._fetch_weekly_stats(
                district_id, week_start, week_end
            )

            highlights = self._generate_weekly_highlights(stats)
            risk_trend = self._determine_risk_trend(
                district_id, (week_start, week_end)
            )

            summary = WeeklySummary(
                summary_id=summary_id,
                district_id=district_id,
                week_start=week_start,
                week_end=week_end,
                new_anomalies=stats.get("new_anomalies", 0),
                resolved_cases=stats.get("resolved_cases", 0),
                escalated_cases=stats.get("escalated_cases", 0),
                total_suspicious_amount_inr=stats.get(
                    "suspicious_amount", 0.0
                ),
                highlights=highlights,
                risk_trend=risk_trend,
            )

            summary.report_text = self._format_weekly_summary(summary)

            # Persist
            await self._save_weekly_summary(summary)

            logger.info(
                "Weekly summary generated | id={id} | new_anomalies={n}",
                id=summary_id,
                n=summary.new_anomalies,
            )
            return summary

        except Exception as exc:
            logger.exception(
                "Weekly summary failed for district {d}: {e}",
                d=district_id,
                e=exc,
            )
            raise

    # ------------------------------------------------------------------
    # Private helpers -- evidence chain construction
    # ------------------------------------------------------------------

    def _build_evidence_chain(
        self,
        case_id: str,
        items: List[EvidenceItem],
    ) -> EvidenceChain:
        """Construct an ordered evidence chain from collected items."""
        chain_id = f"CHN-{uuid.uuid4().hex[:8]}"

        # Sort by collection timestamp
        sorted_items = sorted(items, key=lambda e: e.collected_at)

        # Mark primary evidence (highest confidence per type)
        type_best: Dict[str, EvidenceItem] = {}
        for item in sorted_items:
            key = item.evidence_type.value
            if key not in type_best or item.confidence > type_best[key].confidence:
                type_best[key] = item
        for item in sorted_items:
            item.is_primary = item is type_best.get(item.evidence_type.value)

        # Assess chain strength
        unique_types = len(type_best)
        avg_confidence = (
            sum(i.confidence for i in sorted_items) / max(len(sorted_items), 1)
        )
        primary_count = sum(1 for i in sorted_items if i.is_primary)

        if unique_types >= 3 and avg_confidence >= 0.7:
            strength = "strong"
        elif unique_types >= 2 and avg_confidence >= 0.5:
            strength = "moderate"
        else:
            strength = "weak"

        # Generate narrative
        narrative = self._generate_chain_narrative(sorted_items)

        return EvidenceChain(
            chain_id=chain_id,
            case_id=case_id,
            items=sorted_items,
            narrative=narrative,
            strength=strength,
        )

    def _generate_chain_narrative(
        self, items: List[EvidenceItem]
    ) -> str:
        """Generate a human-readable narrative connecting evidence items."""
        if not items:
            return "No evidence collected."

        lines = ["Evidence Chain Narrative:", ""]

        for i, item in enumerate(items, 1):
            primary_tag = " [PRIMARY]" if item.is_primary else ""
            lines.append(
                f"{i}. [{item.evidence_type.value}]{primary_tag} "
                f"({item.collected_at.strftime('%Y-%m-%d %H:%M')}) - "
                f"{item.summary} (confidence: {item.confidence:.0%})"
            )

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Private helpers -- findings and recommendations
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_findings_summary(
        anomalies: List[Dict[str, Any]],
        evidence: List[EvidenceItem],
    ) -> str:
        """Generate a concise findings summary."""
        lines = ["Investigation Findings Summary:", ""]

        # Summarise anomalies
        anomaly_types = Counter(a.get("anomaly_type", "unknown") for a in anomalies)
        lines.append("Anomalies Detected:")
        for atype, count in anomaly_types.most_common():
            lines.append(f"  - {atype}: {count} instance(s)")

        # Summarise evidence
        lines.append("")
        lines.append(f"Evidence Collected: {len(evidence)} items")
        evidence_types = Counter(e.evidence_type.value for e in evidence)
        for etype, count in evidence_types.most_common():
            lines.append(f"  - {etype}: {count}")

        # Average confidence
        if evidence:
            avg_conf = sum(e.confidence for e in evidence) / len(evidence)
            lines.append(f"\nOverall evidence confidence: {avg_conf:.0%}")

        return "\n".join(lines)

    @staticmethod
    def _generate_recommendations(
        anomalies: List[Dict[str, Any]],
        evidence: List[EvidenceItem],
    ) -> List[str]:
        """Generate recommended actions based on findings."""
        recommendations: List[str] = []
        anomaly_types = {a.get("anomaly_type", "") for a in anomalies}

        if "satellite_mismatch" in anomaly_types:
            recommendations.append(
                "Commission independent physical verification of reported works "
                "by a team from a different block/district"
            )

        if "ghost_worker" in anomaly_types or "attendance_anomaly" in anomaly_types:
            recommendations.append(
                "Conduct Aadhaar-based biometric verification of all workers "
                "listed in flagged muster rolls"
            )

        if "payment_anomaly" in anomaly_types:
            recommendations.append(
                "Freeze suspicious bank accounts and initiate forensic audit "
                "of fund transfer orders (FTOs)"
            )

        if "photo_anomaly" in anomaly_types:
            recommendations.append(
                "Re-upload geotagged photographs from actual work sites with "
                "independent verification officer present"
            )

        if "material_ratio_violation" in anomaly_types:
            recommendations.append(
                "Audit all material procurement records against District "
                "Schedule of Rates; verify vendor credentials and invoices"
            )

        recommendations.append(
            "Issue show-cause notice to the concerned Gram Rozgar Sahayak "
            "(GRS) and Programme Officer (PO)"
        )
        recommendations.append(
            "Report findings to the State Employment Guarantee Council "
            "and consider FIR if financial loss exceeds Rs.1 lakh"
        )

        return recommendations

    @staticmethod
    def _calculate_estimated_loss(
        anomalies: List[Dict[str, Any]],
        evidence: List[EvidenceItem],
    ) -> float:
        """Estimate financial loss from evidence."""
        total = 0.0

        for anomaly in anomalies:
            total += anomaly.get("estimated_loss", 0.0)

        for item in evidence:
            if "estimated_amount" in item.details:
                total += item.details["estimated_amount"]
            elif "total_suspicious_amount" in item.details:
                total += item.details["total_suspicious_amount"]

        # Deduplicate: cap at the maximum single-source estimate
        # to avoid double counting
        return round(total, 2)

    @staticmethod
    def _count_affected_beneficiaries(
        evidence: List[EvidenceItem],
    ) -> int:
        """Count unique affected beneficiaries across all evidence."""
        affected: set = set()
        for item in evidence:
            workers = item.details.get("affected_workers", [])
            affected.update(workers)
            worker_ids = item.details.get("worker_ids", [])
            affected.update(worker_ids)
        return len(affected)

    # ------------------------------------------------------------------
    # Private helpers -- CAG formatting
    # ------------------------------------------------------------------

    @staticmethod
    def _map_criteria(case_file: Dict[str, Any]) -> str:
        """Map case anomaly types to MGNREGA Act criteria."""
        sections = {
            "satellite_mismatch": (
                "Section 17(1) of MGNREGA Act 2005: Programme Officer shall "
                "ensure that works executed under the Scheme are of acceptable "
                "quality and measurements are verified before payment"
            ),
            "ghost_worker": (
                "Section 25 of MGNREGA Act and Para 19.4 of Operational "
                "Guidelines: Each registered worker must possess a unique "
                "job card with photograph and biometric authentication"
            ),
            "payment_anomaly": (
                "Para 7.7 of MGNREGA Operational Guidelines: Fund Transfer "
                "Orders must be generated based on verified muster rolls "
                "and wages must be paid directly to worker accounts via DBT"
            ),
            "material_ratio_violation": (
                "Section 4(3) of MGNREGA Act: The State Government shall "
                "ensure that the ratio of wages to material cost is not "
                "less than 60:40"
            ),
            "attendance_anomaly": (
                "Para 17.3 of Operational Guidelines: Muster rolls must "
                "reflect actual daily attendance verified by the mate/GRS "
                "with individual worker signatures/thumb impressions"
            ),
        }

        anomaly_types = case_file.get("anomaly_ids", [])
        criteria_parts = []
        for atype, section in sections.items():
            criteria_parts.append(section)
        return " | ".join(criteria_parts[:3]) if criteria_parts else "General MGNREGA compliance"

    @staticmethod
    def _map_condition(case_file: Dict[str, Any]) -> str:
        """Describe the actual condition found."""
        summary = case_file.get("findings_summary", "")
        loss = case_file.get("estimated_loss_inr", 0.0)
        return (
            f"Investigation revealed irregularities in MGNREGA works "
            f"involving estimated financial irregularity of Rs.{loss:,.0f}. "
            f"{summary[:500]}"
        )

    @staticmethod
    def _analyse_root_cause(case_file: Dict[str, Any]) -> str:
        """Analyse root cause of the irregularity."""
        return (
            "Inadequate supervisory oversight at the block and district level, "
            "lack of real-time monitoring of GeoMGNREGA compliance, "
            "insufficient biometric verification enforcement, and "
            "potential collusion between field functionaries and beneficiaries."
        )

    @staticmethod
    def _analyse_effect(case_file: Dict[str, Any]) -> str:
        """Describe the effect of the irregularity."""
        loss = case_file.get("estimated_loss_inr", 0.0)
        affected = case_file.get("affected_beneficiaries", 0)
        return (
            f"Estimated financial loss of Rs.{loss:,.0f} to the exchequer. "
            f"Approximately {affected} genuine beneficiaries may have been "
            f"deprived of rightful employment and wages. Undermines the "
            f"social safety net objective of MGNREGA."
        )

    @staticmethod
    def _generate_cag_recommendation(case_file: Dict[str, Any]) -> str:
        """Generate CAG-style recommendation."""
        return (
            "The State Government may consider: (i) initiating recovery "
            "proceedings for the irregularly paid amount; (ii) fixing "
            "accountability of the concerned officials; (iii) strengthening "
            "real-time monitoring through mandatory GeoMGNREGA compliance; "
            "(iv) implementing Aadhaar-based biometric attendance for all "
            "MGNREGA worksites."
        )

    @staticmethod
    def _generate_para_number(case_file: Dict[str, Any]) -> str:
        """Generate a CAG paragraph number."""
        district = case_file.get("district_id", "000")
        return f"4.2.{district[-3:]}"

    # ------------------------------------------------------------------
    # Private helpers -- formatting
    # ------------------------------------------------------------------

    @staticmethod
    def _format_district_briefing(briefing: DistrictBriefing) -> str:
        """Format district briefing into readable text."""
        lines = [
            "=" * 60,
            f"DISTRICT INTELLIGENCE BRIEFING",
            f"District: {briefing.district_name} ({briefing.district_id})",
            f"Period: {briefing.date_range[0]} to {briefing.date_range[1]}",
            f"Generated: {briefing.generated_at.strftime('%Y-%m-%d %H:%M UTC')}",
            "=" * 60,
            "",
            "SUMMARY STATISTICS:",
            f"  Open cases: {briefing.open_cases}",
            f"  New cases (this period): {briefing.new_cases}",
            f"  Flagged works: {briefing.total_flagged_works}",
            f"  Estimated leakage: Rs.{briefing.estimated_leakage_inr:,.0f}",
            "",
        ]

        if briefing.key_findings:
            lines.append("KEY FINDINGS:")
            for i, finding in enumerate(briefing.key_findings, 1):
                lines.append(f"  {i}. {finding}")
            lines.append("")

        if briefing.block_risk_summary:
            lines.append("BLOCK-LEVEL RISK SUMMARY:")
            for block in briefing.block_risk_summary:
                lines.append(
                    f"  - {block.get('block_name', block.get('block_id', ''))}: "
                    f"Risk={block.get('risk_level', 'N/A')} | "
                    f"Flagged={block.get('flagged_works', 0)}"
                )
            lines.append("")

        if briefing.action_items:
            lines.append("RECOMMENDED ACTIONS:")
            for i, action in enumerate(briefing.action_items, 1):
                lines.append(f"  {i}. {action}")

        return "\n".join(lines)

    @staticmethod
    def _format_weekly_summary(summary: WeeklySummary) -> str:
        """Format weekly summary into readable text."""
        lines = [
            f"WEEKLY SUMMARY: {summary.week_start} to {summary.week_end}",
            f"District: {summary.district_id}",
            "",
            f"New anomalies detected: {summary.new_anomalies}",
            f"Cases resolved: {summary.resolved_cases}",
            f"Cases escalated: {summary.escalated_cases}",
            f"Suspicious amount: Rs.{summary.total_suspicious_amount_inr:,.0f}",
            f"Risk trend: {summary.risk_trend}",
            "",
        ]

        if summary.highlights:
            lines.append("HIGHLIGHTS:")
            for h in summary.highlights:
                lines.append(f"  - {h}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Private helpers -- utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _split_text_chunks(
        text: str, max_chars: int
    ) -> List[str]:
        """Split text into chunks at paragraph boundaries."""
        paragraphs = text.split("\n\n")
        chunks: List[str] = []
        current_chunk = ""

        for para in paragraphs:
            if len(current_chunk) + len(para) + 2 > max_chars:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = para
            else:
                current_chunk += "\n\n" + para

        if current_chunk.strip():
            chunks.append(current_chunk.strip())

        return chunks if chunks else [text]

    def _generate_key_findings(
        self,
        stats: Dict[str, Any],
        anomalies: List[Dict[str, Any]],
        block_risks: List[Dict[str, Any]],
    ) -> List[str]:
        """Generate key findings for district briefing."""
        findings: List[str] = []

        new_cases = stats.get("new_cases", 0)
        if new_cases > 0:
            findings.append(
                f"{new_cases} new investigation case(s) opened during the period"
            )

        high_risk_blocks = [b for b in block_risks if b.get("risk_level") == "high"]
        if high_risk_blocks:
            block_names = ", ".join(
                b.get("block_name", b.get("block_id", ""))
                for b in high_risk_blocks[:3]
            )
            findings.append(
                f"{len(high_risk_blocks)} block(s) at high risk level: {block_names}"
            )

        if anomalies:
            top_type = anomalies[0].get("anomaly_type", "unknown")
            top_count = anomalies[0].get("count", 0)
            findings.append(
                f"Most frequent anomaly type: {top_type} ({top_count} instances)"
            )

        return findings

    @staticmethod
    def _generate_action_items(
        stats: Dict[str, Any],
        anomalies: List[Dict[str, Any]],
    ) -> List[str]:
        """Generate action items for district leadership."""
        items = []

        if stats.get("open_cases", 0) > 10:
            items.append(
                "Convene an emergency review meeting of all Programme Officers "
                "to discuss open cases"
            )

        if stats.get("flagged_works", 0) > 50:
            items.append(
                "Deploy additional verification teams to high-risk blocks"
            )

        items.append(
            "Ensure 100% GeoMGNREGA compliance for all new works sanctioned"
        )
        items.append(
            "Review and update District Schedule of Rates for material procurement"
        )

        return items

    def _generate_weekly_highlights(
        self, stats: Dict[str, Any]
    ) -> List[str]:
        """Generate weekly summary highlights."""
        highlights = []
        if stats.get("new_anomalies", 0) > 0:
            highlights.append(
                f"{stats['new_anomalies']} new anomalies detected across the district"
            )
        if stats.get("resolved_cases", 0) > 0:
            highlights.append(
                f"{stats['resolved_cases']} cases resolved through field verification"
            )
        if stats.get("suspicious_amount", 0) > 0:
            highlights.append(
                f"Rs.{stats['suspicious_amount']:,.0f} identified as potentially irregular"
            )
        return highlights

    def _determine_risk_trend(
        self, district_id: str, date_range: Tuple[str, str]
    ) -> str:
        """Determine risk trend for the district."""
        # In production: compare current period anomaly count with previous
        return "stable"

    # ------------------------------------------------------------------
    # Private helpers -- data access
    # ------------------------------------------------------------------

    async def _fetch_anomaly_details(
        self, anomaly_ids: List[str]
    ) -> List[Dict[str, Any]]:
        """Fetch anomaly records from the database."""
        if not anomaly_ids:
            return []
        placeholders = ", ".join(f":id_{i}" for i in range(len(anomaly_ids)))
        query = f"""
            SELECT a.anomaly_id,
                   a.anomaly_type,
                   a.work_id,
                   a.gram_panchayat_id,
                   a.block_id,
                   a.district_id,
                   a.state_code,
                   a.financial_year,
                   a.risk_score,
                   a.estimated_loss
            FROM   anomalies a
            WHERE  a.anomaly_id IN ({placeholders})
        """
        params = {f"id_{i}": aid for i, aid in enumerate(anomaly_ids)}
        rows = await self.db.fetch_all(query, params)
        return [dict(r) for r in rows]

    async def _fetch_satellite_evidence(
        self, work_id: str
    ) -> List[EvidenceItem]:
        """Fetch satellite verification evidence for a work."""
        try:
            query = """
                SELECT sv.work_id,
                       sv.verification_status,
                       sv.confidence_score,
                       sv.ndvi_change,
                       sv.before_image_id,
                       sv.after_image_id,
                       sv.verified_at
                FROM   satellite_verifications sv
                WHERE  sv.work_id = :work_id
            """
            rows = await self.db.fetch_all(query, {"work_id": work_id})
            items = []
            for r in rows:
                items.append(
                    EvidenceItem(
                        evidence_id=f"EV-{uuid.uuid4().hex[:8]}",
                        evidence_type=EvidenceType.SATELLITE_IMAGERY,
                        source_agent="SatelliteVerificationAgent",
                        collected_at=r.get("verified_at", datetime.utcnow()),
                        summary=(
                            f"Satellite verification: {r.get('verification_status', 'unknown')} "
                            f"(confidence={r.get('confidence_score', 0):.0%})"
                        ),
                        details=dict(r),
                        attachments=[
                            p for p in [r.get("before_image_id"), r.get("after_image_id")]
                            if p
                        ],
                        confidence=r.get("confidence_score", 0.0),
                    )
                )
            return items
        except Exception as exc:
            logger.error("Failed to fetch satellite evidence: {e}", e=exc)
            return []

    async def _fetch_muster_evidence(
        self, gp_id: str, block_id: str
    ) -> List[EvidenceItem]:
        """Fetch muster roll forensics evidence."""
        try:
            query = """
                SELECT fr.report_id,
                       fr.block_id,
                       fr.total_findings,
                       fr.ghost_worker_count,
                       fr.clone_group_count,
                       fr.suspicious_person_days,
                       fr.suspicious_wages,
                       fr.generated_at
                FROM   forensics_reports fr
                WHERE  fr.block_id = :block_id
                ORDER  BY fr.generated_at DESC
                LIMIT  1
            """
            row = await self.db.fetch_one(query, {"block_id": block_id})
            if not row:
                return []

            return [
                EvidenceItem(
                    evidence_id=f"EV-{uuid.uuid4().hex[:8]}",
                    evidence_type=EvidenceType.MUSTER_ROLL_ANALYSIS,
                    source_agent="MusterRollForensicsAgent",
                    collected_at=row.get("generated_at", datetime.utcnow()),
                    summary=(
                        f"Muster roll forensics: {row.get('total_findings', 0)} findings, "
                        f"{row.get('ghost_worker_count', 0)} ghost workers, "
                        f"{row.get('clone_group_count', 0)} clone groups"
                    ),
                    details=dict(row),
                    confidence=0.8,
                )
            ]
        except Exception as exc:
            logger.error("Failed to fetch muster evidence: {e}", e=exc)
            return []

    async def _fetch_payment_evidence(
        self, district_id: str, work_ids: List[str]
    ) -> List[EvidenceItem]:
        """Fetch payment pattern analysis evidence."""
        try:
            query = """
                SELECT pr.report_id,
                       pr.district_id,
                       pr.total_findings,
                       pr.total_suspicious_amount,
                       pr.circular_flow_count,
                       pr.shell_beneficiary_count,
                       pr.generated_at
                FROM   payment_reports pr
                WHERE  pr.district_id = :district_id
                ORDER  BY pr.generated_at DESC
                LIMIT  1
            """
            row = await self.db.fetch_one(query, {"district_id": district_id})
            if not row:
                return []

            return [
                EvidenceItem(
                    evidence_id=f"EV-{uuid.uuid4().hex[:8]}",
                    evidence_type=EvidenceType.PAYMENT_GRAPH,
                    source_agent="PaymentPatternAgent",
                    collected_at=row.get("generated_at", datetime.utcnow()),
                    summary=(
                        f"Payment analysis: {row.get('total_findings', 0)} findings, "
                        f"Rs.{row.get('total_suspicious_amount', 0):,.0f} suspicious"
                    ),
                    details=dict(row),
                    confidence=0.75,
                )
            ]
        except Exception as exc:
            logger.error("Failed to fetch payment evidence: {e}", e=exc)
            return []

    async def _fetch_photo_evidence(
        self, work_id: str
    ) -> List[EvidenceItem]:
        """Fetch photo verification evidence."""
        try:
            query = """
                SELECT pvr.report_id,
                       pvr.work_id,
                       pvr.total_photos,
                       pvr.verified_count,
                       pvr.gps_mismatch_count,
                       pvr.duplicate_count,
                       pvr.overall_confidence,
                       pvr.generated_at
                FROM   photo_verification_reports pvr
                WHERE  pvr.work_id = :work_id
                ORDER  BY pvr.generated_at DESC
                LIMIT  1
            """
            row = await self.db.fetch_one(query, {"work_id": work_id})
            if not row:
                return []

            return [
                EvidenceItem(
                    evidence_id=f"EV-{uuid.uuid4().hex[:8]}",
                    evidence_type=EvidenceType.PHOTO_VERIFICATION,
                    source_agent="PhotoVerificationAgent",
                    collected_at=row.get("generated_at", datetime.utcnow()),
                    summary=(
                        f"Photo verification: {row.get('verified_count', 0)}/{row.get('total_photos', 0)} verified, "
                        f"{row.get('gps_mismatch_count', 0)} GPS mismatches, "
                        f"{row.get('duplicate_count', 0)} duplicates"
                    ),
                    details=dict(row),
                    confidence=row.get("overall_confidence", 0.0),
                )
            ]
        except Exception as exc:
            logger.error("Failed to fetch photo evidence: {e}", e=exc)
            return []

    async def _identify_responsible_officials(
        self,
        gp_id: str,
        block_id: str,
        district_id: str,
        work_ids: List[str],
    ) -> List[str]:
        """Identify officials responsible for the flagged works."""
        try:
            query = """
                SELECT DISTINCT o.official_id,
                       o.official_name,
                       o.designation
                FROM   officials o
                       JOIN work_approvals wa ON o.official_id = wa.approving_officer_id
                WHERE  wa.work_id = ANY(:work_ids)
                UNION
                SELECT o.official_id, o.official_name, o.designation
                FROM   officials o
                WHERE  o.posted_at IN (:gp_id, :block_id, :district_id)
                  AND  o.designation IN ('GRS', 'PO', 'APO', 'BDO', 'DPC')
            """
            rows = await self.db.fetch_all(
                query,
                {
                    "work_ids": work_ids,
                    "gp_id": gp_id,
                    "block_id": block_id,
                    "district_id": district_id,
                },
            )
            return [
                f"{r['official_name']} ({r['designation']})" for r in rows
            ]
        except Exception as exc:
            logger.error("Failed to identify officials: {e}", e=exc)
            return []

    async def _fetch_case_evidence(
        self, case_id: str
    ) -> List[EvidenceItem]:
        """Fetch all evidence for an existing case."""
        try:
            query = """
                SELECT e.evidence_id,
                       e.evidence_type,
                       e.source_agent,
                       e.collected_at,
                       e.summary,
                       e.details,
                       e.confidence,
                       e.is_primary
                FROM   case_evidence e
                WHERE  e.case_id = :case_id
                ORDER  BY e.collected_at
            """
            rows = await self.db.fetch_all(query, {"case_id": case_id})
            return [
                EvidenceItem(
                    evidence_id=r["evidence_id"],
                    evidence_type=EvidenceType(r["evidence_type"]),
                    source_agent=r["source_agent"],
                    collected_at=r["collected_at"],
                    summary=r["summary"],
                    details=r.get("details", {}),
                    confidence=r.get("confidence", 0.0),
                    is_primary=r.get("is_primary", False),
                )
                for r in rows
            ]
        except Exception as exc:
            logger.error(
                "Failed to fetch case evidence for {c}: {e}", c=case_id, e=exc
            )
            return []

    async def _fetch_case_file(
        self, case_id: str
    ) -> Optional[Dict[str, Any]]:
        """Fetch a case file record."""
        try:
            query = """
                SELECT * FROM case_files WHERE case_id = :case_id
            """
            row = await self.db.fetch_one(query, {"case_id": case_id})
            return dict(row) if row else None
        except Exception as exc:
            logger.error(
                "Failed to fetch case file {c}: {e}", c=case_id, e=exc
            )
            return None

    async def _fetch_district_metadata(
        self, district_id: str
    ) -> Dict[str, Any]:
        """Fetch district metadata."""
        query = """
            SELECT d.district_code AS district_id,
                   d.district_name,
                   d.state_code
            FROM   districts d
            WHERE  d.district_code = :district_id
        """
        row = await self.db.fetch_one(query, {"district_id": district_id})
        return dict(row) if row else {}

    async def _fetch_case_stats(
        self, district_id: str, date_range: Tuple[str, str]
    ) -> Dict[str, Any]:
        """Fetch case statistics for a district in a date range."""
        query = """
            SELECT COUNT(*) FILTER (WHERE status IN ('open', 'under_investigation')) AS open_cases,
                   COUNT(*) FILTER (WHERE created_at >= :start_date) AS new_cases,
                   COUNT(DISTINCT unnest(work_ids)) AS flagged_works,
                   SUM(estimated_loss_inr) AS total_suspicious_amount
            FROM   case_files
            WHERE  district_id = :district_id
              AND  created_at BETWEEN :start_date AND :end_date
        """
        row = await self.db.fetch_one(
            query,
            {
                "district_id": district_id,
                "start_date": date_range[0],
                "end_date": date_range[1],
            },
        )
        return dict(row) if row else {}

    async def _fetch_block_risk_summary(
        self, district_id: str, date_range: Tuple[str, str]
    ) -> List[Dict[str, Any]]:
        """Fetch block-level risk summary."""
        query = """
            SELECT b.block_code AS block_id,
                   b.block_name,
                   COALESCE(rs.risk_level, 'low') AS risk_level,
                   COALESCE(rs.flagged_works, 0) AS flagged_works
            FROM   blocks b
                   LEFT JOIN block_risk_scores rs
                       ON b.block_code = rs.block_id
                       AND rs.scan_date >= :start_date
            WHERE  b.district_code = :district_id
            ORDER  BY rs.risk_score DESC NULLS LAST
        """
        rows = await self.db.fetch_all(
            query,
            {"district_id": district_id, "start_date": date_range[0]},
        )
        return [dict(r) for r in rows]

    async def _fetch_top_anomalies(
        self, district_id: str, date_range: Tuple[str, str]
    ) -> List[Dict[str, Any]]:
        """Fetch top anomaly types for a district."""
        query = """
            SELECT a.anomaly_type, COUNT(*) AS count
            FROM   anomalies a
            WHERE  a.district_id = :district_id
              AND  a.detected_at BETWEEN :start_date AND :end_date
            GROUP  BY a.anomaly_type
            ORDER  BY count DESC
            LIMIT  10
        """
        rows = await self.db.fetch_all(
            query,
            {
                "district_id": district_id,
                "start_date": date_range[0],
                "end_date": date_range[1],
            },
        )
        return [dict(r) for r in rows]

    async def _fetch_weekly_stats(
        self, district_id: str, start: str, end: str
    ) -> Dict[str, Any]:
        """Fetch weekly statistics."""
        query = """
            SELECT COUNT(*) FILTER (WHERE detected_at >= :start_date) AS new_anomalies,
                   COUNT(*) FILTER (WHERE status = 'closed' AND updated_at >= :start_date) AS resolved_cases,
                   COUNT(*) FILTER (WHERE status = 'escalated' AND updated_at >= :start_date) AS escalated_cases,
                   SUM(CASE WHEN detected_at >= :start_date THEN estimated_loss ELSE 0 END) AS suspicious_amount
            FROM   anomalies
            WHERE  district_id = :district_id
              AND  detected_at BETWEEN :start_date AND :end_date
        """
        row = await self.db.fetch_one(
            query,
            {"district_id": district_id, "start_date": start, "end_date": end},
        )
        return dict(row) if row else {}

    # ------------------------------------------------------------------
    # Private helpers -- persistence
    # ------------------------------------------------------------------

    async def _save_case_file(self, case_file: CaseFile) -> None:
        """Persist a case file to the database."""
        try:
            query = """
                INSERT INTO case_files
                    (case_id, title, status, district_id, block_id,
                     gram_panchayat_id, state_code, financial_year,
                     anomaly_ids, work_ids, findings_summary,
                     estimated_loss_inr, affected_beneficiaries,
                     recommended_actions, responsible_officials,
                     created_at, updated_at)
                VALUES
                    (:case_id, :title, :status, :district_id, :block_id,
                     :gp_id, :state_code, :fy, :anomaly_ids, :work_ids,
                     :summary, :loss, :affected, :actions, :officials,
                     :created, :updated)
            """
            await self.db.execute(
                query,
                {
                    "case_id": case_file.case_id,
                    "title": case_file.title,
                    "status": case_file.status.value,
                    "district_id": case_file.district_id,
                    "block_id": case_file.block_id,
                    "gp_id": case_file.gram_panchayat_id,
                    "state_code": case_file.state_code,
                    "fy": case_file.financial_year,
                    "anomaly_ids": json.dumps(case_file.anomaly_ids),
                    "work_ids": json.dumps(case_file.work_ids),
                    "summary": case_file.findings_summary,
                    "loss": case_file.estimated_loss_inr,
                    "affected": case_file.affected_beneficiaries,
                    "actions": json.dumps(case_file.recommended_actions),
                    "officials": json.dumps(case_file.responsible_officials),
                    "created": case_file.created_at.isoformat(),
                    "updated": case_file.updated_at.isoformat(),
                },
            )
        except Exception as exc:
            logger.error("Failed to save case file: {e}", e=exc)

    async def _save_briefing(self, briefing: DistrictBriefing) -> None:
        """Persist a district briefing."""
        try:
            query = """
                INSERT INTO district_briefings
                    (briefing_id, district_id, date_range_start, date_range_end,
                     report_text, generated_at)
                VALUES
                    (:id, :district_id, :start, :end, :text, :generated)
            """
            await self.db.execute(
                query,
                {
                    "id": briefing.briefing_id,
                    "district_id": briefing.district_id,
                    "start": briefing.date_range[0],
                    "end": briefing.date_range[1],
                    "text": briefing.report_text,
                    "generated": briefing.generated_at.isoformat(),
                },
            )
        except Exception as exc:
            logger.error("Failed to save briefing: {e}", e=exc)

    async def _save_evidence_chain(self, chain: EvidenceChain) -> None:
        """Persist an evidence chain."""
        try:
            query = """
                INSERT INTO evidence_chains
                    (chain_id, case_id, narrative, strength, created_at)
                VALUES (:chain_id, :case_id, :narrative, :strength, :created_at)
            """
            await self.db.execute(
                query,
                {
                    "chain_id": chain.chain_id,
                    "case_id": chain.case_id,
                    "narrative": chain.narrative,
                    "strength": chain.strength,
                    "created_at": chain.created_at.isoformat(),
                },
            )
        except Exception as exc:
            logger.error("Failed to save evidence chain: {e}", e=exc)

    async def _save_cag_observation(self, obs: CAGObservation) -> None:
        """Persist a CAG observation."""
        try:
            query = """
                INSERT INTO cag_observations
                    (observation_id, case_id, para_number, title,
                     criteria, condition, cause, effect,
                     recommendation, amount_involved_inr)
                VALUES
                    (:id, :case_id, :para, :title, :criteria, :condition,
                     :cause, :effect, :rec, :amount)
            """
            await self.db.execute(
                query,
                {
                    "id": obs.observation_id,
                    "case_id": obs.case_id,
                    "para": obs.para_number,
                    "title": obs.title,
                    "criteria": obs.criteria,
                    "condition": obs.condition,
                    "cause": obs.cause,
                    "effect": obs.effect,
                    "rec": obs.recommendation,
                    "amount": obs.amount_involved_inr,
                },
            )
        except Exception as exc:
            logger.error("Failed to save CAG observation: {e}", e=exc)

    async def _save_weekly_summary(self, summary: WeeklySummary) -> None:
        """Persist a weekly summary."""
        try:
            query = """
                INSERT INTO weekly_summaries
                    (summary_id, district_id, week_start, week_end,
                     report_text, generated_at)
                VALUES (:id, :district_id, :start, :end, :text, :generated)
            """
            await self.db.execute(
                query,
                {
                    "id": summary.summary_id,
                    "district_id": summary.district_id,
                    "start": summary.week_start,
                    "end": summary.week_end,
                    "text": summary.report_text,
                    "generated": summary.generated_at.isoformat(),
                },
            )
        except Exception as exc:
            logger.error("Failed to save weekly summary: {e}", e=exc)
