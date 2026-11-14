# WISPR API CONTRACT v1 — FROZEN COMMON INTERFACE

**Owner:** Agent A / Platform. **Consumers:** All backend agents and frontend on laptop B. This is the initial shared interface. Workers MUST NOT independently change fields; send a contract-change request to Agent A. Implement real Pydantic models and OpenAPI in backend. Example data below is structural only. It is not NASA observations.

**Base:** `http(s)://<host>:<port>`; backend prefix `/api/v1`. `GET /health` is intentionally unprefixed. JSON `snake_case`, numeric angles in degrees, height in metres unless marked `_km`, all timestamps ISO-8601 UTC `Z`. East longitudes normalized to [0,360), latitudes [-90,90]. Duration in minutes/hours named explicitly. All APIs have examples in `/docs`.

## Shared provenance and quality fields (every scientific response)

```json
{
  "api_version": "v1",
  "backend_version": "0.1.0",
  "computed_at_utc": "2026-11-14T00:00:00Z",
  "source_type": "NASA_JPL_LIVE | NASA_JPL_VERIFIED_CACHE | NASA_LOLA_DEM | MIXED_VERIFIED | SYNTHETIC_TEST_ONLY | UNAVAILABLE",
  "calculation_mode": "GEOMETRIC_IDEAL | TERRAIN_PARTIAL | TERRAIN_UNAVAILABLE | NOT_CALCULATED",
  "data_quality": "MODEL_ESTIMATE | SOURCE_BACKED | PARTIAL | INSUFFICIENT_DATA | SYNTHETIC_TEST_ONLY",
  "limitations": [],
  "provenance": {"dataset_ids": [], "source_urls": [], "request_params": {}, "raw_sha256": [], "coordinate_frame": null, "sample_step_minutes": null}
}
```

Enum sets are suggestions for consistency; if a worker proposes alternatives, A must update once centrally. Never conflate *source-backed input data* with *fully verified engineering outcomes*. `NASA_JPL_VERIFIED_CACHE` means the actual raw NASA response plus its query metadata/hash was saved and checked, not that terrain, power or landing safety is certified.

## Core schemas

`Site`: `{ "site_id":"R01", "name":"Connecting Ridge", "lat_deg":-89.4632, "lon_east_deg":222.51, "reference_region_not_certified_site":true, "dem_site_id":"Site01", "dem_status":"AVAILABLE|PARTIAL|UNAVAILABLE|UNVERIFIED" }`.

`SkyPosition`: `{ "az_deg":123.4, "el_deg":-1.5, "east":0.0, "north":0.0, "up":0.0, "status":"KNOWN|UNKNOWN" }`. Direction fields are local ENU unit vector. Azimuth clockwise from north, elevation above ideal mathematical horizon. Values null if unknown, NEVER zero-filled.

`SyncedRecord`: `{ "timestamp_utc":"...Z", "sun":SkyPosition|null, "earth":SkyPosition|null, "status":"KNOWN|UNKNOWN", "gap_reason":null }`.

`VisibilityWindow`: `{ "start_utc":"...Z", "end_utc":"...Z", "duration_minutes":180.0, "kind":"SUN|EARTH|BOTH", "estimate_status":"MODEL_ESTIMATE|BRACKETED|UNKNOWN", "boundary_uncertainty_seconds":300, "model":"GEOMETRIC_IDEAL|TERRAIN_PARTIAL" }`. Windows are **estimated model intervals**, not physical proof between arbitrarily spaced samples. Do not report `BRACKETED` unless crossing support exists.

`ScenarioSummary`: `{ "scenario_id":"...", "site_id":"R01", "arrival_utc":"...Z", "end_utc":"...Z", "horizon_model":"GEOMETRIC|LOCAL_TERRAIN", "sun_windows":[], "earth_windows":[], "shared_windows":[], "longest_shared_minutes":null, "earliest_qualifying_window":null, "known_fraction":0.0, "unknown_fraction":1.0, "qualifying_status":"QUALIFIES|FAILS|UNKNOWN", "reason_codes":[], "visibility_series":[], "provenance":{}, "limitations":[] }`.

`Cell`: `{ "cell_id":"SP1KM:<ix>:<iy>", "grid_version":"south_polar_v1", "cell_size_m":1000, "center_lat_deg":-89.46, "center_lon_east_deg":222.5, "center_x_m":null, "center_y_m":null, "boundary_lonlat_east":[[222.4,-89.45],...], "raster_coverage":"AVAILABLE|PARTIAL|UNAVAILABLE|UNVERIFIED", "ephemeris_status":"EVALUATED|UNEVALUATED|UNKNOWN", "observations_represent_center_only":true }`. `center_x/y` are **canonical lunar south-polar projection** meters, never Earth CRS. Projection constants and datum must be documented and stable. Cell IDs derive from canonical projected integer cell indices, not screen pixel/grid row.

