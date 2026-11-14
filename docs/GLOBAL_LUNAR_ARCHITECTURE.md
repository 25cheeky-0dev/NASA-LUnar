# Global lunar foundation

Branch: `feature/global-lunar-fusion-v1`, based on scientific integration commit `1b8ea59`. No engine-wide merge from `feature/unified-data-engine`, no modification to the original V3 package/generator, and no merge to main.

`backend/lunar_global` adds HEALPix NESTED identity on the Moon's 1,737,400 m sphere in MOON_ME_DE421. IDs are `MOON:HPX:NESTED:{nside}:{pixel}`; their definition is versioned as `moon-hpx-nested-v1`. Pixel number and NSIDE are the spatial index. Parent is integer pixel/4; children are 4p..4p+3. Cells have equal exact spherical area; returned boundary rings sample analytic HEALPix edges and declare their sampling. They are **not WGS84 GeoJSON polygons**. Longitude is east-positive [0,360); latitude is spherical planetocentric. Unknown source frames are rejected, not approximately transformed.

The executed grid builds contain 49,152, 196,608 and 786,432 cells at NSIDE 64/128/256. NSIDE 512 is supported by lookup but not materialized. Geometry is lazy, grid generation uses batches of 4,096, and Parquet partitions retain ordered pixel IDs. Source resolution is independent of grid resolution.

The preserved V3 reader verifies the original package checksums and all 400 measurements. Regional crosswalks intersect each original projected polygon with progressively densified HEALPix edges in its lunar projection. Subdivision doubles until overlap changes and the partition sum are below 1e-6. Both query directions exist. The current crosswalk implementation deliberately validates only the small Site04 polar footprint; arbitrary regional frames need a separately validated projection bound.

## Data flow

Official HTTPS source bytes → immutable receipt and SHA256 → source metadata validation → native measurements/derivatives → spherical area quadrature or explicit native-pixel context → immutable Parquet snapshot → bounded DuckDB queries → physical vector or evidence result.

LOLA derivatives are calculated on the native DEM, before HEALPix aggregation. A source snapshot contains distinct raw values, normalized values and masks. Source-product identity, checksum, processing version and grid resolution define the snapshot. Source updates require a new root/snapshot; existing snapshots are not overwritten. Incomplete directories without completion manifests are not advertised as built. A failed early development build was retained locally under `failed-nside64-serialization`; it is not an active level.

Static terrain, historical thermal bins, imagery, dynamic scenarios and document text remain distinct. No statistical fusion is attempted because independent calibration/correlation/uncertainty evidence is absent. LROC image DN never becomes elevation, roughness, mineral abundance or a hazard score. Diviner temperatures never become mission-date predictions or electrical power.

`AnalysisEngine`, `CelestialService`, transport, parser, cache and seven-day comparison are reused. The new cell adapter constructs a bounded canonical dataset containing only selected global cells, then calls the existing evaluator and scenario store. Native regional requests use the existing dataset registry unchanged. Cell-mean elevation is never substituted for Horizons altitude. Existing partial-terrain/unknown states are preserved.

## Resource limits

- Grid build: 4,096 cells per batch; no full global polygon allocation.
- Terrain quadrature: 512 parent cells × 256 equal-area child samples per batch.
- Native demonstration DEM: 720×1,440 int16; derived arrays are bounded to that source size. Larger products require windowed derivative adaptation; this decoder intentionally accepts only LDEM_4 V3.0.
- DuckDB: two threads, 256 MB memory limit per connection; numerical retrieval is exact SQL, not an in-memory all-cell matrix.
- Pages: ≤1,000 rows; geometry tiles: ≤64 cells; source-overlap pages: ≤50.
- Dynamic jobs share the existing two-job gate, 16 selected cells, 20,000 samples and existing UTC limits.
- Source downloads: 64 MB default, 192 MB explicit for the Diviner table. No account restriction is bypassed.

## Migration inventory

| Existing module | Treatment |
|---|---|
| `app/integration/v3.py`, grid contracts and filters | Reused unchanged |
| `app/integration/engine.py` | Reused unchanged |
| `app/integration/api.py` | Extended evaluator with optional injected analysis engine; same legacy behavior |
| `celestial_engine/*` | Untouched |
| `app/providers/terrain.py` | Untouched; existing partial horizon limitations retained |
| `app/main.py` | Adds global router |
| Contract exporter | Extended to skip binary image routes in JSON TypeScript generation |
| Existing frontend | Retained; global explorer added above legacy recovery |
| Competing unified-data engine | Inspected, not copied wholesale |

No original APIs are removed. Global source metadata uses one `SourceProduct` contract. Existing V3 source metadata stays intact inside its canonical dataset rather than being rewritten.
