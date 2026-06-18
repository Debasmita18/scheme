import React, { useMemo, useState } from 'react';
import * as THREE from 'three';
import { Html, Edges } from '@react-three/drei';
import { buildProjection, featureToShapes, featureCentroid } from '../../lib/geo.js';
import { RISK_COLORS, riskBand } from '../../lib/risk.js';
import { formatLakhsToCrore, formatInt } from '../../lib/format.js';

const MAP_SIZE = 100;

function featureColor(props) {
  if (props.mgnrega_active === false) return RISK_COLORS.inactive;
  return RISK_COLORS[props.risk_band || riskBand(props.risk_score)] || RISK_COLORS.medium;
}

function FeatureMesh({ feature, projection, heightScale, selected, dimmed, onSelect, onHover }) {
  const [hovered, setHovered] = useState(false);

  const data = useMemo(() => {
    const shapes = featureToShapes(feature, projection);
    if (!shapes.length) return null;
    const p = feature.properties;
    const risk = p.risk_score || 0;
    const active = p.mgnrega_active !== false;
    const depth = active ? 0.7 + (risk / 100) * 14 * heightScale : 0.45;
    const geom = new THREE.ExtrudeGeometry(shapes, {
      depth, bevelEnabled: false, curveSegments: 1,
    });
    geom.computeVertexNormals();
    return { geom, depth, color: featureColor(p) };
  }, [feature, projection, heightScale]);

  if (!data) return null;
  const lift = hovered || selected ? 0.9 : 0;
  const emissive = selected ? 1.0 : hovered ? 0.7 : 0.22;

  return (
    <mesh
      geometry={data.geom}
      position={[0, 0, lift]}
      onPointerOver={(e) => { e.stopPropagation(); setHovered(true); onHover?.(feature, data.depth); }}
      onPointerOut={() => { setHovered(false); onHover?.(null); }}
      onClick={(e) => { e.stopPropagation(); onSelect?.(feature); }}
      castShadow
    >
      <meshStandardMaterial
        color={data.color}
        emissive={data.color}
        emissiveIntensity={emissive}
        metalness={0.35}
        roughness={0.5}
        transparent
        opacity={dimmed ? 0.22 : 1}
      />
      <Edges threshold={20} scale={1.001} color={'#0a1024'} />
    </mesh>
  );
}

/**
 * Extruded 3D choropleth of a GeoJSON FeatureCollection. Each feature's
 * height encodes its composite risk score; colour encodes the risk band.
 * Lives inside a <Canvas>. Rendered flat on the ground (group rotated -90°).
 */
export default function IndiaMap3D({ geojson, heightScale = 1, selectedId, onSelect }) {
  const projection = useMemo(
    () => (geojson ? buildProjection(geojson, MAP_SIZE) : null),
    [geojson]
  );
  const [hover, setHover] = useState(null); // { feature, depth }

  if (!geojson || !projection) return null;
  const features = geojson.features;

  const handleHover = (feature, depth) => {
    if (!feature) setHover(null);
    else setHover({ feature, depth });
  };

  let tipPos = null;
  if (hover) {
    const [cx, cy] = featureCentroid(hover.feature, projection);
    tipPos = [cx, cy, hover.depth + 2];
  }

  return (
    <group rotation={[-Math.PI / 2, 0, 0]}>
      {/* base platform */}
      <mesh position={[0, 0, -0.4]}>
        <boxGeometry args={[MAP_SIZE * 1.35, MAP_SIZE * 1.35, 0.6]} />
        <meshStandardMaterial color={'#0a1130'} metalness={0.2} roughness={0.9} />
      </mesh>

      {features.map((f) => (
        <FeatureMesh
          key={f.properties.id}
          feature={f}
          projection={projection}
          heightScale={heightScale}
          selected={selectedId === f.properties.id}
          dimmed={selectedId && selectedId !== f.properties.id}
          onSelect={onSelect}
          onHover={handleHover}
        />
      ))}

      {hover && tipPos && (
        <Html position={tipPos} center distanceFactor={70} style={{ pointerEvents: 'none' }}>
          <div style={tipStyle}>
            <div style={{ fontWeight: 700, fontFamily: 'Sora', marginBottom: 2 }}>
              {hover.feature.properties.district_name || hover.feature.properties.state_name}
            </div>
            {hover.feature.properties.district_name && (
              <div style={{ color: '#9aa8cf', fontSize: 10 }}>
                {hover.feature.properties.state_name}
              </div>
            )}
            <div style={{ display: 'flex', gap: 10, marginTop: 4 }}>
              <span>Risk <b style={{ color: featureColor(hover.feature.properties) }}>
                {hover.feature.properties.risk_score ?? '—'}</b></span>
              <span>Works <b>{formatInt(hover.feature.properties.total_works)}</b></span>
            </div>
            <div style={{ color: '#9aa8cf', fontSize: 10, marginTop: 2 }}>
              Outlay {formatLakhsToCrore(hover.feature.properties.total_expenditure_lakhs)}
            </div>
          </div>
        </Html>
      )}
    </group>
  );
}

const tipStyle = {
  background: 'rgba(8,13,33,0.92)',
  border: '1px solid rgba(126,150,220,0.3)',
  borderRadius: 10,
  padding: '8px 11px',
  color: '#eaf0ff',
  fontSize: 12,
  fontFamily: 'Inter, sans-serif',
  whiteSpace: 'nowrap',
  boxShadow: '0 10px 30px rgba(0,0,0,0.5)',
  transform: 'translateY(-8px)',
};
