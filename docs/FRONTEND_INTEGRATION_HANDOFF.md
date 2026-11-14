# WISPR frontend integration handoff

The stable interface is the existing `/api/v1/science` namespace. No frontend layout or appearance changes are included. Scientific response models now validate outgoing payloads without dropping original cell or provider metadata. Legacy routes retain their contracts.

## Authoritative contract artifacts

- [OpenAPI export](contracts/science.openapi.json): the exact application schema, including every science request, response, limit and error schema. The running server serves the same object at `/openapi.json`.
- [Generated TypeScript](contracts/science.generated.ts): generated directly from that schema, including `ScienceOperations` keyed by method and full path. Do not manually edit generated files.
- [Exact tested HTTP requests and responses](evidence/unified/final_api_examples.json): each `examples[]` entry includes method, path, request body, status, selected headers and the complete response. The `name` lookup below identifies each endpoint's example. These are actual TCP HTTP requests against uvicorn with the real V3 package, not fabricated documentation payloads.
- [Scientific verification](SCIENTIFIC_BACKEND_VERIFICATION.md): data checks, test results, CI and release limitations.

From `backend`, regenerate using `uv run --no-sync python -m scripts.export_science_contract`; verify with `--check`. CI checks for schema/type drift. TypeScript carries nullable values and declared unions; numerical bounds and UTC validation remain authoritative in OpenAPI. Source-specific `source`, `uncertainty`, geometry and provider extension dictionaries remain extensible JSON, rather than receiving invented fields.

## Local startup

From the repository root, using Python 3.12 or 3.13 and uv:

