# Retrieval APIs
Existing global `/cells/{id}/features`, `/vectors`, `/sources`, `/similarity`, `/source-overlap`, `/regional/{id}/crosswalk`, `/retrieval` and candidate APIs are preserved.

Native `/datasets/{id}/similarity/{cell}` is strict by default. Null/untyped uncertainty cannot qualify. `accept_unknown_uncertainty=true` enables explicitly labeled DESCRIPTIVE_SIMILARITY_ONLY for compatible source evidence; incompatible structured uncertainty is still rejected. Verified uncertainty requires a known schema, matching source and terrain definition, citation, verified quality, exact feature/unit coverage and finite nonnegative numeric standard uncertainties; booleans are rejected.

`POST /representations/fit`: dataset_id, dimensions. `POST /representations/search`: dataset_id, model_id, cell_id, space, limit, accept_descriptive_similarity. Both are under `/api/v1/science`; computation uses the shared two-slot capacity gate. Model fitting and searches are descriptive, not safety recommendations.

`GET /global/thermal-observations`: west/south/east/north, local_time_bin 0–95, channel t3–t9 or tbol, limit <=1000. Split antimeridian bboxes. Historical native-pixel context only.

Stable requests and complete responses are recorded in [workflow.json](evidence/final-backend/workflow.json).

Executed evidence: [final-backend evidence](evidence/final-backend/). Historical global validation remains in [GLOBAL_VALIDATION_REPORT.md](GLOBAL_VALIDATION_REPORT.md).
