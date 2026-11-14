# Manraj — WISPR integration handoff

Worktree/branch: existing checkout, isolated branch `codex/wispr-release-verification`. No merge, force-push or public deployment. Original staged/uncommitted work remains present. The new entry point is `MissionControl` rendered by `frontend/src/main.tsx`; legacy UI source remains available but is not rendered.

## Install and start (macOS / Linux)

From the repository root:

```sh
python3.13 -m venv backend/.venv
backend/.venv/bin/python -m pip install -e './backend[test]'
cd frontend
npm ci
npm run dev
```

In a second terminal, from the repository root:

```sh
export WISPR_GRID_DIR='/absolute/path/to/WISPR_Site04_Tiling_V3'
export CELESTIAL_CACHE_DIR="$PWD/backend/data/celestial"
backend/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:5173 . The full Site04 package is optional for the two-cell preserved-data demonstration, required for all 400 cells and original 3D terrain. On this Mac the verified package is `/Users/narinderpalsingh/Downloads/WISPR_SITE04_FINAL_HANDOFF_2026-11-14/WISPR_Site04_Tiling_V3`. Never embed that personal path in distribution defaults. API docs: http://127.0.0.1:8000/docs . `.env.example` lists configuration; export backend variables explicitly. Frontend Vite reads `frontend/.env.local`; API keys belong only on the backend.

## Serve the production build locally

After installation, run from the repository root (stop any other backend on port 8000 first):

```sh
cd frontend
npm run build
cd ..
export WISPR_STATIC_DIR="$PWD/frontend/dist"
export WISPR_GRID_DIR='/absolute/path/to/WISPR_Site04_Tiling_V3'
export CELESTIAL_CACHE_DIR="$PWD/backend/data/celestial"
backend/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000 . The production UI uses the same origin for API requests; no separate frontend server is needed. Leave `VITE_API_BASE_URL` unset for this configuration.

## Windows 11 (reviewed, not executed this session)

```powershell
py -3.13 -m venv backend/.venv
backend/.venv/Scripts/python -m pip install -e './backend[test]'
$env:WISPR_GRID_DIR='C:\path\to\WISPR_Site04_Tiling_V3'
$env:CELESTIAL_CACHE_DIR="$PWD\backend\data\celestial"
backend/.venv/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# Separate PowerShell terminal:
cd frontend
npm ci
npm run dev
```

## Tests and evidence

```sh
backend/.venv/bin/python -m pytest -q backend
cd frontend
npm run build
npm test
cd ../backend
.venv/bin/python -m scripts.export_science_contract --check
WISPR_LIVE_TEST=1 .venv/bin/python -m pytest -q celestial_engine/tests/test_live_horizons.py
.venv/bin/python -m scripts.check_integration --grid-root "$WISPR_GRID_DIR" --output ../docs/evidence/release/site04
```

`docs/evidence/release/` contains current logs and fresh real Site04 integration outputs. Historical evidence elsewhere is retained, not overwritten. `RELEASE_ACCEPTANCE.md` identifies bounded PASS, external BLOCKED and unexecuted areas.

## Three-minute demonstration

1. **0:00–0:35** — Atlas: orbit/zoom the Moon. Search Apollo 11 or Tycho. Show the representative point source and distinct HEALPix cell center. Global missing slope/elevation stays Unknown.
2. **0:35–1:15** — Click Site04. Scroll to Terrain pixels: orbit original DEM mesh; switch slope/elevation/roughness; select a cell. Enter maximum slope 10°: zero matches is an honest result. Clear the limit. IDs and source values remain unchanged.
3. **1:15–2:25** — Click Run preserved-data demo. This explicitly disables network in the calculation and uses authentic raw NASA responses, not synthetic UI data. Baseline is November 15–22, 2026; delayed is November 22–29; both 168 hours, hourly cadence. Switch Baseline / +7 days and both cell bars. Original first cell has about 99.82 h shared baseline and 168 h delayed. KEEP means the requested ideal-horizon constraint is still met, not landing approval. Expand provenance.
4. **2:25–3:00** — Evidence tab: explain ideal horizon versus partial/unknown terrain and geometric Earth line of sight versus communications. Open Ask WISPR: absent provider credentials show the structured fallback limitation. Do not pretend the LLM generated the numerical results.

## Architecture / data contracts

- Global geography: `MOON:HPX:NESTED:<nside>:<pixel>`. NSIDE 8 is a lightweight display layer; selecting a point resolves to NSIDE 128. These are intentionally overlapping hierarchy layers. Analytic HEALPix boundaries are sampled for display.
- Original `SITE04_R..._C...` IDs are unchanged and remain a separate namespace. Regional Parquet/WKB uses lunar projected metres. The external 5°/10° hierarchical prototype is not imported or silently combined with HEALPix.
- `moonMath.ts`: adapter +X = equatorial 0°E, +Y = north, -Z = equatorial 90°E. `TerrainScene` centers the original local mesh for display and rotates source Z-up to renderer Y-up at 1× scale. No source coordinates are modified.
- Science remains `app/integration`, `celestial_engine`, `app/science/windows`, and the partial terrain provider. Scene colors and bars do not run a separate numerical model.
- Request generation guards prevent older global lookups and comparisons overwriting newer state. Changing mission settings clears the previous result. Browsing a new location clears stale comparison output.
- The renderer texture is a documented NASA-derived recompression from an attributed mirror, not an elevation source. Official NASA asset host was unreachable; delivery/hash/processing are in `frontend/public/moon/provenance.json`.
- Natural language proposes strict date, duration, shared-window and terrain-filter inputs for already selected cells through `/navigation/interpret`. Explicit UTC and literal unit-bearing user evidence are required. Location changes and unsupported constraints require clarification. Missing provider credentials leave the structured form usable; live model access was not available. No scientific values come from an LLM.

## Google Cloud boundary

Google Cloud is not required locally. No configured deployment was found in the repository; Docker and gcloud were absent on this host. `Dockerfile` prepares one service serving the built UI and FastAPI, one worker, `/health`, `$PORT`. Docker execution is UNASSESSED. Runtime image includes preserved real-data fixtures; original large Site04 package must be mounted/staged separately and `WISPR_GRID_DIR` set. No credentials are baked in.

Remaining authorized-operator steps: install Docker/gcloud; build and run the image locally; choose an actual project and region; confirm billing and deployment authorization; enable required build/artifact/run services; push image to that project's Artifact Registry; deploy to Cloud Run with authentication required, one worker per instance and bounded instance count. Use Secret Manager for optional LLM keys; supply CORS only if using a different origin. Test authenticated health, offline demo, selected-cell queries, cold start, memory, timeouts and persistent-cache strategy. Public access is a separate explicit decision. No project IDs, cloud resources or successful deployment are asserted here.
