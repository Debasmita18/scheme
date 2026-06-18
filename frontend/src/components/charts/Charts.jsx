import React from 'react';
import {
  ResponsiveContainer, AreaChart, Area, LineChart, Line, BarChart, Bar,
  PieChart, Pie, Cell, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
} from 'recharts';
import { tokens } from '../../theme.js';
import { formatInt, formatLakhsToCrore, titleCase } from '../../lib/format.js';

const AXIS = { fontSize: 11, fill: tokens.textDim };
const GRID = 'rgba(126,150,220,0.12)';
const TOOLTIP_STYLE = {
  background: '#0a1130',
  border: `1px solid ${tokens.panelBorder}`,
  borderRadius: 10,
  fontSize: 12,
};
export const CATEGORY_COLORS = [
  '#4f8cff', '#ff9d2e', '#19c37d', '#ff5470', '#a78bfa',
  '#34d6e8', '#ffc24b', '#f472b6', '#5eead4', '#fb923c',
];

export function TrendArea({ data }) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart data={data} margin={{ top: 8, right: 10, left: -12, bottom: 0 }}>
        <defs>
          <linearGradient id="gDet" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={tokens.red} stopOpacity={0.5} />
            <stop offset="100%" stopColor={tokens.red} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke={GRID} vertical={false} />
        <XAxis dataKey="month" tick={AXIS} tickLine={false} axisLine={false} />
        <YAxis tick={AXIS} tickLine={false} axisLine={false} width={40} />
        <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v, n) => [formatInt(v), titleCase(n)]} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Area type="monotone" dataKey="detected" stroke={tokens.red} fill="url(#gDet)" strokeWidth={2} name="Detected" />
        <Line type="monotone" dataKey="resolved" stroke={tokens.green} strokeWidth={2} dot={false} name="Resolved" />
        <Line type="monotone" dataKey="pending" stroke={tokens.amber} strokeWidth={2} strokeDasharray="5 4" dot={false} name="Pending" />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function AnomalyBar({ data }) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={data} layout="vertical" margin={{ top: 4, right: 16, left: 8, bottom: 0 }}>
        <CartesianGrid stroke={GRID} horizontal={false} />
        <XAxis type="number" tick={AXIS} tickLine={false} axisLine={false} />
        <YAxis type="category" dataKey="type" tick={{ ...AXIS, fontSize: 10.5 }} width={120} tickLine={false} axisLine={false} />
        <Tooltip
          contentStyle={TOOLTIP_STYLE}
          formatter={(v, n, p) => [`${formatInt(v)} cases · ${formatLakhsToCrore(p.payload.estimated_amount_lakhs)}`, 'Impact']}
        />
        <Bar dataKey="count" radius={[0, 5, 5, 0]} name="Cases">
          {data.map((_, i) => <Cell key={i} fill={CATEGORY_COLORS[i % CATEGORY_COLORS.length]} />)}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

export function WorksDonut({ worksByType }) {
  const data = Object.entries(worksByType || {}).map(([name, value]) => ({ name, value }));
  return (
    <ResponsiveContainer width="100%" height="100%">
      <PieChart>
        <Pie
          data={data} dataKey="value" nameKey="name" innerRadius="55%" outerRadius="82%"
          paddingAngle={2} stroke="none"
        >
          {data.map((_, i) => <Cell key={i} fill={CATEGORY_COLORS[i % CATEGORY_COLORS.length]} />)}
        </Pie>
        <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v, n) => [formatInt(v), n]} />
        <Legend wrapperStyle={{ fontSize: 10.5 }} iconSize={9} />
      </PieChart>
    </ResponsiveContainer>
  );
}

export function RegionBars({ data }) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={data} margin={{ top: 4, right: 10, left: -10, bottom: 0 }}>
        <CartesianGrid stroke={GRID} vertical={false} />
        <XAxis dataKey="region" tick={AXIS} tickLine={false} axisLine={false} />
        <YAxis tick={AXIS} tickLine={false} axisLine={false} width={48} />
        <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v) => formatLakhsToCrore(v)} />
        <Bar dataKey="expenditure" radius={[5, 5, 0, 0]} name="Outlay">
          {data.map((_, i) => <Cell key={i} fill={CATEGORY_COLORS[i % CATEGORY_COLORS.length]} />)}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
