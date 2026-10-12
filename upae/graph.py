"""In-memory proposition graph with stable identifiers and referential integrity.

Objects are kept in separate typed tables (sources, passages, propositions,
evidence, relations, assessments, issues, derivations).  Identifiers are
``<prefix>-<6 digits>``; when a previous analysis snapshot is supplied, objects with
the same fingerprint keep their previous identifier (stable across runs).
"""
from __future__ import annotations

import json
from collections import defaultdict
from typing import Iterable, Optional

from .models import (
    SCHEMA_VERSION, Assessment, Derivation, Evidence, Issue, Omission, Passage,
    Proposition, Relation, RelationType, Source, UNDIRECTED_RELATIONS,
)

PREFIX = {
    "source": "S", "passage": "T", "proposition": "P", "evidence": "E",
    "relation": "R", "assessment": "A", "issue": "I", "derivation": "D",
}


class IdAllocator:
    def __init__(self, previous: Optional[dict] = None):
        # previous: {kind: {fingerprint: id}}
        self.previous = previous or {}
        self.counters: dict[str, int] = defaultdict(int)
        self.used: set[str] = set()
        for kind, mapping in self.previous.items():
            for ident in mapping.values():
                n = int(ident.split("-")[1])
                self.counters[kind] = max(self.counters[kind], n)

    def allocate(self, kind: str, fingerprint: Optional[str] = None) -> str:
        if fingerprint is not None:
            prev = self.previous.get(kind, {}).get(fingerprint)
            if prev and prev not in self.used:
                self.used.add(prev)
                return prev
        self.counters[kind] += 1
        ident = f"{PREFIX[kind]}-{self.counters[kind]:06d}"
        while ident in self.used:
            self.counters[kind] += 1
            ident = f"{PREFIX[kind]}-{self.counters[kind]:06d}"
        self.used.add(ident)
        return ident


class IntegrityError(ValueError):
    pass


