### Dataset `dev` — 34 cases

| Metric | Value |
|---|---|
| Issue detection, family-level P / R / F1 | 1.000 / 1.000 / 1.000 (gold 20, predicted 20) |
| Issue detection, strict-category P / R / F1 | 1.000 / 1.000 / 1.000 |
| Contradiction detection P / R / F1 | 1.000 / 1.000 / 1.000 (gold 5, predicted 5) |
| Red warnings: total / matching a gold issue (precision) | 16 / 16 (1.000) |
| False-alarm rate on `no_red` cases | 0 of 17 (0.000) |
| Red/non-red agreement on found gold issues | 1.000 |
| Forbidden-category violations | 0 |
| Proposition extraction recall (precision proxy) | 1.000 (1.000) — 10/10 |
| Relation recall (predicted relations of labelled types) | 1.000 — 9/9 (11) |
| Status accuracy | 1.000 — 8/8 |
| Evidence-independence pairwise accuracy | 1.000 — 12/12 pairs |
| Source traceability coverage | 1.000 — 66/66 |
| Integrity violations | 0 |
| Issue-confidence calibration (Brier / ECE, n) | 0.061 / 0.226 (n=20) |
| Status-confidence calibration (Brier / ECE, n) | 0.106 / 0.217 (n=15) |
| Report compression ratio (core words / source words) | 0.601 |
| Latency: mean / max per case, per proposition | 1.68 ms / 12.93 ms, 0.867 ms |
| Model calls (processing cost) | 0 |

Per issue category (gold found / gold; predicted matched / predicted):

| Category | Recall | Precision |
|---|---|---|
| AMBIGUOUS_PROPOSITION | 2/2 | 2/2 |
| ARITHMETIC_ERROR | 3/3 | 3/3 |
| CATEGORICAL_CONFLICT | 1/1 | 1/1 |
| DEPENDENT_CORROBORATION | 2/2 | 2/2 |
| INTERNAL_INCONSISTENCY | 1/1 | 1/1 |
| INVALID_INFERENCE | 2/2 | 2/2 |
| MISLEADING_QUOTATION | 2/2 | 2/2 |
| NUMERICAL_INCONSISTENCY | 2/2 | 2/2 |
| RETRACTED_SOURCE_DEPENDENCY | 1/1 | 1/1 |
| TEMPORAL_DISAGREEMENT | 1/1 | 1/1 |
| TRANSLATION_DISCREPANCY | 2/2 | 2/2 |
| UNSUPPORTED_CAUSAL_CLAIM | 1/1 | 1/1 |

Per case:

| Case | Category | Gold issues found (family) | Predicted (red) | Forbidden violated | Statuses |
|---|---|---|---|---|---|
| D01 | genuine_contradiction | 1/1 | 1 (1) | — | 0/0 |
| D02 | genuine_contradiction | 1/1 | 1 (1) | — | 0/0 |
| D03 | genuine_contradiction | 1/1 | 1 (1) | — | 0/0 |
| D04 | genuine_contradiction | 1/1 | 1 (1) | — | 0/0 |
| D05 | scope_difference | 0/0 | 0 (0) | — | 0/0 |
| D06 | scope_difference | 0/0 | 0 (0) | — | 0/0 |
| D07 | scope_difference | 0/0 | 0 (0) | — | 0/0 |
| D08 | scope_difference | 0/0 | 0 (0) | — | 0/0 |
| D09 | numerical_error | 1/1 | 1 (1) | — | 0/0 |
| D10 | numerical_error | 1/1 | 1 (1) | — | 0/0 |
| D11 | numerical_error | 1/1 | 1 (1) | — | 0/0 |
| D12 | no_issue | 0/0 | 0 (0) | — | 0/0 |
| D13 | misleading_quotation | 1/1 | 1 (1) | — | 0/0 |
| D14 | misleading_quotation | 1/1 | 1 (1) | — | 0/0 |
| D15 | no_issue | 0/0 | 0 (0) | — | 0/0 |
| D16 | unsupported_causal | 2/2 | 2 (2) | — | 0/0 |
| D17 | unsupported_causal | 1/1 | 1 (1) | — | 0/0 |
| D18 | no_issue | 0/0 | 0 (0) | — | 0/0 |
| D19 | dependent_sources | 1/1 | 1 (0) | — | 1/1 |
| D20 | dependent_sources | 1/1 | 1 (0) | — | 1/1 |
| D21 | translation_error | 1/1 | 1 (1) | — | 0/0 |
| D22 | translation_error | 1/1 | 1 (1) | — | 0/0 |
| D23 | no_issue | 0/0 | 0 (0) | — | 0/0 |
| D24 | low_reputation_correct | 0/0 | 0 (0) | — | 1/1 |
| D25 | high_reputation_incorrect | 1/1 | 1 (1) | — | 1/1 |
| D26 | high_reputation_incorrect | 1/1 | 1 (1) | — | 1/1 |
| D27 | ambiguous | 1/1 | 1 (0) | — | 0/0 |
| D28 | ambiguous | 1/1 | 1 (0) | — | 0/0 |
| D29 | no_issue | 0/0 | 0 (0) | — | 0/0 |
| D30 | no_issue | 0/0 | 0 (0) | — | 1/1 |
| D31 | no_issue | 0/0 | 0 (0) | — | 0/0 |
| D32 | no_issue | 0/0 | 0 (0) | — | 1/1 |
| D34 | no_issue | 0/0 | 0 (0) | — | 1/1 |
| D33 | no_issue | 0/0 | 0 (0) | — | 0/0 |

Issue calibration bins: 0.6-0.8: n=10, conf 0.694, acc 1; 0.8-1.0: n=10, conf 0.854, acc 1

Status calibration bins: 0.6-0.8: n=11, conf 0.655, acc 0.909; 0.8-1.0: n=4, conf 0.883, acc 1

