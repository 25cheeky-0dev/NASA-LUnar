# Backend startup and API handoff
From backend, create the locked environment:
```powershell
uv sync --locked --python 3.13 --extra test --extra lint --extra terrain --extra global
$env:WISPR_GRID_DIR = '<absolute original WISPR_Site04_Tiling_V3 directory>'
$env:WISPR_TERRAIN_V3_DIR = $env:WISPR_GRID_DIR
$env:WISPR_GLOBAL_ROOT = '<absolute existing data/lunar-v1 directory>'
$env:CELESTIAL_CACHE_DIR = '<absolute verified celestial cache directory>'
$env:WISPR_MODEL_DIR = '<absolute writable model artifact directory>'
uv run --no-sync uvicorn app.main:app --host 127.0.0.1 --port 8016
```
The original global build/download scripts remain available if those source snapshots are absent. Do not regenerate original V3. Native registry verifies every original manifest file, including its DEM. Use a fresh destination for immutable global builds.

OpenAPI: `/openapi.json`; checked-in [science.openapi.json](contracts/science.openapi.json). Generated TypeScript: [science.generated.ts](contracts/science.generated.ts). Generate/check using `python -m scripts.export_science_contract --check`. Source-specific response metadata remains explicit dictionaries where documented.

```powershell
Invoke-RestMethod http://127.0.0.1:8016/api/v1/science/status
Invoke-RestMethod 'http://127.0.0.1:8016/api/v1/science/global/cells/lookup?latitude=-89&longitude=45'
Invoke-RestMethod http://127.0.0.1:8016/api/v1/science/datasets
```
Full working POST bodies and responses: [workflow.json](evidence/final-backend/workflow.json). Reproduce with `python -m scripts.verify_final_backend`; it starts/stops its own loopback uvicorn. `python -m scripts.verify_science_http` independently verifies all 400 native records; set WISPR_HTTP_EVIDENCE to preserve historical evidence separately.

For full asset/live tests set WISPR_REAL_V3_DIR, WISPR_GLOBAL_ROOT, WISPR_GLOBAL_REAL=1 and WISPR_LIVE_TEST=1, then `python -m pytest -q -ra`. Optional CELESTIAL_LIVE_OUTPUT preserves live responses. Offline CI omits live calls and honestly reports external-asset skips.

This is a local startup configuration, not a public deployment. Configure an authenticated reverse proxy/TLS/rate limits and explicit CORS origins before public exposure. Never put API keys or source datasets in Git.
