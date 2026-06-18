"""
Payment Network Graph Analysis Module
======================================

Models the MGNREGA fund flow as a directed graph and applies network
analysis techniques to detect collusion rings, circular payments,
hub accounts, and rapid fund movements.

Node types:
    - ``worker``     : individual beneficiary
    - ``account``    : bank / post-office account
    - ``work``       : sanctioned MGNREGA work
    - ``panchayat``  : gram panchayat originating the work
    - ``fto``        : Fund Transfer Order

Edge types:
    - ``enrolled_in``     : worker -> work
    - ``paid_for``        : work -> payment
    - ``paid_to``         : payment -> account
    - ``belongs_to``      : work -> panchayat
    - ``authorised_by``   : payment -> fto
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

import networkx as nx
import numpy as np
from loguru import logger


# ---------------------------------------------------------------------------
# Node / edge attribute constants
# ---------------------------------------------------------------------------
_NTYPE = "node_type"   # attribute key for node type
_ETYPE = "edge_type"   # attribute key for edge type


class PaymentNetworkAnalyzer:
    """Graph-based fraud detection on MGNREGA payment networks.

    All public methods accept and return plain Python data structures
    (dicts, lists) so they can be serialised directly to JSON for the
    API layer.  Internally, ``networkx`` graphs are used.
    """

    # ------------------------------------------------------------------
    # Graph construction
    # ------------------------------------------------------------------
    def build_bipartite_graph(
        self,
        workers: List[Dict[str, Any]],
        payments: List[Dict[str, Any]],
        works: List[Dict[str, Any]],
    ) -> nx.Graph:
        """Build an undirected bipartite graph linking workers to works
        through payments.

        Parameters
        ----------
        workers : list[dict]
            Each dict must have ``"worker_id"`` and optionally
            ``"name"``, ``"account_no"``, ``"panchayat_id"``.
        payments : list[dict]
            Each dict: ``"payment_id"``, ``"worker_id"``, ``"work_id"``,
            ``"amount"``, ``"payment_date"``, ``"account_no"``.
        works : list[dict]
            Each dict: ``"work_id"``, ``"work_name"``, ``"panchayat_id"``,
            ``"sanctioned_amount"``.

        Returns
        -------
        nx.Graph
        """
        G = nx.Graph()

        # Add worker nodes
        for w in workers:
            wid = f"worker_{w['worker_id']}"
            G.add_node(wid, **{_NTYPE: "worker"}, **w)

        # Add work nodes
        for wk in works:
            wkid = f"work_{wk['work_id']}"
            G.add_node(wkid, **{_NTYPE: "work"}, **wk)
            # Link to panchayat
            pid = wk.get("panchayat_id")
            if pid:
                pnode = f"panchayat_{pid}"
                if pnode not in G:
                    G.add_node(pnode, **{_NTYPE: "panchayat", "panchayat_id": pid})
                G.add_edge(wkid, pnode, **{_ETYPE: "belongs_to"})

        # Add account nodes and payment edges
        for p in payments:
            wid = f"worker_{p['worker_id']}"
            wkid = f"work_{p['work_id']}"
            acc = p.get("account_no")

            # worker <-> work
            G.add_edge(wid, wkid, **{
                _ETYPE: "enrolled_in",
                "payment_id": p.get("payment_id"),
                "amount": p.get("amount", 0),
                "payment_date": p.get("payment_date"),
            })

            # work <-> account
            if acc:
                anode = f"account_{acc}"
                if anode not in G:
                    G.add_node(anode, **{_NTYPE: "account", "account_no": acc})
                G.add_edge(wkid, anode, **{
                    _ETYPE: "paid_to",
                    "amount": p.get("amount", 0),
                })
                # worker <-> account
                G.add_edge(wid, anode, **{
                    _ETYPE: "paid_to",
                    "amount": p.get("amount", 0),
                })

        logger.info(
            "Bipartite graph built  |  nodes={n}  edges={e}",
            n=G.number_of_nodes(),
            e=G.number_of_edges(),
        )
        return G

    def build_fund_flow_graph(
        self,
        ftos: List[Dict[str, Any]],
        payments: List[Dict[str, Any]],
        accounts: List[Dict[str, Any]],
    ) -> nx.DiGraph:
        """Build a directed graph of fund flow from FTOs to bank accounts.

        Parameters
        ----------
        ftos : list[dict]
            ``"fto_id"``, ``"total_amount"``, ``"generation_date"``,
            ``"panchayat_id"``.
        payments : list[dict]
            ``"payment_id"``, ``"fto_id"``, ``"account_no"``, ``"amount"``,
            ``"credit_date"``.
        accounts : list[dict]
            ``"account_no"``, ``"bank_name"``, ``"branch"``, ``"ifsc"``.

        Returns
        -------
        nx.DiGraph
        """
        G = nx.DiGraph()

        # FTO nodes
        for fto in ftos:
            fid = f"fto_{fto['fto_id']}"
            G.add_node(fid, **{_NTYPE: "fto"}, **fto)
            pid = fto.get("panchayat_id")
            if pid:
                pnode = f"panchayat_{pid}"
                if pnode not in G:
                    G.add_node(pnode, **{_NTYPE: "panchayat", "panchayat_id": pid})
                G.add_edge(pnode, fid, **{
                    _ETYPE: "authorised_by",
                    "amount": fto.get("total_amount", 0),
                })

        # Account nodes
        for acc in accounts:
            anode = f"account_{acc['account_no']}"
            G.add_node(anode, **{_NTYPE: "account"}, **acc)

        # Payment edges: FTO -> account
        for p in payments:
            fid = f"fto_{p['fto_id']}"
            anode = f"account_{p['account_no']}"
            G.add_edge(fid, anode, **{
                _ETYPE: "paid_to",
                "payment_id": p.get("payment_id"),
                "amount": p.get("amount", 0),
                "credit_date": p.get("credit_date"),
            })

        logger.info(
            "Fund flow graph built  |  nodes={n}  edges={e}",
            n=G.number_of_nodes(),
            e=G.number_of_edges(),
        )
        return G

    # ------------------------------------------------------------------
    # Community / cluster detection
    # ------------------------------------------------------------------
    def detect_communities(
        self,
        graph: nx.Graph,
        resolution: float = 1.0,
    ) -> List[Dict[str, Any]]:
        """Find tightly connected clusters (potential collusion rings)
        using the Louvain community detection algorithm.

        Parameters
        ----------
        graph : nx.Graph
            Undirected graph (bipartite or projected).
        resolution : float
            Louvain resolution parameter (higher = smaller communities).

        Returns
        -------
        list[dict]
            Each dict: ``{"community_id", "members", "size",
            "node_types", "internal_edges", "total_amount"}``.
        """
        if graph.number_of_nodes() == 0:
            return []

        # Louvain expects an undirected graph
        ug = graph.to_undirected() if graph.is_directed() else graph
        communities_gen = nx.community.louvain_communities(
            ug, resolution=resolution, seed=42,
        )

        results: List[Dict[str, Any]] = []
        for idx, members in enumerate(communities_gen):
            member_list = sorted(members)
            subgraph = ug.subgraph(members)
            node_types = set()
            total_amount = 0.0
            for n in members:
                ntype = ug.nodes[n].get(_NTYPE, "unknown")
                node_types.add(ntype)
            for _, _, edata in subgraph.edges(data=True):
                total_amount += float(edata.get("amount", 0))

            results.append({
                "community_id": idx,
                "members": member_list,
                "size": len(member_list),
                "node_types": sorted(node_types),
                "internal_edges": subgraph.number_of_edges(),
                "total_amount": round(total_amount, 2),
            })

        # Sort by size descending
        results.sort(key=lambda c: c["size"], reverse=True)
        logger.info(
            "Communities detected  |  count={c}  largest={l}",
            c=len(results),
            l=results[0]["size"] if results else 0,
        )
        return results

    # ------------------------------------------------------------------
    # Bridge nodes
    # ------------------------------------------------------------------
    def find_bridge_nodes(
        self,
        graph: nx.Graph,
        top_n: int = 20,
    ) -> List[Dict[str, Any]]:
        """Identify key intermediary nodes (bridges) in the payment network.

        Bridge nodes connect otherwise-separate parts of the graph.
        In a fraud context, these are often officials or middlemen
        linking multiple panchayats.

        Returns
        -------
        list[dict]
            Sorted by betweenness centrality descending.
        """
        ug = graph.to_undirected() if graph.is_directed() else graph
        if ug.number_of_nodes() == 0:
            return []

        betweenness = nx.betweenness_centrality(ug)
        sorted_nodes = sorted(betweenness.items(), key=lambda x: x[1], reverse=True)

        bridges: List[Dict[str, Any]] = []
        for node, bc in sorted_nodes[:top_n]:
            bridges.append({
                "node_id": node,
                "node_type": ug.nodes[node].get(_NTYPE, "unknown"),
                "betweenness_centrality": round(bc, 6),
                "degree": ug.degree(node),
            })

        logger.info(
            "Bridge nodes  |  top_{n}  highest_bc={bc:.4f}",
            n=top_n,
            bc=bridges[0]["betweenness_centrality"] if bridges else 0,
        )
        return bridges

    # ------------------------------------------------------------------
    # Circular flows
    # ------------------------------------------------------------------
    def detect_circular_flows(
        self,
        graph: nx.DiGraph,
        min_cycle_length: int = 3,
        max_cycle_length: int = 8,
    ) -> List[Dict[str, Any]]:
        """Find circular payment patterns in the directed fund-flow graph.

        Circular flows (A -> B -> C -> A) may indicate round-tripping
        of funds through shell beneficiaries.

        Parameters
        ----------
        graph : nx.DiGraph
        min_cycle_length : int
        max_cycle_length : int

        Returns
        -------
        list[dict]
            Each dict: ``{"cycle", "length", "total_amount"}``.
        """
        if not graph.is_directed():
            logger.warning("detect_circular_flows requires a directed graph.")
            return []

        cycles_found: List[Dict[str, Any]] = []
        seen_cycles: Set[frozenset] = set()

        try:
            # simple_cycles can be expensive; limit iterations
            cycle_iter = nx.simple_cycles(graph)
            count = 0
            max_cycles = 5000  # safety cap

            for cycle in cycle_iter:
                count += 1
                if count > max_cycles:
                    logger.warning(
                        "Cycle search capped at {max} iterations.", max=max_cycles,
                    )
                    break

                clen = len(cycle)
                if clen < min_cycle_length or clen > max_cycle_length:
                    continue

                # Deduplicate rotations of the same cycle
                canonical = frozenset(cycle)
                if canonical in seen_cycles:
                    continue
                seen_cycles.add(canonical)

                # Sum edge amounts along the cycle
                total_amount = 0.0
                for i in range(clen):
                    u, v = cycle[i], cycle[(i + 1) % clen]
                    edata = graph.get_edge_data(u, v) or {}
                    total_amount += float(edata.get("amount", 0))

                cycles_found.append({
                    "cycle": cycle,
                    "length": clen,
                    "total_amount": round(total_amount, 2),
                })
        except Exception:
            logger.exception("Error during cycle detection.")

        cycles_found.sort(key=lambda c: c["total_amount"], reverse=True)
        logger.info(
            "Circular flows detected  |  cycles={n}", n=len(cycles_found),
        )
        return cycles_found

    # ------------------------------------------------------------------
    # Hub accounts
    # ------------------------------------------------------------------
    def identify_hub_accounts(
        self,
        graph: nx.Graph,
        threshold: int = 5,
    ) -> List[Dict[str, Any]]:
        """Identify bank accounts receiving payments from multiple panchayats.

        A single account linked to many panchayats is suspicious --
        it may belong to a middleman siphoning funds.

        Parameters
        ----------
        graph : nx.Graph   Bipartite or fund-flow graph.
        threshold : int    Minimum number of distinct panchayats.

        Returns
        -------
        list[dict]
            ``{"account_node", "panchayat_count", "panchayats",
            "total_amount", "edge_count"}``.
        """
        ug = graph.to_undirected() if graph.is_directed() else graph
        hubs: List[Dict[str, Any]] = []

        account_nodes = [
            n for n, d in ug.nodes(data=True) if d.get(_NTYPE) == "account"
        ]

        for acc in account_nodes:
            # Collect all panchayats reachable within 3 hops
            panchayats_linked: Set[str] = set()
            total_amount = 0.0
            edge_count = 0

            for neighbour in ug.neighbors(acc):
                ndata = ug.nodes[neighbour]
                if ndata.get(_NTYPE) == "panchayat":
                    panchayats_linked.add(neighbour)
                # Also check second-order neighbours (work -> panchayat)
                for nn in ug.neighbors(neighbour):
                    if ug.nodes[nn].get(_NTYPE) == "panchayat":
                        panchayats_linked.add(nn)

                edata = ug.get_edge_data(acc, neighbour) or {}
                total_amount += float(edata.get("amount", 0))
                edge_count += 1

            if len(panchayats_linked) >= threshold:
                hubs.append({
                    "account_node": acc,
                    "panchayat_count": len(panchayats_linked),
                    "panchayats": sorted(panchayats_linked),
                    "total_amount": round(total_amount, 2),
                    "edge_count": edge_count,
                })

        hubs.sort(key=lambda h: h["panchayat_count"], reverse=True)
        logger.info(
            "Hub accounts identified  |  count={n}  threshold={t}",
            n=len(hubs),
            t=threshold,
        )
        return hubs

    # ------------------------------------------------------------------
    # Centrality scores
    # ------------------------------------------------------------------
    def calculate_centrality_scores(
        self,
        graph: nx.Graph,
    ) -> Dict[str, Dict[str, float]]:
        """Compute multiple centrality metrics for every node.

        Returns
        -------
        dict
            Outer keys: ``"betweenness"``, ``"degree"``, ``"eigenvector"``.
            Each inner dict maps node ID -> centrality score.
        """
        ug = graph.to_undirected() if graph.is_directed() else graph
        if ug.number_of_nodes() == 0:
            return {"betweenness": {}, "degree": {}, "eigenvector": {}}

        betweenness = nx.betweenness_centrality(ug)
        degree = nx.degree_centrality(ug)

        try:
            eigenvector = nx.eigenvector_centrality(ug, max_iter=500)
        except nx.PowerIterationFailedConvergence:
            logger.warning("Eigenvector centrality did not converge; using zeros.")
            eigenvector = {n: 0.0 for n in ug.nodes()}

        scores = {
            "betweenness": {k: round(v, 6) for k, v in betweenness.items()},
            "degree": {k: round(v, 6) for k, v in degree.items()},
            "eigenvector": {k: round(v, 6) for k, v in eigenvector.items()},
        }
        logger.info(
            "Centrality scores computed  |  nodes={n}  metrics=3",
            n=ug.number_of_nodes(),
        )
        return scores

    # ------------------------------------------------------------------
    # Rapid fund movement
    # ------------------------------------------------------------------
    def detect_rapid_fund_movement(
        self,
        payments: List[Dict[str, Any]],
        time_window_hours: int = 24,
    ) -> List[Dict[str, Any]]:
        """Detect funds moving through multiple accounts within a short
        time window.

        If the same ``fto_id`` results in credits to multiple accounts
        within *time_window_hours*, it is flagged.

        Parameters
        ----------
        payments : list[dict]
            Each dict: ``"payment_id"``, ``"fto_id"``, ``"account_no"``,
            ``"amount"``, ``"credit_date"`` (ISO format or datetime).
        time_window_hours : int

        Returns
        -------
        list[dict]
            Each flagged movement group with ``"fto_id"``, ``"accounts"``,
            ``"total_amount"``, ``"time_span_hours"``.
        """
        # Group payments by FTO
        fto_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for p in payments:
            fto_id = p.get("fto_id")
            if fto_id is None:
                continue
            fto_groups[str(fto_id)].append(p)

        flagged: List[Dict[str, Any]] = []
        window = timedelta(hours=time_window_hours)

        for fto_id, group in fto_groups.items():
            if len(group) < 2:
                continue

            # Parse dates
            dated: List[Tuple[datetime, Dict[str, Any]]] = []
            for p in group:
                cd = p.get("credit_date")
                if cd is None:
                    continue
                if isinstance(cd, str):
                    try:
                        dt = datetime.fromisoformat(cd)
                    except ValueError:
                        continue
                elif isinstance(cd, datetime):
                    dt = cd
                else:
                    continue
                dated.append((dt, p))

            if len(dated) < 2:
                continue

            dated.sort(key=lambda x: x[0])
            earliest = dated[0][0]
            latest = dated[-1][0]
            span = latest - earliest

            if span <= window:
                accounts = list({str(d[1].get("account_no")) for d in dated})
                if len(accounts) >= 2:
                    total = sum(float(d[1].get("amount", 0)) for d in dated)
                    flagged.append({
                        "fto_id": fto_id,
                        "accounts": accounts,
                        "n_accounts": len(accounts),
                        "total_amount": round(total, 2),
                        "time_span_hours": round(span.total_seconds() / 3600, 2),
                        "n_payments": len(dated),
                    })

        flagged.sort(key=lambda f: f["total_amount"], reverse=True)
        logger.info(
            "Rapid fund movement  |  flagged_ftos={n}  window={w}h",
            n=len(flagged),
            w=time_window_hours,
        )
        return flagged

    # ------------------------------------------------------------------
    # Visualisation export
    # ------------------------------------------------------------------
    def generate_network_visualization(
        self,
        graph: nx.Graph,
        anomalous_nodes: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Generate a JSON-serialisable representation of the graph for
        frontend rendering (e.g. D3.js / Cytoscape.js).

        Parameters
        ----------
        graph : nx.Graph
        anomalous_nodes : list[str] | None
            Node IDs to highlight as suspicious.

        Returns
        -------
        dict   ``{"nodes": [...], "edges": [...], "stats": {...}}``
        """
        anomalous_set = set(anomalous_nodes or [])

        # Node type -> colour mapping
        _colour_map = {
            "worker": "#4CAF50",
            "work": "#2196F3",
            "account": "#FF9800",
            "panchayat": "#9C27B0",
            "fto": "#607D8B",
        }
        _anomaly_colour = "#F44336"

        nodes: List[Dict[str, Any]] = []
        for nid, ndata in graph.nodes(data=True):
            ntype = ndata.get(_NTYPE, "unknown")
            colour = _anomaly_colour if nid in anomalous_set else _colour_map.get(ntype, "#999")
            nodes.append({
                "id": nid,
                "type": ntype,
                "label": ndata.get("name", ndata.get("work_name", nid)),
                "color": colour,
                "is_anomalous": nid in anomalous_set,
                "size": max(5, min(30, graph.degree(nid) * 2)),
            })

        edges: List[Dict[str, Any]] = []
        for u, v, edata in graph.edges(data=True):
            edges.append({
                "source": u,
                "target": v,
                "type": edata.get(_ETYPE, "unknown"),
                "amount": edata.get("amount", 0),
                "label": edata.get(_ETYPE, ""),
            })

        stats = {
            "total_nodes": graph.number_of_nodes(),
            "total_edges": graph.number_of_edges(),
            "anomalous_nodes": len(anomalous_set & set(graph.nodes())),
            "density": round(nx.density(graph), 6) if graph.number_of_nodes() > 1 else 0,
        }

        logger.info(
            "Network viz exported  |  nodes={n}  edges={e}  anomalous={a}",
            n=stats["total_nodes"],
            e=stats["total_edges"],
            a=stats["anomalous_nodes"],
        )
        return {"nodes": nodes, "edges": edges, "stats": stats}

    # ------------------------------------------------------------------
    # Investigation sub-graph extraction
    # ------------------------------------------------------------------
    def export_investigation_subgraph(
        self,
        graph: nx.Graph,
        suspect_nodes: List[str],
        radius: int = 2,
    ) -> Dict[str, Any]:
        """Extract a sub-graph around suspect nodes for focused investigation.

        Parameters
        ----------
        graph : nx.Graph
        suspect_nodes : list[str]
            Node IDs to centre the extraction around.
        radius : int
            Number of hops from each suspect node to include.

        Returns
        -------
        dict
            Same format as ``generate_network_visualization`` but limited
            to the sub-graph, plus ``"suspect_nodes"`` list.
        """
        ug = graph.to_undirected() if graph.is_directed() else graph
        relevant: Set[str] = set()

        for snode in suspect_nodes:
            if snode not in ug:
                logger.warning("Suspect node '{s}' not found in graph.", s=snode)
                continue
            # BFS to radius hops
            neighbours = nx.single_source_shortest_path_length(ug, snode, cutoff=radius)
            relevant.update(neighbours.keys())

        if not relevant:
            logger.warning("No relevant nodes found for suspect list.")
            return {"nodes": [], "edges": [], "stats": {}, "suspect_nodes": suspect_nodes}

        subgraph = graph.subgraph(relevant).copy()
        viz = self.generate_network_visualization(subgraph, anomalous_nodes=suspect_nodes)
        viz["suspect_nodes"] = suspect_nodes
        viz["radius"] = radius

        logger.info(
            "Investigation subgraph  |  suspects={s}  radius={r}  "
            "subgraph_nodes={n}  subgraph_edges={e}",
            s=len(suspect_nodes),
            r=radius,
            n=subgraph.number_of_nodes(),
            e=subgraph.number_of_edges(),
        )
        return viz
