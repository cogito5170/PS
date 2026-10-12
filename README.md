# UPAE — Universal Proposition Analysis Engine (prototype)

UPAE turns documents into a numbered, typed, critically evaluated **proposition graph**. It extracts atomic claims, links them with explicit relations (CONTRADICTS, DIFFERS_IN_SCOPE, DUPLICATES, …) and weighs evidence by independence rather than by reputation. Its red warnings explain what is wrong and what would resolve it, and every conclusion traces back to a verbatim passage.

> Preserve evidence. Compress knowledge. Connect propositions. Challenge every claim. Explain every judgment.

**Status:** minimum viable prototype. Deterministic rule-based extraction for **English and Korean**, offline, standard library only.
On blind held-out sets it is precise but misses many problems:
- English: issue F1 0.55, 0 false alarms on 12 clean cases;
- Korean: issue F1 0.20, 0 false alarms on 6 clean cases.

See [docs/EVALUATION_REPORT.md](docs/EVALUATION_REPORT.md).

## Quick start (Python ≥ 3.10, no installation needed)

```bash
# analyse the demo corpus (JSON, Markdown, HTML, text, German + translation, Korean, a broken PDF)
python -m upae analyze examples/corpus --out out --now 2026-01-01T00:00:00+00:00

open out/report.html        # interactive: filters, graph, sources, drill-down to passages
less out/report.md          # compact numbered report (10 sections)

python -m upae search out/analysis.sqlite "population Norvik"     # FTS5 lexical search

# re-run with the previous snapshot: stable IDs plus a "changes since previous analysis" section
python -m upae analyze examples/corpus --out out2 --previous out/analysis.json

python -m unittest discover -s tests -t .                          # 93 tests, about 0.5 s
python -m upae evaluate eval/dataset/dev.json eval/dataset/heldout.json \
    eval/dataset/dev_ko.json eval/dataset/heldout_ko.json --out eval_report.md
```

Pre-generated outputs are in [`examples/output/`](examples/output/): `report.md`, `report.html`, `analysis.json` and `analysis.sqlite`.

### Input formats

| Format | Notes |
|---|---|
| `.json` / `.jsonl` | one document or `{"documents": [...]}`; fields in [eval/DATASET_FORMAT.md](eval/DATASET_FORMAT.md) §2 |
| `.txt` / `.md` | optional `---` front matter (`key`, `kind`, `title`, `author`, `published`, `url`, `doi`, `language`, `reproduces`, `translation_of`, `cites`, `corrects`, `retracted`, `basis`); `# headings` become sections; `[[page N]]` markers set page numbers |
| `.html` | article text, `<title>`, author/date/publisher meta tags, canonical URL |
| `.epub` | chapters become sections; OPF metadata |
| `.pdf` | needs the optional `pypdf` package. Unreadable files are reported as unavailable, never guessed |

Missing metadata stays missing. The engine never invents authors, dates, pages or citations.

### Optional model provider

English and Korean are extracted by deterministic rules. Other languages (German, French, Spanish and others) are detected, and their translations are checked for changed negation, modality and numbers, but they are not extracted.
`--provider anthropic[:model]` (needs `pip install anthropic` and credentials) enables extraction for those other languages. Everything a model produces is labeled `model:<name>`, `deterministic=false`, and needs human review. The tests use a fake provider, and this adapter has **not** been exercised against the live API.

### Fonts (HTML report)

Korean text uses **Noto Serif KR** (fallback **Nanum Myeongjo**), from local installs or Google Fonts. Formulas use **Latin Modern Math**: install it locally (TeX Live and MiKTeX ship it) or place `latinmodern-math.otf` next to `report.html`.

## Documentation

| Document | Content |
|---|---|
| [SYSTEM_ARCHITECTURE](docs/SYSTEM_ARCHITECTURE.md) | components, data flow, decisions with alternatives and consequences |
| [DATA_MODEL](docs/DATA_MODEL.md) | schemas, relation semantics, status definitions and transitions, invariants |
| [CONTRADICTION_SEMANTICS](docs/CONTRADICTION_SEMANTICS.md) | genuine vs apparent vs unresolved; staged detection; inference checks; paraconsistency |
| [EVIDENCE_POLICY](docs/EVIDENCE_POLICY.md) | independence, the strength formula, status rules; reputation is not an input |
| [EVALUATION_PLAN](docs/EVALUATION_PLAN.md) | datasets, metrics, protocol |
| [EVALUATION_REPORT](docs/EVALUATION_REPORT.md) | measured results (blind and post-hoc), error analysis, disclosures |
| [IMPLEMENTATION_PLAN](docs/IMPLEMENTATION_PLAN.md) | what is done, the next increments with acceptance gates, open decisions |

## Layout

```
upae/       engine (models, ingest, registry, lang, extract, graph, contradiction, checks,
            evidence, status, rank, report, diff, store, providers, pipeline, cli, evaluate)
tests/      unit and end-to-end tests (unittest)
eval/       dataset format, dev and held-out datasets, archived results
examples/   synthetic demo corpus and its generated reports
docs/       design documents
```

All example and evaluation documents are **synthetic** (example.org/example.com, `"synthetic": true`).
