"""End-to-end analysis pipeline (see docs/SYSTEM_ARCHITECTURE.md §2).

ingest → register sources/passages → extract propositions → link (definitions,
attribution, compound, causal, derivations) → compare/contradict → evidence →
deterministic checks → assess → rank/compress → diff against previous run.
"""
from __future__ import annotations

import re
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from . import checks as C
from .contradiction import Comparison, compare_all, family, same_source
from .evidence import assess, logical_evidence, make_evidence, upgrade_contradiction_findings
from .extract import EXTRACTOR_ID, PRONOUNS, Draft, extract_passage_text
from .graph import IdAllocator, KnowledgeGraph
from .models import (Attribution, ClaimType, Derivation, EvidenceBasis, Extraction, FindingClass,
                     Issue, IssueCategory, Modality, Polarity, Proposition, Quantity,
                     RelationType, ReviewStatus, Scope, Severity, Stance)
from .providers import NullProvider, Provider
from .registry import register_documents
from .textutil import content_set, jaccard, norm_ws, normalize_phrase, short_hash

DEFAULT_CONFIG = {
    "ranking": {"relevance": 1.0, "evidence_quality": 1.0, "novelty": 0.5, "connectivity": 0.75,
                "contradiction": 1.5, "uncertainty_reduction": 0.75, "redundancy_penalty": 1.0},
    "query": None,
    "max_core": 25,
}


# ---------------------------------------------------------------------- formatting

def formula(p: Proposition) -> str:
    """Compact, mathematically inspired rendering of a proposition."""
    if p.claim_type == ClaimType.COMPOUND:
        return "∧(" + ", ".join(p.components) + ")"
    neg = "¬" if p.polarity == Polarity.NEGATIVE else ""
    mod = {Modality.POSSIBLE: "◇", Modality.PROBABLE: "◇≈", Modality.PREDICTED: "F",
           Modality.NECESSARY: "□", Modality.QUESTIONED: "?"}.get(p.modality, "")
    args = p.subject if p.object is None else f"{p.subject}, {p.object}"
    s = f"{mod}{neg}{p.predicate}({args})"
    if p.quantity is not None:
        q = p.quantity
        if q.kind == "from_to":
            s += f" : {q.raw}"
        elif q.kind in ("change", "change_pp"):
            sign = "+" if p.direction > 0 else "−" if p.direction < 0 else "Δ"
            s += f" = {sign}{q.raw}"
        elif q.kind != "year":
            s += f" = {q.raw}"
    scope = []
    if p.scope.time:
        scope.append(f"t={p.scope.time}")
    if p.scope.location:
        scope.append(f"loc={p.scope.location}")
    if p.scope.population:
        scope.append(f"pop={p.scope.population}")
    for c in p.scope.conditions:
        scope.append(f"cond={c}")
    if p.quantifier:
        scope.append(f"Q={p.quantifier}")
    if scope:
        s += " | " + "; ".join(scope)
    if p.attribution.kind != "author" and p.attribution.speaker:
        s = f"{p.attribution.speaker} ⊢ {s}"
    if p.claim_type in (ClaimType.OPINION, ClaimType.NORMATIVE):
        s = f"[{p.claim_type.value}] {s}"
    return s


# ---------------------------------------------------------------------- pipeline

