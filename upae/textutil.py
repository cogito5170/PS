"""Deterministic text utilities: sentence splitting, tokenisation, light stemming,
normalisation. Stdlib only."""
from __future__ import annotations

import hashlib
import re
import unicodedata

_ABBREV = {
    "dr", "mr", "mrs", "ms", "prof", "st", "vs", "etc", "e.g", "i.e", "fig", "no",
    "inc", "ltd", "co", "jr", "sr", "approx", "dept", "est", "u.s", "u.k", "al", "ca",
}

_SENT_END = re.compile(r'([.!?])(["”’)]*)(\s+)(?=["“(]?[A-Z0-9À-ɏ])')


def split_sentences(text: str) -> list[tuple[int, int]]:
    """Return (start, end) spans of sentences in ``text``.

    Rule-based: a sentence ends at . ! ? followed by whitespace and an upper-case
    letter/digit, unless the token before the period is a known abbreviation or a
    single initial.  Quotation marks never split a sentence internally.
    """
    spans: list[tuple[int, int]] = []
    start = 0
    for m in _SENT_END.finditer(text):
        end = m.end(2)
        if m.group(1) == ".":
            before = text[start:m.start(1)]
            last = re.findall(r"([\w.]+)$", before)
            word = last[0].lower() if last else ""
            if word in _ABBREV:
                continue
            if len(word) == 1 and word.isalpha():
                # an initial ("J. Smith", "John F. Kennedy") follows a capitalised word or
                # starts the sentence; "conditions A." or "90 °C." end a sentence
                prev = re.findall(r"(\S+)\s+\S$", before)
                if not prev or prev[0][:1].isupper():
                    if before.endswith(" " + last[0]) or before == last[0]:
                        continue
            # do not split inside an open quotation
        if text[start:end].count('"') % 2 == 1:
            continue
        seg = text[start:end].strip()
        if seg:
            s = start + (len(text[start:end]) - len(text[start:end].lstrip()))
            spans.append((s, end))
        start = m.end(3)
    tail = text[start:]
    if tail.strip():
        s = start + (len(tail) - len(tail.lstrip()))
        spans.append((s, len(text.rstrip())))
    return spans


STOPWORDS = {
    "a", "an", "the", "of", "in", "on", "at", "to", "for", "by", "with", "from", "and",
    "or", "is", "are", "was", "were", "be", "been", "being", "that", "this", "these",
    "those", "it", "its", "as", "than", "into", "about", "over", "per", "has", "have",
    "had", "do", "does", "did", "which", "who", "whom", "their", "there", "they", "them",
    "his", "her", "he", "she", "we", "our", "us", "i", "my", "me", "you", "your", "also",
    "very", "more", "most", "such", "so", "up", "out", "after", "before", "during", "while",
    "between", "among", "under", "same", "both", "each", "all", "any", "some", "many",
    "much", "can", "could", "would", "should", "will", "may", "might", "must", "not", "no",
}

_SYNONYMS = {
    "costs": "cost", "expenses": "cost", "expenditure": "cost", "spending": "cost",
    "price": "price", "prices": "price",
    "deaths": "mortality", "death": "mortality", "fatalities": "mortality",
    "pupils": "students", "learners": "students",
    "kids": "children", "child": "children",
    "usa": "united states", "u.s.": "united states", "us": "united states",
    "uk": "united kingdom", "u.k.": "united kingdom",
}


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def stem(word: str) -> str:
    """Very light English suffix stripping (deterministic, conservative)."""
    w = word
    for suf, rep in (("ies", "y"), ("sses", "ss"), ("ing", ""), ("edly", ""), ("ed", ""),
                     ("es", ""), ("s", "")):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            if suf == "s" and w.endswith("ss"):
                continue
            if suf == "es" and not re.search(r"(ss|x|ch|sh|z)es$", w):
                continue
            return w[: len(w) - len(suf)] + rep
    return w


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9À-ɏ]+(?:[.'-][a-z0-9]+)*", text.lower())


def content_tokens(text: str) -> list[str]:
    out = []
    for t in tokens(text):
        t = _SYNONYMS.get(t, t)
        if t in STOPWORDS or len(t) < 2:
            continue
        out.append(stem(t))
    return out


def content_set(text: str) -> frozenset:
    return frozenset(content_tokens(text))


def jaccard(a, b) -> float:
    a, b = set(a), set(b)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def overlap(a, b) -> float:
    """|a∩b| / min(|a|,|b|) — containment-style similarity."""
    a, b = set(a), set(b)
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


_DET = re.compile(r"^(the|a|an|this|that|these|those|its|their|our)\s+", re.I)


def normalize_phrase(text: str | None) -> str:
    if not text:
        return ""
    t = text.strip().strip(",;:.\"'").strip()
    t = re.sub(r"\s+", " ", t)
    t = _DET.sub("", t)
    words = [_SYNONYMS.get(w, w) for w in t.lower().split()]
    return " ".join(words)


def shingles(text: str, k: int = 5) -> set:
    toks = tokens(text)
    if len(toks) < k:
        return {" ".join(toks)} if toks else set()
    return {" ".join(toks[i:i + k]) for i in range(len(toks) - k + 1)}


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def short_hash(*parts: str, n: int = 16) -> str:
    return sha256("\x1f".join(parts))[:n]


def norm_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()
