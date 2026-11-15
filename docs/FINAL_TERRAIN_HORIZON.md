# Terrain horizon integration
The existing tested terrain engine from PR #4 is integrated into the canonical provider, native scenario path and `POST /api/v1/science/terrain/horizon`. Request dataset_id, original cell_id, observer_height_m (0–100), and up to 360 exact azimuths. Coordinates come from the original V3 cell; source checksum, affine, CRS, native pixel dimensions and dataset identity are checked.

The engine uses lunar geodesic rays, spherical curvature, bilinear native-pixel support, directional obstruction samples and explicit stop reasons. Missing support never becomes clear sky. Scenario skyline diagnostics use 5-degree rays; the explicit diagnostic endpoint supports exact requested directions. Discrete samples do not bound unobserved subpixel peaks or the far field.

DEM-to-Horizons vertical compatibility and hard elevation error bounds remain unverified. Relabeling a source string cannot verify them. Physical visibility remains UNKNOWN; no terrain candidate was ranked in the real HTTP test. Nominal sampled obstruction is no longer accepted as certified obstruction without a verified lower bound. The separate imported ephemeris comparison helper retains raw-source revalidation capability, but no production datum transformation is asserted.

Executed evidence: [final-backend evidence](evidence/final-backend/). Historical global validation remains in [GLOBAL_VALIDATION_REPORT.md](GLOBAL_VALIDATION_REPORT.md).
