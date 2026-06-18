"""
Satellite Imagery Fetcher Module
=================================

Fetches Sentinel-2 satellite imagery from the Copernicus Data Space Ecosystem
and ISRO Bhuvan for before/after verification of MGNREGA work sites.

The module provides two primary fetcher classes:

- **SatelliteFetcher** -- Connects to Copernicus ODATA catalogue and download
  APIs to retrieve Sentinel-2 L2A products for a given bounding box and date
  range.  Supports NDVI computation and RGB thumbnail generation.

- **ISROBhuvanFetcher** -- Connects to ISRO Bhuvan WMS/API endpoints for
  supplementary Indian satellite imagery (Cartosat, ResourceSat).

Both fetchers support local caching of downloaded tiles to avoid redundant
network traffic.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import math
import os
import struct
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional, Union

import httpx
import numpy as np
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

# Copernicus Data Space Ecosystem endpoints
COPERNICUS_TOKEN_URL = (
    "https://identity.dataspace.copernicus.eu"
    "/auth/realms/CDSE/protocol/openid-connect/token"
)
COPERNICUS_ODATA_URL = (
    "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"
)
COPERNICUS_DOWNLOAD_BASE = (
    "https://zipper.dataspace.copernicus.eu/odata/v1/Products"
)

# ISRO Bhuvan endpoints
BHUVAN_API_BASE = "https://bhuvan-app1.nrsc.gov.in/api"
BHUVAN_WMS_URL = "https://bhuvan-app1.nrsc.gov.in/bhuvan/wms"

# Sentinel-2 band spatial resolutions (meters)
SENTINEL2_BAND_RESOLUTION: dict[str, int] = {
    "B01": 60,
    "B02": 10,   # Blue
    "B03": 10,   # Green
    "B04": 10,   # Red
    "B05": 20,
    "B06": 20,
    "B07": 20,
    "B08": 10,   # NIR
    "B8A": 20,
    "B09": 60,
    "B10": 60,
    "B11": 20,   # SWIR-1
    "B12": 20,   # SWIR-2
}

DEFAULT_CACHE_DIR = Path.home() / ".cache" / "mgnrega_satellite"
REQUEST_TIMEOUT = 120.0


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BoundingBox:
    """Axis-aligned bounding box in WGS84 coordinates."""

    west: float
    south: float
    east: float
    north: float

    def to_wkt(self) -> str:
        """Return WKT POLYGON representation (for ODATA spatial filters)."""
        return (
            f"POLYGON(("
            f"{self.west} {self.south},"
            f"{self.east} {self.south},"
            f"{self.east} {self.north},"
            f"{self.west} {self.north},"
            f"{self.west} {self.south}))"
        )

    @staticmethod
    def from_point(lat: float, lon: float, buffer_meters: float) -> "BoundingBox":
        """Create a bounding box around a point with a meter-based buffer.

        Uses a simple equirectangular approximation, which is sufficiently
        accurate for buffers up to a few kilometres at Indian latitudes.

        Args:
            lat: Centre latitude in degrees.
            lon: Centre longitude in degrees.
            buffer_meters: Half-width of the box in metres.

        Returns:
            A ``BoundingBox`` instance.
        """
        # Degrees per metre at the given latitude
        lat_deg_per_m = 1.0 / 111_320.0
        lon_deg_per_m = 1.0 / (111_320.0 * math.cos(math.radians(lat)))
        dlat = buffer_meters * lat_deg_per_m
        dlon = buffer_meters * lon_deg_per_m
        return BoundingBox(
            west=lon - dlon,
            south=lat - dlat,
            east=lon + dlon,
            north=lat + dlat,
        )


@dataclass
class SentinelProduct:
    """Metadata for a single Sentinel-2 product returned by the catalogue."""

    product_id: str
    name: str
    ingestion_date: str
    sensing_date: str
    cloud_cover: float
    footprint_wkt: str
    size_mb: float
    online: bool
    download_url: Optional[str] = None


@dataclass
class BandData:
    """Container for a single downloaded Sentinel-2 band."""

    band_name: str
    data: np.ndarray
    resolution: int
    crs: str = "EPSG:32643"  # Default UTM zone for central India
    transform: Optional[Any] = None  # Affine transform if available


@dataclass
class BeforeAfterResult:
    """Holds before-and-after satellite imagery for a work site."""

    before_product: Optional[SentinelProduct] = None
    after_product: Optional[SentinelProduct] = None
    before_bands: dict[str, BandData] = field(default_factory=dict)
    after_bands: dict[str, BandData] = field(default_factory=dict)
    before_ndvi: Optional[np.ndarray] = None
    after_ndvi: Optional[np.ndarray] = None
    before_thumbnail: Optional[bytes] = None
    after_thumbnail: Optional[bytes] = None


# ---------------------------------------------------------------------------
# SatelliteFetcher -- Copernicus Data Space Ecosystem
# ---------------------------------------------------------------------------


class SatelliteFetcher:
    """Fetch Sentinel-2 L2A imagery from the Copernicus Data Space Ecosystem.

    Handles OAuth2 authentication, ODATA catalogue queries, band-level
    downloads, NDVI computation, and RGB thumbnail generation.

    Usage::

        fetcher = SatelliteFetcher(
            client_id="your-client-id",
            client_secret="your-client-secret",
        )
        async with fetcher:
            products = await fetcher.search_sentinel2(
                bbox=BoundingBox(76.5, 26.8, 76.6, 26.9),
                start_date="2025-01-01",
                end_date="2025-03-01",
            )
    """

    def __init__(
        self,
        *,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        cache_dir: Optional[Union[str, Path]] = None,
        timeout: float = REQUEST_TIMEOUT,
    ) -> None:
        """Initialize the Copernicus satellite fetcher.

        Supports two authentication modes:
        1. OAuth2 client credentials (``client_id`` + ``client_secret``).
        2. Resource Owner Password Grant (``username`` + ``password``).

        Environment variable fallbacks:
            - ``COPERNICUS_CLIENT_ID`` / ``COPERNICUS_CLIENT_SECRET``
            - ``COPERNICUS_USERNAME`` / ``COPERNICUS_PASSWORD``

        Args:
            client_id: Copernicus CDSE OAuth2 client ID.
            client_secret: Copernicus CDSE OAuth2 client secret.
            username: Copernicus CDSE account username (email).
            password: Copernicus CDSE account password.
            cache_dir: Local directory for caching downloaded bands.
            timeout: HTTP request timeout in seconds.
        """
        self._client_id = client_id or os.getenv("COPERNICUS_CLIENT_ID", "")
        self._client_secret = client_secret or os.getenv("COPERNICUS_CLIENT_SECRET", "")
        self._username = username or os.getenv("COPERNICUS_USERNAME", "")
        self._password = password or os.getenv("COPERNICUS_PASSWORD", "")
        self._cache_dir = Path(cache_dir) if cache_dir else DEFAULT_CACHE_DIR
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._timeout = timeout
        self._access_token: Optional[str] = None
        self._token_expiry: Optional[datetime] = None
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "SatelliteFetcher":
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(self._timeout),
            follow_redirects=True,
        )
        await self.authenticate()
        logger.info("SatelliteFetcher session opened")
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._client:
            await self._client.aclose()
        logger.info("SatelliteFetcher session closed")

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError(
                "SatelliteFetcher must be used as an async context manager"
            )
        return self._client

    # -- Authentication ----------------------------------------------------

    @retry(
        retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TransportError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def authenticate(self) -> str:
        """Obtain an OAuth2 access token from the Copernicus identity service.

        Tries client-credentials grant first; falls back to resource-owner
        password grant if no client_secret is configured.

        Returns:
            The access token string.

        Raises:
            httpx.HTTPStatusError: If the token request fails after retries.
            ValueError: If no credentials are configured.
        """
        if (
            self._access_token
            and self._token_expiry
            and datetime.utcnow() < self._token_expiry
        ):
            return self._access_token

        if self._client_id and self._client_secret:
            payload = {
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            }
        elif self._username and self._password:
            payload = {
                "grant_type": "password",
                "client_id": self._client_id or "cdse-public",
                "username": self._username,
                "password": self._password,
            }
        else:
            raise ValueError(
                "Copernicus credentials not configured. Set COPERNICUS_CLIENT_ID/"
                "COPERNICUS_CLIENT_SECRET or COPERNICUS_USERNAME/COPERNICUS_PASSWORD "
                "environment variables."
            )

        logger.debug("Requesting Copernicus access token")
        response = await self.client.post(COPERNICUS_TOKEN_URL, data=payload)
        response.raise_for_status()
        data = response.json()

        self._access_token = data["access_token"]
        expires_in = data.get("expires_in", 600)
        self._token_expiry = datetime.utcnow() + timedelta(seconds=expires_in - 60)
        logger.info("Copernicus token acquired, expires in {}s", expires_in)
        return self._access_token

    async def _auth_headers(self) -> dict[str, str]:
        """Return Authorization header, refreshing the token if needed."""
        token = await self.authenticate()
        return {"Authorization": f"Bearer {token}"}

    # -- Catalogue search --------------------------------------------------

    async def search_sentinel2(
        self,
        bbox: BoundingBox,
        start_date: str,
        end_date: str,
        cloud_cover_max: float = 20.0,
        max_results: int = 50,
    ) -> list[SentinelProduct]:
        """Search the Copernicus ODATA catalogue for Sentinel-2 L2A products.

        Builds an ODATA ``$filter`` query combining spatial (intersects),
        temporal, cloud-cover, and collection constraints.

        Args:
            bbox: Geographic bounding box for the area of interest.
            start_date: ISO date string for the start of the search window.
            end_date: ISO date string for the end of the search window.
            cloud_cover_max: Maximum acceptable cloud cover percentage.
            max_results: Maximum number of products to return.

        Returns:
            List of matching ``SentinelProduct`` objects, sorted by sensing
            date (ascending).
        """
        headers = await self._auth_headers()

        # Build ODATA filter string
        footprint_filter = (
            f"OData.CSC.Intersects(area=geography'SRID=4326;{bbox.to_wkt()}')"
        )
        date_filter = (
            f"ContentDate/Start gt {start_date}T00:00:00.000Z and "
            f"ContentDate/Start lt {end_date}T23:59:59.999Z"
        )
        cloud_filter = (
            f"Attributes/OData.CSC.DoubleAttribute/any("
            f"att:att/Name eq 'cloudCover' and att/OData.CSC.DoubleAttribute/Value lt {cloud_cover_max})"
        )
        collection_filter = "Collection/Name eq 'SENTINEL-2' and contains(Name,'L2A')"

        full_filter = (
            f"{footprint_filter} and {date_filter} and "
            f"{cloud_filter} and {collection_filter}"
        )

        params: dict[str, Any] = {
            "$filter": full_filter,
            "$orderby": "ContentDate/Start asc",
            "$top": max_results,
            "$expand": "Attributes",
        }

        logger.info(
            "Searching Sentinel-2 L2A: bbox={}, dates={} to {}, cloud<{}%",
            bbox,
            start_date,
            end_date,
            cloud_cover_max,
        )

        response = await self.client.get(
            COPERNICUS_ODATA_URL, params=params, headers=headers
        )
        response.raise_for_status()
        data = response.json()

        products: list[SentinelProduct] = []
        for item in data.get("value", []):
            # Extract cloud cover from nested attributes
            cloud_cover = 0.0
            for attr in item.get("Attributes", []):
                if attr.get("Name") == "cloudCover":
                    cloud_cover = float(attr.get("Value", 0))
                    break

            # Compute approximate size from ContentLength
            size_bytes = item.get("ContentLength", 0)
            size_mb = size_bytes / (1024 * 1024) if size_bytes else 0.0

            product = SentinelProduct(
                product_id=item["Id"],
                name=item.get("Name", ""),
                ingestion_date=item.get("IngestionDate", ""),
                sensing_date=item.get("ContentDate", {}).get("Start", ""),
                cloud_cover=cloud_cover,
                footprint_wkt=item.get("Footprint", ""),
                size_mb=size_mb,
                online=item.get("Online", True),
                download_url=f"{COPERNICUS_DOWNLOAD_BASE}({item['Id']})/$value",
            )
            products.append(product)

        logger.info("Found {} Sentinel-2 L2A products", len(products))
        return products

    # -- Download ----------------------------------------------------------

    @retry(
        retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TransportError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        reraise=True,
    )
    async def download_tile(
        self,
        product_id: str,
        bands: Optional[list[str]] = None,
    ) -> dict[str, BandData]:
        """Download specific bands from a Sentinel-2 product.

        Uses the Copernicus ODATA download API. Downloads are cached locally
        to avoid re-fetching.

        Args:
            product_id: UUID of the Sentinel-2 product.
            bands: List of band identifiers (e.g. ``['B02','B03','B04','B08']``).
                Defaults to visible + NIR + SWIR bands.

        Returns:
            Dictionary mapping band name to ``BandData`` objects containing
            numpy arrays.
        """
        if bands is None:
            bands = ["B02", "B03", "B04", "B08", "B11", "B12"]

        headers = await self._auth_headers()
        result: dict[str, BandData] = {}

        # Check cache first
        product_cache = self._cache_dir / product_id
        product_cache.mkdir(parents=True, exist_ok=True)

        for band in bands:
            cache_file = product_cache / f"{band}.npy"
            if cache_file.exists():
                logger.debug("Loading cached band {} for product {}", band, product_id)
                arr = np.load(str(cache_file))
                result[band] = BandData(
                    band_name=band,
                    data=arr,
                    resolution=SENTINEL2_BAND_RESOLUTION.get(band, 10),
                )
                continue

            # Download the specific band via ODATA Nodes API
            # Path within the SAFE structure:
            #   GRANULE/*/IMG_DATA/R{res}m/*_{band}_*.jp2
            resolution = SENTINEL2_BAND_RESOLUTION.get(band, 10)
            res_folder = f"R{resolution}m"

            # Use the Nodes endpoint to navigate the product structure
            nodes_url = (
                f"{COPERNICUS_DOWNLOAD_BASE}({product_id})/Nodes"
            )
            logger.info(
                "Downloading band {} ({}m) for product {}",
                band,
                resolution,
                product_id,
            )

            try:
                # Navigate the SAFE directory tree
                resp = await self.client.get(nodes_url, headers=headers)
                resp.raise_for_status()
                nodes = resp.json().get("result", [])

                # Find GRANULE directory
                granule_node = None
                for node in nodes:
                    if "GRANULE" in node.get("Name", ""):
                        granule_node = node
                        break

                if not granule_node:
                    # Fallback: attempt direct band download from product
                    download_url = f"{COPERNICUS_DOWNLOAD_BASE}({product_id})/$value"
                    resp = await self.client.get(
                        download_url,
                        headers=headers,
                        follow_redirects=True,
                    )
                    resp.raise_for_status()
                    arr = self._parse_band_from_zip(resp.content, band)
                    if arr is not None:
                        np.save(str(cache_file), arr)
                        result[band] = BandData(
                            band_name=band,
                            data=arr,
                            resolution=resolution,
                        )
                    continue

                # Navigate to IMG_DATA/{res_folder}
                img_data_url = (
                    f"{nodes_url}('{granule_node['Name']}')"
                    f"/Nodes('IMG_DATA')/Nodes('{res_folder}')/Nodes"
                )
                resp = await self.client.get(img_data_url, headers=headers)
                resp.raise_for_status()
                band_nodes = resp.json().get("result", [])

                # Find the target band file
                band_file = None
                for bn in band_nodes:
                    if f"_{band}_" in bn.get("Name", "") or bn.get("Name", "").endswith(
                        f"{band}.jp2"
                    ):
                        band_file = bn
                        break

                if not band_file:
                    logger.warning(
                        "Band {} not found in product {}", band, product_id
                    )
                    continue

                # Download the band file
                band_download_url = (
                    f"{img_data_url}('{band_file['Name']}')/$value"
                )
                resp = await self.client.get(
                    band_download_url, headers=headers, follow_redirects=True
                )
                resp.raise_for_status()

                # Parse JP2 to numpy array
                arr = self._parse_jp2_band(resp.content)
                np.save(str(cache_file), arr)
                result[band] = BandData(
                    band_name=band, data=arr, resolution=resolution
                )

            except Exception as exc:
                logger.error(
                    "Failed to download band {} for product {}: {}",
                    band,
                    product_id,
                    exc,
                )

        logger.info(
            "Downloaded {}/{} bands for product {}",
            len(result),
            len(bands),
            product_id,
        )
        return result

    # -- Before/After imagery retrieval ------------------------------------

    async def get_before_after_images(
        self,
        lat: float,
        lon: float,
        work_start_date: str,
        work_end_date: str,
        buffer_meters: float = 500.0,
        cloud_cover_max: float = 20.0,
        bands: Optional[list[str]] = None,
    ) -> BeforeAfterResult:
        """Get satellite imagery from before and after a reported work period.

        Searches for the best (lowest cloud cover) Sentinel-2 scene in two
        windows:
        - **Before**: 90 days prior to ``work_start_date`` up to the start.
        - **After**: ``work_end_date`` up to 90 days after.

        Args:
            lat: Latitude of the work site centre.
            lon: Longitude of the work site centre.
            work_start_date: ISO date when work reportedly started.
            work_end_date: ISO date when work reportedly completed.
            buffer_meters: Radius in metres for the bounding box.
            cloud_cover_max: Maximum cloud cover percentage.
            bands: Sentinel-2 bands to download.

        Returns:
            A ``BeforeAfterResult`` containing products, bands, NDVI arrays,
            and RGB thumbnails for both periods.
        """
        if bands is None:
            bands = ["B02", "B03", "B04", "B08"]

        bbox = BoundingBox.from_point(lat, lon, buffer_meters)

        # Parse dates and compute search windows
        start_dt = datetime.fromisoformat(work_start_date)
        end_dt = datetime.fromisoformat(work_end_date)
        before_window_start = (start_dt - timedelta(days=90)).strftime("%Y-%m-%d")
        after_window_end = (end_dt + timedelta(days=90)).strftime("%Y-%m-%d")

        logger.info(
            "Fetching before/after imagery for ({}, {}) work period {} to {}",
            lat,
            lon,
            work_start_date,
            work_end_date,
        )

        # Search both windows in parallel
        before_task = self.search_sentinel2(
            bbox=bbox,
            start_date=before_window_start,
            end_date=work_start_date,
            cloud_cover_max=cloud_cover_max,
        )
        after_task = self.search_sentinel2(
            bbox=bbox,
            start_date=work_end_date,
            end_date=after_window_end,
            cloud_cover_max=cloud_cover_max,
        )
        before_products, after_products = await asyncio.gather(
            before_task, after_task
        )

        result = BeforeAfterResult()

        # Select the best (lowest cloud cover) product from each window
        if before_products:
            result.before_product = min(
                before_products, key=lambda p: p.cloud_cover
            )
            result.before_bands = await self.download_tile(
                result.before_product.product_id, bands
            )
            if "B04" in result.before_bands and "B08" in result.before_bands:
                result.before_ndvi = self.calculate_ndvi(
                    result.before_bands["B04"].data,
                    result.before_bands["B08"].data,
                )
            if all(b in result.before_bands for b in ["B04", "B03", "B02"]):
                result.before_thumbnail = self.extract_rgb_thumbnail(
                    result.before_bands, bbox
                )

        if after_products:
            result.after_product = min(
                after_products, key=lambda p: p.cloud_cover
            )
            result.after_bands = await self.download_tile(
                result.after_product.product_id, bands
            )
            if "B04" in result.after_bands and "B08" in result.after_bands:
                result.after_ndvi = self.calculate_ndvi(
                    result.after_bands["B04"].data,
                    result.after_bands["B08"].data,
                )
            if all(b in result.after_bands for b in ["B04", "B03", "B02"]):
                result.after_thumbnail = self.extract_rgb_thumbnail(
                    result.after_bands, bbox
                )

        return result

    # -- Band math utilities -----------------------------------------------

    @staticmethod
    def calculate_ndvi(
        red_band: np.ndarray, nir_band: np.ndarray
    ) -> np.ndarray:
        """Calculate the Normalized Difference Vegetation Index.

        NDVI = (NIR - Red) / (NIR + Red)

        Values range from -1 to +1.  Healthy vegetation typically shows
        values > 0.3; bare soil/rock is near 0; water is negative.

        Args:
            red_band: 2-D numpy array of red reflectance values (B04).
            nir_band: 2-D numpy array of NIR reflectance values (B08).

        Returns:
            2-D numpy array of NDVI values (float32).
        """
        red = red_band.astype(np.float32)
        nir = nir_band.astype(np.float32)
        denominator = nir + red
        # Avoid division by zero
        ndvi = np.where(
            denominator > 0,
            (nir - red) / denominator,
            0.0,
        )
        return np.clip(ndvi, -1.0, 1.0).astype(np.float32)

    @staticmethod
    def calculate_ndwi(
        green_band: np.ndarray, nir_band: np.ndarray
    ) -> np.ndarray:
        """Calculate the Normalized Difference Water Index.

        NDWI = (Green - NIR) / (Green + NIR)

        Useful for detecting water bodies and moisture content, relevant for
        verifying works like pond construction or canal desilting.

        Args:
            green_band: 2-D numpy array (B03).
            nir_band: 2-D numpy array (B08).

        Returns:
            2-D numpy array of NDWI values (float32).
        """
        green = green_band.astype(np.float32)
        nir = nir_band.astype(np.float32)
        denominator = green + nir
        ndwi = np.where(
            denominator > 0,
            (green - nir) / denominator,
            0.0,
        )
        return np.clip(ndwi, -1.0, 1.0).astype(np.float32)

    @staticmethod
    def calculate_nbr(
        nir_band: np.ndarray, swir_band: np.ndarray
    ) -> np.ndarray:
        """Calculate the Normalized Burn Ratio.

        NBR = (NIR - SWIR) / (NIR + SWIR)

        Useful for detecting land-clearing or changes in soil exposure.

        Args:
            nir_band: 2-D numpy array (B08).
            swir_band: 2-D numpy array (B12).

        Returns:
            2-D numpy array of NBR values (float32).
        """
        nir = nir_band.astype(np.float32)
        swir = swir_band.astype(np.float32)
        denominator = nir + swir
        nbr = np.where(
            denominator > 0,
            (nir - swir) / denominator,
            0.0,
        )
        return np.clip(nbr, -1.0, 1.0).astype(np.float32)

    @staticmethod
    def extract_rgb_thumbnail(
        bands: dict[str, BandData],
        bbox: BoundingBox,
        size: tuple[int, int] = (512, 512),
    ) -> bytes:
        """Generate an RGB thumbnail PNG from downloaded bands.

        Combines B04 (Red), B03 (Green), and B02 (Blue) into a 3-channel
        image, applies histogram stretching for visual clarity, and encodes
        as PNG bytes.

        Args:
            bands: Dictionary of downloaded band data (must include B02-B04).
            bbox: Bounding box for optional spatial cropping metadata.
            size: Output image dimensions ``(width, height)``.

        Returns:
            PNG image bytes.

        Raises:
            ValueError: If required bands are missing.
        """
        for required in ("B04", "B03", "B02"):
            if required not in bands:
                raise ValueError(f"Band {required} required for RGB thumbnail")

        red = bands["B04"].data.astype(np.float32)
        green = bands["B03"].data.astype(np.float32)
        blue = bands["B02"].data.astype(np.float32)

        # Resample to common shape if resolutions differ
        target_h, target_w = size[1], size[0]

        def _resize_nearest(arr: np.ndarray, h: int, w: int) -> np.ndarray:
            """Simple nearest-neighbour resize without external deps."""
            src_h, src_w = arr.shape
            row_idx = (np.arange(h) * src_h // h).astype(int)
            col_idx = (np.arange(w) * src_w // w).astype(int)
            return arr[np.ix_(row_idx, col_idx)]

        red = _resize_nearest(red, target_h, target_w)
        green = _resize_nearest(green, target_h, target_w)
        blue = _resize_nearest(blue, target_h, target_w)

        # Histogram stretching (2nd - 98th percentile)
        def _stretch(band: np.ndarray) -> np.ndarray:
            p2, p98 = np.percentile(band, (2, 98))
            if p98 <= p2:
                return np.zeros_like(band, dtype=np.uint8)
            clipped = np.clip(band, p2, p98)
            return ((clipped - p2) / (p98 - p2) * 255).astype(np.uint8)

        r = _stretch(red)
        g = _stretch(green)
        b = _stretch(blue)

        # Encode as minimal PNG (no PIL dependency required for this path)
        rgb = np.stack([r, g, b], axis=-1)  # (H, W, 3)
        return _encode_png_rgb(rgb)

    # -- Internal helpers ---------------------------------------------------

    @staticmethod
    def _parse_jp2_band(data: bytes) -> np.ndarray:
        """Parse a JPEG2000 band file into a numpy array.

        Falls back to raw uint16 parsing if openjpeg is not available.
        """
        try:
            import glymur  # type: ignore

            with io.BytesIO(data) as buf:
                jp2 = glymur.Jp2k(buf)
                return jp2[:].astype(np.uint16)
        except ImportError:
            pass

        try:
            from PIL import Image  # type: ignore

            with io.BytesIO(data) as buf:
                img = Image.open(buf)
                return np.array(img, dtype=np.uint16)
        except (ImportError, Exception):
            pass

        # Last resort: return a placeholder array signalling raw data
        logger.warning(
            "Could not decode JP2 band -- returning raw byte array. "
            "Install 'glymur' or 'Pillow' with JP2K support."
        )
        return np.frombuffer(data, dtype=np.uint8)

    @staticmethod
    def _parse_band_from_zip(
        zip_bytes: bytes, band_name: str
    ) -> Optional[np.ndarray]:
        """Extract a specific band from a zipped SAFE product."""
        import zipfile

        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                for name in zf.namelist():
                    if f"_{band_name}_" in name or name.endswith(f"{band_name}.jp2"):
                        with zf.open(name) as f:
                            return SatelliteFetcher._parse_jp2_band(f.read())
        except zipfile.BadZipFile:
            logger.error("Invalid ZIP file for product")
        return None

    def clear_cache(self, product_id: Optional[str] = None) -> int:
        """Remove cached band files.

        Args:
            product_id: If given, only clear this product.  Otherwise clear
                all cached data.

        Returns:
            Number of files removed.
        """
        count = 0
        if product_id:
            target = self._cache_dir / product_id
            if target.exists():
                for f in target.iterdir():
                    f.unlink()
                    count += 1
                target.rmdir()
        else:
            for d in self._cache_dir.iterdir():
                if d.is_dir():
                    for f in d.iterdir():
                        f.unlink()
                        count += 1
                    d.rmdir()
        logger.info("Cleared {} cached band files", count)
        return count


# ---------------------------------------------------------------------------
# ISROBhuvanFetcher -- supplementary Indian satellite data
# ---------------------------------------------------------------------------


class ISROBhuvanFetcher:
    """Fetch satellite imagery and geodata from ISRO Bhuvan services.

    Bhuvan provides WMS/WMTS layers from Indian satellite missions (Cartosat,
    ResourceSat, etc.) that complement Sentinel-2 data with higher-frequency
    or India-specific coverage.

    Usage::

        async with ISROBhuvanFetcher() as bhuvan:
            image = await bhuvan.get_wms_image(
                layer="india3",
                bbox=BoundingBox(76.5, 26.8, 76.6, 26.9),
            )
    """

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        cache_dir: Optional[Union[str, Path]] = None,
        timeout: float = REQUEST_TIMEOUT,
    ) -> None:
        """Initialize the Bhuvan fetcher.

        Args:
            api_key: Optional Bhuvan API key (from environment
                ``BHUVAN_API_KEY`` if not passed).
            cache_dir: Local directory for caching.
            timeout: HTTP request timeout in seconds.
        """
        self._api_key = api_key or os.getenv("BHUVAN_API_KEY", "")
        self._cache_dir = Path(cache_dir) if cache_dir else DEFAULT_CACHE_DIR / "bhuvan"
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "ISROBhuvanFetcher":
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(self._timeout),
            follow_redirects=True,
        )
        logger.info("ISROBhuvanFetcher session opened")
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._client:
            await self._client.aclose()
        logger.info("ISROBhuvanFetcher session closed")

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError(
                "ISROBhuvanFetcher must be used as an async context manager"
            )
        return self._client

    @retry(
        retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TransportError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def get_wms_image(
        self,
        layer: str,
        bbox: BoundingBox,
        width: int = 512,
        height: int = 512,
        img_format: str = "image/png",
        srs: str = "EPSG:4326",
    ) -> bytes:
        """Fetch a map image from Bhuvan WMS.

        Args:
            layer: WMS layer name (e.g. ``'india3'``, ``'cartosat'``,
                ``'lulc50k'``).
            bbox: Geographic bounding box.
            width: Image width in pixels.
            height: Image height in pixels.
            img_format: MIME type for the response image.
            srs: Spatial reference system.

        Returns:
            Image bytes (PNG or JPEG).
        """
        cache_key = hashlib.md5(
            f"{layer}_{bbox}_{width}_{height}_{srs}".encode()
        ).hexdigest()
        cache_file = self._cache_dir / f"{cache_key}.png"
        if cache_file.exists():
            logger.debug("Returning cached WMS image for layer {}", layer)
            return cache_file.read_bytes()

        params: dict[str, Any] = {
            "service": "WMS",
            "version": "1.1.1",
            "request": "GetMap",
            "layers": layer,
            "bbox": f"{bbox.west},{bbox.south},{bbox.east},{bbox.north}",
            "width": width,
            "height": height,
            "srs": srs,
            "format": img_format,
            "transparent": "true",
        }
        if self._api_key:
            params["key"] = self._api_key

        logger.info("Fetching Bhuvan WMS: layer={}, bbox={}", layer, bbox)
        resp = await self.client.get(BHUVAN_WMS_URL, params=params)
        resp.raise_for_status()

        image_bytes = resp.content
        cache_file.write_bytes(image_bytes)
        return image_bytes

    @retry(
        retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TransportError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def get_lulc_data(
        self,
        bbox: BoundingBox,
        year: int = 2023,
    ) -> bytes:
        """Fetch Land Use / Land Cover (LULC) map from Bhuvan.

        The LULC layer helps verify whether a reported work site location is
        consistent with the type of NREGA work (e.g., road construction should
        not appear in dense forest zones).

        Args:
            bbox: Geographic bounding box.
            year: Target year for LULC data.

        Returns:
            PNG image bytes of the LULC classification.
        """
        layer = f"lulc:{year}" if year >= 2020 else "lulc50k"
        return await self.get_wms_image(layer=layer, bbox=bbox)

    async def get_dem_elevation(
        self,
        lat: float,
        lon: float,
    ) -> Optional[float]:
        """Query Bhuvan DEM API for elevation at a point.

        Elevation data can cross-check whether a reported work site is
        physically plausible (e.g., a pond at a ridge top is suspicious).

        Args:
            lat: Latitude in degrees.
            lon: Longitude in degrees.

        Returns:
            Elevation in metres above sea level, or ``None`` if unavailable.
        """
        url = f"{BHUVAN_API_BASE}/elevation"
        params = {"lat": lat, "lon": lon}
        if self._api_key:
            params["key"] = self._api_key

        try:
            resp = await self.client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            return float(data.get("elevation", data.get("alt", 0)))
        except Exception as exc:
            logger.warning("Bhuvan DEM query failed for ({}, {}): {}", lat, lon, exc)
            return None

    async def get_cartosat_image(
        self,
        bbox: BoundingBox,
        width: int = 1024,
        height: int = 1024,
    ) -> bytes:
        """Fetch high-resolution Cartosat imagery from Bhuvan WMS.

        Args:
            bbox: Geographic bounding box.
            width: Image width.
            height: Image height.

        Returns:
            PNG image bytes.
        """
        return await self.get_wms_image(
            layer="cartosat",
            bbox=bbox,
            width=width,
            height=height,
        )


# ---------------------------------------------------------------------------
# Minimal PNG encoder (avoids PIL dependency for thumbnail generation)
# ---------------------------------------------------------------------------


def _encode_png_rgb(rgb: np.ndarray) -> bytes:
    """Encode a (H, W, 3) uint8 numpy array as a PNG file.

    Implements a minimal uncompressed PNG encoder using only ``struct`` and
    ``zlib``.  For production deployments with large images, prefer PIL/Pillow.
    """
    import zlib

    height, width, _ = rgb.shape
    raw_data = bytearray()
    for y in range(height):
        raw_data.append(0)  # filter byte: None
        raw_data.extend(rgb[y].tobytes())

    compressed = zlib.compress(bytes(raw_data), 9)

    def _chunk(chunk_type: bytes, data: bytes) -> bytes:
        chunk_data = chunk_type + data
        crc = zlib.crc32(chunk_data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + chunk_data + struct.pack(">I", crc)

    png = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    png += _chunk(b"IHDR", ihdr_data)
    png += _chunk(b"IDAT", compressed)
    png += _chunk(b"IEND", b"")
    return png
