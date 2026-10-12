### Dataset `dev_sns` — 10 cases

| Metric | Value |
|---|---|
| Issue detection, family-level P / R / F1 | 1.000 / 1.000 / 1.000 (gold 6, predicted 6) |
| Issue detection, strict-category P / R / F1 | 1.000 / 1.000 / 1.000 |
| Contradiction detection P / R / F1 | 1.000 / 1.000 / 1.000 (gold 4, predicted 4) |
| Red warnings: total / matching a gold issue (precision) | 5 / 5 (1.000) |
| False-alarm rate on `no_red` cases | 0 of 5 (0.000) |
| Red/non-red agreement on found gold issues | 1.000 |
| Forbidden-category violations | 0 |
| Proposition extraction recall (precision proxy) | n/a (n/a) — 0/0 |
| Relation recall (predicted relations of labelled types) | n/a — 0/0 (0) |
| Status accuracy | n/a — 0/0 |
| Evidence-independence pairwise accuracy | n/a — 0/0 pairs |
| Source traceability coverage | 1.000 — 20/20 |
| Integrity violations | 0 |
| Issue-confidence calibration (Brier / ECE, n) | 0.083 / 0.267 (n=6) |
| Status-confidence calibration (Brier / ECE, n) | n/a / n/a (n=0) |
| Report compression ratio (core words / source words) | 0.917 |
| Latency: mean / max per case, per proposition | 6.05 ms / 37.7 ms, 3.027 ms |
| Model calls (processing cost) | 0 |

Per issue category (gold found / gold; predicted matched / predicted):

| Category | Recall | Precision |
|---|---|---|
| AMBIGUOUS_PROPOSITION | 1/1 | 1/1 |
| ARITHMETIC_ERROR | 1/1 | 1/1 |
| NUMERICAL_INCONSISTENCY | 1/1 | 1/1 |
| TEMPORAL_DISAGREEMENT | 3/3 | 3/3 |

Per case:

| Case | Category | Gold issues found (family) | Predicted (red) | Forbidden violated | Statuses |
|---|---|---|---|---|---|
| SD01 | timeline_consistent | 0/0 | 0 (0) | — | 0/0 |
| SD02 | timeline_inconsistency | 1/1 | 1 (1) | — | 0/0 |
| SD03 | timeline_inconsistency | 1/1 | 1 (1) | — | 0/0 |
| SD04 | timeline_consistent | 0/0 | 0 (0) | — | 0/0 |
| SD05 | timeline_inconsistency | 1/1 | 1 (1) | — | 0/0 |
| SD06 | timeline_consistent | 0/0 | 0 (0) | — | 0/0 |
| SD07 | numerical_error | 1/1 | 1 (1) | — | 0/0 |
| SD08 | genuine_contradiction | 1/1 | 1 (1) | — | 0/0 |
| SD09 | ambiguous | 1/1 | 1 (0) | — | 0/0 |
| SD10 | no_issue | 0/0 | 0 (0) | — | 0/0 |

Issue calibration bins: 0.6-0.8: n=5, conf 0.69, acc 1; 0.8-1.0: n=1, conf 0.95, acc 1

