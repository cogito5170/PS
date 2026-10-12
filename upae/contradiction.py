"""Staged proposition comparison and contradiction detection.

Stages (docs/CONTRADICTION_SEMANTICS.md):
  1. candidate retrieval   — inverted index over content tokens of subject/object
  2. alignment             — entities, predicate family, time, location, population,
                             conditions, units/measure, definitions, modality, quantifier
  3. incompatibility test  — family-specific deterministic rules
  4. dimension of disagreement
  5. (evidence retrieval happens in evidence.py)
  6. classification        — GENUINE | APPARENT | UNRESOLVED, with required assumptions
  7. structured issue      — produced by pipeline from the Comparison
  8. both propositions are always preserved
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from itertools import combinations
from typing import Optional

from .graph import KnowledgeGraph
from .models import ClaimType, Modality, Polarity, Proposition
from .textutil import content_set, jaccard, overlap, tokens
from .units import comparable, values_conflict

SCOPE_DIMS = ("time", "location", "population", "conditions")
MAX_CANDIDATES = 40
ENTITY_THRESHOLD = 0.5
EFFECT_SIZE_TOLERANCE = 0.25
HEDGED = {Modality.POSSIBLE, Modality.PROBABLE, Modality.QUESTIONED, Modality.PREDICTED}


def family(p: Proposition) -> str:
    pr = p.predicate
    if pr in ("increases", "decreases", "causes", "affects"):
        return "effect"
    if pr in ("increased", "decreased"):
        return "change"
    if pr == "has_value":
        return "value"
    if pr == "correlates_with":
        return "assoc"
    if pr == "is_defined_as":
        return "def"
    if pr.endswith("_in") and p.quantity is not None and p.quantity.kind == "year":
        return "event:" + pr
    if pr == "equals":
        return "math"
    if pr == "asserts":
        return "fallback"
    return "attr:" + pr


@dataclass
class Comparison:
    a: str
    b: str
    family: str
    subject_sim: float
    object_sim: float
    scope: dict = field(default_factory=dict)       # dim -> same|different|one_unspecified|both_unspecified
    scope_notes: dict = field(default_factory=dict)
    compatible: Optional[bool] = None               # False = logically incompatible content
    conflict_dims: list = field(default_factory=list)
    equivalent: bool = False
    entails: Optional[str] = None                   # id of the entailing (more specific) side
    refines: Optional[str] = None                   # id of the more specific side
    classification: Optional[str] = None            # GENUINE | APPARENT | UNRESOLVED | None
    differing: list = field(default_factory=list)
    unspecified: list = field(default_factory=list)
    assumptions: list = field(default_factory=list)
    confidence: float = 0.0
    rationale: str = ""


# ----------------------------------------------------------------------- retrieval

def candidate_pairs(g: KnowledgeGraph, props: list[Proposition]) -> list[tuple[str, str]]:
    index: dict[str, set[str]] = defaultdict(set)
    keys: dict[str, frozenset] = {}
    for p in props:
        ks = content_set(p.subject)
        keys[p.id] = ks
        for k in ks:
            index[k].add(p.id)
    pairs: set[tuple[str, str]] = set()
    for p in props:
        scores: dict[str, int] = defaultdict(int)
        for k in keys[p.id]:
            for q in index[k]:
                if q != p.id:
                    scores[q] += 1
        best = sorted(scores, key=lambda q: (-scores[q], q))[:MAX_CANDIDATES]
        for q in best:
            pairs.add(tuple(sorted((p.id, q))))
    return sorted(pairs)


# ----------------------------------------------------------------------- alignment

def _implicit_year(g: KnowledgeGraph, p: Proposition) -> Optional[list]:
    src = g.sources[p.source_refs[0]]
    if src.published and re.match(r"\d{4}", src.published):
        y = int(src.published[:4])
        return [y, y]
    return None


TIME_VARYING = re.compile(
    r"\b(rate|unemployment|inflation|population|price|prices|cost|costs|gdp|sales|revenue|"
    r"share|number|count|budget|debt|deficit|growth|deaths|mortality|cases|enrol\w*|"
    r"turnout|wage|wages|income|salary|salaries|spending|emissions|production|exports|"
    r"imports|ridership|attendance|users|members|employees|stock|index|yield|poverty|"
    r"crime|approval|support|majority|vacancy|occupancy|level|levels|temperature)\b", re.I)


def _time_varying(p: Proposition) -> bool:
    return family(p) == "change" or bool(TIME_VARYING.search(p.subject))


def _time_state(g, a: Proposition, b: Proposition, notes: dict) -> str:
    ta, tb = a.scope.time_norm, b.scope.time_norm
    stat = family(a) in ("value", "change") and family(b) in ("value", "change") \
        and _time_varying(a) and _time_varying(b)
    if stat:  # time-varying statistics without explicit time refer to publication time  # statistics without explicit time refer (implicitly) to publication time
        if ta is None and (ia := _implicit_year(g, a)):
            ta = ia
            notes.setdefault("implicit_time", []).append(a.id)
        if tb is None and (ib := _implicit_year(g, b)):
            tb = ib
            notes.setdefault("implicit_time", []).append(b.id)
    if ta is None and tb is None:
        if a.scope.time and b.scope.time and a.scope.time != b.scope.time:
            return "different"
        if bool(a.scope.time) != bool(b.scope.time):
            return "one_unspecified"
        return "both_unspecified"
    if ta is None or tb is None:
        return "one_unspecified"
    return "same" if ta == tb else "different"


def _full_tokens(text: str) -> set:
    return set(tokens(text)) - {"the", "an", "of", "in", "at", "for", "on"}


def _text_state(x: Optional[str], y: Optional[str], thresh: float = 0.6) -> str:
    """Scope strings are compared on *all* tokens (labels such as "group A" vs
    "group B" or "aged 18" vs "aged 65" must stay distinct)."""
    if not x and not y:
        return "both_unspecified"
    if not x or not y:
        return "one_unspecified"
    cx, cy = _full_tokens(x), _full_tokens(y)
    if x.lower() == y.lower() or (cx and cy and jaccard(cx, cy) >= thresh):
        return "same"
    return "different"


def _cond_state(a: list, b: list) -> str:
    if not a and not b:
        return "both_unspecified"
    if not a or not b:
        return "one_unspecified"
    ca, cb = _full_tokens(" ".join(a)), _full_tokens(" ".join(b))
    return "same" if jaccard(ca, cb) >= 0.75 else "different"


def align(g: KnowledgeGraph, a: Proposition, b: Proposition) -> Comparison:
    fa, fb = family(a), family(b)
    fam = fa if fa == fb else f"{fa}|{fb}"
    ssim = jaccard(content_set(a.subject), content_set(b.subject))
    if ssim < ENTITY_THRESHOLD and overlap(content_set(a.subject), content_set(b.subject)) >= 0.99 \
            and min(len(content_set(a.subject)), len(content_set(b.subject))) >= 2:
        ssim = max(ssim, ENTITY_THRESHOLD)  # one subject contains the other entirely
    if a.object is None and b.object is None:
        osim = 1.0
    elif a.object is None or b.object is None:
        osim = 0.0
    else:
        osim = jaccard(content_set(a.object), content_set(b.object))
        if overlap(content_set(a.object), content_set(b.object)) >= 0.99:
            osim = max(osim, 0.6)
    c = Comparison(a=a.id, b=b.id, family=fam, subject_sim=round(ssim, 2), object_sim=round(osim, 2))
    notes: dict = {}
    c.scope["time"] = _time_state(g, a, b, notes)
    c.scope["location"] = _text_state(a.scope.location, b.scope.location)
    c.scope["population"] = _text_state(a.scope.population, b.scope.population)
    c.scope["conditions"] = _cond_state(a.scope.conditions, b.scope.conditions)
    qa, qb = a.quantity, b.quantity
    if qa is not None and qb is not None and qa.kind != "year":
        same_measure = comparable(qa, qb) and (qa.kind == qb.kind or {qa.kind, qb.kind} <= {"level", "from_to"})
        c.scope["units"] = "same" if same_measure else "different"
        if not same_measure:
            notes["units"] = f"{qa.raw} ({qa.dimension}, {qa.kind}) vs {qb.raw} ({qb.dimension}, {qb.kind})"
    # definitions used by each source for shared terms
    da, db = a.scope.definitions, b.scope.definitions
    shared = set(da) & set(db)
    if shared:
        diff = []
        for term in shared:
            pa, pb = g.propositions[da[term]], g.propositions[db[term]]
            if jaccard(content_set(pa.object or ""), content_set(pb.object or "")) < 0.6:
                diff.append(term)
        c.scope["definitions"] = "different" if diff else "same"
        if diff:
            notes["definitions"] = diff
    elif set(da) ^ set(db):
        notes["definition_only_one_side"] = sorted(set(da) ^ set(db))
    c.scope_notes = notes
    return c


# ----------------------------------------------------------------------- incompatibility

def _level_value(q):
    if q.kind == "from_to":
        return q.to_value
    return q.norm_value


def incompatibility(a: Proposition, b: Proposition, c: Comparison) -> None:
    """Fill c.compatible / conflict_dims / equivalent / entails / refines."""
    fam = c.family
    if fam in ("change|value", "value|change"):
        # "rose to 7.8 m" asserts the level 7.8 m: compare it with a stated value
        ch, val = (a, b) if family(a) == "change" else (b, a)
        if ch.quantity is not None and ch.quantity.kind in ("level", "from_to") and val.quantity is not None:
            fam = "value"
            c.family = "value"
        else:
            return
    if "|" in fam or fam in ("math", "fallback"):
        return
    if c.subject_sim < ENTITY_THRESHOLD:
        return
    pol_diff = a.polarity != b.polarity
    qa, qb = a.quantity, b.quantity

    if fam == "def":
        if c.subject_sim >= 0.8:
            if jaccard(content_set(a.object or ""), content_set(b.object or "")) < 0.5:
                c.compatible, c.conflict_dims = False, ["definition"]
            else:
                c.equivalent = True
        return

    if fam == "effect" or fam == "assoc":
        if c.object_sim < ENTITY_THRESHOLD:
            return
        da, db = a.direction, b.direction
        if a.predicate in ("causes", "affects") or b.predicate in ("causes", "affects"):
            # "has no effect on" vs any positive effect claim
            if pol_diff:
                c.compatible, c.conflict_dims = False, ["polarity"]
            elif a.predicate == b.predicate:
                c.equivalent = True
            return
        if da and db and da != db and not pol_diff:
            c.compatible, c.conflict_dims = False, ["direction"]
            if qa and qb:
                c.conflict_dims.append("magnitude")
            return
        if pol_diff and (da == db):
            c.compatible, c.conflict_dims = False, ["polarity"]
            return
        if not pol_diff and da == db:
            if qa and qb and comparable(qa, qb) and qa.kind == qb.kind:
                if values_conflict(qa, qb, EFFECT_SIZE_TOLERANCE):
                    c.compatible, c.conflict_dims = False, ["magnitude"]
                    return
                c.equivalent = True
                return
            if qa and not qb:
                c.entails = a.id
            elif qb and not qa:
                c.entails = b.id
            else:
                c.equivalent = True
        return

    if fam == "change":
        if a.direction and b.direction and a.direction != b.direction and not pol_diff:
            c.compatible, c.conflict_dims = False, ["direction"]
            return
        if qa and qb and comparable(qa, qb) and qa.kind == qb.kind and not pol_diff:
            va, vb = _level_value(qa), _level_value(qb)
            if qa.kind in ("change", "change_pp"):
                va, vb = qa.norm_value, qb.norm_value
            if va is not None and vb is not None:
                from .models import Quantity
                if values_conflict(Quantity(value=va, norm_value=va, approximate=qa.approximate),
                                   Quantity(value=vb, norm_value=vb, approximate=qb.approximate)):
                    c.compatible, c.conflict_dims = False, ["value"]
                    return
        if not pol_diff and a.direction == b.direction:
            if qa and not qb:
                c.entails = a.id
            elif qb and not qa:
                c.entails = b.id
            else:
                c.equivalent = True
        elif pol_diff and a.direction == b.direction:
            c.compatible, c.conflict_dims = False, ["polarity"]
        return

    if fam == "value":
        if c.subject_sim < 0.6 or qa is None or qb is None:
            return
        if not comparable(qa, qb):
            c.scope["units"] = "different"
            c.compatible, c.conflict_dims = False, ["value"]
            return
        va, vb = _level_value(qa), _level_value(qb)
        from .models import Quantity
        conflict = values_conflict(Quantity(value=va or 0, norm_value=va, approximate=qa.approximate),
                                   Quantity(value=vb or 0, norm_value=vb, approximate=qb.approximate))
        if conflict and not pol_diff:
            c.compatible, c.conflict_dims = False, ["value"]
        elif not conflict and pol_diff:
            c.compatible, c.conflict_dims = False, ["polarity"]
        elif not conflict:
            c.equivalent = True
        return

    if fam.startswith("event:"):
        if qa is None or qb is None:
            return
        if qa.value != qb.value and not pol_diff:
            c.compatible, c.conflict_dims = False, ["event_time"]
        elif qa.value == qb.value and not pol_diff:
            c.equivalent = True
        elif qa.value == qb.value and pol_diff:
            c.compatible, c.conflict_dims = False, ["polarity"]
        return

    if fam.startswith("attr:"):
        if qa is not None and qb is not None and comparable(qa, qb):
            rest_a = content_set(re.sub(r"[\d.,$€£%]+", " ", a.object or ""))
            rest_b = content_set(re.sub(r"[\d.,$€£%]+", " ", b.object or ""))
            if jaccard(rest_a, rest_b) >= 0.6:
                conflict = values_conflict(qa, qb)
                if conflict and not pol_diff:
                    c.compatible, c.conflict_dims = False, ["value"]
                elif not conflict and not pol_diff:
                    c.equivalent = True
                elif not conflict and pol_diff:
                    c.compatible, c.conflict_dims = False, ["polarity"]
                return
        if c.object_sim >= 0.6:
            if pol_diff:
                c.compatible, c.conflict_dims = False, ["polarity"]
            else:
                c.equivalent = True
            return
        # an event happens at one place; definite descriptions denote one value
        functional = (_functional(a) and _functional(b)) or a.predicate.endswith("_at")
        if functional and c.object_sim < 0.2 and not pol_diff and \
                (a.predicate == "is" or a.predicate.endswith("_at")):
            c.compatible, c.conflict_dims = False, ["categorical_value"]
            c.scope_notes["functional_assumption"] = True


_FUNCTIONAL_HEADS = re.compile(r"^(?:the\s+)?(capital|population|height|length|area|founder|inventor|"
                               r"author|winner|president|ceo|chair|head|birthplace|mother|father|"
                               r"currency|official language|tallest|largest|smallest|first|last|"
                               r"name|date|cause|location|seat|headquarters)\b", re.I)


def _functional(p: Proposition) -> bool:
    """Definite descriptions denote a single value ("the capital of X is Y")."""
    surf = (p.surface or {}).get("subject") or p.subject
    return bool(_FUNCTIONAL_HEADS.match(surf)) or bool(re.match(r"^the\s+\w+\s+of\s+", surf, re.I))


# ----------------------------------------------------------------------- classification

ASSUMPTION_TEXT = {
    "time": "both refer to the same time period",
    "location": "both refer to the same location",
    "population": "both refer to the same population",
    "conditions": "both hold under the same conditions",
}


def classify(g: KnowledgeGraph, a: Proposition, b: Proposition, c: Comparison) -> Comparison:
    if c.compatible is not False and not (c.equivalent or c.entails):
        return c
    dims = ["time", "location", "population", "conditions", "units", "definitions"]
    c.differing = [d for d in dims if c.scope.get(d) == "different"]
    c.unspecified = [d for d in SCOPE_DIMS if c.scope.get(d) == "one_unspecified"]
    both = [d for d in SCOPE_DIMS if c.scope.get(d) == "both_unspecified"]
    if c.family.startswith("event:"):
        both = [d for d in both if d == "conditions"]  # an event's date is not scoped by time/place
    for d in both:
        c.assumptions.append(f"Assumed {ASSUMPTION_TEXT[d]} (neither proposition states it).")
    if c.scope_notes.get("implicit_time"):
        c.assumptions.append("Time inferred from publication date for "
                             + ", ".join(c.scope_notes["implicit_time"]) + ".")
    if c.scope_notes.get("functional_assumption"):
        c.assumptions.append("Assumed the subject denotes a single value (definite description).")
    hedged = a.modality in HEDGED or b.modality in HEDGED
    quant_diff = (a.quantifier or "all") != (b.quantifier or "all") and \
        ({a.quantifier, b.quantifier} & {"some", "many", "few", "most"})

    if c.compatible is False:
        if c.differing:
            c.classification = "APPARENT"
            c.rationale = ("Claims look incompatible on " + ", ".join(c.conflict_dims)
                           + " but differ in " + ", ".join(c.differing)
                           + "; they are not contradictory as stated.")
        elif hedged and "definition" not in c.conflict_dims:
            c.classification = "APPARENT"
            c.differing = ["modality"]
            c.rationale = ("At least one claim is hedged/predicted ("
                           f"{a.modality.value} vs {b.modality.value}); a possibility does not "
                           "contradict an assertion.")
        elif quant_diff:
            c.classification = "APPARENT"
            c.differing = ["quantifier"]
            c.rationale = f"Quantifiers differ ({a.quantifier} vs {b.quantifier})."
        elif c.unspecified:
            c.classification = "UNRESOLVED"
            c.rationale = ("Claims conflict on " + ", ".join(c.conflict_dims) + " but "
                           + ", ".join(c.unspecified) + " is specified for only one of them; "
                           "contradiction depends on unstated scope.")
            for d in c.unspecified:
                c.assumptions.append(f"Would require that {ASSUMPTION_TEXT[d]}.")
        else:
            c.classification = "GENUINE"
            c.rationale = ("Same entities, predicate and scope; incompatible on "
                           + ", ".join(c.conflict_dims) + ".")
        value_like = c.family in ("value", "change") or c.family.startswith("event:") \
            or bool(c.scope_notes.get("functional_assumption")) or "value" in c.conflict_dims
        conf = 0.55 + 0.25 * min(c.subject_sim, 1.0 if value_like else c.object_sim)
        conf += 0.1 * (min(a.extraction.confidence, b.extraction.confidence) - 0.5)
        conf -= 0.02 * len(both)
        if c.scope_notes.get("functional_assumption"):
            conf -= 0.1
        c.confidence = round(max(0.3, min(0.95, conf)), 2)
    else:
        # compatible claims: equivalence / entailment / refinement
        if c.differing:
            c.equivalent = False
            c.entails = None
            return c
        if c.unspecified:
            spec_a = sum(1 for d in SCOPE_DIMS if c.scope.get(d) == "one_unspecified" and _has(a, d))
            spec_b = sum(1 for d in SCOPE_DIMS if c.scope.get(d) == "one_unspecified" and _has(b, d))
            if spec_a and not spec_b:
                c.refines = a.id
            elif spec_b and not spec_a:
                c.refines = b.id
            c.equivalent = False
            c.entails = None
        c.confidence = round(0.5 + 0.4 * min(c.subject_sim, c.object_sim), 2)
    return c


def _has(p: Proposition, dim: str) -> bool:
    v = getattr(p.scope, dim)
    return bool(v)


def compare_all(g: KnowledgeGraph, props: list[Proposition]) -> list[Comparison]:
    by_id = {p.id: p for p in props}
    out = []
    for x, y in candidate_pairs(g, props):
        a, b = by_id[x], by_id[y]
        if a.claim_type in (ClaimType.OPINION, ClaimType.NORMATIVE, ClaimType.COMPOUND) or \
                b.claim_type in (ClaimType.OPINION, ClaimType.NORMATIVE, ClaimType.COMPOUND):
            continue
        if a.passage_id == b.passage_id and a.quote == b.quote:
            continue  # clauses of the same sentence
        c = align(g, a, b)
        incompatibility(a, b, c)
        classify(g, a, b, c)
        if c.compatible is False or c.equivalent or c.entails or c.refines:
            out.append(c)
    return out


def same_source(a: Proposition, b: Proposition) -> bool:
    return bool(set(a.source_refs) & set(b.source_refs))


__all__ = ["Comparison", "compare_all", "align", "incompatibility", "classify", "family",
           "candidate_pairs", "same_source", "Polarity"]
