"""
Data Ingestion Package
=======================

Provides modules for ingesting MGNREGA verification data from multiple
sources:

- **nrega_scraper** -- Real-time scraping of the NREGA MIS portal
  (nrega.nic.in) for job cards, muster rolls, works, and FTO records.
- **satellite_fetcher** -- Sentinel-2 imagery from Copernicus Data Space
  and ISRO Bhuvan WMS services for before/after work-site verification.
- **geomgnrega_photos** -- Geotagged photo ingestion with EXIF metadata
  extraction, perceptual hashing, and anomaly detection.

Quick Start::

    from data_ingestion import (
        NREGAScraper,
        NREGADataPipeline,
        SatelliteFetcher,
        ISROBhuvanFetcher,
        GeoMGNREGAPhotoIngester,
    )

    # Scrape NREGA data
    async with NREGAScraper() as scraper:
        districts = await scraper.fetch_district_list("34")

    # Fetch satellite imagery
    async with SatelliteFetcher() as fetcher:
        result = await fetcher.get_before_after_images(
            lat=26.85, lon=76.55,
            work_start_date="2025-01-15",
            work_end_date="2025-04-30",
        )

    # Ingest and analyse geotagged photos
    async with GeoMGNREGAPhotoIngester() as ingester:
        photos = await ingester.fetch_geotagged_photos("RJ/3401/001/001/00001")
        anomalies = ingester.detect_photo_anomalies(photos.metadata)
"""

from data_ingestion.nrega_scraper import (
    NREGAScraper,
    NREGADataPipeline,
    IngestionStats,
    District,
    Block,
    Panchayat,
    WorkRecord,
    WorkStatus,
    MusterRollEntry,
    FTORecord,
    WorkerDetail,
    STATE_CODES,
)
from data_ingestion.satellite_fetcher import (
    SatelliteFetcher,
    ISROBhuvanFetcher,
    BoundingBox,
    SentinelProduct,
    BandData,
    BeforeAfterResult,
)
from data_ingestion.geomgnrega_photos import (
    GeoMGNREGAPhotoIngester,
    PhotoMetadata,
    PhotoAnomaly,
    PhotoIngestionResult,
    AnomalyType,
    GPSCoordinate,
    compute_perceptual_hash,
    hamming_distance,
)

__all__ = [
    # NREGA Scraper
    "NREGAScraper",
    "NREGADataPipeline",
    "IngestionStats",
    "District",
    "Block",
    "Panchayat",
    "WorkRecord",
    "WorkStatus",
    "MusterRollEntry",
    "FTORecord",
    "WorkerDetail",
    "STATE_CODES",
    # Satellite Fetcher
    "SatelliteFetcher",
    "ISROBhuvanFetcher",
    "BoundingBox",
    "SentinelProduct",
    "BandData",
    "BeforeAfterResult",
    # GeoMGNREGA Photos
    "GeoMGNREGAPhotoIngester",
    "PhotoMetadata",
    "PhotoAnomaly",
    "PhotoIngestionResult",
    "AnomalyType",
    "GPSCoordinate",
    "compute_perceptual_hash",
    "hamming_distance",
]
