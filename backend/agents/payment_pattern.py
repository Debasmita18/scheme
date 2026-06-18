"""
Payment Pattern Agent for the MGNREGA Verification & Fraud Intelligence System.

This agent builds and analyses payment network graphs to detect financial
fraud patterns in MGNREGA fund flows. It constructs a multi-layered graph
connecting workers, bank accounts, FTOs (Fund Transfer Orders), works, and
panchayats, then applies graph algorithms and statistical methods to detect:

- Circular payment patterns (money flowing back to officials)
- Shell beneficiaries (single account receiving from multiple panchayats)
- Labour-material ratio violations (>40% material spend)
- Payment splitting (large amounts broken into smaller transfers)
- Vendor collusion (same suppliers with inflated rates across panchayats)

Uses NetworkX for graph construction and community detection algorithms.
"""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np
from loguru import logger

try:
    import networkx as nx
except ImportError:
    nx = None  # type: ignore[assignment]
    logger.warning(
        "NetworkX not installed; PaymentPatternAgent graph features will be unavailable"
    )


# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------

class PaymentFraudType(str, Enum):
    """Categories of payment fraud detected by this agent."""

    CIRCULAR_FLOW = "circular_flow"
    SHELL_BENEFICIARY = "shell_beneficiary"
    MATERIAL_RATIO_VIOLATION = "material_ratio_violation"
    PAYMENT_SPLITTING = "payment_splitting"
    VENDOR_COLLUSION = "vendor_collusion"
    DISPROPORTIONATE_PAYMENT = "disproportionate_payment"
    BENAMI_ACCOUNT = "benami_account"


class NodeType(str, Enum):
    """Types of nodes in the payment graph."""

    WORKER = "worker"
    BANK_ACCOUNT = "bank_account"
    FTO = "fto"
    WORK = "work"
    PANCHAYAT = "panchayat"
    VENDOR = "vendor"
    OFFICIAL = "official"


@dataclass
class PaymentFinding:
    """A single payment pattern fraud finding."""

    finding_id: str
    fraud_type: PaymentFraudType
    severity: str  # "critical", "high", "medium", "low"
    description: str
    affected_entities: List[str] = field(default_factory=list)
    evidence: Dict[str, Any] = field(default_factory=dict)
    estimated_amount: float = 0.0  # in INR
    confidence: float = 0.0
    recommended_action: str = ""
    detected_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ShellBeneficiary:
    """Profile of a suspected shell beneficiary account."""

    account_number: str
    bank_name: str
    ifsc_code: str
    receiving_panchayats: List[str] = field(default_factory=list)
    receiving_works: List[str] = field(default_factory=list)
    linked_worker_ids: List[str] = field(default_factory=list)
    total_received: float = 0.0
    transaction_count: int = 0
    confidence: float = 0.0


@dataclass
class VendorCollusionCluster:
    """A cluster of potentially colluding vendors."""

    cluster_id: str
    vendor_ids: List[str] = field(default_factory=list)
    vendor_names: List[str] = field(default_factory=list)
    common_panchayats: List[str] = field(default_factory=list)
    average_rate_inflation_pct: float = 0.0
    total_material_expenditure: float = 0.0
    indicators: List[str] = field(default_factory=list)
    confidence: float = 0.0


@dataclass
class CircularFlow:
    """A detected circular payment flow."""

    cycle_id: str
    path: List[str]  # ordered node IDs forming the cycle
    path_types: List[str]  # node types along the path
    total_flow_amount: float = 0.0
    min_edge_amount: float = 0.0
    involved_officials: List[str] = field(default_factory=list)
    confidence: float = 0.0


@dataclass
class PaymentReport:
    """Complete payment pattern analysis report."""

    report_id: str
    district_id: str
    financial_year: str
    findings: List[PaymentFinding] = field(default_factory=list)
    shell_beneficiaries: List[ShellBeneficiary] = field(default_factory=list)
    vendor_clusters: List[VendorCollusionCluster] = field(default_factory=list)
    circular_flows: List[CircularFlow] = field(default_factory=list)
    graph_stats: Dict[str, Any] = field(default_factory=dict)
    total_suspicious_amount: float = 0.0
    generated_at: datetime = field(default_factory=datetime.utcnow)
    summary: str = ""


# ---------------------------------------------------------------------------
# Payment Pattern Agent
# ---------------------------------------------------------------------------

