# Frontend handoff

React + TypeScript + Vite. `npm run dev` serves the app; `npm run build` typechecks and builds. API base URL defaults to `http://localhost:8000`. No provider secrets belong in this folder.

Working: required manual UTC arrival, R01/R04 selection, 24/48-hour studies, exact 168h delay, 180min shared constraint, cadence and bounded daily future search, geometric/terrain modes, optional reviewed language interpretation, all six recommendation labels, four-scenario selection, gapped elevation chart, window/unknown timeline, CSV link, projected 18-cell map, stable-ID details, reference-point feature scatter and ENU sky time slider. Physical scatter selections highlight the same containing grid ID while stating that the cell center remains unevaluated.

`VITE_USE_MOCKS=true` is standalone, without backend requests: deterministic grid fixtures, explicitly synthetic observations and an outcome selector. A persistent `SYNTHETIC EXAMPLE — NOT NASA DATA` banner labels the entire mode. Live errors do not load fixtures.

Browser QA: live/cached example at 2026-11-20 UTC displayed KEEP; selecting delayed R04 updated chart/export; grid selection displayed coordinates; terrain mode displayed four UNKNOWN scenarios and INSUFFICIENT_DATA; 390px mobile view had no horizontal overflow. Production typecheck/build passed. Screenshots are in `docs/evidence/` at repository root.

Deferred: local terrain mesh and verified terrain horizon overlay. NASA DEM downloads timed out, so neither fabricated heights nor decorative terrain is shown. Raster ingestion and partial-horizon API exist but have not been validated against an actual downloaded NASA DEM.
