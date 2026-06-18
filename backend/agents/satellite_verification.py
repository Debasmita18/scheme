"""
Satellite Verification Agent for the MGNREGA Verification & Fraud Intelligence System.

This agent performs remote-sensing-based physical verification of reported
MGNREGA works by analysing before-and-after satellite imagery. It uses
Sentinel-2 multispectral data to detect earthworks, estimate physical
dimensions (roads, ponds, canals, land levelling), and compare them against
reported measurements in NREGASoft.

Key capabilities:
- NDVI change detection for ground disturbance identification
- SWIR spectral analysis for earthwork vs vegetation discrimination
- Linear feature extraction for roads and canals
- Water body boundary detection for ponds and tanks
- Terrain change analysis for land levelling
- Automated before-after comparison image generation
"""

from __future__ import annotations

import io
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from loguru import logger


# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------

class VerificationStatus(str, Enum):
    """Outcome of a satellite-based verification."""

    VERIFIED = "verified"
    PARTIAL_MATCH = "partial_match"
    MISMATCH = "mismatch"
    NOT_DETECTED = "not_detected"
    INSUFFICIENT_DATA = "insufficient_data"
    CLOUD_OBSCURED = "cloud_obscured"


class WorkType(str, Enum):
    """MGNREGA work categories relevant to satellite verification."""

    ROAD = "road"
    POND = "pond"
    TANK = "tank"
    CANAL = "canal"
    CHANNEL = "channel"
    LAND_LEVELLING = "land_levelling"
    CHECK_DAM = "check_dam"
    WELL = "well"
    PLANTATION = "plantation"
    BUND = "bund"
    OTHER = "other"


@dataclass
class BoundingBox:
    """Geographic bounding box in WGS-84 coordinates."""

    min_lat: float
    min_lon: float
    max_lat: float
    max_lon: float

    @property
    def center(self) -> Tuple[float, float]:
        return (
            (self.min_lat + self.max_lat) / 2,
            (self.min_lon + self.max_lon) / 2,
        )

    @property
    def width_degrees(self) -> float:
        return self.max_lon - self.min_lon

    @property
    def height_degrees(self) -> float:
        return self.max_lat - self.min_lat


@dataclass
class SatelliteImage:
    """Container for a Sentinel-2 scene or derived product."""

    scene_id: str
    acquisition_date: datetime
    bands: Dict[str, np.ndarray]  # band_name -> 2D array
    cloud_cover_pct: float
    bbox: BoundingBox
    pixel_resolution_m: float = 10.0  # Sentinel-2 Band 4 default
    crs: str = "EPSG:4326"
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MeasurementEstimate:
    """Estimated physical measurement from satellite analysis."""

    dimension: str  # "length_m", "width_m", "area_sqm", "depth_indicator"
    estimated_value: float
    reported_value: float
    deviation_pct: float
    confidence: float  # 0-1
    method: str  # algorithm used


@dataclass
class VerificationResult:
    """Complete verification outcome for a single MGNREGA work."""

    work_id: str
    work_type: WorkType
    verification_status: VerificationStatus
    confidence_score: float
    measurements: List[MeasurementEstimate] = field(default_factory=list)
    before_image_id: Optional[str] = None
    after_image_id: Optional[str] = None
    change_mask_id: Optional[str] = None
    ndvi_change: Optional[float] = None
    spectral_signatures: Dict[str, float] = field(default_factory=dict)
    evidence_urls: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    verified_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ComparisonReport:
    """Before-after comparison report for a work."""

    work_id: str
    report_id: str
    result: VerificationResult
    before_image_path: Optional[str] = None
    after_image_path: Optional[str] = None
    change_overlay_path: Optional[str] = None
    summary: str = ""
    generated_at: datetime = field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Satellite Verification Agent
# ---------------------------------------------------------------------------

