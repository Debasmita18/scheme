"""
Earthwork Boundary Detection Module
====================================

Detects and measures MGNREGA physical assets from satellite-derived change
maps.  Combines morphological image processing, Hough line detection, and
contour analysis to identify:

    * Linear features  -- roads, canals, field bunds
    * Water bodies     -- ponds, tanks, percolation pits
    * Leveled areas    -- land leveling / site preparation

Detected measurements are compared against the reported/sanctioned
dimensions to quantify discrepancies.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
from loguru import logger
from scipy import ndimage
from skimage import morphology as sk_morph


class EarthworkDetector:
    """Detect and measure earthwork features from spectral change masks.

    Parameters
    ----------
    pixel_resolution : float
        Ground sampling distance in metres.  Defaults to 10.0 m
        (Sentinel-2 bands 2/3/4/8).
    min_feature_pixels : int
        Minimum connected-component size to retain.  Smaller blobs are
        discarded as noise.
    """

    def __init__(
        self,
        pixel_resolution: float = 10.0,
        min_feature_pixels: int = 5,
    ) -> None:
        self.pixel_resolution = pixel_resolution
        self.min_feature_pixels = min_feature_pixels
        self._pixel_area_sqm = pixel_resolution * pixel_resolution
        logger.info(
            "EarthworkDetector initialised  |  resolution={r}m  "
            "min_feature={mf}px",
            r=pixel_resolution,
            mf=min_feature_pixels,
        )

    # ------------------------------------------------------------------
    # Band pre-processing
    # ------------------------------------------------------------------
    def preprocess_bands(self, bands_dict: Dict[str, np.ndarray]) -> np.ndarray:
        """Normalize and stack spectral bands for downstream analysis.

        Each band is independently min-max normalised to [0, 1] (NaN-safe).
        The result is a 3-D array of shape ``(rows, cols, n_bands)``.

        Parameters
        ----------
        bands_dict : dict[str, np.ndarray]
            Mapping of band name to 2-D reflectance array.  All arrays
            must share the same spatial dimensions.

        Returns
        -------
        np.ndarray
            Stacked and normalised bands (float64).
        """
        if not bands_dict:
            raise ValueError("bands_dict must contain at least one band.")

        shapes = {v.shape for v in bands_dict.values()}
        if len(shapes) != 1:
            raise ValueError(
                f"All bands must have the same shape.  Got: {shapes}"
            )

        normalised: list[np.ndarray] = []
        for name, band in bands_dict.items():
            arr = band.astype(np.float64, copy=True)
            bmin = float(np.nanmin(arr))
            bmax = float(np.nanmax(arr))
            if bmax - bmin > 0:
                arr = (arr - bmin) / (bmax - bmin)
            else:
                arr = np.zeros_like(arr)
            # Replace NaNs with 0 for morphological processing
            arr = np.nan_to_num(arr, nan=0.0)
            normalised.append(arr)
            logger.debug(
                "  Band '{name}' normalised  |  original range [{lo:.4f}, {hi:.4f}]",
                name=name,
                lo=bmin,
                hi=bmax,
            )

        stacked = np.stack(normalised, axis=-1)
        logger.info(
            "Bands stacked  |  shape={s}  dtype={d}",
            s=stacked.shape,
            d=stacked.dtype,
        )
        return stacked

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _to_uint8(self, mask: np.ndarray) -> np.ndarray:
        """Convert a boolean or float mask to uint8 for OpenCV operations."""
        if mask.dtype == bool:
            return (mask.astype(np.uint8)) * 255
        arr = np.nan_to_num(mask, nan=0.0).astype(np.float64)
        amin, amax = arr.min(), arr.max()
        if amax - amin > 0:
            arr = (arr - amin) / (amax - amin)
        return (arr * 255).astype(np.uint8)

    def _clean_binary_mask(
        self,
        mask: np.ndarray,
        open_radius: int = 1,
        close_radius: int = 2,
    ) -> np.ndarray:
        """Apply morphological opening then closing to clean small noise
        and fill minor gaps in a binary mask.
        """
        binary = mask.astype(bool)
        selem_open = sk_morph.disk(open_radius)
        selem_close = sk_morph.disk(close_radius)
        cleaned = sk_morph.binary_opening(binary, selem_open)
        cleaned = sk_morph.binary_closing(cleaned, selem_close)
        # Remove tiny components
        labelled, n_labels = ndimage.label(cleaned)
        for lbl in range(1, n_labels + 1):
            if np.count_nonzero(labelled == lbl) < self.min_feature_pixels:
                cleaned[labelled == lbl] = False
        return cleaned

    # ------------------------------------------------------------------
    # Feature detection
    # ------------------------------------------------------------------
    def detect_linear_features(
        self,
        change_mask: np.ndarray,
        min_line_length_m: float = 50.0,
        max_line_gap_px: int = 3,
    ) -> List[Dict[str, Any]]:
        """Detect linear features (roads, canals, bunds) from a change mask.

        Uses morphological thinning followed by probabilistic Hough line
        detection.  Short spurious segments are filtered by a minimum
        physical length.

        Parameters
        ----------
        change_mask : np.ndarray
            Binary mask of changed pixels (e.g., vegetation loss or BSI gain).
        min_line_length_m : float
            Minimum line segment length in metres to retain.
        max_line_gap_px : int
            Maximum gap in pixels between line segments to merge.

        Returns
        -------
        list[dict]
            Each dict: ``{"start_px", "end_px", "length_m", "angle_deg"}``.
        """
        cleaned = self._clean_binary_mask(change_mask)
        img = self._to_uint8(cleaned)

        # Probabilistic Hough Line Transform
        min_line_px = max(1, int(min_line_length_m / self.pixel_resolution))
        lines = cv2.HoughLinesP(
            img,
            rho=1,
            theta=np.pi / 180,
            threshold=10,
            minLineLength=min_line_px,
            maxLineGap=max_line_gap_px,
        )

        features: List[Dict[str, Any]] = []
        if lines is None:
            logger.info("No linear features detected.")
            return features

        for seg in lines:
            x1, y1, x2, y2 = seg[0]
            length_px = math.hypot(x2 - x1, y2 - y1)
            length_m = length_px * self.pixel_resolution
            if length_m < min_line_length_m:
                continue
            angle = math.degrees(math.atan2(y2 - y1, x2 - x1)) % 180
            features.append({
                "start_px": (int(x1), int(y1)),
                "end_px": (int(x2), int(y2)),
                "length_m": round(length_m, 2),
                "angle_deg": round(angle, 1),
            })

        logger.info(
            "Linear features detected  |  count={n}  total_length={tl:.1f}m",
            n=len(features),
            tl=sum(f["length_m"] for f in features),
        )
        return features

    def detect_water_bodies(
        self,
        ndwi_map: np.ndarray,
        water_threshold: float = 0.0,
        min_area_sqm: float = 100.0,
    ) -> List[Dict[str, Any]]:
        """Detect water body polygons from an NDWI map.

        Applies thresholding, morphological cleaning, and contour detection
        to delineate individual ponds/tanks.

        Parameters
        ----------
        ndwi_map : np.ndarray
            NDWI index image (positive values = water).
        water_threshold : float
            NDWI value above which a pixel is classified as water.
        min_area_sqm : float
            Minimum area in sq metres to retain as a valid water body.

        Returns
        -------
        list[dict]
            Each dict: ``{"contour", "area_sqm", "centroid_px",
            "bounding_box_px", "perimeter_m"}``.
        """
        # Threshold
        water_mask = np.nan_to_num(ndwi_map, nan=-1.0) > water_threshold
        cleaned = self._clean_binary_mask(water_mask, open_radius=1, close_radius=2)
        img = self._to_uint8(cleaned)

        contours, _ = cv2.findContours(
            img, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE,
        )

        min_area_px = max(1, min_area_sqm / self._pixel_area_sqm)
        bodies: List[Dict[str, Any]] = []
        for cnt in contours:
            area_px = cv2.contourArea(cnt)
            if area_px < min_area_px:
                continue
            area_sqm = area_px * self._pixel_area_sqm
            perimeter_px = cv2.arcLength(cnt, closed=True)
            perimeter_m = perimeter_px * self.pixel_resolution

            M = cv2.moments(cnt)
            if M["m00"] != 0:
                cx = int(M["m10"] / M["m00"])
                cy = int(M["m01"] / M["m00"])
            else:
                cx, cy = 0, 0

            x, y, w, h = cv2.boundingRect(cnt)
            bodies.append({
                "contour": cnt.tolist(),
                "area_sqm": round(area_sqm, 2),
                "centroid_px": (cx, cy),
                "bounding_box_px": {"x": int(x), "y": int(y), "w": int(w), "h": int(h)},
                "perimeter_m": round(perimeter_m, 2),
            })

        logger.info(
            "Water bodies detected  |  count={n}  total_area={ta:.1f} sqm",
            n=len(bodies),
            ta=sum(b["area_sqm"] for b in bodies),
        )
        return bodies

    def detect_leveled_areas(
        self,
        bsi_change: np.ndarray,
        bsi_threshold: float = 0.10,
        min_area_sqm: float = 500.0,
    ) -> List[Dict[str, Any]]:
        """Detect land leveling activity from BSI change maps.

        Land leveling produces uniform increases in BSI over broad,
        contiguous patches -- distinct from the narrow linear signature
        of roads or canals.

        Parameters
        ----------
        bsi_change : np.ndarray
            ``after_bsi - before_bsi``.
        bsi_threshold : float
            Minimum BSI increase to flag.
        min_area_sqm : float
            Minimum patch area to keep.

        Returns
        -------
        list[dict]
            Each dict: ``{"area_sqm", "centroid_px", "bounding_box_px",
            "mean_bsi_change", "aspect_ratio"}``.
        """
        mask = np.nan_to_num(bsi_change, nan=0.0) > bsi_threshold
        cleaned = self._clean_binary_mask(mask, open_radius=2, close_radius=3)
        img = self._to_uint8(cleaned)

        contours, _ = cv2.findContours(
            img, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE,
        )

        min_area_px = max(1, min_area_sqm / self._pixel_area_sqm)
        patches: List[Dict[str, Any]] = []
        for cnt in contours:
            area_px = cv2.contourArea(cnt)
            if area_px < min_area_px:
                continue

            area_sqm = area_px * self._pixel_area_sqm
            x, y, w, h = cv2.boundingRect(cnt)
            aspect_ratio = round(max(w, h) / max(min(w, h), 1), 2)

            # Filter out elongated features (those are likely roads/canals)
            if aspect_ratio > 6.0:
                continue

            M = cv2.moments(cnt)
            cx = int(M["m10"] / M["m00"]) if M["m00"] != 0 else 0
            cy = int(M["m01"] / M["m00"]) if M["m00"] != 0 else 0

            # Mean BSI change within the contour
            contour_mask = np.zeros(bsi_change.shape[:2], dtype=np.uint8)
            cv2.drawContours(contour_mask, [cnt], -1, 255, thickness=cv2.FILLED)
            mean_bsi = float(
                np.nanmean(bsi_change[contour_mask == 255])
            )

            patches.append({
                "area_sqm": round(area_sqm, 2),
                "centroid_px": (cx, cy),
                "bounding_box_px": {"x": int(x), "y": int(y), "w": int(w), "h": int(h)},
                "mean_bsi_change": round(mean_bsi, 4),
                "aspect_ratio": aspect_ratio,
            })

        logger.info(
            "Leveled areas detected  |  count={n}  total_area={ta:.1f} sqm",
            n=len(patches),
            ta=sum(p["area_sqm"] for p in patches),
        )
        return patches

    # ------------------------------------------------------------------
    # Measurement
    # ------------------------------------------------------------------
    def measure_road_length(
        self,
        road_mask: np.ndarray,
        pixel_resolution: Optional[float] = None,
    ) -> float:
        """Measure total road length by skeletonising the mask.

        Parameters
        ----------
        road_mask : np.ndarray
            Binary mask of detected road pixels.
        pixel_resolution : float | None
            Override GSD (metres).  Uses instance default if *None*.

        Returns
        -------
        float
            Total road centreline length in metres.
        """
        res = pixel_resolution or self.pixel_resolution
        cleaned = self._clean_binary_mask(road_mask)
        skeleton = sk_morph.skeletonize(cleaned)

        # Count skeleton pixels -- each pixel traversal is ~1 pixel apart.
        # For a more accurate path length, use a distance-weighted count.
        skeleton_pixels = int(np.count_nonzero(skeleton))

        # Approximate path length: straight segments = res, diagonal = res*sqrt(2).
        # We use the average weighting factor of ~1.12 for 8-connected skeletons.
        length_m = skeleton_pixels * res * 1.12
        logger.info(
            "Road length measured  |  skeleton_px={sp}  length={l:.1f}m",
            sp=skeleton_pixels,
            l=length_m,
        )
        return round(length_m, 2)

    def measure_pond_area(
        self,
        pond_mask: np.ndarray,
        pixel_resolution: Optional[float] = None,
    ) -> float:
        """Calculate water body area from a binary pond mask.

        Parameters
        ----------
        pond_mask : np.ndarray   Binary mask of detected pond pixels.
        pixel_resolution : float | None   Override GSD in metres.

        Returns
        -------
        float   Total pond area in square metres.
        """
        res = pixel_resolution or self.pixel_resolution
        cleaned = self._clean_binary_mask(pond_mask)
        n_pixels = int(np.count_nonzero(cleaned))
        area_sqm = n_pixels * (res * res)
        logger.info(
            "Pond area measured  |  pixels={p}  area={a:.1f} sqm",
            p=n_pixels,
            a=area_sqm,
        )
        return round(area_sqm, 2)

    def measure_canal_dimensions(
        self,
        canal_mask: np.ndarray,
        pixel_resolution: Optional[float] = None,
    ) -> Dict[str, float]:
        """Estimate canal length and average width.

        Length is computed via skeletonisation (centreline pixel count).
        Width is estimated as ``area / length``.

        Parameters
        ----------
        canal_mask : np.ndarray      Binary mask of detected canal pixels.
        pixel_resolution : float | None   Override GSD in metres.

        Returns
        -------
        dict   ``{"length_m", "avg_width_m", "area_sqm"}``.
        """
        res = pixel_resolution or self.pixel_resolution
        cleaned = self._clean_binary_mask(canal_mask)
        total_pixels = int(np.count_nonzero(cleaned))
        area_sqm = total_pixels * (res * res)

        skeleton = sk_morph.skeletonize(cleaned)
        skel_px = int(np.count_nonzero(skeleton))
        length_m = skel_px * res * 1.12 if skel_px > 0 else 0.0
        avg_width_m = area_sqm / length_m if length_m > 0 else 0.0

        dims = {
            "length_m": round(length_m, 2),
            "avg_width_m": round(avg_width_m, 2),
            "area_sqm": round(area_sqm, 2),
        }
        logger.info(
            "Canal dimensions  |  length={l:.1f}m  width={w:.1f}m  "
            "area={a:.1f} sqm",
            l=dims["length_m"],
            w=dims["avg_width_m"],
            a=dims["area_sqm"],
        )
        return dims

    # ------------------------------------------------------------------
    # Discrepancy analysis
    # ------------------------------------------------------------------
    def compare_with_reported(
        self,
        detected_measurements: Dict[str, float],
        reported_measurements: Dict[str, float],
    ) -> Dict[str, Any]:
        """Compare satellite-detected vs. officially reported measurements.

        Parameters
        ----------
        detected_measurements : dict
            Keys are measurement names (e.g. ``"road_length_m"``,
            ``"pond_area_sqm"``), values are floats from detection.
        reported_measurements : dict
            Same keys with values from the MIS / muster roll.

        Returns
        -------
        dict
            ``"discrepancies"``  : list of per-metric dicts with fields
                ``metric``, ``detected``, ``reported``, ``difference``,
                ``pct_deviation``, ``flag``.
            ``"overall_flag"``   : bool -- True if any metric deviates by
                more than 20%.
            ``"summary"``        : str  -- Human-readable summary.
        """
        discrepancies: List[Dict[str, Any]] = []
        any_flagged = False

        for metric in sorted(
            set(detected_measurements.keys()) | set(reported_measurements.keys())
        ):
            det = detected_measurements.get(metric)
            rep = reported_measurements.get(metric)
            if det is None or rep is None:
                discrepancies.append({
                    "metric": metric,
                    "detected": det,
                    "reported": rep,
                    "difference": None,
                    "pct_deviation": None,
                    "flag": "MISSING_DATA",
                })
                continue

            diff = det - rep
            pct_dev = (
                100.0 * abs(diff) / abs(rep) if rep != 0 else
                (100.0 if det != 0 else 0.0)
            )
            flag = "OK"
            if pct_dev > 50:
                flag = "CRITICAL"
                any_flagged = True
            elif pct_dev > 20:
                flag = "WARNING"
                any_flagged = True

            discrepancies.append({
                "metric": metric,
                "detected": round(det, 2),
                "reported": round(rep, 2),
                "difference": round(diff, 2),
                "pct_deviation": round(pct_dev, 2),
                "flag": flag,
            })

        summary_parts: list[str] = []
        for d in discrepancies:
            if d["flag"] in ("CRITICAL", "WARNING"):
                summary_parts.append(
                    f"{d['metric']}: detected {d['detected']} vs reported "
                    f"{d['reported']} ({d['pct_deviation']:.1f}% deviation) "
                    f"[{d['flag']}]"
                )

        summary = (
            "; ".join(summary_parts) if summary_parts
            else "All measurements within acceptable tolerance."
        )

        result: Dict[str, Any] = {
            "discrepancies": discrepancies,
            "overall_flag": any_flagged,
            "summary": summary,
        }
        logger.info(
            "Discrepancy analysis  |  metrics={n}  flagged={f}",
            n=len(discrepancies),
            f=any_flagged,
        )
        return result

    # ------------------------------------------------------------------
    # Visualisation overlay
    # ------------------------------------------------------------------
    def generate_verification_overlay(
        self,
        satellite_rgb: np.ndarray,
        detection_mask: np.ndarray,
        measurements: Dict[str, Any],
        alpha: float = 0.45,
    ) -> np.ndarray:
        """Create an annotated RGB image overlaying detected features.

        Parameters
        ----------
        satellite_rgb : np.ndarray
            3-channel (H, W, 3) uint8 RGB image of the site.
        detection_mask : np.ndarray
            Boolean or integer mask of detected features (H, W).
        measurements : dict
            Measurement values to annotate on the image.
        alpha : float
            Overlay opacity.

        Returns
        -------
        np.ndarray
            Annotated uint8 RGB image.
        """
        if satellite_rgb.ndim != 3 or satellite_rgb.shape[2] != 3:
            raise ValueError("satellite_rgb must be an (H, W, 3) array.")
        if detection_mask.shape[:2] != satellite_rgb.shape[:2]:
            raise ValueError("detection_mask must match the spatial dims of the RGB image.")

        overlay = satellite_rgb.copy()
        if overlay.dtype != np.uint8:
            # Normalise to uint8
            amin, amax = overlay.min(), overlay.max()
            if amax > amin:
                overlay = ((overlay - amin) / (amax - amin) * 255).astype(np.uint8)
            else:
                overlay = np.zeros_like(overlay, dtype=np.uint8)

        # Colour-code detection overlay
        colour_layer = np.zeros_like(overlay)
        binary = detection_mask.astype(bool)
        colour_layer[binary] = [0, 255, 120]  # green highlight for detected areas

        cv2.addWeighted(
            colour_layer, alpha, overlay, 1 - alpha, 0, overlay,
        )

        # Draw contours in yellow for clarity
        mask_u8 = self._to_uint8(binary)
        contours, _ = cv2.findContours(
            mask_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE,
        )
        cv2.drawContours(overlay, contours, -1, (255, 255, 0), 1)

        # Annotate measurements as text on the image
        y_offset = 20
        for key, value in measurements.items():
            if isinstance(value, (int, float)):
                text = f"{key}: {value}"
            else:
                text = f"{key}: {value}"
            cv2.putText(
                overlay,
                text,
                (10, y_offset),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.4,
                (255, 255, 255),
                1,
                cv2.LINE_AA,
            )
            y_offset += 18

        logger.info(
            "Verification overlay generated  |  shape={s}  annotations={n}",
            s=overlay.shape,
            n=len(measurements),
        )
        return overlay
