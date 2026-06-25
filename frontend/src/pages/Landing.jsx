import React, { Suspense } from 'react';
import { useNavigate } from 'react-router-dom';
import { Box, Grid, Typography, Button, Chip, Card } from '@mui/material';
import { motion } from 'framer-motion';
import SatelliteAltIcon from '@mui/icons-material/SatelliteAlt';
import AccountTreeIcon from '@mui/icons-material/AccountTree';
import FactCheckIcon from '@mui/icons-material/FactCheck';
import SmartToyIcon from '@mui/icons-material/SmartToy';
import ArrowForwardIcon from '@mui/icons-material/ArrowForward';
import PublicIcon from '@mui/icons-material/Public';
import { useNationalSummary, useStatesGeo } from '../hooks/useData.js';
import { GlobeHero } from '../components/three/lazy.jsx';
import CountUp from '../components/ui/CountUp.jsx';
import { tokens } from '../theme.js';
import { formatLakhsToCrore, formatInt } from '../lib/format.js';

const CAPS = [
  { icon: <SatelliteAltIcon />, color: tokens.blue, title: 'Satellite Verification', desc: 'Sentinel-2 before/after change detection confirms whether reported earthwork, ponds and roads physically exist on the ground.' },
  { icon: <AccountTreeIcon />, color: tokens.saffron, title: 'Payment-Network Forensics', desc: 'Graph analysis of worker–account–FTO flows surfaces shell beneficiaries, circular payments and vendor collusion.' },
  { icon: <FactCheckIcon />, color: tokens.green, title: 'Muster-Roll Forensics', desc: 'Statistical tests (Benford’s law, attendance-clone & ghost-worker detection) flag fabricated person-days.' },
  { icon: <SmartToyIcon />, color: tokens.cyan, title: 'AI Case Files & Briefings', desc: 'LLM agents fuse the evidence into CAG-format dossiers and vernacular summaries — in minutes, not months.' },
];

function StatTile({ label, value, delay }) {
  return (
    <Card component={motion.div} initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }}
      transition={{ delay }} sx={{ p: 2, textAlign: 'center' }}>
      <Typography sx={{ fontFamily: 'Sora', fontWeight: 800, fontSize: { xs: 20, md: 26 }, background: `linear-gradient(90deg, ${tokens.saffron}, ${tokens.amber})`, WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>
        {value}
      </Typography>
      <Typography sx={{ fontSize: 11.5, color: tokens.textDim, mt: 0.3 }}>{label}</Typography>
    </Card>
  );
}

