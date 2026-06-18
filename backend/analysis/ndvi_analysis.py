"""
NDVI Change Detection Engine
=============================

Performs multi-spectral index analysis on Sentinel-2 imagery to detect
physical changes on the ground corresponding to MGNREGA works such as
road construction, pond excavation, land leveling, and canal building.

Supported indices:
    - NDVI  (Normalized Difference Vegetation Index)
    - NDWI  (Normalized Difference Water Index)
    - BSI   (Bare Soil Index)

The engine compares *before* and *after* imagery for a reported work
period and produces change maps, classified change types, and area
statistics that feed into the verification pipeline.
"""

from __future__ import annotations

from enum import IntEnum, auto
from typing import Any, Dict, Optional, Tuple

import numpy as np
from loguru import logger


# ---------------------------------------------------------------------------
# Sentinel-2 Scene Classification Layer (SCL) values
# ---------------------------------------------------------------------------
class SCLClass(IntEnum):
    """Sentinel-2 Level-2A Scene Classification values."""
    NO_DATA = 0
    SATURATED_DEFECTIVE = 1
    DARK_AREA_SHADOWS = 2  # topographic shadows
    CLOUD_SHADOWS = 3
    VEGETATION = 4
    BARE_SOILS = 5
    WATER = 6
    CLOUD_LOW_PROBABILITY = 7
    CLOUD_MEDIUM_PROBABILITY = 8
    CLOUD_HIGH_PROBABILITY = 9
    THIN_CIRRUS = 10
    SNOW_ICE = 11


# SCL classes that should be masked before analysis
_MASK_SCL_CLASSES: frozenset[int] = frozenset({
    SCLClass.NO_DATA,
    SCLClass.SATURATED_DEFECTIVE,
    SCLClass.CLOUD_SHADOWS,
    SCLClass.CLOUD_MEDIUM_PROBABILITY,
    SCLClass.CLOUD_HIGH_PROBABILITY,
    SCLClass.THIN_CIRRUS,
    SCLClass.SNOW_ICE,
})


# ---------------------------------------------------------------------------
# Change-type classification labels
# ---------------------------------------------------------------------------
class ChangeType(IntEnum):
    """Pixel-level change classification."""
    NO_CHANGE = 0
    VEGETATION_CLEARED = auto()      # road / site clearance
    WATER_BODY_CREATED = auto()      # pond / tank / percolation pit
    SOIL_DISTURBANCE = auto()        # earthwork / land leveling
    MIXED_CHANGE = auto()            # composite signal
    UNCLASSIFIED = auto()


