"""Source registry: source identity, archive, passages, duplicate / syndication
detection and independence groups.

Independence rule (see docs/EVIDENCE_POLICY.md §3): two sources belong to the same
independence group if one reproduces, translates, cites-as-basis or near-duplicates
the other (transitively).  Evidence from the same group never counts as
independent corroboration.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from .graph import KnowledgeGraph
from .lang import detect_language
from .models import EvidenceBasis, Passage, Source, SourceKind
from .textutil import jaccard, sha256, shingles, tokens

NEAR_DUPLICATE_JACCARD = 0.6
# Identical wording is evidence of copying only for texts long enough that
# independent authors are unlikely to coincide; shorter texts rely on declared
# provenance (reproduces / cites / translation_of).
MIN_DUPLICATE_TOKENS = 20
KNOWN_DOC_KEYS = {"key", "kind", "title", "author", "publisher", "published", "url", "canonical_url",
                  "doi", "isbn", "language", "pages", "text", "reproduces", "translation_of", "cites",
                  "retracted", "basis", "synthetic", "license", "version", "retrieved_at", "ocr",
                  "connector", "access_status", "access_note", "metadata"}
_PAGE_MARK = re.compile(r"^\[\[page\s+(\d+)\]\]$", re.I)


def _kind(value: Optional[str]) -> SourceKind:
    try:
        return SourceKind((value or "other").lower())
    except ValueError:
        return SourceKind.OTHER


def _basis(value: Optional[str]) -> Optional[EvidenceBasis]:
    if not value:
        return None
    aliases = {"survey": EvidenceBasis.SURVEY, "rct": EvidenceBasis.EXPERIMENTAL,
               "trial": EvidenceBasis.EXPERIMENTAL}
    try:
        return aliases.get(value.lower()) or EvidenceBasis(value.lower())
    except ValueError:
        return EvidenceBasis.UNSPECIFIED


class _UnionFind:
    def __init__(self):
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            lo, hi = sorted((ra, rb))
            self.parent[hi] = lo


def build_archive(doc: dict) -> tuple[str, list[tuple[int, int, Optional[int], Optional[str]]]]:
    """Return the archived full text and page segments (start, end, page, section)."""
    if doc.get("pages"):
        parts, segs, pos = [], [], 0
        for pg in doc["pages"]:
            t = pg.get("text", "")
            parts.append(t)
            segs.append((pos, pos + len(t), pg.get("page"), pg.get("section")))
            pos += len(t) + 2
        return "\n\n".join(parts), segs
    text = doc.get("text", "") or ""
    return text, [(0, len(text), None, None)]


def segment_passages(text: str, segs) -> list[dict]:
    """Paragraph segmentation with page / section tracking.  Markdown headings
    and ``[[page N]]`` markers update context and are not passages themselves."""
    out = []
    for start, end, page, section in segs:
        cur_page, cur_section = page, section
        for m in re.finditer(r"(?:[^\n]|\n(?!\s*\n))+", text[start:end]):
            block = m.group(0)
            stripped = block.strip()
            if not stripped:
                continue
            pm = _PAGE_MARK.match(stripped)
            if pm:
                cur_page = int(pm.group(1))
                continue
            if stripped.startswith("#"):
                cur_section = stripped.lstrip("#").strip()
                continue
            lead = len(block) - len(block.lstrip())
            s = start + m.start() + lead
            e = s + len(stripped)
            out.append({"start": s, "end": e, "text": text[s:e], "page": cur_page,
                        "section": cur_section})
    return out


def register_documents(g: KnowledgeGraph, docs: list[dict],
                       retrieved_at: Optional[str] = None) -> list[Source]:
    retrieved_at = retrieved_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    key_to_id: dict[str, str] = {}
    created: list[Source] = []
    for doc in docs:
        key = str(doc["key"])
        sid = g.ids.allocate("source", key)
        key_to_id[key] = sid
        text, segs = build_archive(doc)
        detected, det_conf = detect_language(text)
        declared = doc.get("language")
        meta = dict(doc.get("metadata", {}))
        meta.update({k: v for k, v in doc.items() if k not in KNOWN_DOC_KEYS})
        meta["detected_language"] = detected
        meta["detected_language_confidence"] = det_conf
        if declared and detected != "und" and declared != detected:
            meta["language_mismatch"] = f"declared {declared}, detected {detected}"
        src = Source(
            id=sid, key=key, kind=_kind(doc.get("kind")), title=doc.get("title"),
            author=doc.get("author"), publisher=doc.get("publisher"),
            published=doc.get("published"), url=doc.get("url"),
            canonical_url=doc.get("canonical_url") or doc.get("url"), doi=doc.get("doi"),
            isbn=doc.get("isbn"), language=declared or detected,
            retrieved_at=doc.get("retrieved_at") or retrieved_at,
            content_hash=sha256(text) if text else None, version=doc.get("version"),
            license=doc.get("license"),
            access_status=doc.get("access_status", "accessible" if text.strip() else "unavailable"),
            access_note=doc.get("access_note") or (None if text.strip() else "document has no text"),
            retracted=bool(doc.get("retracted", False)), basis=_basis(doc.get("basis")),
            synthetic=bool(doc.get("synthetic", False)), connector=doc.get("connector"),
            metadata=meta,
        )
        src.metadata["_raw_refs"] = {"reproduces": doc.get("reproduces"),
                                     "translation_of": doc.get("translation_of"),
                                     "cites": doc.get("cites") or []}
        if doc.get("ocr"):
            src.metadata["ocr"] = True
        g.add_source(src)
        g.archive[sid] = text
        for i, ps in enumerate(segment_passages(text, segs)):
            lang, conf = detect_language(ps["text"])
            if lang == "und" and src.language:
                lang = src.language
            pid = g.ids.allocate("passage")
            g.add_passage(Passage(id=pid, source_id=sid, text=ps["text"], char_start=ps["start"],
                                  char_end=ps["end"], language=lang, language_confidence=conf,
                                  page=ps["page"], section=ps["section"], paragraph_index=i))
        if src.access_status != "accessible":
            g.limitations.append(f"Source {sid} ('{key}') not analysed: {src.access_status}"
                                 f" — {src.access_note}")
        created.append(src)

    # resolve declared relationships between documents
    for src in created:
        raw = src.metadata.pop("_raw_refs")
        for field_name in ("reproduces", "translation_of"):
            ref = raw.get(field_name)
            if ref:
                if ref in key_to_id:
                    setattr(src, field_name, key_to_id[ref])
                else:
                    src.metadata[f"unresolved_{field_name}"] = ref
        for ref in raw.get("cites", []):
            if ref in key_to_id:
                src.cites.append(key_to_id[ref])
            else:
                src.metadata.setdefault("unresolved_cites", []).append(ref)
    detect_duplicates(g, created)
    assign_independence_groups(g)
    return created


def detect_duplicates(g: KnowledgeGraph, sources: list[Source]) -> None:
    by_hash: dict[str, str] = {}
    sh = {s.id: shingles(g.archive[s.id]) for s in sources}
    ordered = sorted(sources, key=lambda s: s.id)
    for i, s in enumerate(ordered):
        if not s.content_hash or len(tokens(g.archive[s.id])) < MIN_DUPLICATE_TOKENS:
            continue
        if s.content_hash in by_hash:
            s.duplicate_of = by_hash[s.content_hash]
            s.metadata["duplicate_similarity"] = 1.0
            continue
        by_hash[s.content_hash] = s.id
        for t in ordered[:i]:
            if t.duplicate_of or not t.content_hash or len(tokens(g.archive[t.id])) < MIN_DUPLICATE_TOKENS:
                continue
            sim = jaccard(sh[s.id], sh[t.id])
            if sim >= NEAR_DUPLICATE_JACCARD:
                s.duplicate_of = t.id
                s.metadata["duplicate_similarity"] = round(sim, 3)
                break


def assign_independence_groups(g: KnowledgeGraph) -> None:
    uf = _UnionFind()
    for s in g.sources.values():
        uf.find(s.id)
        for other in (s.reproduces, s.translation_of, s.duplicate_of, *s.cites):
            if other:
                uf.union(s.id, other)
    for s in g.sources.values():
        root = uf.find(s.id)
        s.independence_group = "G-" + root.split("-")[1]
