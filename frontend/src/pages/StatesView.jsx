import React, { Suspense, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Box, Grid, Typography, TextField, MenuItem, ToggleButtonGroup, ToggleButton,
  InputAdornment, Card, LinearProgress, CircularProgress,
} from '@mui/material';
import SearchIcon from '@mui/icons-material/Search';
import PublicIcon from '@mui/icons-material/Public';
import { motion } from 'framer-motion';
import { useStates, useStatesGeo } from '../hooks/useData.js';
import Panel from '../components/ui/Panel.jsx';
import SectionTitle from '../components/ui/SectionTitle.jsx';
import RiskBadge from '../components/ui/RiskBadge.jsx';
import { MapExplorer } from '../components/three/lazy.jsx';
import { tokens } from '../theme.js';
import { formatLakhsToCrore, formatCompact } from '../lib/format.js';
import { riskColor } from '../lib/risk.js';

const REGIONS = ['All', 'North', 'South', 'East', 'West', 'Central', 'Northeast'];

const MCard = motion(Card);

function StateCard({ s, index, onClick }) {
  const c = riskColor(s.risk_score);
  return (
    <MCard
      initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: Math.min(index * 0.03, 0.4) }}
      whileHover={{ y: -4 }} onClick={onClick}
      sx={{ p: 2, cursor: 'pointer', height: '100%', position: 'relative', overflow: 'hidden' }}
    >
      <Box sx={{ position: 'absolute', top: 0, left: 0, bottom: 0, width: 4, background: c }} />
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', mb: 1, pl: 0.5 }}>
        <Box sx={{ minWidth: 0 }}>
          <Typography noWrap sx={{ fontFamily: 'Sora', fontWeight: 700, fontSize: 15 }}>{s.state_name}</Typography>
          <Typography sx={{ fontSize: 11, color: tokens.textDim }}>{s.state_type} · {s.region} · {s.total_districts} dist.</Typography>
        </Box>
        <RiskBadge score={s.risk_score} band={s.risk_band} />
      </Box>
      <Box sx={{ display: 'flex', gap: 2, pl: 0.5, mt: 1.2 }}>
        <Box>
          <Typography sx={{ fontSize: 10, color: tokens.textDim }}>OUTLAY</Typography>
          <Typography sx={{ fontWeight: 700, fontSize: 13.5 }}>{formatLakhsToCrore(s.total_expenditure_lakhs)}</Typography>
        </Box>
        <Box>
          <Typography sx={{ fontSize: 10, color: tokens.textDim }}>WORKS</Typography>
          <Typography sx={{ fontWeight: 700, fontSize: 13.5 }}>{formatCompact(s.total_works)}</Typography>
        </Box>
        <Box>
          <Typography sx={{ fontSize: 10, color: tokens.textDim }}>FLAGGED</Typography>
          <Typography sx={{ fontWeight: 700, fontSize: 13.5, color: tokens.red }}>{formatCompact(s.flagged_count)}</Typography>
        </Box>
      </Box>
      <LinearProgress variant="determinate" value={s.risk_score}
        sx={{ mt: 1.5, height: 5, borderRadius: 3, bgcolor: 'rgba(255,255,255,0.06)', '& .MuiLinearProgress-bar': { background: c } }} />
    </MCard>
  );
}

export default function StatesView() {
  const navigate = useNavigate();
  const { data: states, isLoading } = useStates({});
  const { data: geo, isLoading: geoLoading } = useStatesGeo();
  const [region, setRegion] = useState('All');
  const [type, setType] = useState('All');
  const [search, setSearch] = useState('');
  const [sortBy, setSortBy] = useState('risk_score');

  const filtered = useMemo(() => {
    let rows = states ? [...states] : [];
    if (region !== 'All') rows = rows.filter((s) => s.region === region);
    if (type !== 'All') rows = rows.filter((s) => s.state_type === type);
    if (search) rows = rows.filter((s) => s.state_name.toLowerCase().includes(search.toLowerCase()));
    rows.sort((a, b) => (sortBy === 'state_name'
      ? a.state_name.localeCompare(b.state_name)
      : (b[sortBy] || 0) - (a[sortBy] || 0)));
    return rows;
  }, [states, region, type, search, sortBy]);

  return (
    <Box>
      <SectionTitle icon={<PublicIcon fontSize="small" />} title="States & Union Territories"
        subtitle="28 states · 8 UTs · interactive national risk map" />

      <Panel noPad sx={{ mb: 2.5 }} bodySx={{ p: 0 }}>
        <Box sx={{ position: 'relative', height: { xs: 320, md: 460 } }}>
          <Suspense fallback={null}>
            <MapExplorer geojson={geo} loading={geoLoading}
              onSelect={(f) => navigate(`/states/${f.properties.state_code}`)} />
          </Suspense>
        </Box>
      </Panel>

      {/* Filters */}
      <Box sx={{ display: 'flex', gap: 1.5, flexWrap: 'wrap', mb: 2, alignItems: 'center' }}>
        <TextField size="small" placeholder="Search state / UT…" value={search}
          onChange={(e) => setSearch(e.target.value)}
          InputProps={{ startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> }}
          sx={{ minWidth: 200 }} />
        <TextField size="small" select label="Region" value={region} onChange={(e) => setRegion(e.target.value)} sx={{ minWidth: 130 }}>
          {REGIONS.map((r) => <MenuItem key={r} value={r}>{r}</MenuItem>)}
        </TextField>
        <TextField size="small" select label="Sort by" value={sortBy} onChange={(e) => setSortBy(e.target.value)} sx={{ minWidth: 150 }}>
          <MenuItem value="risk_score">Risk score</MenuItem>
          <MenuItem value="total_expenditure_lakhs">Outlay</MenuItem>
          <MenuItem value="total_works">Works</MenuItem>
          <MenuItem value="flagged_count">Flagged</MenuItem>
          <MenuItem value="state_name">Name</MenuItem>
        </TextField>
        <ToggleButtonGroup size="small" exclusive value={type} onChange={(e, v) => v && setType(v)}>
          <ToggleButton value="All">All</ToggleButton>
          <ToggleButton value="State">States</ToggleButton>
          <ToggleButton value="UT">UTs</ToggleButton>
        </ToggleButtonGroup>
        <Box sx={{ flex: 1 }} />
        <Typography sx={{ fontSize: 12.5, color: tokens.textDim }}>{filtered.length} shown</Typography>
      </Box>

      {isLoading && <LinearProgress />}
      <Grid container spacing={2}>
        {filtered.map((s, i) => (
          <Grid item xs={12} sm={6} md={4} lg={3} key={s.id}>
            <StateCard s={s} index={i} onClick={() => navigate(`/states/${s.state_code}`)} />
          </Grid>
        ))}
      </Grid>
    </Box>
  );
}
