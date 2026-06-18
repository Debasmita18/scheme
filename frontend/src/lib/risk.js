import { tokens } from '../theme.js';

export const RISK_COLORS = tokens.risk;

export function riskBand(score) {
  if (score == null) return 'inactive';
  if (score >= 75) return 'critical';
  if (score >= 55) return 'high';
  if (score >= 35) return 'medium';
  return 'low';
}

export function riskColor(scoreOrBand) {
  const band =
    typeof scoreOrBand === 'string' ? scoreOrBand : riskBand(scoreOrBand);
  return RISK_COLORS[band] || RISK_COLORS.medium;
}

export const RISK_LABEL = {
  critical: 'Critical',
  high: 'High',
  medium: 'Moderate',
  low: 'Low',
  inactive: 'N/A (Urban)',
};