class KnowledgeGraph:
    def __init__(self, ids: Optional[IdAllocator] = None):
        self.ids = ids or IdAllocator()
        self.sources: dict[str, Source] = {}
        self.passages: dict[str, Passage] = {}
        self.propositions: dict[str, Proposition] = {}
        self.evidence: dict[str, Evidence] = {}
        self.relations: dict[str, Relation] = {}
        self.assessments: dict[str, Assessment] = {}   # keyed by proposition id
        self.issues: dict[str, Issue] = {}
        self.derivations: dict[str, Derivation] = {}
        self.omissions: list[Omission] = []
        self.archive: dict[str, str] = {}               # source id -> full original text
        self.limitations: list[str] = []
        self.model_calls: int = 0
        self.fingerprints: dict[str, str] = {}          # object id -> stable fingerprint
        self.ranking: list[dict] = []
        self.timings: dict[str, float] = {}
        self.changes: Optional[dict] = None
        self._rel_index: dict[tuple, str] = {}

    # ------------------------------------------------------------------ add
    def add_source(self, s: Source) -> Source:
        self.sources[s.id] = s
        return s

    def add_passage(self, p: Passage) -> Passage:
        self.passages[p.id] = p
        return p

    def add_proposition(self, p: Proposition) -> Proposition:
        self.propositions[p.id] = p
        return p

    def add_evidence(self, e: Evidence) -> Evidence:
        self.evidence[e.id] = e
        prop = self.propositions[e.proposition_id]
        if e.id not in prop.evidence_refs:
            prop.evidence_refs.append(e.id)
        return e

    def add_relation(self, rtype: RelationType, a: str, b: str, **kw) -> Relation:
        """Add (or return the existing) relation of ``rtype`` between ``a`` and ``b``.
        Undirected relations are stored with endpoints in sorted order."""
        directed = rtype not in UNDIRECTED_RELATIONS
        if not directed:
            a, b = sorted((a, b))
        key = (rtype, a, b)
        if key in self._rel_index:
            return self.relations[self._rel_index[key]]
        fp = f"{rtype.value}|{self.propositions[a].fingerprint}|{self.propositions[b].fingerprint}"
        rid = self.ids.allocate("relation", fp)
        rel = Relation(id=rid, type=rtype, source=a, target=b, directed=directed, **kw)
        self.relations[rid] = rel
        self._rel_index[key] = rid
        for pid in (a, b):
            if rid not in self.propositions[pid].relation_refs:
                self.propositions[pid].relation_refs.append(rid)
        return rel

    def remove_relation(self, rid: str) -> None:
        rel = self.relations.pop(rid)
        self._rel_index.pop((rel.type, rel.source, rel.target), None)
        for pid in (rel.source, rel.target):
            refs = self.propositions[pid].relation_refs
            if rid in refs:
                refs.remove(rid)

    def add_issue(self, issue: Issue) -> Issue:
        issue.compute_red()
        self.issues[issue.id] = issue
        for ref in issue.affected:
            if ref in self.propositions and issue.id not in self.propositions[ref].issue_refs:
                self.propositions[ref].issue_refs.append(issue.id)
        return issue

    def remove_issue(self, iid: str) -> None:
        issue = self.issues.pop(iid)
        for ref in issue.affected:
            if ref in self.propositions and iid in self.propositions[ref].issue_refs:
                self.propositions[ref].issue_refs.remove(iid)
        self.fingerprints.pop(iid, None)

    def add_derivation(self, d: Derivation) -> Derivation:
        self.derivations[d.id] = d
        return d

    # ------------------------------------------------------------------ query
    def relations_of(self, pid: str, rtype: Optional[RelationType] = None) -> list[Relation]:
        out = []
        for rid in self.propositions[pid].relation_refs:
            r = self.relations[rid]
            if rtype is None or r.type == rtype:
                out.append(r)
        return out

    def other(self, rel: Relation, pid: str) -> str:
        return rel.target if rel.source == pid else rel.source

    def props_of_source(self, sid: str) -> list[Proposition]:
        return [p for p in self.propositions.values() if sid in p.source_refs]

    def active_propositions(self) -> Iterable[Proposition]:
        return (p for p in self.propositions.values() if p.superseded_by is None)

    def issues_of(self, pid: str) -> list[Issue]:
        return [self.issues[i] for i in self.propositions[pid].issue_refs]

    # ------------------------------------------------------------------ integrity
    def validate(self) -> list[str]:
        """Return a list of referential-integrity / invariant violations (empty = ok)."""
        errs: list[str] = []
        for p in self.passages.values():
            if p.source_id not in self.sources:
                errs.append(f"{p.id}: unknown source {p.source_id}")
            src = self.archive.get(p.source_id)
            if src is not None and src[p.char_start:p.char_end] != p.text:
                errs.append(f"{p.id}: passage text does not match archive span")
        for p in self.propositions.values():
            if not p.source_refs:
                errs.append(f"{p.id}: proposition without source")
            for s in p.source_refs:
                if s not in self.sources:
                    errs.append(f"{p.id}: unknown source {s}")
            if p.passage_id is not None:
                pas = self.passages.get(p.passage_id)
                if pas is None:
                    errs.append(f"{p.id}: unknown passage {p.passage_id}")
                elif p.quote and p.quote not in pas.text:
                    errs.append(f"{p.id}: quote not found verbatim in passage {pas.id}")
            for ref in p.evidence_refs:
                if ref not in self.evidence:
                    errs.append(f"{p.id}: dangling evidence {ref}")
            for ref in p.relation_refs:
                if ref not in self.relations:
                    errs.append(f"{p.id}: dangling relation {ref}")
            for ref in p.issue_refs:
                if ref not in self.issues:
                    errs.append(f"{p.id}: dangling issue {ref}")
            for ref in p.components:
                if ref not in self.propositions:
                    errs.append(f"{p.id}: dangling component {ref}")
            if p.supersedes and p.supersedes not in self.propositions:
                errs.append(f"{p.id}: supersedes unknown {p.supersedes}")
            if p.schema_version != SCHEMA_VERSION:
                errs.append(f"{p.id}: schema version {p.schema_version}")
            if p.id not in self.assessments:
                errs.append(f"{p.id}: no assessment")
        for e in self.evidence.values():
            if e.proposition_id not in self.propositions:
                errs.append(f"{e.id}: unknown proposition")
            if e.via_proposition and e.via_proposition not in self.propositions:
                errs.append(f"{e.id}: unknown via-proposition")
            if e.source_id not in self.sources:
                errs.append(f"{e.id}: unknown source")
            if e.via_proposition == e.proposition_id:
                errs.append(f"{e.id}: proposition used as evidence for itself")
        for r in self.relations.values():
            for end in (r.source, r.target):
                if end not in self.propositions:
                    errs.append(f"{r.id}: unknown endpoint {end}")
            if r.source == r.target:
                errs.append(f"{r.id}: self-relation")
            if not r.rationale:
                errs.append(f"{r.id}: relation without rationale")
        for i in self.issues.values():
            if not i.affected:
                errs.append(f"{i.id}: issue without affected object")
            for ref in i.affected + i.conflicting:
                if ref not in self.propositions and ref not in self.sources:
                    errs.append(f"{i.id}: unknown reference {ref}")
            if not i.reason or not i.resolution:
                errs.append(f"{i.id}: issue missing reason or resolution")
        for d in self.derivations.values():
            for ref in [d.conclusion, *d.premises]:
                if ref not in self.propositions:
                    errs.append(f"{d.id}: unknown proposition {ref}")
        return errs

    # ------------------------------------------------------------------ serialise
    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "sources": [s.to_dict() for s in self.sources.values()],
            "passages": [p.to_dict() for p in self.passages.values()],
            "propositions": [p.to_dict() for p in self.propositions.values()],
            "evidence": [e.to_dict() for e in self.evidence.values()],
            "relations": [r.to_dict() for r in self.relations.values()],
            "assessments": [a.to_dict() for a in self.assessments.values()],
            "issues": [i.to_dict() for i in self.issues.values()],
            "derivations": [d.to_dict() for d in self.derivations.values()],
            "omissions": [o.to_dict() for o in self.omissions],
            "ranking": list(self.ranking),
            "limitations": list(self.limitations),
            "model_calls": self.model_calls,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "KnowledgeGraph":
        g = cls()
        for d in data.get("sources", []):
            g.add_source(Source.from_dict(d))
        for d in data.get("passages", []):
            g.add_passage(Passage.from_dict(d))
        for d in data.get("propositions", []):
            g.add_proposition(Proposition.from_dict(d))
        for d in data.get("evidence", []):
            g.evidence[d["id"]] = Evidence.from_dict(d)
        for d in data.get("relations", []):
            r = Relation.from_dict(d)
            g.relations[r.id] = r
            g._rel_index[(r.type, r.source, r.target)] = r.id
        for d in data.get("assessments", []):
            a = Assessment.from_dict(d)
            g.assessments[a.proposition_id] = a
        for d in data.get("issues", []):
            i = Issue.from_dict(d)
            g.issues[i.id] = i
        for d in data.get("derivations", []):
            dv = Derivation.from_dict(d)
            g.derivations[dv.id] = dv
        g.omissions = [Omission.from_dict(o) for o in data.get("omissions", [])]
        g.ranking = list(data.get("ranking", []))
        g.fingerprints = dict(data.get("fingerprints", {}))
        g.archive = dict(data.get("archive", {}))
        g.timings = dict(data.get("timings", {}))
        g.changes = data.get("changes")
        g.limitations = list(data.get("limitations", []))
        g.model_calls = data.get("model_calls", 0)
        return g

    def id_map(self) -> dict:
        """fingerprint -> id maps used to keep identifiers stable in the next run."""
        return {
            "source": {s.key: s.id for s in self.sources.values()},
            "proposition": {p.fingerprint: p.id for p in self.propositions.values()},
        }

    def dumps(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=1, sort_keys=False)
