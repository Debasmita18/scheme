import React from 'react';
import { Box, Grid, Typography, Card } from '@mui/material';
import DescriptionIcon from '@mui/icons-material/Description';
import GavelIcon from '@mui/icons-material/Gavel';
import SummarizeIcon from '@mui/icons-material/Summarize';
import PublicIcon from '@mui/icons-material/Public';
import InsightsIcon from '@mui/icons-material/Insights';
import DownloadIcon from '@mui/icons-material/Download';
import TranslateIcon from '@mui/icons-material/Translate';
import { motion } from 'framer-motion';
import { useNationalSummary } from '../hooks/useData.js';
import { generateAiReport } from '../lib/api.js';
import SectionTitle from '../components/ui/SectionTitle.jsx';
import Panel from '../components/ui/Panel.jsx';
import GenerateButton from '../components/ui/GenerateButton.jsx';
import { tokens } from '../theme.js';
import { formatLakhsToCrore, formatInt } from '../lib/format.js';

const REPORTS = [
  { icon: <PublicIcon />, color: tokens.blue, kind: 'national-brief', title: 'National Intelligence Brief', desc: 'All-India fraud posture, regional hotspots and leakage estimate.' },
  { icon: <SummarizeIcon />, color: tokens.saffron, kind: 'scorecard', title: 'State Scorecard', desc: 'Per-state ranking, district risk distribution and trend deltas for review meetings.' },
  { icon: <DescriptionIcon />, color: tokens.green, kind: 'audit-pack', title: 'CAG-Format Audit Summary', desc: 'Audit-ready findings with exposure quantification and recommended action.' },
  { icon: <InsightsIcon />, color: tokens.cyan, kind: 'dpc-briefing', title: 'Weekly DPC Briefing', desc: 'Auto-generated briefing for District Programme Coordinators with new flags.' },
  { icon: <GavelIcon />, color: tokens.red, kind: 'audit-pack', title: 'Audit Action Memo', desc: 'Concise memo of the highest-exposure districts and prescribed verification steps.' },
  { icon: <TranslateIcon />, color: tokens.amber, kind: 'national-brief', title: 'Executive One-Pager', desc: 'Single-page summary for senior officials and review meetings.' },
];

const MCard = motion(Card);

export default function Reports() {
  const { data: n } = useNationalSummary();
  return (
    <Box>
      <SectionTitle icon={<DescriptionIcon fontSize="small" />} title="Reports & Audit Packs"
        subtitle="Generate intelligence reports, case files and audit-ready evidence dossiers" />

      <Panel sx={{ mb: 2.5 }}>
        <Grid container spacing={2} alignItems="center">
          <Grid item xs={12} md={8}>
            <Typography sx={{ fontFamily: 'Sora', fontWeight: 700, fontSize: 18 }}>National Leakage Estimate · FY 2025–26</Typography>
            <Typography sx={{ color: tokens.textDim, fontSize: 13, mt: 0.5 }}>
              Across {formatInt(n?.total_districts)} districts in 28 states & 8 UTs, an estimated{' '}
              <b style={{ color: tokens.amber }}>{formatLakhsToCrore(n?.estimated_leakage_lakhs)}</b> of outlay carries
              elevated fraud-risk signals — flagged for verification before wage/material release.
            </Typography>
          </Grid>
          <Grid item xs={12} md={4} sx={{ textAlign: { md: 'right' } }}>
            <GenerateButton
              label="Download National Brief"
              variant="contained"
              icon={<DownloadIcon />}
              title="Compiling National Intelligence Brief"
              doneMessage="National brief generated"
              task={() => generateAiReport('national-brief')}
              sx={{ background: `linear-gradient(90deg, ${tokens.saffronDeep}, ${tokens.saffron})`, color: '#1a1205', fontWeight: 700 }}
            />
          </Grid>
        </Grid>
      </Panel>

      <Grid container spacing={2}>
        {REPORTS.map((r, i) => (
          <Grid item xs={12} sm={6} md={4} key={r.title}>
            <MCard initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.06 }}
              whileHover={{ y: -4 }} sx={{ p: 2.4, height: '100%' }}>
              <Box sx={{ display: 'grid', placeItems: 'center', width: 44, height: 44, borderRadius: 2.5, background: `${r.color}1f`, color: r.color, mb: 1.5 }}>
                {r.icon}
              </Box>
              <Typography sx={{ fontFamily: 'Sora', fontWeight: 700, fontSize: 15.5 }}>{r.title}</Typography>
              <Typography sx={{ color: tokens.textDim, fontSize: 12.5, mt: 0.6, mb: 2, minHeight: 56 }}>{r.desc}</Typography>
              <GenerateButton
                label="Generate"
                fullWidth
                icon={<DownloadIcon />}
                title={`Generating · ${r.title}`}
                doneMessage={`${r.title} generated`}
                task={() => generateAiReport(r.kind)}
                sx={{ borderColor: tokens.panelBorder, color: tokens.text }}
              />
            </MCard>
          </Grid>
        ))}
      </Grid>
    </Box>
  );
}
