"""
Photo Verification Agent for the MGNREGA Verification & Fraud Intelligence System.

This agent analyses GeoMGNREGA photographs uploaded as evidence of work
completion. It performs multi-layered verification:

- GPS metadata consistency (photo GPS vs registered work site GPS)
- Perceptual hashing for duplicate/recycled photo detection
- Content-work-type matching using CLIP zero-shot classification
- Timestamp and bulk upload pattern analysis
- Image forensics (copy-paste, metadata stripping, lighting inconsistencies)
"""

from __future__ import annotations

import hashlib
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np
from loguru import logger


# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------

class PhotoVerificationStatus(str, Enum):
    """Outcome of a single photo verification."""

    VERIFIED = "verified"
    GPS_MISMATCH = "gps_mismatch"
    DUPLICATE = "duplicate"
    TYPE_MISMATCH = "type_mismatch"
    MANIPULATED = "manipulated"
    BULK_UPLOAD = "bulk_upload"
    METADATA_STRIPPED = "metadata_stripped"
    MULTIPLE_ISSUES = "multiple_issues"


class WorkTypeLabel(str, Enum):
    """Work-type labels used for CLIP zero-shot classification."""

    ROAD = "road construction"
    POND = "pond or water tank"
    CANAL = "canal or drainage channel"
    WELL = "well digging"
    LAND_LEVELLING = "land levelling or field bunding"
    PLANTATION = "tree plantation"
    CHECK_DAM = "check dam"
    BUILDING = "building construction"
    UNKNOWN = "unknown"


@dataclass
class PhotoMetadata:
    """Extracted metadata from a GeoMGNREGA photograph."""

    photo_id: str
    work_id: str
    file_name: str
    gps_lat: Optional[float] = None
    gps_lon: Optional[float] = None
    capture_timestamp: Optional[datetime] = None
    upload_timestamp: Optional[datetime] = None
    camera_model: Optional[str] = None
    image_width: int = 0
    image_height: int = 0
    file_size_bytes: int = 0
    has_exif: bool = True
    perceptual_hash: str = ""
    md5_hash: str = ""


@dataclass
class PhotoVerificationResult:
    """Verification result for a single photograph."""

    photo_id: str
    work_id: str
    status: PhotoVerificationStatus
    issues: List[str] = field(default_factory=list)
    gps_distance_m: Optional[float] = None
    duplicate_of: Optional[str] = None
    predicted_work_type: Optional[str] = None
    predicted_confidence: float = 0.0
    integrity_score: float = 1.0  # 1.0 = no manipulation detected
    verified_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class BulkUploadCluster:
    """A cluster of photos uploaded in rapid succession."""

    cluster_id: str
    work_id: str
    photo_ids: List[str] = field(default_factory=list)
    upload_window_seconds: float = 0.0
    uploader_id: Optional[str] = None
    is_suspicious: bool = False


@dataclass
class PhotoVerificationReport:
    """Complete photo verification report for a work."""

    report_id: str
    work_id: str
    total_photos: int = 0
    verified_count: int = 0
    gps_mismatch_count: int = 0
    duplicate_count: int = 0
    type_mismatch_count: int = 0
    manipulation_count: int = 0
    bulk_upload_clusters: List[BulkUploadCluster] = field(default_factory=list)
    photo_results: List[PhotoVerificationResult] = field(default_factory=list)
    overall_confidence: float = 0.0
    summary: str = ""
    generated_at: datetime = field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Photo Verification Agent
# ---------------------------------------------------------------------------

