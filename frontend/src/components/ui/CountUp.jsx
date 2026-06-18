import React, { useEffect, useState } from 'react';
import { animate } from 'framer-motion';

/** Animated number that counts up to `value` on mount / change. */
export default function CountUp({ value = 0, duration = 1.1, format = (v) => Math.round(v) }) {
  const [display, setDisplay] = useState(0);
  useEffect(() => {
    const controls = animate(0, value, {
      duration,
      ease: [0.16, 1, 0.3, 1],
      onUpdate: (v) => setDisplay(v),
    });
    return () => controls.stop();
  }, [value, duration]);
  return <>{format(display)}</>;
}
