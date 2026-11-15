# Selected-cell celestial analysis
The existing validated CelestialService, Horizons parser, source headers, raw hashes, UTC alignment and observer checks remain authoritative. No new NASA client or grid-wide ephemeris precomputation was added. Exact selected centers override request coordinates; DEM height never silently overrides Horizons altitude.

Real HTTP evidence compares original Site04 cells R000_C000/R000_C001 for 2026-11-15 through 2026-11-22 UTC, then exactly +168 hours. Original longest shared geometric windows are about 5988.95 and 5988.59 minutes; delayed modeled windows are 10080 minutes. Outcome KEEP under the recorded filters/thresholds. These runs used VERIFIED_CACHE NASA evidence. They are ideal geometric windows, not proven terrain illumination or radio link budgets.

The fresh live test uses a new cache, validates 169 samples, requires LIVE provenance for both bodies, and compares a separately requested shorter interval. Saved response: [live-nasa.json](evidence/final-backend/live-nasa.json). Its raw hashes/parameters distinguish it from cached workflow evidence.

Missing observations and partial terrain propagate unknown intervals. Only complete eligible modeled candidates rank. No unevaluated date is called a verified alternative.

Executed evidence: [final-backend evidence](evidence/final-backend/). Historical global validation remains in [GLOBAL_VALIDATION_REPORT.md](GLOBAL_VALIDATION_REPORT.md).
