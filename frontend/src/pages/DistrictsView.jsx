import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Box, Typography, TextField, MenuItem, InputAdornment, Table, TableBody,
  TableCell, TableHead, TableRow, TableContainer, TablePagination, LinearProgress, Chip,
} from '@mui/material';
import SearchIcon from '@mui/icons-material/Search';
import LocationCityIcon from '@mui/icons-material/LocationCity';
import { useDistricts } from '../hooks/useData.js';
import Panel from '../components/ui/Panel.jsx';
import SectionTitle from '../components/ui/SectionTitle.jsx';
import RiskBadge from '../components/ui/RiskBadge.jsx';
import { tokens } from '../theme.js';
import { formatLakhsToCrore, formatInt, formatPct } from '../lib/format.js';

const REGIONS = ['All', 'North', 'South', 'East', 'West', 'Central', 'Northeast'];
const BANDS = ['All', 'critical', 'high', 'medium', 'low'];

export default function DistrictsView() {
  const navigate = useNavigate();
  const [search, setSearch] = useState('');
  const [region, setRegion] = useState('All');
  const [band, setBand] = useState('All');
  const [sortBy, setSortBy] = useState('risk_score');
  const [page, setPage] = useState(0);
  const [rpp, setRpp] = useState(25);

  const params = {
    skip: page * rpp,
    limit: rpp,
    sort_by: sortBy,
    order: sortBy === 'district_name' ? 'asc' : 'desc',
    ...(search ? { search } : {}),
    ...(region !== 'All' ? { region } : {}),
    ...(band !== 'All' ? { risk_band: band } : {}),
  };
  const { data, isLoading, isFetching } = useDistricts(params);

  const reset = () => setPage(0);

  return (
    <Box>
      <SectionTitle icon={<LocationCityIcon fontSize="small" />} title="All-India Districts"
        subtitle="Every MGNREGA district across India · search, filter and drill into any case file" />

      <Box sx={{ display: 'flex', gap: 1.5, flexWrap: 'wrap', mb: 2, alignItems: 'center' }}>
        <TextField size="small" placeholder="Search district or state…" value={search}
          onChange={(e) => { setSearch(e.target.value); reset(); }}
          InputProps={{ startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> }}
          sx={{ minWidth: 240 }} />
        <TextField size="small" select label="Region" value={region} onChange={(e) => { setRegion(e.target.value); reset(); }} sx={{ minWidth: 130 }}>
          {REGIONS.map((r) => <MenuItem key={r} value={r}>{r}</MenuItem>)}
        </TextField>
        <TextField size="small" select label="Risk band" value={band} onChange={(e) => { setBand(e.target.value); reset(); }} sx={{ minWidth: 130 }}>
          {BANDS.map((b) => <MenuItem key={b} value={b} sx={{ textTransform: 'capitalize' }}>{b}</MenuItem>)}
        </TextField>
        <TextField size="small" select label="Sort by" value={sortBy} onChange={(e) => { setSortBy(e.target.value); reset(); }} sx={{ minWidth: 150 }}>
          <MenuItem value="risk_score">Risk score</MenuItem>
          <MenuItem value="total_expenditure_lakhs">Outlay</MenuItem>
          <MenuItem value="flagged_count">Flagged</MenuItem>
          <MenuItem value="estimated_leakage_lakhs">Est. leakage</MenuItem>
          <MenuItem value="district_name">Name</MenuItem>
        </TextField>
      </Box>

      <Panel noPad bodySx={{ p: 0 }}>
        {(isLoading || isFetching) && <LinearProgress />}
        <TableContainer sx={{ maxHeight: 640 }}>
          <Table stickyHeader size="small">
            <TableHead>
              <TableRow>
                {['District', 'State / UT', 'Risk', 'Outlay', 'Works', 'Flagged', 'Est. Leakage', 'Completion'].map((h) => (
                  <TableCell key={h} sx={{ bgcolor: '#0c1330', color: tokens.textDim, fontSize: 11, textTransform: 'uppercase', fontWeight: 700 }}>{h}</TableCell>
                ))}
              </TableRow>
            </TableHead>
            <TableBody>
              {(data?.data || []).map((d) => (
                <TableRow key={d.id} hover sx={{ cursor: 'pointer' }} onClick={() => navigate(`/districts/${d.id}`)}>
                  <TableCell>
                    <Typography sx={{ fontSize: 13.5, fontWeight: 600 }}>{d.district_name}</Typography>
                    {!d.mgnrega_active && <Chip label="Urban · N/A" size="small" sx={{ height: 18, fontSize: 9.5 }} />}
                  </TableCell>
                  <TableCell sx={{ fontSize: 13, color: tokens.textDim }}>{d.state_name}</TableCell>
                  <TableCell><RiskBadge score={d.risk_score} band={d.risk_band} /></TableCell>
                  <TableCell sx={{ fontSize: 13 }}>{formatLakhsToCrore(d.total_expenditure_lakhs)}</TableCell>
                  <TableCell sx={{ fontSize: 13 }}>{formatInt(d.total_works)}</TableCell>
                  <TableCell sx={{ fontSize: 13, color: tokens.red, fontWeight: 600 }}>{formatInt(d.flagged_count)}</TableCell>
                  <TableCell sx={{ fontSize: 13, color: tokens.amber }}>{formatLakhsToCrore(d.estimated_leakage_lakhs)}</TableCell>
                  <TableCell sx={{ fontSize: 13 }}>{formatPct(d.completion_rate_pct)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
        <TablePagination
          component="div"
          count={data?.total || 0}
          page={page}
          onPageChange={(e, p) => setPage(p)}
          rowsPerPage={rpp}
          onRowsPerPageChange={(e) => { setRpp(parseInt(e.target.value, 10)); reset(); }}
          rowsPerPageOptions={[25, 50, 100]}
          sx={{ color: tokens.textDim }}
        />
      </Panel>
    </Box>
  );
}