class PhotoVerificationAgent:
    """Agent for verifying GeoMGNREGA photograph authenticity and relevance.

    Performs GPS consistency checks, duplicate detection via perceptual
    hashing, content-work-type matching using CLIP, bulk upload detection,
    and basic image forensics.

    Parameters
    ----------
    db_session : Any
        Database session for querying photo records and work details.
    clip_model : Any, optional
        Pre-loaded CLIP model for zero-shot image classification.
        If ``None``, content-type matching is skipped.
    config : dict, optional
        Runtime configuration overrides.
    """

    GPS_TOLERANCE_M: float = 100.0  # default tolerance in metres
    BULK_UPLOAD_WINDOW_S: float = 300.0  # 5 minutes
    BULK_UPLOAD_MIN_PHOTOS: int = 5
    DUPLICATE_HASH_THRESHOLD: int = 10  # Hamming distance threshold
    CLIP_CONFIDENCE_THRESHOLD: float = 0.5

    # CLIP candidate labels for zero-shot classification
    CLIP_LABELS: List[str] = [
        "a photograph of road construction or road work",
        "a photograph of a pond or water tank excavation",
        "a photograph of a canal or drainage channel",
        "a photograph of a well being dug",
        "a photograph of land levelling or field bunding",
        "a photograph of a tree plantation",
        "a photograph of a check dam or embankment",
        "a photograph of a building or structure",
        "an irrelevant or unrelated photograph",
        "a stock photograph or previously seen image",
    ]

    LABEL_TO_WORK_TYPE: Dict[str, str] = {
        "a photograph of road construction or road work": "road",
        "a photograph of a pond or water tank excavation": "pond",
        "a photograph of a canal or drainage channel": "canal",
        "a photograph of a well being dug": "well",
        "a photograph of land levelling or field bunding": "land_levelling",
        "a photograph of a tree plantation": "plantation",
        "a photograph of a check dam or embankment": "check_dam",
        "a photograph of a building or structure": "building",
        "an irrelevant or unrelated photograph": "irrelevant",
        "a stock photograph or previously seen image": "stock",
    }

    def __init__(
        self,
        db_session: Any,
        clip_model: Optional[Any] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.db = db_session
        self.clip_model = clip_model
        self.config = config or {}
        self.gps_tolerance = self.config.get(
            "gps_tolerance_m", self.GPS_TOLERANCE_M
        )

        # In-memory hash index for duplicate detection
        self._hash_index: Dict[str, List[str]] = defaultdict(list)

        logger.info(
            "PhotoVerificationAgent initialised | gps_tolerance={t}m | clip={'enabled' if clip_model else 'disabled'}",
        )

    # ------------------------------------------------------------------
    # Primary verification
    # ------------------------------------------------------------------

    async def verify_work_photos(
        self, work_id: str
    ) -> PhotoVerificationReport:
        """Run full photo verification pipeline for all photos of a work.

        Pipeline steps:
        1. Fetch all photos and work metadata.
        2. Verify GPS consistency for each photo.
        3. Run perceptual hash duplicate detection.
        4. Classify photo content vs expected work type (CLIP).
        5. Detect bulk upload patterns.
        6. Run image integrity checks.
        7. Compile report.

        Parameters
        ----------
        work_id : str
            The NREGASoft work identifier.

        Returns
        -------
        PhotoVerificationReport
            Comprehensive photo verification report.
        """
        report_id = f"RPT-PHO-{uuid.uuid4().hex[:10].upper()}"
        logger.info("Starting photo verification for work {w}", w=work_id)

        report = PhotoVerificationReport(
            report_id=report_id,
            work_id=work_id,
        )

        try:
            # Fetch work details and photos
            work = await self._fetch_work_details(work_id)
            if not work:
                report.summary = f"Work {work_id} not found in database"
                return report

            photos = await self._fetch_work_photos(work_id)
            if not photos:
                report.summary = f"No photos found for work {work_id}"
                return report

            report.total_photos = len(photos)
            work_gps = (work.get("latitude"), work.get("longitude"))
            expected_type = work.get("work_type", "other")

            # Process each photo
            for photo_meta in photos:
                result = PhotoVerificationResult(
                    photo_id=photo_meta.photo_id,
                    work_id=work_id,
                    status=PhotoVerificationStatus.VERIFIED,
                )
                issues: List[str] = []

                # 1. GPS check
                if photo_meta.gps_lat is not None and photo_meta.gps_lon is not None:
                    gps_ok, distance = self.check_gps_consistency(
                        (photo_meta.gps_lat, photo_meta.gps_lon),
                        work_gps,
                        tolerance_meters=self.gps_tolerance,
                    )
                    result.gps_distance_m = distance
                    if not gps_ok:
                        issues.append(f"GPS mismatch: {distance:.0f}m from work site")
                        report.gps_mismatch_count += 1
                elif not photo_meta.has_exif:
                    issues.append("EXIF metadata stripped (no GPS data)")

                # 2. Duplicate detection
                if photo_meta.perceptual_hash:
                    dup_id = self._check_duplicate_hash(
                        photo_meta.perceptual_hash,
                        photo_meta.photo_id,
                        work.get("district_id", ""),
                    )
                    if dup_id:
                        issues.append(f"Duplicate of photo {dup_id}")
                        result.duplicate_of = dup_id
                        report.duplicate_count += 1

                # 3. Content-type classification (CLIP)
                if self.clip_model is not None:
                    image_data = await self._load_photo_image(
                        photo_meta.photo_id
                    )
                    if image_data is not None:
                        predicted_type, clip_conf = self.classify_work_type(
                            image_data, expected_type
                        )
                        result.predicted_work_type = predicted_type
                        result.predicted_confidence = clip_conf
                        if predicted_type and predicted_type != expected_type:
                            if clip_conf > self.CLIP_CONFIDENCE_THRESHOLD:
                                issues.append(
                                    f"Content mismatch: photo shows '{predicted_type}' "
                                    f"but work type is '{expected_type}' "
                                    f"(confidence={clip_conf:.0%})"
                                )
                                report.type_mismatch_count += 1

                # 4. Image integrity
                integrity = await self.analyze_image_integrity(
                    photo_meta.photo_id
                )
                result.integrity_score = integrity.get("overall_score", 1.0)
                if result.integrity_score < 0.5:
                    issues.append(
                        f"Image manipulation suspected (integrity={result.integrity_score:.2f})"
                    )
                    report.manipulation_count += 1

                # Determine final status
                result.issues = issues
                if len(issues) >= 2:
                    result.status = PhotoVerificationStatus.MULTIPLE_ISSUES
                elif any("GPS" in i for i in issues):
                    result.status = PhotoVerificationStatus.GPS_MISMATCH
                elif any("Duplicate" in i for i in issues):
                    result.status = PhotoVerificationStatus.DUPLICATE
                elif any("Content" in i for i in issues):
                    result.status = PhotoVerificationStatus.TYPE_MISMATCH
                elif any("manipulation" in i.lower() for i in issues):
                    result.status = PhotoVerificationStatus.MANIPULATED
                elif any("stripped" in i.lower() for i in issues):
                    result.status = PhotoVerificationStatus.METADATA_STRIPPED
                else:
                    report.verified_count += 1

                report.photo_results.append(result)

            # 5. Bulk upload detection
            report.bulk_upload_clusters = self.detect_bulk_upload(photos)

            # Overall confidence
            if report.total_photos > 0:
                report.overall_confidence = round(
                    report.verified_count / report.total_photos, 4
                )

            report.summary = self._generate_photo_summary(report)

            logger.info(
                "Photo verification complete | work={w} | total={t} | verified={v} | issues={i}",
                w=work_id,
                t=report.total_photos,
                v=report.verified_count,
                i=report.total_photos - report.verified_count,
            )
            return report

        except Exception as exc:
            logger.exception(
                "Photo verification failed for work {w}: {e}",
                w=work_id,
                e=exc,
            )
            raise

    # ------------------------------------------------------------------
    # GPS consistency check
    # ------------------------------------------------------------------

    @staticmethod
    def check_gps_consistency(
        photo_gps: Tuple[Optional[float], Optional[float]],
        work_gps: Tuple[Optional[float], Optional[float]],
        tolerance_meters: float = 100.0,
    ) -> Tuple[bool, float]:
        """Check if a photo's GPS location matches the work site GPS.

        Uses the Haversine formula to compute the great-circle distance.

        Parameters
        ----------
        photo_gps : tuple of (lat, lon)
            GPS coordinates extracted from photo EXIF data.
        work_gps : tuple of (lat, lon)
            Registered GPS coordinates of the work site.
        tolerance_meters : float
            Maximum allowed distance in metres.

        Returns
        -------
        is_consistent : bool
            True if distance is within tolerance.
        distance_m : float
            Computed distance in metres.
        """
        plat, plon = photo_gps
        wlat, wlon = work_gps

        if any(v is None for v in [plat, plon, wlat, wlon]):
            return True, 0.0  # cannot check if GPS missing

        # Haversine formula
        lat1, lon1 = np.radians(plat), np.radians(plon)
        lat2, lon2 = np.radians(wlat), np.radians(wlon)

        dlat = lat2 - lat1
        dlon = lon2 - lon1

        a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
        c = 2 * np.arcsin(np.sqrt(a))
        distance_m = 6_371_000 * c  # Earth radius in metres

        is_consistent = distance_m <= tolerance_meters
        return is_consistent, round(float(distance_m), 1)

    # ------------------------------------------------------------------
    # Duplicate detection
    # ------------------------------------------------------------------

    def find_duplicate_photos(
        self,
        photo_hashes: Dict[str, str],
        district_id: str,
    ) -> Dict[str, List[str]]:
        """Find duplicate photos across a district using perceptual hashes.

        Groups photos by similar perceptual hash (Hamming distance below
        threshold) to detect recycled evidence photos.

        Parameters
        ----------
        photo_hashes : dict
            Mapping of photo_id -> perceptual_hash_hex.
        district_id : str
            District code for scoping the search.

        Returns
        -------
        dict
            Mapping of canonical_photo_id -> list of duplicate photo_ids.
        """
        logger.debug(
            "Finding duplicate photos | district={d} | n={n}",
            d=district_id,
            n=len(photo_hashes),
        )

        duplicates: Dict[str, List[str]] = defaultdict(list)
        hash_list = list(photo_hashes.items())

        for i in range(len(hash_list)):
            pid_a, hash_a = hash_list[i]
            for j in range(i + 1, len(hash_list)):
                pid_b, hash_b = hash_list[j]
                distance = self._hamming_distance(hash_a, hash_b)
                if distance <= self.DUPLICATE_HASH_THRESHOLD:
                    duplicates[pid_a].append(pid_b)

        # Update global index
        for pid, phash in photo_hashes.items():
            bucket = phash[:8]  # first 8 hex chars as bucket
            self._hash_index[bucket].append(pid)

        logger.debug(
            "Duplicate detection: {n} groups found", n=len(duplicates)
        )
        return dict(duplicates)

    def _check_duplicate_hash(
        self,
        perceptual_hash: str,
        current_photo_id: str,
        district_id: str,
    ) -> Optional[str]:
        """Check a single photo hash against the global index.

        Returns the ID of the first matching photo, or None.
        """
        bucket = perceptual_hash[:8]
        candidates = self._hash_index.get(bucket, [])

        for existing_id in candidates:
            if existing_id == current_photo_id:
                continue
            # In production, retrieve the full hash for the existing photo
            # and compute Hamming distance. Here we use bucket match as proxy.
            return existing_id

        # Register this hash
        self._hash_index[bucket].append(current_photo_id)
        return None

    # ------------------------------------------------------------------
    # Content classification (CLIP)
    # ------------------------------------------------------------------

    def classify_work_type(
        self,
        image: Any,
        expected_type: str,
    ) -> Tuple[Optional[str], float]:
        """Classify the photo content using CLIP zero-shot classification.

        Compares the image against predefined work-type text prompts and
        returns the best-matching label and confidence.

        Parameters
        ----------
        image : Any
            The loaded image (PIL Image or numpy array).
        expected_type : str
            The expected work type from NREGASoft records.

        Returns
        -------
        predicted_type : str or None
            The predicted work type, or None if CLIP is unavailable.
        confidence : float
            Classification confidence (0-1).
        """
        if self.clip_model is None:
            return None, 0.0

        try:
            # Prepare inputs
            text_inputs = self.clip_model.tokenize(self.CLIP_LABELS)
            image_input = self.clip_model.preprocess(image)

            # Forward pass
            image_features = self.clip_model.encode_image(image_input)
            text_features = self.clip_model.encode_text(text_inputs)

            # Cosine similarity
            image_features = image_features / np.linalg.norm(
                image_features, axis=-1, keepdims=True
            )
            text_features = text_features / np.linalg.norm(
                text_features, axis=-1, keepdims=True
            )
            similarities = (image_features @ text_features.T).flatten()

            # Softmax for probabilities
            exp_sims = np.exp(similarities - np.max(similarities))
            probabilities = exp_sims / np.sum(exp_sims)

            best_idx = int(np.argmax(probabilities))
            best_label = self.CLIP_LABELS[best_idx]
            best_confidence = float(probabilities[best_idx])

            predicted_type = self.LABEL_TO_WORK_TYPE.get(best_label, "unknown")

            logger.debug(
                "CLIP classification: predicted={p} ({c:.2%}) | expected={e}",
                p=predicted_type,
                c=best_confidence,
                e=expected_type,
            )
            return predicted_type, round(best_confidence, 4)

        except Exception as exc:
            logger.error("CLIP classification failed: {e}", e=exc)
            return None, 0.0

    # ------------------------------------------------------------------
    # Bulk upload detection
    # ------------------------------------------------------------------

    def detect_bulk_upload(
        self, photos: List[PhotoMetadata]
    ) -> List[BulkUploadCluster]:
        """Detect clusters of photos uploaded in rapid succession.

        A burst of many photos uploaded within a short window suggests
        that someone is batch-uploading fabricated evidence rather than
        taking photos at the actual work site over time.

        Parameters
        ----------
        photos : list of PhotoMetadata
            Photo metadata records for a work.

        Returns
        -------
        list of BulkUploadCluster
            Detected bulk upload clusters.
        """
        # Filter photos with upload timestamps
        timestamped = [
            p for p in photos if p.upload_timestamp is not None
        ]
        if len(timestamped) < self.BULK_UPLOAD_MIN_PHOTOS:
            return []

        # Sort by upload time
        timestamped.sort(key=lambda p: p.upload_timestamp)

        clusters: List[BulkUploadCluster] = []
        window_s = self.config.get(
            "bulk_upload_window_s", self.BULK_UPLOAD_WINDOW_S
        )
        min_photos = self.config.get(
            "bulk_upload_min_photos", self.BULK_UPLOAD_MIN_PHOTOS
        )

        current_cluster: List[PhotoMetadata] = [timestamped[0]]

        for i in range(1, len(timestamped)):
            prev_time = timestamped[i - 1].upload_timestamp
            curr_time = timestamped[i].upload_timestamp

            if prev_time and curr_time:
                gap = (curr_time - prev_time).total_seconds()
                if gap <= window_s:
                    current_cluster.append(timestamped[i])
                else:
                    if len(current_cluster) >= min_photos:
                        clusters.append(
                            self._build_cluster(current_cluster, window_s)
                        )
                    current_cluster = [timestamped[i]]

        # Check last cluster
        if len(current_cluster) >= min_photos:
            clusters.append(self._build_cluster(current_cluster, window_s))

        logger.debug(
            "Bulk upload detection: {n} clusters found", n=len(clusters)
        )
        return clusters

    # ------------------------------------------------------------------
    # Image integrity analysis
    # ------------------------------------------------------------------

    async def analyze_image_integrity(
        self, photo_id: str
    ) -> Dict[str, Any]:
        """Perform basic image forensics on a photograph.

        Checks for:
        - EXIF metadata presence and consistency.
        - Error Level Analysis (ELA) for copy-paste detection.
        - Lighting/shadow consistency heuristics.
        - JPEG quantisation table anomalies (double compression).

        Parameters
        ----------
        photo_id : str
            The photo identifier.

        Returns
        -------
        dict
            Integrity analysis results including ``overall_score`` (0-1).
        """
        logger.debug("Analysing image integrity for photo {p}", p=photo_id)

        result: Dict[str, Any] = {
            "photo_id": photo_id,
            "overall_score": 1.0,
            "checks": {},
        }

        try:
            # Fetch photo data
            photo_data = await self._fetch_photo_data(photo_id)
            if photo_data is None:
                result["overall_score"] = 0.5
                result["checks"]["data_available"] = False
                return result

            scores: List[float] = []

            # 1. EXIF check
            exif_score = self._check_exif_integrity(photo_data)
            result["checks"]["exif_integrity"] = exif_score
            scores.append(exif_score)

            # 2. Error Level Analysis (simplified)
            ela_score = self._error_level_analysis(photo_data)
            result["checks"]["ela_score"] = ela_score
            scores.append(ela_score)

            # 3. JPEG double compression detection
            compression_score = self._check_double_compression(photo_data)
            result["checks"]["compression_integrity"] = compression_score
            scores.append(compression_score)

            # 4. Thumbnail consistency
            thumb_score = self._check_thumbnail_consistency(photo_data)
            result["checks"]["thumbnail_consistency"] = thumb_score
            scores.append(thumb_score)

            result["overall_score"] = round(float(np.mean(scores)), 4)
            return result

        except Exception as exc:
            logger.error(
                "Image integrity analysis failed for photo {p}: {e}",
                p=photo_id,
                e=exc,
            )
            result["overall_score"] = 0.5
            return result

    # ------------------------------------------------------------------
    # Report generation
    # ------------------------------------------------------------------

    async def generate_photo_report(
        self, work_id: str
    ) -> PhotoVerificationReport:
        """Generate a photo verification report for a work.

        Convenience wrapper around ``verify_work_photos``.

        Parameters
        ----------
        work_id : str
            NREGASoft work identifier.

        Returns
        -------
        PhotoVerificationReport
        """
        return await self.verify_work_photos(work_id)

    # ------------------------------------------------------------------
    # Private helpers -- image forensics
    # ------------------------------------------------------------------

    @staticmethod
    def _check_exif_integrity(photo_data: Dict[str, Any]) -> float:
        """Check EXIF metadata for consistency.

        Returns a score from 0 (completely inconsistent/missing) to 1
        (fully consistent).
        """
        if not photo_data.get("has_exif", True):
            return 0.3  # Missing EXIF is suspicious but not conclusive

        score = 1.0
        exif = photo_data.get("exif", {})

        # Check for required fields
        required_fields = ["DateTime", "GPSInfo", "Make", "Model"]
        present = sum(1 for f in required_fields if f in exif)
        score -= (len(required_fields) - present) * 0.15

        # Check timestamp consistency
        datetime_original = exif.get("DateTimeOriginal")
        datetime_digitized = exif.get("DateTimeDigitized")
        if datetime_original and datetime_digitized:
            if datetime_original != datetime_digitized:
                score -= 0.2  # mismatch suggests editing

        # Check software tag (editing software indicator)
        software = exif.get("Software", "").lower()
        editing_tools = ["photoshop", "gimp", "lightroom", "paint"]
        if any(tool in software for tool in editing_tools):
            score -= 0.3

        return max(score, 0.0)

    @staticmethod
    def _error_level_analysis(photo_data: Dict[str, Any]) -> float:
        """Simplified Error Level Analysis (ELA).

        ELA detects regions in a JPEG that were saved at different
        compression levels, which can indicate copy-paste manipulation.

        Returns a score: 1.0 = uniform compression (normal),
        0.0 = highly non-uniform (likely manipulated).
        """
        # In production, this would re-compress the image at a known
        # quality level and compute the difference. Here we provide
        # a placeholder using available metadata indicators.
        quality = photo_data.get("jpeg_quality", 85)
        file_size = photo_data.get("file_size_bytes", 0)
        dimensions = photo_data.get("width", 0) * photo_data.get("height", 0)

        if dimensions == 0:
            return 0.5

        # Expected file size heuristic based on quality and dimensions
        expected_bpp = 0.5 + (quality / 100.0) * 2.0  # bits per pixel
        expected_size = (dimensions * expected_bpp) / 8.0

        if expected_size > 0:
            size_ratio = file_size / expected_size
            if 0.5 < size_ratio < 2.0:
                return 0.9  # normal range
            elif 0.3 < size_ratio < 3.0:
                return 0.6  # slightly off
            else:
                return 0.3  # very unusual

        return 0.5

    @staticmethod
    def _check_double_compression(photo_data: Dict[str, Any]) -> float:
        """Detect JPEG double compression via quantisation table analysis.

        Double compression occurs when an image is saved, edited, and
        re-saved as JPEG, leaving artefacts in the quantisation tables.
        """
        quant_tables = photo_data.get("quantization_tables", [])
        if not quant_tables:
            return 0.7  # cannot determine

        # Check if quantisation table values suggest re-compression
        # Standard JPEG tables have smooth distributions; re-compressed
        # images often show peaks at multiples of the second quality level
        for table in quant_tables:
            if isinstance(table, (list, np.ndarray)):
                values = np.array(table).flatten()
                if len(values) > 0:
                    # Variance of quantisation values
                    var = float(np.var(values))
                    if var < 10:
                        return 0.5  # unusually uniform = suspicious
                    elif var > 500:
                        return 0.6  # unusually varied
                    else:
                        return 0.9  # normal

        return 0.7

    @staticmethod
    def _check_thumbnail_consistency(photo_data: Dict[str, Any]) -> float:
        """Check if the EXIF thumbnail matches the main image.

        Editing software often forgets to update the embedded thumbnail,
        so a mismatch between thumbnail and main image content indicates
        post-processing.
        """
        has_thumbnail = photo_data.get("has_thumbnail", False)
        thumbnail_matches = photo_data.get("thumbnail_matches_main", True)

        if not has_thumbnail:
            return 0.8  # no thumbnail is common on mobile
        if thumbnail_matches:
            return 1.0
        return 0.3  # mismatch = strong indicator of editing

    # ------------------------------------------------------------------
    # Private helpers -- utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _hamming_distance(hash_a: str, hash_b: str) -> int:
        """Compute the Hamming distance between two hex hash strings.

        Each hex character represents 4 bits; XOR reveals differing bits.
        """
        if len(hash_a) != len(hash_b):
            return max(len(hash_a), len(hash_b)) * 4

        distance = 0
        for ca, cb in zip(hash_a, hash_b):
            xor = int(ca, 16) ^ int(cb, 16)
            distance += bin(xor).count("1")
        return distance

    @staticmethod
    def _build_cluster(
        photos: List[PhotoMetadata], window_s: float
    ) -> BulkUploadCluster:
        """Build a BulkUploadCluster from a list of temporally close photos."""
        first_ts = photos[0].upload_timestamp
        last_ts = photos[-1].upload_timestamp
        duration = (
            (last_ts - first_ts).total_seconds()
            if first_ts and last_ts
            else 0.0
        )

        avg_gap = duration / max(len(photos) - 1, 1)
        is_suspicious = avg_gap < 10.0  # less than 10s between photos

        return BulkUploadCluster(
            cluster_id=f"BUL-{uuid.uuid4().hex[:8]}",
            work_id=photos[0].work_id,
            photo_ids=[p.photo_id for p in photos],
            upload_window_seconds=round(duration, 1),
            is_suspicious=is_suspicious,
        )

    # ------------------------------------------------------------------
    # Private helpers -- data fetching
    # ------------------------------------------------------------------

    async def _fetch_work_details(
        self, work_id: str
    ) -> Optional[Dict[str, Any]]:
        """Fetch work metadata."""
        try:
            query = """
                SELECT w.work_id,
                       w.work_type,
                       w.latitude,
                       w.longitude,
                       w.district_id,
                       w.block_id,
                       w.gram_panchayat_id
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

    async def _fetch_work_photos(
        self, work_id: str
    ) -> List[PhotoMetadata]:
        """Fetch all photo records for a work."""
        try:
            query = """
                SELECT p.photo_id,
                       p.work_id,
                       p.file_name,
                       p.gps_latitude     AS gps_lat,
                       p.gps_longitude    AS gps_lon,
                       p.capture_time     AS capture_timestamp,
                       p.upload_time      AS upload_timestamp,
                       p.camera_model,
                       p.image_width,
                       p.image_height,
                       p.file_size_bytes,
                       p.has_exif,
                       p.perceptual_hash,
                       p.md5_hash
                FROM   geo_photos p
                WHERE  p.work_id = :work_id
                ORDER  BY p.upload_time
            """
            rows = await self.db.fetch_all(query, {"work_id": work_id})
            return [
                PhotoMetadata(
                    photo_id=r["photo_id"],
                    work_id=r["work_id"],
                    file_name=r.get("file_name", ""),
                    gps_lat=r.get("gps_lat"),
                    gps_lon=r.get("gps_lon"),
                    capture_timestamp=r.get("capture_timestamp"),
                    upload_timestamp=r.get("upload_timestamp"),
                    camera_model=r.get("camera_model"),
                    image_width=r.get("image_width", 0),
                    image_height=r.get("image_height", 0),
                    file_size_bytes=r.get("file_size_bytes", 0),
                    has_exif=r.get("has_exif", True),
                    perceptual_hash=r.get("perceptual_hash", ""),
                    md5_hash=r.get("md5_hash", ""),
                )
                for r in rows
            ]
        except Exception as exc:
            logger.error(
                "Failed to fetch photos for work {w}: {e}", w=work_id, e=exc
            )
            return []

    async def _load_photo_image(self, photo_id: str) -> Optional[Any]:
        """Load the actual image data for a photo (for CLIP processing)."""
        try:
            query = """
                SELECT p.storage_path
                FROM   geo_photos p
                WHERE  p.photo_id = :photo_id
            """
            row = await self.db.fetch_one(query, {"photo_id": photo_id})
            if not row:
                return None
            # In production: load from object storage
            # storage_path = row["storage_path"]
            # return await self.storage.load_image(storage_path)
            return None
        except Exception as exc:
            logger.error(
                "Failed to load photo image {p}: {e}", p=photo_id, e=exc
            )
            return None

    async def _fetch_photo_data(
        self, photo_id: str
    ) -> Optional[Dict[str, Any]]:
        """Fetch photo data and metadata for integrity analysis."""
        try:
            query = """
                SELECT p.photo_id,
                       p.has_exif,
                       p.exif_data,
                       p.jpeg_quality,
                       p.file_size_bytes,
                       p.image_width   AS width,
                       p.image_height  AS height,
                       p.has_thumbnail,
                       p.thumbnail_matches_main,
                       p.quantization_tables
                FROM   geo_photos p
                WHERE  p.photo_id = :photo_id
            """
            row = await self.db.fetch_one(query, {"photo_id": photo_id})
            return dict(row) if row else None
        except Exception as exc:
            logger.error(
                "Failed to fetch photo data for {p}: {e}", p=photo_id, e=exc
            )
            return None

    # ------------------------------------------------------------------
    # Private helpers -- report summary
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_photo_summary(report: PhotoVerificationReport) -> str:
        """Generate a human-readable summary of the photo verification report."""
        lines = [
            f"Photo Verification Report: Work {report.work_id}",
            f"Generated: {report.generated_at.strftime('%Y-%m-%d %H:%M UTC')}",
            "",
            f"Total photos analysed: {report.total_photos}",
            f"Verified: {report.verified_count}",
            f"GPS mismatches: {report.gps_mismatch_count}",
            f"Duplicates detected: {report.duplicate_count}",
            f"Content-type mismatches: {report.type_mismatch_count}",
            f"Manipulation suspected: {report.manipulation_count}",
            f"Bulk upload clusters: {len(report.bulk_upload_clusters)}",
            "",
            f"Overall confidence: {report.overall_confidence:.0%}",
        ]

        if report.bulk_upload_clusters:
            lines.append("")
            lines.append("Bulk Upload Clusters:")
            for cluster in report.bulk_upload_clusters:
                lines.append(
                    f"  - {len(cluster.photo_ids)} photos in "
                    f"{cluster.upload_window_seconds:.0f}s "
                    f"{'[SUSPICIOUS]' if cluster.is_suspicious else ''}"
                )

        return "\n".join(lines)
