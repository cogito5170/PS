# Evidence Policy

Implemented in `upae/evidence.py`, `upae/registry.py` and `upae/status.py`.

## 1. Principles

1.1 A claim is not evidence for itself. A source's own description of its basis ("a randomised trial found…") is recorded as `stated_basis`, but it does not count as support for the claim the source makes.
1.2 Evidence comes only from *other* propositions, linked through typed relations, and is weighted by explicit criteria.
1.3 Reputation (source kind: textbook, journal, blog, social) is **not an input** to strength or status. Swapping kinds leaves every assessment unchanged; `test_reputation_is_not_an_input` checks this.
1.4 Repetition is not corroboration. Evidence is aggregated per *independence group*, never per source.
1.5 Six dimensions are kept apart and reported separately:

| Dimension | Field |
|---|---|
| source reliability | access status, retraction, conflicts of interest |
| evidence quality | `basis`, `primary`, `missing_method_details` |
| logical validity | `Derivation.validity`, inference issues |
| factual accuracy | the status and Belnap value |
| independence | `independence_group`, `dependent_copies` |
| confidence in the system's assessment | `Assessment.confidence`, `Issue.confidence` |

## 2. Where evidence comes from

| Relation between target t and proposition q from another source | Stance toward t | Directness |
|---|---|---|
| q DUPLICATES t | supports | direct |
| q ENTAILS t | supports | direct |
| q REFINES t (q is more specific) | supports | indirect |
| q CONTRADICTS t, genuine | challenges | direct |
| q CONTRADICTS t, unresolved (scope stated on one side only) | challenges | indirect |
| q correlational on the same variables, t causal | supports | indirect, weighted as observational |
| a false equation (deterministic) | challenges | `LOGICAL`, strength 1.0 |

Propositions from the *same* source never support each other. Contradictions inside one source are reported as INTERNAL_INCONSISTENCY.

## 3. Independence

3.1 Sources are merged into one group by union-find over these links:
- `reproduces`;
- `translation_of`;
- `cites` (as basis);
- `duplicate_of`: exact hash, or 5-word-shingle Jaccard ≥ 0.6, only for texts of at least 20 tokens. Shorter texts rely on declared provenance, because short identical sentences from independent authors are plausible.

3.2 Within a group:
- A copy of the target's claim is a *dependent copy*: it is counted, but never as support.
- An exception is the source the target explicitly *cites*. That source is the target's basis, so its evidence counts, but only once (it is a single group).

3.3 Reworded copies inside a group are matched by an anchor heuristic: a shared non-year number plus at least two shared content words. A match produces `DERIVED_FROM` (`needs_review`) and counts as a dependent copy.
3.4 All repetition is reported as one non-red DEPENDENT_CORROBORATION issue per group.

## 4. Strength formula (transparent, not a reputation score)

```
strength = basis_weight × secondhand × directness × causal_design × COI × method_details × temporal × retracted
```

| Term | Values |
|---|---|
| basis_weight | experimental 1.0 · review 1.0 · logical 1.0 · dataset 0.9 · documentary 0.8 · observational 0.7 · survey 0.6 · secondary 0.4 · unspecified 0.4 · expert_opinion 0.35 · anecdotal 0.15 |
| secondhand | 0.8 if the evidence is reported or quoted (attributed to someone other than its author), else 1.0 |
| directness | direct 1.0 · indirect 0.5 |
| causal_design | 0.5 if the target is causal and the basis is observational or survey (correlation is not causation), else 1.0 |
| COI | 0.8 if a conflict of interest is declared or detected ("funded by …"), else 1.0 |
| method_details | 0.9 if an experimental or observational basis omits the sample size or the control condition, else 1.0 |
| temporal | 0.8 if the evidence concerns a different period, else 1.0 |
| retracted | 0.0 if the evidence source is retracted |

The basis comes from text cues, in this order of precedence: sentence > paragraph > document `basis` metadata > `unspecified`.
Every evidence item stores all its terms (`strength_terms`), so the report can show exactly why a number is what it is.

## 5. From evidence to status

Let S be the sum over independent support groups of each group's maximum strength, and C the same for challenge. The target's own group is excluded, except for sources it cites. τ = 0.8.

| Condition | Status |
|---|---|
| S ≥ τ and C < S/2 | SUPPORTED |
| C ≥ τ and S < C/2 | CONTRADICTED |
| S > 0 and C > 0 otherwise | CONFLICTING_EVIDENCE |
| 0 < S < τ or 0 < C < τ, the other side 0 | INSUFFICIENT_EVIDENCE |
| S = C = 0, with dependent copies | INSUFFICIENT_EVIDENCE |
| S = C = 0, no copies | UNVERIFIED |

These rules have practical consequences, all covered by tests:

- One primary dataset or experiment can make a claim SUPPORTED (0.9–1.0).
- One unspecified-basis corroboration (0.4) cannot. It takes two independent ones.
- A blog claim backed by two independent primary sources is SUPPORTED ("correct claim from a low-reputation source").
- A textbook figure contradicted by two independent datasets is CONTRADICTED, and the contradiction issue becomes PROBABLE_ERROR on the textbook side ("incorrect claim from a high-reputation source").

## 6. Confidence

Assessment confidence is a heuristic:
- SUPPORTED: `0.45 + 0.25·min(S,2) − 0.2·min(C,1)`, capped at 0.95;
- CONTRADICTED: the symmetric formula;
- CONFLICTING: 0.6;
- INSUFFICIENT or UNVERIFIED: 0.6–0.7;
- OUT_OF_SCOPE: 0.8;
- RETRACTED: 0.95;
- HUMAN_REVIEW_REQUIRED: none.

These values are **not calibrated probabilities**. The measured calibration is in EVALUATION_REPORT.md: on the held-out set, statuses predicted at 0.6–0.8 confidence were right only 9 % of the time in the blind run. Fixing this is a top item in IMPLEMENTATION_PLAN.

## 7. What resolves an issue

Every issue names the information that would resolve it, for example:
- the scope dimension that is missing;
- the primary data or measurement protocol;
- a causally identified design;
- the original recording or transcript;
- a fluent re-translation;
- a non-retracted source.

## 8. Limitations

8.1 Basis detection relies on keyword cues. "Archival letters show…" is not recognized as documentary evidence unless the document declares `basis`.
8.2 Conflicts of interest are detected only from explicit metadata or "funded/sponsored by" phrases.
8.3 Reproducibility is not assessed beyond the independence of replications.
