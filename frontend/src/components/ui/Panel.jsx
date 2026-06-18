import React from 'react';
import { Card, Box, Typography } from '@mui/material';
import { tokens } from '../../theme.js';

export default function Panel({ title, subtitle, action, children, sx, bodySx, noPad }) {
  return (
    <Card sx={{ height: '100%', display: 'flex', flexDirection: 'column', ...sx }}>
      {(title || action) && (
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', px: 2.2, pt: 1.8, pb: subtitle ? 0.3 : 1.4, gap: 1 }}>
          <Box>
            {title && <Typography sx={{ fontFamily: 'Sora', fontWeight: 700, fontSize: 15 }}>{title}</Typography>}
            {subtitle && <Typography sx={{ fontSize: 11.5, color: tokens.textDim }}>{subtitle}</Typography>}
          </Box>
          {action}
        </Box>
      )}
      <Box sx={{ flex: 1, minHeight: 0, p: noPad ? 0 : 2.2, pt: title ? 1 : (noPad ? 0 : 2.2), ...bodySx }}>
        {children}
      </Box>
    </Card>
  );
}
