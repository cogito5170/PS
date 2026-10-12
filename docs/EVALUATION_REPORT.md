# Evaluation Report

Measured on 2026-10-12 in the development container (Linux, 4 vCPU, Python 3.13), engine `upae-0.1.0`, with no model provider (0 model calls).
Raw outputs are in `eval/results/`. Every number below was produced by `upae/evaluate.py`; **nothing is simulated or estimated**.

## 1. Headline (read this first)

1. **Blind held-out run** (`heldout_run1_blind`): the only number that estimates generalization.

| Metric | Blind held-out (24 cases) |
|---|---|
| Issue detection P / R / F1 (family) | **0.73 / 0.44 / 0.55** (gold 18, predicted 11) |
| Contradiction detection P / R / F1 | 1.00 / 0.25 / 0.40 (gold 4) |
| Red warnings that match a gold issue | 5 of 6 (0.83) |
| False-alarm rate on the 12 `no_red` cases | **0 of 12** |
| Forbidden-category violations | 0 |
| Proposition extraction recall / precision proxy | 0.61 / 0.60 (25 of 41) |
| Relation recall | 0.11 (2 of 19) |
| Status accuracy | 0.29 (4 of 14) |
| Independence-group accuracy | 1.00 (27 of 27 pairs) |
| Source traceability coverage | 1.00 (129 of 129) |
| Issue confidence: Brier / ECE | 0.170 / 0.042 (n=11) |
| Status confidence: Brier / ECE | 0.362 / 0.511 (n=14). **Poorly calibrated.** |
| Compression ratio | 0.85 |
| Latency | 4.2 ms per case, 0.77 ms per proposition |

2. Interpretation:
   - The engine is **conservative**: it raised no red warning on any case that should have none, and most red warnings it raised were right.
   - It **misses about half of the problems**. The main cause is that the English rule extractor and the token-based alignment cannot match paraphrases.
   - Its status labels are unreliable when evidence is phrased indirectly.

3. **Post-hoc held-out run** (`heldout_run2_posthoc`), after reading the failing cases and making the general changes listed in §4. These numbers are **not blind** and overstate generalization:
   - issue P / R / F1: 0.83 / 0.83 / 0.83;
   - contradiction F1: 0.75;
   - red precision: 0.82 (9 of 11);
   - false alarms: 0 of 12;
   - proposition recall: 0.63;
   - relation recall: 0.32;
   - status accuracy: 0.43;
   - status ECE: 0.36.

4. **Development set** (`dev_latest`, 34 cases written together with the rules), used as a regression guard only:
   - issue F1: 1.00;
   - false alarms: 0 of 17;
   - status accuracy: 1.00 (8 of 8);
   - traceability: 1.00.

   The gap between dev (1.00) and blind held-out (0.55) is a direct measure of overfitting to the developer's own phrasing.

## 2. Contamination and bias disclosures

1. Before run 1, the held-out author's hand-back message summarized some cases, for example "H18 French *peut* translated as *must*". Before run 1 I replaced the translation hedge lexicon with possibility/necessity/universal *modal-class* lexicons. That is a principled change, but it was made knowing such a case existed. H18 may therefore be optimistic even in the blind run.
2. Both datasets were produced by language-model agents in the same session. They share stylistic habits and are not substitutes for human-written, real-world text.
3. The held-out author labeled UNSUPPORTED_CAUSAL_CLAIM and INVALID_INFERENCE as non-red. The engine's policy makes explicit invalid inferences red. On the blind run the only causal issue found (H05) was non-red, so red/non-red agreement on found issues was 1.00, but this policy difference is unresolved (IMPLEMENTATION_PLAN §2.6).
4. Some predicted issues counted as false positives are arguably correct but unlabeled:
   - H09: a second RETRACTED_SOURCE_DEPENDENCY on the textbook's follow-up sentence;
   - H15: a vague-quantifier AMBIGUOUS_PROPOSITION on "Several clinics".

   Precision is therefore a lower bound, and these were *not* relabeled.

## 3. Error analysis (held-out, run 1)

| Case | Miss | Root cause | Fixed in run 2? |
|---|---|---|---|
| H06, H17 | dependent corroboration | copies were reworded, so no DUPLICATES alignment | yes: anchor heuristic (shared number + terms within an independence group) |
| H09 | contradiction "improves by 30 %" vs "found no difference" | "no difference in X between A and B" not parsed; retraction rule needed ≥ 2 shared words | partly: negated effect parsed and retraction found; the effect conflict is still missed (different object wording: "memory" vs "word-recall scores") |
| H10 | ambiguous "it" | pronoun in a subordinate clause was not checked | yes |
| H12 | signing-place conflict | event place not extracted; "the treaty" not resolved to the full name | yes: event place extracted, coreference resolved, and event places treated as single-valued. A first version of this rule did not fire (it was restricted to the predicate "is"); this was found while writing this report and fixed with a unit test |
| H14 | 3 × 3.5 MW ≠ 12 MW | multiplication across sentences is not checked | no |
| H15 | misquotation | the original quote sat in a document without an author; only authored documents were searched | yes: quotes attributed to the same speaker are compared, and direction is taken from `cites` |
| H16 | over-generalization ("for everyone") | conclusion and premise are in different documents; no inference marker | no |
| H20 | canal opening year | "opened … on 14 May 1831" not parsed; the month "May" was read as the modal *may*, turning the claim into a hedge and so APPARENT | yes; new error: the temporal clause "when the first barges passed" is read as a *condition*, causing a red MISSING_CONDITION (counted as a false positive in run 2) |

