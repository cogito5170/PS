"""Social-media (SNS) text normalisation, shared by the English and Korean extractors.

The verbatim quote of every proposition is never changed; only the working copy
that the predicate patterns see is normalised:

* emoji, pictographs and decorative symbols are removed (📦, ✅, ₿, ✨ …);
* URLs are removed, ``#해시태그`` / ``#hashtag`` keep the word without ``#``;
* laughter and crying runs (ㅋㅋ, ㅎㅎ, ㅠㅠ, lol) and repeated punctuation are removed;
* list bullets at the start of a line (-, •, ·, ▶, ✔, "1)") are removed;
* Korean bullet-style endings are restored to sentence endings so the predicate
  patterns can match: 함 → 한다, 됨 → 된다, 임 → 이다, 했음 → 했다, 있음 → 있다 …
"""
from __future__ import annotations

import re
import unicodedata

_URL = re.compile(r"https?://\S+|www\.\S+")
_LAUGH = re.compile(r"(?:[ㅋㅎ]{2,}|[ㅠㅜ]{2,}|\b(?:lol|lmao|haha+)\b)", re.I)
_BULLET = re.compile(r"^\s*(?:[-•·▶▷►✔✓✅☑*]+|\d{1,2}[.)])\s+")
_HASHTAG = re.compile(r"#(\w+)")
_REPEAT_PUNCT = re.compile(r"([!?.~])\1+")

# bullet-style (개조식) endings → declarative endings
_GAEJOSIK = [
    (re.compile(r"했음$"), "했다"), (re.compile(r"였음$"), "였다"), (re.compile(r"었음$"), "었다"),
    (re.compile(r"았음$"), "았다"), (re.compile(r"있음$"), "있다"), (re.compile(r"없음$"), "없다"),
    (re.compile(r"(?<=[가-힣])함$"), "한다"), (re.compile(r"(?<=[가-힣])됨$"), "된다"),
    (re.compile(r"(?<=[가-힣])임$"), "이다"), (re.compile(r"(?<=[가-힣])않음$"), "않는다"),
]


def _is_decoration(ch: str) -> bool:
    """Emoji and pictographs only; unit symbols (° ℃ ㎍ ㎥ µ % ‰) and arrows are kept."""
    o = ord(ch)
    return (0x1F000 <= o <= 0x1FAFF          # emoji, pictographs, flags
            or 0x2600 <= o <= 0x27BF         # misc symbols, dingbats (☀ ✅ ✨ ✔)
            or 0x2B00 <= o <= 0x2BFF         # stars, arrows-ornaments (⭐)
            or 0xFE00 <= o <= 0xFE0F         # variation selectors
            or o == 0x200D or o == 0x20E3    # zero-width joiner, keycap
            or ch == "₿")


def normalize_sns(text: str) -> str:
    t = _URL.sub(" ", text)
    t = _HASHTAG.sub(r"\1", t)
    t = "".join(" " if _is_decoration(c) else c for c in t)
    t = _LAUGH.sub(" ", t)
    t = _BULLET.sub("", t)
    t = _REPEAT_PUNCT.sub(r"\1", t)
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"\s*(?:…|\.\.\.)$", "", t)
    core = t.rstrip(".!")
    for rx, rep in _GAEJOSIK:
        if rx.search(core):
            core = rx.sub(rep, core)
            t = core + "."
            break
    return t


def split_lines(text: str) -> list[tuple[int, int]]:
    """Spans of non-empty lines (SNS posts use one line per sentence)."""
    out, pos = [], 0
    for line in text.split("\n"):
        start = pos
        pos += len(line) + 1
        if line.strip():
            lead = len(line) - len(line.lstrip())
            out.append((start + lead, start + len(line.rstrip())))
    return out
