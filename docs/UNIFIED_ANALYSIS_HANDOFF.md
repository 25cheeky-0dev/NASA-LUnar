# Unified scientific backend handoff

## What is implemented

`app/integration` adds a single pipeline: native/canonical grid discovery → physical terrain vectors → explicit candidate filtering → validated Celestial Engine → horizon diagnostics → dynamic scenario vectors → explainable ranking and seven-day comparison. Existing endpoints and legacy recovery remain available. No frontend, deployment, LLM embedding, vector database, or grid reconstruction changes.

Branch: `feature/unified-scientific-analysis`, based on `feature/celestial-engine`. The PR targets that branch so the existing Celestial Engine changes are not duplicated. Do not merge to main without authorization.

## Real validation

The supplied `WISPR_Site04_Tiling_V3` package was loaded with PyArrow. All 400 original IDs, latitude/longitude, projected centers and three terrain measurements were checked against baseline Parquet; neighbors and geometry bounds were independently checked. Consumed files, including the original NASA DEM, were checked against the package SHA256 manifest. Original WKB bytes are preserved as hexadecimal, projected polygons retain their CRS, and all original tile-cell fields survive ingestion.

The package calls its immutable grid **2.0.0** and its tile processor **3.0.0**. Both are retained. The implementation does not assume 400 cells, this resolution, or these IDs for other compatible datasets.

`docs/evidence/unified/validation_summary.json` records the full-grid/vector fingerprints, query URLs, raw NASA hashes, retrieval times and results. `real_v3_delay.json` contains the complete combined response. `real_v3_two_cells.json` is an authentic extracted two-cell dataset, not synthetic. `backend/tests/fixtures/unified_nasa` contains the exact recorded NASA responses and provenance for offline regression. These recordings are explicitly distinguished from opt-in live tests.

| Real cell | Original week longest shared minutes | Seven-day delayed week |
|---|---:|---:|
| SITE04_R000_C000 | 5988.9515639 | 10080 |
| SITE04_R000_C001 | 5988.5944356 | 10080 |

Original interval: 2026-11-15 00:00 UTC to 2026-11-22 00:00 UTC. Delayed interval: November 22–29, same UTC times. Cadence: 60 minutes. Unknown fraction: zero in all four geometric scenarios. Minimum shared duration: explicitly supplied 60 minutes. Outcome: KEEP. Numerical differences smaller than cadence are not evidence of meaningful superiority. No landing-safe slope or roughness threshold was supplied or invented.

## Run

From `backend`:

```powershell
python -m pip install -e '.[test,terrain]'
$env:WISPR_GRID_DIR='C:\Users\manra\Downloads\WISPR_Site04_Tiled_Provenance_V3\WISPR_Site04_Tiling_V3'
python -m uvicorn app.main:app --port 8000
```

The registry reads once per process; restart after installing a new dataset. The root can be a native V3 package or a directory of canonical JSON/Parquet datasets and native package subdirectories. Discovery reports invalid packages instead of silently replacing them. Keep unrelated JSON files outside a canonical grid directory.

```powershell
python -m pytest -q
$env:WISPR_REAL_V3_DIR=$env:WISPR_GRID_DIR
$env:WISPR_LIVE_TEST='1'
python -m pytest -q
python -m scripts.check_integration --grid-root $env:WISPR_GRID_DIR --output ../docs/evidence/unified
```

Without external assets, the full-package test explicitly skips; authentic extracted-cell plus recorded-NASA end-to-end tests still run. Without the live flag, network tests explicitly skip. Synthetic tests are labeled synthetic and cover alternate grid sizes/versions and failure states.

## Stable V4 contract

Canonical JSON is `{ "metadata": {...}, "cells": [...] }`. Parquet uses the same row fields and UTF-8 JSON under schema metadata key `wispr_grid_metadata`. See `Metadata` and `Cell` in `app/integration/grid.py` and generated OpenAPI for types. No version-name gate exists for compatible canonical V4 data.

Required metadata: dataset_id (unique per dataset version), grid_version, scope (GLOBAL/REGIONAL), coordinate_frame, latitude_type, longitude_convention, elevation_datum, source object, terrain_definition. Include processing_version, projected_crs, reference_radius_m, resolution_m, region and synthetic status as appropriate. Elevations/roughness are metres; slopes degrees. Unknown measurements are JSON null, not zero or NaN.

Required cell fields: original string cell_id, latitude_deg, longitude_deg, valid. Physical features may be null. Preserve projected_x/projected_y, geometry, neighbors, coverage_fraction, quality, uncertainty, source, source resolution and region. Extra original cell fields are retained. Geometry must declare its lunar projection; it is not assumed to be terrestrial GeoJSON. Cross-tile neighbor IDs are retained without fabricating missing neighbor cells.

The native V3 reader maps names from Narinder's package to this interface without modifying original fields. Unknown frame/latitude definitions can be discovered and inspected but cannot reach NASA evaluation. Planetocentric spherical input is accepted only for the declared 1737400 m sphere, and both NASA response headers must confirm that same spherical center shape. The original latitude is retained; east-positive [-180,180] or west-positive longitudes are converted only in the Horizons request. Never use cell-mean DEM elevation as observer altitude.

## Vector definitions and comparison policy

Static feature order: `[elevation_m, slope_deg, roughness_m]`. Normalization `physical-scales-v1` divides by `[1000, 10, 10]` with zero offsets, no clipping, fitting or imputation. These fixed scales are descriptive numerical coordinates, not safety thresholds or uncertainty estimates. Raw and normalized values, units, missing masks and parameters are returned separately. Reproducibility depends on input bytes and this explicit normalization version.

