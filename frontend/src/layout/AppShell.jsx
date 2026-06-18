import React, { useState } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import {
  AppBar, Box, Drawer, IconButton, List, ListItemButton, ListItemIcon,
  ListItemText, Toolbar, Typography, useMediaQuery, Tooltip, Chip, Badge, Avatar,
} from '@mui/material';
import { useTheme } from '@mui/material/styles';
import MenuIcon from '@mui/icons-material/Menu';
import HomeIcon from '@mui/icons-material/Home';
import SpaceDashboardIcon from '@mui/icons-material/SpaceDashboard';
import PublicIcon from '@mui/icons-material/Public';
import LocationCityIcon from '@mui/icons-material/LocationCity';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import DescriptionIcon from '@mui/icons-material/Description';
import NotificationsNoneIcon from '@mui/icons-material/NotificationsNone';
import VerifiedUserIcon from '@mui/icons-material/VerifiedUser';
import { tokens } from '../theme.js';

const DRAWER_WIDTH = 250;

const NAV = [
  { to: '/', label: 'Overview', icon: <HomeIcon />, end: true },
  { to: '/dashboard', label: 'National Dashboard', icon: <SpaceDashboardIcon /> },
  { to: '/states', label: 'States & UTs', icon: <PublicIcon /> },
  { to: '/districts', label: 'Districts', icon: <LocationCityIcon /> },
  { to: '/anomalies', label: 'Anomalies', icon: <WarningAmberIcon />, badge: 24 },
  { to: '/reports', label: 'Reports', icon: <DescriptionIcon /> },
];

function Emblem({ size = 38 }) {
  return (
    <Box
      sx={{
        width: size, height: size, borderRadius: '12px', flexShrink: 0,
        display: 'grid', placeItems: 'center',
        background: `linear-gradient(140deg, ${tokens.saffronDeep}, ${tokens.saffron})`,
        boxShadow: '0 6px 18px rgba(255,122,0,0.35)',
      }}
    >
      <VerifiedUserIcon sx={{ color: '#1a1205', fontSize: size * 0.55 }} />
    </Box>
  );
}

function NavContent({ onNavigate }) {
  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <Box component={NavLink} to="/" onClick={onNavigate}
        sx={{ px: 2.5, py: 2.2, display: 'flex', alignItems: 'center', gap: 1.5, color: 'inherit', textDecoration: 'none' }}>
        <Emblem />
        <Box sx={{ minWidth: 0 }}>
          <Typography sx={{ fontFamily: 'Sora', fontWeight: 800, fontSize: 16, lineHeight: 1 }}>
            MGNREGA<span style={{ color: tokens.saffron }}>·</span>NVS
          </Typography>
          <Typography sx={{ fontSize: 10.5, color: tokens.textDim, letterSpacing: 0.3 }}>
            National Verification System
          </Typography>
        </Box>
      </Box>
      <Box className="tricolor-bar" sx={{ mx: 2.5, mb: 1.5 }} />

      <Typography sx={{ px: 3, pb: 1, fontSize: 10, letterSpacing: 1.5, color: tokens.textDim, textTransform: 'uppercase' }}>
        Navigation
      </Typography>
      <List sx={{ px: 1.5, flex: 1 }}>
        {NAV.map((item) => (
          <ListItemButton
            key={item.to}
            component={NavLink}
            to={item.to}
            end={item.end}
            onClick={onNavigate}
            sx={{
              borderRadius: 2.5, mb: 0.5, py: 1.1,
              color: tokens.textDim,
              '&.active': {
                color: '#fff',
                background: 'linear-gradient(90deg, rgba(79,140,255,0.20), rgba(79,140,255,0.04))',
                boxShadow: 'inset 3px 0 0 ' + tokens.saffron,
              },
              '&:hover': { background: 'rgba(255,255,255,0.05)', color: '#fff' },
            }}
          >
            <ListItemIcon sx={{ color: 'inherit', minWidth: 38 }}>
              {item.badge ? (
                <Badge badgeContent={item.badge} color="error">{item.icon}</Badge>
              ) : item.icon}
            </ListItemIcon>
            <ListItemText primaryTypographyProps={{ fontSize: 14, fontWeight: 600 }} primary={item.label} />
          </ListItemButton>
        ))}
      </List>

      <Box sx={{ p: 2, m: 1.5, borderRadius: 3, border: `1px solid ${tokens.panelBorder}`, background: 'rgba(255,255,255,0.03)' }}>
        <Typography sx={{ fontSize: 11, color: tokens.textDim }}>Coverage</Typography>
        <Typography sx={{ fontFamily: 'Sora', fontWeight: 700, fontSize: 15 }}>
          28 States · 8 UTs
        </Typography>
        <Typography sx={{ fontSize: 11, color: tokens.textDim }}>All districts · FY 2025-26</Typography>
      </Box>
    </Box>
  );
}

