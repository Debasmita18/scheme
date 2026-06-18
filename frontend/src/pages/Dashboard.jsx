import React, { Suspense, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Box, Grid, Typography, Button, Chip, List, ListItemButton, Divider, CircularProgress,
} from '@mui/material';
import AccountBalanceIcon from '@mui/icons-material/AccountBalance';
import EngineeringIcon from '@mui/icons-material/Engineering';
import ReportProblemIcon from '@mui/icons-material/ReportProblem';
import SavingsIcon from '@mui/icons-material/Savings';
import GroupsIcon from '@mui/icons-material/Groups';
import PublicIcon from '@mui/icons-material/Public';
import TimelineIcon from '@mui/icons-material/Timeline';
import MapIcon from '@mui/icons-material/Map';
import ArrowForwardIcon from '@mui/icons-material/ArrowForward';

import { motion } from 'framer-motion';
import {
  useNationalSummary, useNationalTrends, useAnomalyBreakdown,
  useTopDistricts, useStatesGeo, useStates,
} from '../hooks/useData.js';
import StatCard from '../components/ui/StatCard.jsx';
import Panel from '../components/ui/Panel.jsx';
import SectionTitle from '../components/ui/SectionTitle.jsx';
import RiskBadge from '../components/ui/RiskBadge.jsx';
import CountUp from '../components/ui/CountUp.jsx';
import { TrendArea, AnomalyBar, RegionBars } from '../components/charts/Charts.jsx';
import { MapExplorer, GlobeHero, RiskGauge } from '../components/three/lazy.jsx';
import { tokens } from '../theme.js';
import { formatLakhsToCrore, formatCompact, formatInt } from '../lib/format.js';
import { riskColor } from '../lib/risk.js';

