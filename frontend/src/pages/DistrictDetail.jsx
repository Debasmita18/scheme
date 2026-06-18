import React, { Suspense, useMemo, lazy } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Box, Grid, Typography, IconButton, LinearProgress, Divider, Chip,
} from '@mui/material';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import AccountBalanceIcon from '@mui/icons-material/AccountBalance';
import GroupsIcon from '@mui/icons-material/Groups';
import EngineeringIcon from '@mui/icons-material/Engineering';
import ReportProblemIcon from '@mui/icons-material/ReportProblem';
import SavingsIcon from '@mui/icons-material/Savings';
import HomeWorkIcon from '@mui/icons-material/HomeWork';
import DescriptionIcon from '@mui/icons-material/Description';
import { useDistrictDetail, useDistrictHeatmap } from '../hooks/useData.js';
import { generateCaseFile } from '../lib/api.js';
import Panel from '../components/ui/Panel.jsx';
import StatCard from '../components/ui/StatCard.jsx';
import RiskBadge from '../components/ui/RiskBadge.jsx';
import GenerateButton from '../components/ui/GenerateButton.jsx';
import { WorksDonut, AnomalyBar } from '../components/charts/Charts.jsx';
import { RiskGauge } from '../components/three/lazy.jsx';
import { tokens } from '../theme.js';
import { formatLakhsToCrore, formatInt, formatPct } from '../lib/format.js';

const DistrictHeatMap = lazy(() => import('../components/maps/DistrictHeatMap.jsx'));

function MetricRow({ label, value }) {
  return (
    <Box sx={{ display: 'flex', justifyContent: 'space-between', py: 0.7 }}>
      <Typography sx={{ fontSize: 12.5, color: tokens.textDim }}>{label}</Typography>
      <Typography sx={{ fontSize: 13, fontWeight: 600 }}>{value}</Typography>
    </Box>
  );
}

export default function DistrictDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { data: d, isLoading } = useDistrictDetail(id);
  const { data: points } = useDistrictHeatmap(id);

  const anomalyData = useMemo(() => {
    if (!d?.anomaly_by_type) return [];
    const total = Object.values(d.anomaly_by_type).reduce((a, b) => a + b, 0) || 1;
    return Object.entries(d.anomaly_by_type)
      .map(([type, count]) => ({ type, count, estimated_amount_lakhs: (d.estimated_leakage_lakhs * count) / total }))
      .sort((a, b) => b.count - a.count);
  }, [d]);

  if (isLoading || !d) return <LinearProgress />;

  return (
    <Box>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mb: 2, flexWrap: 'wrap' }}>
        <IconButton onClick={() => navigate(`/states/${d.state_code}`)} sx={{ border: `1px solid ${tokens.panelBorder}` }}>
          <ArrowBackIcon />
        </IconButton>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography sx={{ fontFamily: 'Sora', fontWeight: 800, fontSize: { xs: 22, md: 28 } }}>{d.district_name}</Typography>
          <Typography sx={{ fontSize: 12.5, color: tokens.textDim }}>
            {d.state_name} · {d.region} region · {formatInt(d.total_blocks)} blocks · {formatInt(d.total_panchayats)} GPs
          </Typography>
        </Box>
        <RiskBadge score={d.risk_score} band={d.risk_band} size="medium" />
        <GenerateButton
          label="Generate Case File"
          icon={<DescriptionIcon />}
          variant="contained"
          title={`Compiling case file · ${d.district_name}`}
          doneMessage={`Case file for ${d.district_name} ready`}
          task={() => generateCaseFile(d.id)}
          sx={{ background: `linear-gradient(90deg, ${tokens.saffronDeep}, ${tokens.saffron})`, color: '#1a1205', fontWeight: 700 }}
        />
      </Box>

      {!d.mgnrega_active && (
        <Chip label="Fully urban district — MGNREGA not implemented" sx={{ mb: 2, bgcolor: 'rgba(90,104,144,0.2)', color: tokens.textDim }} />
      )}

      <Grid container spacing={2} sx={{ mb: 1 }}>
        <Grid item xs={6} md={2}><StatCard index={0} label="Outlay" rawValue={d.total_expenditure_lakhs} format={formatLakhsToCrore} icon={<AccountBalanceIcon fontSize="small" />} color={tokens.blue} /></Grid>
        <Grid item xs={6} md={2}><StatCard index={1} label="Person-Days" rawValue={d.person_days} format={(v) => `${(v / 1e5).toFixed(1)} L`} icon={<GroupsIcon fontSize="small" />} color={tokens.green} /></Grid>
        <Grid item xs={6} md={2}><StatCard index={2} label="Works" rawValue={d.total_works} format={formatInt} icon={<EngineeringIcon fontSize="small" />} color={tokens.saffron} /></Grid>
        <Grid item xs={6} md={2}><StatCard index={3} label="Households" rawValue={d.total_households} format={formatInt} icon={<HomeWorkIcon fontSize="small" />} color={tokens.cyan} /></Grid>
        <Grid item xs={6} md={2}><StatCard index={4} label="Flagged" rawValue={d.flagged_count} format={formatInt} icon={<ReportProblemIcon fontSize="small" />} color={tokens.red} /></Grid>
        <Grid item xs={6} md={2}><StatCard index={5} label="Est. Leakage" rawValue={d.estimated_leakage_lakhs} format={formatLakhsToCrore} icon={<SavingsIcon fontSize="small" />} color={tokens.amber} /></Grid>
      </Grid>

      <Grid container spacing={2} sx={{ mt: 0.5 }}>
        <Grid item xs={12} md={8}>
          <Panel title="Gram Panchayat Risk Heatmap" subtitle="GP-level risk concentration" noPad sx={{ minHeight: 380 }} bodySx={{ p: 0 }}>
            <Box sx={{ position: 'relative', height: 360, borderRadius: 3, overflow: 'hidden' }}>
              <Suspense fallback={null}>
                <DistrictHeatMap center={[d.lat, d.lng]} points={points || []} />
              </Suspense>
            </Box>
          </Panel>
        </Grid>
        <Grid item xs={12} md={4}>
          <Panel title="Composite Risk">
            <Box sx={{ position: 'relative', height: 150 }}>
              <Suspense fallback={null}><RiskGauge score={d.risk_score} /></Suspense>
            </Box>
            <Divider sx={{ my: 1 }} />
            <MetricRow label="Avg wage rate" value={`₹${d.avg_wage_rate}/day`} />
            <MetricRow label="Avg days / household" value={formatInt(d.avg_days_per_household)} />
            <MetricRow label="Women participation" value={formatPct(d.women_participation_pct)} />
            <MetricRow label="SC/ST participation" value={formatPct(d.scst_participation_pct)} />
            <MetricRow label="Work completion" value={formatPct(d.completion_rate_pct)} />
            <MetricRow label="Verified works" value={formatInt(d.verified_count)} />
          </Panel>
        </Grid>
      </Grid>

      <Grid container spacing={2} sx={{ mt: 0.5 }}>
        <Grid item xs={12} md={5}>
          <Panel title="Works by Category">
            <Box sx={{ height: 300 }}><WorksDonut worksByType={d.works_by_type} /></Box>
          </Panel>
        </Grid>
        <Grid item xs={12} md={7}>
          <Panel title="Detected Anomalies by Type" subtitle="with estimated rupee impact">
            <Box sx={{ height: 300 }}>{anomalyData.length > 0 && <AnomalyBar data={anomalyData} />}</Box>
          </Panel>
        </Grid>
      </Grid>
    </Box>
  );
}
