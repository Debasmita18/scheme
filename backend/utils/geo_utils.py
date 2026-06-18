"""
Geospatial utilities for the MGNREGA Verification system.

Provides functions for area calculation, distance measurement,
coordinate transformation, bounding-box generation, boundary checks,
and polygon overlap computation.

All public functions are pure (no database or network I/O) and safe
to call from async contexts.
"""

from __future__ import annotations

import math
from typing import Optional, Sequence

from pyproj import CRS, Transformer
from shapely.geometry import MultiPolygon, Point, Polygon, shape
from shapely.ops import transform as shapely_transform

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_EARTH_RADIUS_M: float = 6_371_000.0  # Mean Earth radius in metres
_WGS84_EPSG: int = 4326

# Approximate bounding box of India (WGS 84)
_INDIA_BOUNDS = {
    "min_lat": 6.5546079,
    "max_lat": 35.6745457,
    "min_lon": 68.1113787,
    "max_lon": 97.395561,
}

# UTM zone lookup: maps approximate central meridian -> EPSG code for northern
# hemisphere UTM zones that cover India (zones 42-47).
_INDIA_UTM_ZONES: dict[int, int] = {
    69: 32642,   # UTM 42N
    75: 32643,   # UTM 43N
    81: 32644,   # UTM 44N
    87: 32645,   # UTM 45N
    93: 32646,   # UTM 46N
    99: 32647,   # UTM 47N
}


# ---------------------------------------------------------------------------
# Area calculation
# ---------------------------------------------------------------------------

def calculate_polygon_area_sqm(
    coordinates: list[list[float]],
    *,
    srid: int = _WGS84_EPSG,
) -> float:
    """Calculate the area of a polygon in square metres.

    The polygon is first reprojected from WGS 84 to an appropriate UTM
    zone so that the area is computed on a projected plane.

    Args:
        coordinates: List of ``[longitude, latitude]`` pairs forming a
            closed ring (first == last). Follows GeoJSON convention.
        srid: EPSG code of the input coordinates (default 4326 / WGS 84).

    Returns:
        Area in square metres.

    Raises:
        ValueError: If fewer than 4 coordinate pairs are provided (a valid
            closed polygon requires at least 4 points).
    """
    if len(coordinates) < 4:
        raise ValueError(
            "A closed polygon requires at least 4 coordinate pairs "
            f"(including closing point); got {len(coordinates)}"
        )

    polygon = Polygon(coordinates)
    if not polygon.is_valid:
        polygon = polygon.buffer(0)  # attempt fix

    centroid = polygon.centroid
    utm_epsg = _best_utm_epsg(centroid.y, centroid.x)

    transformer = Transformer.from_crs(
        CRS.from_epsg(srid),
        CRS.from_epsg(utm_epsg),
        always_xy=True,
    )
    projected = shapely_transform(transformer.transform, polygon)
    return abs(projected.area)


# ---------------------------------------------------------------------------
# Distance (Haversine)
# ---------------------------------------------------------------------------

