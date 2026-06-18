"""
Build the complete all-India MGNREGA dataset.
==============================================

This is the single source of truth for the "whole of India" data set that
powers the dashboard when no live database / NREGA scrape is configured.

Input
-----
``backend/data/india_districts.geojson``
    District-level boundaries for all 36 states/UTs (759 districts) with
    official census state codes (``st_code``) and district codes (``dt_code``).
    Source: udit-001/india-maps-data (census 2011 administrative boundaries).

Output (written to ``backend/data/generated/``)
-----------------------------------------------
``india_dataset.json``
    National summary + every state/UT (aggregated) + every district with
    realistic, *deterministically generated* MGNREGA metrics.
``geo_states.json``
    Dissolved + simplified state/UT polygons, risk metrics embedded.
    Drives the national 3D India map.
``geo_districts.json``
    Simplified district polygons, risk metrics embedded.
    Drives state-level drill-down maps.

The metrics are synthetic but deterministic (seeded per district) so the
output is stable across runs and totals land at a realistic national scale
(~Rs 95,000 crore expenditure, ~300 crore person-days).  Wherever a live
data source is wired in later, this file is simply replaced.

Run:
    python -m data_ingestion.build_india_dataset      # from backend/
    python data_ingestion/build_india_dataset.py
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path
from typing import Any, Dict, List, Tuple

from shapely.geometry import shape, mapping
from shapely.ops import unary_union

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_DATA_DIR = _BACKEND_DIR / "data"
_SRC_GEOJSON = _DATA_DIR / "india_districts.geojson"
_OUT_DIR = _DATA_DIR / "generated"
_OUT_DIR.mkdir(parents=True, exist_ok=True)

FIN_YEAR = "2025-2026"

# ---------------------------------------------------------------------------
# State / UT metadata (keyed by census state code)
#   type   : "State" | "UT"
#   region : grouping used for filters / regional roll-ups
#   wage   : approx notified MGNREGA wage rate (Rs/day, FY25-26 ballpark)
# ---------------------------------------------------------------------------
STATE_META: Dict[str, Dict[str, Any]] = {
    "01": {"type": "UT", "region": "North", "wage": 259, "abbr": "JK"},      # Jammu & Kashmir
    "02": {"type": "State", "region": "North", "wage": 294, "abbr": "HP"},   # Himachal Pradesh
    "03": {"type": "State", "region": "North", "wage": 322, "abbr": "PB"},   # Punjab
    "04": {"type": "UT", "region": "North", "wage": 331, "abbr": "CH"},      # Chandigarh
    "05": {"type": "State", "region": "North", "wage": 273, "abbr": "UK"},   # Uttarakhand
    "06": {"type": "State", "region": "North", "wage": 357, "abbr": "HR"},   # Haryana
    "07": {"type": "UT", "region": "North", "wage": 379, "abbr": "DL"},      # Delhi
    "08": {"type": "State", "region": "West", "wage": 266, "abbr": "RJ"},    # Rajasthan
    "09": {"type": "State", "region": "Central", "wage": 252, "abbr": "UP"}, # Uttar Pradesh
    "10": {"type": "State", "region": "East", "wage": 245, "abbr": "BR"},    # Bihar
    "11": {"type": "State", "region": "Northeast", "wage": 249, "abbr": "SK"},  # Sikkim
    "12": {"type": "State", "region": "Northeast", "wage": 256, "abbr": "AR"},  # Arunachal
    "13": {"type": "State", "region": "Northeast", "wage": 248, "abbr": "NL"},  # Nagaland
    "14": {"type": "State", "region": "Northeast", "wage": 272, "abbr": "MN"},  # Manipur
    "15": {"type": "State", "region": "Northeast", "wage": 266, "abbr": "MZ"},  # Mizoram
    "16": {"type": "State", "region": "Northeast", "wage": 242, "abbr": "TR"},  # Tripura
    "17": {"type": "State", "region": "Northeast", "wage": 254, "abbr": "ML"},  # Meghalaya
    "18": {"type": "State", "region": "Northeast", "wage": 251, "abbr": "AS"},  # Assam
    "19": {"type": "State", "region": "East", "wage": 250, "abbr": "WB"},    # West Bengal
    "20": {"type": "State", "region": "East", "wage": 248, "abbr": "JH"},    # Jharkhand
    "21": {"type": "State", "region": "East", "wage": 254, "abbr": "OD"},    # Odisha
    "22": {"type": "State", "region": "Central", "wage": 244, "abbr": "CG"}, # Chhattisgarh
    "23": {"type": "State", "region": "Central", "wage": 243, "abbr": "MP"}, # Madhya Pradesh
    "24": {"type": "State", "region": "West", "wage": 280, "abbr": "GJ"},    # Gujarat
    "26": {"type": "UT", "region": "West", "wage": 324, "abbr": "DD"},       # DNH & DD
    "27": {"type": "State", "region": "West", "wage": 297, "abbr": "MH"},    # Maharashtra
    "29": {"type": "State", "region": "South", "wage": 349, "abbr": "KA"},   # Karnataka
    "30": {"type": "State", "region": "West", "wage": 356, "abbr": "GA"},    # Goa
    "31": {"type": "UT", "region": "South", "wage": 304, "abbr": "LD"},      # Lakshadweep
    "32": {"type": "State", "region": "South", "wage": 346, "abbr": "KL"},   # Kerala
    "33": {"type": "State", "region": "South", "wage": 319, "abbr": "TN"},   # Tamil Nadu
    "34": {"type": "UT", "region": "South", "wage": 315, "abbr": "PY"},      # Puducherry
    "35": {"type": "UT", "region": "South", "wage": 327, "abbr": "AN"},      # Andaman & Nicobar
    "36": {"type": "State", "region": "South", "wage": 300, "abbr": "TG"},   # Telangana
    "37": {"type": "State", "region": "South", "wage": 300, "abbr": "AP"},   # Andhra Pradesh
    "38": {"type": "UT", "region": "North", "wage": 259, "abbr": "LA"},      # Ladakh
}

# State codes that are fully urban -> MGNREGA not implemented.
INACTIVE_STATE_CODES = {"04", "07"}  # Chandigarh, Delhi

# Individual fully-urban metro districts (matched by exact district name).
INACTIVE_DISTRICT_NAMES = {
    "Mumbai City", "Mumbai Suburban", "Chennai", "Kolkata", "Hyderabad",
}

# Work categories used across MGNREGA (NREGA permissible works buckets).
WORK_TYPES = [
    "Water Conservation",
    "Rural Connectivity (Roads)",
    "Land Development",
    "Drought Proofing / Plantation",
    "Irrigation & Micro-irrigation",
    "Flood Control & Protection",
    "Anganwadi / Rural Infrastructure",
    "Individual Beneficiary (IAY/IHHL)",
]

ANOMALY_TYPES = [
    "Ghost Workers",
    "Inflated Measurements",
    "Payment Fraud",
    "Duplicate Entries",
    "Material Misuse",
    "Attendance Fraud",
    "Geo-tagging Mismatch",
    "Fund Diversion",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _round_geom(geom, ndigits: int = 4):
    """Round all coordinates of a (multi)polygon mapping to ``ndigits``."""
    gj = mapping(geom)

    def _round_ring(ring):
        return [[round(x, ndigits), round(y, ndigits)] for x, y in ring]

    if gj["type"] == "Polygon":
        gj["coordinates"] = [_round_ring(r) for r in gj["coordinates"]]
    elif gj["type"] == "MultiPolygon":
        gj["coordinates"] = [
            [_round_ring(r) for r in poly] for poly in gj["coordinates"]
        ]
    return gj


def _risk_band(score: float) -> str:
    if score >= 75:
        return "critical"
    if score >= 55:
        return "high"
    if score >= 35:
        return "medium"
    return "low"


def _distribute(total: int, weights: List[float]) -> List[int]:
    """Split ``total`` into integer buckets proportional to ``weights``."""
    s = sum(weights)
    raw = [total * w / s for w in weights]
    out = [int(math.floor(x)) for x in raw]
    rem = total - sum(out)
    # hand out the remainder to the largest fractional parts
    fracs = sorted(range(len(raw)), key=lambda i: raw[i] - out[i], reverse=True)
    for i in range(rem):
        out[fracs[i % len(out)]] += 1
    return out


# ---------------------------------------------------------------------------
# Per-district metric generation (deterministic)
# ---------------------------------------------------------------------------
def generate_district_metrics(
    st_code: str, dt_code: str, district_name: str, active: bool
) -> Dict[str, Any]:
    seed = (int(dt_code) if dt_code.isdigit() else abs(hash(dt_code))) * 7919 + 13
    rng = random.Random(seed)

    if not active:
        return {
            "mgnrega_active": False,
            "total_households": 0,
            "active_workers": 0,
            "person_days": 0,
            "total_works": 0,
            "completed_works": 0,
            "ongoing_works": 0,
            "total_blocks": 0,
            "total_panchayats": 0,
            "total_expenditure_lakhs": 0.0,
            "wages_lakhs": 0.0,
            "material_lakhs": 0.0,
            "verified_count": 0,
            "flagged_count": 0,
            "anomalies_count": 0,
            "estimated_leakage_lakhs": 0.0,
            "risk_score": 0.0,
            "risk_band": "low",
            "avg_wage_rate": float(STATE_META[st_code]["wage"]),
            "avg_days_per_household": 0.0,
            "women_participation_pct": 0.0,
            "scst_participation_pct": 0.0,
            "completion_rate_pct": 0.0,
            "works_by_type": {w: 0 for w in WORK_TYPES},
            "anomaly_by_type": {a: 0 for a in ANOMALY_TYPES},
        }

    wage_rate = float(STATE_META[st_code]["wage"]) + rng.uniform(-8, 8)

    households = rng.randint(30_000, 250_000)
    active_ratio = rng.uniform(0.42, 0.70)
    active_workers = int(households * active_ratio)
    avg_days = rng.uniform(25, 72)
    person_days = int(active_workers * avg_days)

    wages_lakhs = person_days * wage_rate / 1e5
    material_ratio = rng.uniform(0.30, 0.40)
    total_expenditure_lakhs = wages_lakhs / (1 - material_ratio)
    material_lakhs = total_expenditure_lakhs - wages_lakhs

    total_works = rng.randint(800, 7500)
    completion_rate = rng.uniform(0.55, 0.92)
    completed_works = int(total_works * completion_rate)
    ongoing_works = total_works - completed_works

    total_blocks = rng.randint(4, 22)
    total_panchayats = total_blocks * rng.randint(8, 28)

    # Risk: skewed toward the middle, a long tail of critical districts.
    risk_score = round(_clamp(rng.betavariate(2.2, 2.6) * 100, 4, 98), 1)

    verified_count = int(total_works * rng.uniform(0.50, 0.85))
    flagged_ratio = (risk_score / 100) * rng.uniform(0.06, 0.18)
    flagged_count = int(total_works * flagged_ratio)
    anomalies_count = int(flagged_count * rng.uniform(1.0, 1.6))

    leakage_rate = (risk_score / 100) * rng.uniform(0.06, 0.20)
    estimated_leakage_lakhs = total_expenditure_lakhs * leakage_rate

    women_pct = rng.uniform(44, 63)
    scst_pct = rng.uniform(18, 78)

    # works split
    weights = [rng.uniform(0.4, 1.6) for _ in WORK_TYPES]
    counts = _distribute(total_works, weights)
    works_by_type = dict(zip(WORK_TYPES, counts))

    # anomaly split
    aweights = [rng.uniform(0.3, 1.7) for _ in ANOMALY_TYPES]
    acounts = _distribute(anomalies_count, aweights)
    anomaly_by_type = dict(zip(ANOMALY_TYPES, acounts))

    return {
        "mgnrega_active": True,
        "total_households": households,
        "active_workers": active_workers,
        "person_days": person_days,
        "total_works": total_works,
        "completed_works": completed_works,
        "ongoing_works": ongoing_works,
        "total_blocks": total_blocks,
        "total_panchayats": total_panchayats,
        "total_expenditure_lakhs": round(total_expenditure_lakhs, 2),
        "wages_lakhs": round(wages_lakhs, 2),
        "material_lakhs": round(material_lakhs, 2),
        "verified_count": verified_count,
        "flagged_count": flagged_count,
        "anomalies_count": anomalies_count,
        "estimated_leakage_lakhs": round(estimated_leakage_lakhs, 2),
        "risk_score": risk_score,
        "risk_band": _risk_band(risk_score),
        "avg_wage_rate": round(wage_rate, 1),
        "avg_days_per_household": round(person_days / max(households, 1), 1),
        "women_participation_pct": round(women_pct, 1),
        "scst_participation_pct": round(scst_pct, 1),
        "completion_rate_pct": round(completion_rate * 100, 1),
        "works_by_type": works_by_type,
        "anomaly_by_type": anomaly_by_type,
    }


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------
_SUM_FIELDS = [
    "total_households", "active_workers", "person_days", "total_works",
    "completed_works", "ongoing_works", "total_blocks", "total_panchayats",
    "total_expenditure_lakhs", "wages_lakhs", "material_lakhs",
    "verified_count", "flagged_count", "anomalies_count",
    "estimated_leakage_lakhs",
]


def _aggregate(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    agg: Dict[str, Any] = {f: 0 for f in _SUM_FIELDS}
    works_by_type = {w: 0 for w in WORK_TYPES}
    anomaly_by_type = {a: 0 for a in ANOMALY_TYPES}
    active = [r for r in records if r.get("mgnrega_active")]

    for r in records:
        for f in _SUM_FIELDS:
            agg[f] += r.get(f, 0)
        for w in WORK_TYPES:
            works_by_type[w] += r.get("works_by_type", {}).get(w, 0)
        for a in ANOMALY_TYPES:
            anomaly_by_type[a] += r.get("anomaly_by_type", {}).get(a, 0)

    for f in ["total_expenditure_lakhs", "wages_lakhs", "material_lakhs",
              "estimated_leakage_lakhs"]:
        agg[f] = round(agg[f], 2)

    # expenditure-weighted average risk over active units
    tot_exp = sum(r["total_expenditure_lakhs"] for r in active) or 1
    weighted_risk = sum(
        r["risk_score"] * r["total_expenditure_lakhs"] for r in active
    ) / tot_exp
    agg["risk_score"] = round(weighted_risk, 1)
    agg["risk_band"] = _risk_band(weighted_risk)
    agg["completion_rate_pct"] = round(
        agg["completed_works"] / max(agg["total_works"], 1) * 100, 1
    )
    agg["works_by_type"] = works_by_type
    agg["anomaly_by_type"] = anomaly_by_type
    agg["active_districts"] = len(active)
    return agg


# ---------------------------------------------------------------------------
# Main build
# ---------------------------------------------------------------------------
def build() -> None:
    print(f"Loading {_SRC_GEOJSON} ...")
    src = json.loads(_SRC_GEOJSON.read_text(encoding="utf-8"))
    features = src["features"]
    print(f"  {len(features)} district features")

    # group features by state
    states: Dict[str, Dict[str, Any]] = {}
    district_records: List[Dict[str, Any]] = []
    district_geo: List[Dict[str, Any]] = []
    state_geoms: Dict[str, list] = {}

    for idx, f in enumerate(features):
        p = f["properties"]
        # Skip non-district geometry (bare state outlines mixed into the file).
        if "district" not in p or not p.get("district"):
            continue
        st_code = str(p["st_code"]).zfill(2)
        dt_code = str(p.get("dt_code") or f"{st_code}{idx:03d}")
        st_name = p["st_nm"]
        dt_name = p["district"]

        meta = STATE_META.get(st_code)
        if meta is None:
            print(f"  ! unknown state code {st_code} ({st_name}) - skipping")
            continue

        active = (
            st_code not in INACTIVE_STATE_CODES
            and dt_name not in INACTIVE_DISTRICT_NAMES
        )

        geom = shape(f["geometry"])
        if not geom.is_valid:
            geom = geom.buffer(0)
        centroid = geom.centroid
        simp = geom.simplify(0.01, preserve_topology=True)

        metrics = generate_district_metrics(st_code, dt_code, dt_name, active)
        record = {
            "id": f"d-{dt_code}",
            "district_code": dt_code,
            "district_name": dt_name,
            "state_code": st_code,
            "state_name": st_name,
            "state_type": meta["type"],
            "region": meta["region"],
            "lat": round(centroid.y, 5),
            "lng": round(centroid.x, 5),
            **metrics,
        }
        district_records.append(record)

        district_geo.append({
            "type": "Feature",
            "properties": {
                "id": record["id"],
                "district_code": dt_code,
                "district_name": dt_name,
                "state_code": st_code,
                "state_name": st_name,
                "risk_score": metrics["risk_score"],
                "risk_band": metrics["risk_band"],
                "total_works": metrics["total_works"],
                "flagged_count": metrics["flagged_count"],
                "total_expenditure_lakhs": metrics["total_expenditure_lakhs"],
                "mgnrega_active": metrics["mgnrega_active"],
                "centroid": [round(centroid.x, 4), round(centroid.y, 4)],
            },
            "geometry": _round_geom(simp, 4),
        })

        st = states.setdefault(st_code, {
            "state_code": st_code,
            "state_name": st_name,
            "state_type": meta["type"],
            "region": meta["region"],
            "avg_wage_rate": meta["wage"],
            "districts": [],
        })
        st["districts"].append(record)
        state_geoms.setdefault(st_code, []).append(geom)

    # --- state aggregates + dissolved geometry ---
    print("Aggregating states + dissolving boundaries ...")
    state_records: List[Dict[str, Any]] = []
    state_geo: List[Dict[str, Any]] = []
    for st_code, st in sorted(states.items()):
        agg = _aggregate(st["districts"])
        n_districts = len(st["districts"])
        srec = {
            "id": f"s-{st_code}",
            "state_code": st_code,
            "state_name": st["state_name"],
            "state_type": st["state_type"],
            "region": st["region"],
            "avg_wage_rate": st["avg_wage_rate"],
            "total_districts": n_districts,
            **agg,
        }
        state_records.append(srec)

        dissolved = unary_union(state_geoms[st_code])
        if not dissolved.is_valid:
            dissolved = dissolved.buffer(0)
        dissolved = dissolved.simplify(0.02, preserve_topology=True)
        c = dissolved.centroid
        state_geo.append({
            "type": "Feature",
            "properties": {
                "id": srec["id"],
                "state_code": st_code,
                "state_name": st["state_name"],
                "state_type": st["state_type"],
                "region": st["region"],
                "risk_score": agg["risk_score"],
                "risk_band": agg["risk_band"],
                "total_works": agg["total_works"],
                "flagged_count": agg["flagged_count"],
                "total_expenditure_lakhs": agg["total_expenditure_lakhs"],
                "total_districts": n_districts,
                "active_districts": agg["active_districts"],
                "centroid": [round(c.x, 4), round(c.y, 4)],
            },
            "geometry": _round_geom(dissolved, 4),
        })

    # --- national summary ---
    print("Building national summary ...")
    national = _aggregate(district_records)
    national.update({
        "fin_year": FIN_YEAR,
        "total_states": len([s for s in state_records if s["state_type"] == "State"]),
        "total_uts": len([s for s in state_records if s["state_type"] == "UT"]),
        "total_districts": len(district_records),
        "active_districts": national["active_districts"],
    })

    # national monthly trend (deterministic)
    rng = random.Random(20260618)
    months = ["Apr 25", "May 25", "Jun 25", "Jul 25", "Aug 25", "Sep 25",
              "Oct 25", "Nov 25", "Dec 25", "Jan 26", "Feb 26", "Mar 26"]
    base = national["anomalies_count"] / 12
    trend = []
    cum_pending = 0
    for m in months:
        detected = int(base * rng.uniform(0.7, 1.3))
        resolved = int(detected * rng.uniform(0.6, 1.05))
        cum_pending = max(0, cum_pending + detected - resolved)
        trend.append({"month": m, "detected": detected,
                      "resolved": resolved, "pending": cum_pending})

    # top risk districts (national)
    top_districts = sorted(
        [d for d in district_records if d["mgnrega_active"]],
        key=lambda d: d["risk_score"], reverse=True,
    )[:25]
    top_districts = [{
        "id": d["id"], "district_name": d["district_name"],
        "state_name": d["state_name"], "state_code": d["state_code"],
        "risk_score": d["risk_score"], "risk_band": d["risk_band"],
        "flagged_count": d["flagged_count"],
        "total_expenditure_lakhs": d["total_expenditure_lakhs"],
        "estimated_leakage_lakhs": d["estimated_leakage_lakhs"],
        "lat": d["lat"], "lng": d["lng"],
    } for d in top_districts]

    dataset = {
        "meta": {
            "fin_year": FIN_YEAR,
            "generated_from": "india_districts.geojson (census admin boundaries)",
            "note": "Synthetic deterministic metrics for demonstration; "
                    "replace via live NREGA ingestion for production.",
        },
        "national": national,
        "national_trend": trend,
        "top_risk_districts": top_districts,
        "states": state_records,
        "districts": district_records,
    }

    # --- write outputs ---
    (_OUT_DIR / "india_dataset.json").write_text(
        json.dumps(dataset, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    (_OUT_DIR / "geo_states.json").write_text(
        json.dumps({"type": "FeatureCollection", "features": state_geo},
                   ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    (_OUT_DIR / "geo_districts.json").write_text(
        json.dumps({"type": "FeatureCollection", "features": district_geo},
                   ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )

    def _mb(name: str) -> float:
        return (_OUT_DIR / name).stat().st_size / 1e6

    print("\nDone.")
    print(f"  states/UTs       : {len(state_records)}")
    print(f"  districts        : {len(district_records)}")
    print(f"  active districts : {national['active_districts']}")
    print(f"  national exp     : Rs {national['total_expenditure_lakhs']/100:,.0f} crore")
    print(f"  national pdays   : {national['person_days']/1e7:,.1f} crore person-days")
    print(f"  national risk    : {national['risk_score']}")
    print(f"  india_dataset.json : {_mb('india_dataset.json'):.2f} MB")
    print(f"  geo_states.json    : {_mb('geo_states.json'):.2f} MB")
    print(f"  geo_districts.json : {_mb('geo_districts.json'):.2f} MB")


if __name__ == "__main__":
    build()
