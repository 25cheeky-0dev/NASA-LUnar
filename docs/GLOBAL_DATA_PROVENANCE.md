# Actual source provenance and scientific limits

Downloaded source labels, format definitions, receipts and registrations are retained in `docs/evidence/global/source_manifests`. Raw rasters/tables and generated Parquet remain outside Git under `backend/data/lunar-v1`. Checksums are locally computed integrity hashes following verified HTTPS archive retrieval, not publisher signatures.

| Product actually used | Coverage and interpretation |
|---|---|
| NASA LOLA `LDEM_4`, V3.0, 2,073,600 bytes | Global 4 pixels/degree shape map; 7,580.84 m latitude spacing; 2009-07-13 to 2016-11-29 |
| LROC `WAC_GLOBAL_E000N1800_004P`, v1.3 | Global 4 pixels/degree 643 nm mosaic; 2009-11-07 to 2011-01-31; image context only |
| Diviner `GLOBAL_CUMUL_AVG_CYL_90S80S_002.TAB`, version 1 | 1,382,400 rows; south 90–80 degrees; 0.5-degree spatial bins and 0.25-hour local-time bins; 2009-07-05 to 2015-04-01 |
| Original Site04 V3 package | 400 original 100 m cells, original 5 m DEM, baseline version 2.0.0, processing 3.0.0; package checksum verification unchanged |
| JPL Horizons | Selected-cell Sun/Earth observations, exact UTC and explicit reference altitude; source bytes/hashes cached by existing engine |

LOLA image SHA256: `c04632eba6449af49e3108ed7c25b3b1c450600abd3690df4fc815853a1af476`. Its detached label declares MEAN EARTH/POLAR AXIS OF DE421, all radii 1737.4 km, east longitude, 0.5 scaling and 1737400 offset. Height is **DN×0.5**; the offset is added only for planetary radius. It is not geoid height. Values outside label extrema are rejected; no unlisted missing-data constant is assumed.

LOLA slope uses central differences at ±1 source pixel, with east spacing R cos(latitude) Δlongitude and north spacing R Δlatitude. Roughness is the population standard deviation in a 3×3 source neighborhood, including regional slope; it is not detrended roughness. Longitude wraps. The two outer polar rows have null derivatives because the north/south stencil lacks support. Neither derivative is computed from averaged global cell elevations.

Aggregation uses 256 equal-area nested-child centers per global cell and piecewise-constant source pixels. This is numerical spherical quadrature, not exact footprint integration. Minimum/maximum and `sampled_source_pixel_count` cover the sampled source support, not exhaustive source-pixel intersection counts. Elevation variability is the weighted population standard deviation of samples. Coverage is quadrature-supported valid area, not a laser-shot count. The source itself includes interpolation.

For eight documented audit cells, refinement to 1,024 samples changed mean elevation by at most 7.5503 m, slope by 0.3606 degrees and roughness by 3.6998 m. These are **sampled numerical sensitivity results, not global error bounds or instrument uncertainty**. Exact source-pixel intersections and a global error bound remain future scientific improvements. Native raster values and all source bytes remain available for recomputation.

LROC georeferencing and special PDS float pixels are validated. Image DN units are not declared by this attached label, so they are not called reflectance. The visualization uses a documented percentile contrast stretch. Pixel context is the native pixel containing the selected cell center, with its own footprint; it is not a cell-average physical measurement. NASA's [LRO reference-frame explanation](https://svs.gsfc.nasa.gov/4969/) supports the mission-wide ME/DE421 mapping for LROC and Diviner; no positional uncertainty is inferred.

Diviner input longitude [-180,180] is converted by modulo 360. Native 0.5-degree support is preserved. -9999 and -9998 become null; negative brightness temperatures remain flagged below sensitivity. The caller must choose a local-time bin. The table rounds bin-center times to two decimals. Acquisition years, native footprint, channel names and quality survive retrieval. No channel/time averaging is performed by WISPR. Thermal data are regional context for Site04, not 100 m thermal measurements.

## Unavailable and optional sources

- M3 archive documentation was verified, but no geolocated L2 observation set was ingested. The registration validator checks reflectance metadata, band order, quality and missing bands; it is **not a completed M3 IMG ingestion adapter**. No spectral index or mineral abundance is claimed.
- Moon Trek's documented WMTS API was investigated. No individual WMTS capability set is bound; local source-derived images are used instead.
- Document embeddings are unconfigured. Keyword retrieval over exact registered source metadata is operational and separately scored.
- No shot-count/uncertainty raster was ingested. Quality remains unknown where not supplied. No high-resolution global terrain claim is made.

Official discovery paths: [LOLA GDR](https://ode.rsl.wustl.edu/moon/pagehelp/Content/Missions_Instruments/Lunar%20Reconnaissance%20Orbiter%20(LRO)/LOLA/GDR/GDRDEM.htm), [LROC global mosaic](https://data.lroc.im-ldi.com/lroc/view_rdr/WAC_GLOBAL/), [Diviner PDS](https://pds-geosciences.wustl.edu/missions/lro/diviner.htm), [M3 PDS](https://pds.nasa.gov/ds-view/pds/viewProfile.jsp?dsid=CH1-ORB-L-M3-4-L2-REFLECTANCE-V1.0), [Moon Trek API](https://trek.nasa.gov/tiles/apidoc/).
