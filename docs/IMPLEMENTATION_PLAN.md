# Implementation Plan

## 1. Done (prototype `upae-0.1.0`)

Each item notes how it is verified; full numbers are in EVALUATION_REPORT.md.

| # | Workflow step (from the specification) | Result | Verification |
|---|---|---|---|
| 1 | Inspect the repository and environment | empty repository; Python 3.13 and SQLite FTS5; no network | SYSTEM_ARCHITECTURE §1 |
| 2 | Infrastructure and constraints | stdlib only; `unittest`; optional `pypdf` and `anthropic` | — |
| 3 | Minimum viable architecture | 15 modules, one process, one embedded database | SYSTEM_ARCHITECTURE |
| 4 | Schemas, invariants, contradiction semantics | DATA_MODEL, CONTRADICTION_SEMANTICS, EVIDENCE_POLICY | `KnowledgeGraph.validate()` |
| 5 | Small end-to-end prototype | `python -m upae analyze` writes MD, HTML, JSON and SQLite | demo corpus |
| 6 | Deterministic tests and labeled cases | 65 unit tests; 34 dev and 24 held-out cases | `unittest`, `upae evaluate` |
| 7 | Traceability and report correctness | coverage 1.00; 0 integrity violations; 10 report sections; all 7 red-warning fields | tests |
| 8 | Quality and resource measurement | blind held-out F1 0.55, 0 false alarms; under 15 ms per case | EVALUATION_REPORT |
| 9 | Limitations and open decisions | §2 and §3 below | — |

## 2. Next increments, in order of expected value per effort

Each increment has an acceptance gate measured on a held-out set that has *not* been used for development: the false-alarm case rate must not increase, and red-warning precision must not fall.

| # | Increment | Why (measured problem) | Gate |
|---|---|---|---|
| 2.1 | **Fresh human-written blind test set** (≥ 100 cases, two annotators, real licensed text where possible) | the current held-out set is used up (post-hoc), and both sets were model-written | Cohen's κ reported per category |
| 2.2 | **Model-assisted extraction behind `providers.py`**, with rules as the fallback and every model proposition marked `review_required` | proposition recall 0.61 (blind) is the bottleneck for everything downstream | proposition recall ≥ 0.85 with precision proxy ≥ 0.8 on the test set; cost per 1,000 words reported |
| 2.3 | **Paraphrase alignment**: embedding retrieval plus model or NLI equivalence judgments, recorded as `auto_model` relations | contradiction recall 0.25 (blind); missed conflicts had different subject wording | contradiction recall +0.2 with false alarms unchanged |
| 2.4 | **Status confidence calibration**: fit the confidence formula on labeled data (isotonic regression or binned rates) | status ECE 0.51 (blind) | ECE < 0.15 |
| 2.5 | Temporal "when / after / before" clauses parsed as time, not as conditions | false-positive MISSING_CONDITION on H20 | no MISSING_CONDITION on temporal clauses in the tests |
| 2.6 | Decide the red-warning policy for unsupported causal claims and invalid inferences (red vs amber) with reviewers | the two dataset authors disagreed | a written policy, plus agreement measured on 2.1 |
| 2.7 | Cross-sentence arithmetic (n × each = total, shares summing to 100 %) | H14 missed | new arithmetic cases |
| 2.8 | PostgreSQL backend (same DDL, `jsonb` + `tsvector`), analysis-run history, reviewer actions (confirm or reject relations; human status transitions) | needed for multi-user review | migration test; round-trip equality |
| 2.9 | Remote connectors (RSS/news, arXiv/Crossref metadata, Mastodon/Bluesky APIs) with robots, terms and rate-limit enforcement and licence capture | the ingestion layer is local-only | per-connector compliance checklist |
| 2.10 | Native extraction for additional languages (start with de/fr/es, whose cue lexicons already exist; ko/ja/zh need segmentation) | non-English passages are currently a recorded limitation | per-language extraction recall |

## 3. Unresolved design decisions

1. **τ = 0.8 and the basis weights** are policy choices, not learned values. They need agreement with domain experts and should be configurable per domain; medicine and history weight evidence types differently.
2. **Implicit publication time** for time-varying statistics. This prevents false contradictions between reports from different years, but can hide genuine ones. No current test case isolates it, so it needs an ablation on real data.
3. **Granularity of compound claims.** The current rules split coordinated verbs, "because" and "but". Splitting more finely increases comparisons and the chance of noise.
4. **Severity of empirical effect-size disagreements.** The 25 % tolerance is a heuristic. Meta-analytic heterogeneity is not modelled.
5. **Opinions.** They are recorded and attributed, but they are not compared. A future "stance map" could show disagreement between opinions without calling it contradiction.
6. **Retention.** The archive keeps the full text of every document. Copyrighted material needs a retention policy: store passages plus hashes only, with recovery through the source URL.
