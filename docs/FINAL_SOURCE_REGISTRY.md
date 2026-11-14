# Source registry and actual availability
`GET /api/v1/science/status` joins the existing native registry and global source store; it does not create another source of scientific truth. It checks configured raw hashes and supported snapshots. Status is local readiness, not mission readiness or proof of NASA network availability.

Exact product IDs, checksums, footprints, units and provenance: [source-inventory.json](evidence/final-backend/source-inventory.json). It contains real LDEM_4 V3.0 global terrain, LROC WAC_GLOBAL_E000N1800_004P v1.3 imagery and Diviner 90S–80S historical time-binned observations. Original Site04 DEM SHA-256: `38ff70dbdf2f066c2cfa94a646c3a59d653ce7f6b4528b15fc1b43ee397ce758`.

M3: REGISTERED_ONLY, no imported L2 observation. Moon Trek: documentation accessed, no scientific ingestion. QuickMap: landing page accessible, no validated adapter. SBDB: reviewed, NOT_APPLICABLE. Horizons: operational on demand with per-query LIVE/VERIFIED_CACHE provenance.

Supplemental Site04 uncertainty/count product documentation is identified at https://pgda.gsfc.nasa.gov/products/78 but connection attempts timed out. No supplemental uncertainty was assigned to V3. [source-probes.json](evidence/final-backend/source-probes.json) records actual access results; accessible documentation is not ingestion.

Executed evidence: [final-backend evidence](evidence/final-backend/). Historical global validation remains in [GLOBAL_VALIDATION_REPORT.md](GLOBAL_VALIDATION_REPORT.md).
