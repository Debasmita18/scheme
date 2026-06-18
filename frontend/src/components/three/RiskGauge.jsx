import React, { useRef } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { Html } from '@react-three/drei';
import { riskColor, riskBand, RISK_LABEL } from '../../lib/risk.js';
import { tokens } from '../../theme.js';

function Ring({ score }) {
  const grp = useRef();
  const frac = Math.max(0, Math.min(1, (score || 0) / 100));
  const color = riskColor(score);
  useFrame((state) => {
    if (grp.current) {
      const t = state.clock.elapsedTime;
      grp.current.rotation.y = Math.sin(t * 0.5) * 0.25;
      grp.current.rotation.x = Math.cos(t * 0.4) * 0.12;
    }
  });
  return (
    <group ref={grp}>
      {/* track */}
      <mesh rotation={[0, 0, Math.PI / 2]}>
        <torusGeometry args={[1.25, 0.16, 24, 90]} />
        <meshStandardMaterial color={'#1b2550'} metalness={0.3} roughness={0.7} />
      </mesh>
      {/* value arc */}
      <mesh rotation={[0, 0, Math.PI / 2]}>
        <torusGeometry args={[1.25, 0.19, 24, 90, frac * Math.PI * 2]} />
        <meshStandardMaterial color={color} emissive={color} emissiveIntensity={0.7} metalness={0.4} roughness={0.4} />
      </mesh>
      <Html center style={{ pointerEvents: 'none', textAlign: 'center' }}>
        <div style={{ fontFamily: 'Sora', fontWeight: 800, fontSize: 30, color: '#eaf0ff', lineHeight: 1 }}>
          {Math.round(score)}
        </div>
        <div style={{ fontSize: 10, letterSpacing: 1, color, textTransform: 'uppercase', fontWeight: 700 }}>
          {RISK_LABEL[riskBand(score)]}
        </div>
      </Html>
    </group>
  );
}

export default function RiskGauge({ score = 0 }) {
  return (
    <Canvas dpr={[1, 1.8]} camera={{ position: [0, 0, 4], fov: 42 }} gl={{ alpha: true, antialias: true }}>
      <ambientLight intensity={0.8} />
      <directionalLight position={[3, 4, 5]} intensity={1.2} />
      <pointLight position={[-3, -2, 2]} intensity={0.5} color={tokens.saffron} />
      <Ring score={score} />
    </Canvas>
  );
}
