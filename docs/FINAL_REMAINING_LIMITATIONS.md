# Remaining limitations
- Terrain vertical datum/Horizons compatibility and hard uncertainty bounds are unresolved; physical terrain visibility stays UNKNOWN.
- Optional M3 L2 raster ingestion, supplemental Site04 count/uncertainty downloads and semantic embeddings are not complete. Site04 product-server access timed out; none was fabricated.
- Global terrain uses sampled quadrature, not exact analytic pixel overlap. Detailed-level physical features, generic regional crosswalks and exact arbitrary footprint search remain unavailable.
- PCA/z-score API fitting is for native registered populations; global retrieval remains exact fixed-scale. No ANN benchmark was justified for the measured bounded workload.
- Some instrument/model metadata remains dictionary-shaped; not every field is strongly typed.
- NASA network failure can make a new date unavailable. Scenario result storage is process-local and expires on restart; source snapshots and model artifacts persist.
- Local prototype has no authentication/public deployment. Bind loopback; deploy behind access control, TLS and external rate limits before public use. No dependency CVE audit or sustained stress test is claimed.
- No frontend changes, no main merge. Gemini's reported watermelon-platform folder was not found; untracked-file status is not a repository failure and unrelated files were not staged/deleted.

Executed evidence: [final-backend evidence](evidence/final-backend/). Historical global validation remains in [GLOBAL_VALIDATION_REPORT.md](GLOBAL_VALIDATION_REPORT.md).
