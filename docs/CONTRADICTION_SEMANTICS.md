# Contradiction Semantics

Implemented in `upae/contradiction.py`; issue creation is in `pipeline.py`.

## 1. Representation

1.1 Every comparable proposition reduces to a tuple
`⟨subject, predicate-family, object, polarity, direction, quantity, modality, quantifier, scope⟩`,
where `scope = ⟨time, location, population, conditions, units/measure, definitions⟩`.
1.2 Predicate families:
- `effect`: causes, affects, increases, decreases;
- `change`: increased or decreased, with no object;
- `value`: has a level;
- `assoc`: correlates with;
- `def`: is defined as;
- `event:<verb>_in`: a date;
- `attr:<verb>`: copula and other verbs;
- `math`: equations.

1.3 Two propositions can contradict only if they belong to the same family and their entities align: subject token Jaccard ≥ 0.5, rising to 0.6 for `value`. The `effect`, `assoc` and `attr` families also need object Jaccard ≥ 0.5.

## 2. The eight relationships between two aligned claims

| # | Situation | Definition | Output |
|---|---|---|---|
| 1 | **Logical contradiction** | The content tuples are incompatible (opposite polarity, opposite direction, values outside tolerance, different years for one event, different values of a single-valued attribute) **and** every scope dimension is `same` or `both_unspecified`. | `CONTRADICTS` + red issue (UNRESOLVED_CONTRADICTION, upgraded to PROBABLE_ERROR on one side if evidence separates them) |
| 2 | **Empirical disagreement** | A logical contradiction between two *measurements* or *effect estimates*, such as 20 % vs 5 %. | Same as #1. Effect sizes with the same sign get a 25 % relative tolerance and MEDIUM severity. |
| 3 | **Different scopes or conditions** | Incompatible content, but at least one of time, location, population or conditions is `different`. | `DIFFERS_IN_SCOPE` with `dimensions`; no issue |
| 4 | **Different time periods** | A special case of #3 on `time`. Time-varying statistics with no explicit time take their source's publication year, and that assumption is recorded. | `DIFFERS_IN_SCOPE[time]` |
| 5 | **Different definitions** | The two sources define a shared term differently (definition Jaccard < 0.6). | `DIFFERS_IN_SCOPE[definition]`, plus a non-red DEFINITION_CONFLICT when two definitions of a term disagree |
| 6 | **Insufficient evidence** | No incompatibility, or incompatibility with no evidence for either side. | The status rules (EVIDENCE_POLICY); never an automatic verdict |
| 7 | **Invalid inference** | A conclusion marked by "therefore", "this shows" or similar, which is not licensed by its premises. | INVALID_INFERENCE or UNSUPPORTED_CAUSAL_CLAIM (§5) |
| 8 | **Missing information** | Incompatible content where a scope dimension is stated on only one side (`one_unspecified`). | `CONTRADICTS` with `review_status=needs_review`, plus a red MISSING_CONDITION issue (UNRESOLVED_CONTRADICTION, MEDIUM) that names the assumption needed |

Also non-contradictory:
- one side hedged, predicted or questioned ("may reduce" vs "does not reduce");
- quantifiers differ ("some" vs "all");
- the units measure different things (minutes vs kilometres).

All three produce `DIFFERS_IN_SCOPE` with dimension `modality`, `quantifier` or `units`.

## 3. Worked example from the specification

```
P1: decreases(policy x, cost) = −20% | cond=experimental conditions A
P2: increases(policy x, cost) = +5%  | cond=experimental conditions B
```

- Alignment: subject and object are the same; the direction is opposite, so the content is incompatible. Conditions are `different`, so the result is **#3**: `DIFFERS_IN_SCOPE[conditions]` and no red flag.
- If P2's condition were "A": all scope dimensions are the same or both unspecified, so the result is **#1/#2**. The issue lists its assumptions: *"Assumed both refer to the same time period (neither proposition states it)… same location… same population."*
- If P2 had no condition: the result is **#8**. *"Would require that both hold under the same conditions."*

