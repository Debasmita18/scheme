import React, { useMemo, useRef } from 'react';
import * as THREE from 'three';
import { Canvas, useFrame } from '@react-three/fiber';
import { Stars } from '@react-three/drei';
import { tokens } from '../../theme.js';

const R = 2;

function latLngToVec3(lng, lat, radius) {
  const phi = (90 - lat) * (Math.PI / 180);
  const theta = (lng + 180) * (Math.PI / 180);
  return [
    -radius * Math.sin(phi) * Math.cos(theta),
    radius * Math.cos(phi),
    radius * Math.sin(phi) * Math.sin(theta),
  ];
}

function IndiaPoints({ geojson }) {
  const positions = useMemo(() => {
    if (!geojson) return new Float32Array(0);
    const pts = [];
    for (const f of geojson.features) {
      const g = f.geometry;
      if (!g) continue;
      const polys = g.type === 'Polygon' ? [g.coordinates] : g.coordinates;
      for (const poly of polys) {
        for (const ring of poly) {
          for (let i = 0; i < ring.length; i += 1) {
            const [lng, lat] = ring[i];
            const v = latLngToVec3(lng, lat, R + 0.02);
            pts.push(v[0], v[1], v[2]);
          }
        }
      }
    }
    return new Float32Array(pts);
  }, [geojson]);

  if (!positions.length) return null;
  return (
    <points>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" array={positions} count={positions.length / 3} itemSize={3} />
      </bufferGeometry>
      <pointsMaterial size={0.035} color={tokens.saffron} sizeAttenuation transparent opacity={0.95} />
    </points>
  );
}

function GlobeGroup({ geojson }) {
  const ref = useRef();
  useFrame((_, delta) => {
    if (ref.current) ref.current.rotation.y += delta * 0.12;
  });
  return (
    <group ref={ref} rotation={[0.32, -1.2, 0]}>
      {/* core globe */}
      <mesh>
        <sphereGeometry args={[R, 64, 64]} />
        <meshStandardMaterial
          color={'#0e1b46'}
          emissive={'#0a1336'}
          emissiveIntensity={0.5}
          metalness={0.4}
          roughness={0.6}
        />
      </mesh>
      {/* graticule wireframe */}
      <mesh>
        <sphereGeometry args={[R + 0.005, 24, 18]} />
        <meshBasicMaterial color={tokens.blue} wireframe transparent opacity={0.10} />
      </mesh>
      {/* atmosphere glow */}
      <mesh>
        <sphereGeometry args={[R * 1.13, 48, 48]} />
        <meshBasicMaterial color={tokens.blue} transparent opacity={0.06} side={THREE.BackSide} />
      </mesh>
      <IndiaPoints geojson={geojson} />
    </group>
  );
}

export default function GlobeHero({ geojson }) {
  return (
    <Canvas
      dpr={[1, 1.8]}
      camera={{ position: [0, 0, 5.4], fov: 42 }}
      gl={{ antialias: true, alpha: true }}
      style={{ width: '100%', height: '100%' }}
    >
      <ambientLight intensity={0.7} />
      <directionalLight position={[5, 3, 5]} intensity={1.4} />
      <pointLight position={[-4, -2, -3]} intensity={0.6} color={tokens.saffron} />
      <Stars radius={60} depth={30} count={1800} factor={3} saturation={0} fade speed={0.6} />
      <GlobeGroup geojson={geojson} />
    </Canvas>
  );
}
