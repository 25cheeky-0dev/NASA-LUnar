# Interactive verification — macOS Apple Silicon

Executed in the Codex in-app browser on development port 5173 and the production build served by FastAPI on port 8000. Clean Python environment used for production startup.

- Named Apollo 11 navigation selected `MOON:HPX:NESTED:128:71342`; center 0.59684° latitude / 23.55469° E differed from the explicitly labeled historical point 0.674° / 23.473°. Missing terrain stayed Unknown.
- Full original Site04 loaded 400 cells. Selecting `SITE04_R010_C010` displayed -89.75058°, -176.58906°, slope 31.28°, elevation 425.07 m and roughness 1.32 m (rounded presentation only).
- Original checksum-verified GLB loaded with source Z-up to renderer Y-up and no vertical exaggeration. Separate cell atlas switched to elevation colors.
- Maximum slope 10° returned 0 matching cells / 400. No fake suitable candidate appeared.
- Explicit offline demo returned PRESERVED_REAL_DATA_OFFLINE and KEEP. Delayed shared durations: 168.00 h for both cells; baseline: 99.82 and 99.81 h. First baseline qualifying window: 2026-11-17 20:11:02.906166Z; wait 4091.0 min; duration 5989.0 min for first cell. Values agree with fresh backend evidence to display precision.
- Normal structured Calculate action returned SOURCE-BACKED CALCULATION / KEEP for the same selected cells (validated NASA cache available). It does not call the explicit offline-demo route.
- Switching to partial terrain produced INSUFFICIENT DATA, 100% unknown, Unknown durations, no qualifying window. It retained geometric elevation curves but made no terrain-clearance claim.
- Language input without configured credentials displayed the explicit unavailable-provider message; no values or rankings were manufactured.
- Browser console error/warning capture returned an empty list on the production comparison/terrain-unknown flow.
- Production same-origin API repair was necessary; early failed CORS run was reproduced, fixed and retested.
- Actual canvas drag rotated the Moon and scroll changed zoom; the loaded textured globe and selected marker were observed. Final atlas, terrain and comparison screenshots are saved alongside this record.

Limits: browser developer capture supplied console messages, not a complete network HAR. All possible input sequences, screen readers, Windows GPUs and broad load/device matrices were not executed. Screenshots are retained here as visual evidence; tests and source responses are the numerical evidence.