```powershell
cd backend
uv sync --locked --extra celestial --extra test --extra lint --extra terrain
$env:WISPR_GRID_DIR='C:\Users\manra\Downloads\WISPR_Site04_Tiled_Provenance_V3\WISPR_Site04_Tiling_V3'
$env:CORS_ORIGINS='http://localhost:5173,http://127.0.0.1:5173'
uv run --no-sync python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The Windows data path is a local example, not embedded in application code. Set `WISPR_GRID_DIR` to the actual installed package location. No grid assets are downloaded automatically. Discovery loads once per process; restart after replacing datasets. Run one backend worker for the process-local scenario store. Verified NASA responses persist under `CELESTIAL_CACHE_DIR` (default `backend/data/celestial` when launched here).

For a Linux shell, set the same variables with `export`. The app supports a comma-separated `CORS_ORIGINS`. Allowed local-origin POST/JSON preflight was verified; untrusted-origin preflight is rejected. CORS is not authentication.

## Tested quick start

```powershell
$base='http://127.0.0.1:8000'
$dataset='SITE04_NW_ORIGIN_PRESERVED_2KM_100M__tiles_3.0.0'
$cell='SITE04_R000_C000'
Invoke-RestMethod "$base/api/v1/science/datasets"
Invoke-RestMethod "$base/api/v1/science/datasets/$dataset/cells/$cell"
Invoke-RestMethod "$base/api/v1/science/datasets/$dataset/vectors/$cell"
$scenario=@{
  dataset_id=$dataset
  cell_ids=@('SITE04_R000_C000','SITE04_R000_C001')
  start_utc='2026-11-15T00:00:00Z'
  end_utc='2026-11-22T00:00:00Z'
  step_minutes=60
  minimum_shared_minutes=60
  altitude_km=0
  horizon_model='GEOMETRIC_IDEAL'
  filters=@{qualities=@('source_lola_count_and_uncertainty_not_supplied')}
}
Invoke-RestMethod "$base/api/v1/science/celestial" -Method Post -ContentType 'application/json' -Body ($scenario | ConvertTo-Json -Depth 10)
$delay=$scenario.Clone()
$delay.original_cell_id=$cell
Invoke-RestMethod "$base/api/v1/science/delay" -Method Post -ContentType 'application/json' -Body ($delay | ConvertTo-Json -Depth 10)
```

Do not hard-code the example dataset ID in a production client; choose it from discovery. In this V3 package the immutable **grid_version is 2.0.0**, while **processing_version is 3.0.0**. Both must remain visible. The example explicitly accepts the dataset's documented missing uncertainty/shot-count quality state. With the default VERIFIED-only filter, these real cells correctly produce no qualifying candidates; do not silently override that decision.

## Source and scientific semantics

- `StaticVector.feature_names` is exactly `[elevation_m, slope_deg, roughness_m]`; `raw` preserves physical units, `normalized` uses fixed scales `[1000,10,10]`. `missing_mask`, `quality`, `normalization`, and `provenance` are part of the contract. Normalized values are not safety scores.
- `cell.latitude_deg`/`longitude_deg` retain source values. `DynamicVector.observer` identifies the actual converted Horizons request coordinates; projected geometry carries the original lunar CRS and metre units. Never treat it as Earth WGS84 GeoJSON.
- `DynamicVector.provenance.queries.sun/earth` includes query parameters, source URL, SHA256, retrieval time, delivery LIVE/VERIFIED_CACHE and validated NASA header. The source geometry uses airless apparent target centers.
- `horizon_model=GEOMETRIC_IDEAL` means visibility above an ideal local plane. It does not establish terrain clearance, electrical power, communications connectivity or landing safety. `TERRAIN_PARTIAL` remains diagnostic; unsupported directions and unverified height-reference alignment remain unknown.
- Fractions refer to modeled visible duration divided by the full requested interval. Incomplete coverage makes available fractions lower bounds. Never turn null into zero. Hourly interpolation carries one-cadence timing uncertainty; tiny ordering differences do not establish a meaningful site advantage.
- Original DEM elevation is never used as Horizons observer altitude. `altitude_km` refers to the Horizons lunar reference; `observer_height_m` applies to terrain diagnostics only. The source package's vertical reference is not verified compatible with Horizons.

## Loading, bounds and missing states

List endpoints use `offset` (>=0) and `limit` (1–1000, default 100); use 50–100 cells per UI page. Dataset discovery, cell pages and candidates include `total`. Candidate ordering is original ID ascending. Bboxes use ordered east-positive [-180,180] bounds; split antimeridian queries. `filters.offset/limit` paginate candidate selection, but do not remove IDs explicitly supplied for analysis.

Analysis is synchronous, not a background job protocol. Show a loading state while a selected-cell POST runs; initially evaluate one or two candidates. Do not query NASA for every grid cell. Each scenario allows at most 16 IDs, 20,000 total inclusive samples, 10,000 samples per cell, 31 days, and a cadence of 1–1440 whole minutes. The interval must be divisible by cadence. Both timestamps must have explicit zero UTC offset and whole minutes. Seven-day delay evaluates two intervals with the same settings. The backend permits two concurrent analysis jobs per process and returns 429 on overload.

Keep large record arrays out of repeated UI copies. Read summary features and comparison first; retain full source records only where needed. Use `GET /scenarios/{scenario_id}` after analysis/celestial/ranking for stored dynamic vectors. Only the latest 16 responses are retained per process; restart or eviction gives 404. Delay returns full original/delayed bodies but does not publish nested scenario IDs. Scenario IDs are opaque evidence identifiers, not a promise of stable IDs across live/cache deliveries.

Use an explicit client timeout appropriate to NASA requests and selected batch size. Aborting browser fetch does not necessarily stop work already running on the backend. Retry a 429 with bounded backoff; do not automatically repeat a long successful analysis merely to fetch its vectors.

Distinguish these successful HTTP response states:

| Field/state | Frontend handling |
|---|---|
| datasets.status=MISSING_GRID_ASSETS | Show data-configuration problem and ingestion_errors; no fixture fallback |
| combined result NOT_EVALUATED | Display engineering_constraint_failures/reasons; dynamic_vector is null |
| combined result UNKNOWN | NASA/cache unavailable; show reasons and no dynamic vector |
| dynamic missing_data=true | Show unknown fraction and intervals; do not rank as complete |
| visibility modeled_visible=null | Unknown, not hidden or visible |
| TERRAIN_PARTIAL / INCOMPLETE_HORIZON_COVERAGE | Preserve explicit incomplete coverage label |
| UNKNOWN_OBSERVER_REFERENCE | Terrain and celestial observer references cannot be aligned |
| empty comparison.ranked | Display excluded reasons; do not invent a winner |

The delay endpoint's outcome union is exactly KEEP, SWITCH, NO QUALIFYING MODELED OPTION, INSUFFICIENT DATA. POSTPONE belongs to the legacy recovery contract, not this endpoint. KEEP means the original delayed location meets the explicitly supplied constraints, not that it is universally best or safe.

## Error contract

Science 404/422/429 errors use `ScienceError`: `{error_code, detail, missing_fields}`. `detail` is either a string or validation items `{loc: (string|number)[], msg: string}[]`. Existing `detail` remains available. Codes: NOT_FOUND, INVALID_SCIENTIFIC_REQUEST, CAPACITY_EXCEEDED; request-schema validation uses INVALID_REQUEST. An unevaluated NASA source can return HTTP 200 with a cell UNKNOWN state; check both HTTP and per-cell status. Unexpected server/transport failures may not be JSON and must remain errors.

No real API failure is allowed to select synthetic data. The backend has no such fallback; the UI must not add one. Handle errors explicitly, for example:

```typescript
import type { ScienceError } from '../docs/contracts/science.generated';
async function scientificRequest<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  const payload: unknown = response.headers.get('content-type')?.includes('application/json')
    ? await response.json() : await response.text();
  if (!response.ok) {
    const error = payload as Partial<ScienceError>;
    throw new Error(typeof error?.detail === 'string'
      ? error.detail : `Scientific API failed (${response.status})`);
  }
  return payload as T; // Server validates the published response model.
}
```

## Endpoint-by-endpoint contract

The sections below refer to complete response definitions in the generated OpenAPI and TypeScript files; no alternative shortened response shape is introduced. Exact response payloads are linked by `examples[].name` in the HTTP evidence file. Use that entry's `response` unchanged as the example response.

### `GET /api/v1/science/datasets`

Parameters (exact constraints in OpenAPI):

```json
[
  {
    "in": "query",
    "name": "offset",
    "required": false,
    "schema": {
      "default": 0,
      "minimum": 0,
      "title": "Offset",
      "type": "integer"
    }
  },
  {
    "in": "query",
    "name": "limit",
    "required": false,
    "schema": {
      "default": 100,
      "maximum": 1000,
      "minimum": 1,
      "title": "Limit",
      "type": "integer"
    }
  }
]
```

Exact 200 response schema: `DatasetPage` in [OpenAPI](contracts/science.openapi.json) (`#/components/schemas/DatasetPage`) and [TypeScript](contracts/science.generated.ts). All nested types are included there.

