// Indian-format number / currency helpers.

const inGrouping = new Intl.NumberFormat('en-IN');

export function formatInt(n) {
  if (n == null || isNaN(n)) return '—';
  return inGrouping.format(Math.round(n));
}

export function formatCompact(n) {
  if (n == null || isNaN(n)) return '—';
  const abs = Math.abs(n);
  if (abs >= 1e7) return (n / 1e7).toFixed(2) + ' Cr';
  if (abs >= 1e5) return (n / 1e5).toFixed(2) + ' L';
  if (abs >= 1e3) return (n / 1e3).toFixed(1) + 'K';
  return inGrouping.format(Math.round(n));
}

// value is in LAKHS (₹). Render as Cr / Lakh appropriately.
export function formatLakhsToCrore(lakhs) {
  if (lakhs == null || isNaN(lakhs)) return '—';
  const cr = lakhs / 100;
  if (Math.abs(cr) >= 1) return `₹${inGrouping.format(Math.round(cr))} Cr`;
  return `₹${inGrouping.format(Math.round(lakhs))} L`;
}

// Rupees (absolute) -> Indian Cr/Lakh string.
export function formatRupees(value) {
  if (value == null || isNaN(value)) return '—';
  const abs = Math.abs(value);
  if (abs >= 1e7) return `₹${(value / 1e7).toFixed(2)} Cr`;
  if (abs >= 1e5) return `₹${(value / 1e5).toFixed(2)} L`;
  return `₹${inGrouping.format(Math.round(value))}`;
}

export function formatPct(n, digits = 1) {
  if (n == null || isNaN(n)) return '—';
  return `${n.toFixed(digits)}%`;
}

export function titleCase(s = '') {
  return s.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}