export default function Landing() {
  const navigate = useNavigate();
  const { data: n } = useNationalSummary();
  const { data: geo } = useStatesGeo();

  return (
    <Box>
      {/* Hero */}
      <Box className="glass" sx={{ position: 'relative', overflow: 'hidden', mb: 2.5,
        display: 'grid', gridTemplateColumns: { xs: '1fr', md: '1.2fr 1fr' }, minHeight: { xs: 460, md: 420 } }}>
        <Box sx={{ p: { xs: 3, md: 5 }, zIndex: 2, display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1.5 }}>
            <Box className="tricolor-bar" sx={{ width: 46 }} />
            <Typography sx={{ fontSize: 11.5, letterSpacing: 1.5, color: tokens.textDim, textTransform: 'uppercase' }}>
              Government of India · Ministry of Rural Development
            </Typography>
          </Box>
          <Typography component={motion.h1} initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }}
            sx={{ fontFamily: 'Sora', fontWeight: 800, fontSize: { xs: 30, md: 46 }, lineHeight: 1.05 }}>
            Every rupee of MGNREGA,{' '}
            <span style={{ background: `linear-gradient(90deg, ${tokens.saffron}, ${tokens.amber})`, WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>
              verified.
            </span>
          </Typography>
          <Typography sx={{ color: tokens.textDim, mt: 2, fontSize: { xs: 14, md: 16 }, maxWidth: 560, lineHeight: 1.6 }}>
            A single national command centre that screens the rural employment guarantee for fraud —
            fusing satellite imagery, payment-network analysis and muster-roll forensics across
            <b style={{ color: tokens.text }}> every state, union territory and district</b>, and turning
            it into audit-ready evidence for faster, cleaner wage release.
          </Typography>
          <Box sx={{ display: 'flex', gap: 1.5, mt: 3.5, flexWrap: 'wrap' }}>
            <Button size="large" variant="contained" endIcon={<ArrowForwardIcon />} onClick={() => navigate('/dashboard')}
              sx={{ background: `linear-gradient(90deg, ${tokens.saffronDeep}, ${tokens.saffron})`, color: '#1a1205', fontWeight: 700, px: 3 }}>
              Enter National Dashboard
            </Button>
            <Button size="large" variant="outlined" startIcon={<PublicIcon />} onClick={() => navigate('/states')}
              sx={{ borderColor: tokens.panelBorder, color: tokens.text }}>
              Explore States & UTs
            </Button>
          </Box>
        </Box>
        <Box sx={{ position: 'relative', minHeight: { xs: 240, md: 'auto' }, height: '100%' }}>
          <Suspense fallback={null}><GlobeHero geojson={geo} /></Suspense>
        </Box>
      </Box>

      {/* Headline stats */}
      <Grid container spacing={2} sx={{ mb: 3 }}>
        <Grid item xs={6} md={3}><StatTile delay={0.05} label="States & Union Territories"
          value={n ? `${n.total_states} + ${n.total_uts}` : '—'} /></Grid>
        <Grid item xs={6} md={3}><StatTile delay={0.12} label="Districts under verification"
          value={n ? <CountUp value={n.total_districts} format={(v) => formatInt(v)} /> : '—'} /></Grid>
        <Grid item xs={6} md={3}><StatTile delay={0.19} label="Annual outlay screened"
          value={n ? formatLakhsToCrore(n.total_expenditure_lakhs) : '—'} /></Grid>
        <Grid item xs={6} md={3}><StatTile delay={0.26} label="Person-days generated"
          value={n ? `${(n.person_days / 1e7).toFixed(0)} Cr` : '—'} /></Grid>
      </Grid>

      {/* Capabilities */}
      <Typography sx={{ fontFamily: 'Sora', fontWeight: 700, fontSize: 18, mb: 1.5 }}>
        How the platform protects public money
      </Typography>
      <Grid container spacing={2} sx={{ mb: 3 }}>
        {CAPS.map((c, i) => (
          <Grid item xs={12} sm={6} md={3} key={c.title}>
            <Card component={motion.div} initial={{ opacity: 0, y: 18 }} animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.08 }} whileHover={{ y: -4 }} sx={{ p: 2.4, height: '100%' }}>
              <Box sx={{ display: 'grid', placeItems: 'center', width: 44, height: 44, borderRadius: 2.5, background: `${c.color}1f`, color: c.color, mb: 1.5 }}>
                {c.icon}
              </Box>
              <Typography sx={{ fontFamily: 'Sora', fontWeight: 700, fontSize: 15.5 }}>{c.title}</Typography>
              <Typography sx={{ color: tokens.textDim, fontSize: 12.5, mt: 0.6, lineHeight: 1.55 }}>{c.desc}</Typography>
            </Card>
          </Grid>
        ))}
      </Grid>

      {/* Why it matters */}
      <Card sx={{ p: { xs: 2.5, md: 3.5 }, display: 'flex', gap: 3, flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between' }}>
        <Box sx={{ maxWidth: 620 }}>
          <Typography sx={{ fontFamily: 'Sora', fontWeight: 700, fontSize: 18 }}>Why it matters</Typography>
          <Typography sx={{ color: tokens.textDim, fontSize: 13.5, mt: 0.8, lineHeight: 1.6 }}>
            Independent audits estimate 15–40% leakage in parts of the programme. By flagging high-risk
            spend <i>before</i> release and accelerating verification for genuine works, the system targets an
            estimated <b style={{ color: tokens.amber }}>{n ? formatLakhsToCrore(n.estimated_leakage_lakhs) : '—'}</b> of
            at-risk outlay this financial year — while getting honest workers paid faster.
          </Typography>
        </Box>
        <Button size="large" variant="contained" endIcon={<ArrowForwardIcon />} onClick={() => navigate('/dashboard')}
          sx={{ background: `linear-gradient(90deg, ${tokens.saffronDeep}, ${tokens.saffron})`, color: '#1a1205', fontWeight: 700 }}>
          View the National Dashboard
        </Button>
      </Card>
    </Box>
  );
}