Response fields: `datasets`, `ingestion_errors`, `limit`, `offset`, `status`, `total`.

Metadata includes source, grid/processing versions, frame, resolution, synthetic flag and dataset SHA256. Limit <=1000, offset >=0. Empty discovery is a 200 with MISSING_GRID_ASSETS; invalid pagination is 422.

Tested request:

```http
GET /api/v1/science/datasets?offset=0&limit=100

```

Exact tested example response (HTTP 200): [HTTP evidence](evidence/unified/final_api_examples.json), `examples.find(e => e.name === "datasets").response`. This is the complete payload, including source metadata and arrays; nothing is elided or replaced.

### `GET /api/v1/science/datasets/{dataset_id}/cells`

Parameters (exact constraints in OpenAPI):

```json
[
  {
    "in": "path",
    "name": "dataset_id",
    "required": true,
    "schema": {
      "title": "Dataset Id",
      "type": "string"
    }
  },
  {
    "in": "query",
    "name": "offset",
    "required": false,
    "schema": {
      "default": 0,
      "minimum": 0,
      "title": "Offset",
      "type": "integer"
    }
  },
  {
    "in": "query",
    "name": "limit",
    "required": false,
    "schema": {
      "default": 100,
      "maximum": 1000,
      "minimum": 1,
      "title": "Limit",
      "type": "integer"
    }
  }
]
```

