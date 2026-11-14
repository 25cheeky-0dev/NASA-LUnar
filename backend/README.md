# Backend

Run commands from this directory. Use the root README for installation and servers. Configuration is read from environment variables; `.env.example` is a reference file and is not loaded automatically. PowerShell example: `$env:CORS_ORIGINS='http://192.168.1.10:5173'`.

## Source and geometry

Horizons queries Sun 10 and Earth 399 at `coord@301`, quantity 4, airless apparent angles, UT output. The parser checks target, Moon observer, geodetic coordinates, reference height, column labels, monotonic times and angle ranges. Missing rows are aligned to the requested UTC cadence, never joined by row index. Raw JSON is atomically cached beside query metadata and its SHA-256. Every reuse checks hash, parameters and parser version. Windows use piecewise-linear elevation between adjacent known samples and report MODEL_ESTIMATE with a one-step boundary uncertainty. A zero-elevation sample breaks continuity. Fractions are modeled visible duration divided by total study duration; unknown fraction is reported separately. Feature fractions are withheld if the study interval is incomplete.

`HORIZONS_REFERENCE_HEIGHT_KM` defaults to 0 above the JPL reference sphere. `observer_height_m` means height above local DEM ground and is NOT added to this unrelated reference height. This unresolved vertical conversion is stated in every scientific result. Terrain eligibility stays unknown, even if a local raster yields a partial horizon.

Canonical grid: `+proj=stere +lat_0=-90 +lat_ts=-90 +lon_0=0 +R=1737400 +units=m +no_defs`. Integer x/y kilometre indices define immutable `SP1KM:<ix>:<iy>` IDs. All longitudes are east-positive [0,360). This is a spherical lunar grid, not Earth EPSG:3031. Reference-region evaluations do not populate cell-center observations. `/features` returns null-valued cell `points` and separate `reference_points` carrying the containing cell ID, exact coordinates, UTC interval, model and observer settings. No similarity or normalization is claimed without complete features.

## Terrain import

Install the `terrain` extra, set `DEM_R01` / `DEM_R04` to local GeoTIFFs, and supply a companion `<raster-path>.json`:

```json
{"source_url":"https://pgda.gsfc.nasa.gov/data/LOLA_5mpp/Site01/Site01_final_adj_5mpp_surf.tif","raw_sha256":"ACTUAL_FILE_SHA256","z_units":"metre","frame":"MOON_ME_DE421","vertical_reference":"COPY_VERIFIED_DATASET_REFERENCE","uncertainty_source":"COPY_ACTUAL_UNCERTAINTY_REFERENCE"}
```

This manifest is a trusted local operator declaration, not independent proof of NASA authorship. Import validates file hash, lunar radius, projected metre CRS, unrotated transform, NoData and reference-point footprint. Never generate a manifest for fabricated terrain. Heightmaps preserve null masks and signed row spacing. Horizon rays follow lunar geodesics and include spherical curvature. Local coverage remains PARTIAL and far-field completeness false. No actual raster has been bundled; source availability is recorded in `docs/STATUS.md`.

## Optional language providers

Set `GROQ_API_KEY` + `GROQ_MODEL`, or `NVIDIA_API_KEY` + `NVIDIA_MODEL`, only in the backend process environment. No model is assumed available and no provider is contacted without explicit configuration. Responses use JSON-object mode plus Pydantic revalidation, not an unverified strict-schema capability claim. The frontend requires review before executing translated fields. Future search remains 0 after interpretation; opt in using the structured form. Provider errors are reduced to credential-free messages. Manual `/search` works without any model. Provider access and free quota have not been verified; leave credentials unset until the operator has checked them.

## Operational limits

Upstream concurrency is bounded to two requests. Recovery allows two sites, at most 48h per study, 1–60 minute steps, exact 168h delay and at most seven additional daily arrivals. Exact verified queries are reused. Scenario results are held in a bounded 128-entry in-memory store; raw cache survives restarts, feature/export IDs can expire. Local use only: authentication, internet-facing rate limiting, persistent scenario storage and deployment are outside this build.