class SatelliteVerificationAgent:
    """Agent for satellite-based physical verification of MGNREGA works.

    Uses Sentinel-2 multispectral imagery to independently verify whether
    reported works (roads, ponds, canals, land levelling, etc.) physically
    exist and match the dimensions recorded in NREGASoft.

    Parameters
    ----------
    db_session : Any
        Database session for fetching work records and storing results.
    imagery_client : Any
        Client for accessing Sentinel-2 imagery (e.g., Sentinel Hub,
        Google Earth Engine, or a custom tile server).
    storage_client : Any
        Object storage client for saving comparison images.
    config : dict, optional
        Runtime configuration overrides.
    """

    # Default verification tolerances
    MEASUREMENT_TOLERANCE_PCT: float = 20.0  # 20% deviation allowed
    MIN_CONFIDENCE_THRESHOLD: float = 0.4
    MAX_CLOUD_COVER_PCT: float = 30.0
    GPS_BUFFER_M: float = 500.0  # buffer around work GPS for imagery crop

    # Sentinel-2 band mappings
    BAND_RED: str = "B04"          # 665 nm, 10m
    BAND_NIR: str = "B08"          # 842 nm, 10m
    BAND_SWIR1: str = "B11"        # 1610 nm, 20m
    BAND_SWIR2: str = "B12"        # 2190 nm, 20m
    BAND_GREEN: str = "B03"        # 560 nm, 10m
    BAND_BLUE: str = "B02"         # 490 nm, 10m

    def __init__(
        self,
        db_session: Any,
        imagery_client: Any,
        storage_client: Any,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.db = db_session
        self.imagery = imagery_client
        self.storage = storage_client
        self.config = config or {}
        self.tolerance_pct = self.config.get(
            "measurement_tolerance_pct", self.MEASUREMENT_TOLERANCE_PCT
        )
        self.max_cloud = self.config.get(
            "max_cloud_cover_pct", self.MAX_CLOUD_COVER_PCT
        )

        logger.info(
            "SatelliteVerificationAgent initialised | tolerance={t}% | max_cloud={c}%",
            t=self.tolerance_pct,
            c=self.max_cloud,
        )

    # ------------------------------------------------------------------
    # Primary verification entry point
    # ------------------------------------------------------------------

    async def verify_work(self, work_id: str) -> VerificationResult:
        """Run full satellite verification pipeline for a single work.

        Pipeline steps:
        1. Fetch work metadata (GPS, work type, reported measurements,
           start/completion dates) from NREGASoft.
        2. Determine before/after date windows.
        3. Acquire Sentinel-2 imagery for both periods.
        4. Compute NDVI and spectral indices for change detection.
        5. Apply work-type-specific measurement estimation.
        6. Compare estimated vs reported measurements.
        7. Produce verification verdict with confidence score.
        8. Persist results and generate comparison images.

        Parameters
        ----------
        work_id : str
            The NREGASoft work identifier.

        Returns
        -------
        VerificationResult
            Complete verification outcome.
        """
        logger.info("Starting satellite verification for work {w}", w=work_id)

        try:
            # Step 1 -- Fetch work details
            work = await self._fetch_work_details(work_id)
            if not work:
                logger.warning("Work {w} not found in database", w=work_id)
                return VerificationResult(
                    work_id=work_id,
                    work_type=WorkType.OTHER,
                    verification_status=VerificationStatus.INSUFFICIENT_DATA,
                    confidence_score=0.0,
                    notes=["Work record not found in NREGASoft"],
                )

            work_type = WorkType(work.get("work_type", "other"))
            gps_lat = work["latitude"]
            gps_lon = work["longitude"]

            # Step 2 -- Determine temporal windows
            start_date = work.get("start_date", datetime.utcnow() - timedelta(days=180))
            completion_date = work.get("completion_date", datetime.utcnow())
            before_window = (
                start_date - timedelta(days=60),
                start_date - timedelta(days=5),
            )
            after_window = (
                completion_date + timedelta(days=5),
                completion_date + timedelta(days=60),
            )

            # Step 3 -- Build bounding box and acquire imagery
            bbox = self._build_bbox(gps_lat, gps_lon, self.GPS_BUFFER_M)

            before_img = await self._acquire_imagery(bbox, before_window)
            after_img = await self._acquire_imagery(bbox, after_window)

            if before_img is None or after_img is None:
                status = (
                    VerificationStatus.CLOUD_OBSCURED
                    if (before_img is not None or after_img is not None)
                    else VerificationStatus.INSUFFICIENT_DATA
                )
                return VerificationResult(
                    work_id=work_id,
                    work_type=work_type,
                    verification_status=status,
                    confidence_score=0.0,
                    notes=["Could not acquire suitable before/after imagery"],
                )

            # Step 4 -- NDVI and spectral change detection
            change_mask, ndvi_change = self.detect_earthwork(
                before_img, after_img, bbox
            )

            # Step 5 -- Work-type-specific measurement estimation
            measurements = self._estimate_measurements(
                work_type, change_mask, before_img.pixel_resolution_m, work
            )

            # Step 6 -- Compare and compute confidence
            confidence, status = self._evaluate_measurements(
                measurements, work_type
            )

            # Step 7 -- Spectral signatures for evidence
            spectral = self._compute_spectral_signatures(
                after_img, change_mask
            )

            # Step 8 -- Save comparison images
            before_path = await self._save_comparison_image(
                before_img, work_id, "before"
            )
            after_path = await self._save_comparison_image(
                after_img, work_id, "after"
            )
            change_path = await self._save_change_mask(
                change_mask, bbox, work_id
            )

            result = VerificationResult(
                work_id=work_id,
                work_type=work_type,
                verification_status=status,
                confidence_score=round(confidence, 4),
                measurements=measurements,
                before_image_id=before_path,
                after_image_id=after_path,
                change_mask_id=change_path,
                ndvi_change=round(float(ndvi_change), 4),
                spectral_signatures=spectral,
                evidence_urls=[p for p in [before_path, after_path, change_path] if p],
            )

            # Persist to database
            await self._save_verification_result(result)

            logger.info(
                "Verification complete for work {w} | status={s} | confidence={c:.2f}",
                w=work_id,
                s=status.value,
                c=confidence,
            )
            return result

        except Exception as exc:
            logger.exception(
                "Satellite verification failed for work {w}: {e}",
                w=work_id,
                e=exc,
            )
            return VerificationResult(
                work_id=work_id,
                work_type=WorkType.OTHER,
                verification_status=VerificationStatus.INSUFFICIENT_DATA,
                confidence_score=0.0,
                notes=[f"Verification pipeline error: {exc!s}"],
            )

    # ------------------------------------------------------------------
    # Change detection
    # ------------------------------------------------------------------

    def detect_earthwork(
        self,
        before_img: SatelliteImage,
        after_img: SatelliteImage,
        bbox: BoundingBox,
    ) -> Tuple[np.ndarray, float]:
        """Detect ground disturbance between two Sentinel-2 scenes.

        Methodology:
        1. Compute NDVI for both scenes: NDVI = (NIR - RED) / (NIR + RED).
        2. Compute delta-NDVI: significant decrease indicates vegetation
           removal / earthwork.
        3. Compute SWIR-based bare-soil index to discriminate earthwork
           from natural vegetation loss.
        4. Combine indices into a binary change mask using adaptive
           thresholding (Otsu).

        Parameters
        ----------
        before_img : SatelliteImage
            Pre-construction Sentinel-2 scene.
        after_img : SatelliteImage
            Post-construction Sentinel-2 scene.
        bbox : BoundingBox
            Geographic extent for analysis.

        Returns
        -------
        change_mask : np.ndarray
            Binary 2D array (1 = detected change, 0 = no change).
        mean_ndvi_change : float
            Mean NDVI difference in detected change areas.
        """
        logger.debug(
            "Detecting earthwork | before={b} | after={a}",
            b=before_img.scene_id,
            a=after_img.scene_id,
        )

        try:
            # Compute NDVI for both scenes
            ndvi_before = self._compute_ndvi(before_img)
            ndvi_after = self._compute_ndvi(after_img)

            # Delta NDVI (negative = vegetation loss = likely earthwork)
            delta_ndvi = ndvi_after - ndvi_before

            # SWIR-based bare soil index for the after image
            bsi_after = self._compute_bare_soil_index(after_img)

            # Adaptive thresholding on delta NDVI
            ndvi_threshold = self._otsu_threshold(-delta_ndvi)

            # Combined change mask:
            # Significant NDVI decrease AND elevated bare soil index
            ndvi_change_mask = delta_ndvi < -ndvi_threshold
            bsi_threshold = self._otsu_threshold(bsi_after)
            soil_mask = bsi_after > bsi_threshold

            # Union of both indicators
            change_mask = (ndvi_change_mask | soil_mask).astype(np.uint8)

            # Morphological cleanup: remove noise, fill small gaps
            change_mask = self._morphological_cleanup(change_mask)

            # Mean NDVI change in detected areas
            if np.sum(change_mask) > 0:
                mean_change = float(
                    np.mean(delta_ndvi[change_mask.astype(bool)])
                )
            else:
                mean_change = 0.0

            logger.debug(
                "Earthwork detection complete | changed_pixels={cp} | mean_ndvi_change={m:.4f}",
                cp=int(np.sum(change_mask)),
                m=mean_change,
            )
            return change_mask, mean_change

        except Exception as exc:
            logger.error("Earthwork detection failed: {e}", e=exc)
            empty_mask = np.zeros((100, 100), dtype=np.uint8)
            return empty_mask, 0.0

    # ------------------------------------------------------------------
    # Measurement estimation
    # ------------------------------------------------------------------

    def estimate_road_length(
        self, change_mask: np.ndarray, pixel_resolution: float
    ) -> MeasurementEstimate:
        """Estimate road length from a change detection mask.

        Uses skeletonisation to extract the linear backbone of the detected
        change region, then computes the total path length in metres.

        Parameters
        ----------
        change_mask : np.ndarray
            Binary mask of detected change (1 = change).
        pixel_resolution : float
            Ground sampling distance in metres per pixel.

        Returns
        -------
        MeasurementEstimate
            Estimated road length with confidence.
        """
        logger.debug("Estimating road length from change mask")

        try:
            # Skeletonise the change mask to extract centreline
            skeleton = self._skeletonise(change_mask)

            # Count skeleton pixels and convert to metres
            skeleton_pixels = int(np.sum(skeleton > 0))
            estimated_length_m = skeleton_pixels * pixel_resolution

            # Estimate width from mask area / skeleton length
            mask_pixels = int(np.sum(change_mask > 0))
            estimated_width_m = (
                (mask_pixels / max(skeleton_pixels, 1)) * pixel_resolution
                if skeleton_pixels > 0
                else 0.0
            )

            # Confidence based on skeleton coherence
            coherence = self._compute_skeleton_coherence(skeleton, change_mask)
            confidence = min(coherence, 1.0)

            logger.debug(
                "Road estimation | length={l:.1f}m | width={w:.1f}m | confidence={c:.2f}",
                l=estimated_length_m,
                w=estimated_width_m,
                c=confidence,
            )

            return MeasurementEstimate(
                dimension="length_m",
                estimated_value=round(estimated_length_m, 1),
                reported_value=0.0,  # filled by caller
                deviation_pct=0.0,
                confidence=round(confidence, 4),
                method="skeletonisation_centreline",
            )

        except Exception as exc:
            logger.error("Road length estimation failed: {e}", e=exc)
            return MeasurementEstimate(
                dimension="length_m",
                estimated_value=0.0,
                reported_value=0.0,
                deviation_pct=0.0,
                confidence=0.0,
                method="skeletonisation_centreline",
            )

    def estimate_pond_area(
        self, change_mask: np.ndarray, pixel_resolution: float
    ) -> MeasurementEstimate:
        """Estimate pond/tank surface area from a change detection mask.

        Uses connected-component analysis to identify the largest contiguous
        water body region, then computes its area in square metres.

        Parameters
        ----------
        change_mask : np.ndarray
            Binary mask of detected change / water body (1 = change).
        pixel_resolution : float
            Ground sampling distance in metres per pixel.

        Returns
        -------
        MeasurementEstimate
            Estimated area with confidence.
        """
        logger.debug("Estimating pond area from change mask")

        try:
            # Connected component analysis
            labels, num_features = self._connected_components(change_mask)

            if num_features == 0:
                return MeasurementEstimate(
                    dimension="area_sqm",
                    estimated_value=0.0,
                    reported_value=0.0,
                    deviation_pct=0.0,
                    confidence=0.0,
                    method="connected_component_area",
                )

            # Find the largest connected component
            component_sizes = []
            for label_id in range(1, num_features + 1):
                component_sizes.append(
                    (label_id, int(np.sum(labels == label_id)))
                )
            component_sizes.sort(key=lambda x: x[1], reverse=True)

            largest_label, largest_size = component_sizes[0]

            # Area in square metres
            pixel_area_sqm = pixel_resolution ** 2
            estimated_area_sqm = largest_size * pixel_area_sqm

            # Compactness ratio (how circular -- ponds tend to be compact)
            component_mask = (labels == largest_label).astype(np.uint8)
            compactness = self._compute_compactness(component_mask)

            # Confidence: higher for compact, large features
            size_confidence = min(largest_size / 100.0, 1.0)
            confidence = 0.6 * compactness + 0.4 * size_confidence

            logger.debug(
                "Pond estimation | area={a:.1f}sqm | compactness={cp:.2f} | confidence={c:.2f}",
                a=estimated_area_sqm,
                cp=compactness,
                c=confidence,
            )

            return MeasurementEstimate(
                dimension="area_sqm",
                estimated_value=round(estimated_area_sqm, 1),
                reported_value=0.0,
                deviation_pct=0.0,
                confidence=round(confidence, 4),
                method="connected_component_area",
            )

        except Exception as exc:
            logger.error("Pond area estimation failed: {e}", e=exc)
            return MeasurementEstimate(
                dimension="area_sqm",
                estimated_value=0.0,
                reported_value=0.0,
                deviation_pct=0.0,
                confidence=0.0,
                method="connected_component_area",
            )

    def generate_comparison_report(
        self, work_id: str
    ) -> ComparisonReport:
        """Generate a before-after comparison report for a verified work.

        Compiles imagery paths, measurement comparisons, and a human-
        readable summary suitable for audit documentation.

        Parameters
        ----------
        work_id : str
            The NREGASoft work identifier.

        Returns
        -------
        ComparisonReport
            Structured comparison report with image paths and summary.
        """
        logger.info("Generating comparison report for work {w}", w=work_id)

        report_id = f"RPT-SAT-{uuid.uuid4().hex[:10].upper()}"

        # Retrieve cached verification result
        result = self._get_cached_result(work_id)
        if result is None:
            return ComparisonReport(
                work_id=work_id,
                report_id=report_id,
                result=VerificationResult(
                    work_id=work_id,
                    work_type=WorkType.OTHER,
                    verification_status=VerificationStatus.INSUFFICIENT_DATA,
                    confidence_score=0.0,
                ),
                summary="No verification data available for this work.",
            )

        # Build summary text
        summary_lines = [
            f"Satellite Verification Report for Work ID: {work_id}",
            f"Work Type: {result.work_type.value}",
            f"Verification Status: {result.verification_status.value}",
            f"Confidence Score: {result.confidence_score:.2%}",
            "",
        ]

        if result.ndvi_change is not None:
            summary_lines.append(
                f"NDVI Change (mean in affected area): {result.ndvi_change:.4f}"
            )

        if result.measurements:
            summary_lines.append("")
            summary_lines.append("Measurement Comparisons:")
            for m in result.measurements:
                summary_lines.append(
                    f"  - {m.dimension}: estimated={m.estimated_value:.1f}, "
                    f"reported={m.reported_value:.1f}, "
                    f"deviation={m.deviation_pct:.1f}%, "
                    f"confidence={m.confidence:.2%}"
                )

        if result.notes:
            summary_lines.append("")
            summary_lines.append("Notes:")
            for note in result.notes:
                summary_lines.append(f"  - {note}")

        report = ComparisonReport(
            work_id=work_id,
            report_id=report_id,
            result=result,
            before_image_path=result.before_image_id,
            after_image_path=result.after_image_id,
            change_overlay_path=result.change_mask_id,
            summary="\n".join(summary_lines),
        )

        logger.info(
            "Comparison report generated | report_id={r} | work={w}",
            r=report_id,
            w=work_id,
        )
        return report

    # ------------------------------------------------------------------
    # Private helpers -- spectral index computation
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_ndvi(image: SatelliteImage) -> np.ndarray:
        """Compute Normalised Difference Vegetation Index.

        NDVI = (NIR - RED) / (NIR + RED)

        Values range from -1 to +1; healthy vegetation typically > 0.3.
        """
        nir = image.bands.get("B08", np.zeros((1, 1))).astype(np.float64)
        red = image.bands.get("B04", np.zeros((1, 1))).astype(np.float64)

        denominator = nir + red
        # Avoid division by zero
        denominator = np.where(denominator == 0, 1e-10, denominator)

        ndvi = (nir - red) / denominator
        return np.clip(ndvi, -1.0, 1.0)

    @staticmethod
    def _compute_bare_soil_index(image: SatelliteImage) -> np.ndarray:
        """Compute a bare-soil index using SWIR and visible bands.

        BSI = ((SWIR1 + RED) - (NIR + BLUE)) / ((SWIR1 + RED) + (NIR + BLUE))

        Higher values indicate exposed earth / bare soil.
        """
        swir1 = image.bands.get("B11", np.zeros((1, 1))).astype(np.float64)
        red = image.bands.get("B04", np.zeros((1, 1))).astype(np.float64)
        nir = image.bands.get("B08", np.zeros((1, 1))).astype(np.float64)
        blue = image.bands.get("B02", np.zeros((1, 1))).astype(np.float64)

        # Resample SWIR to 10m if needed (SWIR is natively 20m)
        if swir1.shape != red.shape:
            swir1 = np.repeat(np.repeat(swir1, 2, axis=0), 2, axis=1)
            swir1 = swir1[: red.shape[0], : red.shape[1]]

        numerator = (swir1 + red) - (nir + blue)
        denominator = (swir1 + red) + (nir + blue)
        denominator = np.where(denominator == 0, 1e-10, denominator)

        bsi = numerator / denominator
        return bsi

    @staticmethod
    def _compute_ndwi(image: SatelliteImage) -> np.ndarray:
        """Compute Normalised Difference Water Index for water detection.

        NDWI = (GREEN - NIR) / (GREEN + NIR)

        Positive values suggest water presence.
        """
        green = image.bands.get("B03", np.zeros((1, 1))).astype(np.float64)
        nir = image.bands.get("B08", np.zeros((1, 1))).astype(np.float64)

        denominator = green + nir
        denominator = np.where(denominator == 0, 1e-10, denominator)

        ndwi = (green - nir) / denominator
        return ndwi

    # ------------------------------------------------------------------
    # Private helpers -- image processing
    # ------------------------------------------------------------------

    @staticmethod
    def _otsu_threshold(image: np.ndarray) -> float:
        """Compute Otsu's adaptive threshold for a single-channel image.

        Returns the optimal threshold that minimises intra-class variance.
        """
        # Flatten and remove NaN/inf
        flat = image.flatten()
        flat = flat[np.isfinite(flat)]
        if len(flat) == 0:
            return 0.5

        # Histogram with 256 bins over the data range
        hist, bin_edges = np.histogram(flat, bins=256)
        bin_centres = (bin_edges[:-1] + bin_edges[1:]) / 2

        total = hist.sum()
        if total == 0:
            return float(np.median(flat))

        current_max = 0.0
        threshold = float(bin_centres[0])
        sum_total = np.dot(bin_centres, hist)
        sum_bg = 0.0
        weight_bg = 0

        for i, (count, centre) in enumerate(zip(hist, bin_centres)):
            weight_bg += count
            if weight_bg == 0:
                continue
            weight_fg = total - weight_bg
            if weight_fg == 0:
                break

            sum_bg += count * centre
            mean_bg = sum_bg / weight_bg
            mean_fg = (sum_total - sum_bg) / weight_fg
            between_var = weight_bg * weight_fg * (mean_bg - mean_fg) ** 2

            if between_var > current_max:
                current_max = between_var
                threshold = float(centre)

        return threshold

    @staticmethod
    def _morphological_cleanup(
        mask: np.ndarray, kernel_size: int = 3
    ) -> np.ndarray:
        """Apply morphological opening then closing to clean a binary mask.

        Removes small noise blobs (opening) and fills small holes (closing).
        Uses a simple box kernel convolution approach.
        """
        kernel = np.ones((kernel_size, kernel_size), dtype=np.uint8)

        # Erosion (numpy-only approximation)
        def _erode(m: np.ndarray, k: np.ndarray) -> np.ndarray:
            pad = k.shape[0] // 2
            padded = np.pad(m, pad, mode="constant", constant_values=0)
            out = np.zeros_like(m)
            for i in range(m.shape[0]):
                for j in range(m.shape[1]):
                    region = padded[i : i + k.shape[0], j : j + k.shape[1]]
                    out[i, j] = 1 if np.all(region[k == 1] == 1) else 0
            return out

        # Dilation
        def _dilate(m: np.ndarray, k: np.ndarray) -> np.ndarray:
            pad = k.shape[0] // 2
            padded = np.pad(m, pad, mode="constant", constant_values=0)
            out = np.zeros_like(m)
            for i in range(m.shape[0]):
                for j in range(m.shape[1]):
                    region = padded[i : i + k.shape[0], j : j + k.shape[1]]
                    out[i, j] = 1 if np.any(region[k == 1] == 1) else 0
            return out

        # Opening = erosion then dilation (removes small objects)
        opened = _dilate(_erode(mask, kernel), kernel)
        # Closing = dilation then erosion (fills small holes)
        closed = _erode(_dilate(opened, kernel), kernel)

        return closed

    @staticmethod
    def _skeletonise(mask: np.ndarray) -> np.ndarray:
        """Compute the morphological skeleton (medial axis) of a binary mask.

        Uses iterative thinning. The skeleton preserves the topology
        of the shape while reducing it to single-pixel-wide lines.
        """
        skeleton = np.zeros_like(mask)
        element = np.ones((3, 3), dtype=np.uint8)
        temp = mask.copy()

        max_iterations = min(mask.shape[0], mask.shape[1]) // 2
        for _ in range(max_iterations):
            # Erosion step
            eroded = np.zeros_like(temp)
            pad = 1
            padded = np.pad(temp, pad, mode="constant", constant_values=0)
            for i in range(temp.shape[0]):
                for j in range(temp.shape[1]):
                    region = padded[i : i + 3, j : j + 3]
                    eroded[i, j] = 1 if np.all(region[element == 1] == 1) else 0

            # Dilation of eroded
            dilated = np.zeros_like(eroded)
            padded_e = np.pad(eroded, pad, mode="constant", constant_values=0)
            for i in range(eroded.shape[0]):
                for j in range(eroded.shape[1]):
                    region = padded_e[i : i + 3, j : j + 3]
                    dilated[i, j] = (
                        1 if np.any(region[element == 1] == 1) else 0
                    )

            # Opening residue
            diff = temp - dilated
            skeleton = np.maximum(skeleton, diff)
            temp = eroded.copy()

            if np.sum(temp) == 0:
                break

        return skeleton

    @staticmethod
    def _connected_components(
        mask: np.ndarray,
    ) -> Tuple[np.ndarray, int]:
        """Label connected components in a binary mask (4-connectivity).

        Returns the labelled array and the number of distinct components.
        """
        labels = np.zeros_like(mask, dtype=np.int32)
        current_label = 0

        for i in range(mask.shape[0]):
            for j in range(mask.shape[1]):
                if mask[i, j] == 1 and labels[i, j] == 0:
                    current_label += 1
                    # BFS flood fill
                    queue = [(i, j)]
                    labels[i, j] = current_label
                    while queue:
                        ci, cj = queue.pop(0)
                        for di, dj in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                            ni, nj = ci + di, cj + dj
                            if (
                                0 <= ni < mask.shape[0]
                                and 0 <= nj < mask.shape[1]
                                and mask[ni, nj] == 1
                                and labels[ni, nj] == 0
                            ):
                                labels[ni, nj] = current_label
                                queue.append((ni, nj))

        return labels, current_label

    @staticmethod
    def _compute_compactness(component_mask: np.ndarray) -> float:
        """Compute compactness (isoperimetric ratio) of a binary region.

        Compactness = 4 * pi * Area / Perimeter^2
        A perfect circle has compactness = 1.0.
        """
        area = int(np.sum(component_mask))
        if area == 0:
            return 0.0

        # Estimate perimeter by counting boundary pixels
        perimeter = 0
        for i in range(component_mask.shape[0]):
            for j in range(component_mask.shape[1]):
                if component_mask[i, j] == 1:
                    is_boundary = False
                    for di, dj in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                        ni, nj = i + di, j + dj
                        if (
                            ni < 0
                            or ni >= component_mask.shape[0]
                            or nj < 0
                            or nj >= component_mask.shape[1]
                            or component_mask[ni, nj] == 0
                        ):
                            is_boundary = True
                            break
                    if is_boundary:
                        perimeter += 1

        if perimeter == 0:
            return 0.0

        compactness = (4 * np.pi * area) / (perimeter ** 2)
        return min(compactness, 1.0)

    @staticmethod
    def _compute_skeleton_coherence(
        skeleton: np.ndarray, mask: np.ndarray
    ) -> float:
        """Measure how well the skeleton represents the original mask.

        A coherent linear feature (road) will have a long skeleton
        relative to the mask width, yielding a high score.
        """
        skel_pixels = int(np.sum(skeleton > 0))
        mask_pixels = int(np.sum(mask > 0))

        if mask_pixels == 0 or skel_pixels == 0:
            return 0.0

        # Aspect ratio proxy: skel_length / sqrt(area) -- high for linear features
        linearity = skel_pixels / np.sqrt(mask_pixels)
        return min(linearity / 5.0, 1.0)

    # ------------------------------------------------------------------
    # Private helpers -- measurement pipeline
    # ------------------------------------------------------------------

    def _estimate_measurements(
        self,
        work_type: WorkType,
        change_mask: np.ndarray,
        pixel_resolution: float,
        work: Dict[str, Any],
    ) -> List[MeasurementEstimate]:
        """Route to the appropriate measurement estimator by work type."""
        measurements: List[MeasurementEstimate] = []

        if work_type == WorkType.ROAD:
            length_est = self.estimate_road_length(change_mask, pixel_resolution)
            length_est.reported_value = work.get("reported_length_m", 0.0)
            if length_est.reported_value > 0:
                length_est.deviation_pct = round(
                    abs(length_est.estimated_value - length_est.reported_value)
                    / length_est.reported_value
                    * 100,
                    1,
                )
            measurements.append(length_est)

            # Also estimate width
            width_est = self._estimate_road_width(change_mask, pixel_resolution)
            width_est.reported_value = work.get("reported_width_m", 0.0)
            if width_est.reported_value > 0:
                width_est.deviation_pct = round(
                    abs(width_est.estimated_value - width_est.reported_value)
                    / width_est.reported_value
                    * 100,
                    1,
                )
            measurements.append(width_est)

        elif work_type in (WorkType.POND, WorkType.TANK):
            area_est = self.estimate_pond_area(change_mask, pixel_resolution)
            area_est.reported_value = work.get("reported_area_sqm", 0.0)
            if area_est.reported_value > 0:
                area_est.deviation_pct = round(
                    abs(area_est.estimated_value - area_est.reported_value)
                    / area_est.reported_value
                    * 100,
                    1,
                )
            measurements.append(area_est)

            # Depth indicator from spectral analysis
            depth_est = self._estimate_depth_indicator(change_mask, pixel_resolution)
            measurements.append(depth_est)

        elif work_type in (WorkType.CANAL, WorkType.CHANNEL):
            length_est = self.estimate_road_length(change_mask, pixel_resolution)
            length_est.dimension = "channel_length_m"
            length_est.reported_value = work.get("reported_length_m", 0.0)
            if length_est.reported_value > 0:
                length_est.deviation_pct = round(
                    abs(length_est.estimated_value - length_est.reported_value)
                    / length_est.reported_value
                    * 100,
                    1,
                )
            measurements.append(length_est)

        elif work_type == WorkType.LAND_LEVELLING:
            area_est = self._estimate_levelling_area(change_mask, pixel_resolution)
            area_est.reported_value = work.get("reported_area_sqm", 0.0)
            if area_est.reported_value > 0:
                area_est.deviation_pct = round(
                    abs(area_est.estimated_value - area_est.reported_value)
                    / area_est.reported_value
                    * 100,
                    1,
                )
            measurements.append(area_est)

        return measurements

    def _evaluate_measurements(
        self,
        measurements: List[MeasurementEstimate],
        work_type: WorkType,
    ) -> Tuple[float, VerificationStatus]:
        """Evaluate measurement estimates and produce a verdict.

        Returns overall confidence and verification status.
        """
        if not measurements:
            return 0.0, VerificationStatus.NOT_DETECTED

        # Average confidence across all measurement dimensions
        avg_confidence = np.mean([m.confidence for m in measurements])

        # Check if any measurement has a valid estimated value
        has_detection = any(m.estimated_value > 0 for m in measurements)
        if not has_detection:
            return float(avg_confidence), VerificationStatus.NOT_DETECTED

        # Check deviations
        deviations = [
            m.deviation_pct for m in measurements if m.reported_value > 0
        ]

        if not deviations:
            return float(avg_confidence), VerificationStatus.PARTIAL_MATCH

        max_deviation = max(deviations)
        avg_deviation = np.mean(deviations)

        if avg_deviation <= self.tolerance_pct:
            status = VerificationStatus.VERIFIED
        elif avg_deviation <= self.tolerance_pct * 2:
            status = VerificationStatus.PARTIAL_MATCH
        else:
            status = VerificationStatus.MISMATCH

        return float(avg_confidence), status

    # ------------------------------------------------------------------
    # Private helpers -- auxiliary measurement methods
    # ------------------------------------------------------------------

    def _estimate_road_width(
        self, change_mask: np.ndarray, pixel_resolution: float
    ) -> MeasurementEstimate:
        """Estimate road width by dividing mask area by skeleton length."""
        skeleton = self._skeletonise(change_mask)
        skel_pixels = max(int(np.sum(skeleton > 0)), 1)
        mask_pixels = int(np.sum(change_mask > 0))
        estimated_width = (mask_pixels / skel_pixels) * pixel_resolution

        return MeasurementEstimate(
            dimension="width_m",
            estimated_value=round(estimated_width, 1),
            reported_value=0.0,
            deviation_pct=0.0,
            confidence=round(min(skel_pixels / 50.0, 1.0), 4),
            method="area_over_skeleton_length",
        )

    def _estimate_depth_indicator(
        self, change_mask: np.ndarray, pixel_resolution: float
    ) -> MeasurementEstimate:
        """Provide a relative depth indicator for ponds.

        Satellite imagery cannot directly measure depth, but spectral
        absorption patterns in water can provide relative indicators.
        This is flagged as low-confidence qualitative data.
        """
        return MeasurementEstimate(
            dimension="depth_indicator",
            estimated_value=0.0,
            reported_value=0.0,
            deviation_pct=0.0,
            confidence=0.2,
            method="spectral_absorption_proxy",
        )

    def _estimate_levelling_area(
        self, change_mask: np.ndarray, pixel_resolution: float
    ) -> MeasurementEstimate:
        """Estimate land levelling area from change mask."""
        area_pixels = int(np.sum(change_mask > 0))
        area_sqm = area_pixels * (pixel_resolution ** 2)

        confidence = min(area_pixels / 200.0, 1.0)
        return MeasurementEstimate(
            dimension="area_sqm",
            estimated_value=round(area_sqm, 1),
            reported_value=0.0,
            deviation_pct=0.0,
            confidence=round(confidence, 4),
            method="pixel_count_area",
        )

    def _compute_spectral_signatures(
        self, image: SatelliteImage, change_mask: np.ndarray
    ) -> Dict[str, float]:
        """Extract mean spectral values in changed regions for evidence."""
        signatures: Dict[str, float] = {}
        mask_bool = change_mask.astype(bool)

        for band_name, band_data in image.bands.items():
            if band_data.shape == mask_bool.shape and np.sum(mask_bool) > 0:
                mean_val = float(np.mean(band_data[mask_bool]))
                signatures[band_name] = round(mean_val, 4)

        return signatures

    # ------------------------------------------------------------------
    # Private helpers -- geographic utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _build_bbox(
        lat: float, lon: float, buffer_m: float
    ) -> BoundingBox:
        """Build a bounding box centred on a GPS point with a buffer.

        Converts metre buffer to approximate degrees at the given latitude.
        """
        # Approximate degrees per metre at this latitude
        lat_deg_per_m = 1.0 / 111320.0
        lon_deg_per_m = 1.0 / (111320.0 * np.cos(np.radians(lat)))

        dlat = buffer_m * lat_deg_per_m
        dlon = buffer_m * lon_deg_per_m

        return BoundingBox(
            min_lat=lat - dlat,
            min_lon=lon - dlon,
            max_lat=lat + dlat,
            max_lon=lon + dlon,
        )

    # ------------------------------------------------------------------
    # Private helpers -- data I/O
    # ------------------------------------------------------------------

    async def _fetch_work_details(self, work_id: str) -> Optional[Dict[str, Any]]:
        """Fetch work metadata from NREGASoft database."""
        try:
            query = """
                SELECT w.work_id,
                       w.work_name,
                       w.work_type,
                       w.latitude,
                       w.longitude,
                       w.start_date,
                       w.completion_date,
                       w.reported_length_m,
                       w.reported_width_m,
                       w.reported_area_sqm,
                       w.reported_depth_m,
                       w.total_expenditure,
                       w.gram_panchayat_id,
                       w.block_id,
                       w.district_id,
                       w.state_code,
                       w.financial_year,
                       w.scheme_code
                FROM   works w
                WHERE  w.work_id = :work_id
            """
            row = await self.db.fetch_one(query, {"work_id": work_id})
            return dict(row) if row else None
        except Exception as exc:
            logger.error(
                "Failed to fetch work details for {w}: {e}", w=work_id, e=exc
            )
            return None

    async def _acquire_imagery(
        self,
        bbox: BoundingBox,
        date_window: Tuple[datetime, datetime],
    ) -> Optional[SatelliteImage]:
        """Acquire the best available Sentinel-2 scene for a spatiotemporal window.

        Queries the imagery provider for scenes within the date window
        and bounding box, selects the one with lowest cloud cover, and
        retrieves the required bands.
        """
        try:
            scenes = await self.imagery.search(
                bbox={
                    "min_lat": bbox.min_lat,
                    "min_lon": bbox.min_lon,
                    "max_lat": bbox.max_lat,
                    "max_lon": bbox.max_lon,
                },
                start_date=date_window[0].isoformat(),
                end_date=date_window[1].isoformat(),
                max_cloud_cover=self.max_cloud,
                sort_by="cloud_cover",
                limit=5,
            )

            if not scenes:
                logger.warning(
                    "No suitable imagery found for bbox={b} window={w}",
                    b=bbox,
                    w=date_window,
                )
                return None

            best = scenes[0]
            bands = await self.imagery.fetch_bands(
                scene_id=best["scene_id"],
                bands=[
                    self.BAND_RED,
                    self.BAND_NIR,
                    self.BAND_SWIR1,
                    self.BAND_SWIR2,
                    self.BAND_GREEN,
                    self.BAND_BLUE,
                ],
                bbox={
                    "min_lat": bbox.min_lat,
                    "min_lon": bbox.min_lon,
                    "max_lat": bbox.max_lat,
                    "max_lon": bbox.max_lon,
                },
            )

            return SatelliteImage(
                scene_id=best["scene_id"],
                acquisition_date=datetime.fromisoformat(
                    best["acquisition_date"]
                ),
                bands=bands,
                cloud_cover_pct=best.get("cloud_cover", 0.0),
                bbox=bbox,
                pixel_resolution_m=best.get("resolution", 10.0),
            )

        except Exception as exc:
            logger.error("Imagery acquisition failed: {e}", e=exc)
            return None

    async def _save_comparison_image(
        self,
        image: SatelliteImage,
        work_id: str,
        label: str,
    ) -> Optional[str]:
        """Save a natural-colour composite to object storage."""
        try:
            # Create RGB composite from bands 4, 3, 2
            red = image.bands.get("B04", np.zeros((10, 10)))
            green = image.bands.get("B03", np.zeros((10, 10)))
            blue = image.bands.get("B02", np.zeros((10, 10)))

            rgb = np.stack([red, green, blue], axis=-1)
            # Normalise to 0-255
            rgb_min, rgb_max = rgb.min(), rgb.max()
            if rgb_max > rgb_min:
                rgb = ((rgb - rgb_min) / (rgb_max - rgb_min) * 255).astype(
                    np.uint8
                )
            else:
                rgb = np.zeros_like(rgb, dtype=np.uint8)

            path = f"satellite/{work_id}/{label}_{image.scene_id}.png"
            await self.storage.upload(path=path, data=rgb.tobytes())
            return path

        except Exception as exc:
            logger.error("Failed to save comparison image: {e}", e=exc)
            return None

    async def _save_change_mask(
        self,
        mask: np.ndarray,
        bbox: BoundingBox,
        work_id: str,
    ) -> Optional[str]:
        """Save change detection mask overlay to object storage."""
        try:
            path = f"satellite/{work_id}/change_mask.png"
            await self.storage.upload(
                path=path, data=(mask * 255).astype(np.uint8).tobytes()
            )
            return path
        except Exception as exc:
            logger.error("Failed to save change mask: {e}", e=exc)
            return None

    async def _save_verification_result(
        self, result: VerificationResult
    ) -> None:
        """Persist verification result to the database."""
        try:
            query = """
                INSERT INTO satellite_verifications
                    (work_id, verification_status, confidence_score,
                     ndvi_change, before_image_id, after_image_id,
                     change_mask_id, verified_at)
                VALUES
                    (:work_id, :status, :confidence, :ndvi, :before_id,
                     :after_id, :mask_id, :verified_at)
                ON CONFLICT (work_id)
                DO UPDATE SET
                    verification_status = :status,
                    confidence_score    = :confidence,
                    ndvi_change         = :ndvi,
                    verified_at         = :verified_at
            """
            await self.db.execute(
                query,
                {
                    "work_id": result.work_id,
                    "status": result.verification_status.value,
                    "confidence": result.confidence_score,
                    "ndvi": result.ndvi_change,
                    "before_id": result.before_image_id,
                    "after_id": result.after_image_id,
                    "mask_id": result.change_mask_id,
                    "verified_at": result.verified_at.isoformat(),
                },
            )
        except Exception as exc:
            logger.error(
                "Failed to persist verification for {w}: {e}",
                w=result.work_id,
                e=exc,
            )

    def _get_cached_result(self, work_id: str) -> Optional[VerificationResult]:
        """Retrieve a cached verification result (in-memory placeholder)."""
        # In production this would query the DB; here we return None
        # to signal that the caller should run verify_work first.
        return None
