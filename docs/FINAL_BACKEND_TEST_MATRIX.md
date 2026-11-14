# Executed release matrix
| Check | Evidence/result |
|---|---|
| Clean locked Python 3.13 full suite | 239 passed, no skips, 1 deprecation warning; pytest.txt/xml |
| Real native HTTP | 16 calls; 400 original records and all 30 manifest hashes; site04-http.json |
| Global → native → vectors → terrain → NASA → delay HTTP | 22 calls; workflow.json |
| Fresh live Horizons | 169 samples plus independently queried short interval; live-nasa.json |
| Original data integrity | dataset digest unchanged; 400 polygons, 1,520 edges |
| Uncertainty regression | four cases failed before repair; malformed/source/unit cases now pass |
| Numerical representation | independent Euclidean/z-score checks; full PCA preserves distance |
| Adversarial controls | corrupt/stale model, topology, unsafe source URLs, bounds and 429 tests |
| CI Python 3.12/3.13 | required on final PR; exact run linked in delivery |
| Frontend diff | none relative to starting global-fusion commit |

CI intentionally runs offline: live tests deselected and external-data tests skip when assets are absent. Local full run has no skips. Test counts after further added checks are reported in delivery and raw logs; no failures are hidden. Benchmark results are machine-specific and saved in performance.json.

Executed evidence: [final-backend evidence](evidence/final-backend/). Historical global validation remains in [GLOBAL_VALIDATION_REPORT.md](GLOBAL_VALIDATION_REPORT.md).
