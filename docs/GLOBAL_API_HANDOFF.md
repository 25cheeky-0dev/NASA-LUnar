# Run and reproduce

Run from `backend` with Python 3.12 or 3.13:

```powershell
uv sync --locked --extra test --extra terrain --extra global --extra lint
$env:WISPR_GRID_DIR='C:\path\to\WISPR_Site04_Tiling_V3'
$env:WISPR_GLOBAL_ROOT='data/lunar-v1'
uv run --no-sync python -m scripts.build_global --v3 $env:WISPR_GRID_DIR
uv run --no-sync python -m scripts.ingest_global
uv run --no-sync python -m scripts.export_science_contract
uv run --no-sync python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Grid build requires a fresh target; ingestion reuses checksum-verified downloads/completed snapshots. Use a new root for changed scientific products. No raw source files are committed. Three real downloads total approximately 162 MB, dominated by Diviner. The current demonstrated artifacts occupy approximately 266 MB including snapshots.

Frontend, from `frontend`: `npm ci`, `npm run dev`. The default backend is localhost:8000. For different ports set `VITE_API_BASE_URL` and backend `CORS_ORIGINS` explicitly. The demonstration used frontend 127.0.0.1:5185 and API 127.0.0.1:8015. Those are local development services, not a public deployment.

## API

Authoritative prefix: `/api/v1/science/global`. Generated types and OpenAPI remain in `docs/contracts/science.generated.ts` and `science.openapi.json`.

Implemented routes include levels, paginated cells, whole-sphere lookup, cell detail, neighbors, sources, terrain features/vectors, candidates, similarity, source overlap, keyword retrieval, regional reverse crosswalk, layers, bounded geometry tiles, source-derived PNG images, thermal local-time-bin context, optional-source status, analysis and delay. Binary images are excluded from JSON TypeScript operations. Terrain fact responses have explicit strict models; heterogeneous source/evidence metadata remains extensible dictionaries.

Examples:

```text
GET /api/v1/science/global/cells/lookup?latitude=-89&longitude=45&nside=128
GET /api/v1/science/global/cells/MOON:HPX:NESTED:128:131075/thermal?local_time_bin=0
GET /api/v1/science/global/regional/SITE04_R000_C000/crosswalk?nside=128
```

```json
{"reference_cell_id":"MOON:HPX:NESTED:128:12345","normalization_version":"physical-scales-v1","maximum_results":10,"accept_unknown_uncertainty":true}
```

Post the above to `/similarity`. For a global dynamic scenario use `dataset_id="GLOBAL_SELECTED"` (default), selected IDs, explicit UTC start/end, cadence, altitude and minimum shared minutes. Explicitly allow the source quality when appropriate. Regional scenarios retain their original dataset and cell IDs. `/delay` additionally requires `original_cell_id` and evaluates exactly +168 hours using the shared engine. See executed request/response examples in `docs/evidence/global`.

The frontend shows stored elevation, slope, roughness, coverage, categorical source quality, LROC imagery and historical south-polar thermal bins. Missing thermal areas are transparent; spectra remain unavailable. It exposes original V3 projected polygons and exact original values. On-demand NASA analysis is available through the API; the existing mission-date frontend remains unchanged.

## Verification

```powershell
$env:WISPR_REAL_V3_DIR=$env:WISPR_GRID_DIR
$env:WISPR_GLOBAL_REAL='1'
$env:WISPR_LIVE_TEST='1'
uv run --no-sync python -m pytest -q
uv run --no-sync python -m scripts.verify_global --live
uv run --no-sync python -m scripts.export_science_contract --check
```

`--live` permits NASA access but exact source cache reuse is still labeled VERIFIED_CACHE. It does not force a new remote fetch. Offline CI does not download the external V3 package or global source products; asset-dependent tests explicitly skip unless configured. The real-source local run executes them. Do not report those CI skips as live verification.
