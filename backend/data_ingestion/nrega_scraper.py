"""
NREGA Data Scraper Module
=========================

Real-time scraper for the National Rural Employment Guarantee Act (NREGA)
Management Information System hosted at nrega.nic.in.

This module handles the ASP.NET ViewState-based navigation, extracts structured
data from HTML table reports, and orchestrates full district-level data ingestion
pipelines for the MGNREGA Verification & Fraud Intelligence System.

Key Reports Scraped:
    - R1.1  Job Card Register
    - R2.2  Muster Roll (Worksite-wise)
    - R3.17 Work-wise Expenditure
    - R5.1  FTO (Fund Transfer Order) Status
    - R6.1  Demand for Work
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional

import httpx
from bs4 import BeautifulSoup, Tag
from loguru import logger
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_URL = "https://nrega.nic.in"
HOME_URL = f"{BASE_URL}/Nregahome/MGNREGA_new/Nrega_home.aspx"
STATE_HOME_URL = f"{BASE_URL}/netnrega/stHome.aspx"
NET_NREGA_BASE = f"{BASE_URL}/netnrega"

# Report URL templates -- these map to the standard NREGA MIS report codes.
REPORT_URLS = {
    "R1.1": "{base}/netnrega/IndexFrame.aspx?lflag=eng&District_Code={dist}&state_name={state_name}&state_Code={state}&Block_Code={block}&block_name={block_name}&fin_year={fin_year}&check=1&Atea=&Activity_cat=&type=",
    "R2.2": "{base}/netnrega/Aborwise_mroll.aspx?lflag=eng&state_code={state}&district_code={dist}&block_code={block}&pession_code={panchayat}&fin_year={fin_year}",
    "R3.17": "{base}/netnrega/work_wise_expdr.aspx?lflag=eng&state_code={state}&district_code={dist}&block_code={block}&pession_code={panchayat}&fin_year={fin_year}",
    "R5.1": "{base}/netnrega/FTO/FTOReport.aspx?lflag=eng&state_code={state}&district_code={dist}&block_code={block}&fin_year={fin_year}",
    "R6.1": "{base}/netnrega/demand_emp_register.aspx?lflag=eng&state_code={state}&district_code={dist}&block_code={block}&pession_code={panchayat}&fin_year={fin_year}",
}

# Real NREGA state codes -- subset of the most commonly audited states.
STATE_CODES: dict[str, str] = {
    "02": "ANDHRA PRADESH",
    "04": "ASSAM",
    "05": "BIHAR",
    "07": "CHHATTISGARH",
    "09": "GOA",
    "10": "GUJARAT",
    "11": "HARYANA",
    "12": "HIMACHAL PRADESH",
    "13": "JAMMU AND KASHMIR",
    "14": "JHARKHAND",
    "15": "KARNATAKA",
    "16": "KERALA",
    "17": "MADHYA PRADESH",
    "18": "MAHARASHTRA",
    "19": "MANIPUR",
    "20": "MEGHALAYA",
    "21": "MIZORAM",
    "22": "NAGALAND",
    "23": "ODISHA",
    "24": "PUNJAB",
    "25": "RAJASTHAN",
    "27": "SIKKIM",
    "28": "TAMIL NADU",
    "29": "TELANGANA",
    "30": "TRIPURA",
    "31": "UTTAR PRADESH",
    "32": "UTTARAKHAND",
    "33": "WEST BENGAL",
    "34": "RAJASTHAN",
}

DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Referer": BASE_URL,
}

REQUEST_TIMEOUT = 60.0
MAX_CONCURRENT_REQUESTS = 5


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


class WorkStatus(str, Enum):
    """Enumeration of standard NREGA work statuses."""

    NOT_STARTED = "Not Started"
    ONGOING = "Ongoing"
    COMPLETED = "Completed"
    SHELVED = "Shelved"
    UNKNOWN = "Unknown"


@dataclass(frozen=True)
class District:
    """Represents an NREGA district."""

    code: str
    name: str
    state_code: str


@dataclass(frozen=True)
class Block:
    """Represents an NREGA block within a district."""

    code: str
    name: str
    district_code: str
    state_code: str


@dataclass(frozen=True)
class Panchayat:
    """Represents a Gram Panchayat within a block."""

    code: str
    name: str
    block_code: str
    district_code: str
    state_code: str


@dataclass
class WorkRecord:
    """Represents a single NREGA work entry (R3.17 / work-wise expenditure)."""

    work_id: str
    work_name: str
    work_type: str
    sanctioned_amount: float
    expenditure: float
    status: WorkStatus
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    start_date: Optional[str] = None
    completion_date: Optional[str] = None
    panchayat_code: Optional[str] = None
    block_code: Optional[str] = None
    district_code: Optional[str] = None
    state_code: Optional[str] = None


@dataclass
class MusterRollEntry:
    """A single row from a muster roll report."""

    worker_name: str
    job_card_number: str
    days_worked: float
    wages_paid: float
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    muster_roll_number: Optional[str] = None
    work_id: Optional[str] = None


@dataclass
class FTORecord:
    """A Fund Transfer Order record."""

    fto_number: str
    reference_number: str
    worker_name: str
    job_card_number: str
    account_number: str
    amount: float
    status: str
    transaction_date: Optional[str] = None
    rejection_reason: Optional[str] = None
    block_code: Optional[str] = None


@dataclass
class WorkerDetail:
    """Detailed worker information from a job card."""

    job_card_number: str
    worker_name: str
    father_husband_name: str
    age: Optional[int] = None
    gender: Optional[str] = None
    category: Optional[str] = None
    village: Optional[str] = None
    panchayat: Optional[str] = None
    block: Optional[str] = None
    district: Optional[str] = None
    state: Optional[str] = None
    registration_date: Optional[str] = None
    bpl_status: Optional[str] = None
    bank_account: Optional[str] = None
    total_days_worked: Optional[float] = None
    total_wages_received: Optional[float] = None


# ---------------------------------------------------------------------------
# ASP.NET ViewState helpers
# ---------------------------------------------------------------------------


def _extract_viewstate(soup: BeautifulSoup) -> dict[str, str]:
    """Extract ASP.NET hidden form fields required for postback navigation.

    NREGA pages use __VIEWSTATE, __VIEWSTATEGENERATOR, __EVENTVALIDATION,
    and __EVENTTARGET for server-side round-trips.

    Args:
        soup: Parsed HTML of the current page.

    Returns:
        Dictionary of hidden field names to their values.
    """
    fields: dict[str, str] = {}
    for field_name in (
        "__VIEWSTATE",
        "__VIEWSTATEGENERATOR",
        "__EVENTVALIDATION",
        "__EVENTTARGET",
        "__EVENTARGUMENT",
        "__LASTFOCUS",
    ):
        tag = soup.find("input", attrs={"name": field_name})
        if tag and isinstance(tag, Tag):
            fields[field_name] = tag.get("value", "")
    return fields


def _parse_html_table(
    soup: BeautifulSoup,
    table_id: Optional[str] = None,
    table_class: Optional[str] = None,
    skip_header_rows: int = 1,
) -> list[list[str]]:
    """Parse an HTML table into a list of row-lists.

    The NREGA site uses multiple table layouts -- some have ``id`` attributes,
    some only have CSS classes, and some are nested.  This helper covers all
    three cases.

    Args:
        soup: Parsed HTML containing the target table.
        table_id: HTML ``id`` attribute to locate the table.
        table_class: CSS class name to locate the table.
        skip_header_rows: Number of leading ``<tr>`` rows to skip (headers).

    Returns:
        A list of rows, each row a list of cell text values.
    """
    table: Optional[Tag] = None
    if table_id:
        table = soup.find("table", attrs={"id": table_id})
    if table is None and table_class:
        table = soup.find("table", class_=table_class)
    if table is None:
        # Fallback: grab the largest table on the page.
        tables = soup.find_all("table")
        if tables:
            table = max(tables, key=lambda t: len(t.find_all("tr")))
    if table is None:
        return []

    rows: list[list[str]] = []
    all_tr = table.find_all("tr")  # type: ignore[union-attr]
    for tr in all_tr[skip_header_rows:]:
        cells = tr.find_all(["td", "th"])
        row = [cell.get_text(strip=True) for cell in cells]
        if any(row):
            rows.append(row)
    return rows


def _extract_links_from_table(
    soup: BeautifulSoup,
    table_id: Optional[str] = None,
    table_class: Optional[str] = None,
) -> list[dict[str, str]]:
    """Extract hyperlinks from table cells.

    Returns a list of dicts with keys ``text`` and ``href``.
    """
    table: Optional[Tag] = None
    if table_id:
        table = soup.find("table", attrs={"id": table_id})
    if table is None and table_class:
        table = soup.find("table", class_=table_class)
    if table is None:
        tables = soup.find_all("table")
        if tables:
            table = max(tables, key=lambda t: len(t.find_all("tr")))
    if table is None:
        return []

    links: list[dict[str, str]] = []
    for a_tag in table.find_all("a", href=True):
        links.append({"text": a_tag.get_text(strip=True), "href": a_tag["href"]})
    return links


def _safe_float(value: str) -> float:
    """Convert a string to float, stripping commas and non-numeric chars."""
    cleaned = re.sub(r"[^\d.\-]", "", value)
    try:
        return float(cleaned) if cleaned else 0.0
    except ValueError:
        return 0.0


def _safe_int(value: str) -> int:
    """Convert a string to int, stripping non-digit chars."""
    cleaned = re.sub(r"[^\d]", "", value)
    try:
        return int(cleaned) if cleaned else 0
    except ValueError:
        return 0


def _normalize_code(raw: str) -> str:
    """Extract a numeric code from a URL fragment or cell text."""
    match = re.search(r"(\d{4,})", raw)
    return match.group(1) if match else raw.strip()


def _current_fin_year() -> str:
    """Return the current NREGA financial year string, e.g. '2025-2026'."""
    now = datetime.now()
    if now.month >= 4:
        return f"{now.year}-{now.year + 1}"
    return f"{now.year - 1}-{now.year}"


# ---------------------------------------------------------------------------
# NREGAScraper
# ---------------------------------------------------------------------------


class NREGAScraper:
    """Asynchronous scraper for the NREGA MIS portal (nrega.nic.in).

    This class manages a persistent ``httpx.AsyncClient`` session with proper
    cookie handling, constructs ASP.NET postback payloads, and parses the HTML
    tables returned by the various NREGA report pages.

    Usage::

        async with NREGAScraper() as scraper:
            districts = await scraper.fetch_district_list("34")
            for d in districts:
                blocks = await scraper.fetch_block_list("34", d.code)
    """

    def __init__(
        self,
        *,
        timeout: float = REQUEST_TIMEOUT,
        max_concurrent: int = MAX_CONCURRENT_REQUESTS,
    ) -> None:
        self._timeout = timeout
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._client: Optional[httpx.AsyncClient] = None

    # -- Context manager support ------------------------------------------

    async def __aenter__(self) -> "NREGAScraper":
        self._client = httpx.AsyncClient(
            headers=DEFAULT_HEADERS,
            timeout=httpx.Timeout(self._timeout),
            follow_redirects=True,
            http2=False,
        )
        logger.info("NREGAScraper session opened")
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._client:
            await self._client.aclose()
            logger.info("NREGAScraper session closed")

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError(
                "NREGAScraper must be used as an async context manager"
            )
        return self._client

    # -- Low-level HTTP helpers -------------------------------------------

    @retry(
        retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TransportError)),
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        reraise=True,
    )
    async def _get(self, url: str, **kwargs: Any) -> httpx.Response:
        """Issue a GET request with automatic retries and rate-limiting."""
        async with self._semaphore:
            logger.debug("GET {}", url)
            response = await self.client.get(url, **kwargs)
            response.raise_for_status()
            return response

    @retry(
        retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TransportError)),
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        reraise=True,
    )
    async def _post(self, url: str, **kwargs: Any) -> httpx.Response:
        """Issue a POST request with automatic retries and rate-limiting."""
        async with self._semaphore:
            logger.debug("POST {}", url)
            response = await self.client.post(url, **kwargs)
            response.raise_for_status()
            return response

    async def _get_soup(self, url: str, **kwargs: Any) -> BeautifulSoup:
        """Fetch a URL and return a parsed BeautifulSoup tree."""
        resp = await self._get(url, **kwargs)
        return BeautifulSoup(resp.text, "html.parser")

    async def _post_soup(self, url: str, **kwargs: Any) -> BeautifulSoup:
        """POST to a URL and return a parsed BeautifulSoup tree."""
        resp = await self._post(url, **kwargs)
        return BeautifulSoup(resp.text, "html.parser")

    async def _postback(
        self,
        page_url: str,
        viewstate: dict[str, str],
        event_target: str,
        extra_data: Optional[dict[str, str]] = None,
    ) -> BeautifulSoup:
        """Perform an ASP.NET __doPostBack round-trip.

        Args:
            page_url: The URL of the ASP.NET page.
            viewstate: Current ViewState fields from the page.
            event_target: The control ID to trigger.
            extra_data: Additional form fields.

        Returns:
            Parsed BeautifulSoup of the response page.
        """
        payload = {**viewstate, "__EVENTTARGET": event_target, "__EVENTARGUMENT": ""}
        if extra_data:
            payload.update(extra_data)
        return await self._post_soup(page_url, data=payload)

    # -- Public scraping API -----------------------------------------------

    async def fetch_district_list(self, state_code: str) -> list[District]:
        """Fetch all districts for a given state from the NREGA portal.

        Navigates to the state-level home page and extracts the district listing
        table.  Each district row contains a link whose URL encodes the district
        code.

        Args:
            state_code: Two-digit NREGA state code (e.g. ``'34'`` for Rajasthan).

        Returns:
            List of ``District`` objects.
        """
        state_name = STATE_CODES.get(state_code, "UNKNOWN")
        url = (
            f"{NET_NREGA_BASE}/stHome.aspx"
            f"?state_code={state_code}&state_name={state_name}"
        )
        logger.info("Fetching district list for state {} ({})", state_code, state_name)
        soup = await self._get_soup(url)

        districts: list[District] = []
        links = _extract_links_from_table(soup)
        for link in links:
            text = link["text"].strip()
            href = link["href"]
            # District codes are typically embedded as district_code=XXXX in the URL
            code_match = re.search(r"district_code=(\d+)", href, re.IGNORECASE)
            if not code_match:
                code_match = re.search(r"District_Code=(\d+)", href, re.IGNORECASE)
            if code_match and text:
                districts.append(
                    District(
                        code=code_match.group(1),
                        name=text,
                        state_code=state_code,
                    )
                )

        # Deduplicate by code
        seen: set[str] = set()
        unique: list[District] = []
        for d in districts:
            if d.code not in seen:
                seen.add(d.code)
                unique.append(d)

        logger.info("Found {} districts for state {}", len(unique), state_code)
        return unique

    async def fetch_block_list(
        self, state_code: str, district_code: str
    ) -> list[Block]:
        """Fetch all blocks within a district.

        Args:
            state_code: Two-digit NREGA state code.
            district_code: Numeric district code.

        Returns:
            List of ``Block`` objects.
        """
        state_name = STATE_CODES.get(state_code, "UNKNOWN")
        url = (
            f"{NET_NREGA_BASE}/demregister.aspx"
            f"?lflag=eng&state_code={state_code}&state_name={state_name}"
            f"&district_code={district_code}&fin_year={_current_fin_year()}"
        )
        logger.info(
            "Fetching block list for district {} in state {}", district_code, state_code
        )
        soup = await self._get_soup(url)

        blocks: list[Block] = []
        links = _extract_links_from_table(soup)
        for link in links:
            text = link["text"].strip()
            href = link["href"]
            code_match = re.search(r"block_code=(\d+)", href, re.IGNORECASE)
            if not code_match:
                code_match = re.search(r"Block_Code=(\d+)", href, re.IGNORECASE)
            if code_match and text:
                blocks.append(
                    Block(
                        code=code_match.group(1),
                        name=text,
                        district_code=district_code,
                        state_code=state_code,
                    )
                )

        seen: set[str] = set()
        unique: list[Block] = []
        for b in blocks:
            if b.code not in seen:
                seen.add(b.code)
                unique.append(b)

        logger.info("Found {} blocks for district {}", len(unique), district_code)
        return unique

    async def fetch_panchayat_list(
        self,
        state_code: str,
        district_code: str,
        block_code: str,
    ) -> list[Panchayat]:
        """Fetch all Gram Panchayats within a block.

        Args:
            state_code: Two-digit NREGA state code.
            district_code: Numeric district code.
            block_code: Numeric block code.

        Returns:
            List of ``Panchayat`` objects.
        """
        state_name = STATE_CODES.get(state_code, "UNKNOWN")
        url = (
            f"{NET_NREGA_BASE}/demregister.aspx"
            f"?lflag=eng&state_code={state_code}&state_name={state_name}"
            f"&district_code={district_code}&block_code={block_code}"
            f"&fin_year={_current_fin_year()}"
        )
        logger.info(
            "Fetching panchayat list for block {} in district {}",
            block_code,
            district_code,
        )
        soup = await self._get_soup(url)

        panchayats: list[Panchayat] = []
        links = _extract_links_from_table(soup)
        for link in links:
            text = link["text"].strip()
            href = link["href"]
            code_match = re.search(
                r"panchayat_code=(\d+)", href, re.IGNORECASE
            ) or re.search(r"pession_code=(\d+)", href, re.IGNORECASE)
            if code_match and text:
                panchayats.append(
                    Panchayat(
                        code=code_match.group(1),
                        name=text,
                        block_code=block_code,
                        district_code=district_code,
                        state_code=state_code,
                    )
                )

        seen: set[str] = set()
        unique: list[Panchayat] = []
        for p in panchayats:
            if p.code not in seen:
                seen.add(p.code)
                unique.append(p)

        logger.info("Found {} panchayats for block {}", len(unique), block_code)
        return unique

    async def fetch_works_list(
        self,
        state_code: str,
        district_code: str,
        block_code: str,
        panchayat_code: str,
        fin_year: Optional[str] = None,
    ) -> list[WorkRecord]:
        """Fetch the work-wise expenditure report (R3.17) for a panchayat.

        Scrapes the work details table which includes work name, type,
        sanctioned amount, expenditure, status, and (where available) GPS
        coordinates of the work site.

        Args:
            state_code: Two-digit NREGA state code.
            district_code: Numeric district code.
            block_code: Numeric block code.
            panchayat_code: Numeric panchayat code.
            fin_year: Financial year string (e.g. ``'2025-2026'``).  Defaults
                to the current financial year.

        Returns:
            List of ``WorkRecord`` objects.
        """
        fin_year = fin_year or _current_fin_year()
        url = REPORT_URLS["R3.17"].format(
            base=BASE_URL,
            state=state_code,
            dist=district_code,
            block=block_code,
            panchayat=panchayat_code,
            fin_year=fin_year,
        )
        logger.info(
            "Fetching works list for panchayat {} (FY {})", panchayat_code, fin_year
        )
        soup = await self._get_soup(url)
        rows = _parse_html_table(soup, skip_header_rows=2)

        works: list[WorkRecord] = []
        for row in rows:
            if len(row) < 6:
                continue

            # Typical column layout for R3.17:
            # [S.No, Work ID/Name, Work Type, Sanctioned Amt, Expenditure, Status, ...]
            work_id = row[1].strip() if len(row) > 1 else ""
            work_name = row[2].strip() if len(row) > 2 else row[1].strip()
            work_type = row[3].strip() if len(row) > 3 else ""
            sanctioned = _safe_float(row[4]) if len(row) > 4 else 0.0
            expenditure = _safe_float(row[5]) if len(row) > 5 else 0.0

            # Status mapping
            raw_status = row[6].strip().lower() if len(row) > 6 else ""
            if "completed" in raw_status or "complete" in raw_status:
                status = WorkStatus.COMPLETED
            elif "ongoing" in raw_status or "progress" in raw_status:
                status = WorkStatus.ONGOING
            elif "not started" in raw_status:
                status = WorkStatus.NOT_STARTED
            elif "shelved" in raw_status:
                status = WorkStatus.SHELVED
            else:
                status = WorkStatus.UNKNOWN

            # GPS coordinates may appear in later columns
            latitude: Optional[float] = None
            longitude: Optional[float] = None
            if len(row) > 8:
                lat_str = row[7].strip()
                lon_str = row[8].strip()
                if lat_str and lon_str:
                    try:
                        latitude = float(lat_str)
                        longitude = float(lon_str)
                    except ValueError:
                        pass

            works.append(
                WorkRecord(
                    work_id=work_id,
                    work_name=work_name,
                    work_type=work_type,
                    sanctioned_amount=sanctioned,
                    expenditure=expenditure,
                    status=status,
                    latitude=latitude,
                    longitude=longitude,
                    panchayat_code=panchayat_code,
                    block_code=block_code,
                    district_code=district_code,
                    state_code=state_code,
                )
            )

        logger.info(
            "Found {} works for panchayat {}", len(works), panchayat_code
        )
        return works

    async def fetch_muster_rolls(
        self,
        work_id: str,
        fin_year: Optional[str] = None,
        *,
        state_code: Optional[str] = None,
        district_code: Optional[str] = None,
        block_code: Optional[str] = None,
        panchayat_code: Optional[str] = None,
    ) -> list[MusterRollEntry]:
        """Fetch muster roll data (R2.2) for a specific work.

        The muster roll is the core attendance-and-payment register. Each row
        represents a worker who was marked present at a worksite for a date
        range, along with the wages disbursed.

        Args:
            work_id: The NREGA work identifier.
            fin_year: Financial year string.  Defaults to current FY.
            state_code: Optional state code for URL construction.
            district_code: Optional district code.
            block_code: Optional block code.
            panchayat_code: Optional panchayat code.

        Returns:
            List of ``MusterRollEntry`` objects.
        """
        fin_year = fin_year or _current_fin_year()

        # Attempt to parse location codes from the work_id if not provided.
        # NREGA work IDs embed the hierarchy: SS/DDDD/BBB/PPP/WWWWWW
        if not state_code:
            parts = work_id.split("/")
            if len(parts) >= 4:
                state_code = parts[0]
                district_code = parts[1] if not district_code else district_code
                block_code = parts[2] if not block_code else block_code
                panchayat_code = parts[3] if not panchayat_code else panchayat_code

        state_code = state_code or "00"
        district_code = district_code or "0000"
        block_code = block_code or "000"
        panchayat_code = panchayat_code or "000"

        url = REPORT_URLS["R2.2"].format(
            base=BASE_URL,
            state=state_code,
            dist=district_code,
            block=block_code,
            panchayat=panchayat_code,
            fin_year=fin_year,
        )
        logger.info("Fetching muster rolls for work {} (FY {})", work_id, fin_year)
        soup = await self._get_soup(url)

        # The muster roll page may require an additional postback to drill down
        # to a specific work.  First try to find a link for the work_id.
        work_link = soup.find("a", string=re.compile(re.escape(work_id)))
        if work_link and isinstance(work_link, Tag) and work_link.get("href"):
            href = work_link["href"]
            if "javascript:__doPostBack" in str(href):
                target_match = re.search(r"__doPostBack\('([^']+)'", str(href))
                if target_match:
                    viewstate = _extract_viewstate(soup)
                    soup = await self._postback(
                        url, viewstate, target_match.group(1)
                    )
            elif str(href).startswith("http"):
                soup = await self._get_soup(str(href))

        rows = _parse_html_table(soup, skip_header_rows=1)
        entries: list[MusterRollEntry] = []
        for row in rows:
            if len(row) < 4:
                continue

            # Typical columns: [S.No, Worker Name, Job Card No, Days Worked,
            #                    Wages Paid, Date From, Date To, Muster No]
            worker_name = row[1].strip() if len(row) > 1 else ""
            jcn = row[2].strip() if len(row) > 2 else ""
            days = _safe_float(row[3]) if len(row) > 3 else 0.0
            wages = _safe_float(row[4]) if len(row) > 4 else 0.0
            date_from = row[5].strip() if len(row) > 5 else None
            date_to = row[6].strip() if len(row) > 6 else None
            muster_no = row[7].strip() if len(row) > 7 else None

            if worker_name and jcn:
                entries.append(
                    MusterRollEntry(
                        worker_name=worker_name,
                        job_card_number=jcn,
                        days_worked=days,
                        wages_paid=wages,
                        date_from=date_from,
                        date_to=date_to,
                        muster_roll_number=muster_no,
                        work_id=work_id,
                    )
                )

        logger.info(
            "Found {} muster roll entries for work {}", len(entries), work_id
        )
        return entries

    async def fetch_fto_status(
        self,
        state_code: str,
        district_code: str,
        block_code: str,
        fin_year: Optional[str] = None,
    ) -> list[FTORecord]:
        """Fetch Fund Transfer Order status report (R5.1).

        FTOs track the actual payment pipeline from government accounts to
        worker bank accounts.  Discrepancies between muster rolls and FTOs are
        a primary fraud signal.

        Args:
            state_code: Two-digit NREGA state code.
            district_code: Numeric district code.
            block_code: Numeric block code.
            fin_year: Financial year string.

        Returns:
            List of ``FTORecord`` objects.
        """
        fin_year = fin_year or _current_fin_year()
        url = REPORT_URLS["R5.1"].format(
            base=BASE_URL,
            state=state_code,
            dist=district_code,
            block=block_code,
            fin_year=fin_year,
        )
        logger.info(
            "Fetching FTO status for block {} (FY {})", block_code, fin_year
        )
        soup = await self._get_soup(url)

        # The FTO page often lists individual FTO numbers as links; clicking
        # each reveals the detail table.  We first collect all FTO links, then
        # scrape details for each.
        fto_links = _extract_links_from_table(soup)
        fto_detail_urls: list[tuple[str, str]] = []
        for link in fto_links:
            href = link["href"]
            text = link["text"]
            if href and text and re.match(r"FTO", text, re.IGNORECASE):
                full_url = (
                    href
                    if href.startswith("http")
                    else urllib.parse.urljoin(url, href)
                )
                fto_detail_urls.append((text, full_url))

        # If no individual FTO links, parse the summary table directly.
        if not fto_detail_urls:
            return self._parse_fto_summary_table(soup, block_code)

        records: list[FTORecord] = []
        for fto_number, detail_url in fto_detail_urls[:50]:  # cap to avoid overload
            try:
                detail_soup = await self._get_soup(detail_url)
                records.extend(
                    self._parse_fto_detail_table(detail_soup, fto_number, block_code)
                )
            except (httpx.HTTPStatusError, httpx.TransportError) as exc:
                logger.warning(
                    "Failed to fetch FTO detail {}: {}", fto_number, exc
                )

        logger.info(
            "Found {} FTO records for block {}", len(records), block_code
        )
        return records

    def _parse_fto_summary_table(
        self, soup: BeautifulSoup, block_code: str
    ) -> list[FTORecord]:
        """Parse an FTO summary page that shows all records inline."""
        rows = _parse_html_table(soup, skip_header_rows=1)
        records: list[FTORecord] = []
        for row in rows:
            if len(row) < 6:
                continue
            records.append(
                FTORecord(
                    fto_number=row[0].strip(),
                    reference_number=row[1].strip() if len(row) > 1 else "",
                    worker_name=row[2].strip() if len(row) > 2 else "",
                    job_card_number=row[3].strip() if len(row) > 3 else "",
                    account_number=row[4].strip() if len(row) > 4 else "",
                    amount=_safe_float(row[5]) if len(row) > 5 else 0.0,
                    status=row[6].strip() if len(row) > 6 else "",
                    transaction_date=row[7].strip() if len(row) > 7 else None,
                    rejection_reason=row[8].strip() if len(row) > 8 else None,
                    block_code=block_code,
                )
            )
        return records

    def _parse_fto_detail_table(
        self, soup: BeautifulSoup, fto_number: str, block_code: str
    ) -> list[FTORecord]:
        """Parse the detail table for a single FTO."""
        rows = _parse_html_table(soup, skip_header_rows=1)
        records: list[FTORecord] = []
        for row in rows:
            if len(row) < 5:
                continue
            records.append(
                FTORecord(
                    fto_number=fto_number,
                    reference_number=row[0].strip(),
                    worker_name=row[1].strip() if len(row) > 1 else "",
                    job_card_number=row[2].strip() if len(row) > 2 else "",
                    account_number=row[3].strip() if len(row) > 3 else "",
                    amount=_safe_float(row[4]) if len(row) > 4 else 0.0,
                    status=row[5].strip() if len(row) > 5 else "",
                    transaction_date=row[6].strip() if len(row) > 6 else None,
                    rejection_reason=row[7].strip() if len(row) > 7 else None,
                    block_code=block_code,
                )
            )
        return records

    async def fetch_worker_details(
        self, job_card_number: str
    ) -> Optional[WorkerDetail]:
        """Fetch detailed worker information from a job card number.

        The job card number encodes the location hierarchy. This method
        navigates to the Job Card Register (R1.1) and extracts the worker's
        personal and employment details.

        Args:
            job_card_number: Full NREGA job card number
                (e.g. ``'RJ-01-001-001-001/123'``).

        Returns:
            A ``WorkerDetail`` object, or ``None`` if not found.
        """
        logger.info("Fetching worker details for JCN {}", job_card_number)

        # Construct the job card detail URL.
        # NREGA job card URLs follow the pattern:
        #   /netnrega/writereaddata/citizen_out/wrkjcrdtl_<state>_<encoded>.html
        # We use the search/index page instead for reliability.
        encoded_jcn = urllib.parse.quote(job_card_number, safe="")
        search_url = (
            f"{NET_NREGA_BASE}/Aborwisejcr.aspx"
            f"?lflag=eng&Jession_code={encoded_jcn}"
        )

        try:
            soup = await self._get_soup(search_url)
        except (httpx.HTTPStatusError, httpx.TransportError) as exc:
            logger.error("Failed to fetch worker details for {}: {}", job_card_number, exc)
            return None

        # Try to locate the worker detail table.
        rows = _parse_html_table(soup, skip_header_rows=1)
        if not rows:
            logger.warning("No data found for JCN {}", job_card_number)
            return None

        # The detail page typically shows one worker per table row with fields:
        # [Name, Father/Husband, Age, Gender, Category, Village, Registration Date]
        row = rows[0]
        return WorkerDetail(
            job_card_number=job_card_number,
            worker_name=row[0].strip() if len(row) > 0 else "",
            father_husband_name=row[1].strip() if len(row) > 1 else "",
            age=_safe_int(row[2]) if len(row) > 2 else None,
            gender=row[3].strip() if len(row) > 3 else None,
            category=row[4].strip() if len(row) > 4 else None,
            village=row[5].strip() if len(row) > 5 else None,
            registration_date=row[6].strip() if len(row) > 6 else None,
        )

    # -- Convenience: hierarchical code extraction --

    async def fetch_full_hierarchy(
        self, state_code: str
    ) -> dict[str, Any]:
        """Fetch the complete district > block > panchayat hierarchy for a state.

        Returns:
            Nested dict: ``{district_code: {block_code: [panchayat_codes]}}``.
        """
        hierarchy: dict[str, Any] = {}
        districts = await self.fetch_district_list(state_code)

        for district in districts:
            hierarchy[district.code] = {"name": district.name, "blocks": {}}
            blocks = await self.fetch_block_list(state_code, district.code)

            for block in blocks:
                panchayats = await self.fetch_panchayat_list(
                    state_code, district.code, block.code
                )
                hierarchy[district.code]["blocks"][block.code] = {
                    "name": block.name,
                    "panchayats": [
                        {"code": p.code, "name": p.name} for p in panchayats
                    ],
                }

        return hierarchy


# ---------------------------------------------------------------------------
# NREGADataPipeline
# ---------------------------------------------------------------------------


@dataclass
class IngestionStats:
    """Tracks statistics for a data ingestion run."""

    state_code: str
    district_code: str
    started_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    blocks_processed: int = 0
    panchayats_processed: int = 0
    works_ingested: int = 0
    muster_entries_ingested: int = 0
    fto_records_ingested: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def duration_seconds(self) -> float:
        end = self.completed_at or datetime.now()
        return (end - self.started_at).total_seconds()


class NREGADataPipeline:
    """Orchestrates full district-level data ingestion from NREGA into the database.

    This pipeline coordinates the scraper, transforms raw scraped data into
    database-ready records, and handles batch inserts with transaction
    management.

    Usage::

        pipeline = NREGADataPipeline(db_session=session)
        stats = await pipeline.ingest_district("34", "3401")
    """

    def __init__(
        self,
        db_session: Any = None,
        *,
        fin_year: Optional[str] = None,
        max_concurrent_blocks: int = 3,
        max_concurrent_panchayats: int = 5,
        scrape_muster_rolls: bool = True,
        scrape_fto: bool = True,
    ) -> None:
        """Initialize the ingestion pipeline.

        Args:
            db_session: SQLAlchemy async session or compatible database handle.
                If ``None``, records are collected in memory only.
            fin_year: Target financial year.  Defaults to current.
            max_concurrent_blocks: Max blocks scraped in parallel.
            max_concurrent_panchayats: Max panchayats scraped per block.
            scrape_muster_rolls: Whether to also fetch muster roll data.
            scrape_fto: Whether to also fetch FTO data per block.
        """
        self._db = db_session
        self._fin_year = fin_year or _current_fin_year()
        self._block_semaphore = asyncio.Semaphore(max_concurrent_blocks)
        self._panchayat_semaphore = asyncio.Semaphore(max_concurrent_panchayats)
        self._scrape_musters = scrape_muster_rolls
        self._scrape_fto = scrape_fto

        # In-memory accumulation when no DB session is provided.
        self.works: list[WorkRecord] = []
        self.muster_entries: list[MusterRollEntry] = []
        self.fto_records: list[FTORecord] = []

    async def ingest_district(
        self,
        state_code: str,
        district_code: str,
        *,
        block_codes: Optional[list[str]] = None,
    ) -> IngestionStats:
        """Run a full ingestion for one district.

        Scrapes the block and panchayat hierarchy, then for each panchayat
        fetches works, muster rolls, and FTO records.

        Args:
            state_code: Two-digit NREGA state code.
            district_code: Numeric district code.
            block_codes: Optional list of specific block codes to process.
                If ``None``, all blocks in the district are processed.

        Returns:
            ``IngestionStats`` summarising the run.
        """
        stats = IngestionStats(state_code=state_code, district_code=district_code)
        logger.info(
            "Starting district ingestion: state={}, district={}, fin_year={}",
            state_code,
            district_code,
            self._fin_year,
        )

        async with NREGAScraper() as scraper:
            # 1. Fetch blocks
            blocks = await scraper.fetch_block_list(state_code, district_code)
            if block_codes:
                blocks = [b for b in blocks if b.code in block_codes]

            # 2. Process blocks concurrently
            tasks = [
                self._process_block(scraper, block, stats)
                for block in blocks
            ]
            await asyncio.gather(*tasks, return_exceptions=True)

        stats.completed_at = datetime.now()
        logger.info(
            "District ingestion complete: {} blocks, {} panchayats, {} works, "
            "{} muster entries, {} FTO records in {:.1f}s",
            stats.blocks_processed,
            stats.panchayats_processed,
            stats.works_ingested,
            stats.muster_entries_ingested,
            stats.fto_records_ingested,
            stats.duration_seconds,
        )
        return stats

    async def _process_block(
        self,
        scraper: NREGAScraper,
        block: Block,
        stats: IngestionStats,
    ) -> None:
        """Process all panchayats within a single block."""
        async with self._block_semaphore:
            logger.info("Processing block {} ({})", block.code, block.name)
            try:
                panchayats = await scraper.fetch_panchayat_list(
                    block.state_code, block.district_code, block.code
                )
            except Exception as exc:
                msg = f"Failed to fetch panchayats for block {block.code}: {exc}"
                logger.error(msg)
                stats.errors.append(msg)
                return

            # Process panchayats concurrently
            tasks = [
                self._process_panchayat(scraper, panchayat, stats)
                for panchayat in panchayats
            ]
            await asyncio.gather(*tasks, return_exceptions=True)

            # Fetch FTO data at block level
            if self._scrape_fto:
                try:
                    fto_records = await scraper.fetch_fto_status(
                        block.state_code,
                        block.district_code,
                        block.code,
                        self._fin_year,
                    )
                    self.fto_records.extend(fto_records)
                    stats.fto_records_ingested += len(fto_records)
                    await self._persist_fto_records(fto_records)
                except Exception as exc:
                    msg = f"Failed to fetch FTO for block {block.code}: {exc}"
                    logger.error(msg)
                    stats.errors.append(msg)

            stats.blocks_processed += 1

    async def _process_panchayat(
        self,
        scraper: NREGAScraper,
        panchayat: Panchayat,
        stats: IngestionStats,
    ) -> None:
        """Process a single panchayat: fetch works and muster rolls."""
        async with self._panchayat_semaphore:
            try:
                works = await scraper.fetch_works_list(
                    panchayat.state_code,
                    panchayat.district_code,
                    panchayat.block_code,
                    panchayat.code,
                    self._fin_year,
                )
                self.works.extend(works)
                stats.works_ingested += len(works)
                await self._persist_works(works)

                # Optionally fetch muster rolls for each work
                if self._scrape_musters:
                    for work in works:
                        try:
                            musters = await scraper.fetch_muster_rolls(
                                work.work_id,
                                self._fin_year,
                                state_code=panchayat.state_code,
                                district_code=panchayat.district_code,
                                block_code=panchayat.block_code,
                                panchayat_code=panchayat.code,
                            )
                            self.muster_entries.extend(musters)
                            stats.muster_entries_ingested += len(musters)
                            await self._persist_muster_entries(musters)
                        except Exception as exc:
                            msg = (
                                f"Failed muster roll for work "
                                f"{work.work_id}: {exc}"
                            )
                            logger.warning(msg)
                            stats.errors.append(msg)

                stats.panchayats_processed += 1

            except Exception as exc:
                msg = f"Failed to process panchayat {panchayat.code}: {exc}"
                logger.error(msg)
                stats.errors.append(msg)

    # -- Database persistence stubs ----------------------------------------
    # These methods integrate with whatever ORM / database layer the wider
    # system provides.  When ``self._db`` is None, they are no-ops and the
    # data remains in the in-memory lists above.

    async def _persist_works(self, works: list[WorkRecord]) -> None:
        """Insert or upsert work records into the database."""
        if self._db is None:
            return
        try:
            for work in works:
                record = {
                    "work_id": work.work_id,
                    "work_name": work.work_name,
                    "work_type": work.work_type,
                    "sanctioned_amount": work.sanctioned_amount,
                    "expenditure": work.expenditure,
                    "status": work.status.value,
                    "latitude": work.latitude,
                    "longitude": work.longitude,
                    "state_code": work.state_code,
                    "district_code": work.district_code,
                    "block_code": work.block_code,
                    "panchayat_code": work.panchayat_code,
                    "fin_year": self._fin_year,
                    "ingested_at": datetime.utcnow().isoformat(),
                }
                await self._db.execute(
                    """INSERT INTO nrega_works
                       (work_id, work_name, work_type, sanctioned_amount,
                        expenditure, status, latitude, longitude, state_code,
                        district_code, block_code, panchayat_code, fin_year,
                        ingested_at)
                       VALUES (:work_id, :work_name, :work_type,
                               :sanctioned_amount, :expenditure, :status,
                               :latitude, :longitude, :state_code,
                               :district_code, :block_code, :panchayat_code,
                               :fin_year, :ingested_at)
                       ON CONFLICT (work_id, fin_year)
                       DO UPDATE SET expenditure = :expenditure,
                                     status = :status,
                                     ingested_at = :ingested_at""",
                    record,
                )
            await self._db.commit()
        except Exception as exc:
            logger.error("DB persist works failed: {}", exc)
            await self._db.rollback()
            raise

    async def _persist_muster_entries(
        self, entries: list[MusterRollEntry]
    ) -> None:
        """Insert muster roll entries into the database."""
        if self._db is None:
            return
        try:
            for entry in entries:
                record = {
                    "work_id": entry.work_id,
                    "worker_name": entry.worker_name,
                    "job_card_number": entry.job_card_number,
                    "days_worked": entry.days_worked,
                    "wages_paid": entry.wages_paid,
                    "date_from": entry.date_from,
                    "date_to": entry.date_to,
                    "muster_roll_number": entry.muster_roll_number,
                    "ingested_at": datetime.utcnow().isoformat(),
                }
                await self._db.execute(
                    """INSERT INTO muster_rolls
                       (work_id, worker_name, job_card_number, days_worked,
                        wages_paid, date_from, date_to, muster_roll_number,
                        ingested_at)
                       VALUES (:work_id, :worker_name, :job_card_number,
                               :days_worked, :wages_paid, :date_from,
                               :date_to, :muster_roll_number, :ingested_at)""",
                    record,
                )
            await self._db.commit()
        except Exception as exc:
            logger.error("DB persist muster entries failed: {}", exc)
            await self._db.rollback()
            raise

    async def _persist_fto_records(self, records: list[FTORecord]) -> None:
        """Insert FTO records into the database."""
        if self._db is None:
            return
        try:
            for rec in records:
                record = {
                    "fto_number": rec.fto_number,
                    "reference_number": rec.reference_number,
                    "worker_name": rec.worker_name,
                    "job_card_number": rec.job_card_number,
                    "account_number": rec.account_number,
                    "amount": rec.amount,
                    "status": rec.status,
                    "transaction_date": rec.transaction_date,
                    "rejection_reason": rec.rejection_reason,
                    "block_code": rec.block_code,
                    "ingested_at": datetime.utcnow().isoformat(),
                }
                await self._db.execute(
                    """INSERT INTO fto_records
                       (fto_number, reference_number, worker_name,
                        job_card_number, account_number, amount, status,
                        transaction_date, rejection_reason, block_code,
                        ingested_at)
                       VALUES (:fto_number, :reference_number, :worker_name,
                               :job_card_number, :account_number, :amount,
                               :status, :transaction_date, :rejection_reason,
                               :block_code, :ingested_at)""",
                    record,
                )
            await self._db.commit()
        except Exception as exc:
            logger.error("DB persist FTO records failed: {}", exc)
            await self._db.rollback()
            raise

    async def ingest_state(
        self,
        state_code: str,
        *,
        district_codes: Optional[list[str]] = None,
        max_concurrent_districts: int = 2,
    ) -> list[IngestionStats]:
        """Run ingestion across all districts in a state.

        Args:
            state_code: Two-digit NREGA state code.
            district_codes: Optional list to restrict to specific districts.
            max_concurrent_districts: Parallelism limit for districts.

        Returns:
            List of ``IngestionStats``, one per district.
        """
        async with NREGAScraper() as scraper:
            districts = await scraper.fetch_district_list(state_code)

        if district_codes:
            districts = [d for d in districts if d.code in district_codes]

        sem = asyncio.Semaphore(max_concurrent_districts)
        all_stats: list[IngestionStats] = []

        async def _run_district(dist: District) -> IngestionStats:
            async with sem:
                return await self.ingest_district(state_code, dist.code)

        results = await asyncio.gather(
            *[_run_district(d) for d in districts], return_exceptions=True
        )
        for result in results:
            if isinstance(result, IngestionStats):
                all_stats.append(result)
            elif isinstance(result, Exception):
                logger.error("District ingestion failed: {}", result)

        return all_stats
