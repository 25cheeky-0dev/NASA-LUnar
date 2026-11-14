# Final backend architecture
One `/api/v1/science` pipeline is authoritative. `app/integration` owns scenario orchestration, native datasets and physical representations; `lunar_global` owns HEALPix/source-specific facts; `celestial_engine` owns NASA transport/parser/cache; `app/providers/terrain` owns terrain diagnostics. `vector_contract.py` supplies the shared physical feature order and fixed scales.

Base: global fusion `3cabab1`, descendant of scientific foundation `1b8ea59`. Selected terrain modules/tests ported from `4ff3b3a`. The alternative data engine was inspected for topology/partition safeguards; these were implemented in the canonical V3 reader without activating its competing router or registry. Legacy APIs remain compatible; their historical catalogs are not the authoritative V3 database.

No frontend implementation changed in this branch. WISPR-001 browser integration remains outside scope. No main merge or public deployment occurred.

Executed evidence: [final-backend evidence](evidence/final-backend/). Historical global validation remains in [GLOBAL_VALIDATION_REPORT.md](GLOBAL_VALIDATION_REPORT.md).
