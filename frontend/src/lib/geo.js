import { geoMercator } from 'd3-geo';
import { Shape } from 'three';

/**
 * Build a d3 Mercator projection fitted to a GeoJSON FeatureCollection,
 * mapping it into a centred [-size/2, size/2] square (in map-plane units).
 *
 * Coordinates produced are used as (x, y) in a plane that the caller lays
 * flat on the ground by rotating its parent group by -PI/2 about X. We
 * negate the projected Y so that north ends up "away" from the camera.
 */
export function buildProjection(featureCollection, size = 100) {
  const projection = geoMercator();
  projection.fitExtent(
    [
      [-size / 2, -size / 2],
      [size / 2, size / 2],
    ],
    featureCollection
  );
  return projection;
}

function ringToVec2(ring, projection) {
  const pts = [];
  for (const coord of ring) {
    const p = projection(coord);
    if (!p || isNaN(p[0]) || isNaN(p[1])) continue;
    pts.push([p[0], -p[1]]);
  }
  return pts;
}

function polygonToShape(rings, projection) {
  const outer = ringToVec2(rings[0], projection);
  if (outer.length < 3) return null;
  const shape = new Shape();
  shape.moveTo(outer[0][0], outer[0][1]);
  for (let i = 1; i < outer.length; i++) shape.lineTo(outer[i][0], outer[i][1]);
  shape.closePath();
  // holes
  for (let h = 1; h < rings.length; h++) {
    const hole = ringToVec2(rings[h], projection);
    if (hole.length < 3) continue;
    const path = new Shape();
    path.moveTo(hole[0][0], hole[0][1]);
    for (let i = 1; i < hole.length; i++) path.lineTo(hole[i][0], hole[i][1]);
    path.closePath();
    shape.holes.push(path);
  }
  return shape;
}

/** Return an array of THREE.Shape for a feature (Polygon or MultiPolygon). */
export function featureToShapes(feature, projection) {
  const g = feature.geometry;
  if (!g) return [];
  const shapes = [];
  if (g.type === 'Polygon') {
    const s = polygonToShape(g.coordinates, projection);
    if (s) shapes.push(s);
  } else if (g.type === 'MultiPolygon') {
    for (const poly of g.coordinates) {
      const s = polygonToShape(poly, projection);
      if (s) shapes.push(s);
    }
  }
  return shapes;
}

/** Projected centroid (map-plane coords) for a feature with properties.centroid [lng,lat]. */
export function featureCentroid(feature, projection) {
  const c = feature.properties?.centroid;
  if (c) {
    const p = projection(c);
    if (p) return [p[0], -p[1]];
  }
  return [0, 0];
}