`PhysicalFeatures`: `{ "cell_id":"...", "scenario_id":"...", "feature_names":["sun_visible_fraction","earth_visible_fraction","shared_visible_fraction","longest_shared_hours","unknown_fraction","terrain_slope_deg"], "values":[null,null,null,null,null,null], "normalized_values":null, "normalization_version":"v1", "available_features":[], "missing_features":[], "similarity_eligible":false, "quality":"UNEVALUATED" }`. Do not impute missing features as zero or mix scenarios/time windows.

## Endpoints

### `GET /health`
Return `{ "status":"OK|DEGRADED|BLOCKED", "horizons_live":false, "cache_available":false, "dem_status_by_site":{"R01":"UNVERIFIED","R04":"UNVERIFIED"}, "llm_provider_status":"UNCONFIGURED", "warnings":[] }`. Status is operational diagnostics, not scientific certification.

### `GET /api/v1/sites`
Return `{ "sites":[Site, Site], ...common_metadata }`. Always include R01 and R04 reference labels with provenance warning if reference coords not independently validated.

### `GET /api/v1/grid?site_id=R01&radius_cells=1&cell_size_m=1000`
Return `{ "site_id":"R01", "grid_version":"south_polar_v1", "projection":{"name":"MOON_SOUTH_POLAR_STEREOGRAPHIC","wkt_or_proj": "...","axis_units":"metre", "reference_radius_m":null}, "cells":[Cell], "center_cell_id":"...", ...common_metadata }`. `radius_cells=1` means 3×3 around reference point. Bounded; only 1km initially. Do not query Horizons for all cells during grid render. The two local grids can be visualized separately/overlay on appropriate projection.

### `GET /api/v1/grid/{cell_id}`
Return `{ "cell":Cell, "static_features":{"elevation_m":null,"slope_deg":null,"data_status":"UNVERIFIED"}, "available_scenarios":[], ...common_metadata }`.

### `POST /api/v1/ephemeris`
Request:
```json
{
 "site_id":"R01", "lat_deg":null, "lon_east_deg":null,
 "start_utc":"2026-11-20T00:00:00Z", "end_utc":"2026-11-21T00:00:00Z",
 "step_minutes":5, "observer_height_m":1.0,
 "source_preference":"LIVE_THEN_VERIFIED_CACHE"
}
```
Use `site_id` **or** custom (`lat_deg`,`lon_east_deg`); ambiguous/conflicting input is 422. Request `site_id` may be a valid cell ID if provider explicitly supports it via lookup. Return `{ "site":Site|{"lat_deg":...,"lon_east_deg":...}, "records":[SyncedRecord], "observed_start_utc":..., "observed_end_utc":..., "missing_intervals":[], "step_minutes":5, ...common_metadata }`. Source distinction essential. Real JPL values only when retrieved/verified.

### `POST /api/v1/analyze`
Request:
```json
{ "site_ids":["R01"], "start_utc":"2026-11-20T00:00:00Z", "end_utc":"2026-11-21T00:00:00Z", "min_continuous_overlap_minutes":180, "horizon_model":"GEOMETRIC", "observer_height_m":1.0, "step_minutes":5 }
```
Return `{ "scenarios":[ScenarioSummary], ...common_metadata }`. For `LOCAL_TERRAIN` with incomplete horizon, report partial/unknown, NEVER silently substitute geometric eligibility. Geometric results can be supplied as a clearly separate comparison.

### `POST /api/v1/recovery` — MOST IMPORTANT ENDPOINT
Request:
```json
{
  "original_site_id":"R01",
  "original_arrival_utc":"2026-11-20T00:00:00Z",
  "study_duration_hours":24,
  "delay_hours":168,
  "min_continuous_overlap_minutes":180,
  "candidate_site_ids":["R01","R04"],
  "horizon_model":"GEOMETRIC",
  "observer_height_m":1.0,
  "step_minutes":5,
  "future_search_days":0
}
```
Response:
```json
{
  "request":{},
  "search_scope":{"site_ids":["R01","R04"],"original_arrival_utc":"...Z","delayed_arrival_utc":"...Z","study_duration_hours":24,"future_search_days":0},
  "original_scenarios":[ScenarioSummary, ScenarioSummary],
  "delayed_scenarios":[ScenarioSummary, ScenarioSummary],
  "ranked_eligible":[],
  "rejections":[],
  "unknowns":[],
  "recommended_outcome":"KEEP_SITE_AFTER_DELAY | SWITCH_SITE_AFTER_DELAY | POSTPONE_AND_REEVALUATE | NO_QUALIFYING_OPTION_WITHIN_SEARCH | INSUFFICIENT_DATA | NEEDS_INPUT",
  "recommended_site_id":null,
  "recommended_window":null,
  "advisory":"No actual mission command is issued",
  "ranking_criteria":["earliest_eligible_start_utc","longest_shared_duration","source_quality","site_id"],
  "scientific_disclaimer":"...",
  "api_version":"v1", "source_type":"UNAVAILABLE", "calculation_mode":"NOT_CALCULATED", "data_quality":"INSUFFICIENT_DATA", "limitations":[], "provenance":{}
}
```
The literal `ScenarioSummary` above denotes the full schema, not a JSON instance. Rank only among eligible, adequately sourced, comparable candidates. If unknown matters, do not claim `NO_QUALIFYING_OPTION` as certain. "Cancel" means advisory `CONSIDER_RESCHEDULE_OR_CANCEL_PLAN` in explanation, not mission control action.

