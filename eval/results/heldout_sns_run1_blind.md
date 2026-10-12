### Dataset `heldout_sns` — 14 cases

| Metric | Value |
|---|---|
| Issue detection, family-level P / R / F1 | 0.750 / 0.375 / 0.500 (gold 8, predicted 4) |
| Issue detection, strict-category P / R / F1 | 0.750 / 0.375 / 0.500 |
| Contradiction detection P / R / F1 | 1.000 / 0.200 / 0.333 (gold 5, predicted 1) |
| Red warnings: total / matching a gold issue (precision) | 1 / 1 (1.000) |
| False-alarm rate on `no_red` cases | 0 of 8 (0.000) |
| Red/non-red agreement on found gold issues | 1.000 |
| Forbidden-category violations | 0 |
| Proposition extraction recall (precision proxy) | 0.077 (0.077) — 1/13 |
| Relation recall (predicted relations of labelled types) | 0.000 — 0/2 (0) |
| Status accuracy | 0.333 — 1/3 |
| Evidence-independence pairwise accuracy | 1.000 — 3/3 pairs |
| Source traceability coverage | 1.000 — 79/79 |
| Integrity violations | 0 |
| Issue-confidence calibration (Brier / ECE, n) | 0.175 / 0.100 (n=4) |
| Status-confidence calibration (Brier / ECE, n) | 0.290 / 0.200 (n=2) |
| Report compression ratio (core words / source words) | 0.964 |
| Latency: mean / max per case, per proposition | 7.35 ms / 33.97 ms, 1.302 ms |
| Model calls (processing cost) | 0 |

Per issue category (gold found / gold; predicted matched / predicted):

| Category | Recall | Precision |
|---|---|---|
| AMBIGUOUS_PROPOSITION | 1/1 | 1/2 |
| ARITHMETIC_ERROR | 0/1 | 0/0 |
| DEPENDENT_CORROBORATION | 1/1 | 1/1 |
| NUMERICAL_INCONSISTENCY | 0/1 | 0/0 |
| TEMPORAL_DISAGREEMENT | 1/4 | 1/1 |

Per case:

| Case | Category | Gold issues found (family) | Predicted (red) | Forbidden violated | Statuses |
|---|---|---|---|---|---|
| S01 | timeline_inconsistency | 1/1 | 1 (1) | — | 0/0 |
| S02 | timeline_inconsistency | 0/1 | 0 (0) | — | 0/0 |
| S03 | timeline_inconsistency | 0/1 | 0 (0) | — | 0/0 |
| S04 | timeline_inconsistency | 0/1 | 0 (0) | — | 0/0 |
| S05 | timeline_consistent | 0/0 | 0 (0) | — | 0/0 |
| S06 | timeline_consistent | 0/0 | 0 (0) | — | 0/0 |
| S07 | timeline_consistent | 0/0 | 0 (0) | — | 0/0 |
| S08 | timeline_consistent | 0/0 | 0 (0) | — | 0/0 |
| S09 | genuine_contradiction | 0/1 | 0 (0) | — | 0/0 |
| S10 | scope_difference | 0/0 | 0 (0) | — | 0/0 |
| S11 | numerical_error | 0/1 | 0 (0) | — | 1/1 |
| S12 | ambiguous | 1/1 | 2 (0) | — | 0/0 |
| S13 | dependent_sources | 1/1 | 1 (0) | — | 0/1 |
| S14 | no_issue | 0/0 | 0 (0) | — | 0/1 |

Issue calibration bins: 0.6-0.8: n=4, conf 0.65, acc 0.75

Status calibration bins: 0.6-0.8: n=2, conf 0.7, acc 0.5