## 4. Changes between run 1 and run 2

All changes are general rules; no case-specific strings were added:
- event date or place patterns, appositive events and date formats;
- the "no difference" negated effect;
- month "May" is no longer the modal *may*;
- bare definite-description coreference;
- the anchor heuristic for reworded copies, with DERIVED_FROM relations;
- one dependency issue per independence group;
- quotation comparison against quotes attributed to the same speaker, respecting citation direction;
- subordinate-clause pronoun ambiguity;
- the retraction token rule relaxed to one distinctive shared word;
- power units (megawatts and similar).

The dev set stayed at F1 1.00 with 0 false alarms, and the unit tests stayed green.

## 5. Other measured properties

1. **Integrity**: 0 referential-integrity violations across all 58 cases and the demo corpus.
2. **Determinism**: two runs on the same input give byte-identical snapshots, apart from wall-clock timings (`test_deterministic_output`).
3. **Stable IDs**: re-running with `--previous` keeps every ID. Adding one document adds exactly one proposition and leaves existing IDs unchanged (`test_stable_ids_and_diff`).
4. **Demo corpus** (`examples/corpus`, 18 sources in 6 formats including an unreadable PDF and a Korean document):
   - 27 propositions, 31 relations, 12 issues (9 red), all of them intended;
   - the unreadable PDF and the unextracted Korean passage are both reported as limitations.
5. **Unit tests**: 93 tests pass (`python -m unittest discover -s tests -t .`, about 0.4 s).

## 6. What these results do *not* show

1. Performance on real-world text: news, papers, social media, long documents, OCR noise.
2. Extraction quality for any language other than English. Other languages are detected and compared against translations only.
3. Scalability beyond a few dozen documents.
4. The cost or quality of the optional model provider, which was not exercised: there were no credentials and no network.

## 7. Korean (added later in the same session)

Measured on 2026-10-12 against the Korean rule extractor (`upae/extract_ko.py`). The protocol is the same as for English:
- the code was committed and pushed (`1cf591f`) **before** the blind run;
- a separate agent wrote the held-out set after reading only `eval/DATASET_FORMAT.md`, and it was told not to describe any case contents in its report.

| Metric | Korean dev (18, own cases) | **Korean held-out, blind** (16) | Korean held-out, post-hoc |
|---|---|---|---|
| Issue P / R / F1 (family) | 1.00 / 1.00 / 1.00 | **0.29 / 0.15 / 0.20** | 0.67 / 0.46 / 0.55 |
| Contradiction detection recall | 1.00 (4 of 4) | **0.00 (0 of 3)** | 0.00 (0 of 3) |
| Red warnings that match a gold issue | 10 of 10 | **1 of 2** | 3 of 3 |
| False alarms on `no_red` cases | 0 of 8 | **0 of 6** | 0 of 6 |
| Proposition recall | 1.00 (4 of 4) | **0.42 (15 of 36)** | 0.53 (19 of 36) |
| Status accuracy | 1.00 (4 of 4) | **0.29 (2 of 7)** | 0.43 (3 of 7) |
| Independence accuracy / traceability | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 |

Raw files: `eval/results/heldout_ko_run1_blind.*`, `heldout_ko_run2_posthoc.*` and `dev_ko_latest.*`.

### 7.1 Interpretation

1. The blind number (F1 0.20) is the honest one. The Korean rules fit the developer's own sentences (dev 1.00) but not natural Korean news prose.
2. The engine stays conservative in Korean as well: it raised no false alarm on any clean case.

### 7.2 Root causes found in the blind run

All of these were fixed as general rules before the post-hoc run:
- quotations with an adverbial before them (`교수는 인터뷰에서 "…"`);
- curly quotation marks splitting sentences;
- predicates without an object marker (`3위로 마쳤다`);
- comparative predicates (`전년보다 1.8도 낮았다`);
- passive value verbs (`기록되었다`, `이른다`);
- completion events (`축조가 완료되었다`);
- reported judgements (`…것으로 판단했다`);
- `…라고 밝혔다` losing its copula;
- Korean counters and units (`도`, `곳`, `그루`, `위`, `㎍/㎥`);
- season and school-year times (`2025시즌`, `2026학년도`);
- the formal negative `아닙니다` and permission `-면 됩니다` missing from the translation cues;
- `그 회사는` with two candidate antecedents;
- "rose to 7.8 m" not compared with "recorded at 7.8 m".

### 7.3 Still missing after the post-hoc run

1. All 3 Korean contradictions. They need semantic matching of different wordings of the same attribute: `3위로 마쳤다` vs `최종 순위 7위`; `유의한 감소를 보였습니다` vs `유의한 차이가 없었다`; `축조가 완료` vs `공사를 마쳤다는 기록`.
2. Cross-sentence arithmetic (`이 가운데 340명 … 21%`).
3. Unsupported causal claims stated without an inference marker (`덕분에`, `…다는 사실이 증명됐습니다`).

These are the same gaps as in English (IMPLEMENTATION_PLAN 2.2–2.3, 2.7), and they are larger in Korean.

### 7.4 Language detection fix

"No Guts, Just Data." used to be detected as Spanish, from the single word "no". Short texts (under 8 words) now need two stop-word hits *and* a lead over English before a non-English language is chosen; otherwise plain-ASCII text is treated as low-confidence English. Confidence is capped at 0.6 for short texts. All English and Korean results are unchanged by this fix, and it is covered by tests.
