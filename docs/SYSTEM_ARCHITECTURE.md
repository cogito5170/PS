# System Architecture

Status: minimum viable prototype (`upae-0.1.0`). Statements are numbered; `→` marks a consequence.
Measured numbers are in [EVALUATION_REPORT.md](EVALUATION_REPORT.md); nothing here is an estimate unless it says so.

## 1. Starting point (inspection, 2026-10-12)

1.1 Repository: one commit with a 4-byte `README.md`. No code, tests, CI or dependencies to preserve.
1.2 Environment: Python 3.13, SQLite 3.45 with FTS5, `psql` client but no PostgreSQL server, no `pytest`,
outbound network restricted (font CDNs and package mirrors unreachable).
1.3 → The prototype is pure-stdlib Python, tested with `unittest`, persisted to SQLite. It runs offline.

## 2. Pipeline

```
files ─► A Ingestion ─► B Source registry ─► C Language ID ─► D Extraction ─► E Graph
                         (archive, passages,                  (rules; model     │
                          duplicates, groups)                  adapter optional)│
        ┌───────────────────────────────────────────────────────────────────────┘
        ▼
  G Comparison / contradiction ─► F Evidence items ─► deterministic checks ─► assessment
        ─► H Ranking & compression ─► I Reports (MD, HTML) + JSON snapshot + SQLite/FTS5
        ─► diff against previous snapshot
```

| # | Component | Module | Deterministic? |
|---|---|---|---|
| A | Ingestion connectors (JSON/JSONL, TXT/MD + front matter, HTML, EPUB, PDF via optional `pypdf`) | `ingest.py` | yes |
| B | Source registry, archive, passages, duplicates, independence groups | `registry.py` | yes |
| C | Language identification, multilingual cue lexicons, number formats | `lang.py` | yes |
| D | Proposition extraction (English rules); model adapter for other languages | `extract.py`, `providers.py` | rules yes / model no |
| E | Typed graph, stable IDs, referential integrity, supersession | `graph.py`, `models.py` | yes |
| F | Evidence items, strength formula, status rules | `evidence.py`, `status.py` | yes |
| G | Staged comparison (retrieve → align → incompatibility → classify) | `contradiction.py` | yes |
| — | Checks: arithmetic, quotations, translations, inferences, causal basis, dependence, retraction, ambiguity | `checks.py`, `pipeline.py` | yes |
| H | Ranking, compression, omission records | `rank.py` | yes |
| I | Markdown and interactive HTML reports, change report | `report.py`, `diff.py` | yes |
| — | Persistence and lexical search | `store.py` | yes |
| — | Orchestration, CLI, evaluation harness | `pipeline.py`, `cli.py`, `evaluate.py` | yes |

2.1 Acquisition is separate from analysis. Connectors return *document records* containing only metadata that is present in the file. The analysis code never fetches anything.
2.2 Every stage writes into one `KnowledgeGraph`. Each object type has its own table: sources, passages, propositions, evidence, relations, assessments, issues, derivations and omissions. The original text of every source is stored in `archive`.
2.3 Model output (`providers.py`) is labeled `deterministic=False` and `method=model:<name>`, and it triggers human review. When no provider is configured, the engine runs completely and records non-English passages as a limitation.

## 3. Key design decisions

Each decision lists its rationale (R), the alternatives considered (Alt), its limitations (Lim) and the measurable consequence (M).

**D1. Deterministic rules first, model adapter optional.**
R: the specification requires usefulness without an LLM, and it requires that model judgments not be treated as verified. Rules are inspectable and reproducible.
Alt: LLM extraction for everything; NLI models for contradiction.
Lim: the English-only rule extractor misses unusual phrasing. On the blind held-out set it reached proposition recall 0.61 and issue recall 0.44.
M: zero model calls, under 15 ms per case, byte-identical output across runs (tested).

