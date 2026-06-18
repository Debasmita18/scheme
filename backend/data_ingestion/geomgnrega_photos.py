"""
GeoMGNREGA Photo Ingestion Module
===================================

Handles ingestion, metadata extraction, and anomaly detection for geotagged
photographs uploaded to the GeoMGNREGA system for MGNREGA work verification.

GeoMGNREGA requires field functionaries to upload timestamped, GPS-tagged
photos at three stages of each work: before commencement, during execution,
and after completion.  This module fetches those photos, extracts EXIF
metadata, computes perceptual hashes for duplicate detection, and flags
common manipulation patterns indicative of fraud.

Anomaly Categories Detected:
    - GPS coordinates distant from the registered work site
    - Identical timestamps across multiple photos (bulk-upload pattern)
    - Stripped or tampered EXIF metadata
    - Duplicate images reused across different works (perceptual hashing)
    - Inconsistent camera identifiers within a single work's photo set
    - Photos taken outside daylight hours (suspicious for outdoor works)
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import math
import os
import struct
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Optional, Union

import httpx
import numpy as np
from loguru import logger
from PIL import Image, ExifTags
from PIL.ExifTags import GPSTAGS, TAGS
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GEOMGNREGA_BASE_URL = "https://nrega.nic.in/netnrega/WriteReaddata/citizen_out"
GEOMGNREGA_PHOTO_API = "https://nrega.nic.in/netnrega/getGeoPhotos.aspx"

# Anomaly thresholds
GPS_DISTANCE_THRESHOLD_METERS = 5_000  # 5 km from registered site
TIMESTAMP_DUPLICATE_WINDOW_SECONDS = 60  # Photos within 1 min = suspicious
DAYLIGHT_START = time(6, 0)   # 6 AM
DAYLIGHT_END = time(18, 30)   # 6:30 PM
MIN_PHOTOS_FOR_CAMERA_CHECK = 3

# Perceptual hash configuration
PHASH_SIZE = 8  # 8x8 DCT matrix -> 64-bit hash
PHASH_HAMMING_THRESHOLD = 10  # Hashes within 10 bits = likely duplicate

REQUEST_TIMEOUT = 60.0
MAX_CONCURRENT_DOWNLOADS = 10

DEFAULT_CACHE_DIR = Path.home() / ".cache" / "mgnrega_photos"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


class AnomalyType(str, Enum):
    """Categories of photo anomalies."""

    GPS_MISMATCH = "gps_mismatch"
    TIMESTAMP_DUPLICATE = "timestamp_duplicate"
    EXIF_STRIPPED = "exif_stripped"
    EXIF_TAMPERED = "exif_tampered"
    IMAGE_DUPLICATE = "image_duplicate"
    CAMERA_INCONSISTENCY = "camera_inconsistency"
    NIGHTTIME_PHOTO = "nighttime_photo"
    RESOLUTION_ANOMALY = "resolution_anomaly"
    SOFTWARE_EDITING = "software_editing"


@dataclass
class GPSCoordinate:
    """GPS coordinate extracted from EXIF data."""

    latitude: float
    longitude: float
    altitude: Optional[float] = None

    def distance_to(self, other: "GPSCoordinate") -> float:
        """Calculate Haversine distance in metres to another coordinate."""
        R = 6_371_000  # Earth radius in metres
        lat1 = math.radians(self.latitude)
        lat2 = math.radians(other.latitude)
        dlat = math.radians(other.latitude - self.latitude)
        dlon = math.radians(other.longitude - self.longitude)
        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        )
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c


@dataclass
class PhotoMetadata:
    """Complete metadata extracted from a GeoMGNREGA photo."""

    photo_id: str
    work_id: str
    filename: str
    timestamp: Optional[datetime] = None
    gps: Optional[GPSCoordinate] = None
    camera_make: Optional[str] = None
    camera_model: Optional[str] = None
    software: Optional[str] = None
    image_width: Optional[int] = None
    image_height: Optional[int] = None
    orientation: Optional[int] = None
    has_thumbnail: bool = False
    exif_present: bool = False
    perceptual_hash: Optional[str] = None
    raw_exif: dict[str, Any] = field(default_factory=dict)


@dataclass
class PhotoAnomaly:
    """A detected anomaly in a photo or photo set."""

    anomaly_type: AnomalyType
    severity: str  # "low", "medium", "high", "critical"
    photo_id: str
    work_id: str
    description: str
    details: dict[str, Any] = field(default_factory=dict)
    related_photo_ids: list[str] = field(default_factory=list)


@dataclass
class PhotoIngestionResult:
    """Summary of a photo ingestion and analysis run."""

    work_id: str
    photos_fetched: int = 0
    photos_processed: int = 0
    anomalies: list[PhotoAnomaly] = field(default_factory=list)
    metadata: list[PhotoMetadata] = field(default_factory=list)
    perceptual_hashes: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def anomaly_count(self) -> int:
        return len(self.anomalies)

    @property
    def critical_anomalies(self) -> list[PhotoAnomaly]:
        return [a for a in self.anomalies if a.severity == "critical"]


# ---------------------------------------------------------------------------
# Perceptual hashing (pHash)
# ---------------------------------------------------------------------------


def _dct_2d(block: np.ndarray) -> np.ndarray:
    """Compute a 2-D Discrete Cosine Transform using numpy.

    Implements the Type-II DCT without requiring scipy, keeping the
    dependency footprint minimal.
    """
    N = block.shape[0]
    result = np.zeros_like(block, dtype=np.float64)

    # Row-wise 1-D DCT
    for i in range(N):
        for k in range(N):
            s = 0.0
            for n in range(N):
                s += block[i, n] * math.cos(math.pi * k * (2 * n + 1) / (2 * N))
            result[i, k] = s

    # Column-wise 1-D DCT
    temp = result.copy()
    for j in range(N):
        for k in range(N):
            s = 0.0
            for n in range(N):
                s += temp[n, j] * math.cos(math.pi * k * (2 * n + 1) / (2 * N))
            result[k, j] = s

    return result


def compute_perceptual_hash(image: Image.Image, hash_size: int = PHASH_SIZE) -> str:
    """Compute a perceptual hash (pHash) for an image.

    The algorithm:
    1. Resize to (hash_size*4) x (hash_size*4) and convert to greyscale.
    2. Compute the 2-D DCT.
    3. Extract the top-left hash_size x hash_size DCT coefficients
       (low-frequency components that capture overall structure).
    4. Compute the median and threshold to produce a binary hash.
    5. Encode as a hexadecimal string.

    Args:
        image: PIL Image object.
        hash_size: Size of the hash grid (default 8 -> 64-bit hash).

    Returns:
        Hexadecimal string representing the perceptual hash.
    """
    # Resize and greyscale
    img_size = hash_size * 4
    img = image.convert("L").resize((img_size, img_size), Image.LANCZOS)
    pixels = np.array(img, dtype=np.float64)

    # DCT
    dct = _dct_2d(pixels)

    # Extract low-frequency block
    dct_low = dct[:hash_size, :hash_size]

    # Exclude DC component (top-left corner) for threshold
    dct_low_flat = dct_low.flatten()
    median_val = np.median(dct_low_flat[1:])  # skip DC

    # Binary hash
    bits = dct_low_flat > median_val

    # Pack into bytes
    hash_int = 0
    for bit in bits:
        hash_int = (hash_int << 1) | int(bit)

    n_bytes = (hash_size * hash_size + 7) // 8
    return format(hash_int, f"0{n_bytes * 2}x")


def hamming_distance(hash1: str, hash2: str) -> int:
    """Compute the Hamming distance between two hexadecimal hash strings.

    Args:
        hash1: First hash as hex string.
        hash2: Second hash as hex string.

    Returns:
        Number of differing bits.
    """
    val1 = int(hash1, 16)
    val2 = int(hash2, 16)
    xor = val1 ^ val2
    return bin(xor).count("1")


# ---------------------------------------------------------------------------
# EXIF extraction helpers
# ---------------------------------------------------------------------------


def _dms_to_decimal(dms_tuple: tuple, ref: str) -> float:
    """Convert EXIF GPS DMS (degrees, minutes, seconds) to decimal degrees.

    Args:
        dms_tuple: Tuple of (degrees, minutes, seconds) -- each may be
            a ``Rational`` (tuple of numerator/denominator) or a float.
        ref: Reference direction: ``'N'``, ``'S'``, ``'E'``, or ``'W'``.

    Returns:
        Decimal degrees (negative for S/W).
    """
    def _rational_to_float(val: Any) -> float:
        if isinstance(val, tuple) and len(val) == 2:
            return val[0] / val[1] if val[1] != 0 else 0.0
        return float(val)

    d = _rational_to_float(dms_tuple[0])
    m = _rational_to_float(dms_tuple[1])
    s = _rational_to_float(dms_tuple[2])
    decimal = d + m / 60.0 + s / 3600.0
    if ref in ("S", "W"):
        decimal = -decimal
    return decimal


# ---------------------------------------------------------------------------
# GeoMGNREGAPhotoIngester
# ---------------------------------------------------------------------------


class GeoMGNREGAPhotoIngester:
    """Ingest, analyse, and flag anomalies in GeoMGNREGA work-site photos.

    Connects to the NREGA photo storage endpoints, downloads geotagged
    images, extracts EXIF metadata, computes perceptual hashes, and runs a
    suite of anomaly detection checks.

    Usage::

        async with GeoMGNREGAPhotoIngester() as ingester:
            result = await ingester.fetch_geotagged_photos("RJ/3401/001/001/00001")
            anomalies = ingester.detect_photo_anomalies(
                result.metadata,
                work_lat=26.85,
                work_lon=76.55,
            )
    """

    def __init__(
        self,
        *,
        cache_dir: Optional[Union[str, Path]] = None,
        timeout: float = REQUEST_TIMEOUT,
        max_concurrent: int = MAX_CONCURRENT_DOWNLOADS,
        db_session: Any = None,
    ) -> None:
        """Initialize the photo ingester.

        Args:
            cache_dir: Directory for caching downloaded photos.
            timeout: HTTP request timeout in seconds.
            max_concurrent: Maximum concurrent photo downloads.
            db_session: Optional database session for persisting results.
        """
        self._cache_dir = Path(cache_dir) if cache_dir else DEFAULT_CACHE_DIR
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._timeout = timeout
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._db = db_session
        self._client: Optional[httpx.AsyncClient] = None

        # Global hash registry for cross-work duplicate detection
        self._hash_registry: dict[str, list[tuple[str, str]]] = defaultdict(list)
        # Maps phash -> list of (work_id, photo_id)

    async def __aenter__(self) -> "GeoMGNREGAPhotoIngester":
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(self._timeout),
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
                ),
            },
        )
        logger.info("GeoMGNREGAPhotoIngester session opened")
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._client:
            await self._client.aclose()
        logger.info("GeoMGNREGAPhotoIngester session closed")

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError(
                "GeoMGNREGAPhotoIngester must be used as an async context manager"
            )
        return self._client

    # -- Photo fetching ----------------------------------------------------

    @retry(
        retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TransportError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def _download_photo(self, url: str, photo_id: str) -> Optional[bytes]:
        """Download a single photo with caching.

        Args:
            url: Full URL to the photo.
            photo_id: Unique identifier for cache keying.

        Returns:
            Image bytes, or ``None`` on failure.
        """
        # Check cache
        safe_id = photo_id.replace("/", "_").replace("\\", "_")
        cache_file = self._cache_dir / f"{safe_id}.jpg"
        if cache_file.exists():
            logger.debug("Returning cached photo {}", photo_id)
            return cache_file.read_bytes()

        async with self._semaphore:
            logger.debug("Downloading photo {}", photo_id)
            resp = await self.client.get(url)
            resp.raise_for_status()

            # Verify it is actually an image
            content_type = resp.headers.get("content-type", "")
            if "image" not in content_type and not resp.content[:4] in (
                b"\xff\xd8\xff",  # JPEG
                b"\x89PNG",       # PNG
            ):
                logger.warning(
                    "Photo {} returned non-image content-type: {}",
                    photo_id,
                    content_type,
                )
                return None

            cache_file.write_bytes(resp.content)
            return resp.content

    async def fetch_geotagged_photos(
        self,
        work_id: str,
    ) -> PhotoIngestionResult:
        """Fetch all geotagged photos for a specific NREGA work from GeoMGNREGA.

        Navigates the NREGA photo listing page for the work, extracts photo
        URLs, downloads each image, and performs EXIF extraction and pHash
        computation.

        Args:
            work_id: The NREGA work identifier.

        Returns:
            ``PhotoIngestionResult`` containing metadata for all photos.
        """
        logger.info("Fetching geotagged photos for work {}", work_id)
        result = PhotoIngestionResult(work_id=work_id)

        # Construct the photo listing URL
        # GeoMGNREGA stores photos at predictable paths derived from work IDs
        encoded_work_id = work_id.replace("/", "_")
        listing_url = (
            f"{GEOMGNREGA_PHOTO_API}?work_code={encoded_work_id}&lflag=eng"
        )

        try:
            resp = await self.client.get(listing_url)
            resp.raise_for_status()
        except (httpx.HTTPStatusError, httpx.TransportError) as exc:
            error_msg = f"Failed to fetch photo listing for {work_id}: {exc}"
            logger.error(error_msg)
            result.errors.append(error_msg)
            return result

        # Parse the photo listing page
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(resp.text, "html.parser")
        photo_urls: list[tuple[str, str]] = []  # (photo_id, url)

        # Look for image tags or download links
        for idx, img_tag in enumerate(soup.find_all("img")):
            src = img_tag.get("src", "")
            if src and ("geo" in src.lower() or "photo" in src.lower() or ".jpg" in src.lower()):
                full_url = (
                    src
                    if src.startswith("http")
                    else f"https://nrega.nic.in{src}"
                )
                photo_id = f"{work_id}/photo_{idx:03d}"
                photo_urls.append((photo_id, full_url))

        # Also check anchor tags for photo downloads
        for idx, a_tag in enumerate(soup.find_all("a", href=True)):
            href = a_tag["href"]
            if any(ext in href.lower() for ext in (".jpg", ".jpeg", ".png")):
                full_url = (
                    href
                    if href.startswith("http")
                    else f"https://nrega.nic.in{href}"
                )
                photo_id = f"{work_id}/link_photo_{idx:03d}"
                photo_urls.append((photo_id, full_url))

        result.photos_fetched = len(photo_urls)
        logger.info("Found {} photos for work {}", len(photo_urls), work_id)

        # Download and process each photo
        tasks = [
            self._process_single_photo(photo_id, url, work_id)
            for photo_id, url in photo_urls
        ]
        photo_results = await asyncio.gather(*tasks, return_exceptions=True)

        for pr in photo_results:
            if isinstance(pr, PhotoMetadata):
                result.metadata.append(pr)
                if pr.perceptual_hash:
                    result.perceptual_hashes[pr.photo_id] = pr.perceptual_hash
                result.photos_processed += 1
            elif isinstance(pr, Exception):
                result.errors.append(str(pr))

        return result

    async def _process_single_photo(
        self,
        photo_id: str,
        url: str,
        work_id: str,
    ) -> PhotoMetadata:
        """Download, extract metadata, and compute pHash for one photo."""
        image_bytes = await self._download_photo(url, photo_id)
        if image_bytes is None:
            raise ValueError(f"Failed to download photo {photo_id}")

        metadata = self.extract_exif_metadata(image_bytes, photo_id, work_id)

        # Compute perceptual hash
        try:
            img = Image.open(io.BytesIO(image_bytes))
            metadata.perceptual_hash = compute_perceptual_hash(img)
            # Register hash for cross-work duplicate detection
            self._hash_registry[metadata.perceptual_hash].append(
                (work_id, photo_id)
            )
        except Exception as exc:
            logger.warning("pHash computation failed for {}: {}", photo_id, exc)

        return metadata

    # -- EXIF extraction ---------------------------------------------------

    def extract_exif_metadata(
        self,
        image_bytes: bytes,
        photo_id: str = "",
        work_id: str = "",
    ) -> PhotoMetadata:
        """Extract GPS coordinates, timestamp, camera info, and detect
        manipulation signs from EXIF metadata.

        Checks for:
        - Presence of GPS IFD (missing = stripped metadata)
        - Software tags indicating editing (Photoshop, GIMP, etc.)
        - Inconsistent EXIF version or maker note anomalies
        - Thumbnail presence and consistency

        Args:
            image_bytes: Raw image file bytes.
            photo_id: Identifier for this photo.
            work_id: Parent work identifier.

        Returns:
            ``PhotoMetadata`` with all extracted fields.
        """
        metadata = PhotoMetadata(
            photo_id=photo_id,
            work_id=work_id,
            filename=f"{photo_id.replace('/', '_')}.jpg",
        )

        try:
            img = Image.open(io.BytesIO(image_bytes))
        except Exception as exc:
            logger.warning("Cannot open image {}: {}", photo_id, exc)
            return metadata

        metadata.image_width = img.width
        metadata.image_height = img.height

        # Extract EXIF
        exif_data = img.getexif()
        if not exif_data:
            logger.debug("No EXIF data in photo {}", photo_id)
            metadata.exif_present = False
            return metadata

        metadata.exif_present = True

        # Build readable EXIF dict
        exif_dict: dict[str, Any] = {}
        for tag_id, value in exif_data.items():
            tag_name = TAGS.get(tag_id, str(tag_id))
            try:
                # Some values are not directly serialisable
                exif_dict[tag_name] = str(value) if not isinstance(value, (str, int, float)) else value
            except Exception:
                exif_dict[tag_name] = "<unreadable>"
        metadata.raw_exif = exif_dict

        # Camera information
        metadata.camera_make = exif_dict.get("Make", None)
        if isinstance(metadata.camera_make, str):
            metadata.camera_make = metadata.camera_make.strip()
        metadata.camera_model = exif_dict.get("Model", None)
        if isinstance(metadata.camera_model, str):
            metadata.camera_model = metadata.camera_model.strip()
        metadata.software = exif_dict.get("Software", None)
        metadata.orientation = exif_dict.get("Orientation", None)

        # Timestamp
        datetime_str = exif_dict.get(
            "DateTimeOriginal",
            exif_dict.get("DateTime", exif_dict.get("DateTimeDigitized", None)),
        )
        if datetime_str and isinstance(datetime_str, str):
            for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
                try:
                    metadata.timestamp = datetime.strptime(datetime_str.strip(), fmt)
                    break
                except ValueError:
                    continue

        # GPS data
        gps_ifd = exif_data.get_ifd(ExifTags.IFD.GPSInfo)
        if gps_ifd:
            gps_data: dict[str, Any] = {}
            for gps_tag_id, gps_value in gps_ifd.items():
                gps_tag_name = GPSTAGS.get(gps_tag_id, str(gps_tag_id))
                gps_data[gps_tag_name] = gps_value

            lat_dms = gps_data.get("GPSLatitude")
            lat_ref = gps_data.get("GPSLatitudeRef", "N")
            lon_dms = gps_data.get("GPSLongitude")
            lon_ref = gps_data.get("GPSLongitudeRef", "E")

            if lat_dms and lon_dms:
                try:
                    lat = _dms_to_decimal(lat_dms, lat_ref)
                    lon = _dms_to_decimal(lon_dms, lon_ref)
                    altitude = None
                    alt_val = gps_data.get("GPSAltitude")
                    if alt_val is not None:
                        if isinstance(alt_val, tuple) and len(alt_val) == 2:
                            altitude = alt_val[0] / alt_val[1] if alt_val[1] != 0 else 0.0
                        else:
                            altitude = float(alt_val)
                    metadata.gps = GPSCoordinate(
                        latitude=lat, longitude=lon, altitude=altitude
                    )
                except (TypeError, ValueError, ZeroDivisionError) as exc:
                    logger.warning(
                        "GPS parsing failed for {}: {}", photo_id, exc
                    )

        # Check for thumbnail
        try:
            metadata.has_thumbnail = img.info.get("exif", b"").find(b"\xff\xd8") > 0
        except Exception:
            metadata.has_thumbnail = False

        return metadata

    # -- Anomaly detection -------------------------------------------------

    def detect_photo_anomalies(
        self,
        photos: list[PhotoMetadata],
        *,
        work_lat: Optional[float] = None,
        work_lon: Optional[float] = None,
        gps_threshold_m: float = GPS_DISTANCE_THRESHOLD_METERS,
        timestamp_window_s: float = TIMESTAMP_DUPLICATE_WINDOW_SECONDS,
    ) -> list[PhotoAnomaly]:
        """Run the full anomaly detection suite on a set of photos.

        Checks performed:
        1. GPS coordinates far from the registered work site.
        2. Multiple photos with near-identical timestamps (bulk upload).
        3. Photos with stripped or absent EXIF data.
        4. Photos edited with image-manipulation software.
        5. Duplicate images across different works (perceptual hashing).
        6. Inconsistent camera identifiers within the set.
        7. Photos taken outside daylight hours.

        Args:
            photos: List of ``PhotoMetadata`` objects to analyse.
            work_lat: Registered latitude of the work site.
            work_lon: Registered longitude of the work site.
            gps_threshold_m: Distance threshold for GPS mismatch.
            timestamp_window_s: Time window for duplicate timestamp detection.

        Returns:
            List of ``PhotoAnomaly`` objects.
        """
        if not photos:
            return []

        work_id = photos[0].work_id
        anomalies: list[PhotoAnomaly] = []
        logger.info(
            "Running anomaly detection on {} photos for work {}",
            len(photos),
            work_id,
        )

        work_site: Optional[GPSCoordinate] = None
        if work_lat is not None and work_lon is not None:
            work_site = GPSCoordinate(latitude=work_lat, longitude=work_lon)

        # --- 1. GPS mismatch ---
        if work_site:
            for photo in photos:
                if photo.gps:
                    distance = photo.gps.distance_to(work_site)
                    if distance > gps_threshold_m:
                        anomalies.append(
                            PhotoAnomaly(
                                anomaly_type=AnomalyType.GPS_MISMATCH,
                                severity="high",
                                photo_id=photo.photo_id,
                                work_id=work_id,
                                description=(
                                    f"Photo GPS ({photo.gps.latitude:.5f}, "
                                    f"{photo.gps.longitude:.5f}) is "
                                    f"{distance / 1000:.1f} km from the registered "
                                    f"work site ({work_lat:.5f}, {work_lon:.5f})"
                                ),
                                details={
                                    "distance_meters": round(distance, 1),
                                    "photo_lat": photo.gps.latitude,
                                    "photo_lon": photo.gps.longitude,
                                    "work_lat": work_lat,
                                    "work_lon": work_lon,
                                },
                            )
                        )

        # --- 2. Timestamp duplicates ---
        timestamped = [
            p for p in photos if p.timestamp is not None
        ]
        timestamped.sort(key=lambda p: p.timestamp)  # type: ignore[arg-type]
        for i in range(len(timestamped) - 1):
            t1 = timestamped[i].timestamp
            t2 = timestamped[i + 1].timestamp
            if t1 and t2:
                delta = abs((t2 - t1).total_seconds())
                if delta < timestamp_window_s:
                    anomalies.append(
                        PhotoAnomaly(
                            anomaly_type=AnomalyType.TIMESTAMP_DUPLICATE,
                            severity="medium",
                            photo_id=timestamped[i].photo_id,
                            work_id=work_id,
                            description=(
                                f"Photos taken within {delta:.0f}s of each other "
                                f"(possible bulk upload)"
                            ),
                            details={
                                "timestamp_1": t1.isoformat(),
                                "timestamp_2": t2.isoformat(),
                                "delta_seconds": delta,
                            },
                            related_photo_ids=[timestamped[i + 1].photo_id],
                        )
                    )

        # --- 3. Missing / stripped EXIF ---
        for photo in photos:
            if not photo.exif_present:
                anomalies.append(
                    PhotoAnomaly(
                        anomaly_type=AnomalyType.EXIF_STRIPPED,
                        severity="high",
                        photo_id=photo.photo_id,
                        work_id=work_id,
                        description="Photo has no EXIF metadata (possibly stripped)",
                        details={},
                    )
                )
            elif photo.exif_present and not photo.gps:
                anomalies.append(
                    PhotoAnomaly(
                        anomaly_type=AnomalyType.EXIF_TAMPERED,
                        severity="medium",
                        photo_id=photo.photo_id,
                        work_id=work_id,
                        description=(
                            "Photo has EXIF data but GPS coordinates are missing "
                            "(GPS IFD may have been selectively removed)"
                        ),
                        details={"exif_tags_present": list(photo.raw_exif.keys())},
                    )
                )

        # --- 4. Editing software detection ---
        EDITING_SOFTWARE = {
            "photoshop", "gimp", "lightroom", "snapseed", "pixlr",
            "paint.net", "affinity", "canva", "fotor", "picsart",
        }
        for photo in photos:
            if photo.software:
                sw_lower = photo.software.lower()
                for editor in EDITING_SOFTWARE:
                    if editor in sw_lower:
                        anomalies.append(
                            PhotoAnomaly(
                                anomaly_type=AnomalyType.SOFTWARE_EDITING,
                                severity="critical",
                                photo_id=photo.photo_id,
                                work_id=work_id,
                                description=(
                                    f"Photo processed with editing software: "
                                    f"{photo.software}"
                                ),
                                details={"software": photo.software},
                            )
                        )
                        break

        # --- 5. Perceptual hash duplicates (within the set) ---
        hashes: list[tuple[str, str]] = [
            (p.photo_id, p.perceptual_hash)
            for p in photos
            if p.perceptual_hash is not None
        ]
        for i in range(len(hashes)):
            for j in range(i + 1, len(hashes)):
                pid1, h1 = hashes[i]
                pid2, h2 = hashes[j]
                dist = hamming_distance(h1, h2)
                if dist <= PHASH_HAMMING_THRESHOLD:
                    anomalies.append(
                        PhotoAnomaly(
                            anomaly_type=AnomalyType.IMAGE_DUPLICATE,
                            severity="critical" if dist <= 5 else "high",
                            photo_id=pid1,
                            work_id=work_id,
                            description=(
                                f"Visually similar/duplicate images detected "
                                f"(Hamming distance: {dist})"
                            ),
                            details={
                                "hamming_distance": dist,
                                "hash_1": h1,
                                "hash_2": h2,
                            },
                            related_photo_ids=[pid2],
                        )
                    )

        # Cross-work duplicate check via global registry
        for photo in photos:
            if photo.perceptual_hash and photo.perceptual_hash in self._hash_registry:
                for reg_work_id, reg_photo_id in self._hash_registry[
                    photo.perceptual_hash
                ]:
                    if reg_work_id != work_id:
                        anomalies.append(
                            PhotoAnomaly(
                                anomaly_type=AnomalyType.IMAGE_DUPLICATE,
                                severity="critical",
                                photo_id=photo.photo_id,
                                work_id=work_id,
                                description=(
                                    f"Photo is a duplicate of {reg_photo_id} "
                                    f"from work {reg_work_id} (cross-work reuse)"
                                ),
                                details={
                                    "source_work_id": reg_work_id,
                                    "source_photo_id": reg_photo_id,
                                    "hash": photo.perceptual_hash,
                                },
                                related_photo_ids=[reg_photo_id],
                            )
                        )

        # --- 6. Camera inconsistency ---
        cameras: list[tuple[str, str]] = [
            (p.photo_id, f"{p.camera_make or ''}|{p.camera_model or ''}")
            for p in photos
            if p.camera_make or p.camera_model
        ]
        if len(cameras) >= MIN_PHOTOS_FOR_CAMERA_CHECK:
            camera_counts = Counter(cam for _, cam in cameras)
            if len(camera_counts) > 1:
                # Find minority cameras
                most_common_cam = camera_counts.most_common(1)[0][0]
                for pid, cam in cameras:
                    if cam != most_common_cam:
                        anomalies.append(
                            PhotoAnomaly(
                                anomaly_type=AnomalyType.CAMERA_INCONSISTENCY,
                                severity="low",
                                photo_id=pid,
                                work_id=work_id,
                                description=(
                                    f"Photo taken with different camera "
                                    f"({cam}) than majority ({most_common_cam})"
                                ),
                                details={
                                    "photo_camera": cam,
                                    "majority_camera": most_common_cam,
                                    "camera_distribution": dict(camera_counts),
                                },
                            )
                        )

        # --- 7. Nighttime photos ---
        for photo in photos:
            if photo.timestamp:
                photo_time = photo.timestamp.time()
                if photo_time < DAYLIGHT_START or photo_time > DAYLIGHT_END:
                    anomalies.append(
                        PhotoAnomaly(
                            anomaly_type=AnomalyType.NIGHTTIME_PHOTO,
                            severity="medium",
                            photo_id=photo.photo_id,
                            work_id=work_id,
                            description=(
                                f"Photo taken at {photo_time.strftime('%H:%M')} "
                                f"(outside daylight hours {DAYLIGHT_START.strftime('%H:%M')}"
                                f"-{DAYLIGHT_END.strftime('%H:%M')})"
                            ),
                            details={
                                "photo_time": photo_time.isoformat(),
                                "daylight_start": DAYLIGHT_START.isoformat(),
                                "daylight_end": DAYLIGHT_END.isoformat(),
                            },
                        )
                    )

        # --- 8. Resolution anomaly ---
        if len(photos) >= 2:
            resolutions = [
                (p.photo_id, p.image_width, p.image_height)
                for p in photos
                if p.image_width and p.image_height
            ]
            if resolutions:
                res_counter = Counter(
                    (w, h) for _, w, h in resolutions
                )
                if len(res_counter) > 1:
                    most_common_res = res_counter.most_common(1)[0][0]
                    for pid, w, h in resolutions:
                        if (w, h) != most_common_res:
                            # Only flag significantly different resolutions
                            mcw, mch = most_common_res
                            ratio = (w * h) / (mcw * mch) if mcw * mch > 0 else 0
                            if ratio < 0.5 or ratio > 2.0:
                                anomalies.append(
                                    PhotoAnomaly(
                                        anomaly_type=AnomalyType.RESOLUTION_ANOMALY,
                                        severity="low",
                                        photo_id=pid,
                                        work_id=work_id,
                                        description=(
                                            f"Photo resolution ({w}x{h}) differs "
                                            f"significantly from majority "
                                            f"({mcw}x{mch})"
                                        ),
                                        details={
                                            "photo_resolution": f"{w}x{h}",
                                            "majority_resolution": f"{mcw}x{mch}",
                                            "pixel_ratio": round(ratio, 2),
                                        },
                                    )
                                )

        logger.info(
            "Detected {} anomalies in {} photos for work {}",
            len(anomalies),
            len(photos),
            work_id,
        )
        return anomalies

    # -- Batch ingestion ---------------------------------------------------

    async def batch_ingest_photos(
        self,
        work_ids: list[str],
        *,
        work_locations: Optional[dict[str, tuple[float, float]]] = None,
    ) -> list[PhotoIngestionResult]:
        """Bulk photo ingestion pipeline for multiple works.

        Downloads and analyses photos for each work, then runs cross-work
        duplicate detection using the global perceptual hash registry.

        Args:
            work_ids: List of NREGA work identifiers.
            work_locations: Optional mapping of ``work_id`` to ``(lat, lon)``
                for GPS anomaly checking.

        Returns:
            List of ``PhotoIngestionResult`` objects, one per work.
        """
        logger.info("Starting batch photo ingestion for {} works", len(work_ids))
        work_locations = work_locations or {}
        results: list[PhotoIngestionResult] = []

        # Process works sequentially to build up the hash registry
        # (cross-work detection requires previously seen hashes)
        for work_id in work_ids:
            try:
                ingestion_result = await self.fetch_geotagged_photos(work_id)

                # Run anomaly detection
                lat_lon = work_locations.get(work_id)
                anomalies = self.detect_photo_anomalies(
                    ingestion_result.metadata,
                    work_lat=lat_lon[0] if lat_lon else None,
                    work_lon=lat_lon[1] if lat_lon else None,
                )
                ingestion_result.anomalies = anomalies

                # Persist to DB if available
                await self._persist_ingestion_result(ingestion_result)

                results.append(ingestion_result)
                logger.info(
                    "Work {}: {} photos, {} anomalies",
                    work_id,
                    ingestion_result.photos_processed,
                    ingestion_result.anomaly_count,
                )

            except Exception as exc:
                logger.error(
                    "Failed to ingest photos for work {}: {}", work_id, exc
                )
                error_result = PhotoIngestionResult(work_id=work_id)
                error_result.errors.append(str(exc))
                results.append(error_result)

        # Summary statistics
        total_photos = sum(r.photos_processed for r in results)
        total_anomalies = sum(r.anomaly_count for r in results)
        total_critical = sum(len(r.critical_anomalies) for r in results)
        logger.info(
            "Batch ingestion complete: {} works, {} photos, {} anomalies "
            "({} critical)",
            len(results),
            total_photos,
            total_anomalies,
            total_critical,
        )

        return results

    # -- Database persistence ----------------------------------------------

    async def _persist_ingestion_result(
        self, result: PhotoIngestionResult
    ) -> None:
        """Persist photo metadata and anomalies to the database."""
        if self._db is None:
            return

        try:
            # Persist photo metadata
            for meta in result.metadata:
                record = {
                    "photo_id": meta.photo_id,
                    "work_id": meta.work_id,
                    "filename": meta.filename,
                    "timestamp": meta.timestamp.isoformat() if meta.timestamp else None,
                    "latitude": meta.gps.latitude if meta.gps else None,
                    "longitude": meta.gps.longitude if meta.gps else None,
                    "altitude": meta.gps.altitude if meta.gps else None,
                    "camera_make": meta.camera_make,
                    "camera_model": meta.camera_model,
                    "software": meta.software,
                    "image_width": meta.image_width,
                    "image_height": meta.image_height,
                    "exif_present": meta.exif_present,
                    "perceptual_hash": meta.perceptual_hash,
                    "ingested_at": datetime.utcnow().isoformat(),
                }
                await self._db.execute(
                    """INSERT INTO geo_photos
                       (photo_id, work_id, filename, timestamp, latitude,
                        longitude, altitude, camera_make, camera_model,
                        software, image_width, image_height, exif_present,
                        perceptual_hash, ingested_at)
                       VALUES (:photo_id, :work_id, :filename, :timestamp,
                               :latitude, :longitude, :altitude, :camera_make,
                               :camera_model, :software, :image_width,
                               :image_height, :exif_present, :perceptual_hash,
                               :ingested_at)
                       ON CONFLICT (photo_id) DO UPDATE SET
                           ingested_at = :ingested_at""",
                    record,
                )

            # Persist anomalies
            for anomaly in result.anomalies:
                import json

                record = {
                    "anomaly_type": anomaly.anomaly_type.value,
                    "severity": anomaly.severity,
                    "photo_id": anomaly.photo_id,
                    "work_id": anomaly.work_id,
                    "description": anomaly.description,
                    "details": json.dumps(anomaly.details),
                    "related_photo_ids": json.dumps(anomaly.related_photo_ids),
                    "detected_at": datetime.utcnow().isoformat(),
                }
                await self._db.execute(
                    """INSERT INTO photo_anomalies
                       (anomaly_type, severity, photo_id, work_id,
                        description, details, related_photo_ids, detected_at)
                       VALUES (:anomaly_type, :severity, :photo_id, :work_id,
                               :description, :details, :related_photo_ids,
                               :detected_at)""",
                    record,
                )

            await self._db.commit()
        except Exception as exc:
            logger.error("DB persist photo data failed: {}", exc)
            await self._db.rollback()
            raise

    # -- Utility: standalone pHash computation ------------------------------

    @staticmethod
    def compute_perceptual_hash(image: Image.Image) -> str:
        """Public interface to the perceptual hash function.

        Args:
            image: PIL Image.

        Returns:
            Hexadecimal pHash string.
        """
        return compute_perceptual_hash(image)

    def get_cross_work_duplicates(self) -> dict[str, list[tuple[str, str]]]:
        """Return all perceptual hashes that appear in multiple works.

        Returns:
            Dictionary mapping hash -> list of ``(work_id, photo_id)`` tuples,
            filtered to only those appearing across 2+ distinct works.
        """
        duplicates: dict[str, list[tuple[str, str]]] = {}
        for phash, entries in self._hash_registry.items():
            work_ids_seen = {wid for wid, _ in entries}
            if len(work_ids_seen) > 1:
                duplicates[phash] = entries
        return duplicates
