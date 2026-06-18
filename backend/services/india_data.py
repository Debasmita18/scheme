"""
All-India MGNREGA data service.
===============================

Loads the generated dataset (national + states + districts + map geometry)
once into memory and exposes fast, filtered query helpers used by the API
routes.  This is the single in-memory source of truth that lets the whole
application run for every state, UT and district with no database.

If ``backend/data/generated/india_dataset.json`` is missing, the service
raises a clear error telling the operator to run the build step:

    python -m data_ingestion.build_india_dataset
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_GEN_DIR = _BACKEND_DIR / "data" / "generated"

_DATASET_FILE = _GEN_DIR / "india_dataset.json"
_GEO_STATES_FILE = _GEN_DIR / "geo_states.json"
_GEO_DISTRICTS_FILE = _GEN_DIR / "geo_districts.json"

# Light-weight fields returned in district list responses.
_DISTRICT_SUMMARY_FIELDS = (
    "id", "district_code", "district_name", "state_code", "state_name",
    "state_type", "region", "lat", "lng", "mgnrega_active",
    "total_works", "total_expenditure_lakhs", "verified_count",
    "flagged_count", "anomalies_count", "estimated_leakage_lakhs",
    "risk_score", "risk_band", "person_days", "active_workers",
    "total_households", "completion_rate_pct",
)


class _Store:
    """Holds the parsed dataset and lookup indexes."""

    def __init__(self) -> None:
        if not _DATASET_FILE.exists():
            raise FileNotFoundError(
                f"Dataset not found at {_DATASET_FILE}. "
                "Generate it first:  python -m data_ingestion.build_india_dataset"
            )
        data = json.loads(_DATASET_FILE.read_text(encoding="utf-8"))
        self.meta: Dict[str, Any] = data["meta"]
        self.national: Dict[str, Any] = data["national"]
        self.national_trend: List[Dict[str, Any]] = data["national_trend"]
        self.top_risk_districts: List[Dict[str, Any]] = data["top_risk_districts"]
        self.states: List[Dict[str, Any]] = data["states"]
        self.districts: List[Dict[str, Any]] = data["districts"]

        self.state_by_code: Dict[str, Dict[str, Any]] = {
            s["state_code"]: s for s in self.states
        }
        self.district_by_id: Dict[str, Dict[str, Any]] = {
            d["id"]: d for d in self.districts
        }
        self.districts_by_state: Dict[str, List[Dict[str, Any]]] = {}
        for d in self.districts:
            self.districts_by_state.setdefault(d["state_code"], []).append(d)

        # geometry (loaded lazily on first access)
        self._geo_states: Optional[Dict[str, Any]] = None
        self._geo_districts: Optional[Dict[str, Any]] = None

    # -- geometry -----------------------------------------------------------
    @property
    def geo_states(self) -> Dict[str, Any]:
        if self._geo_states is None:
            self._geo_states = json.loads(
                _GEO_STATES_FILE.read_text(encoding="utf-8")
            )
        return self._geo_states

    @property
    def geo_districts(self) -> Dict[str, Any]:
        if self._geo_districts is None:
            self._geo_districts = json.loads(
                _GEO_DISTRICTS_FILE.read_text(encoding="utf-8")
            )
        return self._geo_districts


@lru_cache(maxsize=1)
def _store() -> _Store:
    return _Store()


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------
def national_summary() -> Dict[str, Any]:
    s = _store()
    out = dict(s.national)
    out["meta"] = s.meta
    return out


def national_trend() -> List[Dict[str, Any]]:
    return _store().national_trend


def top_risk_districts(limit: int = 10) -> List[Dict[str, Any]]:
    return _store().top_risk_districts[:limit]


def anomaly_breakdown() -> List[Dict[str, Any]]:
    """National anomaly counts by type with a rough rupee impact estimate."""
    s = _store()
    by_type = s.national["anomaly_by_type"]
    total_leak = s.national["estimated_leakage_lakhs"]
    total_anom = sum(by_type.values()) or 1
    return [
        {
            "type": k,
            "count": v,
            "estimated_amount_lakhs": round(total_leak * v / total_anom, 2),
        }
        for k, v in sorted(by_type.items(), key=lambda kv: kv[1], reverse=True)
    ]


def _state_summary(s: Dict[str, Any]) -> Dict[str, Any]:
    keep = (
        "id", "state_code", "state_name", "state_type", "region",
        "avg_wage_rate", "total_districts", "active_districts",
        "total_works", "total_expenditure_lakhs", "person_days",
        "verified_count", "flagged_count", "anomalies_count",
        "estimated_leakage_lakhs", "risk_score", "risk_band",
        "total_households", "active_workers", "completion_rate_pct",
    )
    return {k: s.get(k) for k in keep}


def list_states(
    region: Optional[str] = None,
    state_type: Optional[str] = None,
    search: Optional[str] = None,
    sort_by: str = "risk_score",
    order: str = "desc",
) -> List[Dict[str, Any]]:
    rows = list(_store().states)
    if region:
        rows = [s for s in rows if s["region"].lower() == region.lower()]
    if state_type:
        rows = [s for s in rows if s["state_type"].lower() == state_type.lower()]
    if search:
        q = search.lower()
        rows = [s for s in rows if q in s["state_name"].lower()]
    reverse = order == "desc"
    rows.sort(key=lambda s: s.get(sort_by, 0)
              if isinstance(s.get(sort_by), (int, float))
              else str(s.get(sort_by, "")), reverse=reverse)
    return [_state_summary(s) for s in rows]


def get_state(code: str) -> Optional[Dict[str, Any]]:
    s = _store().state_by_code.get(code)
    if not s:
        return None
    out = {k: v for k, v in s.items() if k != "districts"}
    out["districts"] = [
        {k: d.get(k) for k in _DISTRICT_SUMMARY_FIELDS}
        for d in _store().districts_by_state.get(code, [])
    ]
    return out


def list_districts(
    state: Optional[str] = None,
    region: Optional[str] = None,
    risk_band: Optional[str] = None,
    search: Optional[str] = None,
    active_only: bool = False,
    sort_by: str = "risk_score",
    order: str = "desc",
    skip: int = 0,
    limit: int = 50,
) -> Dict[str, Any]:
    rows = list(_store().districts)
    if state:
        # accept state code or (partial) state name
        rows = [
            d for d in rows
            if d["state_code"] == state or state.lower() in d["state_name"].lower()
        ]
    if region:
        rows = [d for d in rows if d["region"].lower() == region.lower()]
    if risk_band:
        rows = [d for d in rows if d["risk_band"] == risk_band.lower()]
    if active_only:
        rows = [d for d in rows if d["mgnrega_active"]]
    if search:
        q = search.lower()
        rows = [
            d for d in rows
            if q in d["district_name"].lower() or q in d["state_name"].lower()
        ]

    reverse = order == "desc"
    rows.sort(key=lambda d: d.get(sort_by, 0)
              if isinstance(d.get(sort_by), (int, float))
              else str(d.get(sort_by, "")), reverse=reverse)

    total = len(rows)
    page = rows[skip: skip + limit]
    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "data": [{k: d.get(k) for k in _DISTRICT_SUMMARY_FIELDS} for d in page],
    }


def get_district(district_id: str) -> Optional[Dict[str, Any]]:
    return _store().district_by_id.get(district_id)


def states_geojson() -> Dict[str, Any]:
    return _store().geo_states


def districts_geojson(state: Optional[str] = None) -> Dict[str, Any]:
    gj = _store().geo_districts
    if not state:
        return gj
    feats = [
        f for f in gj["features"]
        if f["properties"]["state_code"] == state
        or state.lower() in f["properties"]["state_name"].lower()
    ]
    return {"type": "FeatureCollection", "features": feats}


def warm_cache() -> Dict[str, int]:
    """Force-load everything (called at app startup). Returns simple counts."""
    s = _store()
    _ = s.geo_states
    _ = s.geo_districts
    return {
        "states": len(s.states),
        "districts": len(s.districts),
        "geo_states": len(s.geo_states["features"]),
        "geo_districts": len(s.geo_districts["features"]),
    }