Exact 200 response schema: `CellPage` in [OpenAPI](contracts/science.openapi.json) (`#/components/schemas/CellPage`) and [TypeScript](contracts/science.generated.ts). All nested types are included there.

Response fields: `cells`, `limit`, `offset`, `total`.

Cells preserve source, uncertainty, quality, neighbors, projected geometry and extra original fields. Limit <=1000, offset >=0; unknown dataset 404, invalid pagination 422.

Tested request:

```http
GET /api/v1/science/datasets/SITE04_NW_ORIGIN_PRESERVED_2KM_100M__tiles_3.0.0/cells?offset=0&limit=2

```

Exact tested example response (HTTP 200): [HTTP evidence](evidence/unified/final_api_examples.json), `examples.find(e => e.name === "cells_page").response`. This is the complete payload, including source metadata and arrays; nothing is elided or replaced.

### `GET /api/v1/science/datasets/{dataset_id}/cells/{cell_id}`

Parameters (exact constraints in OpenAPI):

```json
[
  {
    "in": "path",
    "name": "dataset_id",
    "required": true,
    "schema": {
      "title": "Dataset Id",
      "type": "string"
    }
  },
  {
    "in": "path",
    "name": "cell_id",
    "required": true,
    "schema": {
      "title": "Cell Id",
      "type": "string"
    }
  }
]
```

Exact 200 response schema: `CellResponse` in [OpenAPI](contracts/science.openapi.json) (`#/components/schemas/CellResponse`) and [TypeScript](contracts/science.generated.ts). All nested types are included there.

Response fields: `cell`, `dataset_sha256`, `metadata`.

Returns cell plus metadata and dataset_sha256. Unknown dataset/cell 404. No pagination; one original cell.

Tested request:

```http
GET /api/v1/science/datasets/SITE04_NW_ORIGIN_PRESERVED_2KM_100M__tiles_3.0.0/cells/SITE04_R000_C000

```

Exact tested example response (HTTP 200): [HTTP evidence](evidence/unified/final_api_examples.json), `examples.find(e => e.name === "cell").response`. This is the complete payload, including source metadata and arrays; nothing is elided or replaced.

### `GET /api/v1/science/datasets/{dataset_id}/vectors/{cell_id}`

Parameters (exact constraints in OpenAPI):

```json
[
  {
    "in": "path",
    "name": "dataset_id",
    "required": true,
    "schema": {
      "title": "Dataset Id",
      "type": "string"
    }
  },
  {
    "in": "path",
    "name": "cell_id",
    "required": true,
    "schema": {
      "title": "Cell Id",
      "type": "string"
    }
  }
]
```

Exact 200 response schema: `StaticVector` in [OpenAPI](contracts/science.openapi.json) (`#/components/schemas/StaticVector`) and [TypeScript](contracts/science.generated.ts). All nested types are included there.

Response fields: `cell_id`, `dataset_id`, `feature_names`, `grid_version`, `missing_mask`, `normalization`, `normalized`, `provenance`, `quality`, `raw`, `units`, `valid`.

Returns physical raw and normalized values separately, units, missing mask, quality and provenance. Unknown dataset/cell 404. No pagination; one static vector.

Tested request:

```http
GET /api/v1/science/datasets/SITE04_NW_ORIGIN_PRESERVED_2KM_100M__tiles_3.0.0/vectors/SITE04_R000_C000

```

Exact tested example response (HTTP 200): [HTTP evidence](evidence/unified/final_api_examples.json), `examples.find(e => e.name === "static_vector").response`. This is the complete payload, including source metadata and arrays; nothing is elided or replaced.

### `GET /api/v1/science/datasets/{dataset_id}/similarity/{cell_id}`