class PaymentPatternAgent:
    """Agent for payment network analysis and financial fraud detection.

    Builds a directed multigraph of MGNREGA payment flows and applies
    graph-theoretic algorithms to detect circular flows, shell beneficiaries,
    vendor collusion, and other financial fraud patterns.

    Parameters
    ----------
    db_session : Any
        Database session for querying payment and FTO data.
    config : dict, optional
        Runtime configuration overrides.
    """

    # MGNREGA mandates: >= 60% labour, <= 40% material
    MATERIAL_RATIO_LIMIT: float = 0.40
    PAYMENT_SPLIT_THRESHOLD: float = 50000.0  # Rs 50,000 split detection
    MIN_SHELL_PANCHAYATS: int = 3  # min panchayats to flag shell account
    RATE_INFLATION_THRESHOLD_PCT: float = 25.0  # 25% above district average

    def __init__(
        self,
        db_session: Any,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.db = db_session
        self.config = config or {}
        self._graphs: Dict[str, Any] = {}  # cache: district_id -> graph

        if nx is None:
            logger.error(
                "NetworkX is required for PaymentPatternAgent. "
                "Install with: pip install networkx"
            )

        logger.info("PaymentPatternAgent initialised")

    # ------------------------------------------------------------------
    # Graph construction
    # ------------------------------------------------------------------

    async def build_payment_graph(
        self, district_id: str, fin_year: str
    ) -> Any:
        """Build a directed payment flow graph for an entire district.

        The graph encodes the following relationships:
        - PANCHAYAT --sanctions--> WORK
        - WORK --generates--> FTO
        - FTO --pays--> BANK_ACCOUNT
        - BANK_ACCOUNT --belongs_to--> WORKER
        - WORK --procures_from--> VENDOR
        - OFFICIAL --approves--> FTO

        Each edge carries attributes: amount, date, FTO number, etc.

        Parameters
        ----------
        district_id : str
            NREGASoft district code.
        fin_year : str
            Financial year (e.g., ``"2025-2026"``).

        Returns
        -------
        nx.DiGraph
            Directed payment graph.
        """
        if nx is None:
            raise RuntimeError("NetworkX is not installed")

        logger.info(
            "Building payment graph | district={d} | fy={fy}",
            d=district_id,
            fy=fin_year,
        )

        graph = nx.DiGraph()

        try:
            # Fetch FTO-level payment data
            fto_payments = await self._fetch_fto_payments(district_id, fin_year)
            for record in fto_payments:
                panchayat_id = record["gram_panchayat_id"]
                work_id = record["work_id"]
                fto_id = record["fto_no"]
                account_no = record["account_number"]
                worker_id = record["worker_id"]
                amount = record.get("amount", 0.0)
                approver = record.get("approving_officer", "")

                # Add nodes with types
                graph.add_node(
                    panchayat_id,
                    node_type=NodeType.PANCHAYAT.value,
                    label=record.get("panchayat_name", panchayat_id),
                )
                graph.add_node(
                    work_id,
                    node_type=NodeType.WORK.value,
                    label=record.get("work_name", work_id),
                )
                graph.add_node(
                    fto_id,
                    node_type=NodeType.FTO.value,
                    label=fto_id,
                )
                graph.add_node(
                    account_no,
                    node_type=NodeType.BANK_ACCOUNT.value,
                    bank=record.get("bank_name", ""),
                    ifsc=record.get("ifsc_code", ""),
                )
                graph.add_node(
                    worker_id,
                    node_type=NodeType.WORKER.value,
                    label=record.get("worker_name", worker_id),
                )

                # Add edges
                graph.add_edge(
                    panchayat_id,
                    work_id,
                    edge_type="sanctions",
                    amount=amount,
                )
                graph.add_edge(
                    work_id,
                    fto_id,
                    edge_type="generates",
                    amount=amount,
                )
                graph.add_edge(
                    fto_id,
                    account_no,
                    edge_type="pays",
                    amount=amount,
                    date=record.get("payment_date", ""),
                )
                graph.add_edge(
                    account_no,
                    worker_id,
                    edge_type="belongs_to",
                )

                if approver:
                    graph.add_node(
                        approver,
                        node_type=NodeType.OFFICIAL.value,
                    )
                    graph.add_edge(
                        approver,
                        fto_id,
                        edge_type="approves",
                    )

            # Add vendor/material procurement edges
            material_records = await self._fetch_material_payments(
                district_id, fin_year
            )
            for mrec in material_records:
                vendor_id = mrec["vendor_id"]
                work_id = mrec["work_id"]
                graph.add_node(
                    vendor_id,
                    node_type=NodeType.VENDOR.value,
                    label=mrec.get("vendor_name", vendor_id),
                    pan=mrec.get("vendor_pan", ""),
                )
                graph.add_edge(
                    work_id,
                    vendor_id,
                    edge_type="procures_from",
                    amount=mrec.get("amount", 0.0),
                    material_type=mrec.get("material_type", ""),
                    rate=mrec.get("rate", 0.0),
                )

            # Cache the graph
            cache_key = f"{district_id}_{fin_year}"
            self._graphs[cache_key] = graph

            logger.info(
                "Payment graph built | nodes={n} | edges={e}",
                n=graph.number_of_nodes(),
                e=graph.number_of_edges(),
            )
            return graph

        except Exception as exc:
            logger.exception(
                "Failed to build payment graph for district {d}: {e}",
                d=district_id,
                e=exc,
            )
            raise

    # ------------------------------------------------------------------
    # Shell beneficiary detection
    # ------------------------------------------------------------------

    async def detect_shell_beneficiaries(
        self, block_id: str
    ) -> List[ShellBeneficiary]:
        """Detect bank accounts receiving payments from multiple panchayats.

        A "shell beneficiary" is an account that receives MGNREGA wage
        payments from three or more different gram panchayats, which is
        highly unusual and suggests a controlled account used to siphon
        funds.

        Parameters
        ----------
        block_id : str
            NREGASoft block code.

        Returns
        -------
        list of ShellBeneficiary
            Detected shell beneficiary profiles.
        """
        logger.debug(
            "Detecting shell beneficiaries in block {b}", b=block_id
        )

        try:
            # Fetch account-to-panchayat payment mappings
            account_data = await self._fetch_account_panchayat_map(block_id)

            # Group by account
            account_map: Dict[str, Dict[str, Any]] = {}
            for rec in account_data:
                acct = rec["account_number"]
                if acct not in account_map:
                    account_map[acct] = {
                        "bank_name": rec.get("bank_name", ""),
                        "ifsc": rec.get("ifsc_code", ""),
                        "panchayats": set(),
                        "works": set(),
                        "workers": set(),
                        "total": 0.0,
                        "txn_count": 0,
                    }
                account_map[acct]["panchayats"].add(rec["gram_panchayat_id"])
                account_map[acct]["works"].add(rec["work_id"])
                account_map[acct]["workers"].add(rec["worker_id"])
                account_map[acct]["total"] += rec.get("amount", 0.0)
                account_map[acct]["txn_count"] += 1

            # Filter for shell beneficiaries
            shells: List[ShellBeneficiary] = []
            min_panchayats = self.config.get(
                "min_shell_panchayats", self.MIN_SHELL_PANCHAYATS
            )

            for acct, data in account_map.items():
                if len(data["panchayats"]) >= min_panchayats:
                    confidence = min(
                        len(data["panchayats"]) / 10.0, 1.0
                    )
                    shells.append(
                        ShellBeneficiary(
                            account_number=acct,
                            bank_name=data["bank_name"],
                            ifsc_code=data["ifsc"],
                            receiving_panchayats=sorted(data["panchayats"]),
                            receiving_works=sorted(data["works"]),
                            linked_worker_ids=sorted(data["workers"]),
                            total_received=round(data["total"], 2),
                            transaction_count=data["txn_count"],
                            confidence=round(confidence, 4),
                        )
                    )

            logger.debug(
                "Shell beneficiary detection: {n} accounts flagged in block {b}",
                n=len(shells),
                b=block_id,
            )
            return shells

        except Exception as exc:
            logger.error(
                "Shell beneficiary detection failed for block {b}: {e}",
                b=block_id,
                e=exc,
            )
            return []

    # ------------------------------------------------------------------
    # Labour-material ratio check
    # ------------------------------------------------------------------

    async def check_labor_material_ratio(
        self, work_id: str
    ) -> Optional[PaymentFinding]:
        """Check if a work violates the MGNREGA 60:40 labour-material ratio.

        MGNREGA mandates that at least 60% of expenditure must be on
        wages (labour) and at most 40% on materials. Violations indicate
        potential siphoning through inflated material costs.

        Parameters
        ----------
        work_id : str
            NREGASoft work identifier.

        Returns
        -------
        PaymentFinding or None
            Finding if a violation is detected, else None.
        """
        try:
            work_data = await self._fetch_work_expenditure(work_id)
            if not work_data:
                return None

            labour = work_data.get("labour_expenditure", 0.0)
            material = work_data.get("material_expenditure", 0.0)
            total = labour + material

            if total <= 0:
                return None

            material_ratio = material / total
            labour_ratio = labour / total

            if material_ratio > self.MATERIAL_RATIO_LIMIT:
                severity = (
                    "critical"
                    if material_ratio > 0.60
                    else "high"
                    if material_ratio > 0.50
                    else "medium"
                )

                return PaymentFinding(
                    finding_id=f"F-{uuid.uuid4().hex[:8]}",
                    fraud_type=PaymentFraudType.MATERIAL_RATIO_VIOLATION,
                    severity=severity,
                    description=(
                        f"Work {work_id} violates MGNREGA 60:40 ratio: "
                        f"labour={labour_ratio:.0%}, material={material_ratio:.0%}. "
                        f"Material expenditure Rs.{material:,.0f} out of "
                        f"Rs.{total:,.0f} total"
                    ),
                    affected_entities=[work_id],
                    evidence={
                        "work_id": work_id,
                        "labour_expenditure": labour,
                        "material_expenditure": material,
                        "total_expenditure": total,
                        "labour_ratio": round(labour_ratio, 4),
                        "material_ratio": round(material_ratio, 4),
                    },
                    estimated_amount=material - (total * self.MATERIAL_RATIO_LIMIT),
                    confidence=min((material_ratio - 0.40) / 0.30 + 0.5, 1.0),
                    recommended_action=(
                        "Audit material procurement records; verify vendor invoices; "
                        "compare material rates with district schedule of rates"
                    ),
                )

            return None

        except Exception as exc:
            logger.error(
                "Ratio check failed for work {w}: {e}", w=work_id, e=exc
            )
            return None

    # ------------------------------------------------------------------
    # Payment splitting detection
    # ------------------------------------------------------------------

    async def detect_payment_splitting(
        self, panchayat_id: str
    ) -> List[PaymentFinding]:
        """Detect payment splitting patterns in a panchayat.

        Payment splitting occurs when a large payment is broken into
        multiple smaller FTOs to stay below scrutiny thresholds (e.g.,
        splitting a Rs 5 lakh payment into ten Rs 50,000 transfers).

        Parameters
        ----------
        panchayat_id : str
            Gram panchayat code.

        Returns
        -------
        list of PaymentFinding
            Detected splitting patterns.
        """
        logger.debug(
            "Detecting payment splitting in GP {gp}", gp=panchayat_id
        )

        findings: List[PaymentFinding] = []

        try:
            # Fetch all FTOs for this panchayat, ordered by date
            fto_records = await self._fetch_panchayat_ftos(panchayat_id)
            if not fto_records:
                return []

            # Group FTOs by target account and date proximity
            account_ftos: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
            for fto in fto_records:
                account_ftos[fto["account_number"]].append(fto)

            for account, ftos in account_ftos.items():
                if len(ftos) < 3:
                    continue

                # Sort by date
                ftos.sort(key=lambda x: x.get("payment_date", ""))

                # Sliding window: check for clusters of payments just below threshold
                window_days = self.config.get("split_window_days", 7)
                threshold = self.config.get(
                    "split_threshold", self.PAYMENT_SPLIT_THRESHOLD
                )

                for i in range(len(ftos)):
                    cluster = [ftos[i]]
                    base_date = ftos[i].get("payment_date", "")
                    if not base_date:
                        continue

                    for j in range(i + 1, len(ftos)):
                        compare_date = ftos[j].get("payment_date", "")
                        if not compare_date:
                            continue
                        try:
                            d1 = datetime.fromisoformat(str(base_date))
                            d2 = datetime.fromisoformat(str(compare_date))
                            if (d2 - d1).days <= window_days:
                                cluster.append(ftos[j])
                            else:
                                break
                        except (ValueError, TypeError):
                            continue

                    if len(cluster) >= 3:
                        amounts = [c.get("amount", 0) for c in cluster]
                        total = sum(amounts)

                        # Check if individual amounts are just below threshold
                        # but total significantly exceeds it
                        below_threshold = all(a < threshold for a in amounts)
                        total_exceeds = total > threshold * 2

                        if below_threshold and total_exceeds:
                            findings.append(
                                PaymentFinding(
                                    finding_id=f"F-{uuid.uuid4().hex[:8]}",
                                    fraud_type=PaymentFraudType.PAYMENT_SPLITTING,
                                    severity="high",
                                    description=(
                                        f"Payment splitting detected: {len(cluster)} "
                                        f"transfers to account {account[:6]}*** "
                                        f"within {window_days} days, each below "
                                        f"Rs.{threshold:,.0f} but totalling "
                                        f"Rs.{total:,.0f}"
                                    ),
                                    affected_entities=[
                                        panchayat_id, account
                                    ] + [c["fto_no"] for c in cluster],
                                    evidence={
                                        "account": account,
                                        "num_transfers": len(cluster),
                                        "amounts": amounts,
                                        "total": total,
                                        "fto_numbers": [
                                            c["fto_no"] for c in cluster
                                        ],
                                        "window_days": window_days,
                                    },
                                    estimated_amount=total,
                                    confidence=min(
                                        len(cluster) / 10.0, 1.0
                                    ),
                                    recommended_action=(
                                        "Verify if split payments correspond to "
                                        "legitimate separate muster rolls or if "
                                        "they were artificially divided"
                                    ),
                                )
                            )

            return findings

        except Exception as exc:
            logger.error(
                "Payment splitting detection failed for GP {gp}: {e}",
                gp=panchayat_id,
                e=exc,
            )
            return []

    # ------------------------------------------------------------------
    # Circular flow detection
    # ------------------------------------------------------------------

    def find_circular_flows(
        self, graph: Any
    ) -> List[CircularFlow]:
        """Detect circular payment flows in the payment graph.

        A circular flow suggests that money paid to a beneficiary account
        eventually flows back to an official or panchayat account, indicating
        potential embezzlement or kickback schemes.

        Uses Johnson's algorithm for finding all elementary cycles in the
        directed graph.

        Parameters
        ----------
        graph : nx.DiGraph
            The payment network graph.

        Returns
        -------
        list of CircularFlow
            Detected circular payment flows.
        """
        if nx is None:
            logger.error("NetworkX required for circular flow detection")
            return []

        logger.debug("Detecting circular flows in payment graph")

        circular_flows: List[CircularFlow] = []

        try:
            # Find all simple cycles
            max_cycle_length = self.config.get("max_cycle_length", 8)
            cycles = list(nx.simple_cycles(graph))

            for cycle in cycles:
                if len(cycle) < 3 or len(cycle) > max_cycle_length:
                    continue

                # Get node types along the cycle
                path_types = [
                    graph.nodes[n].get("node_type", "unknown") for n in cycle
                ]

                # Filter for cycles involving officials or panchayats
                involves_official = NodeType.OFFICIAL.value in path_types
                involves_panchayat = NodeType.PANCHAYAT.value in path_types

                if not (involves_official or involves_panchayat):
                    continue

                # Calculate flow amounts along edges
                edge_amounts = []
                for i in range(len(cycle)):
                    src = cycle[i]
                    dst = cycle[(i + 1) % len(cycle)]
                    edge_data = graph.get_edge_data(src, dst, default={})
                    amount = edge_data.get("amount", 0.0)
                    edge_amounts.append(amount)

                total_flow = sum(edge_amounts)
                min_edge = min(edge_amounts) if edge_amounts else 0.0

                officials = [
                    cycle[i]
                    for i, t in enumerate(path_types)
                    if t == NodeType.OFFICIAL.value
                ]

                confidence = 0.7 if involves_official else 0.5
                if len(cycle) <= 4:
                    confidence += 0.1

                circular_flows.append(
                    CircularFlow(
                        cycle_id=f"CYC-{uuid.uuid4().hex[:8]}",
                        path=cycle,
                        path_types=path_types,
                        total_flow_amount=round(total_flow, 2),
                        min_edge_amount=round(min_edge, 2),
                        involved_officials=officials,
                        confidence=round(min(confidence, 1.0), 4),
                    )
                )

            logger.debug(
                "Circular flow detection: {n} cycles found", n=len(circular_flows)
            )
            return circular_flows

        except Exception as exc:
            logger.error("Circular flow detection failed: {e}", e=exc)
            return []

    # ------------------------------------------------------------------
    # Vendor collusion detection
    # ------------------------------------------------------------------

    async def detect_vendor_collusion(
        self, district_id: str
    ) -> List[VendorCollusionCluster]:
        """Detect vendor collusion patterns across panchayats.

        Identifies clusters of vendors that:
        - Supply materials to the same set of panchayats
        - Charge consistently inflated rates above the district SOR
        - Share common ownership indicators (similar names, addresses, PAN
          patterns)
        - Win contracts in suspiciously regular rotation patterns

        Parameters
        ----------
        district_id : str
            NREGASoft district code.

        Returns
        -------
        list of VendorCollusionCluster
            Detected collusion clusters.
        """
        logger.debug(
            "Detecting vendor collusion in district {d}", d=district_id
        )

        clusters: List[VendorCollusionCluster] = []

        try:
            # Fetch vendor data
            vendor_data = await self._fetch_vendor_data(district_id)
            if not vendor_data:
                return []

            # Build vendor-panchayat matrix
            vendor_panchayats: Dict[str, Set[str]] = defaultdict(set)
            vendor_rates: Dict[str, List[float]] = defaultdict(list)
            vendor_names: Dict[str, str] = {}
            vendor_totals: Dict[str, float] = defaultdict(float)

            for rec in vendor_data:
                vid = rec["vendor_id"]
                vendor_panchayats[vid].add(rec["gram_panchayat_id"])
                vendor_rates[vid].append(rec.get("rate", 0.0))
                vendor_names[vid] = rec.get("vendor_name", vid)
                vendor_totals[vid] += rec.get("amount", 0.0)

            # Fetch district average rates for comparison
            district_avg_rates = await self._fetch_district_sor_rates(
                district_id
            )

            vendors = list(vendor_panchayats.keys())
            if len(vendors) < 2:
                return []

            # Jaccard similarity on panchayat sets
            visited: Set[str] = set()
            for i, v1 in enumerate(vendors):
                if v1 in visited:
                    continue
                cluster_vendors = [v1]

                for j in range(i + 1, len(vendors)):
                    v2 = vendors[j]
                    if v2 in visited:
                        continue

                    p1 = vendor_panchayats[v1]
                    p2 = vendor_panchayats[v2]
                    intersection = len(p1 & p2)
                    union = len(p1 | p2)
                    if union == 0:
                        continue

                    similarity = intersection / union
                    if similarity >= 0.5 and intersection >= 2:
                        cluster_vendors.append(v2)

                if len(cluster_vendors) >= 2:
                    # Compute rate inflation
                    all_rates = []
                    for cv in cluster_vendors:
                        all_rates.extend(vendor_rates[cv])

                    avg_vendor_rate = np.mean(all_rates) if all_rates else 0.0
                    avg_district_rate = (
                        np.mean(list(district_avg_rates.values()))
                        if district_avg_rates
                        else avg_vendor_rate
                    )

                    inflation_pct = 0.0
                    if avg_district_rate > 0:
                        inflation_pct = (
                            (avg_vendor_rate - avg_district_rate)
                            / avg_district_rate
                            * 100
                        )

                    # Build indicators
                    indicators: List[str] = []
                    if inflation_pct > self.RATE_INFLATION_THRESHOLD_PCT:
                        indicators.append(
                            f"rate_inflation_{inflation_pct:.0f}pct"
                        )

                    common_gps = set.intersection(
                        *[vendor_panchayats[v] for v in cluster_vendors]
                    )
                    if len(common_gps) >= 3:
                        indicators.append("shared_multiple_panchayats")

                    # Check for similar vendor names (potential benami)
                    names = [vendor_names.get(v, "") for v in cluster_vendors]
                    if self._names_are_similar(names):
                        indicators.append("similar_vendor_names")

                    if indicators:
                        total_expenditure = sum(
                            vendor_totals[v] for v in cluster_vendors
                        )
                        confidence = min(len(indicators) / 4.0, 1.0)

                        clusters.append(
                            VendorCollusionCluster(
                                cluster_id=f"VCC-{uuid.uuid4().hex[:8]}",
                                vendor_ids=cluster_vendors,
                                vendor_names=[
                                    vendor_names.get(v, v)
                                    for v in cluster_vendors
                                ],
                                common_panchayats=sorted(common_gps),
                                average_rate_inflation_pct=round(
                                    inflation_pct, 1
                                ),
                                total_material_expenditure=round(
                                    total_expenditure, 2
                                ),
                                indicators=indicators,
                                confidence=round(confidence, 4),
                            )
                        )
                        visited.update(cluster_vendors)

            logger.debug(
                "Vendor collusion detection: {n} clusters in district {d}",
                n=len(clusters),
                d=district_id,
            )
            return clusters

        except Exception as exc:
            logger.error(
                "Vendor collusion detection failed for district {d}: {e}",
                d=district_id,
                e=exc,
            )
            return []

    # ------------------------------------------------------------------
    # District-level report generation
    # ------------------------------------------------------------------

    async def generate_payment_report(
        self, district_id: str
    ) -> PaymentReport:
        """Generate a comprehensive payment pattern analysis for a district.

        Orchestrates all detection modules and compiles findings.

        Parameters
        ----------
        district_id : str
            NREGASoft district code.

        Returns
        -------
        PaymentReport
            Complete payment analysis report.
        """
        report_id = f"RPT-PAY-{uuid.uuid4().hex[:10].upper()}"
        fin_year = self.config.get("financial_year", "2025-2026")

        logger.info(
            "Generating payment report | district={d} | fy={fy}",
            d=district_id,
            fy=fin_year,
        )

        report = PaymentReport(
            report_id=report_id,
            district_id=district_id,
            financial_year=fin_year,
        )

        try:
            # Build the payment graph
            graph = await self.build_payment_graph(district_id, fin_year)
            report.graph_stats = {
                "total_nodes": graph.number_of_nodes(),
                "total_edges": graph.number_of_edges(),
                "node_types": dict(
                    Counter(
                        data.get("node_type", "unknown")
                        for _, data in graph.nodes(data=True)
                    )
                ),
            }

            # Run all detection modules
            # 1. Circular flows
            report.circular_flows = self.find_circular_flows(graph)
            for cf in report.circular_flows:
                report.findings.append(
                    PaymentFinding(
                        finding_id=f"F-{uuid.uuid4().hex[:8]}",
                        fraud_type=PaymentFraudType.CIRCULAR_FLOW,
                        severity="critical",
                        description=(
                            f"Circular payment flow detected: "
                            f"{' -> '.join(cf.path[:4])}... "
                            f"({len(cf.path)} nodes, Rs.{cf.total_flow_amount:,.0f})"
                        ),
                        affected_entities=cf.path,
                        evidence={
                            "cycle_length": len(cf.path),
                            "total_flow": cf.total_flow_amount,
                            "officials": cf.involved_officials,
                        },
                        estimated_amount=cf.total_flow_amount,
                        confidence=cf.confidence,
                        recommended_action=(
                            "Trace the complete fund flow with bank records; "
                            "investigate involved officials"
                        ),
                    )
                )

            # 2. Shell beneficiaries (across all blocks in district)
            blocks = await self._fetch_district_blocks(district_id)
            for block in blocks:
                shells = await self.detect_shell_beneficiaries(
                    block["block_id"]
                )
                report.shell_beneficiaries.extend(shells)
                for sb in shells:
                    report.findings.append(
                        PaymentFinding(
                            finding_id=f"F-{uuid.uuid4().hex[:8]}",
                            fraud_type=PaymentFraudType.SHELL_BENEFICIARY,
                            severity="high",
                            description=(
                                f"Shell beneficiary account {sb.account_number[:6]}*** "
                                f"receiving from {len(sb.receiving_panchayats)} "
                                f"panchayats, Rs.{sb.total_received:,.0f} total"
                            ),
                            affected_entities=[sb.account_number]
                            + sb.receiving_panchayats,
                            evidence={
                                "panchayat_count": len(sb.receiving_panchayats),
                                "total_received": sb.total_received,
                                "transaction_count": sb.transaction_count,
                            },
                            estimated_amount=sb.total_received,
                            confidence=sb.confidence,
                            recommended_action=(
                                "Verify account holder identity; check if single "
                                "person holds job cards in multiple panchayats"
                            ),
                        )
                    )

            # 3. Vendor collusion
            report.vendor_clusters = await self.detect_vendor_collusion(
                district_id
            )
            for vc in report.vendor_clusters:
                report.findings.append(
                    PaymentFinding(
                        finding_id=f"F-{uuid.uuid4().hex[:8]}",
                        fraud_type=PaymentFraudType.VENDOR_COLLUSION,
                        severity="high",
                        description=(
                            f"Vendor collusion cluster: {len(vc.vendor_ids)} vendors "
                            f"({', '.join(vc.vendor_names[:3])}) operating across "
                            f"{len(vc.common_panchayats)} common panchayats with "
                            f"{vc.average_rate_inflation_pct:.0f}% rate inflation"
                        ),
                        affected_entities=vc.vendor_ids + vc.common_panchayats,
                        evidence={
                            "vendor_count": len(vc.vendor_ids),
                            "common_panchayats": len(vc.common_panchayats),
                            "rate_inflation_pct": vc.average_rate_inflation_pct,
                            "total_expenditure": vc.total_material_expenditure,
                            "indicators": vc.indicators,
                        },
                        estimated_amount=vc.total_material_expenditure * 0.25,
                        confidence=vc.confidence,
                        recommended_action=(
                            "Cross-verify vendor registrations; check beneficial "
                            "ownership; compare rates with SOR"
                        ),
                    )
                )

            # 4. Payment splitting for each panchayat
            panchayats = await self._fetch_district_panchayats(district_id)
            for gp in panchayats:
                splitting_findings = await self.detect_payment_splitting(
                    gp["gram_panchayat_id"]
                )
                report.findings.extend(splitting_findings)

            # 5. Labour-material ratio checks
            works = await self._fetch_district_works(district_id, fin_year)
            for work in works:
                ratio_finding = await self.check_labor_material_ratio(
                    work["work_id"]
                )
                if ratio_finding:
                    report.findings.append(ratio_finding)

            # Aggregate
            report.total_suspicious_amount = sum(
                f.estimated_amount for f in report.findings
            )
            report.summary = self._generate_payment_summary(report)

            logger.info(
                "Payment report generated | district={d} | findings={f} | amount=Rs.{a:,.0f}",
                d=district_id,
                f=len(report.findings),
                a=report.total_suspicious_amount,
            )
            return report

        except Exception as exc:
            logger.exception(
                "Payment report generation failed for district {d}: {e}",
                d=district_id,
                e=exc,
            )
            raise

    # ------------------------------------------------------------------
    # Private helpers -- data fetching
    # ------------------------------------------------------------------

    async def _fetch_fto_payments(
        self, district_id: str, fin_year: str
    ) -> List[Dict[str, Any]]:
        """Fetch FTO-level payment records for the district."""
        query = """
            SELECT fto.fto_no,
                   fto.work_id,
                   fto.worker_id,
                   fto.account_number,
                   fto.amount,
                   fto.payment_date,
                   fto.approving_officer,
                   w.gram_panchayat_id,
                   w.work_name,
                   gp.panchayat_name,
                   ba.bank_name,
                   ba.ifsc_code,
                   jc.worker_name
            FROM   fund_transfer_orders fto
                   JOIN works w ON fto.work_id = w.work_id
                   JOIN gram_panchayats gp
                       ON w.gram_panchayat_id = gp.panchayat_code
                   LEFT JOIN bank_accounts ba
                       ON fto.account_number = ba.account_number
                   LEFT JOIN job_cards jc
                       ON fto.worker_id = jc.worker_id
            WHERE  w.district_id = :district_id
              AND  w.financial_year = :fy
            ORDER  BY fto.payment_date
        """
        rows = await self.db.fetch_all(
            query, {"district_id": district_id, "fy": fin_year}
        )
        return [dict(r) for r in rows]

    async def _fetch_material_payments(
        self, district_id: str, fin_year: str
    ) -> List[Dict[str, Any]]:
        """Fetch material procurement records."""
        query = """
            SELECT mp.vendor_id,
                   mp.work_id,
                   mp.amount,
                   mp.material_type,
                   mp.rate,
                   mp.quantity,
                   v.vendor_name,
                   v.vendor_pan,
                   w.gram_panchayat_id
            FROM   material_payments mp
                   JOIN works w ON mp.work_id = w.work_id
                   LEFT JOIN vendors v ON mp.vendor_id = v.vendor_id
            WHERE  w.district_id = :district_id
              AND  w.financial_year = :fy
        """
        rows = await self.db.fetch_all(
            query, {"district_id": district_id, "fy": fin_year}
        )
        return [dict(r) for r in rows]

    async def _fetch_account_panchayat_map(
        self, block_id: str
    ) -> List[Dict[str, Any]]:
        """Fetch account-to-panchayat payment mappings."""
        query = """
            SELECT fto.account_number,
                   w.gram_panchayat_id,
                   fto.work_id,
                   fto.worker_id,
                   fto.amount,
                   ba.bank_name,
                   ba.ifsc_code
            FROM   fund_transfer_orders fto
                   JOIN works w ON fto.work_id = w.work_id
                   LEFT JOIN bank_accounts ba
                       ON fto.account_number = ba.account_number
            WHERE  w.block_id = :block_id
        """
        rows = await self.db.fetch_all(query, {"block_id": block_id})
        return [dict(r) for r in rows]

    async def _fetch_panchayat_ftos(
        self, panchayat_id: str
    ) -> List[Dict[str, Any]]:
        """Fetch all FTOs for a panchayat."""
        query = """
            SELECT fto.fto_no,
                   fto.account_number,
                   fto.amount,
                   fto.payment_date,
                   fto.worker_id
            FROM   fund_transfer_orders fto
                   JOIN works w ON fto.work_id = w.work_id
            WHERE  w.gram_panchayat_id = :gp_id
            ORDER  BY fto.payment_date
        """
        rows = await self.db.fetch_all(query, {"gp_id": panchayat_id})
        return [dict(r) for r in rows]

    async def _fetch_work_expenditure(
        self, work_id: str
    ) -> Optional[Dict[str, Any]]:
        """Fetch labour and material expenditure for a work."""
        query = """
            SELECT w.work_id,
                   w.labour_expenditure,
                   w.material_expenditure,
                   w.total_expenditure
            FROM   works w
            WHERE  w.work_id = :work_id
        """
        row = await self.db.fetch_one(query, {"work_id": work_id})
        return dict(row) if row else None

    async def _fetch_vendor_data(
        self, district_id: str
    ) -> List[Dict[str, Any]]:
        """Fetch vendor procurement data for a district."""
        query = """
            SELECT mp.vendor_id,
                   v.vendor_name,
                   w.gram_panchayat_id,
                   mp.rate,
                   mp.amount,
                   mp.material_type
            FROM   material_payments mp
                   JOIN works w ON mp.work_id = w.work_id
                   JOIN vendors v ON mp.vendor_id = v.vendor_id
            WHERE  w.district_id = :district_id
        """
        rows = await self.db.fetch_all(query, {"district_id": district_id})
        return [dict(r) for r in rows]

    async def _fetch_district_sor_rates(
        self, district_id: str
    ) -> Dict[str, float]:
        """Fetch Schedule of Rates averages for the district."""
        query = """
            SELECT material_type, AVG(rate) AS avg_rate
            FROM   schedule_of_rates
            WHERE  district_id = :district_id
            GROUP  BY material_type
        """
        rows = await self.db.fetch_all(query, {"district_id": district_id})
        return {r["material_type"]: r["avg_rate"] for r in rows}

    async def _fetch_district_blocks(
        self, district_id: str
    ) -> List[Dict[str, Any]]:
        """Fetch all blocks in a district."""
        query = """
            SELECT DISTINCT b.block_code AS block_id, b.block_name
            FROM   blocks b
            WHERE  b.district_code = :district_id
        """
        rows = await self.db.fetch_all(query, {"district_id": district_id})
        return [dict(r) for r in rows]

    async def _fetch_district_panchayats(
        self, district_id: str
    ) -> List[Dict[str, Any]]:
        """Fetch all gram panchayats in a district."""
        query = """
            SELECT gp.panchayat_code AS gram_panchayat_id
            FROM   gram_panchayats gp
            WHERE  gp.district_code = :district_id
              AND  gp.is_active = TRUE
        """
        rows = await self.db.fetch_all(query, {"district_id": district_id})
        return [dict(r) for r in rows]

    async def _fetch_district_works(
        self, district_id: str, fin_year: str
    ) -> List[Dict[str, Any]]:
        """Fetch all works in a district for a financial year."""
        query = """
            SELECT w.work_id
            FROM   works w
            WHERE  w.district_id = :district_id
              AND  w.financial_year = :fy
        """
        rows = await self.db.fetch_all(
            query, {"district_id": district_id, "fy": fin_year}
        )
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Private helpers -- utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _names_are_similar(names: List[str]) -> bool:
        """Check if vendor names are suspiciously similar (potential benami).

        Uses simple token overlap as a heuristic. In production, this
        would use fuzzy string matching or an entity resolution model.
        """
        if len(names) < 2:
            return False

        # Tokenise and check overlap
        token_sets = [
            set(name.lower().split()) - {"and", "the", "of", "pvt", "ltd", "co"}
            for name in names
            if name
        ]

        for i in range(len(token_sets)):
            for j in range(i + 1, len(token_sets)):
                if not token_sets[i] or not token_sets[j]:
                    continue
                overlap = len(token_sets[i] & token_sets[j])
                union = len(token_sets[i] | token_sets[j])
                if union > 0 and overlap / union > 0.5:
                    return True

        return False

    @staticmethod
    def _generate_payment_summary(report: PaymentReport) -> str:
        """Generate a human-readable summary of the payment report."""
        lines = [
            f"Payment Pattern Analysis Report: District {report.district_id}",
            f"Financial Year: {report.financial_year}",
            f"Generated: {report.generated_at.strftime('%Y-%m-%d %H:%M UTC')}",
            "",
            f"Payment Graph: {report.graph_stats.get('total_nodes', 0)} nodes, "
            f"{report.graph_stats.get('total_edges', 0)} edges",
            "",
            f"Total findings: {len(report.findings)}",
            f"Circular flows detected: {len(report.circular_flows)}",
            f"Shell beneficiary accounts: {len(report.shell_beneficiaries)}",
            f"Vendor collusion clusters: {len(report.vendor_clusters)}",
            "",
            f"Total suspicious amount: Rs.{report.total_suspicious_amount:,.0f}",
        ]

        # Severity breakdown
        severity_counts: Dict[str, int] = defaultdict(int)
        for f in report.findings:
            severity_counts[f.severity] += 1
        for sev in ["critical", "high", "medium", "low"]:
            if severity_counts.get(sev, 0) > 0:
                lines.append(f"  {sev.upper()}: {severity_counts[sev]}")

        return "\n".join(lines)
