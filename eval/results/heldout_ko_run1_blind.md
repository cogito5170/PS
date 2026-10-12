### Dataset `heldout_ko` — 16 cases

| Metric | Value |
|---|---|
| Issue detection, family-level P / R / F1 | 0.286 / 0.154 / 0.200 (gold 13, predicted 7) |
| Issue detection, strict-category P / R / F1 | 0.286 / 0.154 / 0.200 |
| Contradiction detection P / R / F1 | n/a / 0.000 / n/a (gold 3, predicted 0) |
| Red warnings: total / matching a gold issue (precision) | 2 / 1 (0.500) |
| False-alarm rate on `no_red` cases | 0 of 6 (0.000) |
| Red/non-red agreement on found gold issues | 1.000 |
| Forbidden-category violations | 0 |
| Proposition extraction recall (precision proxy) | 0.417 (0.417) — 15/36 |
| Relation recall (predicted relations of labelled types) | 0.000 — 0/11 (0) |
| Status accuracy | 0.286 — 2/7 |
| Evidence-independence pairwise accuracy | 1.000 — 11/11 pairs |
| Source traceability coverage | 1.000 — 94/94 |
| Integrity violations | 0 |
| Issue-confidence calibration (Brier / ECE, n) | 0.321 / 0.443 (n=7) |
| Status-confidence calibration (Brier / ECE, n) | 0.357 / 0.367 (n=6) |
| Report compression ratio (core words / source words) | 0.960 |
| Latency: mean / max per case, per proposition | 6.35 ms / 26.23 ms, 1.081 ms |
| Model calls (processing cost) | 0 |

Per issue category (gold found / gold; predicted matched / predicted):

| Category | Recall | Precision |
|---|---|---|
| AMBIGUOUS_PROPOSITION | 0/2 | 0/3 |
| ARITHMETIC_ERROR | 0/2 | 0/0 |
| CATEGORICAL_CONFLICT | 0/1 | 0/0 |
| DEPENDENT_CORROBORATION | 1/1 | 1/2 |
| MISLEADING_QUOTATION | 0/1 | 0/0 |
| NUMERICAL_INCONSISTENCY | 0/1 | 0/0 |
| TEMPORAL_DISAGREEMENT | 0/1 | 0/0 |
| TRANSLATION_DISCREPANCY | 1/2 | 1/2 |
| UNSUPPORTED_CAUSAL_CLAIM | 0/2 | 0/0 |

Per case:

| Case | Category | Gold issues found (family) | Predicted (red) | Forbidden violated | Statuses |
|---|---|---|---|---|---|
| K01 | genuine_contradiction | 0/1 | 0 (0) | — | 0/0 |
| K02 | genuine_contradiction | 0/1 | 1 (0) | — | 0/0 |
| K03 | scope_difference | 0/0 | 2 (0) | — | 2/2 |
| K04 | scope_difference | 0/0 | 0 (0) | — | 0/1 |
| K05 | numerical_error | 0/1 | 0 (0) | — | 0/0 |
| K06 | numerical_error | 0/1 | 0 (0) | — | 0/0 |
| K07 | misleading_quotation | 0/1 | 0 (0) | — | 0/0 |
| K08 | unsupported_causal | 0/1 | 1 (0) | — | 0/1 |
| K09 | unsupported_causal | 0/1 | 0 (0) | — | 0/0 |
| K10 | dependent_sources | 1/1 | 1 (0) | — | 0/1 |
| K11 | translation_error | 0/1 | 1 (1) | — | 0/0 |
| K12 | translation_error | 1/1 | 1 (1) | — | 0/0 |
| K13 | low_reputation_correct | 0/0 | 0 (0) | — | 0/1 |
| K14 | high_reputation_incorrect | 0/1 | 0 (0) | — | 0/1 |
| K15 | ambiguous | 0/2 | 0 (0) | — | 0/0 |
| K16 | no_issue | 0/0 | 0 (0) | — | 0/0 |

Issue calibration bins: 0.6-0.8: n=6, conf 0.658, acc 0.167; 0.8-1.0: n=1, conf 0.85, acc 1

Status calibration bins: 0.6-0.8: n=6, conf 0.7, acc 0.333