class Analysis:
    def __init__(self, config: Optional[dict] = None, provider: Optional[Provider] = None,
                 previous: Optional[dict] = None, now: Optional[str] = None):
        self.config = {**DEFAULT_CONFIG, **(config or {})}
        self.provider = provider or NullProvider()
        self.previous = previous
        self.now = now or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        prev_map = (previous or {}).get("id_map") or {}
        self.g = KnowledgeGraph(IdAllocator(prev_map))
        self.drafts: dict[str, Draft] = {}
        self.unresolved_pronoun: set[str] = set()
        self.review: dict[str, list[str]] = defaultdict(list)
        self.confirmed_error: set[str] = set()
        self.dependent_extra: dict[str, int] = defaultdict(int)
        self.timings: dict[str, float] = {}

    # -------------------------------------------------------------- helpers
    def _tick(self, name: str, t0: float) -> float:
        t = time.perf_counter()
        self.timings[name] = round(t - t0, 4)
        return t

    def _issue(self, d: C.IssueDraft) -> Issue:
        fps = sorted(self.g.fingerprints.get(a, a) for a in d.affected)
        fp = f"{d.category.value}|{'|'.join(fps)}|{d.details.get('key', '')}"
        for existing in self.g.issues.values():
            if self.g.fingerprints.get(existing.id) == fp:
                return existing
        iid = self.g.ids.allocate("issue", fp)
        self.g.fingerprints[iid] = fp
        issue = Issue(id=iid, category=d.category, finding_class=d.finding_class, severity=d.severity,
                      confidence=round(d.confidence, 2), affected=list(dict.fromkeys(d.affected)),
                      conflicting=list(dict.fromkeys(d.conflicting)), reason=d.reason,
                      evidence=list(dict.fromkeys(d.evidence)), resolution=d.resolution,
                      dimensions=d.dimensions, assumptions=d.assumptions, detector=d.detector,
                      deterministic=d.deterministic, details=d.details)
        return self.g.add_issue(issue)

    def _rel(self, rtype: RelationType, a: str, b: str, **kw):
        g = self.g
        rel = g.add_relation(rtype, a, b, **kw)
        pa, pb = g.propositions[rel.source], g.propositions[rel.target]
        g.fingerprints[rel.id] = f"{rtype.value}|{pa.fingerprint}|{pb.fingerprint}"
        return rel

    # -------------------------------------------------------------- run
    def run(self, docs: list[dict]) -> KnowledgeGraph:
        t0 = time.perf_counter()
        g = self.g
        register_documents(g, docs, retrieved_at=self.now)
        for p in g.passages.values():
            g.fingerprints[p.id] = f"{g.sources[p.source_id].key}|{p.paragraph_index}|{short_hash(p.text)}"
        t0 = self._tick("register", t0)
        self.extract_all()
        t0 = self._tick("extract", t0)
        self.link_definitions()
        self.link_attribution()
        props = [p for p in g.propositions.values() if p.claim_type != ClaimType.COMPOUND]
        comps = compare_all(g, props)
        self.apply_comparisons(comps)
        self.correlational_evidence(props)
        t0 = self._tick("compare", t0)
        self.check_arithmetic()
        self.check_quotations()
        self.subsume_misquote_conflicts()
        self.check_translations()
        self.check_inferences()
        self.check_causal()
        self.check_dependence()
        self.check_reworded_copies()
        self.check_retractions()
        self.check_ambiguity()
        self.check_sources()
        t0 = self._tick("checks", t0)
        self.assess_all()
        upgrade_contradiction_findings(g)
        t0 = self._tick("assess", t0)
        from .rank import rank_and_compress
        rank_and_compress(g, self.config)
        t0 = self._tick("rank", t0)
        errs = g.validate()
        if errs:
            g.limitations.extend(f"integrity: {e}" for e in errs)
        g.model_calls = getattr(self.provider, "calls", 0)
        return g

    # -------------------------------------------------------------- extraction
    def extract_all(self) -> None:
        g = self.g
        translated = {s.translation_of: s.id for s in g.sources.values() if s.translation_of}
        unextracted = defaultdict(int)
        for src in sorted(g.sources.values(), key=lambda s: s.id):
            if src.access_status != "accessible":
                continue
            orig_map = self._translation_map(src) if src.translation_of else {}
            for pas in sorted((p for p in g.passages.values() if p.source_id == src.id),
                              key=lambda p: p.char_start):
                lang = pas.language if pas.language != "und" else src.language
                if lang in ("en", "und") or (src.language == "en" and pas.language_confidence < 0.3):
                    drafts = extract_passage_text(pas.text, src.basis)
                    self._materialise(src, pas, drafts, orig_map, model=False)
                elif src.id in translated:
                    continue  # analysed through its translation
                else:
                    model_drafts = self.provider.extract(pas.text, lang)
                    if model_drafts is None:
                        unextracted[(src.id, lang)] += 1
                        continue
                    self._materialise(src, pas, self._model_drafts(pas.text, model_drafts), {},
                                      model=True)
        for (sid, lang), n in sorted(unextracted.items()):
            g.limitations.append(f"Source {sid}: {n} passage(s) in '{lang}' not extracted — no offline "
                                 f"extractor for this language and no translation in corpus "
                                 f"(enable a model provider).")

    def _translation_map(self, src) -> dict[str, str]:
        g = self.g
        orig = C.doc_sentences(g.archive[src.translation_of])
        trans = C.doc_sentences(g.archive[src.id])
        return {norm_ws(trans[j]): orig[i] for i, j in C.align_sentences(orig, trans)
                if i < len(orig) and j < len(trans)}

    def _model_drafts(self, text: str, items: list[dict]) -> list[Draft]:
        out = []
        for i, it in enumerate(items):
            sent = it.get("sentence") or ""
            start = text.find(sent) if sent else -1
            span = (start, start + len(sent)) if start >= 0 else (0, 0)
            scope = Scope(time=it.get("time"), location=it.get("location"),
                          population=it.get("population"), conditions=list(it.get("conditions") or []))
            try:
                ct = ClaimType(it.get("claim_type", "empirical"))
            except ValueError:
                ct = ClaimType.EMPIRICAL
            out.append(Draft(subject=normalize_phrase(it.get("english_gloss") and it["subject"] or it["subject"]),
                             predicate=it.get("predicate", "asserts"), object=it.get("object"),
                             claim_type=ct, modality=Modality.POSSIBLE if it.get("hedged") else Modality.ASSERTED,
                             polarity=Polarity.NEGATIVE if it.get("negated") else Polarity.POSITIVE,
                             scope=scope, quote=sent if start >= 0 else "", quote_span=span,
                             sentence_index=i, clause=it.get("english_gloss", ""), confidence=0.6,
                             method="model-extract", notes=["model extraction: unverified"]))
        return out

    def _materialise(self, src, pas, drafts: list[Draft], orig_map: dict, model: bool) -> None:
        g = self.g
        by_sentence: dict[int, list[Proposition]] = defaultdict(list)
        sentence_drafts: dict[int, list[Draft]] = defaultdict(list)
        last_subject: Optional[str] = None
        last_subjects_prev_sentence: set[str] = set()
        current_sentence = -1
        current_subjects: set[str] = set()
        for d in drafts:
            if d.sentence_index != current_sentence:
                last_subjects_prev_sentence = current_subjects or last_subjects_prev_sentence
                current_subjects = set()
                current_sentence = d.sentence_index
            fp = short_hash(src.key, str(pas.paragraph_index), str(d.sentence_index), d.clause,
                            d.subject, d.predicate, d.object or "", d.polarity.value)
            pid = g.ids.allocate("proposition", fp)
            notes = list(d.notes)
            subj = d.subject
            conf = d.confidence
            head = (d.surface.get("subject") or "").strip()
            bare_def = re.fullmatch(r"(?i:the)\s+([a-z][\w-]*)", head)
            if bare_def and d.sentence_index > 0:
                # "The treaty ..." after "The Treaty of Kessmark ..." (bare definite description)
                noun = bare_def.group(1).lower()
                ante = next((q.subject for q in reversed(list(g.props_of_source(src.id)))
                             if q.passage_id == pas.id and noun in q.subject.split() and q.subject != noun), None)
                if ante:
                    notes.append(f"definite description '{head}' resolved to '{ante}' (heuristic)")
                    subj = ante
                    conf = round(conf - 0.05, 2)
            if subj in PRONOUNS or (subj.split(" ")[0] in ("it", "they", "this", "these", "he", "she")
                                    and len(subj.split()) <= 2):
                if last_subject and len(last_subjects_prev_sentence) <= 1:
                    notes.append(f"pronoun '{subj}' resolved to '{last_subject}' (heuristic)")
                    subj = last_subject
                else:
                    self.unresolved_pronoun.add(pid)
                    notes.append(f"pronoun '{subj}' unresolved")
            quote = d.quote
            span = list(d.quote_span) if quote else None
            prop = Proposition(
                id=pid, fingerprint=fp, text="", subject=subj, predicate=d.predicate, object=d.object,
                claim_type=d.claim_type, surface=d.surface, modality=d.modality, polarity=d.polarity,
                direction=d.direction, quantity=d.quantity, quantifier=d.quantifier, scope=d.scope,
                attribution=d.attribution, source_refs=[src.id], passage_id=pas.id, quote=quote,
                quote_span=span, language="en" if not model else pas.language,
                original_text=orig_map.get(norm_ws(quote)) if orig_map else None,
                stated_basis=d.stated_basis,
                extraction=Extraction(method=("model:" + self.provider.name) if model
                                      else f"{EXTRACTOR_ID}/{d.method}",
                                      confidence=conf, review_required=conf < 0.5 or model,
                                      notes=notes, deterministic=not model),
                created_at=self.now,
            )
            if src.metadata.get("ocr"):
                prop.extraction.confidence = round(prop.extraction.confidence * 0.8, 2)
                prop.extraction.notes.append("OCR source: text may contain recognition errors")
            if model:
                self.review[pid].append("proposition extracted by a language model (unverified)")
            prop.text = formula(prop)
            g.add_proposition(prop)
            g.fingerprints[pid] = fp
            self.drafts[pid] = d
            by_sentence[d.sentence_index].append(prop)
            sentence_drafts[d.sentence_index].append(d)
            if subj not in PRONOUNS:
                last_subject = subj
                current_subjects.add(subj)
        # intra-sentence structure: causes, qualifications, compounds, derivations
        ordered = sorted(by_sentence)
        for si in ordered:
            props, ds = by_sentence[si], sentence_drafts[si]
            for p, d in zip(props, ds):
                if d.caused_by is not None:
                    cause = next((q for q, dd in zip(props, ds) if dd.group == d.caused_by), None)
                    if cause is not None and cause.id != p.id:
                        self._rel(RelationType.CAUSES, cause.id, p.id,
                                  rationale="Source states a causal link ('because').",
                                  evidence_refs=[pas.id], confidence=0.6,
                                  review_status=ReviewStatus.ASSERTED_BY_SOURCE, method="rule:because@1")
                if d.qualifies_previous:
                    prev = [q for q, dd in zip(props, ds) if dd.group < d.group]
                    if prev:
                        self._rel(RelationType.QUALIFIES, p.id, prev[-1].id,
                                  rationale="Contrastive clause ('but/however') qualifies the preceding claim.",
                                  evidence_refs=[pas.id], confidence=0.6,
                                  review_status=ReviewStatus.ASSERTED_BY_SOURCE, method="rule:but@1")
            plain = [p for p, d in zip(props, ds) if d.caused_by is None and not d.inference_marker]
            if len(plain) >= 2 and not any(d.inference_marker for d in ds):
                fp = short_hash("compound", *[p.fingerprint for p in plain])
                cid = g.ids.allocate("proposition", fp)
                comp = Proposition(
                    id=cid, fingerprint=fp, text="", subject="", predicate="and", object=None,
                    claim_type=ClaimType.COMPOUND, components=[p.id for p in plain],
                    source_refs=[src.id], passage_id=pas.id, quote=plain[0].quote,
                    quote_span=plain[0].quote_span,
                    extraction=Extraction(method=f"{EXTRACTOR_ID}/compound", confidence=min(p.extraction.confidence for p in plain)),
                    created_at=self.now)
                comp.text = formula(comp)
                g.add_proposition(comp)
                g.fingerprints[cid] = fp
                for p in plain:
                    p.parent_id = cid
            for p, d in zip(props, ds):
                if not d.inference_marker:
                    continue
                inline = [q for q, dd in zip(props, ds) if not dd.inference_marker and q.id != p.id]
                if inline:
                    premises = inline
                else:
                    earlier = [s for s in ordered if s < si][-2:]
                    premises = [q for s in earlier for q in by_sentence[s] if q.claim_type != ClaimType.COMPOUND]
                if not premises:
                    continue
                did = g.ids.allocate("derivation", "deriv|" + p.fingerprint)
                g.fingerprints[did] = "deriv|" + p.fingerprint
                g.add_derivation(Derivation(id=did, conclusion=p.id, premises=[q.id for q in premises],
                                            marker=d.inference_marker))
                for q in premises:
                    self._rel(RelationType.DERIVED_FROM, p.id, q.id,
                              rationale=f"Source presents this as a conclusion ('{d.inference_marker}').",
                              evidence_refs=[pas.id], confidence=0.7,
                              review_status=ReviewStatus.ASSERTED_BY_SOURCE, method="rule:inference-marker@1")

    # -------------------------------------------------------------- linking
    def link_definitions(self) -> None:
        g = self.g
        defs: dict[str, dict[str, str]] = defaultdict(dict)   # source -> term -> prop id
        for p in g.propositions.values():
            if p.claim_type == ClaimType.DEFINITION:
                defs[p.source_refs[0]][p.subject] = p.id
        for p in g.propositions.values():
            if p.claim_type == ClaimType.DEFINITION:
                continue
            for term, did in defs.get(p.source_refs[0], {}).items():
                ts = content_set(term)
                if ts and ts <= content_set(p.subject + " " + (p.object or "")):
                    p.scope.definitions[term] = did
                    p.text = formula(p)

    def link_attribution(self) -> None:
        g = self.g
        for p in g.propositions.values():
            sp = p.attribution.speaker
            if not sp:
                continue
            for s in g.sources.values():
                if s.id in p.source_refs:
                    continue
                if C.speaker_matches(sp, s.author, s.publisher):
                    p.attribution.origin_source_id = s.id
                    break

    # -------------------------------------------------------------- comparisons
    def apply_comparisons(self, comps: list[Comparison]) -> None:
        """Pass 1 records compatible relations and builds equivalence classes
        (DUPLICATES); pass 2 records conflicts, so that a claim contradicting
        several copies of the same statement yields one issue, not one per copy."""
        g = self.g
        parent: dict[str, str] = {}

        def find(x: str) -> str:
            parent.setdefault(x, x)
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        self._class = find
        self._conflict_issues: dict[tuple, str] = {}
        for c in comps:
            if c.compatible is False:
                continue
            a, b = g.propositions[c.a], g.propositions[c.b]
            evidence = [x for x in (a.passage_id, b.passage_id) if x]
            if c.equivalent:
                ra, rb = find(a.id), find(b.id)
                if ra != rb:
                    parent[max(ra, rb)] = min(ra, rb)
                self._rel(RelationType.DUPLICATES, a.id, b.id,
                          rationale="Same entities, predicate, polarity, value and scope.",
                          evidence_refs=evidence, confidence=c.confidence, method="rule:equivalence@1",
                          assumptions=c.assumptions)
                if not same_source(a, b):
                    make_evidence(g, a, b, Stance.SUPPORTS, "direct", "rel:DUPLICATES")
                    make_evidence(g, b, a, Stance.SUPPORTS, "direct", "rel:DUPLICATES")
            elif c.entails:
                strong = a if c.entails == a.id else b
                weak = b if strong is a else a
                self._rel(RelationType.ENTAILS, strong.id, weak.id,
                          rationale="The quantified claim implies the unquantified claim (same scope).",
                          evidence_refs=evidence, confidence=c.confidence, method="rule:entailment@1")
                if not same_source(a, b):
                    make_evidence(g, weak, strong, Stance.SUPPORTS, "direct", "rel:ENTAILS")
            elif c.refines:
                spec = a if c.refines == a.id else b
                gen = b if spec is a else a
                self._rel(RelationType.REFINES, spec.id, gen.id,
                          rationale="Same claim with additional scope restrictions ("
                                    + ", ".join(c.unspecified) + ").",
                          evidence_refs=evidence, confidence=c.confidence, method="rule:refinement@1",
                          dimensions=c.unspecified)
                if not same_source(a, b):
                    make_evidence(g, gen, spec, Stance.SUPPORTS, "indirect", "rel:REFINES")
        for c in comps:
            if c.compatible is not False:
                continue
            a, b = g.propositions[c.a], g.propositions[c.b]
            src_a, src_b = g.sources[a.source_refs[0]], g.sources[b.source_refs[0]]
            evidence = [x for x in (a.passage_id, b.passage_id) if x]
            corrects = self._corrects(a, b)
            if corrects:
                new, old = corrects
                self._rel(RelationType.CORRECTS, new.id, old.id,
                          rationale=f"{g.sources[new.source_refs[0]].id} is a declared correction of "
                                    f"{g.sources[old.source_refs[0]].id}; conflicting claim superseded.",
                          evidence_refs=evidence, confidence=0.9, method="rule:declared-correction@1",
                          dimensions=c.conflict_dims)
                old.superseded_by, new.supersedes = new.id, old.id
                new.version = old.version + 1
                continue
            if c.conflict_dims == ["definition"]:
                self._rel(RelationType.DIFFERS_IN_SCOPE, a.id, b.id, rationale=
                          "The term is defined differently; claims using it may not be comparable.",
                          evidence_refs=evidence, confidence=c.confidence or 0.7,
                          method="rule:definition-compare@1", dimensions=["definition"])
                self._issue(C.IssueDraft(
                    category=IssueCategory.DEFINITION_CONFLICT, finding_class=FindingClass.SUSPICIOUS_CLAIM,
                    severity=Severity.LOW, confidence=0.7, affected=[a.id, b.id],
                    reason=f"'{a.subject}' is defined as '{a.object}' in {src_a.id} but as "
                           f"'{b.object}' in {src_b.id}.",
                    resolution="Use one definition when comparing figures that depend on this term, "
                               "or report them separately.",
                    evidence=evidence, detector="rule:definition-compare@1", dimensions=["definition"]))
                continue
            if c.classification == "APPARENT":
                self._rel(RelationType.DIFFERS_IN_SCOPE, a.id, b.id, rationale=c.rationale,
                          evidence_refs=evidence, confidence=c.confidence,
                          method="rule:scope-align@1", dimensions=c.differing,
                          assumptions=c.assumptions)
                continue
            review = ReviewStatus.AUTO_DETERMINISTIC if c.classification == "GENUINE" else ReviewStatus.NEEDS_REVIEW
            self._rel(RelationType.CONTRADICTS, a.id, b.id, rationale=c.rationale,
                      evidence_refs=evidence, confidence=c.confidence, review_status=review,
                      method="rule:contradiction@1", dimensions=c.conflict_dims,
                      assumptions=c.assumptions)
            self._contradiction_issue(a, b, c, evidence)
            if not same_source(a, b):
                direct = "direct" if c.classification == "GENUINE" else "indirect"
                make_evidence(g, a, b, Stance.CHALLENGES, direct, "rel:CONTRADICTS")
                make_evidence(g, b, a, Stance.CHALLENGES, direct, "rel:CONTRADICTS")

    def _corrects(self, a: Proposition, b: Proposition):
        g = self.g
        sa, sb = g.sources[a.source_refs[0]], g.sources[b.source_refs[0]]
        by_key = {s.key: s for s in g.sources.values()}

        def corrected(new, old) -> bool:
            target = by_key.get(new.metadata.get("corrects"))
            # a correction also applies to copies that reproduce the corrected document
            return target is not None and (target.id == old.id or
                                           target.independence_group == old.independence_group)
        if corrected(sa, sb):
            return a, b
        if corrected(sb, sa):
            return b, a
        return None

    def _contradiction_issue(self, a: Proposition, b: Proposition, c: Comparison, evidence: list) -> None:
        g = self.g
        dims = c.conflict_dims
        ca, cb = self._class(a.id), self._class(b.id)
        key = (c.classification, tuple(sorted((ca, cb))))
        if key in self._conflict_issues:
            issue = g.issues[self._conflict_issues[key]]
            sides = issue.details["sides"]
            for p, cls in ((a, ca), (b, cb)):
                side = sides[0] if cls == issue.details["side_classes"][0] else sides[1]
                if p.id not in side:
                    side.append(p.id)
                if p.id not in issue.affected:
                    issue.affected.append(p.id)
                    issue.conflicting.append(p.id)
                    p.issue_refs.append(issue.id)
            issue.evidence.extend(e for e in evidence if e not in issue.evidence)
            issue.details.setdefault("pairs", []).append([a.id, b.id])
            return
        before = set(g.issues)
        if c.classification == "UNRESOLVED":
            lacking = [p.id for p in (a, b) for d in c.unspecified if not getattr(p.scope, d)]
            self._issue(C.IssueDraft(
                category=IssueCategory.MISSING_CONDITION, finding_class=FindingClass.UNRESOLVED_CONTRADICTION,
                severity=Severity.MEDIUM, confidence=max(0.3, c.confidence - 0.15), affected=[a.id, b.id],
                conflicting=[a.id, b.id],
                reason=f"{a.id} [{a.text}] and {b.id} [{b.text}] conflict on {', '.join(dims)}, but "
                       f"{', '.join(c.unspecified)} is stated only for one of them. {c.rationale}",
                resolution=f"Determine the {', '.join(c.unspecified)} that "
                           f"{', '.join(sorted(set(lacking)))} refers to; if it matches the other "
                           "proposition, the contradiction is genuine, otherwise it is a scope difference.",
                evidence=evidence, detector="rule:contradiction@1", dimensions=dims + c.unspecified,
                assumptions=c.assumptions, details={"lacking_scope": sorted(set(lacking))}))
            self._register_conflict(key, before, a, b, ca, cb)
            return
        if same_source(a, b):
            cat = IssueCategory.INTERNAL_INCONSISTENCY
        elif "event_time" in dims:
            cat = IssueCategory.TEMPORAL_DISAGREEMENT
        elif "value" in dims or "magnitude" in dims:
            cat = IssueCategory.NUMERICAL_INCONSISTENCY
        else:
            cat = IssueCategory.CATEGORICAL_CONFLICT
        sev = Severity.MEDIUM if dims == ["magnitude"] else Severity.HIGH
        self._issue(C.IssueDraft(
            category=cat, finding_class=FindingClass.UNRESOLVED_CONTRADICTION, severity=sev,
            confidence=c.confidence, affected=[a.id, b.id], conflicting=[a.id, b.id],
            reason=f"{a.id} [{a.text}] vs {b.id} [{b.text}]: {c.rationale}",
            resolution="Consult primary evidence (original data, measurement protocol) for "
                       f"'{a.subject}' under the shared scope; check definitions and measurement "
                       "methods. Neither side is discarded.",
            evidence=evidence, detector="rule:contradiction@1", dimensions=dims,
            assumptions=c.assumptions, details={"family": c.family}))
        self._register_conflict(key, before, a, b, ca, cb)

    def _register_conflict(self, key, before, a, b, ca, cb) -> None:
        new = [i for i in self.g.issues if i not in before]
        if new:
            issue = self.g.issues[new[0]]
            issue.details["sides"] = [[a.id], [b.id]]
            issue.details["side_classes"] = [ca, cb]
            issue.details["pairs"] = [[a.id, b.id]]
            self._conflict_issues[key] = issue.id

    def correlational_evidence(self, props: list[Proposition]) -> None:
        """Correlational propositions are indirect, weak evidence for causal claims on
        the same pair of variables (never direct support)."""
        g = self.g
        corr = [p for p in props if p.claim_type == ClaimType.CORRELATIONAL and p.polarity == Polarity.POSITIVE]
        causal = [p for p in props if p.claim_type == ClaimType.CAUSAL and p.polarity == Polarity.POSITIVE]
        for c in causal:
            for q in corr:
                if same_source(c, q):
                    continue
                if jaccard(content_set(c.subject), content_set(q.subject)) >= 0.5 and \
                        jaccard(content_set(c.object or ""), content_set(q.object or "")) >= 0.3:
                    make_evidence(g, c, q, Stance.SUPPORTS, "indirect", "rel:correlation-for-causation",
                                  correlational=True)

    # -------------------------------------------------------------- checks
    def _sentence_props(self) -> dict[tuple, list[Proposition]]:
        out: dict[tuple, list[Proposition]] = defaultdict(list)
        for p in self.g.propositions.values():
            if p.claim_type != ClaimType.COMPOUND and p.passage_id:
                out[(p.passage_id, p.quote)].append(p)
        return out

    def check_arithmetic(self) -> None:
        g = self.g
        # one issue per (independence group, computation): copies of the same faulty
        # sentence are reported once, with every copy listed as affected
        found: dict[tuple, dict] = {}
        for (pas_id, quote), props in sorted(self._sentence_props().items()):
            grp = g.sources[g.passages[pas_id].source_id].independence_group
            for f in C.check_arithmetic(quote):
                k = (grp, norm_ws(f["span"]).lower())
                entry = found.setdefault(k, {"f": f, "affected": [], "evidence": []})
                entry["affected"].extend(p.id for p in props)
                entry["evidence"].append(pas_id)
        for (grp, span), entry in found.items():
            f = entry["f"]
            for pid in entry["affected"]:
                self.review[pid].append("source sentence contains an arithmetic inconsistency")
            copies = len(set(entry["evidence"]))
            self._issue(C.IssueDraft(
                category=IssueCategory.ARITHMETIC_ERROR, finding_class=FindingClass.CONFIRMED_ERROR,
                severity=Severity.HIGH, confidence=0.95, affected=entry["affected"],
                reason=f"In “{f['span']}”: " + "; ".join(f["problems"]) + "."
                       + (f" Repeated in {copies} passages sharing origin {grp}." if copies > 1 else ""),
                resolution="Check the original figures; at least one of the stated numbers is wrong. "
                           "The computation is deterministic, the faulty number is not identified.",
                evidence=entry["evidence"], detector=f"rule:arithmetic-{f['kind']}@1",
                details={"stated": f["stated"], "computed": f["computed"], "key": span}))
        for p in list(g.propositions.values()):
            f = C.check_math(p)
            if f:
                self.confirmed_error.add(p.id)
                ev = logical_evidence(g, p, "math-eval@1")
                self._issue(C.IssueDraft(
                    category=IssueCategory.ARITHMETIC_ERROR, finding_class=FindingClass.CONFIRMED_ERROR,
                    severity=Severity.HIGH, confidence=0.99, affected=[p.id],
                    reason="Equation is false: " + "; ".join(f["problems"]) + ".",
                    resolution="None needed for the arithmetic itself; check whether the source "
                               "intended different operands.",
                    evidence=[p.passage_id, ev.id], detector="rule:math-eval@1",
                    details={"stated": f["stated"], "computed": f["computed"]}))

    def check_quotations(self) -> None:
        g = self.g
        sentences_cache: dict[str, list[str]] = {}

        def sents(sid):
            if sid not in sentences_cache:
                sentences_cache[sid] = C.doc_sentences(g.archive.get(sid, ""))
            return sentences_cache[sid]

        seen: set[tuple] = set()
        for p in g.propositions.values():
            at = p.attribution
            if at.kind not in ("quoted", "reported") or not at.speaker:
                continue
            cands = [s for s in g.sources.values() if s.id not in p.source_refs
                     and C.speaker_matches(at.speaker, s.author, s.publisher)]
            here_id = p.source_refs[0]
            attributed_elsewhere = any(
                q.attribution.kind == "quoted" and q.source_refs[0] != here_id
                and not (here_id in g.sources[q.source_refs[0]].cites or g.sources[q.source_refs[0]].reproduces == here_id)
                and C.speaker_matches(at.speaker, q.attribution.speaker, None)
                for q in g.propositions.values())
            if not cands and not (at.kind == "quoted" and attributed_elsewhere):
                continue
            key = (p.passage_id, p.quote, at.speaker)
            if key in seen:
                continue
            seen.add(key)
            orig_sents = [x for s in cands for x in sents(s.id)]
            # statements attributed to the same speaker elsewhere are also originals
            # (a document that cites or reproduces this one is downstream, not an original)
            here = g.sources[p.source_refs[0]]

            def downstream(sid):
                o = g.sources[sid]
                return here.id in o.cites or o.reproduces == here.id or o.duplicate_of == here.id
            orig_sents += [q.attribution.quote for q in g.propositions.values()
                           if q.attribution.kind == "quoted" and q.attribution.quote
                           and q.source_refs[0] not in p.source_refs and not downstream(q.source_refs[0])
                           and C.speaker_matches(at.speaker, q.attribution.speaker, None)]
            siblings = [q.id for q in g.propositions.values()
                        if q.passage_id == p.passage_id and q.quote == p.quote and q.claim_type != ClaimType.COMPOUND]
            if at.kind == "quoted":
                res = C.compare_quote(at.quote or "", orig_sents)
                if res is None:
                    self._issue(C.IssueDraft(
                        category=IssueCategory.MISLEADING_QUOTATION, finding_class=FindingClass.MISSING_EVIDENCE,
                        severity=Severity.LOW, confidence=0.5, affected=siblings,
                        reason=f"Quotation attributed to {at.speaker} not found in their available "
                               f"document(s) or other attributed quotations "
                               f"({', '.join(s.id for s in cands) or 'quotations only'}).",
                        resolution="Locate the original statement (other document, transcript, recording).",
                        evidence=[p.passage_id], detector="rule:quote-verify@1"))
                    continue
                if res.get("verbatim") and not res.get("truncated"):
                    p.extraction.notes.append(f"quotation verified verbatim in {', '.join(s.id for s in cands)}")
                    continue
                if res.get("truncated"):
                    self._issue(C.IssueDraft(
                        category=IssueCategory.MISLEADING_QUOTATION, finding_class=FindingClass.PROBABLE_ERROR,
                        severity=Severity.HIGH, confidence=0.7, affected=siblings,
                        reason=f"Quotation is verbatim but omits qualifying context present in the "
                               f"original ({', '.join(res['dropped'])}): “{res['original']}”.",
                        resolution="Compare with the full original sentence; report the qualifier.",
                        evidence=[p.passage_id], detector="rule:quote-context@1",
                        details={"original": res["original"], "dropped": res["dropped"]}))
                    continue
                if res.get("changes"):
                    self._issue(C.IssueDraft(
                        category=IssueCategory.MISLEADING_QUOTATION, finding_class=FindingClass.PROBABLE_ERROR,
                        severity=Severity.HIGH, confidence=0.8, affected=siblings,
                        reason=f"Quotation differs from the closest original statement "
                               f"(similarity {res['similarity']}): " + "; ".join(res["changes"])
                               + f". Original: “{res['original']}”.",
                        resolution="Check the original recording/transcript; if confirmed, the quotation "
                                   "misrepresents the speaker.",
                        evidence=[p.passage_id], detector="rule:quote-compare@1",
                        details={"original": res["original"], "changes": res["changes"]}))
                else:
                    self._issue(C.IssueDraft(
                        category=IssueCategory.MISLEADING_QUOTATION, finding_class=FindingClass.SUSPICIOUS_CLAIM,
                        severity=Severity.LOW, confidence=0.5, affected=siblings,
                        reason=f"Quotation is not verbatim (closest original: “{res['original']}”), "
                               "although no change in negation, modality or numbers was detected.",
                        resolution="Quote verbatim or mark as paraphrase.",
                        evidence=[p.passage_id], detector="rule:quote-compare@1"))
            else:
                # reported speech: check that negation / modality / numbers survive the paraphrase
                clause = p.quote
                m = re.search(r"\bthat\s+(.+)$", clause) or re.search(r",\s*(.+)$", clause)
                content = m.group(1) if m else clause
                best, best_sim = None, 0.0
                for s in orig_sents:
                    sim = jaccard(content_set(content), content_set(s))
                    if sim > best_sim:
                        best, best_sim = s, sim
                if best is None or best_sim < 0.4:
                    continue
                changes = [ch for ch in C.meaning_changes("en", content, "en", best)
                           if not ch.startswith("numbers")]
                na, nb = set(C.numbers_in(content)), set(C.numbers_in(best))
                if na - nb and nb - na:
                    changes.append(f"numbers differ: {sorted(na - nb)} vs {sorted(nb - na)}")
                if changes:
                    self._issue(C.IssueDraft(
                        category=IssueCategory.MISLEADING_QUOTATION, finding_class=FindingClass.PROBABLE_ERROR,
                        severity=Severity.HIGH, confidence=0.7, affected=siblings,
                        reason=f"Reported statement attributed to {at.speaker} changes the original: "
                               + "; ".join(changes) + f". Original: “{best}”.",
                        resolution="Compare with the original statement and correct the attribution.",
                        evidence=[p.passage_id], detector="rule:reported-speech@1",
                        details={"original": best, "changes": changes}))

    def subsume_misquote_conflicts(self) -> None:
        """A contradiction between a misquotation and the quoted person's original
        statement has one root cause: the misquotation.  The CONTRADICTS relation is
        kept; the separate contradiction issue is folded into the quotation issue."""
        g = self.g
        contra = {IssueCategory.NUMERICAL_INCONSISTENCY, IssueCategory.CATEGORICAL_CONFLICT,
                  IssueCategory.TEMPORAL_DISAGREEMENT, IssueCategory.MISSING_CONDITION}
        quote_issues = [i for i in g.issues.values() if i.category == IssueCategory.MISLEADING_QUOTATION
                        and i.finding_class == FindingClass.PROBABLE_ERROR]
        for qi in quote_issues:
            quoted = set(qi.affected)
            origins = {g.propositions[x].attribution.origin_source_id for x in quoted}
            for issue in list(g.issues.values()):
                if issue.category not in contra or len(issue.affected) != 2:
                    continue
                x, y = issue.affected
                pair = [(x, y), (y, x)]
                if any(q in quoted and g.propositions[o].source_refs[0] in origins for q, o in pair):
                    qi.details.setdefault("subsumes", []).append(
                        {"category": issue.category.value, "between": [x, y]})
                    qi.conflicting = list(dict.fromkeys(qi.conflicting + [x, y]))
                    self.g.remove_issue(issue.id)

    def check_translations(self) -> None:
        g = self.g
        for t in g.sources.values():
            if not t.translation_of:
                continue
            o = g.sources[t.translation_of]
            orig = C.doc_sentences(g.archive[o.id])
            trans = C.doc_sentences(g.archive[t.id])
            lang_o = o.language or "und"
            lang_t = t.language or "en"
            for i, j in C.align_sentences(orig, trans):
                if i >= len(orig) or j >= len(trans):
                    continue
                changes = C.meaning_changes(lang_o, orig[i], lang_t, trans[j])
                if not changes:
                    continue
                affected = [p.id for p in g.propositions.values()
                            if p.source_refs[0] == t.id and norm_ws(p.quote) == norm_ws(trans[j])
                            and p.claim_type != ClaimType.COMPOUND] or [t.id]
                for pid in affected:
                    if pid in g.propositions:
                        self.review[pid].append("translation may not preserve the original meaning")
                numeric = any(c.startswith("numbers") for c in changes)
                self._issue(C.IssueDraft(
                    category=IssueCategory.TRANSLATION_DISCREPANCY, finding_class=FindingClass.PROBABLE_ERROR,
                    severity=Severity.HIGH, confidence=0.85 if numeric else 0.75, affected=affected,
                    reason=f"Translation {t.id} sentence “{trans[j]}” vs original {o.id} ({lang_o}) "
                           f"“{orig[i]}”: " + "; ".join(changes) + ".",
                    resolution="Have the sentence re-translated or checked by a fluent reader; prefer the "
                               "original-language source.",
                    evidence=[o.id, t.id], detector="rule:translation-cues@1",
                    details={"original": orig[i], "translation": trans[j], "key": trans[j]}))

    def check_inferences(self) -> None:
        g = self.g
        for d in g.derivations.values():
            concl = g.propositions[d.conclusion]
            prem = [g.propositions[x] for x in d.premises]
            problems = C.inference_problems(concl, prem)
            if not problems:
                rels = {r.type for r in g.relations_of(concl.id)
                        if g.other(r, concl.id) in d.premises}
                d.validity = "valid" if rels & {RelationType.DUPLICATES, RelationType.ENTAILS} else "unknown"
                d.checks = ["no deterministic invalidity pattern found"]
                continue
            d.validity = "invalid"
            d.checks = [pr["type"] for pr in problems]
            for pr in problems:
                causal = pr["type"] == "correlation_to_causation"
                self._issue(C.IssueDraft(
                    category=pr["category"], finding_class=FindingClass.PROBABLE_ERROR,
                    severity=Severity.HIGH, confidence=0.75 if causal else 0.7,
                    affected=[concl.id], conflicting=pr["premises"],
                    reason=f"Conclusion {concl.id} [{concl.text}] marked '{d.marker}': {pr['reason']}",
                    resolution=("Evidence from a randomised or otherwise causally identified design, or "
                                "an explicit argument ruling out confounding.") if causal else
                               ("Evidence that the result holds beyond the premise's scope, or restate the "
                                "conclusion with the premise's restrictions."),
                    evidence=[concl.passage_id] + [g.propositions[x].passage_id for x in pr["premises"]],
                    detector=f"rule:inference-{pr['type']}@1", details={"derivation": d.id}))

    def check_causal(self) -> None:
        g = self.g
        flagged = {a for i in g.issues.values() if i.category == IssueCategory.UNSUPPORTED_CAUSAL_CLAIM
                   for a in i.affected}
        for p in g.propositions.values():
            if p.claim_type != ClaimType.CAUSAL or p.polarity != Polarity.POSITIVE or p.id in flagged:
                continue
            if p.modality in (Modality.POSSIBLE, Modality.PREDICTED, Modality.QUESTIONED):
                continue
            basis = p.stated_basis
            if basis not in (EvidenceBasis.OBSERVATIONAL, EvidenceBasis.SURVEY):
                continue
            ev = [g.evidence[e] for e in p.evidence_refs]
            if any(e.basis in (EvidenceBasis.EXPERIMENTAL, EvidenceBasis.REVIEW) and e.stance == Stance.SUPPORTS
                   for e in ev):
                continue
            self._issue(C.IssueDraft(
                category=IssueCategory.UNSUPPORTED_CAUSAL_CLAIM, finding_class=FindingClass.SUSPICIOUS_CLAIM,
                severity=Severity.MEDIUM, confidence=0.6, affected=[p.id],
                reason=f"Causal claim [{p.text}] is presented with a {basis.value} basis, which cannot by "
                       "itself establish causation; no experimental evidence was found in the corpus.",
                resolution="Randomised/controlled evidence, or a causal-identification argument.",
                evidence=[p.passage_id], detector="rule:causal-basis@1"))

    def check_dependence(self) -> None:
        g = self.g
        adj: dict[str, set[str]] = defaultdict(set)
        for r in g.relations.values():
            if r.type in (RelationType.DUPLICATES, RelationType.ENTAILS):
                adj[r.source].add(r.target)
                adj[r.target].add(r.source)
        seen: set[str] = set()
        self._dep_clusters: dict[str, list] = defaultdict(list)
        for start in sorted(adj):
            if start in seen:
                continue
            comp, stack = [], [start]
            while stack:
                x = stack.pop()
                if x in seen:
                    continue
                seen.add(x)
                comp.append(x)
                stack.extend(adj[x] - seen)
            groups: dict[str, set[str]] = defaultdict(set)
            for pid in comp:
                src = g.sources[g.propositions[pid].source_refs[0]]
                groups[src.independence_group].add(src.id)
            dup_groups = {gid: s for gid, s in groups.items() if len(s) >= 2}
            if not dup_groups:
                continue
            if any(g.sources[sid].retracted for members in dup_groups.values() for sid in members):
                continue  # reported as RETRACTED_SOURCE_DEPENDENCY instead
            for gid, members in dup_groups.items():
                self._dep_clusters[gid].append({"props": sorted(pid for pid in comp if g.sources[
                    g.propositions[pid].source_refs[0]].independence_group == gid),
                    "sources": sorted(members), "independent_origins": len(groups),
                    "method": "rule:independence@1"})

    def check_reworded_copies(self) -> None:
        """Copies are often reworded, so DUPLICATES alignment misses them.  Within an
        independence group, two sentences from different sources that share a
        non-year number *and* at least two content words are treated as the same
        reported claim (anchor heuristic); the copy is DERIVED_FROM the origin."""
        g = self.g
        by_group: dict[str, list] = defaultdict(list)
        for (pas_id, quote), props in self._sentence_props().items():
            src = g.sources[g.passages[pas_id].source_id]
            by_group[src.independence_group].append((src, quote, props))
        covered = {pid for cl in self._dep_clusters.values() for c in cl for pid in c["props"]}
        for grp, items in sorted(by_group.items()):
            if len({s.id for s, _, _ in items}) < 2:
                continue
            parent: dict[int, int] = {}

            def find(x):
                parent.setdefault(x, x)
                while parent[x] != x:
                    x = parent[x]
                return x
            anchors = []
            for s, quote, props in items:
                nums = {n for n in C.numbers_in(quote) if not (1900 <= n <= 2100 and float(n).is_integer())}
                anchors.append((nums, content_set(quote)))
            for i in range(len(items)):
                for j in range(i + 1, len(items)):
                    si, sj = items[i][0], items[j][0]
                    if si.id == sj.id:
                        continue
                    (ni, ci), (nj, cj) = anchors[i], anchors[j]
                    if ni & nj and len(ci & cj) >= 2 + len(ni & nj):
                        parent[find(i)] = find(j)
                        origin, copy = (i, j) if si.id < sj.id else (j, i)
                        if items[copy][0].reproduces or items[copy][0].duplicate_of or items[copy][0].cites:
                            for pc in items[copy][2]:
                                for po in items[origin][2][:1]:
                                    self._rel(RelationType.DERIVED_FROM, pc.id, po.id,
                                              rationale=f"{items[copy][0].id} reproduces {items[origin][0].id}; "
                                                        "reworded sentence anchored by shared numbers and terms.",
                                              evidence_refs=[pc.passage_id, po.passage_id], confidence=0.6,
                                              review_status=ReviewStatus.NEEDS_REVIEW,
                                              method="rule:reworded-copy@1")
            comps: dict[int, list[int]] = defaultdict(list)
            for k in parent:
                comps[find(k)].append(k)
            for members in comps.values():
                srcs = sorted({items[k][0].id for k in members})
                pids = sorted({p.id for k in members for p in items[k][2]})
                if len(srcs) < 2 or set(pids) <= covered:
                    continue
                if any(g.sources[x].retracted for x in srcs):
                    continue
                for pid in pids:
                    self.dependent_extra[pid] += len(srcs) - 1
                self._dep_clusters[grp].append({"props": pids, "sources": srcs, "independent_origins": 1,
                                                "method": "rule:reworded-copy@1"})
        self._emit_dependency_issues()

    def _emit_dependency_issues(self) -> None:
        """One DEPENDENT_CORROBORATION issue per independence group, listing every
        claim that the group's sources repeat (compact; nothing is counted twice)."""
        g = self.g
        for grp, clusters in sorted(self._dep_clusters.items()):
            pids = sorted({p for c in clusters for p in c["props"]})
            srcs = sorted({s for c in clusters for s in c["sources"]})
            if len(srcs) < 2:
                continue
            claims = "; ".join(f"[{g.propositions[c['props'][0]].text}] ×{len(c['sources'])}" for c in clusters)
            others = max(c["independent_origins"] for c in clusters) - 1
            self._issue(C.IssueDraft(
                category=IssueCategory.DEPENDENT_CORROBORATION, finding_class=FindingClass.MISSING_EVIDENCE,
                severity=Severity.LOW, confidence=0.8 if all(c["method"] == "rule:independence@1" for c in clusters) else 0.7,
                affected=pids,
                reason=f"Sources {', '.join(srcs)} share origin {grp}; {len(clusters)} claim(s) they repeat are "
                       f"counted once: {claims}."
                       + (f" {others} other independent origin(s) also state a matching claim." if others > 0 else
                          " No independent origin states these claims."),
                resolution="Find corroboration from a source that does not derive from the same origin.",
                evidence=srcs, detector=", ".join(sorted({c["method"] for c in clusters})),
                details={"clusters": clusters, "key": grp}))

    def check_retractions(self) -> None:
        g = self.g
        retracted = {s.id for s in g.sources.values() if s.retracted}
        if not retracted:
            return
        for s in g.sources.values():
            if s.retracted:
                continue
            deps = retracted & ({s.reproduces, s.translation_of, s.duplicate_of} | set(s.cites))
            if not deps:
                continue
            rprops = [p for p in g.propositions.values() if p.source_refs[0] in deps]
            rsubj = set().union(*[content_set(p.subject + " " + (p.object or "")) for p in rprops]) if rprops else set()
            for p in g.props_of_source(s.id):
                if p.claim_type == ClaimType.COMPOUND:
                    continue
                linked = any(g.other(r, p.id) in {q.id for q in rprops} for r in g.relations_of(p.id))
                shared = {t for t in content_set(p.subject + " " + (p.object or "")) & rsubj if len(t) >= 4}
                if not linked and not shared:
                    continue
                self._issue(C.IssueDraft(
                    category=IssueCategory.RETRACTED_SOURCE_DEPENDENCY, finding_class=FindingClass.PROBABLE_ERROR,
                    severity=Severity.HIGH, confidence=0.8 if linked else 0.65, affected=[p.id],
                    conflicting=sorted(deps),
                    reason=f"{p.id} [{p.text}] comes from {s.id}, which relies on retracted source(s) "
                           f"{', '.join(sorted(deps))}.",
                    resolution="Find independent, non-retracted evidence for the claim or withdraw it.",
                    evidence=sorted(deps), detector="rule:retraction@1"))
                self.review[p.id].append(f"relies on retracted source {', '.join(sorted(deps))}")

    SUBORDINATE_PRONOUN = re.compile(r"\b(?:after|before|when|because|since|until|while|although|once|as|if)\s+(it|they|he|she)\b", re.I)
    CANDIDATE_NP = re.compile(r"\b(?:[Tt]he|[Aa]n?)\s+(?:[A-Z][\w-]+\s+)*[a-zA-Z][\w-]+|\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+")

    def check_ambiguity(self) -> None:
        g = self.g
        for (pas_id, quote), props in self._sentence_props().items():
            m = self.SUBORDINATE_PRONOUN.search(quote)
            if not m:
                continue
            main = quote[:m.start()]
            cands = {c.lower() for c in self.CANDIDATE_NP.findall(main)}
            if len(cands) >= 2:
                for p in props:
                    self.unresolved_pronoun.add(p.id)
                    p.extraction.notes.append(f"pronoun '{m.group(1)}' could refer to: {', '.join(sorted(cands))}")
        for p in g.propositions.values():
            if p.claim_type == ClaimType.COMPOUND:
                continue
            src = g.sources[p.source_refs[0]]
            reasons = C.ambiguity_reasons(p, bool(src.published), p.id in self.unresolved_pronoun)
            if reasons:
                self._issue(C.IssueDraft(
                    category=IssueCategory.AMBIGUOUS_PROPOSITION, finding_class=FindingClass.SUSPICIOUS_CLAIM,
                    severity=Severity.LOW, confidence=0.6, affected=[p.id],
                    reason="Underspecified: " + "; ".join(reasons) + ".",
                    resolution="Specify the missing referent, unit or time anchor.",
                    evidence=[p.passage_id] if p.passage_id else [], detector="rule:ambiguity@1"))

    def check_sources(self) -> None:
        g = self.g
        for s in g.sources.values():
            if s.access_status != "accessible":
                self._issue(C.IssueDraft(
                    category=IssueCategory.SOURCE_UNAVAILABLE, finding_class=FindingClass.LIMITATION,
                    severity=Severity.LOW, confidence=1.0, affected=[s.id],
                    reason=f"Source '{s.key}' could not be analysed: {s.access_status} ({s.access_note}).",
                    resolution="Provide an accessible copy or install the required connector dependency.",
                    detector="registry"))

    # -------------------------------------------------------------- assessment
    def assess_all(self) -> None:
        g = self.g
        prev_assess = {}
        if self.previous:
            fp_by_id = {p["id"]: p["fingerprint"] for p in self.previous.get("propositions", [])}
            for a in self.previous.get("assessments", []):
                fp = fp_by_id.get(a["proposition_id"])
                if fp:
                    prev_assess[fp] = a
        ordered = sorted(g.propositions.values(), key=lambda p: (p.claim_type == ClaimType.COMPOUND, p.id))
        for p in ordered:
            triggers = list(dict.fromkeys(self.review.get(p.id, [])))
            if p.extraction.confidence < 0.5 and (p.relation_refs or p.evidence_refs or
                                                   [i for i in p.issue_refs if g.issues[i].category
                                                    != IssueCategory.AMBIGUOUS_PROPOSITION]):
                triggers.append(f"low extraction confidence ({p.extraction.confidence}) on a "
                                "proposition other findings depend on")
            g.assessments[p.id] = assess(g, p, triggers, p.id in self.confirmed_error,
                                         prev_assess.get(p.fingerprint), self.dependent_extra.get(p.id, 0))


def analyze(docs: list[dict], config: Optional[dict] = None, provider: Optional[Provider] = None,
            previous: Optional[dict] = None, now: Optional[str] = None) -> KnowledgeGraph:
    an = Analysis(config, provider, previous, now)
    g = an.run(docs)
    g.timings = an.timings
    if previous is not None:
        from .diff import diff_snapshots
        g.changes = diff_snapshots(previous, snapshot(g))
    else:
        g.changes = None
    return g


def snapshot(g: KnowledgeGraph) -> dict:
    d = g.to_dict()
    d["fingerprints"] = dict(g.fingerprints)
    d["archive"] = dict(g.archive)
    id_map: dict[str, dict] = defaultdict(dict)
    from .graph import PREFIX
    inv = {v: k for k, v in PREFIX.items()}
    id_map["source"] = {s.key: s.id for s in g.sources.values()}
    for ident, fp in d["fingerprints"].items():
        kind = inv.get(ident.split("-")[0])
        if kind and kind != "source":
            id_map[kind][fp] = ident
    d["id_map"] = id_map
    d["timings"] = g.timings
    d["changes"] = g.changes
    return d
