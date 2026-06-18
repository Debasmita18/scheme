"""
Groq LLM service.
=================

Thin client over Groq's OpenAI-compatible chat API, plus high-level helpers
that turn district / national data into written intelligence products
(case files, briefings). Model and key come from settings / environment.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import httpx
from loguru import logger

from config.settings import get_settings


def is_configured() -> bool:
    return bool(get_settings().groq_api_key)


def model_name() -> str:
    return get_settings().groq_model


async def chat(
    messages: List[Dict[str, str]],
    max_tokens: int = 2600,
    temperature: float = 0.4,
) -> str:
    """Call Groq chat completions and return the assistant text."""
    s = get_settings()
    if not s.groq_api_key:
        raise RuntimeError("GROQ_API_KEY not configured")

    payload = {
        "model": s.groq_model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    async with httpx.AsyncClient(timeout=90) as client:
        r = await client.post(
            f"{s.groq_base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {s.groq_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
    if r.status_code != 200:
        logger.error("Groq error {}: {}", r.status_code, r.text[:300])
        r.raise_for_status()
    data = r.json()
    return data["choices"][0]["message"]["content"].strip()


# ---------------------------------------------------------------------------
# High-level products
# ---------------------------------------------------------------------------
def _fmt_cr(lakhs: Optional[float]) -> str:
    if not lakhs:
        return "NA"
    return f"Rs {lakhs / 100:,.0f} crore"


def _district_facts(d: Dict[str, Any]) -> str:
    return json.dumps({
        "district": d.get("district_name"),
        "state": d.get("state_name"),
        "region": d.get("region"),
        "fin_year": "2025-26",
        "composite_risk_score_0_100": d.get("risk_score"),
        "risk_band": d.get("risk_band"),
        "total_outlay_rs_crore": round((d.get("total_expenditure_lakhs") or 0) / 100, 1),
        "wages_rs_crore": round((d.get("wages_lakhs") or 0) / 100, 1),
        "material_rs_crore": round((d.get("material_lakhs") or 0) / 100, 1),
        "person_days": d.get("person_days"),
        "households": d.get("total_households"),
        "active_workers": d.get("active_workers"),
        "total_works": d.get("total_works"),
        "completed_works": d.get("completed_works"),
        "blocks": d.get("total_blocks"),
        "gram_panchayats": d.get("total_panchayats"),
        "verified_works": d.get("verified_count"),
        "flagged_works": d.get("flagged_count"),
        "anomalies": d.get("anomalies_count"),
        "estimated_leakage_rs_crore": round((d.get("estimated_leakage_lakhs") or 0) / 100, 1),
        "women_participation_pct": d.get("women_participation_pct"),
        "scst_participation_pct": d.get("scst_participation_pct"),
        "avg_wage_rate": d.get("avg_wage_rate"),
        "completion_rate_pct": d.get("completion_rate_pct"),
        "anomaly_by_type": d.get("anomaly_by_type"),
        "works_by_type": d.get("works_by_type"),
        "data_source": d.get("data_source", "modelled"),
    }, ensure_ascii=False, indent=2)


CASE_FILE_SYSTEM = (
    "You are a senior audit analyst at the Ministry of Rural Development, "
    "Government of India, preparing a CAG-format verification case file for an "
    "MGNREGA district. Write precise, formal, evidence-driven prose suitable for "
    "a District Programme Coordinator and CAG auditors. Use ONLY the figures "
    "provided; never invent specific numbers. If a figure is modelled rather than "
    "live, note that limitation once. "
    "Output a clean HTML FRAGMENT only (no <html>, <head> or <body> tags, no "
    "markdown). Use <h2>, <h3>, <p>, <ul>, <li>, <table>, <strong>. "
    "Use plain ASCII punctuation only: write the rupee symbol as 'Rs' (never the "
    "Unicode rupee glyph), use ordinary hyphens '-' (never en/em dashes) and "
    "straight quotes. "
    "Sections: Executive Summary; Financial & Physical Snapshot (a table); "
    "Risk Assessment (interpret the composite score and anomaly mix); "
    "Key Findings & Red Flags; Recommended Verification Actions; "
    "Estimated Exposure & Next Steps."
)


async def generate_case_file_html(d: Dict[str, Any]) -> str:
    facts = _district_facts(d)
    user = (
        f"Prepare the MGNREGA verification case file for {d.get('district_name')}, "
        f"{d.get('state_name')} (FY 2025-26). Structured district data (JSON):\n\n{facts}\n\n"
        "Write the HTML fragment now."
    )
    return await chat(
        [{"role": "system", "content": CASE_FILE_SYSTEM},
         {"role": "user", "content": user}],
        max_tokens=3000,
        temperature=0.45,
    )


REPORT_SYSTEM = (
    "You are a policy analyst at the Ministry of Rural Development, Government of "
    "India. Produce a crisp, formal intelligence report for senior officials using "
    "ONLY the provided figures (never invent specific numbers). Output a clean HTML "
    "FRAGMENT (no <html>/<head>/<body>, no markdown). Use <h2>,<h3>,<p>,<ul>,<li>,"
    "<table>,<strong>. Use plain ASCII punctuation only: write the rupee symbol as "
    "'Rs' (never the Unicode rupee glyph), ordinary hyphens '-' (never en/em dashes) "
    "and straight quotes."
)


async def generate_report_html(title: str, context: Dict[str, Any], brief: str) -> str:
    user = (
        f"Report type: {title}.\n{brief}\n\n"
        f"Data (JSON):\n{json.dumps(context, ensure_ascii=False, indent=2)}\n\n"
        "Write the HTML fragment now."
    )
    return await chat(
        [{"role": "system", "content": REPORT_SYSTEM},
         {"role": "user", "content": user}],
        max_tokens=2800,
        temperature=0.5,
    )
