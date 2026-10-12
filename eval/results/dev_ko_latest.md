### Dataset `dev_ko` — 18 cases

| Metric | Value |
|---|---|
| Issue detection, family-level P / R / F1 | 1.000 / 1.000 / 1.000 (gold 13, predicted 13) |
| Issue detection, strict-category P / R / F1 | 1.000 / 1.000 / 1.000 |
| Contradiction detection P / R / F1 | 1.000 / 1.000 / 1.000 (gold 4, predicted 4) |
| Red warnings: total / matching a gold issue (precision) | 10 / 10 (1.000) |
| False-alarm rate on `no_red` cases | 0 of 8 (0.000) |
| Red/non-red agreement on found gold issues | 1.000 |
| Forbidden-category violations | 0 |
| Proposition extraction recall (precision proxy) | 1.000 (1.000) — 4/4 |
| Relation recall (predicted relations of labelled types) | 1.000 — 5/5 (5) |
| Status accuracy | 1.000 — 4/4 |
| Evidence-independence pairwise accuracy | 1.000 — 8/8 pairs |
| Source traceability coverage | 1.000 — 39/39 |
| Integrity violations | 0 |
| Issue-confidence calibration (Brier / ECE, n) | 0.070 / 0.241 (n=13) |
| Status-confidence calibration (Brier / ECE, n) | 0.056 / 0.224 (n=8) |
| Report compression ratio (core words / source words) | 0.748 |
| Latency: mean / max per case, per proposition | 3.1 ms / 21.04 ms, 1.429 ms |
| Model calls (processing cost) | 0 |

Per issue category (gold found / gold; predicted matched / predicted):

| Category | Recall | Precision |
|---|---|---|
| AMBIGUOUS_PROPOSITION | 2/2 | 2/2 |
| ARITHMETIC_ERROR | 2/2 | 2/2 |
| CATEGORICAL_CONFLICT | 1/1 | 1/1 |
| DEPENDENT_CORROBORATION | 1/1 | 1/1 |
| INTERNAL_INCONSISTENCY | 1/1 | 1/1 |
| INVALID_INFERENCE | 1/1 | 1/1 |
| MISLEADING_QUOTATION | 1/1 | 1/1 |
| NUMERICAL_INCONSISTENCY | 2/2 | 2/2 |
| TRANSLATION_DISCREPANCY | 1/1 | 1/1 |
| UNSUPPORTED_CAUSAL_CLAIM | 1/1 | 1/1 |

Per case:

| Case | Category | Gold issues found (family) | Predicted (red) | Forbidden violated | Statuses |
|---|---|---|---|---|---|
| KD01 | genuine_contradiction | 1/1 | 1 (1) | — | 0/0 |
| KD02 | genuine_contradiction | 1/1 | 1 (1) | — | 0/0 |
| KD03 | genuine_contradiction | 1/1 | 1 (1) | — | 0/0 |
| KD04 | scope_difference | 0/0 | 0 (0) | — | 0/0 |
| KD05 | scope_difference | 0/0 | 0 (0) | — | 0/0 |
| KD06 | scope_difference | 0/0 | 0 (0) | — | 0/0 |
| KD07 | numerical_error | 1/1 | 1 (1) | — | 0/0 |
| KD08 | numerical_error | 1/1 | 1 (1) | — | 0/0 |
| KD09 | misleading_quotation | 1/1 | 1 (1) | — | 0/0 |
| KD10 | unsupported_causal | 2/2 | 2 (2) | — | 0/0 |
| KD11 | dependent_sources | 1/1 | 1 (0) | — | 1/1 |
| KD12 | translation_error | 1/1 | 1 (1) | — | 0/0 |
| KD13 | no_issue | 0/0 | 0 (0) | — | 0/0 |
| KD14 | low_reputation_correct | 0/0 | 0 (0) | — | 1/1 |
| KD15 | high_reputation_incorrect | 1/1 | 1 (1) | — | 1/1 |
| KD16 | ambiguous | 2/2 | 2 (0) | — | 0/0 |
| KD17 | no_issue | 0/0 | 0 (0) | — | 0/0 |
| KD18 | no_issue | 0/0 | 0 (0) | — | 1/1 |

Issue calibration bins: 0.6-0.8: n=8, conf 0.693, acc 1; 0.8-1.0: n=5, conf 0.864, acc 1

Status calibration bins: 0.6-0.8: n=5, conf 0.726, acc 1; 0.8-1.0: n=3, conf 0.86, acc 1

