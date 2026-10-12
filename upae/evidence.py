"""Evidence evaluation engine.

Evidence items are created from typed relations between propositions of *other*
sources.  Each item records inspectable criteria (basis, primary/secondary,
directness, independence group, temporal relevance, conflicts of interest,
missing method details).  A transparent strength formula combines them
(docs/EVIDENCE_POLICY.md §4); the status rules in ``assess`` use per-group
maxima so that repeated copies never add up.  Source *reputation* is not an
input to strength.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Optional

from .graph import KnowledgeGraph
from .models import (Assessment, ClaimType, Evidence, EvidenceBasis, FindingClass,
                     IssueCategory, Proposition, RelationType, Stance, Status)
from .status import TransitionError, transition

TAU = 0.8  # independent strength needed for SUPPORTED / CONTRADICTED

BASIS_WEIGHT = {
    EvidenceBasis.EXPERIMENTAL: 1.0, EvidenceBasis.REVIEW: 1.0, EvidenceBasis.LOGICAL: 1.0,
    EvidenceBasis.DATASET: 0.9, EvidenceBasis.DOCUMENTARY: 0.8,
    EvidenceBasis.OBSERVATIONAL: 0.7, EvidenceBasis.SURVEY: 0.6,
    EvidenceBasis.SECONDARY: 0.4, EvidenceBasis.UNSPECIFIED: 0.4,
    EvidenceBasis.EXPERT_OPINION: 0.35, EvidenceBasis.ANECDOTAL: 0.15,
}
PRIMARY_BASES = {EvidenceBasis.EXPERIMENTAL, EvidenceBasis.REVIEW, EvidenceBasis.DATASET,
                 EvidenceBasis.DOCUMENTARY, EvidenceBasis.OBSERVATIONAL, EvidenceBasis.SURVEY}
CORRELATIONAL_BASES = {EvidenceBasis.OBSERVATIONAL, EvidenceBasis.SURVEY}

# relation type -> (stance relative to the *other* proposition, directness)
SUPPORTING_RELATIONS = {
    RelationType.DUPLICATES: "direct",
    RelationType.ENTAILS: "direct",     # only from the entailing side
    RelationType.REFINES: "indirect",   # only from the specific side
    RelationType.SUPPORTS: "direct",
}


def basis_of(g: KnowledgeGraph, p: Proposition) -> EvidenceBasis:
    if p.stated_basis:
        return p.stated_basis
    src = g.sources[p.source_refs[0]]
    if src.basis:
        return src.basis
    return EvidenceBasis.UNSPECIFIED


def _missing_details(g: KnowledgeGraph, q: Proposition, basis: EvidenceBasis) -> list[str]:
    if basis not in (EvidenceBasis.EXPERIMENTAL, EvidenceBasis.OBSERVATIONAL, EvidenceBasis.SURVEY):
        return []
    passage = g.passages.get(q.passage_id) if q.passage_id else None
    text = g.archive.get(q.source_refs[0], "") if passage is None else g.archive[q.source_refs[0]]
    missing = []
    if not re.search(r"\b(n\s*=\s*\d+|\d[\d,]*\s+(?:participants|patients|adults|children|students|"
                     r"respondents|people|subjects|households|firms|mice|rats|volunteers|schools|women|men))",
                     text, re.I):
        missing.append("sample size not reported")
    if basis == EvidenceBasis.EXPERIMENTAL and not re.search(r"\b(control|placebo|randomi[sz])", text, re.I):
        missing.append("control condition not described")
    return missing


def _coi(g: KnowledgeGraph, q: Proposition) -> list[str]:
    src = g.sources[q.source_refs[0]]
    out = []
    funder = src.metadata.get("funded_by") or src.metadata.get("funding")
    if funder:
        out.append(f"funded by {funder}")
    text = g.archive.get(src.id, "")
    m = re.search(r"\b(?:funded|sponsored|paid for|commissioned)\s+by\s+([^.;,]+)", text, re.I)
    if m:
        out.append(f"{m.group(0).strip()}")
    return sorted(set(out))


def strength(basis: EvidenceBasis, secondhand: bool, directness: str, for_causal: bool,
             coi: bool, missing: list, temporal: str, retracted: bool) -> tuple[float, dict]:
    terms = {"basis_weight": BASIS_WEIGHT[basis]}
    terms["secondhand"] = 0.8 if secondhand else 1.0
    terms["directness"] = 1.0 if directness == "direct" else 0.5
    terms["causal_design"] = 0.5 if (for_causal and basis in CORRELATIONAL_BASES) else 1.0
    terms["conflict_of_interest"] = 0.8 if coi else 1.0
    terms["method_details"] = 0.9 if missing else 1.0
    terms["temporal"] = 0.8 if temporal == "different_period" else 1.0
    terms["retracted"] = 0.0 if retracted else 1.0
    s = 1.0
    for v in terms.values():
        s *= v
    return round(min(1.0, s), 3), terms


def make_evidence(g: KnowledgeGraph, target: Proposition, via: Proposition, stance: Stance,
                  directness: str, method: str, correlational: bool = False) -> Optional[Evidence]:
    if via.id == target.id:
        return None
    for eid in target.evidence_refs:
        e = g.evidence[eid]
        if e.via_proposition == via.id and e.stance == stance:
            return e
    src = g.sources[via.source_refs[0]]
    basis = basis_of(g, via)
    if correlational and basis not in CORRELATIONAL_BASES:
        basis = EvidenceBasis.OBSERVATIONAL
    primary = basis in PRIMARY_BASES and via.attribution.kind == "author"
    missing = _missing_details(g, via, basis)
    coi = _coi(g, via)
    temporal = "unknown"
    if target.scope.time_norm and via.scope.time_norm:
        temporal = "same_period" if target.scope.time_norm == via.scope.time_norm else "different_period"
    st, terms = strength(basis, via.attribution.kind != "author", directness,
                         target.claim_type == ClaimType.CAUSAL,
                         bool(coi), missing, temporal, src.retracted)
    fp = f"ev|{target.fingerprint}|{via.fingerprint}|{stance.value}"
    eid = g.ids.allocate("evidence", fp)
    g.fingerprints[eid] = fp
    e = Evidence(id=eid, proposition_id=target.id, stance=stance, source_id=src.id,
                 passage_id=via.passage_id, via_proposition=via.id, basis=basis, primary=primary,
                 directness=directness, independence_group=src.independence_group,
                 temporal_relevance=temporal, conflicts_of_interest=coi,
                 missing_method_details=missing, strength=st, strength_terms=terms, method=method)
    g.add_evidence(e)
    return e


def logical_evidence(g: KnowledgeGraph, target: Proposition, reason: str) -> Evidence:
    fp = f"ev|{target.fingerprint}|logic|{reason}"
    eid = g.ids.allocate("evidence", fp)
    g.fingerprints[eid] = fp
    e = Evidence(id=eid, proposition_id=target.id, stance=Stance.CHALLENGES,
                 source_id=target.source_refs[0], passage_id=target.passage_id, via_proposition=None,
                 basis=EvidenceBasis.LOGICAL, primary=True, directness="direct",
                 independence_group="LOGIC", strength=1.0, strength_terms={"logical_proof": 1.0},
                 method=f"rule:{reason}")
    return g.add_evidence(e)


def _own_group(g: KnowledgeGraph, p: Proposition) -> str:
    return g.sources[p.source_refs[0]].independence_group or ""


def _cites_origin(g: KnowledgeGraph, p: Proposition, e: Evidence) -> bool:
    """True if the evidence comes from a source that p's source explicitly relies on
    (cites); such evidence is p's basis and counts, but only once."""
    src = g.sources[p.source_refs[0]]
    return e.source_id in src.cites


