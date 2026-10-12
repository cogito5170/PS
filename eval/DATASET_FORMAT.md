# Labeled Evaluation Dataset Format

A dataset file is a JSON object `{"dataset": "<name>", "version": "1", "cases": [ ... ]}`.
Every case is a self-contained mini-corpus plus gold labels. Cases are evaluated
independently: the engine analyses only the documents of one case at a time.

All sources in the datasets are **synthetic**. Titles, authors, publishers and URLs are
invented, use the reserved `example.org` / `example.com` domains, and every document
carries `"synthetic": true`. No real publication is cited.

## 1. Case

```json
{
  "id": "D01",
  "category": "genuine_contradiction",
  "description": "One sentence explaining what the case tests.",
  "documents": [ <Document>, ... ],
  "expected": <Expected>
}
```

`category` is one of:

| category | meaning |
|---|---|
| `genuine_contradiction` | two propositions incompatible under the same scope |
| `scope_difference` | apparent contradiction explained by different time / population / location / conditions / units / definitions |
| `numerical_error` | an arithmetic or computed figure inside a text is wrong |
| `misleading_quotation` | a quotation that changes the meaning of the original statement (dropped negation, hedge, qualifier, altered number) |
| `unsupported_causal` | a causal conclusion drawn from correlational/observational evidence, or other invalid inference (over-generalisation, hedge dropped) |
| `dependent_sources` | several documents that copy/syndicate one origin; repetition is not corroboration |
| `translation_error` | a translation that changes negation, numbers or modality |
| `low_reputation_correct` | a claim from a low-reputation source (blog, social post) that is supported by independent primary evidence |
| `high_reputation_incorrect` | a claim from a high-reputation source (textbook, journal, agency) that is contradicted by independent primary evidence or relies on a retracted source |
| `ambiguous` | an underspecified proposition (unresolved pronoun, vague quantifier, number without unit) |
| `no_issue` | consistent, unproblematic documents; any red warning is a false alarm |
| `timeline_inconsistency` | posts or documents by the same author whose relative time expressions ("tomorrow", "two days since I arrived", "for a month", "내일부터", "온 지 이틀", "한 달 동안") imply incompatible dates for the same episode, given each document's `published` date. Expected issue: `TEMPORAL_DISAGREEMENT` |
| `timeline_consistent` | the same kind of posts whose implied dates agree; any red warning is a false alarm |

## 2. Document

```json
{
  "key": "a",
  "kind": "news",
  "title": "Synthetic title",
  "author": "Jane Example",
  "publisher": "Example Daily",
  "published": "2023-05-02",
  "url": "https://news.example.org/a",
  "language": "en",
  "text": "Plain text. Paragraphs are separated by a blank line.",
  "synthetic": true
}
```

Required: `key` (unique within the case), `kind`, `text`, `synthetic`.
Optional fields (omit rather than invent):

* `kind`: `blog | news | social | paper | textbook | book | report | dataset | web | other`
* `author`, `publisher`, `published` (ISO date), `url`, `doi`, `isbn`, `language` (ISO 639-1)
* `pages`: `[{"page": 12, "section": "3.1 Results", "text": "..."}]` instead of `text`
* `reproduces`: key of a document in the same case that this document copies / syndicates
* `translation_of`: key of the document this one translates (sentence order preserved)
* `cites`: list of keys this document relies on as its source
* `retracted`: `true` if the document has been retracted
* `basis`: what the document itself reports as its evidence:
  `experimental | observational | survey | dataset | review | secondary | expert_opinion | anecdotal`

Social-media posts (`kind: "social"`) may use SNS style: one short line per sentence without final
punctuation, noun-final sentences ("치앙마이에 온 지 이틀"), bullet-style endings (함/됨/임), emoji and
hashtags. Timeline cases must set `published` (ISO date) on every post.

Text conventions: ordinary declarative English prose (news, blog, textbook, abstract style).
Non-English text is used for translation cases: the original (`language` set, e.g. `de`) and
an English translation with `translation_of` pointing to the original.
Quotations use straight double quotes: `Dr. Example said "..."`.

## 3. Expected labels

All matching is by **substring of the source sentence** that a proposition was extracted
from (case-insensitive, whitespace-normalised). Choose substrings that are unique within the
case.

```json
{
  "propositions": [
    {"sentence": "reduced costs by 20%", "subject": "policy x", "predicate": "decreases",
     "object": "cost", "polarity": "positive", "claim_type": "causal"}
  ],
  "issues": [
    {"category": "NUMERICAL_INCONSISTENCY", "affected": ["is 100 degrees", "is 90 degrees"], "red": true}
  ],
  "forbidden_issue_categories": ["MISLEADING_QUOTATION"],
  "no_red": false,
  "relations": [
    {"type": "DIFFERS_IN_SCOPE", "between": ["under conditions A", "under conditions B"]}
  ],
  "statuses": [
    {"sentence": "reduced costs by 20%", "status": "SUPPORTED"}
  ],
  "independent_groups": [["a", "b"], ["c"]]
}
```

Every key is optional. Semantics:

* `propositions` — gold atomic propositions. `subject`, `predicate`, `object` are free text;
  scoring uses token overlap, so exact wording is not required. `claim_type` one of
  `empirical, statistical, causal, correlational, definition, opinion, normative, prediction,
  hypothesis, observation, mathematical, quotation`.
* `issues` — warnings that must be raised. `affected` lists sentence substrings; an issue
  matches if it touches at least one of them. `red` states whether the warning should be red.
  Categories:
  `NUMERICAL_INCONSISTENCY, CATEGORICAL_CONFLICT, TEMPORAL_DISAGREEMENT, DEFINITION_CONFLICT,
  INTERNAL_INCONSISTENCY, ARITHMETIC_ERROR, INVALID_INFERENCE, UNSUPPORTED_CAUSAL_CLAIM,
  MISLEADING_QUOTATION, TRANSLATION_DISCREPANCY, MISSING_CONDITION, DEPENDENT_CORROBORATION,
  RETRACTED_SOURCE_DEPENDENCY, AMBIGUOUS_PROPOSITION`.
  Scoring also reports a lenient "family" score in which `NUMERICAL_INCONSISTENCY`,
  `CATEGORICAL_CONFLICT`, `TEMPORAL_DISAGREEMENT`, `INTERNAL_INCONSISTENCY` and
  `MISSING_CONDITION` are interchangeable, as are `INVALID_INFERENCE` and
  `UNSUPPORTED_CAUSAL_CLAIM`.
* `forbidden_issue_categories` — categories that must not be raised in this case.
* `no_red` — `true` means any red warning in this case is a false alarm.
* `relations` — relations that must exist between propositions from the two sentences.
  Types: `SUPPORTS, CONTRADICTS, ENTAILS, REQUIRES, CAUSES, CORRELATES_WITH, QUALIFIES,
  REFINES, CORRECTS, DUPLICATES, DERIVED_FROM, DIFFERS_IN_SCOPE`.
* `statuses` — expected assessment status of the proposition from that sentence:
  `UNVERIFIED` (no evidence beyond the assertion itself), `SUPPORTED` (independent supporting
  evidence, no comparable challenge), `CONTRADICTED` (independent challenging evidence, no
  comparable support), `CONFLICTING_EVIDENCE` (both), `INSUFFICIENT_EVIDENCE` (only dependent
  copies or weak evidence), `OUT_OF_SCOPE` (opinion / normative, not empirically assessable),
  `RETRACTED` (from a retracted document), `HUMAN_REVIEW_REQUIRED`.
* `independent_groups` — gold partition of document keys into independence groups
  (documents in one group share an origin and do not corroborate each other).
