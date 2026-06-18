"""
data.gov.in MGNREGA ingestion (real figures).
=============================================

The Open Government Data (OGD) platform publishes "District-wise MGNREGA Data
at a Glance" as a JSON REST resource. This is the legitimate, reliable channel
for REAL district figures (the public NREGA dashboard exposes the directory
well but not clean per-district aggregates).

Configure in backend/.env:
    DATAGOVIN_API_KEY=<your free key from data.gov.in, or the public sample key>
    DATAGOVIN_RESOURCE_ID=<resource id of the dataset>

CLI:
    python -m data_ingestion.datagovin --inspect      # show fields + sample (API must be up)
    python -m data_ingestion.datagovin --refresh      # rebuild dataset with REAL numbers

When --refresh succeeds it rewrites data/generated/india_dataset.json with
real metrics and tags each record data_source="data.gov.in (live)". The map
geometry and any unmatched districts keep their existing values.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_GEN = _BACKEND_DIR / "data" / "generated" / "india_dataset.json"


def _cfg() -> Dict[str, str]:
    # read backend/.env without extra deps
    env = {}
    envfile = _BACKEND_DIR / ".env"
    if envfile.exists():
        for line in envfile.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return {
        "key": os.getenv("DATAGOVIN_API_KEY", env.get("DATAGOVIN_API_KEY", "")),
        "rid": os.getenv("DATAGOVIN_RESOURCE_ID", env.get("DATAGOVIN_RESOURCE_ID", "")),
    }


def fetch_records(limit: int = 2000) -> List[Dict[str, Any]]:
    """Page through the data.gov.in resource and return all records."""
    c = _cfg()
    if not c["key"] or not c["rid"]:
        raise RuntimeError("DATAGOVIN_API_KEY / DATAGOVIN_RESOURCE_ID not set in backend/.env")
    url = f"https://api.data.gov.in/resource/{c['rid']}"
    records: List[Dict[str, Any]] = []
    offset = 0
    with httpx.Client(timeout=90) as client:
        while True:
            r = client.get(url, params={"api-key": c["key"], "format": "json",
                                        "limit": limit, "offset": offset})
            r.raise_for_status()
            j = r.json()
            batch = j.get("records", [])
            records.extend(batch)
            total = int(j.get("total", len(records)))
            offset += len(batch)
            if not batch or offset >= total:
                break
    return records


def inspect() -> None:
    recs = fetch_records(limit=5)
    print(f"fetched {len(recs)} sample records")
    if recs:
        print("fields:", list(recs[0].keys()))
        print(json.dumps(recs[0], ensure_ascii=False, indent=2))


# Map likely data.gov.in field names -> our metric keys. Adjust after --inspect.
_FIELD_ALIASES = {
    "state": ["state_name", "state", "states"],
    "district": ["district_name", "district", "districts"],
    "expenditure_lakhs": ["total_exp", "total_expenditure", "expenditure", "exp"],
    "person_days": ["persondays", "person_days", "total_persondays_generated"],
    "households": ["households", "total_households_worked", "hh_worked"],
    "works": ["total_works", "works", "no_of_works"],
}


def _pick(rec: Dict[str, Any], keys: List[str]) -> Optional[Any]:
    for k in keys:
        for rk in rec:
            if rk.lower() == k.lower():
                return rec[rk]
    return None


def refresh() -> None:
    if not _GEN.exists():
        raise RuntimeError(f"{_GEN} missing; run build_india_dataset first")
    recs = fetch_records()
    print(f"fetched {len(recs)} real records from data.gov.in")
    if not recs:
        print("no records returned; aborting")
        return

    # index real records by (state, district) upper-cased
    real = {}
    for rec in recs:
        st = (_pick(rec, _FIELD_ALIASES["state"]) or "").strip().upper()
        dt = (_pick(rec, _FIELD_ALIASES["district"]) or "").strip().upper()
        if st and dt:
            real[(st, dt)] = rec

    dataset = json.loads(_GEN.read_text(encoding="utf-8"))
    matched = 0
    for d in dataset["districts"]:
        key = (d["state_name"].upper(), d["district_name"].upper())
        rec = real.get(key)
        if not rec:
            continue
        exp = _pick(rec, _FIELD_ALIASES["expenditure_lakhs"])
        pdays = _pick(rec, _FIELD_ALIASES["person_days"])
        hh = _pick(rec, _FIELD_ALIASES["households"])
        works = _pick(rec, _FIELD_ALIASES["works"])
        try:
            if exp is not None:
                d["total_expenditure_lakhs"] = float(str(exp).replace(",", ""))
            if pdays is not None:
                d["person_days"] = int(float(str(pdays).replace(",", "")))
            if hh is not None:
                d["total_households"] = int(float(str(hh).replace(",", "")))
            if works is not None:
                d["total_works"] = int(float(str(works).replace(",", "")))
            d["data_source"] = "data.gov.in (live)"
            matched += 1
        except (ValueError, TypeError):
            continue

    dataset.setdefault("meta", {})["data_source"] = (
        f"data.gov.in (live) — {matched} districts matched"
    )
    _GEN.write_text(json.dumps(dataset, ensure_ascii=False, separators=(",", ":")),
                    encoding="utf-8")
    print(f"updated {matched} districts with REAL figures -> {_GEN}")
    print("Restart the API to serve the refreshed data.")


def main():
    ap = argparse.ArgumentParser(description="data.gov.in MGNREGA ingestion")
    ap.add_argument("--inspect", action="store_true")
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()
    try:
        if args.inspect:
            inspect()
        elif args.refresh:
            refresh()
        else:
            ap.print_help()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
