# WISPR Celestial Engine

Source-backed NASA/JPL Horizons Sun/Earth observer ephemerides for lunar locations.
Research prototype: no flight certification, terrain visibility or landing eligibility claims.
The sample location (-89°, 45° east) is a software integration example, not a selected landing site.

## Architecture and integration

`schemas.py` validates requests → `celestial_service.py` requests Sun then Earth →
`horizons_client.py` handles NASA access and exact-query cache → `ephemeris_parser.py`
checks the response identity, labeled columns, frame and coordinates →
`data_validation.py` aligns by UTC timestamps → `export_result` writes physical-unit datasets.
`grid_adapter.py` provides a bounded, independent interface to terrain grid cells.
`api.py` is included in the existing `app.main:app` FastAPI application.

Existing `/api/v1/ephemeris`, analysis, recovery, frontend and grid contracts remain intact.
The legacy provider shares a process-wide upstream lock with this module. Its cached data
and parser remain separate. No terrain or grid implementation was changed.

## Official NASA references and assumptions

- [Horizons overview](https://ssd.jpl.nasa.gov/horizons/)
- [API documentation](https://ssd-api.jpl.nasa.gov/doc/horizons.html)
- [Manual](https://ssd.jpl.nasa.gov/horizons/manual.html), observer coordinates, lunar frame, quantity 4
- [Fair use policy](https://ssd-api.jpl.nasa.gov/doc/)
- [API endpoint](https://ssd.jpl.nasa.gov/api/horizons.api)

Documentation reviewed November 14, 2026. The documentation states API version 1.3;
the actual recorded responses report 1.2. Both are explicitly supported; unknown API
versions fail closed pending documentation review. Actual live output uses `MEAN_ME`,
`Azimuth_(a-app)` and `Elevation_(a-app)`; documented `MOON_ME` and abbreviated angle
labels are also accepted. Columns are selected by validated labels, never blind offsets.
See `fixtures/*.capture.json`, exact raw bytes, and output query metadata for evidence.

Coordinates: planetodetic latitude [-90,90], positive-east longitude [0,360), altitude km
above Horizons' lunar reference surface. Live headers report a 1737.4 km reference sphere,
`MEAN_ME (high precision)`, DE441 ephemerides and east-positive longitude.
The manual defines the lunar surface frame as DE421 mean-Earth/polar-axis, distinct from
the DE440 principal-axis frame. We verify the actual center-body/frame/radius/coordinates
in each response and preserve the complete output header. No Earth EPSG datum is used.
Grid DEM elevations are not presumed compatible with this sphere or frame.

`QUANTITIES=4` is **airless apparent** target-center azimuth/elevation, including light-time,
aberration and deflection corrections. It is not an uncorrected geometric-vector output.
Azimuth is clockwise north→east, degrees [0,360). Elevation is [-90,90] relative to the
plane perpendicular to the local reference-surface normal. Positive elevation alone
establishes neither unobstructed sunlight nor a usable Earth communications link.

Modern Horizons UT is interpreted as UTC. Requests require explicit Z/+00:00 and whole
minutes, supported years 1900–2100. Do not extend this interpretation to ancient UT1 dates.
No locally approximated astronomy, interpolation or fabricated values is used.

## Installation and configuration

Use Python 3.12+ (repository requirement). From `backend/`:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e '.[celestial,test,lint]'
# Reproducible alternative, with uv installed:
uv sync --locked --extra celestial --extra test --extra lint
.\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

Dependencies: existing FastAPI, Pydantic 2, httpx, truststore and uvicorn; the `celestial`
extra adds PyArrow. pytest and Ruff are test/lint extras. No database, pandas, NumPy or
SPICE installation is needed for this service. `uv.lock` records resolved versions.

`CELESTIAL_CACHE_DIR` defaults to `backend/data/celestial` when run from backend.
`CELESTIAL_USER_AGENT` may override the product/version/repository-contact User-Agent;
operators should supply their deployment's monitored contact. No API key is needed.
The backend's existing CORS configuration is used. Frontends call WISPR, not NASA.

Use one backend worker/process for NASA access: the shared lock coordinates threads
within that process, not separate processes or other applications. Cache exact results,
avoid large terrain sweeps, and follow NASA fair-use guidance. A deployment with multiple
workers needs a shared request queue and distributed gate before enabling upstream access.

HTTP timeouts: 10 s connection / 45 s per other httpx phase. At most three attempts by
default (configurable maximum five), exponential backoff capped at 60 s, retryable network
errors and HTTP 429/500/502/503/504. Query/format errors are not retried. Failed scientific
payloads are retained under `rejected/`. No TLS verification bypass is used.

Cache entries retain raw response, SHA-256, parameters, parser/API versions, retrieval time
and NASA header. Reuse checks hash, parameters and the current parser again. Delivery
is labeled LIVE or VERIFIED_CACHE per target. Cache is an archive with no automatic TTL;
retrieval time stays visible. Remove entries to refresh against later JPL solutions.
Hashes detect accidental corruption, not malicious local rewriting. Monitor disk usage
and apply operator retention limits to raw/rejected archives.

## Run and export the requested sample

```powershell
.\.venv\Scripts\python -m celestial_engine --output celestial_engine/outputs
# Same exact cached query, fail without a validated cache:
.\.venv\Scripts\python -m celestial_engine --offline --output celestial_engine/outputs
```

The CLI explicitly runs the November 15–22, 2026 example. Library/API callers supply their
own validated `EphemerisRequest`. The service returns an `EphemerisResult`; use
`export_result(result, directory)` to save it. API requests do not write an export file
automatically; raw successful NASA responses are cached.

Exports:

- `outputs/sample_ephemeris.parquet`: typed UTC timestamp, float64 physical angles and
  coordinates, booleans and string quality; full metadata in `wispr_metadata`.
- `outputs/sample_ephemeris.json`: `{records, metadata}`, ISO UTC Z timestamps.
- `outputs/query_metadata.json`: units, feature names, source, exact parameters,
  coordinates/reference, start/end, retrieval times, hashes, headers and processing version.

Canonical values retain degrees/km, with no normalization, lossy compression or imputation.
Parquet compression is disabled. Missing observations remain null, explicitly invalid,
and retain their requested timestamp. Off-cadence, duplicate, out-of-range or malformed
observations are rejected. Sun/Earth joins are by timestamp, never by row index.

## API and schema

Interactive docs: `http://127.0.0.1:8000/docs`; OpenAPI: `/openapi.json`.

`POST /api/v1/celestial/ephemeris`:

```json
{
  "latitude_deg": -89.0,
  "longitude_east_deg": 45.0,
  "altitude_km": 0.0,
  "altitude_reference": "horizons_lunar_reference",
  "start_utc": "2026-11-15T00:00:00Z",
  "end_utc": "2026-11-22T00:00:00Z",
  "step_minutes": 60
}
```

Response excerpt from actual NASA data (remaining rows and metadata omitted):

```json
{
  "records": [{
    "timestamp_utc": "2026-11-15T00:00:00Z",
    "sun_azimuth_deg": 69.459630327,
    "sun_elevation_deg": 1.907460447,
    "earth_azimuth_deg": 312.41826831,
    "earth_elevation_deg": -2.878732303,
    "latitude_deg": -89.0,
    "longitude_east_deg": 45.0,
    "altitude_km": 0.0,
    "source": "NASA_JPL_HORIZONS",
    "valid": true,
    "quality": "SOURCE_BACKED"
  }]
}
```

`metadata` is required in the complete response and includes `queries.sun/earth`,
`request`, `feature_names`, `units`, `coordinate_reference`, `time_standard`,
`target_timestamp_sets_match`, `missing_observations`, `data_quality`, `limitations`.
Each row has the fields shown above. Four nullable angle fields support missing values.
The example returns 169 inclusive rows across 168 hourly intervals.

`GET /api/v1/celestial/health` is a local liveness endpoint, explicitly `horizons_status=NOT_PROBED`;
it does not claim upstream reachability or scientific readiness.

Errors: HTTP 422 `{error_code: INVALID_REQUEST, detail: [...], missing_fields: []}` via
existing application validation; HTTP 503 `{error_code: SOURCE_UNAVAILABLE, detail: ...,
fallback: NONE}` for NASA/query/format failure; local storage failure uses CACHE_UNAVAILABLE.
Partial valid source tables can return 200 with null rows and PARTIAL metadata.
There is no synthetic-data fallback. Interval must be a positive integer number of steps,
at most 31 days and 10000 inclusive samples. Altitude service bounds are -10 to 100 km.

## Tests and evidence

```powershell
.\.venv\Scripts\python -m pytest -m 'not live'
.\.venv\Scripts\ruff check celestial_engine
.\.venv\Scripts\ruff format --check celestial_engine
$env:WISPR_LIVE_TEST='1'
.\.venv\Scripts\python -m pytest celestial_engine/tests/test_live_horizons.py -q
```

For Windows systems with short-path limits, add `--basetemp C:\tmp\wispr-tests` using an
existing writable parent. Offline tests use authentic recorded NASA fixtures and explicitly
synthetic corruption/grid interface tests. They never certify terrain or NASA authenticity
merely from synthetic values. Scoped `.gitattributes` preserves raw fixture checksums.
The live test requires a fresh NASA query, checks 169 aligned valid rows, numerical ranges,
cadence/smoothness diagnostics, Parquet/JSON round trips, API equality, then independently
queries a shorter interval at November 18 12:00–13:00 and compares both targets exactly.
These same-source cross-checks are not independent ephemeris-model validation.
See `VERIFICATION.md` for executed results and actual angular ranges.

## Grid and future terrain integration

See `HANDOFF.md`. Inputs preserve original string IDs and extra cell fields; metadata must
declare frame, coordinate convention, elevation units and datum. Valid cells are evaluated
sequentially in bounded batches, with identical requested UTC cadence. Grid processing is
never triggered by rendering the existing grid endpoint. Missing/rejected data is explicit.

Future Terrain Horizon Engine should compare these apparent directions with a verified
azimuth-dependent terrain horizon in the same local reference. Sun disk angular size,
sampling uncertainty, refraction assumptions, spacecraft height, far-field terrain and
reference-frame consistency need explicit treatment. Power requires illumination duration,
array orientation and system models; communications requires line of sight plus link budget,
antenna pointing and network availability. Neither belongs in this module's angle dataset.

For large grids, replace the upstream provider with a local NASA SPICE implementation:
pin/checksum planetary SPKs, lunar orientation binary/text PCKs, frame kernels, leap-second
LSK and required constants; transform validated grid coordinates into the selected lunar
frame, convert UTC↔ET and calculate observer-target directions with explicitly matched
aberration settings. Preserve kernel versions/coverage, raw physical units and quality.
Validate selected cells/times against Horizons before using local results. ME/PA transforms,
time coverage and datum consistency must be resolved first. No SPICE implementation or
NASA-scale terrain sweep is claimed here. Deployments still need authentication, resource
quotas, cache retention, monitoring and coordinated upstream access before public exposure.
