# Physical and document retrieval

`terrain-v1` feature order is `[elevation_m, slope_deg, roughness_m]`; units are metres, degrees, metres. `physical-scales-v1` divides by `[1000,10,10]`, without fitting, clipping or imputation. The global feature Parquet has separate `raw_values`, `normalized_values` and `missing_mask` columns. These scales describe numerical distance, not safety thresholds.

Similarity defaults to rejecting unknown uncertainty. `accept_unknown_uncertainty=true` permits **descriptive** distance within one identical source/method/resolution/snapshot, requiring complete feature support. Results contain exact Euclidean distance, raw measurements, per-feature differences, source identity and scope. Unknown-quality acceptance does not certify equal accuracy. Different source snapshots, V3 terrain definitions, thermal channels, dates and semantic scores are never silently mixed.

Population z-score fitting is available through `fit_zscore`: explicit complete ordered population, source snapshot, feature means, population standard deviations (ddof=0), population bytes hash and fit hash. Constant or incomplete features fail. The public similarity route intentionally exposes fixed-scales only; z-score retrieval needs a selected stored fit and is not advertised as implemented.

Geographic filtering uses explicit center-in-bbox semantics with longitude wrap support. It is not an exact cell-footprint bbox intersection query. Regional V3 crosswalk retrieval separately uses polygon overlap. Caller bounds are in physical units; no landing-safe default is invented.

`POST /global/retrieve` is keyword evidence search over immutable source metadata fields. It returns exact chunks, citation, source URL, document hash, score and `keyword-set-overlap-v1`. There is no embedding model configured. Keyword score is never combined with terrain distance or used to rank landing locations.
