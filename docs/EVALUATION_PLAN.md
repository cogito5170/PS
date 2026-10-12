# Evaluation Plan

## 1. Datasets

| Set | Cases | Author | Purpose | Status |
|---|---|---|---|---|
| `eval/dataset/dev.json` | 34 | the engine's developer, alongside the rules | development and regression guard; **optimistic by construction** | in repo |
| `eval/dataset/heldout.json` | 24 | a separate agent told not to read the engine code or the dev set (it read only `eval/DATASET_FORMAT.md`) | estimate of generalization; run **once blind**, then used for failure analysis | in repo; no longer blind after run 1 |
| `eval/dataset/dev_ko.json` | 18 | the engine's developer, alongside the Korean rules | Korean development and regression guard; optimistic by construction | in repo |
| `eval/dataset/heldout_ko.json` | 16 | a separate agent that read only `eval/DATASET_FORMAT.md` and was told not to describe case contents in its report | blind estimate for Korean; run once | in repo |
| future `test` set | ≥ 100 | humans who did not write the rules, with two independent annotators | headline numbers and inter-annotator agreement | not yet built |

1.1 Both sets cover every required category:
- genuine contradictions;
- scope-induced apparent contradictions;
- numerical errors;
- misleading quotations;
- unsupported causal claims;
- duplicate and dependent sources;
- translation errors (German, Spanish and French originals);
- correct claims from low-reputation sources;
- incorrect claims from high-reputation sources, including reliance on a retracted source;
- ambiguous propositions;
- clean controls.

1.2 All documents are synthetic (`"synthetic": true`, example.org/example.com URLs), so no real publication is cited or misrepresented.
1.3 The label format is in `eval/DATASET_FORMAT.md`. Labels match propositions by sentence substring, so they are independent of the extractor's normalization.

## 2. Metrics (all computed by `upae/evaluate.py`)

| Metric | Definition |
|---|---|
| Issue P/R/F1, strict | a predicted issue matches a gold issue when the category is equal and it touches one of the gold sentences |
| Issue P/R/F1, family | the same, but the contradiction family (NUMERICAL, CATEGORICAL, TEMPORAL, INTERNAL, MISSING_CONDITION) and the inference family (INVALID_INFERENCE, UNSUPPORTED_CAUSAL) count as one category each |
| Contradiction detection P/R/F1 | issue scores restricted to the contradiction family |
| Red precision | red warnings that match a gold issue ÷ all red warnings |
| **False-alarm case rate** | cases labeled `no_red` that got at least one red warning ÷ all `no_red` cases (the primary guard against alarm fatigue) |
| Forbidden-category violations | a category marked `forbidden` for a case was raised |
| Proposition recall | gold propositions matched (subject token overlap ≥ 0.5, object overlap, polarity) |
| Proposition precision proxy | matched ÷ all propositions extracted from labeled sentences |
| Relation recall | gold relations found between propositions from the two labeled sentences |
| Status accuracy | the gold status is among the statuses of the propositions from that sentence |
| Independence accuracy | pairwise agreement between the gold partition and the computed independence groups |
| Traceability coverage | the quote is verbatim in its passage, the passage equals its archive span, and a retrieval timestamp is present |
| Calibration | Brier score and expected calibration error (5 bins) for issue confidence (correct means the issue matches gold) and for status confidence (correct means the status matches gold) |
| Compression ratio | words in core-report formulas ÷ source words |
| Latency and cost | wall-clock time per case and per proposition; number of model calls |

## 3. Protocol

3.1 Freeze the code, then run the held-out set once and archive the output unchanged (`eval/results/heldout_run1_blind.*`).
3.2 Every later held-out run is labeled **post-hoc**. It may be used for failure analysis only, never as a generalization claim.
3.3 Report measured results only. Mark estimates as estimates. There are no simulated results in this repository.
3.4 Optimize for precision of red warnings first, then for recall. An acceptance gate for any change is: false-alarm case rate must not rise, and red precision must not fall.
3.5 Reproduce with:
`python -m upae evaluate eval/dataset/dev.json eval/dataset/heldout.json --out report.md --json-out results.json`.

## 4. Planned additions

4.1 A human-annotated test set of real, licensed documents with real-world provenance. It needs a separate process for checking copyright and licences.
4.2 Inter-annotator agreement (Cohen's κ) per issue category. Annotator disagreement bounds the precision any automatic system can reach.
4.3 Measurement at scale: latency and memory with 10⁴ and 10⁶ propositions, and the cost per document when a model provider is enabled.
4.4 Ablations: with versus without implicit publication-time scoping, the anchor heuristic and the strict scope comparison.