Parameters (exact constraints in OpenAPI):

```json
[
  {
    "in": "path",
    "name": "dataset_id",
    "required": true,
    "schema": {
      "title": "Dataset Id",
      "type": "string"
    }
  },
  {
    "in": "path",
    "name": "cell_id",
    "required": true,
    "schema": {
      "title": "Cell Id",
      "type": "string"
    }
  },
  {
    "in": "query",
    "name": "limit",
    "required": false,
    "schema": {
      "default": 20,
      "maximum": 1000,
      "minimum": 1,
      "title": "Limit",
      "type": "integer"
    }
  }
]
```

Exact 200 response schema: `SimilarityResponse` in [OpenAPI](contracts/science.openapi.json) (`#/components/schemas/SimilarityResponse`) and [TypeScript](contracts/science.generated.ts). All nested types are included there.

Response fields: `comparability`, `matches`, `metric`, `reference_cell_id`.

Default limit 20, maximum 1000. Unknown dataset/cell 404; incompatible evidence 422. Real V3 correctly rejects similarity because uncertainty/shot-count evidence is missing; no successful real-data similarity response is fabricated. The exact successful response shape is SimilarityResponse.

Tested request:

```http
GET /api/v1/science/datasets/SITE04_NW_ORIGIN_PRESERVED_2KM_100M__tiles_3.0.0/similarity/SITE04_R000_C000

```

Exact tested example response (HTTP 422): [HTTP evidence](evidence/unified/final_api_examples.json), `examples.find(e => e.name === "similarity_quality_rejection").response`. This is the complete payload, including source metadata and arrays; nothing is elided or replaced.

```json
{
  "error_code": "INVALID_SCIENTIFIC_REQUEST",
  "detail": "Resolution, full coverage, verified quality and uncertainty required for similarity",
  "missing_fields": []
}
```

### `POST /api/v1/science/datasets/{dataset_id}/candidates`

Parameters (exact constraints in OpenAPI):

```json
[
  {
    "in": "path",
    "name": "dataset_id",
    "required": true,
    "schema": {
      "title": "Dataset Id",
      "type": "string"
    }
  }
]
```

Request body schema: `Filters`.

Exact 200 response schema: `CandidateResponse` in [OpenAPI](contracts/science.openapi.json) (`#/components/schemas/CandidateResponse`) and [TypeScript](contracts/science.generated.ts). All nested types are included there.

Response fields: `cell_ids`, `filters`, `limit`, `offset`, `ordering`, `total`, `units`.

Filters contain physical-unit thresholds, quality, coverage, region/bbox and offset/limit (<=1000). Unknown dataset 404, invalid filter 422. Candidate IDs refer to dataset provenance; retrieve vectors for per-cell quality. No NASA calls.

Tested request:

```http
POST /api/v1/science/datasets/SITE04_NW_ORIGIN_PRESERVED_2KM_100M__tiles_3.0.0/candidates
Content-Type: application/json

{
  "qualities": [
    "source_lola_count_and_uncertainty_not_supplied"
  ],
  "limit": 2
}
```

Exact tested example response (HTTP 200): [HTTP evidence](evidence/unified/final_api_examples.json), `examples.find(e => e.name === "candidates").response`. This is the complete payload, including source metadata and arrays; nothing is elided or replaced.

```json
{
  "cell_ids": [
    "SITE04_R000_C000",
    "SITE04_R000_C001"
  ],
  "total": 400,
  "offset": 0,
  "limit": 2,
  "filters": {
    "region": null,
    "bbox": null,
    "minimum_coverage": 1.0,
    "qualities": [
      "source_lola_count_and_uncertainty_not_supplied"
    ],
    "maximum_slope_deg": null,
    "maximum_roughness_m": null,
    "minimum_elevation_m": null,
    "maximum_elevation_m": null,
    "offset": 0,
    "limit": 2
  },
  "units": {
    "slope": "degree",
    "roughness": "m",
    "elevation": "m"
  },
  "ordering": "Original cell ID ascending; no implicit safety thresholds"
}
```