**D2. SQLite + FTS5 now, PostgreSQL later.**
R: no server is available, and an embedded database is locally testable. The schema (`store.py`) has one table per object plus a JSON payload, which maps 1:1 to PostgreSQL with `tsvector` and `jsonb`.
Alt: PostgreSQL immediately; a graph database.
Lim: single writer; no concurrent ingestion.
M: the 18-source demo corpus is 276 KB on disk; `upae search` runs a BM25 query.

**D3. No graph database.**
R: every graph query the prototype makes is a 1–2 hop neighbourhood lookup over indexed `relations(source)` and `relations(target)` columns. The specification asks for a graph database only if measured queries justify one, and none does yet.
M (to measure at scale): p95 latency of 3-hop traversals on more than 10⁶ relations. Revisit this decision if it exceeds 100 ms.

**D4. In-memory analysis per corpus.**
R: the hard parts are comparison and evaluation, not storage. Pairwise candidate retrieval uses an inverted index over subject tokens, capped at 40 candidates per proposition.
Lim: the whole corpus must fit in memory. The cost grows as O(n·40) comparisons.
M: 0.8–0.9 ms per proposition measured on the evaluation sets.

**D5. Stable identifiers from fingerprints.**
R: diffs between runs and human review both need persistent IDs. IDs look like `P-000123`, and on a re-run they are re-bound through the previous snapshot's `id_map` (fingerprint → id).
Lim: if the wording of a source sentence changes, the fingerprint and therefore the ID change too. The diff reports this as one proposition removed and one added.
M: a re-run on unchanged input keeps every ID and reports no changes (tested).

**D6. Typed relations plus `DIFFERS_IN_SCOPE`.**
R: an apparent contradiction is a relation, not an issue. Making it explicit is how scope differences are stopped from turning red. See CONTRADICTION_SEMANTICS.md.
M: 0 false alarms on the 29 `no_red` cases across the two datasets.

**D7. Independence groups computed at source level.**
R: copies must never count as corroboration. Sources are merged into one group by union-find over `reproduces`, `translation_of`, `cites` and near-duplicate content (5-word shingles with Jaccard ≥ 0.6, for texts of at least 20 tokens).
Lim: undeclared, reworded copies are caught only by the anchor heuristic: the two sentences must share a number and content words.
M: pairwise independence accuracy was 1.00 on both datasets (12 and 27 pairs).

**D8. Ranking kept separate from truth.**
R: a ranking score decides what is shown in the core report; it is never evidence. Red issues and counter-evidence are always retained.
M: compression ratio of 0.60 on dev and 0.83 on held-out, measured as core-statement words over source words. Short test documents limit how much compression is possible.

## 4. Data flow guarantees (checked by `KnowledgeGraph.validate()` and tests)

4.1 Every proposition has a source and a passage. Its quote appears verbatim in the passage. The passage equals the corresponding span of the archived source text.
4.2 Every relation has a rationale. Every issue has affected objects, a reason and a resolution.
4.3 No proposition is evidence for itself. Evidence from a retracted source has strength 0.
4.4 Nothing is deleted when a conflict is found. Superseded propositions keep their records and get `superseded_by`. Omissions are recorded with a reason.

## 5. Scaling path (not implemented; decisions to measure first)

5.1 PostgreSQL: reuse the `store.py` DDL, use `jsonb` payloads and GIN `tsvector` indexes, and add an `analysis_run` table for history.
5.2 Semantic retrieval: add an embedding adapter as a second candidate source next to the token index. Measure the gain in recall of contradiction pairs before adopting it.
5.3 Model-assisted extraction and paraphrase alignment through `providers.py`. Gate it on held-out precision; the red-warning precision must not drop below its current value.
5.4 Remote connectors (`ingest.REMOTE_CONNECTORS`). Each must enforce robots and terms of service, rate limits and licence metadata before it is registered.
5.5 Web UI: the self-contained HTML report already provides filtering, graph exploration, source inspection and drill-down to passages. A server is needed only for multi-user review workflows.
