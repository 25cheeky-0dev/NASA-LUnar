# Grid → Celestial Engine handoff for Narinder

The Celestial Engine does not modify or require your grid implementation. Existing
`app/science/grid.py`, terrain code and frontend are unchanged. The new API is additive.

Deliver JSON `{metadata, cells}` or Parquet with UTF-8 JSON `wispr_grid_metadata` in schema
metadata. Required cell fields (extra fields are accepted):

```json
{
  "cell_id": "YOUR_ORIGINAL_STRING_ID",
  "latitude_deg": -89.0,
  "longitude_east_deg": 45.0,
  "elevation_m": 0.0,
  "slope_deg": 0.0,
  "roughness_m": 0.0,
  "valid": true
}
```

This is a structural example only, not actual terrain measurements.

Required dataset metadata:

```json
{
  "coordinate_frame": "MOON_ME_DE421",
  "longitude_convention": "east_positive_0_360",
  "latitude_type": "planetodetic",
  "elevation_units": "m",
  "elevation_datum": "COPY_ACTUAL_DATASET_VERTICAL_REFERENCE",
  "source": "COPY_ACTUAL_DATASET_URL_AND_VERSION",
  "elevation_matches_horizons_reference": false
}
```

Verify these declarations against your source data. Convert west-positive or signed
longitudes before handing them over; longitude values must be [0,360), latitude [-90,90].
Do not label principal-axis or Earth coordinates as MOON_ME_DE421. For the current spherical
reference, planetocentric and planetodetic latitude coincide, but frame transformations
still need evidence. IDs must be unique strings; they are never regenerated from geometry.

```python
from celestial_engine.grid_adapter import GridAdapter, read_grid
from celestial_engine.celestial_service import CelestialService
from celestial_engine.schemas import EphemerisRequest

metadata, cells = read_grid("grid.json")
template = EphemerisRequest(
    latitude_deg=-89,
    longitude_east_deg=45,
    altitude_km=0,
    start_utc="2026-11-15T00:00:00Z",
    end_utc="2026-11-22T00:00:00Z",
    step_minutes=60,
)
result = GridAdapter(CelestialService()).process(
    cells,
    metadata,
    template,
    batch_size=4,
    use_grid_elevation=False,
)
# result['results'][i]: cell_id, ephemeris (Pydantic result), grid metadata,
# grid_elevation_applied; result['skipped_cell_ids'] identifies valid=False rows.
```

Default job limit: 16 submitted cells, 20000 total valid-cell samples; batch size 4.
Maximum configurable cell limit 64, sample limit 100000. All requests are sequential.
Invalid metadata/coordinates, duplicate IDs and exceeded budgets fail before any request.
An upstream failure raises explicitly; there is no silent partial job success or substitution.
Rows keep the same requested UTC cadence, including null observations.

The default uses the explicit template altitude, ignoring DEM elevation. Only request
`use_grid_elevation=True` after documented conversion to Horizons' 1737.4 km lunar sphere
and DE421 ME frame, with metadata `elevation_datum="horizons_lunar_reference"` and
`elevation_matches_horizons_reference=true`. Then metres are converted to kilometres.
This flag is your operator assertion, not independent validation by the adapter.

Join returned physical features on original `cell_id` and UTC timestamp. Keep static
terrain fields alongside them; do not normalize canonical angles. Terrain obstruction,
illumination durations, usable communications and landing eligibility require downstream
models and uncertainty analysis. The existing grid API's center_lat/center_lon schema is
not automatically relabeled; construct the documented adapter contract explicitly.
