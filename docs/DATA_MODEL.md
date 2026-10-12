# Data Model (schema 1.1)

Definitions live in `upae/models.py`. Every object is a dataclass with `to_dict` and `from_dict`. Objects reference each other only by ID.
ID prefixes: `S` source, `T` passage (a text span), `P` proposition, `E` evidence, `R` relation, `A` assessment, `I` issue, `D` derivation. IDs take the form `X-000001`.

## 1. Source (`S-…`)

| Field | Meaning |
|---|---|
| `key` | caller-supplied identity (file stem or document key); used for stable IDs |
| `kind` | blog, news, social, paper, textbook, book, report, dataset, web, other |
| `title, author, publisher, published, url, canonical_url, doi, isbn, license, version` | only when present in the input; **never inferred** (`None` otherwise; reports print "not stated") |
| `language` | declared, otherwise detected; detection result kept in `metadata.detected_language` |
| `retrieved_at` | analysis timestamp (or supplied value) |
| `content_hash` | SHA-256 of archived text (document version identity) |
| `access_status, access_note` | `accessible`, `unavailable`, `restricted`, `unsupported_format` + reason |
| `retracted` | input flag; propositions become `RETRACTED` |
| `basis` | evidence type the document reports for itself (experimental, dataset, …) |
| `reproduces, translation_of, cites, duplicate_of` | provenance links (source IDs) |
| `independence_group` | `G-…`, union of provenance links (EVIDENCE_POLICY §3) |
| `synthetic` | marks invented test material |

## 2. Passage (`T-…`): the evidence archive

A passage is a verbatim paragraph with `char_start`/`char_end` offsets into the archived source text, plus `page`, `section`, `language` and `paragraph_index`.
Invariant: `archive[source][char_start:char_end] == text`.

## 3. Proposition (`P-…`)

Abridged example (field values are illustrative):

```json
{
 "id": "P-000004", "fingerprint": "9c1f…", "schema_version": "1.1", "version": 1,
 "text": "has_value(population of norvik) = 1.2 million | t=2020",
 "subject": "population of norvik", "predicate": "has_value", "object": null,
 "surface": {"subject": "Norvik", "predicate": "has_value", "object": null},
 "claim_type": "statistical", "modality": "asserted", "polarity": "positive", "direction": 0,
 "quantity": {"value": 1200000, "unit": null, "raw": "1.2 million", "norm_value": 1200000,
              "kind": "level", "approximate": false, "dimension": "dimensionless"},
 "quantifier": null,
 "scope": {"time": "2020", "time_norm": [2020, 2020], "location": null, "population": null,
           "conditions": [], "units": null, "definitions": {}},
 "attribution": {"speaker": null, "kind": "author", "quote": null, "origin_source_id": null},
 "source_refs": ["S-000004"], "passage_id": "T-000004",
 "quote": "Norvik had a population of 1.2 million in 2020.", "quote_span": [0, 48],
 "language": "en", "original_text": null, "stated_basis": null,
 "evidence_refs": ["E-000023", "E-000025"], "relation_refs": ["R-000018"], "issue_refs": ["I-000002"],
 "components": [], "parent_id": null, "supersedes": null, "superseded_by": null,
 "extraction": {"method": "rule-en@1/rule:has-value@1", "confidence": 0.85,
                "review_required": false, "notes": [], "deterministic": true},
 "created_at": "2026-10-12T00:00:00+00:00"
}
```

Changes from the initial proposal in the specification, with the reason for each:

