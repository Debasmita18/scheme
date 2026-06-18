import axios from 'axios';

// In dev, Vite proxies /api -> FastAPI. In prod, set VITE_API_BASE to the API origin.
const baseURL = import.meta.env.VITE_API_BASE || '';

export const http = axios.create({
  baseURL,
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
});

http.interceptors.response.use(
  (res) => res.data,
  (err) => {
    const status = err.response?.status ?? 0;
    const message =
      err.response?.data?.detail || err.response?.data?.message || err.message || 'Request failed';
    return Promise.reject({ status, message });
  }
);

// ---- National ----
export const getNationalSummary = () => http.get('/api/national/summary');
export const getNationalTrends = () => http.get('/api/national/trends');
export const getAnomalyBreakdown = () => http.get('/api/national/anomaly-breakdown');
export const getTopDistricts = (limit = 10) =>
  http.get('/api/national/top-districts', { params: { limit } });

// ---- States / UTs ----
export const getStates = (params) => http.get('/api/states', { params });
export const getState = (code) => http.get(`/api/states/${code}`);

// ---- Districts ----
export const getDistricts = (params) => http.get('/api/districts', { params });
export const getDistrict = (id) => http.get(`/api/districts/${id}`);
export const getDistrictHeatmap = (id) => http.get(`/api/districts/${id}/heatmap`);

// ---- Geo ----
export const getStatesGeo = () => http.get('/api/geo/states');
export const getDistrictsGeo = (state) =>
  http.get('/api/geo/districts', { params: state ? { state } : {} });

// ---- AI (Groq) report generation ----
export const getAiStatus = () => http.get('/api/ai/status');
export const generateCaseFile = (districtId) =>
  http.post(`/api/ai/case-file/${districtId}`);
export const generateAiReport = (kind) =>
  http.post('/api/ai/report', { kind });
