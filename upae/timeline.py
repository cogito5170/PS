"""Time anchoring and cross-document timeline consistency (deterministic).

1. **Anchoring.** Relative time expressions ("내일", "3달 후", "10월", "tomorrow",
   "next month") are resolved against the publication date of their source into
   ``scope.time_resolved = [start, end]`` (ISO dates).  The original wording is
   kept in ``scope.time``; every resolution is noted in the proposition.
2. **Episodes.** Sentences about a stay or trip ("내일부터 치앙마이에서 한 달을
   살아봅니다", "치앙마이에 온 지 이틀", "Day 2", "한 달 동안 태국에서 …했습니다") are
   turned into statements that each *imply an interval for the episode's start
   date*, with an explicit tolerance for counting ambiguity.
3. **Consistency.** Statements by the same author about the same place (a city
   counts as part of its country) must have overlapping implied start intervals;
   otherwise a TEMPORAL_DISAGREEMENT issue names the dates and the gap.
4. **Predictions.** Present-tense statements about a resolved future time are
   predictions with a due date; once the analysis date passes the due date
   without evidence of fulfilment, a non-red MISSING_EVIDENCE note is raised.

Self-consistency of one author is *not* corroboration: no evidence items are
created from timeline agreement.
"""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

KO_DAYS = {"하루": 1, "이틀": 2, "사흘": 3, "나흘": 4, "닷새": 5, "엿새": 6, "이레": 7, "여드레": 8,
           "아흐레": 9, "열흘": 10, "보름": 15, "일주일": 7, "한 주": 7, "한주": 7}
KO_NUM = {"한": 1, "두": 2, "세": 3, "석": 3, "네": 4, "넉": 4, "다섯": 5, "여섯": 6, "일곱": 7,
          "여덟": 8, "아홉": 9, "열": 10}
EN_NUM = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
          "seven": 7, "eight": 8, "nine": 9, "ten": 10, "a couple of": 2, "few": 3}

# city -> country, used to treat "치앙마이" and "태국" as the same episode
PLACE_FAMILY = {
    "치앙마이": "태국", "방콕": "태국", "푸껫": "태국", "파타야": "태국", "chiang mai": "thailand",
    "bangkok": "thailand", "phuket": "thailand", "다낭": "베트남", "하노이": "베트남", "호치민": "베트남",
    "hanoi": "vietnam", "da nang": "vietnam", "발리": "인도네시아", "bali": "indonesia",
    "도쿄": "일본", "오사카": "일본", "후쿠오카": "일본", "tokyo": "japan", "osaka": "japan",
    "서울": "한국", "부산": "한국", "제주": "한국", "seoul": "korea", "busan": "korea",
    "리스본": "포르투갈", "lisbon": "portugal", "바르셀로나": "스페인", "barcelona": "spain",
    "파리": "프랑스", "paris": "france", "베를린": "독일", "berlin": "germany",
}
COUNTRY_ALIASES = {"thailand": "태국", "vietnam": "베트남", "indonesia": "인도네시아", "japan": "일본",
                   "korea": "한국", "portugal": "포르투갈", "spain": "스페인", "france": "프랑스",
                   "germany": "독일"}
_KO_PLACES = sorted({*PLACE_FAMILY, *PLACE_FAMILY.values(), "베트남", "인도네시아", "포르투갈", "스페인",
                     "프랑스", "독일", "대만", "타이베이", "싱가포르", "홍콩", "뉴욕", "런던", "멕시코시티"},
                    key=len, reverse=True)
PLACE_RE = "|".join(re.escape(p) for p in _KO_PLACES if not p.isascii())
EN_PLACE_RE = r"(?-i:[A-Z][a-z]+(?:\s[A-Z][a-z]+)?)"  # case-sensitive even inside re.I patterns
DEICTIC = re.compile(r"(?:여기|이곳|이 곳|이 도시)|\b(?:here)\b", re.I)


def family(place: Optional[str]) -> Optional[str]:
    if not place:
        return None
    p = place.strip().lower()
    p = PLACE_FAMILY.get(p, p)
    return COUNTRY_ALIASES.get(p, p)


