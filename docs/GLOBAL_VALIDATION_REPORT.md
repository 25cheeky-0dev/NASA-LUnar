# Executed validation and remaining scope

The working foundation includes complete three-level whole-Moon indexing, actual LOLA/LROC/Diviner data, source-separated physical and temporal retrieval, preserved Site04 crosswalks, shared Horizons evaluation and a real browser workflow. It is a bounded scientific prototype. It does not implement every optional extension or certify landing safety.

## Executed evidence

- Full local Python 3.13 run with original V3 assets, downloaded global sources and opt-in live NASA tests: **189 passed**, one upstream Starlette deprecation warning. No tests were disabled to obtain this result.
- Frontend production build passed. Existing synthetic frontend fixture checks passed; they are not described as genuine NASA validation.
- Independent scalar calculations verify representative native elevation decoding, spherical central-difference slopes and 3×3 roughness. PyProj spherical polygon areas independently check sampled HEALPix boundaries. All cells at NSIDE 64/128/256 undergo center roundtrip and parent mapping tests.
- Adversarial checks cover invalid coordinates/IDs/NSIDE, longitude wrap, corrupt Parquet/hash, immutable snapshots, failed manifest serialization, missing vectors, incompatible frame/radius, unknown uncertainty, invalid normalization, absent thermal coverage/time bins and missing spectral bands. Existing regressions cover NASA parser/cache failures, partial horizon states and concurrent analysis overload.
- A newly discovered global analysis response defect (missing scenario ID) was fixed by reusing the authoritative evaluator and scenario store; a recorded-source regression test covers it.
- All original Site04 IDs, coordinates and physical values remain unchanged under the existing full-package validation. Each grid level has 400 crosswalk rows; in this actual small footprint every native cell lies within one global cell. The algorithm does not assume that cardinality.
- Browser interaction opened the whole-Moon map, selected a genuine global cell, then opened all 400 original Site04 cells. Displayed `SITE04_R000_C000` values: elevation 1072.0976434326171 m, slope 32.13135594956228 degrees, roughness 0.9163221785602584 m. The API remains the source of those displayed values.
- The global NASA demonstration evaluated two actual global cell centers. The existing two-cell Site04 original/delayed scenario reproduced **KEEP**. Terrain clearance remained unsupported rather than converted to a clear horizon. Final recorded deliveries were VERIFIED_CACHE; underlying exact NASA retrieval metadata/hashes remain present.

## Performance

Machine: Windows 11, Intel64 Family 6 Model 170, 18 logical CPUs, approximately 16.6 GB RAM, Python 3.13.17.

| Operation | Measured result |
|---|---:|
| NSIDE 64 build | 49,152 cells; 2.34 s |
| NSIDE 128 build | 196,608 cells; 8.91 s |
| NSIDE 256 streamed build | 786,432 cells; 36.44 s |
| Per-level Site04 crosswalk | about 1.5–1.6 s |
| Grid build peak process RSS | 140,427,264 bytes |
| Standard terrain snapshot extraction | 137.93 s |
| Warm lookup / vector | about 0.17 / 0.09 s |
| Warm exact similarity | about 1.00 s |
| Warm thermal bin lookup | about 0.49 s |
| 64-cell geometry tile | about 0.13 s |
| NASA global / Site04 delay from verified cache | about 0.88 / 0.66 s |
| Demonstration peak process RSS | 273,117,184 bytes |

`docs/evidence/global/benchmark.json` contains per-call durations and response sizes. “Cold” means first request in a fresh process, not an OS disk-cache purge. Measurements are machine-specific, not latency guarantees. Full global feature scans are bounded to one fixed 196,608-cell snapshot and use DuckDB memory limits; no unlimited date or spatial workload is accepted. Subsequent integrity hardening rechecks registered file hashes before reads, so current timing may be slightly higher than the saved baseline.

## Limitations and remaining work

1. Terrain area weighting is validated numerical quadrature, not exact analytic pixel-footprint clipping. Sampled extrema/counts are labeled accordingly; no global discretization bound is established.
2. Generic regional crosswalks outside Site04, very large windowed native DEM extraction, detailed-level physical features and NSIDE 512 materialization are not implemented in this release.
3. M3 observation ingestion and spectral indices are unavailable. Only its metadata/band registration guard exists. No embeddings/model are configured. Z-score fitting exists but the public search API exposes only fixed-scale distance.
4. Bbox filtering selects centers. Exact arbitrary spherical footprint region queries are not exposed. Source overlap returns separate supported products rather than statistical fusion.
5. Some heterogeneous evidence metadata uses dictionary contracts; it is not fully typed down to every instrument-specific field. Crosswalks and terrain facts are typed.
6. The test suite is independent numerical/code validation, not external scientific peer review. It does not exhaustively prove every possible spherical edge case or all adversarial cases listed in the original brief.
7. Authentication, deployment hardening and durable dynamic scenario storage are unchanged from the existing local prototype. Source files and feature snapshots survive restart; the bounded dynamic store does not.

Python 3.12/3.13 CI is configured on the PR. Its final status and exact commit are reported in the delivery message; no unexecuted CI success is claimed here. No main-branch merge is authorized or performed.
