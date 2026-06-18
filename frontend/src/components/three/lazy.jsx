import React, { lazy, Suspense } from 'react';
import Canvas3D from './Canvas3D.jsx';

// Lazy-loaded so three.js only ships when a 3D view is actually rendered,
// and wrapped in a WebGL error boundary for graceful degradation.
const _MapExplorer = lazy(() => import('./MapExplorer.jsx'));
const _GlobeHero = lazy(() => import('./GlobeHero.jsx'));
const _RiskGauge = lazy(() => import('./RiskGauge.jsx'));

export function MapExplorer(props) {
  return (
    <Canvas3D>
      <Suspense fallback={null}>
        <_MapExplorer {...props} />
      </Suspense>
    </Canvas3D>
  );
}

export function GlobeHero(props) {
  return (
    <Canvas3D fallback={null}>
      <Suspense fallback={null}>
        <_GlobeHero {...props} />
      </Suspense>
    </Canvas3D>
  );
}

export function RiskGauge(props) {
  return (
    <Canvas3D fallback={null}>
      <Suspense fallback={null}>
        <_RiskGauge {...props} />
      </Suspense>
    </Canvas3D>
  );
}
