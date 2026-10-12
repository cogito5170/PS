"""Transparent, configurable ranking and knowledge compression.

Ranking decides what the *main report* shows.  It is kept separate from truth
assessment (status) and from source credibility: a high rank means "worth
reading first", never "true".  Every hidden, merged or summarised proposition
gets an ``Omission`` record with the reason; nothing is deleted.

score(p) = Σ_k w_k · f_k(p) − w_redundancy · redundant(p)

f_relevance       query-token coverage (1.0 when no query is configured)
f_evidence        max evidence strength attached to p (support or challenge)
f_novelty         1 − max content-token Jaccard with higher-ranked propositions
f_connectivity    relation degree / max degree
f_contradiction   max issue severity (0..1), halved for non-red issues
f_uncertainty     open status (conflicting / review / insufficient) × (0.5 + 0.5·connectivity)
"""
from __future__ import annotations

from .graph import KnowledgeGraph
from .models import SEVERITY_ORDER, ClaimType, Omission, RelationType, Status
from .textutil import content_set, jaccard

OPEN_STATUS = {Status.CONFLICTING_EVIDENCE: 1.0, Status.HUMAN_REVIEW_REQUIRED: 1.0,
               Status.CONTRADICTED: 0.75, Status.INSUFFICIENT_EVIDENCE: 0.5}


def features(g: KnowledgeGraph, pid: str, query_tokens: frozenset, max_degree: int) -> dict:
    p = g.propositions[pid]
    toks = content_set(p.text + " " + p.quote)
    rel = 1.0 if not query_tokens else len(query_tokens & toks) / len(query_tokens)
    ev = max((g.evidence[e].strength for e in p.evidence_refs), default=0.0)
    deg = len(p.relation_refs)
    conn = deg / max_degree if max_degree else 0.0
    contra = 0.0
    for iid in p.issue_refs:
        i = g.issues[iid]
        v = (SEVERITY_ORDER[i.severity] + 1) / 4
        contra = max(contra, v if i.red_for(pid) else v / 2)
    a = g.assessments.get(pid)
    unc = OPEN_STATUS.get(a.status, 0.0) * (0.5 + 0.5 * conn) if a else 0.0
    return {"relevance": round(rel, 3), "evidence_quality": round(ev, 3),
            "connectivity": round(conn, 3), "contradiction": round(contra, 3),
            "uncertainty_reduction": round(unc, 3)}


def rank_and_compress(g: KnowledgeGraph, config: dict) -> None:
    w = config.get("ranking", {})
    max_core = int(config.get("max_core", 25))
    query = config.get("query")
    qt = content_set(query) if query else frozenset()
    g.omissions = []
    g.ranking = []
    candidates = [p for p in g.propositions.values() if p.claim_type != ClaimType.COMPOUND]
    for p in g.propositions.values():
        if p.claim_type == ClaimType.COMPOUND:
            g.omissions.append(Omission(proposition_id=p.id, decision="summarized",
                                        reason="compound statement represented by its components "
                                               + ", ".join(p.components)))
    max_degree = max((len(p.relation_refs) for p in candidates), default=0)
    base = {}
    feats = {}
    for p in candidates:
        f = features(g, p.id, qt, max_degree)
        feats[p.id] = f
        base[p.id] = sum(w.get(k, 0.0) * v for k, v in f.items())
    order = sorted(candidates, key=lambda p: (-base[p.id], p.id))
    selected: list[str] = []
    merged_into: dict[str, str] = {}
    tokens = {p.id: content_set(p.text) for p in candidates}
    scores = {}
    for p in order:
        if p.superseded_by:
            merged_into[p.id] = p.superseded_by
            continue
        dup_reps = [g.other(r, p.id) for r in g.relations_of(p.id, RelationType.DUPLICATES)]
        rep = next((d for d in dup_reps if d in selected), None)
        if rep:
            merged_into[p.id] = rep
            continue
        nov = 1.0 - max((jaccard(tokens[p.id], tokens[s]) for s in selected), default=0.0)
        feats[p.id]["novelty"] = round(nov, 3)
        scores[p.id] = round(base[p.id] + w.get("novelty", 0.0) * nov, 4)
        selected.append(p.id)
    ranked = sorted(selected, key=lambda x: (-scores[x], x))
    core = set(ranked[:max_core])
    # counter-evidence retention: never hide a proposition carrying a red issue or
    # challenging a core proposition, whatever its score
    forced = set()
    for pid in ranked[max_core:]:
        p = g.propositions[pid]
        red = any(g.issues[i].red_for(pid) for i in p.issue_refs)
        challenges_core = any(e.via_proposition == pid and e.proposition_id in core
                              for e in g.evidence.values() if e.stance.value == "challenges")
        if red or challenges_core:
            forced.add(pid)
    for pos, pid in enumerate(ranked):
        decision = "core" if pid in core else "core_forced" if pid in forced else "hidden_low_priority"
        g.ranking.append({"id": pid, "rank": pos + 1, "score": scores[pid], "features": feats[pid],
                          "decision": decision})
        if decision == "hidden_low_priority":
            g.omissions.append(Omission(proposition_id=pid, decision="hidden_low_priority",
                                        reason=f"rank {pos + 1} > max_core={max_core}; no red issue "
                                               "and not counter-evidence to a core proposition",
                                        score=scores[pid]))
        elif decision == "core_forced":
            g.omissions.append(Omission(proposition_id=pid, decision="retained_counterevidence",
                                        reason="low rank but kept: carries a red issue or challenges a "
                                               "core proposition", score=scores[pid]))
    for pid, rep in merged_into.items():
        g.omissions.append(Omission(proposition_id=pid, decision="merged", into=rep,
                                    reason=("superseded by correction " if g.propositions[pid].superseded_by
                                            else "duplicate of ") + rep))