def assess(g: KnowledgeGraph, p: Proposition, review_triggers: list[str],
           confirmed_error: bool, previous: Optional[dict] = None,
           extra_dependent: int = 0) -> Assessment:
    a = Assessment(id="A-" + p.id.split("-")[1], proposition_id=p.id)
    if previous:
        a.status = Status(previous.get("status", "UNVERIFIED"))
        a.history = list(previous.get("history", []))
    own = _own_group(g, p)
    support: dict[str, float] = defaultdict(float)
    challenge: dict[str, float] = defaultdict(float)
    dependent = 0
    for eid in p.evidence_refs:
        e = g.evidence[eid]
        grp = e.independence_group or e.source_id
        if grp == own and e.basis != EvidenceBasis.LOGICAL and not _cites_origin(g, p, e):
            dependent += 1
            continue
        bucket = support if e.stance == Stance.SUPPORTS else challenge
        bucket[grp] = max(bucket[grp], e.strength)
    dependent += extra_dependent  # reworded copies found by the anchor heuristic
    S, C = round(sum(support.values()), 3), round(sum(challenge.values()), 3)
    a.support_strength, a.challenge_strength = S, C
    a.support_groups, a.challenge_groups = sorted(support), sorted(challenge)
    a.dependent_copies = dependent
    a.criteria = {
        "independent_support_groups": len(support), "independent_challenge_groups": len(challenge),
        "dependent_copies": dependent, "support_strength": S, "challenge_strength": C,
        "stated_basis": (p.stated_basis.value if p.stated_basis else None),
        "extraction_confidence": p.extraction.confidence,
        "deterministic_extraction": p.extraction.deterministic,
        "tau": TAU,
    }
    src = g.sources[p.source_refs[0]]

    if src.retracted:
        new, why, conf = Status.RETRACTED, f"Source {src.id} is marked as retracted.", 0.95
    elif p.claim_type == ClaimType.COMPOUND:
        new, why, conf = _compound_status(g, p)
    elif not p.is_truth_apt:
        new, why, conf = (Status.OUT_OF_SCOPE,
                          f"{p.claim_type.value} — recorded as attributed {p.claim_type.value}, "
                          "not assessed as fact.", 0.8)
    elif review_triggers:
        new, why, conf = Status.HUMAN_REVIEW_REQUIRED, "Review required: " + "; ".join(review_triggers), None
    elif confirmed_error:
        new, why, conf = Status.CONTRADICTED, "Deterministic check proves the stated value wrong.", 0.95
    elif S >= TAU and C < S / 2:
        new, why = Status.SUPPORTED, f"{len(support)} independent supporting group(s), S={S:.2f} ≥ τ, C={C:.2f}."
        conf = round(min(0.95, 0.45 + 0.25 * min(S, 2) - 0.2 * min(C, 1)), 2)
    elif C >= TAU and S < C / 2:
        new, why = Status.CONTRADICTED, f"{len(challenge)} independent challenging group(s), C={C:.2f} ≥ τ, S={S:.2f}."
        conf = round(min(0.95, 0.45 + 0.25 * min(C, 2) - 0.2 * min(S, 1)), 2)
    elif S > 0 and C > 0:
        new, why, conf = Status.CONFLICTING_EVIDENCE, f"Support S={S:.2f} and challenge C={C:.2f}; neither dominates.", 0.6
    elif S > 0 or C > 0:
        new, why = Status.INSUFFICIENT_EVIDENCE, f"Only weak independent evidence (S={S:.2f}, C={C:.2f} < τ={TAU})."
        conf = 0.6
    elif dependent:
        new, why, conf = (Status.INSUFFICIENT_EVIDENCE,
                          f"Repeated by {dependent} dependent source(s) sharing origin {own}; "
                          "no independent corroboration.", 0.7)
    else:
        new, why, conf = Status.UNVERIFIED, "No evidence in the corpus beyond the assertion itself.", 0.7
    a.review_triggers = list(review_triggers)
    a.review_required = bool(review_triggers) or p.extraction.review_required
    a.rationale = why
    a.confidence = conf
    a.belnap = ("B" if S >= TAU and C >= TAU else "T" if S >= TAU else "F" if (C >= TAU or confirmed_error)
                else "N")
    try:
        transition(a, new, why, actor="system")
    except TransitionError as exc:
        a.review_triggers.append(f"automatic transition blocked: {exc}")
        a.review_required = True
        a.rationale = f"{why} (status kept at {a.status.value}: {exc})"
    return a


