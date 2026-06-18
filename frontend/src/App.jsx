import React, { Suspense, lazy, useEffect } from 'react';
import { Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { Box, LinearProgress } from '@mui/material';
import AppShell from './layout/AppShell.jsx';

const Landing = lazy(() => import('./pages/Landing.jsx'));
const Dashboard = lazy(() => import('./pages/Dashboard.jsx'));
const StatesView = lazy(() => import('./pages/StatesView.jsx'));
const StateDetail = lazy(() => import('./pages/StateDetail.jsx'));
const DistrictsView = lazy(() => import('./pages/DistrictsView.jsx'));
const DistrictDetail = lazy(() => import('./pages/DistrictDetail.jsx'));
const Anomalies = lazy(() => import('./pages/Anomalies.jsx'));
const Reports = lazy(() => import('./pages/Reports.jsx'));

function ScrollToTop() {
  const { pathname } = useLocation();
  useEffect(() => {
    const el = document.querySelector('main');
    if (el) el.scrollTo?.({ top: 0 });
    window.scrollTo({ top: 0 });
  }, [pathname]);
  return null;
}

export default function App() {
  return (
    <AppShell>
      <ScrollToTop />
      <Suspense fallback={<LinearProgress sx={{ mt: 2 }} />}>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/states" element={<StatesView />} />
          <Route path="/states/:code" element={<StateDetail />} />
          <Route path="/districts" element={<DistrictsView />} />
          <Route path="/districts/:id" element={<DistrictDetail />} />
          <Route path="/anomalies" element={<Anomalies />} />
          <Route path="/reports" element={<Reports />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </AppShell>
  );
}
