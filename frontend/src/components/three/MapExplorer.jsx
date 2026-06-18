import React, { Suspense } from 'react';
import { Canvas } from '@react-three/fiber';
import { OrbitControls } from '@react-three/drei';
import { Box, CircularProgress, Typography, Chip } from '@mui/material';
import OpenWithIcon from '@mui/icons-material/OpenWith';
import IndiaMap3D from './IndiaMap3D.jsx';
import { RISK_COLORS } from '../../lib/risk.js';
import { tokens } from '../../theme.js';

const LEGEND = [
  { band: 'critical', label: 'Critical' },
  { band: 'high', label: 'High' },
  { band: 'medium', label: 'Moderate' },
  { band: 'low', label: 'Low' },
  { band: 'inactive', label: 'Urban / N.A.' },
];

function Scene({ geojson, heightScale, selectedId, onSelect }) {
  return (
    <>
      <color attach="background" args={['#070b1f']} />
      <fog attach="fog" args={['#070b1f', 160, 320]} />
      <ambientLight intensity={0.75} />
      <directionalLight position={[40, 90, 50]} intensity={1.25} castShadow />
      <pointLight position={[-55, 40, -30]} intensity={0.8} color={tokens.saffron} />
      <pointLight position={[55, 30, 50]} intensity={0.7} color={tokens.blue} />
      <Suspense fallback={null}>
        <IndiaMap3D
          geojson={geojson}
          heightScale={heightScale}
          selectedId={selectedId}
          onSelect={onSelect}
        />
      </Suspense>
      <OrbitControls
        makeDefault
        enablePan={false}
        enableDamping
        dampingFactor={0.08}
        minDistance={55}
        maxDistance={210}
        maxPolarAngle={Math.PI / 2.15}
        autoRotate={!selectedId}
        autoRotateSpeed={0.35}
      />
    </>
  );
}

export default function MapExplorer({
  geojson,
  loading,
  heightScale = 1,
  selectedId,
  onSelect,
  hint = 'Drag to orbit · scroll to zoom · click a region to drill in',
}) {
  return (
    <Box sx={{ position: 'relative', width: '100%', height: '100%', minHeight: 0 }}>
      {(loading || !geojson) && (
        <Box sx={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center', zIndex: 2 }}>
          <Box sx={{ textAlign: 'center' }}>
            <CircularProgress size={30} />
            <Typography sx={{ mt: 1.5, fontSize: 12, color: tokens.textDim }}>
              Rendering India…
            </Typography>
          </Box>
        </Box>
      )}

      <Canvas
        shadows
        dpr={[1, 1.8]}
        camera={{ position: [0, 90, 96], fov: 38, near: 0.1, far: 1000 }}
        gl={{ antialias: true, powerPreference: 'high-performance' }}
        style={{ borderRadius: 16 }}
      >
        {geojson && (
          <Scene geojson={geojson} heightScale={heightScale} selectedId={selectedId} onSelect={onSelect} />
        )}
      </Canvas>

      {/* Legend */}
      <Box
        sx={{
          position: 'absolute', left: 12, bottom: 12, p: 1.2, px: 1.5,
          borderRadius: 2.5, background: 'rgba(8,13,33,0.7)',
          border: `1px solid ${tokens.panelBorder}`, backdropFilter: 'blur(8px)',
          display: 'flex', gap: 1.2, flexWrap: 'wrap', maxWidth: '90%',
        }}
      >
        {LEGEND.map((l) => (
          <Box key={l.band} sx={{ display: 'flex', alignItems: 'center', gap: 0.6 }}>
            <Box sx={{ width: 11, height: 11, borderRadius: '3px', bgcolor: RISK_COLORS[l.band] }} />
            <Typography sx={{ fontSize: 10.5, color: tokens.textDim }}>{l.label}</Typography>
          </Box>
        ))}
      </Box>

      {/* Hint */}
      <Chip
        icon={<OpenWithIcon sx={{ fontSize: 14 }} />}
        label={hint}
        size="small"
        sx={{
          position: 'absolute', right: 12, top: 12,
          display: { xs: 'none', md: 'flex' },
          background: 'rgba(8,13,33,0.7)', border: `1px solid ${tokens.panelBorder}`,
          color: tokens.textDim, fontSize: 11,
        }}
      />
    </Box>
  );
}