Similarity uses Euclidean distance only when complete valid cells share resolution, terrain definition, datum, frame, quality, coverage and uncertainty descriptors. Unknown quality is not converted into equivalent precision. The real V3 package lacks shot counts and uncertainty layers, so its default quality does **not** pass the default VERIFIED-only filter or the strict similarity gate. The demonstration explicitly allows its exact source quality string. This accepts a documented limitation for geometric comparison; it does not invent measurement accuracy.

Candidate filters use original physical units, optional region/bbox, explicit quality/coverage, and caller-supplied slope/roughness/elevation bounds. No default engineering safety limits. Deterministic ordering is by original cell ID. The implementation uses float64 NumPy matrices and PyArrow ingestion, with an in-memory dataset registry; out-of-core planetary-scale performance has not been benchmarked. No vector database requirement has been demonstrated.

Dynamic vectors are generated only for evaluated cells, separately from static vectors. They include UTC start/end, observer settings, cadence, model, provenance, missing-data flags and units. Windows reuse the existing piecewise-linear interpolation between adjacent known samples. Fractions use the entire requested interval as denominator; they are lower bounds when data is incomplete. Unknown intervals are never bridged. Available Sun observations survive missing Earth samples and vice versa. Ranking excludes incomplete dynamic evidence, rejected terrain constraints and nonqualifying windows. It reports individual measurements and reasons rather than a composite score.

## Terrain limitations

The original terrain provider now accepts the actual selected latitude/longitude, retaining the old site-based call contract. It returns source manifest, raster hash and observing position. It uses the existing finite-radius spherical/geodesic ray calculation and never certifies complete far-field visibility.

Terrain mode is explicitly `TERRAIN_PARTIAL`. Its discrete rays support obstruction diagnostics at exact sampled azimuths; unsampled directions and apparent clearance remain unknown, not clear. No unsupported azimuth interpolation is introduced. Even obstruction comparisons are disabled when DEM ground + observer height cannot be matched to the explicitly requested Horizons altitude/reference. The real V3 DEM's vertical datum is unverified for this purpose, so the demonstrated results are **GEOMETRIC_IDEAL**, at explicit Horizons altitude 0 km. They are not terrain-screened physical landing visibility.

A verified future terrain provider must supply matching observer/reference evidence and directional coverage before stronger visibility claims are possible. Missing DEM configuration produces structured unknown terrain state, not a geometric fallback within a terrain comparison.

## API (additive `/api/v1/science` namespace)

| Method | Path | Result |
|---|---|---|
| GET | /datasets | Paginated metadata, availability and ingestion errors |
| GET | /datasets/{id}/cells | Paginated cells |
| GET | /datasets/{id}/cells/{cell} | Original measurements, geometry, neighbors and provenance |
| GET | /datasets/{id}/vectors/{cell} | Raw/normalized static vector |
| GET | /datasets/{id}/similarity/{cell} | Evidence-constrained numerical neighbors |
| POST | /datasets/{id}/candidates | Physical and quality filters |
| POST | /analysis | Complete selected-cell combined response |
| POST | /celestial | Same integrated evaluation, including joined celestial records |
| GET | /scenarios/{scenario_id} | Dynamic vectors from a bounded recent-analysis store |
| POST | /ranking | Same-scenario ranking with evidence and exclusions |
| POST | /delay | Original plus exactly seven-day-shifted comparison |

Example analysis body:

```json
{
  "dataset_id": "SITE04_NW_ORIGIN_PRESERVED_2KM_100M__tiles_3.0.0",
  "cell_ids": ["SITE04_R000_C000", "SITE04_R000_C001"],
  "start_utc": "2026-11-15T00:00:00Z",
  "end_utc": "2026-11-22T00:00:00Z",
  "step_minutes": 60,
  "altitude_km": 0,
  "minimum_shared_minutes": 60,
  "horizon_model": "GEOMETRIC_IDEAL",
  "filters": {"qualities": ["source_lola_count_and_uncertainty_not_supplied"]}
}
```

For delay add `original_cell_id`. KEEP means the original delayed location still qualifies; SWITCH selects a qualifying evaluated alternative if it does not. Without qualifying options, unknown evidence gives INSUFFICIENT DATA; complete failures give NO QUALIFYING MODELED OPTION. POSTPONE remains in legacy recovery, but this bounded seven-day comparison does not invent an unevaluated later interval.

Queries are limited to 16 selected cells, 20,000 total inclusive samples per scenario, 31 days and 10,000 samples per cell. Pages are at most 1,000 records. Two concurrent analysis jobs per process; overload returns 429. Dynamic storage holds 16 recent responses per process and expires on restart; absent/expired scenarios return 404. NASA's existing validated disk cache persists scientific source responses. No automatic global NASA query is performed.

## Scientific references

- [NASA Horizons manual](https://ssd.jpl.nasa.gov/horizons/manual.html): observer coordinate and lunar mean-Earth conventions.
- [NASA Horizons API](https://ssd-api.jpl.nasa.gov/doc/horizons.html): quantity 4, airless apparent azimuth/elevation, request parameters.
- [USGS lunar coordinate systems](https://pubs.usgs.gov/tm/11/e1/tm11E1.pdf): spherical lunar latitude conventions.
- Native V3 README, baseline metadata and tile manifests are authoritative for supplied terrain definitions and uncertainties; preserved in the extracted-cell evidence.

## Verification result for this handoff

Final full run with `WISPR_REAL_V3_DIR` pointing at the supplied package and `WISPR_LIVE_TEST=1`: **171 passed**, no skips. This includes existing API/recovery tests, Celestial Engine regressions, the original live NASA comparison, native V3 ingestion, real Site04 combined analysis, and new integration tests. Ruff passed for all new Python modules/tests/scripts; `git diff --check` passed. One upstream Starlette warning concerns future TestClient transport deprecation; it did not affect results.
