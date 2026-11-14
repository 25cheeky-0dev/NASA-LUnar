# Physical vectors and learned representations
Raw order is `[elevation_m, slope_deg, roughness_m]`; no default imputation. `physical-scales-v1` divides by `[1000,10,10]` and is shared across native/global engines. Native and global roughness definitions remain different and are not silently compared.

`terrain-population-zscore-v1` persists means, population standard deviations and a constant-feature mask. Constant columns map to zero via an explicitly recorded divisor of one; no numerical variance is invented.

`PCA_FEATURE_EMBEDDING` is genuine NumPy/LAPACK SVD on centered fixed-scale physical features, not a neural or semantic model. Fit uses complete, full-coverage compatible native cells; excludes unsupported quality; caps population at 200,000 and dimensions at 1–3. Original V3 missing uncertainty is preserved and allowed only for descriptive representations, never qualified precision. Source IDs, feature definitions, ordered population, raw-value/input hash, preprocessing, components, variance, NumPy version and model checksum are persisted atomically.

Inference rejects incompatible spaces, missing models, corruption and stale source/population hashes. Full-dimensional PCA distance is independently checked against exact physical distance; reduced dimensions may change neighbors. Signed physical differences accompany results. Ties order by exact numerical distance then cell ID. Degenerate SVD subspaces may vary across numerical libraries; persisted model parameters are authoritative.

Actual Site04 model: [representation-model.json](evidence/final-backend/representation-model.json). Model ID `76dec9d165584aa01e974bb44c918c951340089261725046a26f33a81ecd1a1d`. Search is exact NumPy, no ANN or external vector database. Global PCA is not exposed; the new fit endpoint uses the native registry. Semantic retrieval remains explicitly keyword-based because no semantic embedding model is configured.

Executed evidence: [final-backend evidence](evidence/final-backend/). Historical global validation remains in [GLOBAL_VALIDATION_REPORT.md](GLOBAL_VALIDATION_REPORT.md).
