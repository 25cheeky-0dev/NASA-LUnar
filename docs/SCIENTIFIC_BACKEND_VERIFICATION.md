# Scientific backend verification — stabilization

Verified on 2026-11-14. Branch: `feature/unified-scientific-analysis`. Scope: stabilize the implemented backend, repair locked CI, validate source-backed behavior and freeze the frontend contract. No grid/celestial/vector engine rebuild, no frontend changes and no merge.

## Dependency failure and repair

Failed run: [43599996866](https://github.com/25cheeky-0dev/LUNA---MOON---NASA-HACKATHON/actions/runs/43599996866). Python 3.13 failed `uv sync --project backend --locked --extra celestial --extra test --extra lint`; Python 3.12 was cancelled by fail-fast.

The exact command reproduced the mismatch locally. `pyproject.toml` already declared NumPy, PyArrow and pyproj as core dependencies, while `backend/uv.lock` listed them only through extras. `uv lock --project backend` changed six dependency-metadata lines and no package versions. The exact locked sync then succeeded. Repair commit: `60cedebf4a123407376ff73ffc7a4a35ffd0daa5`.

[Repair CI run 43600589729](https://github.com/25cheeky-0dev/LUNA---MOON---NASA-HACKATHON/actions/runs/43600589729) passed **both Python 3.12 and 3.13**. `--locked` remains mandatory; tests and NASA validators were not weakened. The workflow now also validates integration code and generated contracts, watches documentation artifacts, and uses fail-fast=false so both Python versions produce independent results.

Key locked versions: NumPy 2.5.4, PyArrow 26.0.1, pyproj 3.8.0, FastAPI 0.162.7, Pydantic 2.14.3, httpx 0.28.1, pytest 9.2.0, Ruff 0.17.5. The same lock resolves on both CI Python versions. Optional terrain dependencies remain available through `--extra terrain`.

## Tests and contract checks

- Final local full run with the actual V3 package and `WISPR_LIVE_TEST=1`: **175 passed, no skips** on Python 3.13.17. This includes the prior 171 tests and four focused contract/release tests.
- Offline run without external asset environment: **172 passed, 3 skipped**. The skips explicitly require the external full V3 package or live NASA; authentic extracted V3 + recorded-NASA tests still run.
- CI uses `-m 'not live'`: the two live tests are intentionally deselected; the absent full external V3 package is an explicit skip, not synthetic validation. No NASA network dependency was introduced into offline CI.
- New checks cover generated OpenAPI/TypeScript drift, all eleven declared response models, HTTP error envelopes/429 gate, CORS, source-unavailable UNKNOWN state with no synthetic fallback, and saved real HTTP examples against runtime response models.
- Existing legacy API, celestial API, Horizons validation/cache, vectors, quality filtering, similarity, UTC/coordinate joins, scenario separation, delay outcomes, partial horizons and provenance tests remain passing.
- TypeScript generated contracts passed `tsc --noEmit --strict --skipLibCheck`. Ruff checks/formatting and `git diff --check` passed.
- One upstream Starlette TestClient/httpx deprecation warning is present. It is not a scientific or test failure.

## Native V3 and actual HTTP verification

`python -m scripts.verify_science_http` launches a temporary uvicorn subprocess and sends real HTTP requests over localhost TCP, then stops the subprocess. It reads the dataset exclusively from `WISPR_GRID_DIR`. The full package is not copied into Git.

Results:

- All **30 files** in `SHA256_MANIFEST.json` matched, including the original NASA raster.
- All **400 cells** were retrieved over three bounded pages and compared with baseline Parquet.
- Exact IDs, original latitude/longitude, projected X/Y, elevation, slope and roughness were unchanged.
- Polygon coordinates were decoded from baseline WKB and matched exactly; original WKB bytes and lunar projected CRS were preserved.
- Immutable grid version **2.0.0**, tile-processing version **3.0.0**, dataset ID `SITE04_NW_ORIGIN_PRESERVED_2KM_100M__tiles_3.0.0` preserved.
- Static feature order and fixed normalization verified; raw/normalized arrays remain separate.
- Missing elevation uncertainty and LOLA shot counts remain null, with the source quality string intact. Real V3 similarity correctly returns 422 under its strict comparability rule.
- All eleven science routes exercised, plus errors and CORS. **16 complete HTTP examples** are committed in [final_api_examples.json](evidence/unified/final_api_examples.json). Full 400-cell validation does not require committing all three large pagination responses; the file retains a two-cell page example.
- The running server's `/openapi.json` exactly matched [the exported schema](contracts/science.openapi.json).

## Verified source-backed scenario

| Cell | Nov 15–22, 2026 UTC | Nov 22–29, 2026 UTC |
|---|---:|---:|
| SITE04_R000_C000 | 5988.9515639 minutes | 10080 minutes |
| SITE04_R000_C001 | 5988.594435616667 minutes | 10080 minutes |

Intervals start/end at 00:00 UTC; cadence is 60 minutes; each cell/interval has 169 inclusive samples. Minimum shared visibility duration is the explicitly supplied 60 minutes. Horizons altitude is explicitly 0 km; model is GEOMETRIC_IDEAL. Unknown fraction is zero in these source-backed scenarios; outcome is **KEEP**. No material numerical difference from the previous handoff was found.

The HTTP verification used **VERIFIED_CACHE** deliveries, with exact query matching, source hashes and NASA header validation. The full test run separately passed live NASA retrieval and independent timestamp-comparison tests. Neither category is labeled as the other. Each complete response carries query URLs, timestamps, delivery mode and provenance.

## Scientific limitations retained

The V3 DEM vertical reference is still unverified against Horizons, and finite local terrain coverage does not establish complete skyline visibility. The demonstrated results remain GEOMETRIC_IDEAL, not verified terrain-obstructed visibility. Observer altitude is never substituted from a cell-mean DEM elevation. No fabricated uncertainty, shot counts, terrain clearance, actual solar power, radio link or safe landing claims are introduced.

Original-week cell differences are below the 60-minute sampling cadence and do not establish a meaningful advantage. Candidate quality acceptance is explicit. No universal slope/roughness safety threshold is invented. Unknown samples and unavailable sources remain unknown; incomplete results are not ranked as complete. No new synthetic fallback exists.

The in-memory grid registry has not been benchmarked for full-Moon production scale. Dynamic responses are bounded to 16 recent entries per process; they expire on restart/eviction. NASA scientific cache persists separately. Browser abort does not guarantee upstream cancellation. These are operational limitations, not release blockers for the documented selected-cell frontend integration.

## Merge readiness and integrity review

- PR #1: `feature/celestial-engine` → `main`, head `7736d1085d1f1974e386496355bb23b709ca1ea2`; open, non-draft, GitHub mergeable/clean. Its existing CI runs passed.
- PR #2: `feature/unified-scientific-analysis` → `feature/celestial-engine`; open, non-draft, GitHub mergeable/clean at the repair checkpoint; updated stabilization CI is tracked in the final handoff.
- Local ancestry checks confirm `main` → `feature/celestial-engine` → integration. No frontend paths changed relative to the celestial branch; original backend endpoints are retained.
- Ordinary Git history contains no `.tif`, `.tiff` or `.img` raw DEM assets. The new large JSON artifact is HTTP evidence, not a raw raster. Native data stays in its external package.
- Targeted tracked-file checks found no private-key, GitHub-token or AWS access-key patterns. Credentials used by the existing Git authentication remain outside repository files. This is a scoped release check, not a claim of an exhaustive independent security audit.
- All native source checksums matched; no original V3 measurements were modified.

After explicit approval, merge sequentially: first PR #1 into main; then retarget PR #2 to main, recheck its resulting diff/CI and merge it. Do not squash or reorder branches without checking ancestry/diff. Neither PR has been merged by this work.

## Reproduction and frontend handoff

Use the exact environment/startup commands, endpoint inventory, errors and loading guidance in [FRONTEND_INTEGRATION_HANDOFF.md](FRONTEND_INTEGRATION_HANDOFF.md). From `backend`:

```powershell
uv sync --locked --extra celestial --extra test --extra lint --extra terrain
$env:WISPR_GRID_DIR='C:\Users\manra\Downloads\WISPR_Site04_Tiled_Provenance_V3\WISPR_Site04_Tiling_V3'
$env:WISPR_REAL_V3_DIR=$env:WISPR_GRID_DIR
$env:WISPR_LIVE_TEST='1'
uv run --no-sync python -m pytest -q
uv run --no-sync python -m scripts.export_science_contract --check
uv run --no-sync python -m scripts.verify_science_http
```

The path is a documentation example only. For CI-style offline execution, unset the live/asset variables and run `uv run --no-sync python -m pytest -q -m 'not live'`. Obtain the checked-out final release SHA with `git rev-parse HEAD`; the final delivery also reports the pushed commit and its CI run.

### Cross-version schema stabilization

The expanded workflow exposed a Python 3.12/3.13 difference in the standard library's HTTP 422 reason phrase (`Unprocessable Content` versus `Unprocessable Entity`). Scientific tests passed; only the exact OpenAPI snapshot failed on 3.12. Science error response descriptions are now explicitly defined in the router, so the served and exported schema is identical across versions. The snapshot assertion was retained, not loosened.

## Final code checkpoint

Implementation commit: **`3e26bb057c678481be6045a7c59bbaea9c14c48d`** on `feature/unified-scientific-analysis`.

[Final implementation workflow 43601758863](https://github.com/25cheeky-0dev/LUNA---MOON---NASA-HACKATHON/actions/runs/43601758863):

| Python | CI result | Exact pytest result |
|---|---|---|
| 3.12 | SUCCESS | 172 passed, 1 skipped, 2 deselected, 1 warning |
| 3.13 | SUCCESS | 172 passed, 1 skipped, 2 deselected, 1 warning |

Both jobs passed locked sync, lint, formatting, the entire offline regression suite and exact generated-contract validation. The single skip is the unavailable external full V3 package on CI; the two deselections are the explicitly live NASA tests. Local full validation with those dependencies enabled was 175 passed.

No backend integration blocker remains for the documented scope. The unverified terrain vertical reference, incomplete horizons, missing uncertainty layers and bounded process-local storage remain explicit limitations. PR #2 is ready for review and an approved sequential merge; no merge was performed. A subsequent documentation-only commit records this checkpoint; its SHA is available in Git/PR history and the final delivery.