1. `assessment` is a **separate object**, keyed by proposition. This keeps the claim, its evidence and the current judgment apart, as P6 requires.
2. `surface` keeps the original wording; `subject` and `object` are normalized. Normalization never erases the original (C). `language` is the language the proposition was extracted in (`en`, `ko`, or the passage language for model extraction). In Korean, an omitted subject is written `(화자)` (the speaker), since Korean routinely drops subjects.
3. `polarity`, `direction`, `quantifier` and `modality` are separate fields. This separation lets "may reduce", "does not reduce", "reduces" and "increases" be compared deterministically.
4. `quantity` holds both the raw and the normalized value, the dimension and the kind (`level`, `change`, `change_pp`, `from_to`, `year`).
5. `scope.time_norm` gives a year range for comparison, and `scope.definitions` maps a term to the definition proposition the source uses.
6. `attribution` separates who asserts the claim (author, reported or quoted) from the document's author.
7. A **compound** is a parent proposition (`claim_type=compound`, `components=[…]`). It is not compared itself; its status is that of its weakest component.
8. **Mathematical** propositions (`equals(2 + 2, 5)`) are evaluated exactly. **Predictions**, **hypotheses**, **definitions**, **opinions** and **normative** statements are distinct claim types. Opinions and normative statements are `OUT_OF_SCOPE` for truth assessment, so an author's opinion is never promoted to fact.
9. Statistical findings use `quantity` plus the population and time scope. Legal interpretations and other domain assertions use `claim_type` plus `attribution`. A domain-specific type needs only a new `ClaimType` member and comparison rules.
10. Versioning: `version`, `supersedes`, `superseded_by`. A declared correction creates a `CORRECTS` relation and supersedes the old claim. Nothing is deleted.

### Claim types

`empirical, statistical, causal, correlational, definition, opinion, normative, prediction, hypothesis, observation, mathematical, quotation, compound`

### Modalities

`asserted, possible (may/might/suggests), probable (likely), necessary, predicted (will), reported (attributed), questioned`

## 4. Evidence (`E-…`)

An evidence item is a stance (`supports` or `challenges`) from proposition `via_proposition`, located in source `source_id` and passage `passage_id`, toward the target proposition `proposition_id`.
Each item records explicit criteria: `basis`, `primary`, `directness`, `independence_group`, `temporal_relevance`, `conflicts_of_interest`, `missing_method_details`, the multiplicative `strength_terms`, and the resulting `strength`. The formula is in EVIDENCE_POLICY §4.

## 5. Relation (`R-…`)

The fields are `type`, `source → target`, `directed`, `rationale`, `evidence_refs` (passages), `confidence`, `review_status` (`auto_deterministic | auto_model | asserted_by_source | needs_review | confirmed | rejected`), `method`, `dimensions` and `assumptions`.

| Type | Direction | Semantics (holds when…) | Produced by |
|---|---|---|---|
| SUPPORTS | a→b | a is evidence for b without entailing it | reserved: model or human review (evidence items carry machine support) |
| CONTRADICTS | ↔ | a and b are logically incompatible under the same (or assumed-same) scope; `review_status=needs_review` if a scope dimension is unstated on one side | comparison |
| ENTAILS | a→b | a deductively implies b (quantified effect ⇒ unquantified effect, same scope) | comparison |
| REQUIRES | a→b | a holds only if b holds | reserved (the predicate `requires` is extracted inside propositions) |
| CAUSES | a→b | the source asserts that the state in a causes the state in b ("because") | extraction; always `asserted_by_source`, never verified |
| CORRELATES_WITH | ↔ | the source asserts that a and b co-vary | reserved; correlation *claims* are propositions with predicate `correlates_with` |
| QUALIFIES | a→b | a limits or conditions b ("but…", "however…") | extraction |
| REFINES | a→b | a states b with more scope restrictions; supports b only indirectly | comparison |
| CORRECTS | a→b | a is a declared correction of b; b gets `superseded_by=a` | comparison + `corrects` metadata |
| DUPLICATES | ↔ | same entities, predicate, polarity, value and scope | comparison |
| DERIVED_FROM | a→b | a is presented as a conclusion from b ("therefore"), or a is a reworded copy of b | extraction / reworded-copy check |
| DIFFERS_IN_SCOPE | ↔ | a and b look incompatible but differ in time, place, population, conditions, units, definition, modality or quantifier, so they are **not** a contradiction | comparison |

## 6. Assessment (`A-…`, one per proposition)

The fields are `status`, `confidence` (heuristic), `rationale`, `belnap` (`N`/`T`/`F`/`B`), `support_strength`, `challenge_strength`, `support_groups`, `challenge_groups`, `dependent_copies`, `criteria`, `review_required`, `review_triggers` and `history` (a list of transitions).

