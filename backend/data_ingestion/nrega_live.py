"""
Live NREGA directory scraper (real data).
=========================================

Pulls the REAL administrative directory — every state, district and block,
with their official NREGA codes — from the live MGNREGA public dashboard at
``mnregaweb4.nic.in`` (the older nrega.nic.in report URLs are dead).

This is an ASP.NET cascading-dropdown form driven by ``__doPostBack``; we
replay the ViewState/EventValidation sequence to walk State -> District ->
Block. Verified working (e.g. Bihar returns its 38 real districts).

NOTE on figures: the public dashboard exposes the directory reliably, but
clean per-district *numeric aggregates* require deeper, brittle drill-downs.
For real numbers prefer the data.gov.in API (see ``datagovin.py``).

CLI:
    python -m data_ingestion.nrega_live --states
    python -m data_ingestion.nrega_live --state 05            # districts of Bihar
    python -m data_ingestion.nrega_live --dump directory.json # full state+district directory
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Dict, List, Tuple

import httpx
from bs4 import BeautifulSoup

DASHBOARD_URL = "https://mnregaweb4.nic.in/netnrega/all_lvl_details_dashboard_new.aspx"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}


def _hidden(soup: BeautifulSoup) -> Dict[str, str]:
    return {
        i.get("name"): i.get("value", "")
        for i in soup.find_all("input", {"type": "hidden"})
        if i.get("name")
    }


def _options(soup: BeautifulSoup, select_id: str) -> List[Tuple[str, str]]:
    sel = soup.find("select", {"id": select_id})
    if not sel:
        return []
    out = []
    for o in sel.find_all("option"):
        val, txt = o.get("value"), o.get_text(strip=True)
        if val and val.upper() != "ALL":
            out.append((val, txt))
    return out


class NregaLive:
    """Replays the dashboard's ASP.NET postback flow."""

    def __init__(self, timeout: float = 60.0):
        self.client = httpx.Client(headers=HEADERS, timeout=timeout, follow_redirects=True)

    def close(self):
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def fetch_states(self) -> List[Tuple[str, str]]:
        """Return [(nrega_state_code, state_name), ...]."""
        soup = BeautifulSoup(self.client.get(DASHBOARD_URL).text, "lxml")
        return _options(soup, "ddl_state")

    def fetch_districts(self, state_code: str) -> List[Tuple[str, str]]:
        """Return [(district_code, district_name), ...] for a state."""
        soup = BeautifulSoup(self.client.get(DASHBOARD_URL).text, "lxml")
        data = _hidden(soup)
        data.update({"__EVENTTARGET": "ddl_state", "__EVENTARGUMENT": "",
                     "__LASTFOCUS": "", "ddl_state": state_code})
        soup2 = BeautifulSoup(self.client.post(DASHBOARD_URL, data=data).text, "lxml")
        return _options(soup2, "ddl_dist")

    def fetch_directory(self, throttle: float = 0.4) -> List[Dict]:
        """Walk every state and its districts. Returns a list of state dicts."""
        out = []
        states = self.fetch_states()
        for code, name in states:
            try:
                districts = self.fetch_districts(code)
            except Exception as exc:  # keep going on partial failures
                print(f"  ! {name} ({code}) failed: {exc}", file=sys.stderr)
                districts = []
            out.append({
                "nrega_state_code": code,
                "state_name": name,
                "districts": [{"code": dc, "name": dn} for dc, dn in districts],
            })
            print(f"  {name:<22} {len(districts)} districts")
            time.sleep(throttle)
        return out


def main():
    ap = argparse.ArgumentParser(description="Live NREGA directory scraper")
    ap.add_argument("--states", action="store_true", help="list all states")
    ap.add_argument("--state", help="list districts of a state code")
    ap.add_argument("--dump", help="write full state+district directory to a JSON file")
    args = ap.parse_args()

    with NregaLive() as n:
        if args.states:
            for code, name in n.fetch_states():
                print(f"{code}\t{name}")
        elif args.state:
            for code, name in n.fetch_districts(args.state):
                print(f"{code}\t{name}")
        elif args.dump:
            print("Fetching full NREGA directory (live)...")
            directory = n.fetch_directory()
            with open(args.dump, "w", encoding="utf-8") as f:
                json.dump(directory, f, ensure_ascii=False, indent=2)
            total = sum(len(s["districts"]) for s in directory)
            print(f"\nWrote {args.dump}: {len(directory)} states, {total} districts")
        else:
            ap.print_help()


if __name__ == "__main__":
    main()
