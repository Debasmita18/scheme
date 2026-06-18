"""
Investigation Report Generator
================================

Produces structured intelligence reports for MGNREGA fraud investigations
in multiple formats:

    - District intelligence report (comprehensive)
    - Individual case file
    - Weekly briefing for District Programme Coordinator (DPC)
    - HTML rendered report via Jinja2
    - CAG (Comptroller and Auditor General) audit format

All monetary amounts are formatted in Indian numbering convention
(lakhs and crores).
"""

from __future__ import annotations

import math
from datetime import datetime, date
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from jinja2 import Environment, BaseLoader
from loguru import logger


# ---------------------------------------------------------------------------
# Indian currency formatting helpers
# ---------------------------------------------------------------------------

def _format_indian_number(value: float) -> str:
    """Format a number using the Indian numbering system (lakhs, crores).

    Examples:
        1234       -> '1,234'
        123456     -> '1,23,456'
        12345678   -> '1,23,45,678'
    """
    if value < 0:
        return "-" + _format_indian_number(-value)
    int_part = int(value)
    decimal_part = value - int_part

    s = str(int_part)
    if len(s) <= 3:
        formatted = s
    else:
        # Last three digits
        last3 = s[-3:]
        remaining = s[:-3]
        # Group remaining digits in pairs from the right
        groups: list[str] = []
        while len(remaining) > 2:
            groups.append(remaining[-2:])
            remaining = remaining[:-2]
        if remaining:
            groups.append(remaining)
        groups.reverse()
        formatted = ",".join(groups) + "," + last3

    if decimal_part > 0.005:
        return formatted + f".{round(decimal_part * 100):02d}"
    return formatted


def _format_inr(value: float) -> str:
    """Format as Indian Rupees with the Rs symbol."""
    return f"Rs {_format_indian_number(value)}"


def _to_lakhs(value: float) -> float:
    """Convert raw amount to lakhs."""
    return round(value / 100_000, 2)


def _to_crores(value: float) -> float:
    """Convert raw amount to crores."""
    return round(value / 10_000_000, 2)


def _human_amount(value: float) -> str:
    """Express amount in lakhs or crores for readability."""
    abs_val = abs(value)
    if abs_val >= 10_000_000:
        return f"Rs {_to_crores(value)} Cr"
    if abs_val >= 100_000:
        return f"Rs {_to_lakhs(value)} L"
    return _format_inr(value)


# ---------------------------------------------------------------------------
# Inline Jinja2 HTML templates
# ---------------------------------------------------------------------------

