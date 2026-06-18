"""
Agent Orchestrator for the MGNREGA Verification & Fraud Intelligence System.

Defines the investigation workflow as a state graph (LangGraph-style),
routing anomalies to specialised agents, managing their lifecycle, handling
dependencies (e.g., satellite verification before case file compilation),
and providing an API for triggering investigations and checking status.

The orchestrator supports:
- Single-work investigations (triggered by Sentinel alerts)
- District-wide scans (comprehensive sweep of all panchayats)
- Pilot analyses (initial assessment of a district for system deployment)
- Parallel execution of independent agent tasks
- Dependency-aware sequencing of dependent tasks
"""

from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from loguru import logger

from .case_file_agent import CaseFileAgent
from .muster_roll_forensics import MusterRollForensicsAgent
from .payment_pattern import PaymentPatternAgent
from .photo_verification import PhotoVerificationAgent
from .satellite_verification import SatelliteVerificationAgent
from .sentinel_agent import AnomalyType, SentinelAgent


# ---------------------------------------------------------------------------
# Workflow state
# ---------------------------------------------------------------------------

class WorkflowState(str, Enum):
    """States in the investigation workflow graph."""

    INITIAL = "initial"
    TRIAGE = "triage"
    SATELLITE_VERIFICATION = "satellite_verification"
    MUSTER_ROLL_FORENSICS = "muster_roll_forensics"
    PAYMENT_ANALYSIS = "payment_analysis"
    PHOTO_VERIFICATION = "photo_verification"
    EVIDENCE_COMPILATION = "evidence_compilation"
    REPORT_GENERATION = "report_generation"
    COMPLETED = "completed"
    FAILED = "failed"


class InvestigationPhase(str, Enum):
    """High-level phases of an investigation."""

    QUEUED = "queued"
    DATA_COLLECTION = "data_collection"
    ANALYSIS = "analysis"
    EVIDENCE = "evidence"
    REPORTING = "reporting"
    DONE = "done"
    ERROR = "error"


@dataclass
class WorkflowNode:
    """A node in the workflow state graph."""

    state: WorkflowState
    handler: Optional[str] = None  # method name on orchestrator
    dependencies: List[WorkflowState] = field(default_factory=list)
    is_parallel: bool = False  # can run in parallel with siblings
    timeout_seconds: int = 600  # 10 minutes default


@dataclass
class InvestigationContext:
    """Mutable context passed through the workflow."""

    investigation_id: str
    work_id: Optional[str] = None
    district_id: Optional[str] = None
    block_id: Optional[str] = None
    gram_panchayat_id: Optional[str] = None
    state_code: Optional[str] = None
    financial_year: str = "2025-2026"
    anomaly_types: List[AnomalyType] = field(default_factory=list)

    # Intermediate results from agents
    satellite_result: Optional[Dict[str, Any]] = None
    muster_result: Optional[Dict[str, Any]] = None
    payment_result: Optional[Dict[str, Any]] = None
    photo_result: Optional[Dict[str, Any]] = None
    case_file: Optional[Dict[str, Any]] = None

    # Workflow tracking
    current_state: WorkflowState = WorkflowState.INITIAL
    completed_states: Set[WorkflowState] = field(default_factory=set)
    errors: Dict[str, str] = field(default_factory=dict)
    started_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    phase: InvestigationPhase = InvestigationPhase.QUEUED
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class InvestigationStatus:
    """Public status view of an investigation."""

    investigation_id: str
    phase: InvestigationPhase
    current_state: WorkflowState
    completed_steps: List[str]
    pending_steps: List[str]
    progress_pct: float
    started_at: datetime
    elapsed_seconds: float
    errors: Dict[str, str]
    has_satellite: bool
    has_muster: bool
    has_payment: bool
    has_photo: bool
    has_case_file: bool


# ---------------------------------------------------------------------------
# Agent Orchestrator
# ---------------------------------------------------------------------------

