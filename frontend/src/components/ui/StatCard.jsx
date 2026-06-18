import React from 'react';
import { Card, Box, Typography } from '@mui/material';
import { motion } from 'framer-motion';
import TrendingUpIcon from '@mui/icons-material/TrendingUp';
import TrendingDownIcon from '@mui/icons-material/TrendingDown';
import { tokens } from '../../theme.js';
import CountUp from './CountUp.jsx';

const MCard = motion(Card);

export default function StatCard({
  label, value, rawValue, format = (v) => Math.round(v).toLocaleString('en-IN'),
  icon, color = tokens.blue, delta, deltaPositiveIsGood = true, sub, index = 0,
}) {
  const hasDelta = delta != null;
  const isUp = delta > 0;
  const good = deltaPositiveIsGood ? isUp : !isUp;

  return (
    <MCard
      initial={{ opacity: 0, y: 18 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay: index * 0.07, ease: [0.16, 1, 0.3, 1] }}
      whileHover={{ y: -4 }}
      sx={{ p: 2.2, position: 'relative', overflow: 'hidden', height: '100%' }}
    >
      <Box sx={{ position: 'absolute', top: 0, left: 0, right: 0, height: 3, background: `linear-gradient(90deg, ${color}, transparent)` }} />
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', mb: 1 }}>
        <Typography sx={{ fontSize: 12.5, color: tokens.textDim, fontWeight: 600, letterSpacing: 0.2 }}>
          {label}
        </Typography>
        <Box sx={{ display: 'grid', placeItems: 'center', width: 34, height: 34, borderRadius: 2, background: `${color}1f`, color }}>
          {icon}
        </Box>
      </Box>
      <Typography sx={{ fontFamily: 'Sora', fontWeight: 800, fontSize: { xs: 22, md: 26 }, lineHeight: 1.1 }}>
        {rawValue != null ? <CountUp value={rawValue} format={format} /> : value}
      </Typography>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mt: 0.8, flexWrap: 'wrap' }}>
        {hasDelta && (
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.3, color: good ? tokens.green : tokens.red }}>
            {isUp ? <TrendingUpIcon sx={{ fontSize: 15 }} /> : <TrendingDownIcon sx={{ fontSize: 15 }} />}
            <Typography sx={{ fontSize: 12, fontWeight: 700 }}>{Math.abs(delta)}%</Typography>
          </Box>
        )}
        {sub && <Typography sx={{ fontSize: 11.5, color: tokens.textDim }}>{sub}</Typography>}
      </Box>
    </MCard>
  );
}
