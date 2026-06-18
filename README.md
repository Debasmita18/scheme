# MGNREGA National Verification & Fraud Intelligence System

**AI-powered, all-India verification of the world's largest rural employment programme — now covering every state, union territory and district.**

MGNREGA spends ~₹1 lakh crore a year across 15+ crore households. CAG audits document 30–40% fabrication in some pockets — ghost workers, inflated measurements, delayed wages. This platform closes the verification gap with satellite imagery, statistical forensics, payment-network analysis and agentic AI, and presents it as a modern, 3D, government-grade command centre.

> **v2 — “Ready for the whole of India.”** 28 states · 8 UTs · **725 districts**. Interactive 3D India map, rotating globe, responsive on phone / tablet / desktop, built on Vite + React + react-three-fiber.

---

## Coverage

| | |
|---|---|
| States | **28** |
| Union Territories | **8** |
| Districts | **725** (719 MGNREGA-active; fully-urban units flagged N/A) |
| Financial year | 2025–26 |
| Geography | Current admin map — Telangana, Ladakh, merged DNH&DD, A&N all present, census/LGD state & district codes |

The administrative hierarchy is **National → State/UT → District**, with block / gram-panchayat roll-ups, served from a single in-memory dataset so the entire app runs with **no database**.

---

## What you get

- **National Dashboard** — rotating 3D globe with India glowing on its surface, animated KPI cards (outlay, person-days, works, flagged anomalies, estimated leakage), an interactive **3D extruded India map** (bar height = composite fraud-risk, colour = risk band), a **3D risk gauge**, top-risk districts and trend/anomaly charts.
- **States & UTs** — interactive national 3D map + a filterable, sortable grid of all 36 states/UTs.
- **State drill-down** — that state's **districts** rendered as a 3D risk map, works-mix donut and a districts table; click any district.
- **All-India Districts** — searchable / filterable / paginated table across all 725 districts.
- **District case file** — full metrics, GP-level Leaflet risk heatmap, 3D gauge, works & anomaly breakdowns.
- **Anomaly Intelligence** — national anomaly mix, detection-vs-resolution trend, prioritised case queue.
- **Reports** — national brief, state scorecard, CAG-format audit pack, district case file, vernacular summary.

Fully responsive (mobile / iPad / desktop), dark “command-centre” theme with India-tricolor accents, code-split & lazy-loaded 3D, and a **WebGL error boundary** so locked-down machines degrade gracefully.

---

## Quick start

### 1. Backend API (no database needed)

```bash
cd backend

python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS / Linux

# Slim stack that RUNS the API + dataset builder (no GDAL/ML pain):
pip install -r requirements-api.txt

# (Re)build the all-India dataset — already committed under data/generated/
python -m data_ingestion.build_india_dataset

# Run the API
uvicorn api.main:app --app-dir . --port 8000
```

Swagger UI at <http://localhost:8000/docs>. `requirements.txt` (the full satellite + ML + PostGIS stack) is only needed for the live-ingestion / CV pipelines.

### 2. Frontend (Vite + React + 3D)

```bash
cd frontend
npm install
npm run dev          # http://localhost:3000  (proxies /api -> :8000)
```

`npm run build` produces an optimised, code-split bundle (three.js and charts are lazy chunks).

---

## How the data works

The dataset is built from official census/LGD **district boundaries** (`data/india_districts.geojson`). For each district, `data_ingestion/build_india_dataset.py` generates **deterministic, realistic** MGNREGA metrics (seeded per district, so output is stable) and rolls them up to state and national level:

- expenditure (wages + ~60:40 material split), person-days, households, active workers
- works (by permissible-works category), blocks, gram panchayats
- verified / flagged counts, composite **risk score**, estimated leakage
- women & SC/ST participation, average wage rate, completion rate

National totals land at a realistic scale (~₹1.18 lakh crore outlay, ~277 crore person-days, ~3 million works). **These figures are synthetic-but-credible for demonstration** — the geography, names and codes are real; the per-district numbers are modelled. To switch to real numbers, point ingestion at the live NREGA portal (`data_ingestion/nrega_scraper.py` already maps every state and can fetch district lists), then regenerate.