export default function AppShell({ children }) {
  const theme = useTheme();
  const isDesktop = useMediaQuery(theme.breakpoints.up('lg'));
  const [mobileOpen, setMobileOpen] = useState(false);
  const location = useLocation();

  // close the drawer on route change (mobile)
  React.useEffect(() => { setMobileOpen(false); }, [location.pathname]);

  return (
    <Box sx={{ display: 'flex', minHeight: '100vh' }}>
      <AppBar
        position="fixed"
        elevation={0}
        sx={{
          background: 'rgba(8,13,33,0.72)',
          backdropFilter: 'blur(16px)',
          borderBottom: `1px solid ${tokens.panelBorder}`,
          zIndex: (t) => t.zIndex.drawer + 1,
        }}
      >
        <Toolbar sx={{ gap: 1.5, minHeight: { xs: 58, sm: 64 } }}>
          {!isDesktop && (
            <IconButton color="inherit" edge="start" onClick={() => setMobileOpen(true)}>
              <MenuIcon />
            </IconButton>
          )}
          {!isDesktop && <Emblem size={32} />}
          <Box sx={{ minWidth: 0, flex: 1 }}>
            <Typography noWrap sx={{ fontFamily: 'Sora', fontWeight: 700, fontSize: { xs: 14, sm: 17 }, lineHeight: 1.1 }}>
              National Verification & Fraud Intelligence
            </Typography>
            <Typography noWrap sx={{ fontSize: { xs: 9.5, sm: 11 }, color: tokens.textDim }}>
              Ministry of Rural Development · Government of India
            </Typography>
          </Box>
          <Chip
            label="LIVE"
            size="small"
            sx={{ display: { xs: 'none', sm: 'flex' }, bgcolor: 'rgba(25,195,125,0.15)', color: tokens.green, fontWeight: 700, border: `1px solid ${tokens.green}55` }}
          />
          <Tooltip title="Alerts">
            <IconButton color="inherit"><Badge badgeContent={7} color="error"><NotificationsNoneIcon /></Badge></IconButton>
          </Tooltip>
          <Avatar sx={{ width: 34, height: 34, bgcolor: tokens.bg2, border: `1px solid ${tokens.panelBorder}`, fontSize: 14 }}>DD</Avatar>
        </Toolbar>
      </AppBar>

      {/* Permanent drawer (desktop) */}
      <Drawer
        variant="permanent"
        open
        sx={{
          display: { xs: 'none', lg: 'block' },
          // Reserve the drawer's width in the flex row so the fixed paper
          // does not overlap the main content.
          width: { lg: DRAWER_WIDTH },
          flexShrink: 0,
          '& .MuiDrawer-paper': {
            width: DRAWER_WIDTH, boxSizing: 'border-box',
            background: 'rgba(8,12,30,0.6)', backdropFilter: 'blur(16px)',
            borderRight: `1px solid ${tokens.panelBorder}`,
          },
        }}
      >
        <Toolbar sx={{ minHeight: { xs: 58, sm: 64 } }} />
        <NavContent />
      </Drawer>

      {/* Temporary drawer (mobile / tablet) */}
      <Drawer
        variant="temporary"
        open={mobileOpen}
        onClose={() => setMobileOpen(false)}
        ModalProps={{ keepMounted: true }}
        sx={{
          display: { xs: 'block', lg: 'none' },
          '& .MuiDrawer-paper': {
            width: DRAWER_WIDTH, boxSizing: 'border-box',
            background: 'rgba(8,12,30,0.96)', backdropFilter: 'blur(16px)',
            borderRight: `1px solid ${tokens.panelBorder}`,
          },
        }}
      >
        <NavContent onNavigate={() => setMobileOpen(false)} />
      </Drawer>

      <Box
        component="main"
        sx={{ flexGrow: 1, minWidth: 0 }}
      >
        <Toolbar sx={{ minHeight: { xs: 58, sm: 64 } }} />
        <Box sx={{ p: { xs: 1.5, sm: 2.5, md: 3 } }}>{children}</Box>
      </Box>
    </Box>
  );
}
