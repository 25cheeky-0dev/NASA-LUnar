# Executed scientific validation
The final clean Python 3.13 suite passed 239 tests, zero skips, one Starlette deprecation warning. This includes authentic real V3/global assets, terrain tests and two opt-in live tests. A later shared-constant refactor is covered by focused regression and CI; see final release message for exact commit checks.

Independent checks include scalar raster derivatives, HEALPix areas/hierarchy/centers, native projection and source pixels, analytical terrain geometry, full-dimensional PCA distance preservation, explicit z-score math, original source hashes and 400-cell/1,520-edge preservation. Existing global quadrature refinement results are retained, not overstated as instrument uncertainty.

Four failing uncertainty reproductions were executed before repair. Added tests cover wrong units/source/definition, null/negative/boolean uncertainty, corrupt/stale model files, invalid vector spaces, HTTP overload, wrong thermal channels/bounds, malformed topology, source URL credential/port/host restrictions and unknown terrain bounds.

These are engineering verification results, not external peer review, dependency CVE certification or exhaustive lunar edge-case proof.

Executed evidence: [final-backend evidence](evidence/final-backend/). Historical global validation remains in [GLOBAL_VALIDATION_REPORT.md](GLOBAL_VALIDATION_REPORT.md).
