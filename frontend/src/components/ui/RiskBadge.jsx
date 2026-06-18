import React from 'react';
import { Chip } from '@mui/material';
import { riskColor, riskBand, RISK_LABEL } from '../../lib/risk.js';

export default function RiskBadge({ score, band, size = 'small', showScore = true }) {
  const b = band || riskBand(score);
  const c = riskColor(b);
  const label = showScore && score != null ? `${RISK_LABEL[b]} · ${score}` : RISK_LABEL[b];
  return (
    <Chip
      size={size}
      label={label}
      sx={{
        bgcolor: `${c}22`,
        color: c,
        border: `1px solid ${c}66`,
        fontWeight: 700,
        fontSize: 11.5,
        height: size === 'small' ? 22 : 28,
      }}
    />
  );
}