_DISTRICT_REPORT_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>District Intelligence Report - {{ district_id }} ({{ fin_year }})</title>
<style>
  body { font-family: 'Segoe UI', Arial, sans-serif; margin: 2rem; color: #222; }
  h1 { color: #1a237e; border-bottom: 3px solid #1a237e; padding-bottom: .4rem; }
  h2 { color: #283593; margin-top: 2rem; }
  h3 { color: #3949ab; }
  table { border-collapse: collapse; width: 100%; margin: 1rem 0; }
  th, td { border: 1px solid #bdbdbd; padding: .5rem .75rem; text-align: left; }
  th { background: #e8eaf6; }
  tr:nth-child(even) { background: #f5f5f5; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 4px;
           font-size: .85rem; font-weight: 600; }
  .critical { background: #ffcdd2; color: #b71c1c; }
  .high { background: #ffe0b2; color: #e65100; }
  .medium { background: #fff9c4; color: #f57f17; }
  .low { background: #c8e6c9; color: #2e7d32; }
  .summary-box { background: #e3f2fd; padding: 1rem 1.5rem; border-radius: 8px;
                 margin: 1rem 0; }
  .metric { font-size: 1.4rem; font-weight: bold; color: #0d47a1; }
  footer { margin-top: 3rem; font-size: .8rem; color: #757575;
           border-top: 1px solid #ccc; padding-top: .5rem; }
</style>
</head>
<body>
<h1>MGNREGA Fraud Intelligence Report</h1>
<p><strong>District:</strong> {{ district_id }} &nbsp;|&nbsp;
   <strong>Financial Year:</strong> {{ fin_year }} &nbsp;|&nbsp;
   <strong>Generated:</strong> {{ generated_at }}</p>

<div class="summary-box">
  <h2>Executive Summary</h2>
  <p>Total works analysed: <span class="metric">{{ summary.total_works }}</span></p>
  <p>Satellite-verified: <span class="metric">{{ summary.verified_count }}</span>
     ({{ summary.verified_pct }}%)</p>
  <p>Flagged for investigation: <span class="metric">{{ summary.flagged_count }}</span>
     <span class="badge {{ summary.risk_css }}">{{ summary.risk_level }}</span></p>
  <p>Estimated leakage: <span class="metric">{{ summary.estimated_leakage }}</span>
     ({{ summary.leakage_pct }}% of total expenditure)</p>
</div>

{% if top_anomalies %}
<h2>Top Anomalies</h2>
<table>
  <tr><th>#</th><th>Description</th><th>Severity</th><th>Amount</th><th>Location</th></tr>
  {% for a in top_anomalies %}
  <tr>
    <td>{{ loop.index }}</td>
    <td>{{ a.description }}</td>
    <td><span class="badge {{ a.severity_css }}">{{ a.severity }}</span></td>
    <td>{{ a.amount_display }}</td>
    <td>{{ a.location }}</td>
  </tr>
  {% endfor %}
</table>
{% endif %}

{% if satellite_results %}
<h2>Satellite Verification Results</h2>
<table>
  <tr><th>Work ID</th><th>Work Name</th><th>Reported</th><th>Detected</th><th>Deviation</th><th>Status</th></tr>
  {% for s in satellite_results %}
  <tr>
    <td>{{ s.work_id }}</td>
    <td>{{ s.work_name }}</td>
    <td>{{ s.reported }}</td>
    <td>{{ s.detected }}</td>
    <td>{{ s.deviation }}</td>
    <td><span class="badge {{ s.status_css }}">{{ s.status }}</span></td>
  </tr>
  {% endfor %}
</table>
{% endif %}

{% if muster_findings %}
<h2>Muster Roll Forensics</h2>
<ul>
{% for f in muster_findings %}
  <li>{{ f }}</li>
{% endfor %}
</ul>
{% endif %}

{% if network_patterns %}
<h2>Payment Network Suspicious Patterns</h2>
<ul>
{% for p in network_patterns %}
  <li>{{ p }}</li>
{% endfor %}
</ul>
{% endif %}

{% if recommendations %}
<h2>Recommendations</h2>
<ol>
{% for r in recommendations %}
  <li>{{ r }}</li>
{% endfor %}
</ol>
{% endif %}

<footer>
  Auto-generated by MGNREGA Verification & Fraud Intelligence System.
  Classification: RESTRICTED. For official use only.
</footer>
</body>
</html>
"""

_CASE_FILE_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Case File - {{ case_id }}</title>
<style>
  body { font-family: 'Segoe UI', Arial, sans-serif; margin: 2rem; color: #222; }
  h1 { color: #b71c1c; }
  h2 { color: #c62828; }
  table { border-collapse: collapse; width: 100%; margin: 1rem 0; }
  th, td { border: 1px solid #bdbdbd; padding: .5rem; text-align: left; }
  th { background: #ffebee; }
  .evidence { background: #fff3e0; padding: .75rem; border-left: 4px solid #ff9800;
              margin: .5rem 0; }
  footer { margin-top: 2rem; font-size: .8rem; color: #757575; }
</style>
</head>
<body>
<h1>Investigation Case File</h1>
<p><strong>Case ID:</strong> {{ case_id }} &nbsp;|&nbsp;
   <strong>Status:</strong> {{ status }} &nbsp;|&nbsp;
   <strong>Created:</strong> {{ created_at }}</p>

<h2>Subject</h2>
<p>{{ subject_description }}</p>

<h2>Evidence Chain</h2>
{% for e in evidence_chain %}
<div class="evidence">
  <p><strong>{{ e.type }}</strong> ({{ e.date }})</p>
  <p>{{ e.detail }}</p>
  {% if e.reference %}<p><em>Ref: {{ e.reference }}</em></p>{% endif %}
</div>
{% endfor %}

{% if financials %}
<h2>Financial Summary</h2>
<table>
  <tr><th>Item</th><th>Amount</th></tr>
  {% for key, val in financials.items() %}
  <tr><td>{{ key }}</td><td>{{ val }}</td></tr>
  {% endfor %}
</table>
{% endif %}

<footer>
  MGNREGA Fraud Intelligence System - Case File.
  Classification: CONFIDENTIAL.
</footer>
</body>
</html>
"""

_WEEKLY_BRIEFING_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Weekly Briefing - {{ district_id }} ({{ week_label }})</title>
<style>
  body { font-family: 'Segoe UI', Arial, sans-serif; margin: 2rem; }
  h1 { color: #1565c0; }
  .kpi { display: inline-block; text-align: center; padding: 1rem;
         margin: .5rem; background: #e3f2fd; border-radius: 8px; min-width: 150px; }
  .kpi-value { font-size: 1.6rem; font-weight: bold; color: #0d47a1; }
  .kpi-label { font-size: .85rem; color: #555; }
  table { border-collapse: collapse; width: 100%; margin-top: 1rem; }
  th, td { border: 1px solid #ccc; padding: .4rem .6rem; }
  th { background: #bbdefb; }
  footer { margin-top: 2rem; font-size: .8rem; color: #9e9e9e; }
</style>
</head>
<body>
<h1>Weekly Intelligence Briefing</h1>
<p>{{ district_id }} | {{ week_label }} | Generated {{ generated_at }}</p>

<div>
{% for kpi in kpis %}
  <div class="kpi">
    <div class="kpi-value">{{ kpi.value }}</div>
    <div class="kpi-label">{{ kpi.label }}</div>
  </div>
{% endfor %}
</div>

{% if alerts %}
<h2>Priority Alerts</h2>
<table>
  <tr><th>Alert</th><th>Severity</th><th>Action Required</th></tr>
  {% for a in alerts %}
  <tr>
    <td>{{ a.message }}</td>
    <td>{{ a.severity }}</td>
    <td>{{ a.action }}</td>
  </tr>
  {% endfor %}
</table>
{% endif %}

{% if progress %}
<h2>Verification Progress</h2>
<table>
  <tr><th>Block</th><th>Total Works</th><th>Verified</th><th>Flagged</th><th>Pending</th></tr>
  {% for b in progress %}
  <tr>
    <td>{{ b.block }}</td>
    <td>{{ b.total }}</td>
    <td>{{ b.verified }}</td>
    <td>{{ b.flagged }}</td>
    <td>{{ b.pending }}</td>
  </tr>
  {% endfor %}
</table>
{% endif %}

<footer>
  Prepared for the District Programme Coordinator.
  MGNREGA Fraud Intelligence System.
</footer>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Report Generator
# ---------------------------------------------------------------------------

class ReportGenerator:
    """Generate investigation reports for the MGNREGA verification system.

    Reports can be emitted as structured dicts (for JSON APIs) or
    rendered as HTML via Jinja2 templates.
    """

    def __init__(self) -> None:
        self._env = Environment(loader=BaseLoader(), autoescape=True)
        # Register custom filters
        self._env.filters["inr"] = _format_inr
        self._env.filters["human_amount"] = _human_amount
        self._env.filters["indian_number"] = _format_indian_number
        logger.info("ReportGenerator initialised.")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _severity_css(severity: str) -> str:
        return {
            "CRITICAL": "critical",
            "HIGH": "high",
            "MEDIUM": "medium",
            "LOW": "low",
        }.get(severity.upper(), "low")

    @staticmethod
    def _now_str() -> str:
        return datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    # ------------------------------------------------------------------
    # District report
    # ------------------------------------------------------------------
    def generate_district_report(
        self,
        district_id: str,
        fin_year: str,
        anomalies: List[Dict[str, Any]],
        verifications: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Generate a comprehensive district intelligence report.

        Parameters
        ----------
        district_id : str
            District code or name.
        fin_year : str
            Financial year label (e.g. ``"2024-25"``).
        anomalies : list[dict]
            Each dict: ``"description"``, ``"severity"`` (CRITICAL/HIGH/
            MEDIUM/LOW), ``"amount"`` (float), ``"location"`` (str),
            ``"work_id"`` (optional).
        verifications : list[dict]
            Each dict: ``"work_id"``, ``"work_name"``, ``"reported_value"``,
            ``"detected_value"``, ``"deviation_pct"``, ``"status"``
            (VERIFIED / DISCREPANT / UNVERIFIABLE).

        Returns
        -------
        dict   Structured report data suitable for ``generate_html_report``.
        """
        total_works = len(verifications)
        verified = [v for v in verifications if v.get("status") == "VERIFIED"]
        flagged = [v for v in verifications if v.get("status") == "DISCREPANT"]
        verified_pct = round(100 * len(verified) / max(total_works, 1), 1)

        # Estimated leakage = sum of discrepancy amounts
        total_expenditure = sum(
            float(v.get("reported_value", 0)) for v in verifications
        )
        leakage_amount = sum(
            abs(float(v.get("reported_value", 0)) - float(v.get("detected_value", 0)))
            for v in flagged
        )
        leakage_pct = round(100 * leakage_amount / max(total_expenditure, 1), 2)

        # Determine overall risk level
        if leakage_pct > 20 or len(flagged) > total_works * 0.3:
            risk_level = "CRITICAL"
        elif leakage_pct > 10:
            risk_level = "HIGH"
        elif leakage_pct > 5:
            risk_level = "MEDIUM"
        else:
            risk_level = "LOW"

        # Sort anomalies by severity then amount
        severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
        sorted_anomalies = sorted(
            anomalies,
            key=lambda a: (
                severity_order.get(a.get("severity", "LOW").upper(), 4),
                -float(a.get("amount", 0)),
            ),
        )

        # Build top anomalies for template
        top_anomalies = []
        for a in sorted_anomalies[:20]:
            sev = a.get("severity", "LOW").upper()
            top_anomalies.append({
                "description": a.get("description", ""),
                "severity": sev,
                "severity_css": self._severity_css(sev),
                "amount_display": _human_amount(float(a.get("amount", 0))),
                "location": a.get("location", "N/A"),
            })

        # Satellite results
        satellite_results = []
        for v in verifications:
            status = v.get("status", "UNVERIFIABLE")
            satellite_results.append({
                "work_id": v.get("work_id", ""),
                "work_name": v.get("work_name", ""),
                "reported": _human_amount(float(v.get("reported_value", 0))),
                "detected": _human_amount(float(v.get("detected_value", 0))),
                "deviation": f"{v.get('deviation_pct', 0)}%",
                "status": status,
                "status_css": self._severity_css(
                    "CRITICAL" if status == "DISCREPANT" else "LOW"
                ),
            })

        # Muster roll findings (derive from anomalies of type 'muster')
        muster_findings = [
            a["description"]
            for a in sorted_anomalies
            if "muster" in a.get("description", "").lower()
               or "attendance" in a.get("description", "").lower()
        ]

        # Network patterns
        network_patterns = [
            a["description"]
            for a in sorted_anomalies
            if "network" in a.get("description", "").lower()
               or "circular" in a.get("description", "").lower()
               or "hub account" in a.get("description", "").lower()
        ]

        # Recommendations
        recommendations = self._generate_recommendations(
            risk_level, leakage_pct, len(flagged), anomalies,
        )

        report_data: Dict[str, Any] = {
            "template": "district_report",
            "district_id": district_id,
            "fin_year": fin_year,
            "generated_at": self._now_str(),
            "summary": {
                "total_works": total_works,
                "verified_count": len(verified),
                "verified_pct": verified_pct,
                "flagged_count": len(flagged),
                "risk_level": risk_level,
                "risk_css": self._severity_css(risk_level),
                "estimated_leakage": _human_amount(leakage_amount),
                "leakage_pct": leakage_pct,
                "total_expenditure": _human_amount(total_expenditure),
            },
            "top_anomalies": top_anomalies,
            "satellite_results": satellite_results,
            "muster_findings": muster_findings,
            "network_patterns": network_patterns,
            "recommendations": recommendations,
        }

        logger.info(
            "District report generated  |  district={d}  year={y}  "
            "risk={r}  leakage={l}",
            d=district_id,
            y=fin_year,
            r=risk_level,
            l=_human_amount(leakage_amount),
        )
        return report_data

    @staticmethod
    def _generate_recommendations(
        risk_level: str,
        leakage_pct: float,
        flagged_count: int,
        anomalies: List[Dict[str, Any]],
    ) -> List[str]:
        """Produce context-aware recommendations based on findings."""
        recs: List[str] = []

        if risk_level in ("CRITICAL", "HIGH"):
            recs.append(
                "Initiate immediate field verification of all CRITICAL and "
                "HIGH severity works with a joint team of engineers and "
                "social audit staff."
            )
        if leakage_pct > 10:
            recs.append(
                f"Estimated leakage rate of {leakage_pct}% exceeds acceptable "
                f"threshold. Recommend freezing new sanctions in affected "
                f"blocks pending investigation."
            )
        if flagged_count > 0:
            recs.append(
                f"{flagged_count} works show satellite-detected discrepancies. "
                f"Cross-verify with physical measurement books and geo-tagged "
                f"photographs."
            )
        # Check for specific anomaly types
        has_attendance = any(
            "attendance" in a.get("description", "").lower() for a in anomalies
        )
        has_network = any(
            "network" in a.get("description", "").lower()
            or "circular" in a.get("description", "").lower()
            for a in anomalies
        )
        if has_attendance:
            recs.append(
                "Attendance clone patterns detected. Conduct biometric "
                "re-verification of flagged workers at the worksite."
            )
        if has_network:
            recs.append(
                "Suspicious payment network patterns found. Refer hub "
                "accounts and circular fund flows to the Vigilance cell "
                "for forensic audit."
            )
        if not recs:
            recs.append(
                "No critical issues identified. Continue routine monitoring "
                "and quarterly satellite verification."
            )
        return recs

    # ------------------------------------------------------------------
    # Case file
    # ------------------------------------------------------------------
    def generate_case_file(
        self,
        case_id: str,
        evidence_chain: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Generate an individual investigation case file.

        Parameters
        ----------
        case_id : str
            Unique case identifier.
        evidence_chain : list[dict]
            Ordered list of evidence items.  Each dict:
            ``"type"`` (str), ``"date"`` (str), ``"detail"`` (str),
            ``"reference"`` (str|None), ``"amount"`` (float|None).

        Returns
        -------
        dict   Structured case data.
        """
        total_amount = sum(
            float(e.get("amount", 0)) for e in evidence_chain if e.get("amount")
        )

        # Build financials summary
        financials: Dict[str, str] = {}
        for e in evidence_chain:
            if e.get("amount"):
                label = e.get("type", "Unknown")
                financials[label] = _human_amount(float(e["amount"]))
        financials["Total Involved"] = _human_amount(total_amount)

        subject_parts = [e.get("detail", "") for e in evidence_chain[:2]]
        subject = "; ".join(subject_parts) if subject_parts else "Under investigation"

        report_data: Dict[str, Any] = {
            "template": "case_file",
            "case_id": case_id,
            "status": "OPEN",
            "created_at": self._now_str(),
            "subject_description": subject,
            "evidence_chain": evidence_chain,
            "financials": financials,
            "total_amount": total_amount,
            "total_amount_display": _human_amount(total_amount),
        }

        logger.info(
            "Case file generated  |  case={c}  evidence_items={n}  "
            "total_amount={a}",
            c=case_id,
            n=len(evidence_chain),
            a=_human_amount(total_amount),
        )
        return report_data

    # ------------------------------------------------------------------
    # Weekly briefing
    # ------------------------------------------------------------------
    def generate_weekly_briefing(
        self,
        district_id: str,
        week_ending: Optional[str] = None,
        block_progress: Optional[List[Dict[str, Any]]] = None,
        alerts: Optional[List[Dict[str, Any]]] = None,
        kpi_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Generate a weekly briefing for the District Programme Coordinator.

        Parameters
        ----------
        district_id : str
        week_ending : str | None
            ISO date string.  Defaults to today.
        block_progress : list[dict] | None
            Per-block verification progress.  Each dict:
            ``"block"``, ``"total"``, ``"verified"``, ``"flagged"``, ``"pending"``.
        alerts : list[dict] | None
            Priority alerts.  Each dict:
            ``"message"``, ``"severity"``, ``"action"``.
        kpi_data : dict | None
            Key performance indicators.  Expected keys:
            ``"works_verified_this_week"``, ``"new_flags"``,
            ``"leakage_estimate"``, ``"verification_rate"``.

        Returns
        -------
        dict   Structured briefing data.
        """
        if week_ending is None:
            week_ending = date.today().isoformat()

        week_label = f"Week ending {week_ending}"

        # Default KPIs
        kpi_data = kpi_data or {}
        kpis = [
            {
                "label": "Works Verified This Week",
                "value": str(kpi_data.get("works_verified_this_week", 0)),
            },
            {
                "label": "New Flags Raised",
                "value": str(kpi_data.get("new_flags", 0)),
            },
            {
                "label": "Est. Leakage (Cumulative)",
                "value": _human_amount(float(kpi_data.get("leakage_estimate", 0))),
            },
            {
                "label": "Verification Rate",
                "value": f"{kpi_data.get('verification_rate', 0)}%",
            },
        ]

        report_data: Dict[str, Any] = {
            "template": "weekly_briefing",
            "district_id": district_id,
            "week_label": week_label,
            "generated_at": self._now_str(),
            "kpis": kpis,
            "alerts": alerts or [],
            "progress": block_progress or [],
        }

        logger.info(
            "Weekly briefing generated  |  district={d}  week={w}",
            d=district_id,
            w=week_label,
        )
        return report_data

    # ------------------------------------------------------------------
    # HTML rendering
    # ------------------------------------------------------------------
    def generate_html_report(
        self,
        report_data: Dict[str, Any],
        template_name: Optional[str] = None,
    ) -> str:
        """Render a report dict as HTML using inline Jinja2 templates.

        Parameters
        ----------
        report_data : dict
            Output from ``generate_district_report``, ``generate_case_file``,
            or ``generate_weekly_briefing``.
        template_name : str | None
            ``"district_report"``, ``"case_file"``, or ``"weekly_briefing"``.
            Auto-detected from ``report_data["template"]`` if not provided.

        Returns
        -------
        str   Rendered HTML.
        """
        tname = template_name or report_data.get("template", "district_report")
        template_map = {
            "district_report": _DISTRICT_REPORT_TEMPLATE,
            "case_file": _CASE_FILE_TEMPLATE,
            "weekly_briefing": _WEEKLY_BRIEFING_TEMPLATE,
        }

        template_str = template_map.get(tname)
        if template_str is None:
            raise ValueError(
                f"Unknown template '{tname}'.  "
                f"Available: {list(template_map.keys())}"
            )

        template = self._env.from_string(template_str)
        html = template.render(**report_data)
        logger.info(
            "HTML report rendered  |  template={t}  length={l} chars",
            t=tname,
            l=len(html),
        )
        return html

    # ------------------------------------------------------------------
    # CAG audit format
    # ------------------------------------------------------------------
    def generate_cag_format(
        self,
        report_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Format report data per Comptroller and Auditor General (CAG)
        audit standards.

        The CAG format organises findings into:
            - Para number (sequential)
            - Observation
            - Financial implication
            - Reply of the department (placeholder)
            - Audit recommendation

        Parameters
        ----------
        report_data : dict
            Output from ``generate_district_report``.

        Returns
        -------
        dict   CAG-formatted report.
        """
        paras: List[Dict[str, Any]] = []
        para_no = 1

        summary = report_data.get("summary", {})
        top_anomalies = report_data.get("top_anomalies", [])
        satellite_results = report_data.get("satellite_results", [])
        recommendations = report_data.get("recommendations", [])

        # Executive observation para
        paras.append({
            "para_no": f"{para_no}.",
            "heading": "Executive Observation",
            "observation": (
                f"Audit of {summary.get('total_works', 0)} MGNREGA works in "
                f"district {report_data.get('district_id', 'N/A')} for FY "
                f"{report_data.get('fin_year', 'N/A')} revealed that "
                f"{summary.get('flagged_count', 0)} works "
                f"({summary.get('leakage_pct', 0)}% of total expenditure "
                f"{summary.get('total_expenditure', 'N/A')}) showed "
                f"discrepancies upon satellite verification."
            ),
            "financial_implication": summary.get("estimated_leakage", "N/A"),
            "department_reply": "[Awaiting reply]",
            "recommendation": recommendations[0] if recommendations else "N/A",
        })
        para_no += 1

        # One para per top anomaly
        for anomaly in top_anomalies[:10]:
            paras.append({
                "para_no": f"{para_no}.",
                "heading": f"Anomaly - {anomaly.get('severity', 'N/A')} Severity",
                "observation": anomaly.get("description", ""),
                "financial_implication": anomaly.get("amount_display", "N/A"),
                "department_reply": "[Awaiting reply]",
                "recommendation": (
                    "Field verification and cross-check with measurement book "
                    "recommended."
                ),
            })
            para_no += 1

        # Satellite verification paras for discrepant works
        discrepant = [s for s in satellite_results if s.get("status") == "DISCREPANT"]
        if discrepant:
            paras.append({
                "para_no": f"{para_no}.",
                "heading": "Satellite Verification Discrepancies",
                "observation": (
                    f"{len(discrepant)} works showed significant deviation "
                    f"between reported and satellite-detected measurements."
                ),
                "financial_implication": "See individual work details above.",
                "department_reply": "[Awaiting reply]",
                "recommendation": (
                    "Conduct joint physical verification with GPS coordinates "
                    "and photographic evidence."
                ),
            })
            para_no += 1

        cag_report: Dict[str, Any] = {
            "format": "CAG_AUDIT",
            "report_title": (
                f"Audit Report on MGNREGA Works - "
                f"{report_data.get('district_id', '')} "
                f"({report_data.get('fin_year', '')})"
            ),
            "audit_authority": "Comptroller and Auditor General of India",
            "generated_at": self._now_str(),
            "district_id": report_data.get("district_id", ""),
            "fin_year": report_data.get("fin_year", ""),
            "total_paras": len(paras),
            "paras": paras,
            "summary": summary,
        }

        logger.info(
            "CAG format report generated  |  paras={p}", p=len(paras),
        )
        return cag_report

    # ------------------------------------------------------------------
    # Leakage estimation
    # ------------------------------------------------------------------
    def calculate_leakage_estimate(
        self,
        district_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Estimate total leakage with confidence intervals.

        Uses sampled verification results to extrapolate district-wide
        leakage using ratio estimation.

        Parameters
        ----------
        district_data : dict
            Expected keys:
            ``"total_expenditure"``   : float
            ``"verified_works"``      : list of dicts with ``"reported"``
                                        and ``"detected"`` amounts
            ``"total_works_count"``   : int

        Returns
        -------
        dict
            ``"point_estimate"``, ``"lower_bound"``, ``"upper_bound"``,
            ``"confidence_level"``, ``"methodology"``,
            ``"sample_leakage_rate"``.
        """
        total_exp = float(district_data.get("total_expenditure", 0))
        verified = district_data.get("verified_works", [])
        total_works = int(district_data.get("total_works_count", 1))

        if not verified or total_exp == 0:
            return {
                "point_estimate": _human_amount(0),
                "point_estimate_raw": 0,
                "lower_bound": _human_amount(0),
                "upper_bound": _human_amount(0),
                "confidence_level": "N/A",
                "methodology": "Insufficient data for estimation.",
                "sample_leakage_rate": 0,
            }

        # Compute per-work leakage in the sample
        leakages: List[float] = []
        for v in verified:
            rep = float(v.get("reported", 0))
            det = float(v.get("detected", 0))
            if rep > 0:
                leakages.append(max(0, rep - det))

        if not leakages:
            leakage_arr = np.array([0.0])
        else:
            leakage_arr = np.array(leakages, dtype=np.float64)

        sample_total_reported = sum(
            float(v.get("reported", 0)) for v in verified
        )
        sample_total_leakage = float(leakage_arr.sum())
        sample_rate = (
            sample_total_leakage / sample_total_reported
            if sample_total_reported > 0 else 0.0
        )

        # Point estimate via ratio extrapolation
        point_est = sample_rate * total_exp

        # Confidence interval using bootstrap-style standard error
        n = len(leakage_arr)
        std_err = float(leakage_arr.std(ddof=1)) / math.sqrt(max(n, 1)) if n > 1 else 0
        # Scale to population
        scaling = total_works / max(n, 1)
        margin = 1.96 * std_err * scaling  # 95% CI

        lower = max(0, point_est - margin)
        upper = point_est + margin

        result: Dict[str, Any] = {
            "point_estimate": _human_amount(point_est),
            "point_estimate_raw": round(point_est, 2),
            "lower_bound": _human_amount(lower),
            "lower_bound_raw": round(lower, 2),
            "upper_bound": _human_amount(upper),
            "upper_bound_raw": round(upper, 2),
            "confidence_level": "95%",
            "methodology": (
                f"Ratio estimation based on {n} verified works out of "
                f"{total_works} total. Sample leakage rate: "
                f"{round(sample_rate * 100, 2)}%."
            ),
            "sample_leakage_rate": round(sample_rate, 4),
            "sample_size": n,
            "total_works": total_works,
        }

        logger.info(
            "Leakage estimate  |  point={pe}  CI=[{lo}, {hi}]  rate={r:.2%}",
            pe=result["point_estimate"],
            lo=result["lower_bound"],
            hi=result["upper_bound"],
            r=sample_rate,
        )
        return result

    # ------------------------------------------------------------------
    # Period comparison
    # ------------------------------------------------------------------
    def generate_comparison_stats(
        self,
        district_id: str,
        previous_period: Dict[str, Any],
        current_period: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Generate period-over-period comparison statistics.

        Parameters
        ----------
        district_id : str
        previous_period : dict
            ``"label"`` (str), ``"total_expenditure"`` (float),
            ``"total_works"`` (int), ``"flagged_works"`` (int),
            ``"leakage_estimate"`` (float), ``"risk_score"`` (float).
        current_period : dict
            Same keys as *previous_period*.

        Returns
        -------
        dict   Comparison metrics with deltas and trend indicators.
        """
        def _delta(curr: float, prev: float) -> Dict[str, Any]:
            diff = curr - prev
            if prev != 0:
                pct = round(100 * diff / abs(prev), 2)
            else:
                pct = 100.0 if curr != 0 else 0.0
            trend = "UP" if diff > 0 else "DOWN" if diff < 0 else "FLAT"
            return {
                "current": curr,
                "previous": prev,
                "change": round(diff, 2),
                "change_pct": pct,
                "trend": trend,
            }

        metrics = {}
        for key in ("total_expenditure", "total_works", "flagged_works",
                     "leakage_estimate", "risk_score"):
            curr_val = float(current_period.get(key, 0))
            prev_val = float(previous_period.get(key, 0))
            metrics[key] = _delta(curr_val, prev_val)

        # Flag rate comparison
        curr_flag_rate = (
            float(current_period.get("flagged_works", 0))
            / max(float(current_period.get("total_works", 1)), 1)
        )
        prev_flag_rate = (
            float(previous_period.get("flagged_works", 0))
            / max(float(previous_period.get("total_works", 1)), 1)
        )
        metrics["flag_rate"] = _delta(
            round(curr_flag_rate * 100, 2),
            round(prev_flag_rate * 100, 2),
        )

        # Overall assessment
        leakage_trend = metrics["leakage_estimate"]["trend"]
        if leakage_trend == "UP":
            assessment = (
                "Leakage estimate has INCREASED compared to the previous period. "
                "Recommend enhanced monitoring and investigation."
            )
        elif leakage_trend == "DOWN":
            assessment = (
                "Leakage estimate has DECREASED, indicating improvement. "
                "Continue current monitoring levels."
            )
        else:
            assessment = "Leakage estimate is stable."

        comparison: Dict[str, Any] = {
            "district_id": district_id,
            "previous_label": previous_period.get("label", "Previous"),
            "current_label": current_period.get("label", "Current"),
            "generated_at": self._now_str(),
            "metrics": metrics,
            "assessment": assessment,
            "formatted": {
                "previous_expenditure": _human_amount(
                    float(previous_period.get("total_expenditure", 0))
                ),
                "current_expenditure": _human_amount(
                    float(current_period.get("total_expenditure", 0))
                ),
                "previous_leakage": _human_amount(
                    float(previous_period.get("leakage_estimate", 0))
                ),
                "current_leakage": _human_amount(
                    float(current_period.get("total_expenditure", 0))
                ),
            },
        }

        logger.info(
            "Comparison stats  |  district={d}  prev={pl}  curr={cl}  "
            "leakage_trend={lt}",
            d=district_id,
            pl=comparison["previous_label"],
            cl=comparison["current_label"],
            lt=leakage_trend,
        )
        return comparison