class NDVIAnalyzer:
    """Sentinel-2 multi-spectral change detection for MGNREGA verification.

    All band arrays are expected as 2-D ``numpy`` arrays of ``float32`` or
    ``float64`` reflectance values (0-1 scale).  The engine is stateless;
    every method is a pure function operating on the arrays passed in.

    Parameters
    ----------
    cloud_mask_scl_classes : frozenset[int] | None
        SCL class IDs to mask out.  Defaults to clouds, shadows, snow, and
        no-data pixels.
    nodata_value : float
        Sentinel value written into masked pixels.  Defaults to ``np.nan``.
    """

    def __init__(
        self,
        cloud_mask_scl_classes: Optional[frozenset[int]] = None,
        nodata_value: float = np.nan,
    ) -> None:
        self._mask_classes = cloud_mask_scl_classes or _MASK_SCL_CLASSES
        self._nodata = nodata_value
        logger.info(
            "NDVIAnalyzer initialised  |  masked SCL classes={classes}  nodata={nd}",
            classes=sorted(self._mask_classes),
            nd=self._nodata,
        )

    # ------------------------------------------------------------------
    # Cloud / quality masking
    # ------------------------------------------------------------------
    def apply_cloud_mask(
        self,
        band: np.ndarray,
        scl_band: np.ndarray,
    ) -> np.ndarray:
        """Mask out clouds, shadows, snow, and defective pixels using the
        Sentinel-2 Scene Classification Layer (SCL).

        Parameters
        ----------
        band : np.ndarray
            2-D reflectance array for any single band.
        scl_band : np.ndarray
            2-D SCL array (integer class codes) of the same spatial extent.

        Returns
        -------
        np.ndarray
            Copy of *band* with masked pixels set to ``self._nodata``.
        """
        if band.shape != scl_band.shape:
            raise ValueError(
                f"Band shape {band.shape} does not match SCL shape {scl_band.shape}"
            )
        mask = np.isin(scl_band, list(self._mask_classes))
        masked_band = band.astype(np.float64, copy=True)
        masked_band[mask] = self._nodata
        pct_masked = 100.0 * np.count_nonzero(mask) / mask.size
        logger.debug("Cloud mask applied  |  {pct:.1f}% pixels masked", pct=pct_masked)
        return masked_band

    # ------------------------------------------------------------------
    # Spectral index calculations
    # ------------------------------------------------------------------
    @staticmethod
    def _safe_normalised_diff(a: np.ndarray, b: np.ndarray) -> np.ndarray:
        """Compute (a - b) / (a + b) with safe division.

        Where the denominator is zero the result is set to ``0.0``.
        NaN values in either input propagate through.
        """
        numerator = a.astype(np.float64) - b.astype(np.float64)
        denominator = a.astype(np.float64) + b.astype(np.float64)
        with np.errstate(divide="ignore", invalid="ignore"):
            result = np.where(denominator != 0, numerator / denominator, 0.0)
        return result

    def calculate_ndvi(
        self,
        red_band: np.ndarray,
        nir_band: np.ndarray,
    ) -> np.ndarray:
        """Calculate Normalized Difference Vegetation Index.

        NDVI = (NIR - Red) / (NIR + Red)

        Values range from -1 to +1.  Healthy vegetation yields high positive
        values; bare soil and water yield values near or below 0.

        Parameters
        ----------
        red_band : np.ndarray
            Sentinel-2 Band 4 (Red, 665 nm) reflectance.
        nir_band : np.ndarray
            Sentinel-2 Band 8 (NIR, 842 nm) reflectance.

        Returns
        -------
        np.ndarray
            NDVI image in [-1, 1].
        """
        if red_band.shape != nir_band.shape:
            raise ValueError("Red and NIR bands must have the same shape.")
        ndvi = self._safe_normalised_diff(nir_band, red_band)
        logger.debug(
            "NDVI computed  |  min={lo:.3f}  max={hi:.3f}  mean={mu:.3f}",
            lo=float(np.nanmin(ndvi)),
            hi=float(np.nanmax(ndvi)),
            mu=float(np.nanmean(ndvi)),
        )
        return ndvi

    def calculate_ndwi(
        self,
        green_band: np.ndarray,
        nir_band: np.ndarray,
    ) -> np.ndarray:
        """Calculate Normalized Difference Water Index (McFeeters).

        NDWI = (Green - NIR) / (Green + NIR)

        Positive values indicate open water surfaces; useful for detecting
        newly excavated ponds and tanks.

        Parameters
        ----------
        green_band : np.ndarray
            Sentinel-2 Band 3 (Green, 560 nm) reflectance.
        nir_band : np.ndarray
            Sentinel-2 Band 8 (NIR, 842 nm) reflectance.

        Returns
        -------
        np.ndarray
            NDWI image in [-1, 1].
        """
        if green_band.shape != nir_band.shape:
            raise ValueError("Green and NIR bands must have the same shape.")
        ndwi = self._safe_normalised_diff(green_band, nir_band)
        logger.debug(
            "NDWI computed  |  min={lo:.3f}  max={hi:.3f}  mean={mu:.3f}",
            lo=float(np.nanmin(ndwi)),
            hi=float(np.nanmax(ndwi)),
            mu=float(np.nanmean(ndwi)),
        )
        return ndwi

    def calculate_bsi(
        self,
        blue_band: np.ndarray,
        red_band: np.ndarray,
        nir_band: np.ndarray,
        swir_band: np.ndarray,
    ) -> np.ndarray:
        """Calculate Bare Soil Index for earthwork detection.

        BSI = ((SWIR + Red) - (NIR + Blue)) / ((SWIR + Red) + (NIR + Blue))

        High values indicate exposed soil from recent earthwork such as
        road grading, embankment construction, or land leveling.

        Parameters
        ----------
        blue_band : np.ndarray   Sentinel-2 Band 2 (490 nm)
        red_band  : np.ndarray   Sentinel-2 Band 4 (665 nm)
        nir_band  : np.ndarray   Sentinel-2 Band 8 (842 nm)
        swir_band : np.ndarray   Sentinel-2 Band 11 (1610 nm) or Band 12

        Returns
        -------
        np.ndarray
            BSI image in [-1, 1].
        """
        shapes = {b.shape for b in (blue_band, red_band, nir_band, swir_band)}
        if len(shapes) != 1:
            raise ValueError(
                "All four bands must share the same spatial dimensions. "
                f"Got shapes: {shapes}"
            )
        numerator = (swir_band + red_band) - (nir_band + blue_band)
        denominator = (swir_band + red_band) + (nir_band + blue_band)
        with np.errstate(divide="ignore", invalid="ignore"):
            bsi = np.where(denominator != 0, numerator / denominator, 0.0)
        bsi = bsi.astype(np.float64)
        logger.debug(
            "BSI computed  |  min={lo:.3f}  max={hi:.3f}  mean={mu:.3f}",
            lo=float(np.nanmin(bsi)),
            hi=float(np.nanmax(bsi)),
            mu=float(np.nanmean(bsi)),
        )
        return bsi

    # ------------------------------------------------------------------
    # Change detection
    # ------------------------------------------------------------------
    def compute_change_map(
        self,
        before_index: np.ndarray,
        after_index: np.ndarray,
        threshold: float = 0.15,
    ) -> np.ndarray:
        """Generate a binary change mask from two temporal index images.

        A pixel is flagged as *changed* if the absolute difference exceeds
        *threshold*.  NaN pixels in either image are treated as no-change.

        Parameters
        ----------
        before_index : np.ndarray   Pre-work spectral index image.
        after_index  : np.ndarray   Post-work spectral index image.
        threshold    : float         Minimum absolute delta to flag change.

        Returns
        -------
        np.ndarray
            Boolean mask (``True`` = changed pixel).
        """
        if before_index.shape != after_index.shape:
            raise ValueError("Temporal images must have identical dimensions.")
        diff = after_index.astype(np.float64) - before_index.astype(np.float64)
        # NaN-safe comparison: NaN differences are not flagged
        change_mask = np.abs(diff) > threshold
        change_mask[np.isnan(diff)] = False
        n_changed = int(np.count_nonzero(change_mask))
        logger.info(
            "Change map  |  threshold={t:.2f}  changed_pixels={n}  "
            "({pct:.2f}% of valid area)",
            t=threshold,
            n=n_changed,
            pct=100.0 * n_changed / max(change_mask.size, 1),
        )
        return change_mask

    def detect_vegetation_loss(
        self,
        before_ndvi: np.ndarray,
        after_ndvi: np.ndarray,
        loss_threshold: float = 0.15,
    ) -> np.ndarray:
        """Detect areas where vegetation was cleared (NDVI decrease).

        Vegetation loss is a strong indicator of ground preparation for road
        construction, pond excavation, or site clearance works.

        Returns
        -------
        np.ndarray
            Boolean mask where ``True`` = significant vegetation loss.
        """
        diff = after_ndvi.astype(np.float64) - before_ndvi.astype(np.float64)
        loss_mask = diff < -abs(loss_threshold)
        loss_mask[np.isnan(diff)] = False
        logger.info(
            "Vegetation loss detected  |  pixels={n}",
            n=int(np.count_nonzero(loss_mask)),
        )
        return loss_mask

    def detect_water_body_change(
        self,
        before_ndwi: np.ndarray,
        after_ndwi: np.ndarray,
        gain_threshold: float = 0.20,
    ) -> np.ndarray:
        """Detect new water bodies (NDWI increase).

        An increase in NDWI indicates newly filled ponds, tanks, or
        percolation pits -- key MGNREGA water-conservation assets.

        Returns
        -------
        np.ndarray
            Boolean mask where ``True`` = new water body pixels.
        """
        diff = after_ndwi.astype(np.float64) - before_ndwi.astype(np.float64)
        water_mask = diff > abs(gain_threshold)
        water_mask[np.isnan(diff)] = False
        logger.info(
            "Water body change detected  |  new_water_pixels={n}",
            n=int(np.count_nonzero(water_mask)),
        )
        return water_mask

    def detect_soil_disturbance(
        self,
        before_bsi: np.ndarray,
        after_bsi: np.ndarray,
        disturbance_threshold: float = 0.12,
    ) -> np.ndarray:
        """Detect ground disturbance from earthwork (BSI increase).

        A BSI increase signals freshly exposed soil from excavation,
        embankment construction, or land leveling activities.

        Returns
        -------
        np.ndarray
            Boolean mask where ``True`` = soil disturbance.
        """
        diff = after_bsi.astype(np.float64) - before_bsi.astype(np.float64)
        soil_mask = diff > abs(disturbance_threshold)
        soil_mask[np.isnan(diff)] = False
        logger.info(
            "Soil disturbance detected  |  pixels={n}",
            n=int(np.count_nonzero(soil_mask)),
        )
        return soil_mask

    # ------------------------------------------------------------------
    # Change classification
    # ------------------------------------------------------------------
    def classify_change_type(
        self,
        change_map: np.ndarray,
        ndvi_change: np.ndarray,
        ndwi_change: np.ndarray,
        bsi_change: np.ndarray,
    ) -> np.ndarray:
        """Classify each changed pixel into a work-related category.

        Classification logic (evaluated in priority order):
            1. NDWI gain  > 0.20  -->  WATER_BODY_CREATED
            2. BSI  gain  > 0.12  -->  SOIL_DISTURBANCE
            3. NDVI loss  > 0.15  -->  VEGETATION_CLEARED
            4. Multiple indices change  -->  MIXED_CHANGE
            5. Changed but no clear type -->  UNCLASSIFIED

        Parameters
        ----------
        change_map   : np.ndarray  Boolean mask from ``compute_change_map``.
        ndvi_change  : np.ndarray  ``after_ndvi - before_ndvi``.
        ndwi_change  : np.ndarray  ``after_ndwi - before_ndwi``.
        bsi_change   : np.ndarray  ``after_bsi  - before_bsi``.

        Returns
        -------
        np.ndarray
            Integer array of ``ChangeType`` values.
        """
        shapes = {a.shape for a in (change_map, ndvi_change, ndwi_change, bsi_change)}
        if len(shapes) != 1:
            raise ValueError("All input arrays must share the same shape.")

        classified = np.full(change_map.shape, ChangeType.NO_CHANGE, dtype=np.int8)

        # Only classify within the change mask
        changed = change_map.astype(bool)

        is_water = changed & (ndwi_change > 0.20)
        is_soil = changed & (bsi_change > 0.12)
        is_veg_loss = changed & (ndvi_change < -0.15)

        # Count how many indices flagged each pixel
        flag_count = is_water.astype(int) + is_soil.astype(int) + is_veg_loss.astype(int)

        # Single-index changes
        classified[is_water & (flag_count == 1)] = ChangeType.WATER_BODY_CREATED
        classified[is_soil & (flag_count == 1)] = ChangeType.SOIL_DISTURBANCE
        classified[is_veg_loss & (flag_count == 1)] = ChangeType.VEGETATION_CLEARED

        # Multi-index overlap
        classified[flag_count > 1] = ChangeType.MIXED_CHANGE

        # Changed but uncategorised
        classified[changed & (flag_count == 0)] = ChangeType.UNCLASSIFIED

        # Log distribution
        unique, counts = np.unique(classified[changed], return_counts=True)
        for label, cnt in zip(unique, counts):
            logger.debug(
                "  ChangeType {name}={val}  |  pixels={c}",
                name=ChangeType(label).name,
                val=int(label),
                c=int(cnt),
            )
        return classified

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------
    def compute_change_statistics(
        self,
        change_map: np.ndarray,
        pixel_resolution: float = 10.0,
    ) -> Dict[str, Any]:
        """Compute area and percentage statistics for a change mask.

        Parameters
        ----------
        change_map       : np.ndarray  Boolean change mask.
        pixel_resolution : float       Ground sampling distance in metres
                                       (default 10 m for Sentinel-2 bands at
                                       10 m resolution).

        Returns
        -------
        dict
            ``total_pixels``          : int   -- pixels in raster
            ``changed_pixels``        : int   -- pixels flagged as changed
            ``valid_pixels``          : int   -- non-NaN pixels
            ``change_percentage``     : float -- % of valid area changed
            ``changed_area_sqm``      : float -- changed area in sq metres
            ``changed_area_hectares`` : float -- changed area in hectares
            ``pixel_area_sqm``        : float -- area of one pixel
        """
        total_pixels = int(change_map.size)
        # If change_map is float with NaN (shouldn't be, but handle it)
        if np.issubdtype(change_map.dtype, np.floating):
            valid_mask = ~np.isnan(change_map)
            valid_pixels = int(np.count_nonzero(valid_mask))
            changed_pixels = int(np.count_nonzero(change_map[valid_mask]))
        else:
            valid_pixels = total_pixels
            changed_pixels = int(np.count_nonzero(change_map))

        pixel_area_sqm = pixel_resolution * pixel_resolution
        changed_area_sqm = changed_pixels * pixel_area_sqm
        change_pct = (
            100.0 * changed_pixels / valid_pixels if valid_pixels > 0 else 0.0
        )

        stats: Dict[str, Any] = {
            "total_pixels": total_pixels,
            "changed_pixels": changed_pixels,
            "valid_pixels": valid_pixels,
            "change_percentage": round(change_pct, 4),
            "changed_area_sqm": round(changed_area_sqm, 2),
            "changed_area_hectares": round(changed_area_sqm / 10_000, 4),
            "pixel_area_sqm": pixel_area_sqm,
        }
        logger.info(
            "Change statistics  |  {cp} pixels changed  |  "
            "{area:.1f} sqm  |  {pct:.2f}%",
            cp=changed_pixels,
            area=changed_area_sqm,
            pct=change_pct,
        )
        return stats

    # ------------------------------------------------------------------
    # Convenience: full pipeline for a single work site
    # ------------------------------------------------------------------
    def run_site_analysis(
        self,
        before_bands: Dict[str, np.ndarray],
        after_bands: Dict[str, np.ndarray],
        before_scl: Optional[np.ndarray] = None,
        after_scl: Optional[np.ndarray] = None,
        pixel_resolution: float = 10.0,
    ) -> Dict[str, Any]:
        """Run the complete multi-index change analysis pipeline for a site.

        Parameters
        ----------
        before_bands : dict  ``{"blue", "green", "red", "nir", "swir"}``
        after_bands  : dict  Same keys as *before_bands*.
        before_scl   : np.ndarray | None  SCL band for the before image.
        after_scl    : np.ndarray | None  SCL band for the after image.
        pixel_resolution : float  GSD in metres.

        Returns
        -------
        dict  Consolidated results with change maps, classification, and stats.
        """
        required_keys = {"red", "nir", "green"}
        for label, bands in [("before", before_bands), ("after", after_bands)]:
            missing = required_keys - set(bands.keys())
            if missing:
                raise ValueError(
                    f"'{label}' bands dict is missing keys: {missing}"
                )

        # --- Apply cloud masks if SCL is available ---
        def _mask(bands: dict, scl: Optional[np.ndarray]) -> dict:
            if scl is None:
                return bands
            return {k: self.apply_cloud_mask(v, scl) for k, v in bands.items()}

        b_before = _mask(before_bands, before_scl)
        b_after = _mask(after_bands, after_scl)

        # --- Compute indices ---
        ndvi_before = self.calculate_ndvi(b_before["red"], b_before["nir"])
        ndvi_after = self.calculate_ndvi(b_after["red"], b_after["nir"])

        ndwi_before = self.calculate_ndwi(b_before["green"], b_before["nir"])
        ndwi_after = self.calculate_ndwi(b_after["green"], b_after["nir"])

        has_bsi = all(
            k in b_before and k in b_after for k in ("blue", "swir")
        )
        if has_bsi:
            bsi_before = self.calculate_bsi(
                b_before["blue"], b_before["red"],
                b_before["nir"], b_before["swir"],
            )
            bsi_after = self.calculate_bsi(
                b_after["blue"], b_after["red"],
                b_after["nir"], b_after["swir"],
            )
        else:
            logger.warning(
                "Blue/SWIR bands not provided -- BSI analysis skipped."
            )
            bsi_before = np.zeros_like(ndvi_before)
            bsi_after = np.zeros_like(ndvi_after)

        # --- Change deltas ---
        ndvi_diff = ndvi_after - ndvi_before
        ndwi_diff = ndwi_after - ndwi_before
        bsi_diff = bsi_after - bsi_before

        # --- Binary change mask (union of all significant changes) ---
        composite_diff = np.sqrt(ndvi_diff ** 2 + ndwi_diff ** 2 + bsi_diff ** 2)
        # Replace NaN propagation with 0 for composite
        composite_diff = np.nan_to_num(composite_diff, nan=0.0)
        change_map = composite_diff > 0.15

        # --- Detection masks ---
        veg_loss = self.detect_vegetation_loss(ndvi_before, ndvi_after)
        water_new = self.detect_water_body_change(ndwi_before, ndwi_after)
        soil_dist = self.detect_soil_disturbance(bsi_before, bsi_after)

        # --- Classification ---
        classified = self.classify_change_type(
            change_map, ndvi_diff, ndwi_diff, bsi_diff,
        )

        # --- Statistics ---
        stats = self.compute_change_statistics(change_map, pixel_resolution)

        return {
            "ndvi_before": ndvi_before,
            "ndvi_after": ndvi_after,
            "ndwi_before": ndwi_before,
            "ndwi_after": ndwi_after,
            "bsi_before": bsi_before,
            "bsi_after": bsi_after,
            "change_map": change_map,
            "vegetation_loss_mask": veg_loss,
            "water_body_mask": water_new,
            "soil_disturbance_mask": soil_dist,
            "classified_change": classified,
            "statistics": stats,
        }
