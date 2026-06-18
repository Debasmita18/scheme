import React from 'react';
import { Box, Typography } from '@mui/material';
import ViewInArIcon from '@mui/icons-material/ViewInAr';
import { tokens } from '../../theme.js';

/**
 * Error boundary that catches WebGL / three.js failures (e.g. on locked-down
 * machines where hardware acceleration is disabled) and shows a graceful
 * fallback instead of crashing the whole page.
 */
export default class Canvas3D extends React.Component {
  constructor(props) {
    super(props);
    this.state = { failed: false };
  }

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error) {
    // eslint-disable-next-line no-console
    console.warn('3D view unavailable, showing fallback:', error?.message);
  }

  render() {
    if (this.state.failed) {
      return (
        this.props.fallback ?? (
          <Box sx={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center', p: 2 }}>
            <Box sx={{ textAlign: 'center', color: tokens.textDim }}>
              <ViewInArIcon sx={{ fontSize: 40, opacity: 0.5 }} />
              <Typography sx={{ mt: 1, fontSize: 12.5 }}>
                3D view unavailable on this device.<br />Data is shown in the panels below.
              </Typography>
            </Box>
          </Box>
        )
      );
    }
    return this.props.children;
  }
}
