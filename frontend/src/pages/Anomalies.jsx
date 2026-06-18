import React, { useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Box, Grid, Typography, Table, TableBody, TableCell, TableHead, TableRow,
  TableContainer, Chip,
} from '@mui/material';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import ReportProblemIcon from '@mui/icons-material/ReportProblem';
import SavingsIcon from '@mui/icons-material/Savings';
import GppMaybeIcon from '@mui/icons-material/GppMaybe';
import RuleIcon from '@mui/icons-material/Rule';
import {
  useNationalSummary, useAnomalyBreakdown, useNationalTrends, useTopDistricts,
} from '../hooks/useData.js';
import SectionTitle from '../components/ui/SectionTitle.jsx';
import StatCard from '../components/ui/StatCard.jsx';
import Panel from '../components/ui/Panel.jsx';
import RiskBadge from '../components/ui/RiskBadge.jsx';
import { AnomalyBar, TrendArea } from '../components/charts/Charts.jsx';
import { tokens } from '../theme.js';
import { formatInt, formatLakhsToCrore } from '../lib/format.js';
import { riskColor } from '../lib/risk.js';

const STATUS = ['Open', 'Under Review', 'Field Verification', 'Escalated'];

export default function Anomalies() {
  const navigate = useNavigate();
  const { data: n } = useNationalSummary();
  const { data: breakdown } = useAnomalyBreakdown();
  const { data: trends } = useNationalTrends();
  const { data: top } = useTopDistricts(25);

  const cases = useMemo(() => {
    if (!top || !breakdown) return [];
    return top.map((d, i) => {
      const a = breakdown[i % breakdown.length];
      const code = String(d.id || '').replace(/\D/g, '') || String(4500 + i);
      return {
        id: `ANM-26-${code.padStart(4, '0')}`,
        type: a.type,
        district: d.district_name,
        state: d.state_name,
        districtId: d.id,
        risk: d.risk_score,
        amount: d.estimated_leakage_lakhs,
        status: STATUS[i % STATUS.length],
      };
    });
  }, [top, breakdown]);

  const critical = (top || []).filter((d) => d.risk_score >= 75).length;

  return (
    <Box>
      <SectionTitle icon={<WarningAmberIcon fontSize="small" />} title="Anomaly Intelligence"
        subtitle="National fraud-signal detection across satellite, payment and muster-roll forensics" />

      <Grid container spacing={2} sx={{ mb: 1 }}>
        <Grid item xs={6} md={3}><StatCard index={0} label="Total Anomalies" rawValue={n?.anomalies_count || 0} format={formatInt} icon={<ReportProblemIcon fontSize="small" />} color={tokens.red} /></Grid>
        <Grid item xs={6} md={3}><StatCard index={1} label="Flagged Works" rawValue={n?.flagged_count || 0} format={formatInt} icon={<RuleIcon fontSize="small" />} color={tokens.saffron} /></Grid>
        <Grid item xs={6} md={3}><StatCard index={2} label="Est. Leakage" rawValue={n?.estimated_leakage_lakhs || 0} format={formatLakhsToCrore} icon={<SavingsIcon fontSize="small" />} color={tokens.amber} /></Grid>
        <Grid item xs={6} md={3}><StatCard index={3} label="Critical Districts" rawValue={critical} format={formatInt} icon={<GppMaybeIcon fontSize="small" />} color={tokens.cyan} sub="of top 25" /></Grid>
      </Grid>

      <Grid container spacing={2} sx={{ mt: 0.5 }}>
        <Grid item xs={12} md={5}>
          <Panel title="Anomalies by Type"><Box sx={{ height: 280 }}>{breakdown && <AnomalyBar data={breakdown} />}</Box></Panel>
        </Grid>
        <Grid item xs={12} md={7}>
          <Panel title="Detection vs Resolution" subtitle="last 12 months"><Box sx={{ height: 280 }}>{trends && <TrendArea data={trends} />}</Box></Panel>
        </Grid>
      </Grid>

      <Panel title="Active High-Priority Cases" subtitle="auto-prioritised by composite risk × rupee exposure" sx={{ mt: 2 }} noPad bodySx={{ p: 0 }}>
        <TableContainer sx={{ maxHeight: 560 }}>
          <Table stickyHeader size="small">
            <TableHead>
              <TableRow>
                {['Case ID', 'Type', 'Location', 'Risk', 'Exposure', 'Status'].map((h) => (
                  <TableCell key={h} sx={{ bgcolor: '#0c1330', color: tokens.textDim, fontSize: 11, textTransform: 'uppercase', fontWeight: 700 }}>{h}</TableCell>
                ))}
              </TableRow>
            </TableHead>
            <TableBody>
              {cases.map((c) => (
                <TableRow key={c.id} hover sx={{ cursor: 'pointer' }} onClick={() => navigate(`/districts/${c.districtId}`)}>
                  <TableCell sx={{ fontFamily: 'monospace', fontSize: 12.5 }}>{c.id}</TableCell>
                  <TableCell sx={{ fontSize: 13 }}>{c.type}</TableCell>
                  <TableCell sx={{ fontSize: 13 }}>{c.district}<span style={{ color: tokens.textDim }}>, {c.state}</span></TableCell>
                  <TableCell><RiskBadge score={c.risk} /></TableCell>
                  <TableCell sx={{ fontSize: 13, color: tokens.amber, fontWeight: 600 }}>{formatLakhsToCrore(c.amount)}</TableCell>
                  <TableCell><Chip label={c.status} size="small" sx={{ height: 22, fontSize: 11, bgcolor: 'rgba(79,140,255,0.15)', color: tokens.blue }} /></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      </Panel>
    </Box>
  );
}
