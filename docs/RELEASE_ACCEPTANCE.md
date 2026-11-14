# WISPR release acceptance — 14 November 2026

Current branch: `codex/wispr-release-verification`. Existing staged `.DS_Store` and seven user-edited source/test files were preserved. No merge, push or public deployment.

| Requirement → implementation | Source/dependency | Verification | Status |
|---|---|---|---|
| Global selectable sphere → Three.js + HEALPix NSIDE 8 overview / 128 selection | `lunar_global/grid.py`, analytic sphere 1,737,400 m | Existing polar/wrap/hierarchy tests; new renderer cardinal/roundtrip tests; browser named selection | PASS |
| Stable detailed identity → original V3 loader + 400 selectable cells | Original Site04 manifest and Parquet; 2.0.0 grid / 3.0.0 processing | Real-package test with `WISPR_REAL_V3_DIR`; browser C010 selection | PASS |
| Color terrain measurements → slope/elevation/roughness pixel atlas | Original cell summaries; null stays unknown | Browser slope filter returns 0 at 10°; no safety winner invented | PASS |
| Original detailed 3D → manifest-checked GLB route and Z-up adapter | Original 2 km Site04 mesh; 5 m sampled DEM | HTTP loader and browser mesh load, 1× height | PASS |
| Named navigation → curated point catalogue | NASA Apollo, USGS feature centers, ISRO planned region | HTTP tests, browser; named point distinguished from selected cell | PASS |
| UTC, geometry, exact seven-day shift → existing Celestial Engine | JPL Sun 10 / Earth 399 / coord@301 / airless quantity 4 | Existing regressions plus live Horizons test | PASS |
| Source-backed offline two-location comparison → explicit demo route | Original two cells + exact cache with raw response SHA256 and metadata | New HTTP regression and browser 168 h delayed shared window | PASS |
| Arbitrary selected-cell comparison → structured deterministic form | `/science/delay` and `/science/global/delay` | Existing pipeline tests; fresh full-package integration evidence in release/site04 | PASS |
| Windows/gaps/terrain unknown → existing window and skyline engines | Cadence-limited interpolation; reference compatibility gates | Existing missing-data, obstruction and unknown tests | PASS |
| Language interpretation → strict selected-cell mission input schema; structured fallback | Optional Groq/NVIDIA credentials and models | Invalid/unavailable interpreter regression; selected-cell form usable | BLOCKED |
| Honest global terrain availability | Global high-resolution terrain not supplied or required; not implied | UI labels and no-ingested-data responses retain Unknown | PASS |
| Verified terrain-clearance result | DEM/Horizons vertical-reference alignment; complete skyline evidence absent | Explicit UNKNOWN gate regression | BLOCKED |
| Production frontend and clean installation | Node 22+, Python 3.12+ | Empty Python venv install/test; clean npm ci/build/test; production-http.json; browser same-origin checks | PASS |
| Google Cloud deployment | Authorized project, billing, identity; Docker/gcloud unavailable locally | Dockerfile, health endpoint, env example; no resources created | BLOCKED |
| Windows execution | Windows host unavailable this session | PowerShell commands reviewed only; historical reports not fresh evidence | UNASSESSED |

PASS applies to the listed bounded check, not flight validation or universal correctness.

## Official challenge mapping

The official challenge search result retrieved 14 November 2026 describes comparing lunar sites and dates, visualizing Sun/Earth relative to the horizon, and assessing power-generation potential and direct-to-Earth windows: https://www.spaceappschallenge.org/2026/challenges/lunar-landing-site-navigator/ . Direct retrieval returned HTTP 502, so the full brief/resource-tab audit remains BLOCKED by that source. Mapped workflows: atlas/location selection → structured comparison → baseline/delay chart and three window tracks → explicit source and limitations. Do not claim complete coverage of inaccessible brief text.

Official scientific settings checked against https://ssd-api.jpl.nasa.gov/doc/horizons.html and https://ssd.jpl.nasa.gov/horizons/manual.html . ISRO benchmark: https://www.isro.gov.in/ISRO_EN/Chandrayaan3_Details.html . It distinguishes mission communications, terrain and operational capability; it is not WISPR approval.

## Package authority and limits

Read together: repository frontend/unified/global handoffs; Celestial Engine verification; local `WISPR_SITE04_FINAL_HANDOFF_2026-11-14/00_START_HERE_FINAL.md` and independent audit; `WISPR_Global_Hierarchical_Grid_Final/HANDOFF_HIERARCHICAL_TO_MANRAJ.md`. The external hierarchical prototype advises retaining V3 and adds coordinate routing, not global measured heights. It is not merged into HEALPix or relabeled as HEALPix. These namespaces intentionally overlap spatially. No separate horizon package was found in the inspected Downloads inventory; the repository's terrain provider remains authoritative for implemented partial skylines.

The external audit's lack of independent Parquet reading is addressed by this session's PyArrow real-package checks. Its unverified observer altitude and missing uncertainty gates remain open. All source files stay unchanged. NASA globe texture uses an attributed third-party recompression because the official asset host was unreachable; `/moon/provenance.json` records delivery, hash and limitations. Texture is never used as scientific height.

## Current executed totals

198 backend tests passed, six explicitly skipped with real Site04 enabled. Separate fresh live Horizons test: 1 passed. Fresh Site04 integration made eight LIVE NASA queries, preserved raw responses and evaluated both dates/two cells successfully. Frontend production build and fixture/coordinate checks passed. Clean Python install: 194 passed / seven skipped at that checkpoint, before the three intent tests; final suite is the 198-test log. Clean frontend `npm ci` passed from its own working directory (initial `--prefix` attempt failed); build and tests passed. Docker and Windows execution remain unverified.
