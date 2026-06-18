import { createTheme } from '@mui/material/styles';

// India tricolor-inspired, premium dark "command centre" palette.
export const tokens = {
  bg0: '#070b1f',
  bg1: '#0b1330',
  bg2: '#101a40',
  panel: 'rgba(20, 30, 66, 0.55)',
  panelBorder: 'rgba(126, 150, 220, 0.16)',
  saffron: '#ff9d2e',
  saffronDeep: '#ff7a00',
  green: '#19c37d',
  blue: '#4f8cff',
  cyan: '#34d6e8',
  red: '#ff5470',
  amber: '#ffc24b',
  text: '#eaf0ff',
  textDim: '#9aa8cf',
  // risk band colors (shared with 3D map)
  risk: {
    critical: '#ff4d6d',
    high: '#ff8f2e',
    medium: '#ffd152',
    low: '#1fd286',
    inactive: '#5a6890',
  },
};

const theme = createTheme({
  palette: {
    mode: 'dark',
    primary: { main: tokens.blue },
    secondary: { main: tokens.saffron },
    success: { main: tokens.green },
    error: { main: tokens.red },
    warning: { main: tokens.amber },
    background: { default: tokens.bg0, paper: tokens.bg1 },
    text: { primary: tokens.text, secondary: tokens.textDim },
    divider: tokens.panelBorder,
  },
  shape: { borderRadius: 14 },
  typography: {
    fontFamily: '"Inter", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
    h1: { fontFamily: '"Sora", sans-serif', fontWeight: 800, letterSpacing: '-0.02em' },
    h2: { fontFamily: '"Sora", sans-serif', fontWeight: 700, letterSpacing: '-0.02em' },
    h3: { fontFamily: '"Sora", sans-serif', fontWeight: 700, letterSpacing: '-0.01em' },
    h4: { fontFamily: '"Sora", sans-serif', fontWeight: 700 },
    h5: { fontFamily: '"Sora", sans-serif', fontWeight: 600 },
    h6: { fontFamily: '"Sora", sans-serif', fontWeight: 600 },
    button: { textTransform: 'none', fontWeight: 600 },
  },
  components: {
    MuiPaper: {
      styleOverrides: {
        root: {
          backgroundImage: 'none',
          backgroundColor: tokens.panel,
          border: `1px solid ${tokens.panelBorder}`,
          backdropFilter: 'blur(14px)',
          WebkitBackdropFilter: 'blur(14px)',
        },
      },
    },
    MuiCard: {
      styleOverrides: {
        root: {
          backgroundColor: tokens.panel,
          border: `1px solid ${tokens.panelBorder}`,
          backdropFilter: 'blur(14px)',
          WebkitBackdropFilter: 'blur(14px)',
          backgroundImage: 'none',
          borderRadius: 16,
        },
      },
    },
    MuiButton: {
      styleOverrides: { root: { borderRadius: 10 } },
      defaultProps: { disableElevation: true },
    },
    MuiTooltip: {
      styleOverrides: {
        tooltip: {
          backgroundColor: '#0a1130',
          border: `1px solid ${tokens.panelBorder}`,
          fontSize: 12,
        },
      },
    },
    MuiCssBaseline: {
      styleOverrides: {
        body: { backgroundColor: tokens.bg0 },
      },
    },
  },
});

export default theme;
