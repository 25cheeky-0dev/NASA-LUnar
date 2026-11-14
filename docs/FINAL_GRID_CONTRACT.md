# Grid and native identity
HEALPix NESTED IDs `MOON:HPX:NESTED:<nside>:<pixel>`, Moon ME/DE421, radius 1,737,400 m, spherical latitude, east-positive longitude. NSIDE 64/128/256 indexes are built; 512 is supported analytically but not materialized. Boundaries use HEALPix spherical definitions with declared sampling. Physical terrain exists at 128, separately from geographic identity.

Site04 remains 400 original IDs, 400 original polygons, 1,520 directed neighbors, grid version 2.0.0, processing version 3.0.0. All 30 manifest files are checked. The dataset fingerprint remains `af7ada607c292caa4da066fdbfb6ccb3900f02365cc19c2aa2bb80a7de2d95a3`.

Added duplicate baseline/geometry/tile checks, exact shared-field comparison, projected polygon center and bounds checks, projection roundtrips and reciprocal shared-edge topology. Crosswalks remain bidirectional, projected and convergence-tested for Site04 only. Bbox APIs explicitly select centers, not exact arbitrary footprint intersections.

Executed evidence: [final-backend evidence](evidence/final-backend/). Historical global validation remains in [GLOBAL_VALIDATION_REPORT.md](GLOBAL_VALIDATION_REPORT.md).