def haversine_distance_m(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    """Compute the great-circle distance between two points using the
    Haversine formula.

    Args:
        lat1: Latitude of point 1 in decimal degrees.
        lon1: Longitude of point 1 in decimal degrees.
        lat2: Latitude of point 2 in decimal degrees.
        lon2: Longitude of point 2 in decimal degrees.

    Returns:
        Distance in metres.
    """
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return _EARTH_RADIUS_M * c


# ---------------------------------------------------------------------------
# Coordinate system conversion
# ---------------------------------------------------------------------------

def convert_coordinates(
    x: float,
    y: float,
    from_epsg: int,
    to_epsg: int,
) -> tuple[float, float]:
    """Convert a single coordinate pair between two CRS.

    Args:
        x: Easting or longitude.
        y: Northing or latitude.
        from_epsg: Source EPSG code (e.g. 4326 for WGS 84).
        to_epsg: Target EPSG code (e.g. 32644 for UTM 44N).

    Returns:
        Tuple ``(x_out, y_out)`` in the target CRS.
    """
    transformer = Transformer.from_crs(
        CRS.from_epsg(from_epsg),
        CRS.from_epsg(to_epsg),
        always_xy=True,
    )
    return transformer.transform(x, y)


def wgs84_to_utm(lat: float, lon: float) -> tuple[float, float, int]:
    """Convert WGS 84 lat/lon to the best-fit UTM zone for India.

    Args:
        lat: Latitude in decimal degrees.
        lon: Longitude in decimal degrees.

    Returns:
        Tuple ``(easting, northing, utm_epsg)`` where *utm_epsg* is the
        EPSG code of the UTM zone used.
    """
    utm_epsg = _best_utm_epsg(lat, lon)
    easting, northing = convert_coordinates(lon, lat, _WGS84_EPSG, utm_epsg)
    return easting, northing, utm_epsg


def utm_to_wgs84(
    easting: float,
    northing: float,
    utm_epsg: int,
) -> tuple[float, float]:
    """Convert UTM easting/northing back to WGS 84 lat/lon.

    Args:
        easting: UTM easting in metres.
        northing: UTM northing in metres.
        utm_epsg: EPSG code of the UTM zone.

    Returns:
        Tuple ``(longitude, latitude)`` in WGS 84.
    """
    return convert_coordinates(easting, northing, utm_epsg, _WGS84_EPSG)


# ---------------------------------------------------------------------------
# Bounding box
# ---------------------------------------------------------------------------

def bounding_box_from_point(
    lat: float,
    lon: float,
    radius_m: float,
) -> dict[str, float]:
    """Generate a WGS 84 bounding box around a centre point.

    Uses a simple angular offset approximation that is accurate enough
    for radii up to ~50 km at Indian latitudes.

    Args:
        lat: Centre latitude in decimal degrees.
        lon: Centre longitude in decimal degrees.
        radius_m: Radius in metres.

    Returns:
        Dict with keys ``min_lat``, ``max_lat``, ``min_lon``, ``max_lon``.
    """
    if radius_m <= 0:
        raise ValueError("radius_m must be positive")

    # Approximate degrees per metre at this latitude
    lat_offset = radius_m / 111_320.0
    lon_offset = radius_m / (111_320.0 * math.cos(math.radians(lat)))

    return {
        "min_lat": lat - lat_offset,
        "max_lat": lat + lat_offset,
        "min_lon": lon - lon_offset,
        "max_lon": lon + lon_offset,
    }


# ---------------------------------------------------------------------------
# Indian boundary check
# ---------------------------------------------------------------------------

def is_point_within_india(
    lat: float,
    lon: float,
    *,
    strict: bool = False,
    india_boundary: Optional[Polygon | MultiPolygon] = None,
) -> bool:
    """Check whether a GPS coordinate falls within India.

    In *non-strict* mode (default), a fast bounding-box test is used.
    In *strict* mode, the caller must provide a Shapely geometry of
    India's border for a proper point-in-polygon check.

    Args:
        lat: Latitude in decimal degrees.
        lon: Longitude in decimal degrees.
        strict: When ``True``, use the supplied ``india_boundary`` polygon.
        india_boundary: A Shapely ``Polygon`` or ``MultiPolygon`` of
            India's territory. Required when ``strict=True``.

    Returns:
        ``True`` if the point is (likely) within India.

    Raises:
        ValueError: If ``strict=True`` but no boundary geometry is given.
    """
    if strict:
        if india_boundary is None:
            raise ValueError(
                "india_boundary geometry is required when strict=True"
            )
        return india_boundary.contains(Point(lon, lat))

    return (
        _INDIA_BOUNDS["min_lat"] <= lat <= _INDIA_BOUNDS["max_lat"]
        and _INDIA_BOUNDS["min_lon"] <= lon <= _INDIA_BOUNDS["max_lon"]
    )


# ---------------------------------------------------------------------------
# Polygon overlap
# ---------------------------------------------------------------------------

def polygon_overlap_percentage(
    polygon_a_coords: list[list[float]],
    polygon_b_coords: list[list[float]],
) -> float:
    """Calculate the overlap between two polygons as a percentage of the
    smaller polygon's area.

    Args:
        polygon_a_coords: List of ``[lon, lat]`` pairs for polygon A.
        polygon_b_coords: List of ``[lon, lat]`` pairs for polygon B.

    Returns:
        Overlap as a percentage (0.0 -- 100.0).  Returns 0.0 when the
        polygons do not intersect.
    """
    poly_a = Polygon(polygon_a_coords)
    poly_b = Polygon(polygon_b_coords)

    if not poly_a.is_valid:
        poly_a = poly_a.buffer(0)
    if not poly_b.is_valid:
        poly_b = poly_b.buffer(0)

    if not poly_a.intersects(poly_b):
        return 0.0

    intersection = poly_a.intersection(poly_b)
    if intersection.is_empty:
        return 0.0

    # Project all three to UTM for accurate area comparison
    centroid = intersection.centroid
    utm_epsg = _best_utm_epsg(centroid.y, centroid.x)
    transformer = Transformer.from_crs(
        CRS.from_epsg(_WGS84_EPSG),
        CRS.from_epsg(utm_epsg),
        always_xy=True,
    )

    proj_a = shapely_transform(transformer.transform, poly_a)
    proj_b = shapely_transform(transformer.transform, poly_b)
    proj_inter = shapely_transform(transformer.transform, intersection)

    smaller_area = min(proj_a.area, proj_b.area)
    if smaller_area == 0:
        return 0.0

    return (proj_inter.area / smaller_area) * 100.0


def geojson_to_shapely(geojson: dict) -> Polygon | MultiPolygon:
    """Convert a GeoJSON geometry dict to a Shapely geometry.

    Args:
        geojson: A GeoJSON ``Polygon`` or ``MultiPolygon`` dict with
            ``type`` and ``coordinates`` keys.

    Returns:
        Corresponding Shapely geometry.

    Raises:
        ValueError: If the GeoJSON type is unsupported.
    """
    geom = shape(geojson)
    if not isinstance(geom, (Polygon, MultiPolygon)):
        raise ValueError(
            f"Expected Polygon or MultiPolygon, got {type(geom).__name__}"
        )
    return geom


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _best_utm_epsg(lat: float, lon: float) -> int:
    """Return the best UTM EPSG code for a given lat/lon in India.

    Falls back to computing from the standard UTM zone formula if the
    longitude is outside the pre-computed India lookup table.
    """
    # Try the India-specific lookup first
    for central_meridian, epsg in _INDIA_UTM_ZONES.items():
        if abs(lon - central_meridian) <= 3:
            return epsg

    # Generic UTM zone calculation (northern hemisphere)
    zone_number = int((lon + 180) / 6) + 1
    if lat >= 0:
        return 32600 + zone_number
    return 32700 + zone_number
