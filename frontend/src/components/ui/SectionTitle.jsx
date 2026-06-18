import React from 'react';
import { Box, Typography } from '@mui/material';
import { tokens } from '../../theme.js';

export default function SectionTitle({ title, subtitle, icon, action }) {
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1.6, gap: 1, flexWrap: 'wrap' }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.2 }}>
        {icon && (
          <Box sx={{ display: 'grid', placeItems: 'center', width: 32, height: 32, borderRadius: 2, background: 'rgba(79,140,255,0.15)', color: tokens.blue }}>
            {icon}
          </Box>
        )}
        <Box>
          <Typography sx={{ fontFamily: 'Sora', fontWeight: 700, fontSize: { xs: 16, md: 18 } }}>{title}</Typography>
          {subtitle && <Typography sx={{ fontSize: 12, color: tokens.textDim }}>{subtitle}</Typography>}
        </Box>
      </Box>
      {action}
    </Box>
  );
}
