# Source-aware measurement support
The join system preserves native V3 measurements, sampled global aggregates, coarse LROC context and historical Diviner bins as distinct facts. Each includes source IDs, units, footprint/resolution, temporal support and missing/quality states. No rounded-coordinate statistical fusion or unverified uncertainty weighting is introduced.

LOLA derivatives are calculated on native source pixels before equal-area HEALPix quadrature. Min/max and pixel counts are sampled, not exhaustive; coverage does not mean laser-shot density. Prior independent refinement evidence remains valid and does not establish a global error bound.

Diviner retrieval now supports region, source channel and local-time bin through `/science/global/thermal-observations`. It selects native pixel centers in an ordered bbox; sentinel nulls and below-sensitivity values retain their quality labels. Observations are not forecasts or electrical-power estimates. LROC values remain imagery context, not terrain physics.

Executed evidence: [final-backend evidence](evidence/final-backend/). Historical global validation remains in [GLOBAL_VALIDATION_REPORT.md](GLOBAL_VALIDATION_REPORT.md).