### `POST /api/v1/science/analysis`

Request body schema: `Scenario`.

Exact 200 response schema: `AnalysisResponse` in [OpenAPI](contracts/science.openapi.json) (`#/components/schemas/AnalysisResponse`) and [TypeScript](contracts/science.generated.ts). All nested types are included there.

Response fields: `comparison`, `dataset`, `dataset_sha256`, `results`, `scenario`, `scenario_id`, `scope`.

Combined result includes original Cell, StaticVector, separate DynamicVector, NASA provenance and model-specific comparison. Bounded Scenario (16 cells/20000 total samples/31 days). Missing ID 404, scientific/schema constraints 422, capacity 429. Source unavailable is a 200 UNKNOWN cell result.

Tested request:

```http
POST /api/v1/science/analysis
Content-Type: application/json

{
  "dataset_id": "SITE04_NW_ORIGIN_PRESERVED_2KM_100M__tiles_3.0.0",
  "cell_ids": [
    "SITE04_R000_C000",
    "SITE04_R000_C001"
  ],
  "start_utc": "2026-11-15T00:00:00Z",
  "end_utc": "2026-11-22T00:00:00Z",
  "step_minutes": 60,
  "minimum_shared_minutes": 60,
  "altitude_km": 0,
  "horizon_model": "GEOMETRIC_IDEAL",
  "filters": {
    "qualities": [
      "source_lola_count_and_uncertainty_not_supplied"
    ]
  }
}
```

Exact tested example response (HTTP 200): [HTTP evidence](evidence/unified/final_api_examples.json), `examples.find(e => e.name === "analysis").response`. This is the complete payload, including source metadata and arrays; nothing is elided or replaced.

### `POST /api/v1/science/celestial`

Request body schema: `Scenario`.

Exact 200 response schema: `AnalysisResponse` in [OpenAPI](contracts/science.openapi.json) (`#/components/schemas/AnalysisResponse`) and [TypeScript](contracts/science.generated.ts). All nested types are included there.

Response fields: `comparison`, `dataset`, `dataset_sha256`, `results`, `scenario`, `scenario_id`, `scope`.

Alias of integrated analysis, with exactly the same AnalysisResponse contract, limits and errors. Join records by cell_id + timestamp_utc; observer is the converted selected-cell position. No separate simplified celestial payload.

Tested request:

```http
POST /api/v1/science/celestial
Content-Type: application/json

{
  "dataset_id": "SITE04_NW_ORIGIN_PRESERVED_2KM_100M__tiles_3.0.0",
  "cell_ids": [
    "SITE04_R000_C000"
  ],
  "start_utc": "2026-11-15T00:00:00Z",
  "end_utc": "2026-11-22T00:00:00Z",
  "step_minutes": 60,
  "minimum_shared_minutes": 60,
  "altitude_km": 0,
  "horizon_model": "GEOMETRIC_IDEAL",
  "filters": {
    "qualities": [
      "source_lola_count_and_uncertainty_not_supplied"
    ]
  }
}
```

Exact tested example response (HTTP 200): [HTTP evidence](evidence/unified/final_api_examples.json), `examples.find(e => e.name === "celestial").response`. This is the complete payload, including source metadata and arrays; nothing is elided or replaced.

### `GET /api/v1/science/scenarios/{scenario_id}`

Parameters (exact constraints in OpenAPI):

```json
[
  {
    "in": "path",
    "name": "scenario_id",
    "required": true,
    "schema": {
      "title": "Scenario Id",
      "type": "string"
    }
  }
]
```

Exact 200 response schema: `ScenarioResponse` in [OpenAPI](contracts/science.openapi.json) (`#/components/schemas/ScenarioResponse`) and [TypeScript](contracts/science.generated.ts). All nested types are included there.

Response fields: `dynamic_vectors`, `scenario_id`, `unevaluated_cell_ids`.