class AgentOrchestrator:
    """Orchestrates the MGNREGA fraud investigation workflow.

    Implements a LangGraph-style state graph where each node represents
    an agent task. The orchestrator manages routing, parallel execution,
    dependency resolution, and lifecycle tracking.

    Parameters
    ----------
    db_session : Any
        Shared database session.
    imagery_client : Any
        Satellite imagery provider client.
    storage_client : Any
        Object storage client.
    bhashini_client : Any, optional
        Bhashini translation API client.
    clip_model : Any, optional
        Pre-loaded CLIP model for photo verification.
    config : dict, optional
        Runtime configuration.
    """

    def __init__(
        self,
        db_session: Any,
        imagery_client: Any,
        storage_client: Any,
        bhashini_client: Optional[Any] = None,
        clip_model: Optional[Any] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.db = db_session
        self.config = config or {}

        # Initialise all agents
        self.sentinel = SentinelAgent(db_session, config)
        self.satellite = SatelliteVerificationAgent(
            db_session, imagery_client, storage_client, config
        )
        self.muster = MusterRollForensicsAgent(db_session, config)
        self.payment = PaymentPatternAgent(db_session, config)
        self.photo = PhotoVerificationAgent(db_session, clip_model, config)
        self.case_file = CaseFileAgent(db_session, bhashini_client, config)

        # Active investigations
        self._investigations: Dict[str, InvestigationContext] = {}

        # Build the workflow graph
        self._workflow = self.create_workflow()

        logger.info("AgentOrchestrator initialised with all agents")

    # ------------------------------------------------------------------
    # Workflow definition
    # ------------------------------------------------------------------

    def create_workflow(self) -> Dict[WorkflowState, WorkflowNode]:
        """Define the investigation workflow as a state graph.

        Graph structure::

            INITIAL
              |
            TRIAGE
              |
            +---------+---------+---------+
            |         |         |         |
            SAT       MR        PAY       PHOTO    (parallel)
            |         |         |         |
            +---------+---------+---------+
              |
            EVIDENCE_COMPILATION
              |
            REPORT_GENERATION
              |
            COMPLETED

        Returns
        -------
        dict
            Mapping of WorkflowState to WorkflowNode definitions.
        """
        workflow: Dict[WorkflowState, WorkflowNode] = {
            WorkflowState.INITIAL: WorkflowNode(
                state=WorkflowState.INITIAL,
                handler="_handle_initial",
            ),
            WorkflowState.TRIAGE: WorkflowNode(
                state=WorkflowState.TRIAGE,
                handler="_handle_triage",
                dependencies=[WorkflowState.INITIAL],
            ),
            WorkflowState.SATELLITE_VERIFICATION: WorkflowNode(
                state=WorkflowState.SATELLITE_VERIFICATION,
                handler="_handle_satellite",
                dependencies=[WorkflowState.TRIAGE],
                is_parallel=True,
                timeout_seconds=900,
            ),
            WorkflowState.MUSTER_ROLL_FORENSICS: WorkflowNode(
                state=WorkflowState.MUSTER_ROLL_FORENSICS,
                handler="_handle_muster_roll",
                dependencies=[WorkflowState.TRIAGE],
                is_parallel=True,
                timeout_seconds=600,
            ),
            WorkflowState.PAYMENT_ANALYSIS: WorkflowNode(
                state=WorkflowState.PAYMENT_ANALYSIS,
                handler="_handle_payment",
                dependencies=[WorkflowState.TRIAGE],
                is_parallel=True,
                timeout_seconds=600,
            ),
            WorkflowState.PHOTO_VERIFICATION: WorkflowNode(
                state=WorkflowState.PHOTO_VERIFICATION,
                handler="_handle_photo",
                dependencies=[WorkflowState.TRIAGE],
                is_parallel=True,
                timeout_seconds=300,
            ),
            WorkflowState.EVIDENCE_COMPILATION: WorkflowNode(
                state=WorkflowState.EVIDENCE_COMPILATION,
                handler="_handle_evidence_compilation",
                dependencies=[
                    WorkflowState.SATELLITE_VERIFICATION,
                    WorkflowState.MUSTER_ROLL_FORENSICS,
                    WorkflowState.PAYMENT_ANALYSIS,
                    WorkflowState.PHOTO_VERIFICATION,
                ],
                timeout_seconds=300,
            ),
            WorkflowState.REPORT_GENERATION: WorkflowNode(
                state=WorkflowState.REPORT_GENERATION,
                handler="_handle_report_generation",
                dependencies=[WorkflowState.EVIDENCE_COMPILATION],
                timeout_seconds=300,
            ),
            WorkflowState.COMPLETED: WorkflowNode(
                state=WorkflowState.COMPLETED,
                handler="_handle_completed",
                dependencies=[WorkflowState.REPORT_GENERATION],
            ),
        }

        logger.debug(
            "Workflow graph created with {n} nodes", n=len(workflow)
        )
        return workflow

    # ------------------------------------------------------------------
    # Investigation entry points
    # ------------------------------------------------------------------

    async def run_investigation(
        self, work_id: str
    ) -> InvestigationContext:
        """Run a full investigation on a single MGNREGA work.

        Executes the complete workflow: triage, parallel agent analysis,
        evidence compilation, and report generation.

        Parameters
        ----------
        work_id : str
            The NREGASoft work identifier.

        Returns
        -------
        InvestigationContext
            Final investigation context with all results.
        """
        inv_id = f"INV-{uuid.uuid4().hex[:12].upper()}"
        logger.info(
            "Starting investigation {id} for work {w}",
            id=inv_id,
            w=work_id,
        )

        # Fetch work metadata to populate context
        work = await self._fetch_work_metadata(work_id)

        ctx = InvestigationContext(
            investigation_id=inv_id,
            work_id=work_id,
            district_id=work.get("district_id", ""),
            block_id=work.get("block_id", ""),
            gram_panchayat_id=work.get("gram_panchayat_id", ""),
            state_code=work.get("state_code", ""),
            financial_year=work.get("financial_year", "2025-2026"),
        )

        self._investigations[inv_id] = ctx

        try:
            await self._execute_workflow(ctx)
            logger.info(
                "Investigation {id} completed | phase={p}",
                id=inv_id,
                p=ctx.phase.value,
            )
        except Exception as exc:
            ctx.phase = InvestigationPhase.ERROR
            ctx.errors["workflow"] = str(exc)
            logger.exception(
                "Investigation {id} failed: {e}", id=inv_id, e=exc
            )

        return ctx

    async def run_district_scan(
        self, district_id: str
    ) -> Dict[str, Any]:
        """Run a comprehensive district-wide scan.

        Triggers the Sentinel to scan all GPs in the district, then
        spawns investigations for high-risk works.

        Parameters
        ----------
        district_id : str
            NREGASoft district code.

        Returns
        -------
        dict
            Scan results with flagged works and spawned investigations.
        """
        scan_id = f"SCAN-{uuid.uuid4().hex[:10].upper()}"
        logger.info(
            "Starting district scan {id} for district {d}",
            id=scan_id,
            d=district_id,
        )

        results: Dict[str, Any] = {
            "scan_id": scan_id,
            "district_id": district_id,
            "started_at": datetime.utcnow().isoformat(),
            "flagged_works": [],
            "investigations_spawned": [],
            "errors": [],
        }

        try:
            # Step 1: Run Sentinel daily scan
            dashboard_stats = await self.sentinel.run_daily_scan()
            results["dashboard_stats"] = {
                "gps_scanned": dashboard_stats.total_gram_panchayats_scanned,
                "works_flagged": dashboard_stats.total_works_flagged,
                "high_risk_districts": dashboard_stats.high_risk_districts,
            }

            # Step 2: Get priority queue of flagged works for this district
            all_flagged = self.sentinel.get_priority_queue(limit=100)
            district_flagged = [
                fw
                for fw in all_flagged
                if fw.district_id == district_id
            ]

            results["flagged_works"] = [
                {
                    "work_id": fw.work_id,
                    "risk_score": fw.risk_score,
                    "anomaly_types": [at.value for at in fw.anomaly_types],
                }
                for fw in district_flagged
            ]

            # Step 3: Spawn investigations for top-N flagged works
            max_investigations = self.config.get("max_parallel_investigations", 10)
            for fw in district_flagged[:max_investigations]:
                try:
                    ctx = await self.run_investigation(fw.work_id)
                    results["investigations_spawned"].append(
                        {
                            "investigation_id": ctx.investigation_id,
                            "work_id": fw.work_id,
                            "phase": ctx.phase.value,
                        }
                    )
                except Exception as exc:
                    results["errors"].append(
                        {
                            "work_id": fw.work_id,
                            "error": str(exc),
                        }
                    )

            # Step 4: Generate district-level reports
            fin_year = self.config.get("financial_year", "2025-2026")
            payment_report = await self.payment.generate_payment_report(
                district_id
            )
            results["payment_report_id"] = payment_report.report_id

            results["completed_at"] = datetime.utcnow().isoformat()

            logger.info(
                "District scan complete | district={d} | flagged={f} | investigations={i}",
                d=district_id,
                f=len(district_flagged),
                i=len(results["investigations_spawned"]),
            )
            return results

        except Exception as exc:
            logger.exception(
                "District scan failed for {d}: {e}", d=district_id, e=exc
            )
            results["errors"].append({"error": str(exc)})
            return results

    def get_investigation_status(
        self, investigation_id: str
    ) -> Optional[InvestigationStatus]:
        """Get the current status of an investigation.

        Parameters
        ----------
        investigation_id : str
            The investigation identifier.

        Returns
        -------
        InvestigationStatus or None
            Current status, or None if investigation not found.
        """
        ctx = self._investigations.get(investigation_id)
        if ctx is None:
            logger.warning(
                "Investigation {id} not found", id=investigation_id
            )
            return None

        # Determine completed and pending steps
        all_states = [s for s in WorkflowState if s != WorkflowState.FAILED]
        completed_steps = [s.value for s in ctx.completed_states]
        pending_steps = [
            s.value
            for s in all_states
            if s not in ctx.completed_states and s != WorkflowState.COMPLETED
        ]

        # Progress percentage
        total_steps = len(all_states) - 1  # exclude FAILED
        done_steps = len(ctx.completed_states)
        progress = (done_steps / max(total_steps, 1)) * 100.0

        elapsed = (datetime.utcnow() - ctx.started_at).total_seconds()

        return InvestigationStatus(
            investigation_id=investigation_id,
            phase=ctx.phase,
            current_state=ctx.current_state,
            completed_steps=completed_steps,
            pending_steps=pending_steps,
            progress_pct=round(progress, 1),
            started_at=ctx.started_at,
            elapsed_seconds=round(elapsed, 1),
            errors=ctx.errors,
            has_satellite=ctx.satellite_result is not None,
            has_muster=ctx.muster_result is not None,
            has_payment=ctx.payment_result is not None,
            has_photo=ctx.photo_result is not None,
            has_case_file=ctx.case_file is not None,
        )

    async def run_pilot_analysis(
        self,
        district_code: str,
        state_code: str,
        fin_year: str,
    ) -> Dict[str, Any]:
        """Run a pilot analysis for initial system deployment assessment.

        Performs a lighter-weight scan to demonstrate the system's
        capabilities and calibrate thresholds for a specific district.

        Parameters
        ----------
        district_code : str
            NREGASoft district code (e.g., ``"3401"``).
        state_code : str
            NREGASoft state code (e.g., ``"34"`` for Rajasthan).
        fin_year : str
            Financial year (e.g., ``"2025-2026"``).

        Returns
        -------
        dict
            Pilot analysis results.
        """
        pilot_id = f"PILOT-{uuid.uuid4().hex[:10].upper()}"
        logger.info(
            "Starting pilot analysis {id} | district={d} | state={s} | fy={fy}",
            id=pilot_id,
            d=district_code,
            s=state_code,
            fy=fin_year,
        )

        results: Dict[str, Any] = {
            "pilot_id": pilot_id,
            "district_code": district_code,
            "state_code": state_code,
            "financial_year": fin_year,
            "started_at": datetime.utcnow().isoformat(),
            "analyses": {},
            "summary": {},
        }

        try:
            # 1. Fetch sample blocks and panchayats
            blocks = await self._fetch_district_blocks(district_code)
            sample_blocks = blocks[:3]  # analyse first 3 blocks

            # 2. Run muster roll forensics on sample blocks
            muster_findings: List[Dict[str, Any]] = []
            for block in sample_blocks:
                block_id = block["block_id"]
                try:
                    report = await self.muster.analyze_block(
                        block_id, fin_year
                    )
                    muster_findings.append(
                        {
                            "block_id": block_id,
                            "findings_count": len(report.findings),
                            "ghost_workers": len(report.ghost_worker_profiles),
                            "clone_groups": len(report.clone_groups),
                            "benfords_score": report.benfords_deviation_score,
                            "suspicious_person_days": report.total_suspicious_person_days,
                        }
                    )
                except Exception as exc:
                    muster_findings.append(
                        {"block_id": block_id, "error": str(exc)}
                    )

            results["analyses"]["muster_roll"] = muster_findings

            # 3. Run payment analysis on the district
            try:
                payment_report = await self.payment.generate_payment_report(
                    district_code
                )
                results["analyses"]["payment"] = {
                    "report_id": payment_report.report_id,
                    "findings_count": len(payment_report.findings),
                    "circular_flows": len(payment_report.circular_flows),
                    "shell_beneficiaries": len(
                        payment_report.shell_beneficiaries
                    ),
                    "vendor_clusters": len(payment_report.vendor_clusters),
                    "suspicious_amount": payment_report.total_suspicious_amount,
                }
            except Exception as exc:
                results["analyses"]["payment"] = {"error": str(exc)}

            # 4. Run satellite verification on a sample of works
            sample_works = await self._fetch_sample_works(
                district_code, fin_year, limit=5
            )
            sat_results: List[Dict[str, Any]] = []
            for work in sample_works:
                try:
                    sat_result = await self.satellite.verify_work(
                        work["work_id"]
                    )
                    sat_results.append(
                        {
                            "work_id": work["work_id"],
                            "status": sat_result.verification_status.value,
                            "confidence": sat_result.confidence_score,
                        }
                    )
                except Exception as exc:
                    sat_results.append(
                        {"work_id": work["work_id"], "error": str(exc)}
                    )

            results["analyses"]["satellite"] = sat_results

            # 5. Photo verification on sample works
            photo_results: List[Dict[str, Any]] = []
            for work in sample_works:
                try:
                    photo_report = await self.photo.verify_work_photos(
                        work["work_id"]
                    )
                    photo_results.append(
                        {
                            "work_id": work["work_id"],
                            "total_photos": photo_report.total_photos,
                            "verified": photo_report.verified_count,
                            "gps_mismatches": photo_report.gps_mismatch_count,
                            "duplicates": photo_report.duplicate_count,
                        }
                    )
                except Exception as exc:
                    photo_results.append(
                        {"work_id": work["work_id"], "error": str(exc)}
                    )

            results["analyses"]["photo"] = photo_results

            # 6. Generate pilot summary
            results["summary"] = self._generate_pilot_summary(results)
            results["completed_at"] = datetime.utcnow().isoformat()

            logger.info(
                "Pilot analysis complete | id={id} | district={d}",
                id=pilot_id,
                d=district_code,
            )
            return results

        except Exception as exc:
            logger.exception(
                "Pilot analysis failed: {e}", e=exc
            )
            results["error"] = str(exc)
            return results

    # ------------------------------------------------------------------
    # Workflow execution engine
    # ------------------------------------------------------------------

    async def _execute_workflow(
        self, ctx: InvestigationContext
    ) -> None:
        """Execute the workflow graph for a given investigation context.

        Resolves node dependencies, identifies parallelisable groups,
        and executes handlers in the correct order.
        """
        ctx.phase = InvestigationPhase.DATA_COLLECTION

        # Execute INITIAL and TRIAGE sequentially
        await self._execute_node(WorkflowState.INITIAL, ctx)
        await self._execute_node(WorkflowState.TRIAGE, ctx)

        ctx.phase = InvestigationPhase.ANALYSIS

        # Execute parallel analysis nodes concurrently
        parallel_nodes = [
            WorkflowState.SATELLITE_VERIFICATION,
            WorkflowState.MUSTER_ROLL_FORENSICS,
            WorkflowState.PAYMENT_ANALYSIS,
            WorkflowState.PHOTO_VERIFICATION,
        ]

        # Filter to only nodes relevant to detected anomaly types
        relevant_nodes = self._filter_relevant_nodes(
            parallel_nodes, ctx.anomaly_types
        )

        parallel_tasks = [
            self._execute_node_safe(node, ctx) for node in relevant_nodes
        ]
        await asyncio.gather(*parallel_tasks)

        ctx.phase = InvestigationPhase.EVIDENCE

        # Evidence compilation (depends on all parallel nodes completing)
        await self._execute_node(WorkflowState.EVIDENCE_COMPILATION, ctx)

        ctx.phase = InvestigationPhase.REPORTING

        # Report generation
        await self._execute_node(WorkflowState.REPORT_GENERATION, ctx)

        # Mark complete
        await self._execute_node(WorkflowState.COMPLETED, ctx)
        ctx.phase = InvestigationPhase.DONE

    async def _execute_node(
        self, state: WorkflowState, ctx: InvestigationContext
    ) -> None:
        """Execute a single workflow node."""
        node = self._workflow.get(state)
        if node is None:
            logger.error("Unknown workflow state: {s}", s=state)
            return

        ctx.current_state = state
        handler_name = node.handler
        if handler_name is None:
            ctx.completed_states.add(state)
            return

        handler = getattr(self, handler_name, None)
        if handler is None:
            logger.error(
                "Handler {h} not found on orchestrator", h=handler_name
            )
            return

        logger.debug(
            "Executing workflow node {s} for investigation {id}",
            s=state.value,
            id=ctx.investigation_id,
        )

        try:
            await asyncio.wait_for(
                handler(ctx), timeout=node.timeout_seconds
            )
            ctx.completed_states.add(state)
        except asyncio.TimeoutError:
            ctx.errors[state.value] = (
                f"Timed out after {node.timeout_seconds}s"
            )
            logger.error(
                "Node {s} timed out for investigation {id}",
                s=state.value,
                id=ctx.investigation_id,
            )
        except Exception as exc:
            ctx.errors[state.value] = str(exc)
            logger.error(
                "Node {s} failed for investigation {id}: {e}",
                s=state.value,
                id=ctx.investigation_id,
                e=exc,
            )

    async def _execute_node_safe(
        self, state: WorkflowState, ctx: InvestigationContext
    ) -> None:
        """Execute a node and catch all exceptions without propagating."""
        try:
            await self._execute_node(state, ctx)
        except Exception as exc:
            ctx.errors[state.value] = str(exc)
            logger.error(
                "Safe execution of {s} failed: {e}", s=state.value, e=exc
            )

    # ------------------------------------------------------------------
    # Node handlers
    # ------------------------------------------------------------------

    async def _handle_initial(
        self, ctx: InvestigationContext
    ) -> None:
        """Initial state: validate context and fetch prerequisites."""
        logger.debug(
            "Initialising investigation {id}", id=ctx.investigation_id
        )
        if not ctx.work_id and not ctx.district_id:
            raise ValueError("Investigation requires either work_id or district_id")

    async def _handle_triage(
        self, ctx: InvestigationContext
    ) -> None:
        """Triage state: determine which anomaly types are present.

        If anomaly types are not pre-set, runs Sentinel risk scoring
        on the GP to determine the relevant detection modules.
        """
        logger.debug(
            "Triaging investigation {id}", id=ctx.investigation_id
        )

        if not ctx.anomaly_types and ctx.gram_panchayat_id:
            score = await self.sentinel.calculate_risk_score(
                ctx.gram_panchayat_id
            )
            ctx.anomaly_types = [AnomalyType(f) for f in score.anomaly_flags]
            ctx.metadata["risk_score"] = score.composite_score
            ctx.metadata["score_breakdown"] = {
                "expenditure": score.expenditure_score,
                "attendance": score.attendance_score,
                "satellite": score.satellite_score,
                "photo": score.photo_score,
                "payment": score.payment_score,
            }

        if not ctx.anomaly_types:
            # Default: run all agents
            ctx.anomaly_types = list(AnomalyType)

        logger.debug(
            "Triage complete | anomaly_types={t}", t=ctx.anomaly_types
        )

    async def _handle_satellite(
        self, ctx: InvestigationContext
    ) -> None:
        """Run satellite verification."""
        if not ctx.work_id:
            logger.debug("Skipping satellite: no work_id")
            return

        result = await self.satellite.verify_work(ctx.work_id)
        ctx.satellite_result = {
            "work_id": result.work_id,
            "status": result.verification_status.value,
            "confidence": result.confidence_score,
            "ndvi_change": result.ndvi_change,
            "measurements": [
                {
                    "dimension": m.dimension,
                    "estimated": m.estimated_value,
                    "reported": m.reported_value,
                    "deviation_pct": m.deviation_pct,
                }
                for m in result.measurements
            ],
        }

    async def _handle_muster_roll(
        self, ctx: InvestigationContext
    ) -> None:
        """Run muster roll forensics."""
        if not ctx.block_id:
            logger.debug("Skipping muster roll: no block_id")
            return

        report = await self.muster.analyze_block(
            ctx.block_id, ctx.financial_year
        )
        ctx.muster_result = {
            "report_id": report.report_id,
            "findings_count": len(report.findings),
            "ghost_workers": len(report.ghost_worker_profiles),
            "clone_groups": len(report.clone_groups),
            "suspicious_person_days": report.total_suspicious_person_days,
            "suspicious_wages": report.total_suspicious_wages,
            "benfords_score": report.benfords_deviation_score,
        }

    async def _handle_payment(
        self, ctx: InvestigationContext
    ) -> None:
        """Run payment pattern analysis."""
        if not ctx.district_id:
            logger.debug("Skipping payment: no district_id")
            return

        report = await self.payment.generate_payment_report(
            ctx.district_id
        )
        ctx.payment_result = {
            "report_id": report.report_id,
            "findings_count": len(report.findings),
            "circular_flows": len(report.circular_flows),
            "shell_beneficiaries": len(report.shell_beneficiaries),
            "vendor_clusters": len(report.vendor_clusters),
            "suspicious_amount": report.total_suspicious_amount,
        }

    async def _handle_photo(
        self, ctx: InvestigationContext
    ) -> None:
        """Run photo verification."""
        if not ctx.work_id:
            logger.debug("Skipping photo: no work_id")
            return

        report = await self.photo.verify_work_photos(ctx.work_id)
        ctx.photo_result = {
            "report_id": report.report_id,
            "total_photos": report.total_photos,
            "verified": report.verified_count,
            "gps_mismatches": report.gps_mismatch_count,
            "duplicates": report.duplicate_count,
            "type_mismatches": report.type_mismatch_count,
            "manipulation_count": report.manipulation_count,
            "overall_confidence": report.overall_confidence,
        }

    async def _handle_evidence_compilation(
        self, ctx: InvestigationContext
    ) -> None:
        """Compile all agent results into a case file."""
        # Collect anomaly IDs from metadata
        anomaly_ids = ctx.metadata.get("anomaly_ids", [])
        if not anomaly_ids:
            anomaly_ids = [
                f"ANM-{ctx.investigation_id}-{at.value}"
                for at in ctx.anomaly_types
            ]

        case = await self.case_file.compile_case_file(anomaly_ids)
        ctx.case_file = {
            "case_id": case.case_id,
            "title": case.title,
            "status": case.status.value,
            "evidence_chains": len(case.evidence_chains),
            "estimated_loss": case.estimated_loss_inr,
            "affected_beneficiaries": case.affected_beneficiaries,
            "recommended_actions": case.recommended_actions,
        }

    async def _handle_report_generation(
        self, ctx: InvestigationContext
    ) -> None:
        """Generate final reports."""
        if ctx.district_id:
            now = datetime.utcnow()
            date_range = (
                (now - timedelta(days=30)).strftime("%Y-%m-%d"),
                now.strftime("%Y-%m-%d"),
            )
            briefing = await self.case_file.generate_district_briefing(
                ctx.district_id, date_range
            )
            ctx.metadata["briefing_id"] = briefing.briefing_id

        if ctx.case_file and ctx.case_file.get("case_id"):
            observation = await self.case_file.export_cag_format(
                ctx.case_file["case_id"]
            )
            ctx.metadata["cag_observation_id"] = observation.observation_id

    async def _handle_completed(
        self, ctx: InvestigationContext
    ) -> None:
        """Mark investigation as complete."""
        ctx.completed_at = datetime.utcnow()
        elapsed = (ctx.completed_at - ctx.started_at).total_seconds()
        logger.info(
            "Investigation {id} completed in {t:.1f}s | errors={e}",
            id=ctx.investigation_id,
            t=elapsed,
            e=len(ctx.errors),
        )

    # ------------------------------------------------------------------
    # Routing helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _filter_relevant_nodes(
        nodes: List[WorkflowState],
        anomaly_types: List[AnomalyType],
    ) -> List[WorkflowState]:
        """Filter workflow nodes to only those relevant to detected anomalies.

        Ensures we don't waste resources running agents whose domain
        is unrelated to the detected anomaly types.
        """
        if not anomaly_types:
            return nodes  # run all if unspecified

        anomaly_set = set(anomaly_types)
        relevant: List[WorkflowState] = []

        # Satellite is relevant for spatial anomalies
        satellite_triggers = {
            AnomalyType.SATELLITE,
            AnomalyType.EXPENDITURE,
        }
        if anomaly_set & satellite_triggers:
            relevant.append(WorkflowState.SATELLITE_VERIFICATION)

        # Muster roll is relevant for attendance and worker anomalies
        muster_triggers = {
            AnomalyType.ATTENDANCE,
            AnomalyType.GHOST_WORKER,
            AnomalyType.MUSTER_ROLL,
        }
        if anomaly_set & muster_triggers:
            relevant.append(WorkflowState.MUSTER_ROLL_FORENSICS)

        # Payment is relevant for financial anomalies
        payment_triggers = {
            AnomalyType.PAYMENT,
            AnomalyType.MATERIAL_RATIO,
            AnomalyType.EXPENDITURE,
        }
        if anomaly_set & payment_triggers:
            relevant.append(WorkflowState.PAYMENT_ANALYSIS)

        # Photo is relevant for photo anomalies
        if AnomalyType.PHOTO in anomaly_set:
            relevant.append(WorkflowState.PHOTO_VERIFICATION)

        # If nothing matched, run all
        if not relevant:
            return nodes

        return relevant

    # ------------------------------------------------------------------
    # Data access helpers
    # ------------------------------------------------------------------

    async def _fetch_work_metadata(
        self, work_id: str
    ) -> Dict[str, Any]:
        """Fetch work metadata for populating investigation context."""
        try:
            query = """
                SELECT w.work_id,
                       w.district_id,
                       w.block_id,
                       w.gram_panchayat_id,
                       w.state_code,
                       w.financial_year,
                       w.work_type,
                       w.work_name
                FROM   works w
                WHERE  w.work_id = :work_id
            """
            row = await self.db.fetch_one(query, {"work_id": work_id})
            return dict(row) if row else {}
        except Exception as exc:
            logger.error(
                "Failed to fetch work metadata for {w}: {e}",
                w=work_id,
                e=exc,
            )
            return {}

    async def _fetch_district_blocks(
        self, district_code: str
    ) -> List[Dict[str, Any]]:
        """Fetch all blocks in a district."""
        try:
            query = """
                SELECT b.block_code AS block_id, b.block_name
                FROM   blocks b
                WHERE  b.district_code = :district_id
                ORDER  BY b.block_name
            """
            rows = await self.db.fetch_all(
                query, {"district_id": district_code}
            )
            return [dict(r) for r in rows]
        except Exception as exc:
            logger.error(
                "Failed to fetch blocks for district {d}: {e}",
                d=district_code,
                e=exc,
            )
            return []

    async def _fetch_sample_works(
        self, district_code: str, fin_year: str, limit: int = 5
    ) -> List[Dict[str, Any]]:
        """Fetch a sample of works for pilot analysis."""
        try:
            query = """
                SELECT w.work_id,
                       w.work_name,
                       w.work_type,
                       w.total_expenditure
                FROM   works w
                WHERE  w.district_id = :district_id
                  AND  w.financial_year = :fy
                  AND  w.total_expenditure > 100000
                ORDER  BY w.total_expenditure DESC
                LIMIT  :limit
            """
            rows = await self.db.fetch_all(
                query,
                {
                    "district_id": district_code,
                    "fy": fin_year,
                    "limit": limit,
                },
            )
            return [dict(r) for r in rows]
        except Exception as exc:
            logger.error(
                "Failed to fetch sample works for {d}: {e}",
                d=district_code,
                e=exc,
            )
            return []

    # ------------------------------------------------------------------
    # Pilot summary
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_pilot_summary(results: Dict[str, Any]) -> Dict[str, Any]:
        """Generate a summary of the pilot analysis."""
        analyses = results.get("analyses", {})

        # Muster summary
        muster_data = analyses.get("muster_roll", [])
        total_findings = sum(
            b.get("findings_count", 0) for b in muster_data if "error" not in b
        )
        total_ghosts = sum(
            b.get("ghost_workers", 0) for b in muster_data if "error" not in b
        )

        # Payment summary
        payment = analyses.get("payment", {})
        payment_findings = payment.get("findings_count", 0) if "error" not in payment else 0
        suspicious_amount = payment.get("suspicious_amount", 0) if "error" not in payment else 0

        # Satellite summary
        sat_data = analyses.get("satellite", [])
        verified = sum(
            1
            for s in sat_data
            if s.get("status") == "verified" and "error" not in s
        )
        mismatches = sum(
            1
            for s in sat_data
            if s.get("status") == "mismatch" and "error" not in s
        )

        return {
            "district_code": results["district_code"],
            "blocks_analysed": len(muster_data),
            "muster_roll_findings": total_findings,
            "ghost_workers_detected": total_ghosts,
            "payment_findings": payment_findings,
            "suspicious_amount_inr": suspicious_amount,
            "satellite_verified": verified,
            "satellite_mismatches": mismatches,
            "satellite_works_checked": len(sat_data),
            "recommendation": (
                "HIGH RISK"
                if (total_ghosts > 10 or suspicious_amount > 1000000 or mismatches > 2)
                else "MODERATE RISK"
                if (total_findings > 5 or suspicious_amount > 500000)
                else "LOW RISK"
            ),
        }