### Terrain endpoints
- `GET /api/v1/terrain/{site_id}/metadata` → source dataset URL/ID, raster `CRS` WKT, X/Y/z units, NoData, footprint, resolution, verified footprint status, vertical datum, coverage, uncertainty references, provenance.
- `GET /api/v1/terrain/{site_id}/heightmap?size_m=1000&max_points=128` → `{ "origin_x_m":...,"origin_y_m":...,"dx_m":...,"dy_m":...,"z_m":[[...]],"nodata_mask":[[...]],"projection":{},"source":{},"coverage":"...", ...common_metadata }`. Heightmap is actual sampled DEM if present. This is the payload for a later Three.js terrain mesh, not an image.
- `GET /api/v1/terrain/{site_id}/horizon?observer_height_m=1&az_step_deg=5` → `{ "azimuth_samples":[{"azimuth_deg":0,"terrain_horizon_elevation_deg":null,"coverage":"UNKNOWN|PARTIAL|COVERED","uncertainty_deg":null}], "max_supported_radius_m":..., "far_field_complete":false, ...common_metadata }`. Local terrain coverage ≠ true full-horizon clearance. Known blocking may be asserted when the local DEM is trustworthy. Null means unknown.

### LLM and search
- `POST /api/v1/interpret`: `{ "text":"...", "provider_preference":"groq|nvidia|auto|manual" }` → `{ "parsed_requirements":{same relevant request fields as RecoveryRequest, null if missing}, "needs_clarification":true|false,"missing_fields":[],"provider_used":"groq|nvidia|manual|unavailable","validation_errors":[], ...common_metadata }`.
- `POST /api/v1/search`: **same body as `/api/v1/recovery`**; deterministic search even with no LLM configured. LLM-translated requirements must be Pydantic-validated before use. For free-text direct search, call `/interpret` first client-side or via orchestrator, then `/search`.

### Feature-space endpoints
- `GET /api/v1/features?scenario_id=<id>` → `{ "scenario_id":"...","feature_definitions":[{"name":"sun_visible_fraction","unit":"fraction","direction":"higher_better"},...],"points":[PhysicalFeatures],"scatter_axes":{"x":"sun_visible_fraction","y":"longest_shared_hours","z":"earth_visible_fraction"},"normalization":{},"ignored_or_missing":[], ...common_metadata }`.
- Optional `POST /api/v1/features/similar`: `{ "scenario_id":"...","reference_cell_id":"...","max_results":5,"required_eligibility":true }` → rank only complete comparable vectors after hard eligibility filters, return distance/similarity+method and exclusions.

### Optional export
- `GET /api/v1/export/{scenario_id}.csv`: CSV with timestamp and units, source ID/hash and a JSON provenance sidecar if supported.

## Error contract

- Request validation/missing date: HTTP 422 JSON `{ "error_code":"INVALID_REQUEST|NEEDS_INPUT", "detail":"...", "missing_fields":[] }`.
- NASA temporarily unavailable but cached data exists: serve **verified cached** results with exact source and cache freshness; don't pretend live.
- NASA/DEM unavailable with no valid cache: HTTP 503 JSON `{ "error_code":"SOURCE_UNAVAILABLE|TERRAIN_UNAVAILABLE", "detail":"...", "fallback":"GEOMETRIC_IF_USER_APPROVES|NONE" }` or return an explicit `INSUFFICIENT_DATA` scenario where product can show it. No fake success.
- Unknown scientific outcome is a valid 200 JSON `recommended_outcome=INSUFFICIENT_DATA`, not a server crash.

## Independence rules for frontend

Frontend is allowed to use `mocks/*.json` while API is being built. **Every mock must show the badge/text `SYNTHETIC EXAMPLE — NOT NASA DATA`**; never use mock angles to claim real lunar science. Frontend type/interfaces should match these field names. Never send Groq/NVIDIA keys to browser. `localhost` on separate laptop cannot reach the backend running on another laptop; configure reachable LAN/backend URL and CORS during integration.

## Versioning rule

Freeze field names and response structure for V1. A may add optional fields without breaking consumers. Any change to enum/value/required fields must be documented, discussed and communicated to the frontend agent before merge. Provide generated OpenAPI at `/openapi.json` and `/docs`.
