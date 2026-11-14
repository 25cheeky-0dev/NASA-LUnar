# Implementation status — 14 November 2026

Local source: `C:\Users\manra\Documents\GitHub\LUNA---MOON---NASA-HACKATHON`. Baseline was an empty repository with an unborn `main` branch. During implementation an initial snapshot appeared as commit `b758d38` on `main` and `origin/main`; this session did not create or push it. Remaining changes and new tests/evidence are uncommitted. This session did not publish a site. The supplied agent instructions were treated as project specifications. No parallel workers or remote branches were created.

## Verified results

- Python 3.12.16 backend: **77 tests passed**. Coverage includes 179/180-minute thresholds, strict zero threshold, three separated windows, gaps, isolated samples, crossing uncertainty, exact +168h across leap day/year rollover, reverse-site switching, all recovery outcomes, bounded future dates, lunar projection round trips, source-version identities, malformed JPL headers, scientific-notation heights, target alignment, cache replay/tampering, invalid model output and manual fallback.
- Frontend: **`npm test` passed**, covering six synthetic outcomes, exact delay, window consistency, null features, shared grid IDs and zero-day future-search bounds.
- Frontend: **`npm run build` passed**, including TypeScript.
- Browser: live/cached recovery, scenario selection, chart/export changes, grid details, missing-terrain result and a 390px mobile layout checked. No horizontal overflow. Screenshot: `docs/evidence/preview.jpg`.
- Dependencies pinned in `backend/uv.lock` and `frontend/package-lock.json`. The initial npm dependency audit reported zero vulnerabilities. Backend tests emit one upstream Starlette/httpx deprecation warning; tests still pass.

## Feature checklist

| Feature | Status | Evidence / limit |
|---|---|---|
| FastAPI boot, `/health`, `/docs`, OpenAPI | WORKING | HTTP 200; generated schema in `docs/evidence/openapi.json`. Health is DEGRADED until a live probe succeeds in that process. |
| Real Sun/Earth lunar observations | WORKING | Eight actual JPL target series retrieved for R01/R04 on original/delayed dates. Raw responses plus query metadata and SHA-256 saved locally. |
| Verified offline cache | WORKING | Exact query, parser version and raw hash checked before replay; authentic cache and tampering tests. |
| Continuous-window model | WORKING | Piecewise-linear target-center elevations, adjacent known samples only, MODEL_ESTIMATE with step-sized uncertainty. No unqualified proof of continuous physical visibility. |
| Four-scenario recovery and optional future search | WORKING | Actual HTTP 200 recovery example and deterministic outcome tests. Future dates are explicit daily arrival instants, not every possible instant in a continuous date range. |
| Lunar 1km grid | WORKING | Nine cells per region, 18 total; canonical spherical lunar projection. Reference observations never evaluate the containing cell center. |
| Physical feature vectors / scatter | WORKING | Scenario-specific reference points; nine null-valued center points per selected neighborhood. Missing slope prevents complete-vector similarity. No PCA or embeddings. |
| React mission interface | WORKING | Structured UTC form, all outcome states, comparisons, elevations, windows, map IDs, scatter, ENU slider, provenance and CSV. Synthetic mode makes no backend requests and retains its banner. |
| Local DEM reader / heightmap / horizon code | PARTIAL | Hash, declared source/vertical reference, CRS, lunar radius, footprint and NoData checks implemented. Geodesic rays include curvature. No actual NASA raster was downloaded, so end-to-end source verification remains incomplete. |
| Terrain-aware recovery | BLOCKED | Local and far-field horizon coverage plus vertical-reference conversion are unverified. Returns INSUFFICIENT_DATA. No geometric fallback. |
| Optional Groq/NVIDIA translation | PARTIAL | JSON output revalidation, fixed-rule protection and manual fallback tested with synthetic responses. Real account/model/free-quota access untested. Requires server-side keys and model IDs. |
| Local 3D terrain mesh / imagery basemap | BLOCKED | No verified heightmap source. No invented surface, screen-aligned NASA imagery or decorative globe presented as science. |
| Deployment / authentication / persistent scenario database | OUT OF SCOPE | Local development build. Scenario summaries use a bounded in-memory store; raw cache persists. No internet exposure or mission action. |

## Actual source-backed development example

This example is not the user's selected mission date. Original arrival: **2026-11-20T00:00:00Z**. Delayed arrival: **2026-11-27T00:00:00Z**. Both sites: 24h studies, 5-minute samples, geometric ideal horizon, target centers, 180-minute minimum. Horizons reference-sphere height: **0 km**; the 1m above-DEM setting is not applied to this unrelated reference surface.

| Scenario | Samples per target | Known interval | Longest modeled shared window |
|---|---:|---:|---:|
| Original R01 | 289 | 100% | 1440 minutes |
| Original R04 | 289 | 100% | 1440 minutes |
| Delayed R01 | 289 | 100% | 1440 minutes |
| Delayed R04 | 289 | 100% | 1440 minutes |

Actual recommendation: **KEEP_SITE_AFTER_DELAY**. Final HTTP replay: **200**, `source_type=NASA_JPL_VERIFIED_CACHE`. Scope and all eight raw hashes are recorded in `docs/evidence/recovery_summary.json`. Full result: `backend/data/evidence/development_recovery.json`; raw sources: `backend/data/raw`. Generated raw/cache data are ignored by Git. Small authentic source fixtures and query metadata are tracked under `backend/tests/fixtures` for offline parser/cache tests.

Independent Windows-curl Sun probe and the Python adapter agreed at R01:

| UTC | Sun azimuth | Sun elevation |
|---|---:|---:|
| 2026-11-20T00:00:00Z | 191.084568° | 1.017911° |
| 2026-11-20T00:05:00Z | 191.042390° | 1.017823° |

The Python Earth source at 00:00 gave azimuth 130.274804°, elevation 2.824754°. These are real API values, not an independent physical ephemeris validation. A separate visual cross-check in the interactive JPL webpage has **not** been performed.

## External failures and unresolved data

Both NASA GSFC DEM URLs were attempted with certificate verification and a bounded timeout:

- `https://pgda.gsfc.nasa.gov/data/LOLA_5mpp/Site01/Site01_final_adj_5mpp_surf.tif`
- `https://pgda.gsfc.nasa.gov/data/LOLA_5mpp/Site04/Site04_final_adj_5mpp_surf.tif`

Both failed with curl error 28: could not connect to pgda.gsfc.nasa.gov:443 after about 21 seconds. Neither CRS/vertical datum nor geographic footprint has been validated against an actual downloaded raster. Local ingestion instructions are in `backend/README.md`.

The initial Python urllib probe failed certificate-chain validation. The implemented provider uses `truststore` to validate through the OS trust store; live Python retrieval then succeeded. Certificate verification was not disabled.

No Groq/NVIDIA key or model access was assumed. Configure secrets only in the backend environment, verify the account's free allowance, then test a chosen model. The manual flow does not need them.

## What this build cannot calculate

Flight safety, landing hazards, complete terrain clearance, finite solar-disc illumination, actual watts/battery state, radio-link budget, propellant requirements, global optimality or real spacecraft actions. A 5-minute series supports a declared sampled model estimate, not a certified continuous engineering guarantee.