def _compound_status(g: KnowledgeGraph, p: Proposition):
    statuses = [g.assessments[c].status for c in p.components if c in g.assessments]
    if not statuses:
        return Status.UNVERIFIED, "Compound with unassessed components.", None
    order = [Status.RETRACTED, Status.CONTRADICTED, Status.HUMAN_REVIEW_REQUIRED,
             Status.CONFLICTING_EVIDENCE, Status.INSUFFICIENT_EVIDENCE, Status.UNVERIFIED,
             Status.OUT_OF_SCOPE, Status.SUPPORTED]
    worst = min(statuses, key=order.index)
    return worst, f"Conjunction of {len(statuses)} components; weakest component is {worst.value}.", None


def upgrade_contradiction_findings(g: KnowledgeGraph) -> None:
    """After assessment: a genuine contradiction whose sides are clearly separated by
    independent evidence becomes a PROBABLE_ERROR on the weaker side.  Prestige is
    never consulted; both propositions stay in the graph."""
    contra = {IssueCategory.NUMERICAL_INCONSISTENCY, IssueCategory.CATEGORICAL_CONFLICT,
              IssueCategory.TEMPORAL_DISAGREEMENT, IssueCategory.INTERNAL_INCONSISTENCY}
    for issue in g.issues.values():
        if issue.category not in contra or issue.finding_class != FindingClass.UNRESOLVED_CONTRADICTION:
            continue
        sides = issue.details.get("sides") or ([issue.affected[:1], issue.affected[1:2]]
                                               if len(issue.affected) == 2 else None)
        if not sides:
            continue
        st = [[g.assessments[x].status for x in side if x in g.assessments] for side in sides]
        for weak_i, strong_i in ((0, 1), (1, 0)):
            weak, strong = st[weak_i], st[strong_i]
            if weak and all(s == Status.CONTRADICTED for s in weak) and Status.SUPPORTED in strong:
                issue.finding_class = FindingClass.PROBABLE_ERROR
                issue.details["probable_error_on"] = list(sides[weak_i])
                issue.details["better_supported"] = list(sides[strong_i])
                s_best = max(g.assessments[x].support_strength for x in sides[strong_i])
                c_weak = max(g.assessments[x].challenge_strength for x in sides[weak_i])
                issue.reason += (f" Independent evidence favours {', '.join(sides[strong_i])} (S={s_best:.2f})"
                                 f" over {', '.join(sides[weak_i])} (C={c_weak:.2f}); both are kept.")
                issue.compute_red()
                break