Fully-urban units (Delhi, Chandigarh and the metro districts) are flagged `mgnrega_active: false` and excluded from active roll-ups.

---

## Key API endpoints

```
GET /api/national/summary            All-India KPIs (states, UTs, districts, outlay, risk…)
GET /api/national/trends             12-month anomaly detection trend
GET /api/national/anomaly-breakdown  Anomalies by type with rupee impact
GET /api/national/top-districts      Highest-risk districts nationwide
GET /api/states                      All 28 states + 8 UTs (filter/sort)
GET /api/states/{code}               State detail + its districts
GET /api/districts                   All 725 districts (search/filter/sort/paginate)
GET /api/districts/{id}              District case file
GET /api/districts/{id}/heatmap      GP-level risk points
GET /api/geo/states                  State/UT boundary GeoJSON + risk  (3D national map)
GET /api/geo/districts?state={code}  District boundary GeoJSON + risk  (3D drill-down)
GET  /api/ai/status                  Is the Groq AI engine configured?
POST /api/ai/case-file/{id}          Generate a district case file (downloadable PDF)
POST /api/ai/report                  Generate a national/strategic report
```

Responses are gzip-compressed; map geometry is cached for a day on the client.

---

## AI engine (Groq LLM)

Case files and reports are written by a real LLM via Groq's OpenAI-compatible API.

1. Put your key in `backend/.env` (gitignored — never commit it):
   ```
   GROQ_API_KEY=gsk_xxx
   GROQ_MODEL=openai/gpt-oss-120b      # or llama-3.3-70b-versatile
   ```
2. On the **District** page → **Generate Case File**, and on **Reports** → any
   button: the app calls Groq, builds a CAG-format dossier from that
   district's/nation's figures, renders it to **PDF** server-side (xhtml2pdf,
   pure-Python) and **downloads the `.pdf`** automatically.
3. For deployment set `GROQ_API_KEY` as an env var on the host.

## Real-data ingestion (replacing modelled figures)

The geography, names and official codes are **real**. Per-district financial
figures are **modelled** by default (the public NREGA dashboard exposes the
directory reliably but not clean per-district aggregates). Two real paths ship
ready:

```bash
# 1) Live NREGA directory (real states/districts/blocks + official codes)
python -m data_ingestion.nrega_live --states
python -m data_ingestion.nrega_live --state 05          # Bihar's real districts
python -m data_ingestion.nrega_live --dump directory.json

# 2) Real district FIGURES from the Govt Open Data API (data.gov.in)
#    Set DATAGOVIN_API_KEY + DATAGOVIN_RESOURCE_ID in backend/.env, then:
python -m data_ingestion.datagovin --inspect            # view fields (API must be up)
python -m data_ingestion.datagovin --refresh            # rewrite dataset with REAL numbers
```

`--refresh` tags updated records `data_source="data.gov.in (live)"`. (data.gov.in
occasionally returns 502 under load — retry; the client paginates and is idempotent.)

---

## Tech stack

| Layer | Technology |
|-------|-----------|
| Frontend | Vite, React 18, MUI 5, **react-three-fiber / three.js / drei** (3D), d3-geo, Recharts, Framer Motion, React Query, Leaflet |
| API | FastAPI, Pydantic, Uvicorn, ORJSON, GZip |
| Data build | Shapely (dissolve + simplify boundaries), deterministic metric generator |
| Live ingestion (optional) | NREGA portal scraper, Sentinel-2 / Copernicus, scikit-learn, NetworkX, rasterio |

---

## Scalability notes

- The API serves a single in-memory dataset (sub-millisecond lookups). For production scale, the `services/india_data.py` layer is the seam to swap in PostgreSQL + PostGIS without touching routes.
- Frontend is route-code-split; three.js (~233 KB gz) and charts load only when their view is opened.
- Map geometry is pre-simplified and gzipped; the national map is ~36 features, drill-downs are per-state.

## License

MIT
