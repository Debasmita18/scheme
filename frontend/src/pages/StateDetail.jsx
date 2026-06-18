import React, { Suspense, useMemo, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Box, Grid, Typography, Button, IconButton, Table, TableBody, TableCell,
  TableHead, TableRow, TableContainer, Chip, LinearProgress, TextField, InputAdornment,
} from '@mui/material';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import SearchIcon from '@mui/icons-material/Search';
import { useStateDetail, useDistrictsGeo } from '../hooks/useData.js';
import Panel from '../components/ui/Panel.jsx';
import RiskBadge from '../components/ui/RiskBadge.jsx';
import StatCard from '../components/ui/StatCard.jsx';
import { WorksDonut } from '../components/charts/Charts.jsx';
import { MapExplorer } from '../components/three/lazy.jsx';
import { tokens } from '../theme.js';
import { formatLakhsToCrore, formatCompact, formatInt, formatPct } from '../lib/format.js';
import { riskColor } from '../lib/risk.js';
import AccountBalanceIcon from '@mui/icons-material/AccountBalance';
import GroupsIcon from '@mui/icons-material/Groups';
import EngineeringIcon from '@mui/icons-material/Engineering';
import ReportProblemIcon from '@mui/icons-material/ReportProblem';

export default function StateDetail() {
  const { code } = useParams();
  const navigate = useNavigate();
  const { data: state, isLoading } = useStateDetail(code);
  const { data: geo, isLoading: geoLoading } = useDistrictsGeo(code);
  const [q, setQ] = useState('');

  const districts = useMemo(() => {
    const rows = state?.districts ? [...state.districts] : [];
    const f = q ? rows.filter((d) => d.district_name.toLowerCase().includes(q.toLowerCase())) : rows;
    return f.sort((a, b) => (b.risk_score || 0) - (a.risk_score || 0));
  }, [state, q]);

  if (isLoading || !state) return <LinearProgress />;

  return (
    <Box>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mb: 2, flexWrap: 'wrap' }}>
        <IconButton onClick={() => navigate('/states')} sx={{ border: `1px solid ${tokens.panelBorder}` }}>
          <ArrowBackIcon />
        </IconButton>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography sx={{ fontFamily: 'Sora', fontWeight: 800, fontSize: { xs: 22, md: 28 } }}>{state.state_name}</Typography>
          <Typography sx={{ fontSize: 12.5, color: tokens.textDim }}>
            {state.state_type} · {state.region} region · {state.total_districts} districts · {formatInt(state.total_panchayats)} gram panchayats
          </Typography>
        </Box>
        <RiskBadge score={state.risk_score} band={state.risk_band} size="medium" />
      </Box>

      <Grid container spacing={2} sx={{ mb: 1 }}>
        <Grid item xs={6} md={3}>
          <StatCard index={0} label="Outlay" rawValue={state.total_expenditure_lakhs} format={formatLakhsToCrore} icon={<AccountBalanceIcon fontSize="small" />} color={tokens.blue} />
        </Grid>
        <Grid item xs={6} md={3}>
          <StatCard index={1} label="Person-Days" rawValue={state.person_days} format={(v) => `${(v / 1e7).toFixed(2)} Cr`} icon={<GroupsIcon fontSize="small" />} color={tokens.green} />
        </Grid>
        <Grid item xs={6} md={3}>
          <StatCard index={2} label="Works" rawValue={state.total_works} format={formatCompact} icon={<EngineeringIcon fontSize="small" />} color={tokens.saffron} />
        </Grid>
        <Grid item xs={6} md={3}>
          <StatCard index={3} label="Flagged" rawValue={state.flagged_count} format={formatInt} icon={<ReportProblemIcon fontSize="small" />} color={tokens.red} />
        </Grid>
      </Grid>

      <Grid container spacing={2} sx={{ mt: 0.5 }}>
        <Grid item xs={12} lg={8}>
          <Panel title="District Risk Map" subtitle="height = composite risk · click a district for the case file" noPad sx={{ minHeight: 440 }} bodySx={{ p: 0 }}>
            <Box sx={{ position: 'relative', height: 420 }}>
              <Suspense fallback={null}>
                <MapExplorer geojson={geo} loading={geoLoading} heightScale={1.4}
                  hint="Drag to orbit · click a district"
                  onSelect={(f) => navigate(`/districts/${f.properties.id}`)} />
              </Suspense>
            </Box>
          </Panel>
        </Grid>
        <Grid item xs={12} lg={4}>
          <Panel title="Works by Category" subtitle="permissible-works mix" sx={{ height: '100%' }}>
            <Box sx={{ height: 360 }}><WorksDonut worksByType={state.works_by_type} /></Box>
          </Panel>
        </Grid>
      </Grid>

      <Panel title="Districts" subtitle={`${districts.length} districts`} sx={{ mt: 2 }}
        action={
          <TextField size="small" placeholder="Search district…" value={q} onChange={(e) => setQ(e.target.value)}
            InputProps={{ startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> }} />
        }>
        <TableContainer sx={{ maxHeight: 480 }}>
          <Table stickyHeader size="small">
            <TableHead>
              <TableRow>
                {['District', 'Risk', 'Outlay', 'Works', 'Flagged', 'Completion'].map((h) => (
                  <TableCell key={h} sx={{ bgcolor: '#0c1330', color: tokens.textDim, fontSize: 11, textTransform: 'uppercase', fontWeight: 700 }}>{h}</TableCell>
                ))}
              </TableRow>
            </TableHead>
            <TableBody>
              {districts.map((d) => (
                <TableRow key={d.id} hover sx={{ cursor: 'pointer' }} onClick={() => navigate(`/districts/${d.id}`)}>
                  <TableCell>
                    <Typography sx={{ fontSize: 13.5, fontWeight: 600 }}>{d.district_name}</Typography>
                    {!d.mgnrega_active && <Chip label="Urban · N/A" size="small" sx={{ height: 18, fontSize: 9.5 }} />}
                  </TableCell>
                  <TableCell><RiskBadge score={d.risk_score} band={d.risk_band} /></TableCell>
                  <TableCell sx={{ fontSize: 13 }}>{formatLakhsToCrore(d.total_expenditure_lakhs)}</TableCell>
                  <TableCell sx={{ fontSize: 13 }}>{formatInt(d.total_works)}</TableCell>
                  <TableCell sx={{ fontSize: 13, color: tokens.red, fontWeight: 600 }}>{formatInt(d.flagged_count)}</TableCell>
                  <TableCell sx={{ fontSize: 13 }}>{formatPct(d.completion_rate_pct)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      </Panel>
    </Box>
  );
}