# ----------------------------------------------------------------------------- arithmetic

def add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    y = d.year + m // 12
    m = m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def month_range(y: int, m: int) -> tuple[date, date]:
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])


def parse_iso(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.match(r"(\d{4})-(\d{2})$", s)
    if m:
        return date(int(m.group(1)), int(m.group(2)), 1)
    return None


def duration_days(text: str) -> Optional[int]:
    """'이틀' → 2, '한 달' → 30, '3주' → 21, 'two weeks' → 14, 'a month' → 30."""
    t = text.strip().lower()
    for k, v in KO_DAYS.items():
        if t == k or t.startswith(k):
            return v
    m = re.match(r"(\d+)\s?(일|주|달|개월|년|days?|weeks?|months?|years?)", t)
    if not m:
        m2 = re.match(r"(한|두|세|석|네|넉|다섯|여섯|일곱|여덟|아홉|열)\s?(달|주|해|개월)", t) \
            or re.match(r"(a couple of|an|a|one|two|three|four|five|six|seven|eight|nine|ten|few)\s(days?|weeks?|months?|years?)", t)
        if not m2:
            return None
        n = KO_NUM.get(m2.group(1)) or EN_NUM.get(m2.group(1))
        unit = m2.group(2)
    else:
        n, unit = int(m.group(1)), m.group(2)
    if unit.startswith(("일", "day")):
        return n
    if unit.startswith(("주", "week")):
        return 7 * n
    if unit.startswith(("달", "개월", "month")):
        return 30 * n
    return 365 * n


DUR_KO = (r"(?:하루|이틀|사흘|나흘|닷새|엿새|이레|여드레|아흐레|열흘|보름|일주일|한\s?주|"
          r"\d+\s?(?:일|주|달|개월|년)|(?:한|두|세|석|네|넉|다섯|여섯)\s?(?:달|주|개월))")
DUR_EN = (r"(?:\d+|a couple of|an|a|one|two|three|four|five|six|seven|eight|nine|ten|few)\s"
          r"(?:days?|weeks?|months?|years?)")


def resolve(expr: str, pub: date) -> Optional[tuple[date, date, str]]:
    """Resolve a time expression against a publication date."""
    t = expr.strip().lower()
    t = re.sub(r"(?:부터|까지|에는|에|째)$", "", t).strip()
    one = lambda d, why: (d, d, why)  # noqa: E731
    table = {"오늘": 0, "today": 0, "tonight": 0, "현재": 0, "지금": 0, "내일": 1, "tomorrow": 1, "모레": 2,
             "어제": -1, "yesterday": -1, "그제": -2, "그저께": -2}
    if t in table:
        return one(pub + timedelta(days=table[t]), f"{expr} → publication date {pub.isoformat()} {table[t]:+d} day(s)")
    years = {"올해": 0, "금년": 0, "this year": 0, "내년": 1, "next year": 1, "작년": -1, "지난해": -1,
             "last year": -1}
    if t in years:
        y = pub.year + years[t]
        return date(y, 1, 1), date(y, 12, 31), f"{expr} → {y}"
    months = {"이번 달": 0, "이번달": 0, "this month": 0, "다음 달": 1, "다음달": 1, "next month": 1,
              "지난달": -1, "지난 달": -1, "last month": -1}
    if t in months:
        d = add_months(pub, months[t])
        a, b = month_range(d.year, d.month)
        return a, b, f"{expr} → {a.isoformat()[:7]}"
    weeks = {"이번 주": 0, "이번주": 0, "this week": 0, "다음 주": 1, "다음주": 1, "next week": 1,
             "지난주": -1, "지난 주": -1, "last week": -1}
    if t in weeks:
        monday = pub - timedelta(days=pub.weekday()) + timedelta(weeks=weeks[t])
        return monday, monday + timedelta(days=6), f"{expr} → week of {monday.isoformat()}"
    m = re.match(rf"^({DUR_KO})\s?(후|뒤|전)$", t) or re.match(rf"^(?:in\s)?({DUR_EN})(\slater|\sago)?$", t)
    if m:
        n = duration_days(m.group(1))
        if n is None:
            return None
        sign = -1 if (m.group(2) or "").strip() in ("전", "ago") else 1
        if sign > 0 and not m.group(2) and not t.startswith("in "):
            return None  # bare duration is not a time point
        d = pub + timedelta(days=sign * n)
        tol = max(1, round(n * 0.1)) if n >= 28 else 0
        return d - timedelta(days=tol), d + timedelta(days=tol), f"{expr} → {pub.isoformat()} {sign * n:+d} day(s)"
    m = re.match(r"^(\d{4})\s?년\s?(\d{1,2})\s?월(?:\s?(\d{1,2})\s?일)?$", t)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        if m.group(3):
            d = date(y, mo, int(m.group(3)))
            return d, d, f"{expr} (absolute)"
        a, b = month_range(y, mo)
        return a, b, f"{expr} (absolute)"
    m = re.match(r"^(\d{1,2})\s?월(?:\s?(\d{1,2})\s?일)?$", t)
    if m:
        mo = int(m.group(1))
        if not 1 <= mo <= 12:
            return None
        y = pub.year
        if m.group(2):
            d = date(y, mo, int(m.group(2)))
            return d, d, f"{expr} → year {y} assumed from publication date"
        a, b = month_range(y, mo)
        return a, b, f"{expr} → {y}-{mo:02d} (year assumed from publication date)"
    return None


# ----------------------------------------------------------------------------- episodes

@dataclass
class Statement:
    source_id: str
    passage_id: str
    quote: str
    kind: str                 # start | elapsed | day_count | past_duration
    place: Optional[str]
    implied_start: tuple      # (earliest, latest) date
    explanation: str
    planned_days: Optional[int] = None
    prop_ids: list = field(default_factory=list)


# past tense in Korean: any syllable whose final consonant is ㅆ (했, 었, 웠, 갔, 봤 …)
PAST_SYLLABLES = "".join(chr(0xAC00 + i) for i in range(11172) if i % 28 == 20)

_START_KO = re.compile(
    rf"(?P<when>내일|모레|오늘|다음\s?주|다음\s?달|\d+\s?(?:일|주|달|개월)\s?(?:후|뒤)|\d{{1,2}}\s?월\s?\d{{1,2}}\s?일)\s?부터"
    rf"(?:[^.\n]*?(?P<place>{PLACE_RE})(?:에서|에|로))?(?:[^.\n]*?(?P<dur>{DUR_KO})(?:을|를|간|동안)?)?")
_START_EN = re.compile(
    rf"(?P<when>tomorrow|today|next week|next month)\b[^.\n]*?\b(?:fly|leave|move|head|go|start|begin|arrive|land)s?\b"
    rf"(?:[^.\n]*?\b(?:to|in)\s(?P<place>{EN_PLACE_RE}))?(?:[^.\n]*?\bfor\s(?P<dur>{DUR_EN}))?", re.I)
_ELAPSED_KO = re.compile(
    rf"(?:(?P<place>{PLACE_RE}|여기|이곳)(?:에|에서|로)?\s?)?(?:온|도착한|간|머문|지낸|산|살기\s?시작한|입국한)\s?지\s?(?P<dur>{DUR_KO})")
_ELAPSED_EN = re.compile(
    rf"(?P<dur>{DUR_EN})\s(?:since|after)\s(?:I|we)\s(?:arrived|landed|got here|moved here)(?:\s(?:in|to)\s(?P<place>{EN_PLACE_RE}))?",
    re.I)
_DAYCOUNT = re.compile(r"(?:\bday\s?(?P<n>\d{1,3})\b|(?P<n2>\d{1,3})\s?일\s?(?:차|째))", re.I)
_PAST_DUR_KO = re.compile(
    rf"(?:(?P<dur>{DUR_KO})\s?(?:동안|간)\s?(?:[^.\n]*?(?P<place>{PLACE_RE})(?:에서|에))?|(?P<place2>{PLACE_RE})에서\s?(?P<dur2>{DUR_KO})\s?(?:동안|간))"
    rf"[^.\n]*?[{PAST_SYLLABLES}]")
_PAST_DUR_EN = re.compile(
    rf"\b(?:spent|lived|stayed|worked|was|were|been|traveled|travelled|focused)\b[^.\n]*?\b(?:for\s)?(?P<dur>{DUR_EN})\s(?:in|at)\s(?P<place>{EN_PLACE_RE})"
    rf"|\b(?:after|for)\s(?P<dur2>{DUR_EN})\s(?:in|at)\s(?P<place2>{EN_PLACE_RE})", re.I)


def _place_in(text: str) -> Optional[str]:
    m = re.search(PLACE_RE, text)
    if m:
        return m.group(0)
    for p in PLACE_FAMILY:
        if p.isascii() and re.search(rf"\b{re.escape(p)}\b", text, re.I):
            return p
    for c in COUNTRY_ALIASES:
        if re.search(rf"\b{c}\b", text, re.I):
            return c
    return None


def statements_for(text: str, pub: date, context_place: Optional[str]) -> list[dict]:
    """All episode statements in one sentence/line."""
    out = []
    for rx in (_START_KO, _START_EN):
        m = rx.search(text)
        if m:
            r = resolve(m.group("when"), pub)
            if r:
                place = m.group("place") or _place_in(text) or context_place
                dur = duration_days(m.group("dur")) if m.group("dur") else None
                out.append(dict(kind="start", place=place, implied=(r[0], r[1]), planned=dur,
                                why=f"'{m.group('when')}' resolved to {r[0].isoformat()} ({r[2]})"))
                break
    for rx in (_ELAPSED_KO, _ELAPSED_EN):
        m = rx.search(text)
        if m:
            n = duration_days(m.group("dur"))
            if n:
                place = m.group("place")
                if place and DEICTIC.fullmatch(place):
                    place = None
                place = place or _place_in(text) or context_place
                # "온 지 이틀": arrival 2 days ago, or today is day 2 → counting ambiguity of one day
                out.append(dict(kind="elapsed", place=place,
                                implied=(pub - timedelta(days=n), pub - timedelta(days=n - 1)),
                                why=f"'{m.group(0).strip()}' on {pub.isoformat()} → arrival {n - 1}–{n} day(s) earlier"))
                break
    m = _DAYCOUNT.search(text)
    if m:
        n = int(m.group("n") or m.group("n2"))
        if 1 <= n <= 400:
            out.append(dict(kind="day_count", place=_place_in(text) or context_place,
                            implied=(pub - timedelta(days=n), pub - timedelta(days=n - 1)),
                            why=f"'{m.group(0).strip()}' on {pub.isoformat()} → day 1 was {n - 1}–{n} day(s) earlier"))
    for rx in (_PAST_DUR_KO, _PAST_DUR_EN):
        m = rx.search(text)
        if m:
            dur = m.group("dur") or m.group("dur2")
            n = duration_days(dur)
            if n:
                place = m.group("place") or m.group("place2") or _place_in(text) or context_place
                tol = max(2, round(n * 0.15))
                end = pub
                out.append(dict(kind="past_duration", place=place,
                                implied=(end - timedelta(days=n + tol), end - timedelta(days=max(0, n - tol))),
                                why=f"'{dur}' completed by {pub.isoformat()} → start ≈ {(end - timedelta(days=n)).isoformat()} ±{tol} day(s)"))
                break
    return out


# ----------------------------------------------------------------------------- graph level

def anchor_propositions(g) -> list[str]:
    """Resolve relative ``scope.time`` of every proposition against its source's
    publication date.  Returns ids of propositions that refer to a future time
    relative to publication (prediction candidates)."""
    future = []
    for p in g.propositions.values():
        src = g.sources[p.source_refs[0]]
        pub = parse_iso(src.published)
        if pub is None or not p.scope.time:
            continue
        r = resolve(p.scope.time, pub)
        if r is None:
            continue
        a, b, why = r
        p.scope.time_resolved = [a.isoformat(), b.isoformat()]
        p.scope.time_norm = [a.year, b.year]
        p.extraction.notes.append(f"time anchored: {why}")
        if a > pub:
            future.append(p.id)
    return future


def build_timelines(g) -> list[dict]:
    """Collect episode statements per author and place family and test whether
    their implied start dates can all be true at once."""
    by_author: dict[str, list[Statement]] = {}
    srcs = sorted((s for s in g.sources.values() if parse_iso(s.published)),
                  key=lambda s: (s.published, s.id))
    last_place: dict[str, Optional[str]] = {}
    for src in srcs:
        pub = parse_iso(src.published)
        author = src.author or src.publisher or f"source:{src.key}"
        passages = sorted((x for x in g.passages.values() if x.source_id == src.id), key=lambda x: x.char_start)
        post_place = None
        for pas in passages:
            place_here = _place_in(pas.text)
            post_place = post_place or place_here
        for pas in passages:
            for line in [ln for ln in re.split(r"\n+", pas.text) if ln.strip()]:
                for st in statements_for(line, pub, post_place or last_place.get(author)):
                    props = [p.id for p in g.propositions.values()
                             if p.passage_id == pas.id and p.quote and (p.quote in line or line.strip() in p.quote)
                             and p.claim_type.value != "compound"]
                    by_author.setdefault(author, []).append(Statement(
                        source_id=src.id, passage_id=pas.id, quote=line.strip(), kind=st["kind"],
                        place=st["place"], implied_start=st["implied"], explanation=st["why"],
                        planned_days=st.get("planned"), prop_ids=props))
                    if st["place"]:
                        last_place[author] = st["place"]
        if post_place:
            last_place[author] = post_place
    episodes = []
    for author, sts in sorted(by_author.items()):
        groups: dict[str, list[Statement]] = {}
        for st in sts:
            groups.setdefault(family(st.place) or "(unspecified place)", []).append(st)
        for fam, items in sorted(groups.items()):
            if len(items) < 2 or len({i.source_id for i in items}) < 2:
                episodes.append(_episode(author, fam, items, None))
                continue
            lo = max(i.implied_start[0] for i in items)
            hi = min(i.implied_start[1] for i in items)
            conflict = None
            if lo > hi:
                worst, gap = None, 0
                for x in range(len(items)):
                    for y in range(x + 1, len(items)):
                        a, b = items[x], items[y]
                        d = max((a.implied_start[0] - b.implied_start[1]).days,
                                (b.implied_start[0] - a.implied_start[1]).days)
                        if d > gap and a.source_id != b.source_id:
                            worst, gap = (a, b), d
                conflict = (worst, gap) if worst else None
            episodes.append(_episode(author, fam, items, conflict, (lo, hi) if lo <= hi else None))
    return episodes


def _episode(author, fam, items, conflict, window=None) -> dict:
    return {
        "author": author, "place": fam,
        "statements": [{"source": i.source_id, "passage": i.passage_id, "quote": i.quote, "kind": i.kind,
                        "implied_start": [i.implied_start[0].isoformat(), i.implied_start[1].isoformat()],
                        "explanation": i.explanation, "planned_days": i.planned_days,
                        "propositions": i.prop_ids} for i in items],
        "checked": len({i.source_id for i in items}) >= 2,
        "consistent": conflict is None,
        "start_window": [window[0].isoformat(), window[1].isoformat()] if window else None,
        "conflict": None if conflict is None else {
            "a": conflict[0][0].quote, "b": conflict[0][1].quote, "gap_days": conflict[1],
            "a_props": conflict[0][0].prop_ids, "b_props": conflict[0][1].prop_ids,
            "a_source": conflict[0][0].source_id, "b_source": conflict[0][1].source_id,
            "a_why": conflict[0][0].explanation, "b_why": conflict[0][1].explanation},
    }
