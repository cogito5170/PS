### Dataset `heldout` — 24 cases

| Metric | Value |
|---|---|
| Issue detection, family-level P / R / F1 | 0.824 / 0.778 / 0.800 (gold 18, predicted 17) |
| Issue detection, strict-category P / R / F1 | 0.824 / 0.778 / 0.800 |
| Contradiction detection P / R / F1 | 0.667 / 0.500 / 0.571 (gold 4, predicted 3) |
| Red warnings: total / matching a gold issue (precision) | 10 / 8 (0.800) |
| False-alarm rate on `no_red` cases | 0 of 12 (0.000) |
| Red/non-red agreement on found gold issues | 1.000 |
| Forbidden-category violations | 0 |
| Proposition extraction recall (precision proxy) | 0.634 (0.578) — 26/41 |
| Relation recall (predicted relations of labelled types) | 0.263 — 5/19 (15) |
| Status accuracy | 0.429 — 6/14 |
| Evidence-independence pairwise accuracy | 1.000 — 27/27 pairs |
| Source traceability coverage | 1.000 — 132/132 |
| Integrity violations | 0 |
| Issue-confidence calibration (Brier / ECE, n) | 0.147 / 0.115 (n=17) |
| Status-confidence calibration (Brier / ECE, n) | 0.295 / 0.361 (n=14) |
| Report compression ratio (core words / source words) | 0.830 |
| Latency: mean / max per case, per proposition | 4.15 ms / 14.0 ms, 0.754 ms |
| Model calls (processing cost) | 0 |

Per issue category (gold found / gold; predicted matched / predicted):

| Category | Recall | Precision |
|---|---|---|
| AMBIGUOUS_PROPOSITION | 3/3 | 3/4 |
| ARITHMETIC_ERROR | 1/2 | 1/1 |
| CATEGORICAL_CONFLICT | 0/2 | 0/0 |
| DEPENDENT_CORROBORATION | 2/2 | 2/2 |
| INVALID_INFERENCE | 0/1 | 0/0 |
| MISLEADING_QUOTATION | 2/2 | 2/2 |
| MISSING_CONDITION | 0/0 | 0/1 |
| NUMERICAL_INCONSISTENCY | 1/1 | 1/1 |
| RETRACTED_SOURCE_DEPENDENCY | 1/1 | 1/2 |
| TEMPORAL_DISAGREEMENT | 1/1 | 1/1 |
| TRANSLATION_DISCREPANCY | 2/2 | 2/2 |
| UNSUPPORTED_CAUSAL_CLAIM | 1/1 | 1/1 |

Per case:

| Case | Category | Gold issues found (family) | Predicted (red) | Forbidden violated | Statuses |
|---|---|---|---|---|---|
| H01 | genuine_contradiction | 1/1 | 1 (1) | — | 0/0 |
| H02 | scope_difference | 0/0 | 0 (0) | — | 0/0 |
| H03 | numerical_error | 1/1 | 1 (1) | — | 0/0 |
| H04 | misleading_quotation | 1/1 | 1 (1) | — | 1/1 |
| H05 | unsupported_causal | 1/1 | 1 (0) | — | 0/0 |
| H06 | dependent_sources | 1/1 | 1 (0) | — | 1/1 |
| H07 | translation_error | 1/1 | 1 (1) | — | 0/0 |
| H08 | low_reputation_correct | 0/0 | 0 (0) | — | 0/2 |
| H09 | high_reputation_incorrect | 1/2 | 2 (2) | — | 1/2 |
| H10 | ambiguous | 1/1 | 1 (0) | — | 0/0 |
| H11 | no_issue | 0/0 | 0 (0) | — | 0/1 |
| H12 | genuine_contradiction | 0/1 | 0 (0) | — | 0/0 |
| H13 | scope_difference | 0/0 | 0 (0) | — | 0/0 |
| H14 | numerical_error | 0/1 | 0 (0) | — | 0/0 |
| H15 | misleading_quotation | 1/1 | 2 (1) | — | 0/0 |
| H16 | unsupported_causal | 0/1 | 0 (0) | — | 0/0 |
| H17 | dependent_sources | 1/1 | 1 (0) | — | 0/1 |
| H18 | translation_error | 1/1 | 1 (1) | — | 0/0 |
| H19 | low_reputation_correct | 0/0 | 0 (0) | — | 0/1 |
| H20 | high_reputation_incorrect | 1/1 | 2 (2) | — | 1/2 |
| H21 | ambiguous | 2/2 | 2 (0) | — | 0/0 |
| H22 | no_issue | 0/0 | 0 (0) | — | 1/2 |
| H23 | no_issue | 0/0 | 0 (0) | — | 1/1 |
| H24 | no_issue | 0/0 | 0 (0) | — | 0/0 |

Issue calibration bins: 0.6-0.8: n=12, conf 0.653, acc 0.75; 0.8-1.0: n=5, conf 0.84, acc 1

Status calibration bins: 0.6-0.8: n=11, conf 0.692, acc 0.273; 0.8-1.0: n=3, conf 0.85, acc 1