Returns only evaluated dynamic vectors, with each vector retaining provenance/quality/model; explicitly lists unevaluated IDs. Missing/expired scenario 404. Response size bounded by the stored originating request; no pagination.

Tested request:

```http
GET /api/v1/science/scenarios/98063e496fed399e40fda9178514a6c4ddda1763ff5318768d960d2090c87968

```

Exact tested example response (HTTP 200): [HTTP evidence](evidence/unified/final_api_examples.json), `examples.find(e => e.name === "dynamic_vectors").response`. This is the complete payload, including source metadata and arrays; nothing is elided or replaced.

### `POST /api/v1/science/ranking`

Request body schema: `Scenario`.

Exact 200 response schema: `RankingResponse` in [OpenAPI](contracts/science.openapi.json) (`#/components/schemas/RankingResponse`) and [TypeScript](contracts/science.generated.ts). All nested types are included there.

Response fields: `comparison`, `results`, `scenario_id`, `scope`.

Uses the same bounded Scenario as analysis, returns Comparison plus evidence-bearing CombinedCell results and scenario_id. No cross-model/time-window comparison. Errors 404/422/429; source unknowns appear in excluded reasons.

Tested request:

```http
POST /api/v1/science/ranking
Content-Type: application/json

{
  "dataset_id": "SITE04_NW_ORIGIN_PRESERVED_2KM_100M__tiles_3.0.0",
  "cell_ids": [
    "SITE04_R000_C000",
    "SITE04_R000_C001"
  ],
  "start_utc": "2026-11-15T00:00:00Z",
  "end_utc": "2026-11-22T00:00:00Z",
  "step_minutes": 60,
  "minimum_shared_minutes": 60,
  "altitude_km": 0,
  "horizon_model": "GEOMETRIC_IDEAL",
  "filters": {
    "qualities": [
      "source_lola_count_and_uncertainty_not_supplied"
    ]
  }
}
```

Exact tested example response (HTTP 200): [HTTP evidence](evidence/unified/final_api_examples.json), `examples.find(e => e.name === "ranking").response`. This is the complete payload, including source metadata and arrays; nothing is elided or replaced.

### `POST /api/v1/science/delay`

Request body schema: `DelayRequest`.

Exact 200 response schema: `DelayResponse` in [OpenAPI](contracts/science.openapi.json) (`#/components/schemas/DelayResponse`) and [TypeScript](contracts/science.generated.ts). All nested types are included there.

Response fields: `delay_days`, `delayed`, `limitations`, `original`, `original_cell_id`, `original_qualifying_ids`, `outcome`, `reason`, `selected`.

DelayRequest extends Scenario with original_cell_id. Returns original and delayed CombinedResponse values, selected candidate or null, outcome and reasons. Original cell must be selected; shifted dates must validate. Same 16-cell/20000-sample bound for each of the two intervals. Errors 404/422/429; missing evidence yields INSUFFICIENT DATA. Does not populate scenario retrieval IDs.

Tested request:

```http
POST /api/v1/science/delay
Content-Type: application/json

{
  "dataset_id": "SITE04_NW_ORIGIN_PRESERVED_2KM_100M__tiles_3.0.0",
  "cell_ids": [
    "SITE04_R000_C000",
    "SITE04_R000_C001"
  ],
  "start_utc": "2026-11-15T00:00:00Z",
  "end_utc": "2026-11-22T00:00:00Z",
  "step_minutes": 60,
  "minimum_shared_minutes": 60,
  "altitude_km": 0,
  "horizon_model": "GEOMETRIC_IDEAL",
  "filters": {
    "qualities": [
      "source_lola_count_and_uncertainty_not_supplied"
    ]
  },
  "original_cell_id": "SITE04_R000_C000"
}
```

Exact tested example response (HTTP 200): [HTTP evidence](evidence/unified/final_api_examples.json), `examples.find(e => e.name === "delay").response`. This is the complete payload, including source metadata and arrays; nothing is elided or replaced.
