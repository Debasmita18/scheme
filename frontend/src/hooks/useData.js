import { useQuery } from '@tanstack/react-query';
import * as api from '../lib/api.js';

export const useNationalSummary = () =>
  useQuery({ queryKey: ['national', 'summary'], queryFn: api.getNationalSummary });

export const useNationalTrends = () =>
  useQuery({ queryKey: ['national', 'trends'], queryFn: api.getNationalTrends });

export const useAnomalyBreakdown = () =>
  useQuery({ queryKey: ['national', 'anomalies'], queryFn: api.getAnomalyBreakdown });

export const useTopDistricts = (limit = 12) =>
  useQuery({ queryKey: ['national', 'top', limit], queryFn: () => api.getTopDistricts(limit) });

export const useStates = (params = {}) =>
  useQuery({ queryKey: ['states', params], queryFn: () => api.getStates(params) });

export const useStateDetail = (code) =>
  useQuery({ queryKey: ['state', code], queryFn: () => api.getState(code), enabled: !!code });

export const useDistricts = (params = {}) =>
  useQuery({ queryKey: ['districts', params], queryFn: () => api.getDistricts(params) });

export const useDistrictDetail = (id) =>
  useQuery({ queryKey: ['district', id], queryFn: () => api.getDistrict(id), enabled: !!id });

export const useDistrictHeatmap = (id) =>
  useQuery({ queryKey: ['district', id, 'heatmap'], queryFn: () => api.getDistrictHeatmap(id), enabled: !!id });

export const useStatesGeo = () =>
  useQuery({ queryKey: ['geo', 'states'], queryFn: api.getStatesGeo, staleTime: Infinity });

export const useDistrictsGeo = (state) =>
  useQuery({
    queryKey: ['geo', 'districts', state || 'all'],
    queryFn: () => api.getDistrictsGeo(state),
    enabled: !!state,
    staleTime: Infinity,
  });
