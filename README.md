# WISPR — The Moon as a Searchable Memory

Current release: see [Manraj release handoff](docs/MANRAJ_RELEASE_HANDOFF.md) for exact macOS/Windows commands and the three-minute demo, [acceptance matrix](docs/RELEASE_ACCEPTANCE.md), and [issue ledger](docs/RELEASE_ISSUES.md). The interactive entry point now integrates a 3D Moon, global HEALPix selection, original Site04 terrain and a preserved-real-data seven-day comparison.

The sections below are historical subsystem instructions; the release handoff takes precedence for the current UI.

# WISPR — lunar visibility and schedule recovery

The global lunar extension is documented in [GLOBAL_API_HANDOFF.md](docs/GLOBAL_API_HANDOFF.md), with actual source coverage and limitations in [GLOBAL_DATA_PROVENANCE.md](docs/GLOBAL_DATA_PROVENANCE.md) and executed verification in [GLOBAL_VALIDATION_REPORT.md](docs/GLOBAL_VALIDATION_REPORT.md).

Compare Sun and direct-to-Earth visibility at two lunar reference regions before and after a seven-day delay. Results are sampled geometric estimates, not landing certification, electrical power, radio link budgets or spacecraft commands.

## Run locally (PowerShell)

Use Python 3.12 or 3.13 and Node 22 or newer.

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python -m pip install -e '.[test]'
.\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In another terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. API documentation: http://localhost:8000/docs. No API keys are required. For another laptop, set `VITE_API_BASE_URL` to the reachable backend address and `CORS_ORIGINS` on the backend to the frontend origin. Bind to a trusted LAN interface only when needed.

```powershell
cd backend
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\python -m scripts.check_horizons
cd ../frontend
npm run build
npm test
```

The smoke test uses an explicitly labeled development example (2026-11-20, R01/R04, 24 hours). Select a mission date yourself. Raw JPL JSON and query metadata are cached under `backend/data/raw`; synthetic data never enters that cache. Offline synthetic UI mode: set `VITE_USE_MOCKS=true` in `frontend/.env.local`. Live errors never switch to synthetic data.

## Terrain and language input

Terrain requires real local GeoTIFFs and explicit vertical-reference metadata. See `backend/README.md`. No raster is bundled. The UI provides a complete manual form. Optional language interpretation requires server-side Groq/NVIDIA environment variables; it is unavailable without them and cannot invent dates. Do not put keys in frontend env files.

See `docs/IMPLEMENTATION_PLAN.md`, `docs/STATUS.md`, and the supplied frozen `docs/contracts/API_V1.md` for scope, evidence and limitations.

`backend/uv.lock` and `frontend/package-lock.json` record resolved dependencies. With uv installed, `uv sync --project backend --extra test --extra terrain --locked` reproduces the backend environment. `npm ci` reproduces the frontend install.

The integrated scientific grid/vector/scenario backend is documented in [UNIFIED_ANALYSIS_HANDOFF.md](docs/UNIFIED_ANALYSIS_HANDOFF.md), including real V3/NASA validation, API usage and the V4 ingestion contract.

Frontend integration and final stabilization evidence: [FRONTEND_INTEGRATION_HANDOFF.md](docs/FRONTEND_INTEGRATION_HANDOFF.md) and [SCIENTIFIC_BACKEND_VERIFICATION.md](docs/SCIENTIFIC_BACKEND_VERIFICATION.md).
