import React from 'react';
import { MapContainer, TileLayer, CircleMarker, Tooltip } from 'react-leaflet';
import { riskColor } from '../../lib/risk.js';

/** Leaflet scatter/heat of gram-panchayat risk points for a district. */
export default function DistrictHeatMap({ center, points = [] }) {
  if (!center) return null;
  return (
    <MapContainer
      center={center}
      zoom={9}
      style={{ width: '100%', height: '100%' }}
      scrollWheelZoom={false}
      attributionControl={false}
    >
      <TileLayer
        url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
        crossOrigin
      />
      {points.map((p) => {
        const c = riskColor(p.risk_score);
        return (
          <CircleMarker
            key={p.panchayat_id}
            center={[p.latitude, p.longitude]}
            radius={6 + (p.risk_score / 100) * 9}
            pathOptions={{ color: c, fillColor: c, fillOpacity: 0.55, weight: 1.5 }}
          >
            <Tooltip>
              <div style={{ fontSize: 12 }}>
                Risk <b>{p.risk_score}</b> · {p.total_works} works
              </div>
            </Tooltip>
          </CircleMarker>
        );
      })}
    </MapContainer>
  );
}