| Status | Exact meaning |
|---|---|
| UNVERIFIED | nothing in the corpus beyond the assertion itself |
| SUPPORTED | independent support S ≥ τ (0.8) and challenge C < S/2 |
| CONTRADICTED | C ≥ τ and S < C/2, or a deterministic proof of error (a false equation) |
| CONFLICTING_EVIDENCE | S > 0 and C > 0 with neither dominating |
| INSUFFICIENT_EVIDENCE | some evidence below τ, or only dependent copies |
| OUT_OF_SCOPE | opinion or normative statement: recorded as attributed, not assessed as fact |
| RETRACTED | the source is retracted |
| HUMAN_REVIEW_REQUIRED | a review trigger fired: model extraction, mistranslation, arithmetic inconsistency in the sentence, reliance on a retracted source, or low extraction confidence on a proposition that other findings depend on |

Precedence when computing: RETRACTED > (compound) > OUT_OF_SCOPE > HUMAN_REVIEW_REQUIRED > confirmed error > the evidence rules.

### Allowed transitions (`status.py`)

| From → To | Actor |
|---|---|
| UNVERIFIED → any | system |
| SUPPORTED / CONTRADICTED / CONFLICTING / INSUFFICIENT → each other, UNVERIFIED, RETRACTED, HUMAN_REVIEW_REQUIRED | system |
| … → OUT_OF_SCOPE | human (the claim type is fixed per proposition version) |
| OUT_OF_SCOPE → RETRACTED / HUMAN_REVIEW_REQUIRED | system; → others: human |
| RETRACTED → any | **human only** |
| HUMAN_REVIEW_REQUIRED → any | system only if no review trigger remains; otherwise human |

A transition the system is not allowed to make is not applied. The status stays as it was, and the blocked transition is recorded as a review trigger. A test covers this: a previously retracted claim stays RETRACTED after the flag is removed until a human acts.

## 7. Issue (`I-…`)

The fields are `category`, `finding_class`, `severity`, `confidence`, `affected`, `conflicting`, `reason`, `evidence`, `resolution`, `dimensions`, `assumptions`, `detector`, `deterministic`, `red` and `details`.

**Finding classes:** CONFIRMED_ERROR (deterministic proof), PROBABLE_ERROR, UNRESOLVED_CONTRADICTION, SUSPICIOUS_CLAIM, MISSING_EVIDENCE, LIMITATION.

**Red rule:** an issue is red if (class ∈ {CONFIRMED_ERROR, PROBABLE_ERROR, UNRESOLVED_CONTRADICTION} or severity ≥ HIGH) and confidence ≥ 0.5.
`red_for(pid)`: once evidence has identified the probable-error side of a contradiction, only that side is drawn red.

Each red issue maps onto the seven required fields as follows: (1) `affected`, (2) `category`, (3) `conflicting` or `evidence`, (4) `reason`, (5) `severity` and `confidence`, (6) `evidence` (passage and evidence IDs; the reports print the quoted text), (7) `resolution`.

## 8. Derivation (`D-…`)

A derivation records `conclusion`, `premises`, `marker` ("therefore") and `validity` (`valid | invalid | unknown`), plus the names of the `checks` that ran. "Valid" is claimed only when the conclusion duplicates or is entailed by a premise. Every other case is `unknown` or `invalid`.

## 9. Omission

An omission records `proposition_id`, `decision` (`merged | hidden_low_priority | summarized | retained_counterevidence`), `reason`, `into` and `score`. Every proposition that is not in the core report has one.

## 10. Validation rules and invariants

These are enforced by `KnowledgeGraph.validate()`, which every run calls; a non-empty result is reported as an integrity error.

1. All references resolve: source, passage, evidence, relation, issue, component, supersession and derivation premises.
2. The quote is verbatim inside its passage, and the passage matches its archive span.
3. Every proposition has at least one source and exactly one assessment. Its `schema_version` equals the current version.
4. No self-evidence and no self-relations. Every relation has a rationale.
5. Every issue has an affected object, a reason and a resolution.
