# Executed verification — November 14, 2026

Environment: Windows, CPython 3.15.2, repository `backend/uv.lock`, installed using
`uv sync --locked --extra celestial --extra test --extra lint`. Repository requirement
remains Python 3.12+. CI is configured for 3.12/3.13; those CI runs are not local evidence.

- Complete backend offline regression suite: **146 passed**, one live test deselected.
- Real NASA integration: **1 passed** (four sequential HTTP queries: Sun/Earth full week,
  then Sun/Earth separately parameterized two-row midpoint interval).
- Ruff lint: all checks passed. Ruff format: 18 Python files already formatted.
- Live full-week observations: 169 for Sun and 169 for Earth, UTC November 15 00:00 through
  November 22 00:00, 2026, 60-minute step. No missing or invalid observations.
- API TestClient equality and JSON/Parquet round trips passed in the live test.
- Separate actual uvicorn HTTP server: health 200, ephemeris 200 with 169 identical saved
  NASA records, invalid coordinates 422, OpenAPI routes present. Server stopped after test.
- Shorter November 18 12:00–13:00 queries matched full-week records exactly for both bodies.
- A nonblocking Starlette deprecation warning requests a future test-transport migration;
  no test failed because of this warning.

## Actual NASA sample

All four angular columns are degrees. Location -89° latitude, 45° east longitude, altitude
0 km above the Horizons lunar reference sphere. These are source-backed apparent angles,
not terrain-cleared visibility claims.

| Timestamp UTC | Sun azimuth | Sun elevation | Earth azimuth | Earth elevation |
|---|---:|---:|---:|---:|
| 2026-11-15 00:00 | 69.459630327 | 1.907460447 | 312.418268310 | -2.878732303 |
| 2026-11-18 12:00 | 26.844994417 | 2.441797402 | 308.344727825 | 1.758790924 |
| 2026-11-22 00:00 | 344.299966960 | 2.499038676 | 308.540643429 | 5.960842986 |

Sun elevation range: 1.907460447–2.542208569°. Earth elevation range:
-2.878732303–5.960842986°. Maximum successive hourly Sun azimuth change, wrapped through
north: 0.507660869°; Sun elevation change 0.008250244°. Corresponding Earth values:
0.058445936° and 0.058285818°. The Sun passes through azimuth zero; this is not a 360°
discontinuity. These smooth ranges and small polar solar elevations are plausible
diagnostics for this interval, not a proof of mission accuracy.

NASA live headers were checked for Sun 10 / Earth 399, Moon 301, positive-east observer
longitude 45°, latitude -89°, reference height approximately zero (reported rounding
-1.92937e-13 km), lunar radii 1737.4 km, MEAN_ME orientation, DE441 source, UTC/UT labeling,
airless apparent angular labels and exact cadence. Raw headers and source URLs are retained.

Full-week Sun raw SHA-256:
`c107cff4ef0a321e735e043e9b4c41db3ff911c1b89051fa78f4021933ebeabc`

Full-week Earth raw SHA-256:
`f48a065b931aca66cbf98dec0bbf8f054e1febce0ef089377581902f0752ffbb`

Retrieved at 2026-11-14T11:51:26.460861+00:00 and
2026-11-14T11:51:27.648687+00:00 respectively. Exact queries, headers and retrieval times
are in `fixtures/*.capture.json` and `outputs/query_metadata.json`.

## Issues found and resolved

The first live attempt failed closed because actual NASA signature 1.2 and expanded
column/frame labels differed from the current version-1.3 documentation. Authentic raw
captures established the observed format; explicit supported aliases were added.

The first combined offline run found a pre-existing Windows checkout issue: Git CRLF
conversion invalidated raw fixture SHA-256 values. Scoped `.gitattributes` now preserves
NASA JSON bytes. Legacy fixture content matches HEAD; grid and terrain files are unchanged.
An early staging-only test run also lacked the application's import path; integrated
tests now run under the existing backend with importlib test discovery.

## Scope and limits

Synthetic grid records and deliberately corrupted response tests are software interface
tests only. No real DEM was integrated. No terrain obstruction, illumination windows,
power assessment, link-budget analysis or landing recommendation was validated.
The independent shorter query uses the same NASA service and physical model; it does not
establish independent numerical-model accuracy. The service is a research prototype.
