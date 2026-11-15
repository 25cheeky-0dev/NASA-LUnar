# WISPR Terrain Intelligence — local implementation

Branch: `feature/adaptive-regions-agent` at `C:\Users\manra\Documents\NASA-LUnar`.
Changes are uncommitted. Nothing was pushed, merged, committed or deployed to Google Cloud.

## Implemented

- Integrated **Extract 3D terrain** into the existing Region Intelligence panel.
- Read verified regional DEMs from `WISPR_REGIONAL_CATALOG`, or the original manifest-verified Site04 V3 package from `WISPR_GRID_DIR`. Select the finest intersecting registered source.
- Clip individual terrain triangles against the geographic polygon, including partial triangles, concave boundaries and holes. Boundary heights come from each source triangle's plane. Preserve missing coverage rather than fill it.
- Preview, balanced and native sampling, with explicit memory/triangle limits and actual source/mesh spacing.
- Inside, exclude and global extraction scopes. **Global means the selected source DEM footprint**, not all lunar datasets. Scope selection takes effect when Extract is pressed.
- Orbitable 3D laboratory with grayscale, elevation and mesh-derived slope, surface/block/wireframe modes, top-down/reset, vertical exaggeration, display-only walls and base.
- Persist extracted meshes with stable IDs and source/CRS/datum/resolution/coverage metadata. Export OBJ, lunar GeoJSON, full JSON mesh/manifest, browser-generated GLB and PNG. GLB retains 1× scientific scale regardless of display exaggeration; its metadata records the axis mapping and origin.
- Saved-region browser and names; geographic coordinate editing including additional hole rings; original versions remain saved. Drawing undo/redo and matching polygon outlines on the globe.
- Supplied Montserrat font and license, supplied logo image, restrained colors and 1× default vertical scale.
- Preserve existing grid IDs, vector/retrieval services, region scientific jobs, AI assistant and representative-point Sun/Earth comparison.

## Validation

- Backend: **272 passed, 9 skipped** with `backend/.venv/Scripts/python.exe -m pytest backend -q --disable-warnings` from the repository root.
- Frontend: `npm run build` and `npm test` passed. Vite retains a warning for a Three.js chunk over 500 kB.
- New tests independently verify analytic-plane elevation preservation, triangle/edge clipping, holes, NoData at coarser LOD, no coverage, corrupted sources, scope-area partitioning, persistence, names and export metadata.
- Test HTTP rate counters now reset between independent test cases; production rate limiting remains unchanged.
- API contracts regenerated; Shapely minimum updated to 2.1 for constrained triangulation. Existing lock resolves Shapely 2.2.0.
- Local FastAPI production/static preview starts successfully. Browser visual verification could not complete: in-app browser attachment timed out; native Chrome activation/input failed.
- Docker was unavailable in the execution environment, so no container build was executed. Existing Docker and Google Cloud configuration were retained.

Synthetic raster fixtures are **test-only**. No synthetic terrain or fabricated science is exposed as real lunar data.

## Data setup and use

1. Configure an existing verified Site04 package with `WISPR_GRID_DIR`, or a regional catalog with `WISPR_REGIONAL_CATALOG`, before starting the backend. The pre-existing `app/regions/local.py` defines the catalog contract: source ID, path, SHA-256, `MOON_ME_DE421`, metre units, vertical reference and metre-based lunar grid CRS/origin/root width.
2. Open Regions, draw a polygon on the existing surface or globe, then Finish. Saved regions can be reopened or edited in **Saved regions & geographic editor**.
3. Select **Extract 3D terrain**, choose scope/resolution, and extract. The source must actually cover the selection. Missing data produces an explicit error.
4. Download the JSON mesh/manifest together with OBJ or GLB to retain complete georeferencing.

The local checkout contains coarse global LOLA data, but no high-resolution regional TIFF was found in its data directory. NASA's public file server timed out while fetching the LOLA README, so a real Site04 extraction benchmark was not completed. The official [NASA LOLA product page](https://pgda.gsfc.nasa.gov/products/78) documents the 5 m south-polar products and MOON_ME/DE421 frame. A label or pixel spacing alone does not verify a vertical datum conversion for ephemeris work.

## Remaining work — full brief is not complete

- Polygon-wide Sun illumination, dynamic terrain shadows and Earth-visibility overlays are **not implemented in the new laboratory**. Existing representative-point celestial analysis and conservative terrain-horizon services remain separate. Laboratory lighting is explicitly illustrative.
- No new miniature Moon locator with physical celestial directions, finite-disc model, polygon-area availability timeline or communication link-budget model.
- No drag-handle vertex editing or drawing directly on extracted meshes; geographic JSON editing is supported. No new 2D map editor.
- No multi-tile DEM mosaics, exploded layers, contours, cross-section tools, independent layer-opacity stack or side-by-side mesh comparison.
- No new 3/5/8 candidate-discovery workflow or new numerical tools wired into the AI planner. Existing retrieval and comparison workflows are preserved.
- The existing region summary can still describe coarse/global support while the laboratory independently discovers a configured regional source; these capability reports need unification.
- Extraction is synchronous and bounded, with persisted results. It does not yet provide a cancellable server-side extraction job or incremental refinement.
- The full requested Shackleton → polygon → 3D → time-varying Sun/Earth → AI acceptance demonstration remains outstanding.

No deployment should be inferred from passing local tests.