function Canvas3DFallback({ label = 'Loading 3D…' }) {
  return (
    <Box sx={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center' }}>
      <Box sx={{ textAlign: 'center' }}>
        <CircularProgress size={26} />
        <Typography sx={{ mt: 1, fontSize: 11, color: tokens.textDim }}>{label}</Typography>
      </Box>
    </Box>
  );
}

export default function Dashboard() {
  const navigate = useNavigate();
  const { data: n } = useNationalSummary();
  const { data: trends } = useNationalTrends();
  const { data: anomalies } = useAnomalyBreakdown();
  const { data: top } = useTopDistricts(10);
  const { data: geo, isLoading: geoLoading } = useStatesGeo();
  const { data: states } = useStates({});

  const regionData = useMemo(() => {
    if (!states) return [];
    const m = {};
    for (const s of states) m[s.region] = (m[s.region] || 0) + s.total_expenditure_lakhs;
    return Object.entries(m).map(([region, expenditure]) => ({ region, expenditure }))
      .sort((a, b) => b.expenditure - a.expenditure);
  }, [states]);

  return (
    <Box>
      {/* ---- HERO ---- */}
      <Box
        component={motion.div}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.6 }}
        className="glass"
        sx={{
          position: 'relative', overflow: 'hidden', mb: 2.5,
          minHeight: { xs: 340, md: 300 },
          display: 'grid', gridTemplateColumns: { xs: '1fr', md: '1.15fr 1fr' },
        }}
      >
        <Box sx={{ p: { xs: 2.5, md: 4 }, zIndex: 2, display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
          <Chip label="● LIVE · FY 2025–26" size="small" sx={{ width: 'fit-content', mb: 1.5, bgcolor: 'rgba(25,195,125,0.15)', color: tokens.green, fontWeight: 700 }} />
          <Typography sx={{ fontFamily: 'Sora', fontWeight: 800, fontSize: { xs: 26, md: 36 }, lineHeight: 1.08 }}>
            India’s rural employment,{' '}
            <span style={{ background: `linear-gradient(90deg, ${tokens.saffron}, ${tokens.amber})`, WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>
              verified end-to-end
            </span>
          </Typography>
          <Typography sx={{ color: tokens.textDim, mt: 1.2, fontSize: { xs: 13, md: 14.5 }, maxWidth: 520 }}>
            Satellite, payment-network and muster-roll forensics across every state, union
            territory and district — turning {n ? `₹${formatCompact(n.total_expenditure_lakhs * 1e5)}` : '₹1 lakh-crore+'} of
            annual outlay into auditable, fraud-screened spend.
          </Typography>
          <Box sx={{ display: 'flex', gap: 1.5, mt: 2.5, flexWrap: 'wrap' }}>
            <Button variant="contained" endIcon={<MapIcon />} onClick={() => navigate('/states')}
              sx={{ background: `linear-gradient(90deg, ${tokens.saffronDeep}, ${tokens.saffron})`, color: '#1a1205', fontWeight: 700 }}>
              Explore States & UTs
            </Button>
            <Button variant="outlined" endIcon={<ReportProblemIcon />} onClick={() => navigate('/anomalies')}
              sx={{ borderColor: tokens.panelBorder, color: tokens.text }}>
              Review Anomalies
            </Button>
          </Box>
        </Box>
        <Box sx={{ position: 'relative', minHeight: { xs: 220, md: 'auto' } }}>
          <Suspense fallback={<Canvas3DFallback label="Loading globe…" />}>
            <GlobeHero geojson={geo} />
          </Suspense>
        </Box>
      </Box>

      {/* ---- KPI ROW ---- */}
      <Grid container spacing={2} sx={{ mb: 1 }}>
        <Grid item xs={6} md={2.4}>
          <StatCard index={0} label="Total Outlay" rawValue={n?.total_expenditure_lakhs || 0}
            format={(v) => formatLakhsToCrore(v)} icon={<AccountBalanceIcon fontSize="small" />}
            color={tokens.blue} delta={11.4} sub="vs last FY" />
        </Grid>
        <Grid item xs={6} md={2.4}>
          <StatCard index={1} label="Person-Days" rawValue={n?.person_days || 0}
            format={(v) => `${(v / 1e7).toFixed(1)} Cr`} icon={<GroupsIcon fontSize="small" />}
            color={tokens.green} delta={6.2} sub="generated" />
        </Grid>
        <Grid item xs={6} md={2.4}>
          <StatCard index={2} label="Active Works" rawValue={n?.total_works || 0}
            format={(v) => formatCompact(v)} icon={<EngineeringIcon fontSize="small" />}
            color={tokens.saffron} delta={8.7} sub="nationwide" />
        </Grid>
        <Grid item xs={6} md={2.4}>
          <StatCard index={3} label="Flagged Anomalies" rawValue={n?.flagged_count || 0}
            format={(v) => formatInt(v)} icon={<ReportProblemIcon fontSize="small" />}
            color={tokens.red} delta={23.5} deltaPositiveIsGood={false} sub="under review" />
        </Grid>
        <Grid item xs={12} md={2.4}>
          <StatCard index={4} label="Est. Leakage Averted" rawValue={n?.estimated_leakage_lakhs || 0}
            format={(v) => formatLakhsToCrore(v)} icon={<SavingsIcon fontSize="small" />}
            color={tokens.cyan} delta={-4.1} deltaPositiveIsGood={false} sub="flagged value" />
        </Grid>
      </Grid>

      {/* ---- MAP + SIDE ---- */}
      <Grid container spacing={2} sx={{ mt: 0.5 }}>
        <Grid item xs={12} lg={8}>
          <Panel title="National Risk Map" subtitle="All 28 states & 8 UTs · height = composite fraud-risk · click to drill in" noPad
            sx={{ minHeight: { xs: 380, md: 540 } }} bodySx={{ p: 0 }}>
            <Box sx={{ position: 'relative', height: { xs: 360, md: 500 } }}>
              <Suspense fallback={<Canvas3DFallback />}>
                <MapExplorer
                  geojson={geo}
                  loading={geoLoading}
                  onSelect={(f) => navigate(`/states/${f.properties.state_code}`)}
                />
              </Suspense>
            </Box>
          </Panel>
        </Grid>
        <Grid item xs={12} lg={4}>
          <Grid container spacing={2} sx={{ height: '100%' }}>
            <Grid item xs={12} sm={6} lg={12}>
              <Panel title="National Composite Risk" subtitle="expenditure-weighted">
                <Box sx={{ position: 'relative', height: 170 }}>
                  <Suspense fallback={<Canvas3DFallback label="" />}>
                    <RiskGauge score={n?.risk_score || 0} />
                  </Suspense>
                </Box>
              </Panel>
            </Grid>
            <Grid item xs={12} sm={6} lg={12}>
              <Panel title="Highest-Risk Districts" subtitle="top 10 nationwide" bodySx={{ p: 1 }}>
                <List dense sx={{ py: 0 }}>
                  {(top || []).map((d, i) => (
                    <ListItemButton key={d.id} onClick={() => navigate(`/districts/${d.id}`)}
                      sx={{ borderRadius: 2, py: 0.6 }}>
                      <Typography sx={{ width: 22, color: tokens.textDim, fontSize: 12, fontWeight: 700 }}>{i + 1}</Typography>
                      <Box sx={{ flex: 1, minWidth: 0 }}>
                        <Typography noWrap sx={{ fontSize: 13, fontWeight: 600 }}>{d.district_name}</Typography>
                        <Typography noWrap sx={{ fontSize: 11, color: tokens.textDim }}>{d.state_name}</Typography>
                      </Box>
                      <Box sx={{ textAlign: 'right' }}>
                        <Typography sx={{ fontSize: 13, fontWeight: 800, color: riskColor(d.risk_score) }}>{d.risk_score}</Typography>
                        <Typography sx={{ fontSize: 10, color: tokens.textDim }}>{formatLakhsToCrore(d.estimated_leakage_lakhs)}</Typography>
                      </Box>
                    </ListItemButton>
                  ))}
                </List>
              </Panel>
            </Grid>
          </Grid>
        </Grid>
      </Grid>

      {/* ---- CHARTS ---- */}
      <Grid container spacing={2} sx={{ mt: 0.5 }}>
        <Grid item xs={12} md={7}>
          <Panel title="Anomaly Detection Trend" subtitle="detected vs resolved · last 12 months">
            <Box sx={{ height: 260 }}>{trends && <TrendArea data={trends} />}</Box>
          </Panel>
        </Grid>
        <Grid item xs={12} md={5}>
          <Panel title="Anomalies by Type" subtitle="national, with est. rupee impact">
            <Box sx={{ height: 260 }}>{anomalies && <AnomalyBar data={anomalies} />}</Box>
          </Panel>
        </Grid>
        <Grid item xs={12}>
          <Panel title="Outlay by Region" subtitle="aggregated across states & UTs">
            <Box sx={{ height: 220 }}>{regionData.length > 0 && <RegionBars data={regionData} />}</Box>
          </Panel>
        </Grid>
      </Grid>
    </Box>
  );
}