All three variants are unit tests (`tests/test_analysis.py::ContradictionSemantics`).

## 4. Staged detection

1. **Retrieve** candidates through an inverted index on normalized subject tokens (light stemming, synonyms), keeping the top 40 per proposition.
2. **Align** the entities and predicate family, then each scope dimension. The time comparison uses year ranges, and quantities are compared after unit normalization (°F→°C, mi→m, million→×10⁶).
3. **Test incompatibility** with family-specific rules (`incompatibility()`). A value conflict uses a 1 % relative tolerance, or 10 % when either value is approximate ("about").
4. **Name the dimension** of disagreement: `polarity`, `direction`, `magnitude`, `value`, `event_time` or `categorical_value`.
5. **Retrieve evidence**: each side becomes a challenging evidence item for the other. Strength comes from basis, directness and independence (EVIDENCE_POLICY).
6. **Classify** the pair as GENUINE, APPARENT or UNRESOLVED, with `rationale` and `assumptions`.
7. **Report the issue**:
   - one issue per pair of *equivalence classes*, so a claim that contradicts three copies of the same figure produces one issue;
   - the category is NUMERICAL, CATEGORICAL, TEMPORAL, INTERNAL (same source) or MISSING_CONDITION;
   - a contradiction caused by a detected misquotation is folded into the quotation issue; the `CONTRADICTS` relation is kept.
8. **Preserve both sides**: nothing is deleted. A side is marked superseded only by a *declared* correction, which produces `CORRECTS`.

## 5. Inference checks (deterministic)

For a conclusion C with premises Π, where the premises are the earlier sentences in the same paragraph or an inline "…, which shows that …":

| Check | Fires when | Category |
|---|---|---|
| correlation → causation | C is causal and positive; some π is correlational or has an observational or survey basis; no π has an experimental or review basis | UNSUPPORTED_CAUSAL_CLAIM (PROBABLE_ERROR) |
| over-generalization | π restricts population, location or conditions, and C drops the restriction | INVALID_INFERENCE |
| quantifier shift | π says some, many, few or most, and C says all | INVALID_INFERENCE |
| modality strengthening | π is possible or probable, and C is asserted | INVALID_INFERENCE |

A derivation is marked `valid` only when C duplicates or is entailed by a premise; otherwise it is `unknown`. The engine never certifies an argument it has not checked.
Without an inference marker, a causal claim that rests on an observational or survey basis, with no experimental evidence anywhere in the corpus, gets a non-red SUSPICIOUS UNSUPPORTED_CAUSAL_CLAIM.

## 6. Paraconsistent treatment

6.1 Each assessment carries a Belnap value: T (supported), F (challenged), B (both) or N (neither). Contradictions are local. Nothing in the engine derives arbitrary conclusions from a contradiction, so conflicting evidence never makes the graph unusable.
6.2 A proposition with value B is `CONFLICTING_EVIDENCE` and remains usable as a node. Ranking promotes it, since resolving it reduces uncertainty.
6.3 Neither side is discarded automatically. If independent evidence clearly separates the two sides (one side `SUPPORTED`, the other `CONTRADICTED`), the issue becomes `PROBABLE_ERROR` on the weaker side. The reason states the strengths. Source prestige is never consulted, and a test swaps textbook and social-post labels to show identical outcomes.

## 7. Known gaps (measured or observed)

7.1 Paraphrase: claims with different subject wording ("Dransky joined Rovere" vs "Rovere signed Dransky") are not aligned. This is the main source of missed contradictions on the held-out set; contradiction recall was 0.25 blind and 0.50 post-hoc.
7.2 Event *place* and *date* are separate propositions. A date conflict needs the same event verb on both sides.
7.3 Single-valued attributes are recognized only from definite descriptions ("the capital of X", "the population of X") and event places. Other single-valued relations stay unflagged, which trades recall for precision.
