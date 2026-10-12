"""Deterministic issue detectors that do not need pairwise contradiction search:
arithmetic, quotations, translations, causal / inferential validity, ambiguity.

Each detector returns ``IssueDraft`` objects; the pipeline assigns identifiers.
"""
from __future__ import annotations

import ast
import operator
import re
from dataclasses import dataclass, field
from typing import Optional

from .lang import (NECESSITY_CUES, NEGATION_CUES, POSSIBILITY_CUES, UNIVERSAL_CUES, cue_count,
                   numbers_in)
from .models import (ClaimType, EvidenceBasis, FindingClass, IssueCategory, Modality,
                     Polarity, Proposition, Severity)
from .textutil import HANGUL, content_set, jaccard, norm_ws, split_sentences, tokens
from .units import find_quantities, parse_number


@dataclass
class IssueDraft:
    category: IssueCategory
    finding_class: FindingClass
    severity: Severity
    confidence: float
    affected: list
    reason: str
    resolution: str
    conflicting: list = field(default_factory=list)
    evidence: list = field(default_factory=list)
    detector: str = ""
    deterministic: bool = True
    dimensions: list = field(default_factory=list)
    assumptions: list = field(default_factory=list)
    details: dict = field(default_factory=dict)


# ------------------------------------------------------------------------ arithmetic

_NUM = r"[$€£]?\d[\d,]*(?:\.\d+)?"
_PCT_CHANGE = [
    re.compile(rf"from\s+(?P<a>{_NUM})\s*(?:%|percent)?\s*(?:\w+\s+){{0,2}}to\s+(?P<b>{_NUM})\s*(?:%|percent)?[^.;]*?\b(?:an?|the)\s+(?P<p>{_NUM})\s*(?:%|percent|per cent)\s+(?P<w>increase|rise|gain|growth|jump|decrease|drop|decline|fall|reduction|cut|loss)", re.I),
    re.compile(rf"(?P<w>increased|rose|grew|climbed|jumped|decreased|fell|dropped|declined|shrank)\s+(?:by\s+)?(?P<p>{_NUM})\s*(?:%|percent|per cent)\s*,?\s*from\s+(?P<a>{_NUM})\s*(?:\w+\s+){{0,2}}to\s+(?P<b>{_NUM})", re.I),
    re.compile(rf"(?P<w>increase|rise|growth|decrease|drop|decline|fall|reduction)\s+of\s+(?P<p>{_NUM})\s*(?:%|percent|per cent)\s*,?\s*from\s+(?P<a>{_NUM})\s*(?:\w+\s+){{0,2}}to\s+(?P<b>{_NUM})", re.I),
    re.compile(rf"from\s+(?P<a>{_NUM})\s*(?:\w+\s+){{0,2}}to\s+(?P<b>{_NUM})[^.;]*?(?:an?\s+)?(?P<w>increase|rise|growth|decrease|drop|decline|fall|reduction)\s+of\s+(?P<p>{_NUM})\s*(?:%|percent|per cent)", re.I),
]
# Korean: "40에서 50으로 50% 증가", "1,000명에서 1,500명으로 25퍼센트 늘었다"
_PCT_CHANGE.append(re.compile(rf"(?P<a>{_NUM})\s?(?:천|만|억|조)?\s?[가-힣]{{0,3}}에서\s+(?P<b>{_NUM})\s?(?:천|만|억|조)?\s?[가-힣]{{0,3}}(?:으로|로)\s+(?:약\s)?(?P<p>{_NUM})\s?(?:%|퍼센트)\s?(?P<w>증가|상승|늘|급증|감소|하락|줄|급감)"))
_SHARE_KO = re.compile(rf"(?P<y>{_NUM})\s?명?\s?중\s?(?P<x>{_NUM})\s?명?\s?(?:\(|,|이|가|은|는)?\s?(?:약\s)?(?P<p>{_NUM})\s?(?:%|퍼센트)")
_MULT = re.compile(rf"(?P<w>doubled|tripled|quadrupled|halved)\s*,?\s*(?:\w+\s+){{0,3}}?from\s+(?P<a>{_NUM})\s*(?:\w+\s+){{0,2}}to\s+(?P<b>{_NUM})", re.I)
_SHARE = re.compile(rf"(?P<x>{_NUM})\s+(?:out\s+)?of\s+(?:the\s+)?(?P<y>{_NUM})\s+(?:[\w-]+\s*){{0,3}}?[,(—-]\s*(?:or\s+|that is\s+|i\.e\.\s+)?(?:about\s+|roughly\s+|approximately\s+|nearly\s+)?(?P<p>{_NUM})\s*(?:%|percent|per cent)", re.I)
_SUM = re.compile(rf"(?P<items>(?:{_NUM}[^,.;]{{0,40}}?,\s*)*{_NUM}[^,.;]{{0,40}}?,?\s+and\s+{_NUM}[^.;]{{0,40}}?)[,;]?\s*(?:for\s+)?(?:a\s+(?:combined\s+)?total\s+of|totall?ing|in\s+total|making|adding\s+up\s+to|which\s+(?:sums?|adds?\s+up)\s+to|together\s+(?:making|totall?ing))\s+(?P<t>{_NUM})", re.I)
_TOTAL_FIRST = re.compile(rf"(?:a\s+)?total\s+of\s+(?P<t>{_NUM})\b[^.;]*?(?::|,|—|including|of\s+which|comprising)\s*(?P<items>{_NUM}[^.;]*?\band\s+{_NUM}[^.;]*)", re.I)


def _num(s: str) -> Optional[float]:
    return parse_number(s.replace("$", "").replace("€", "").replace("£", ""))


def _approx_equal(reported: float, actual: float) -> bool:
    return abs(reported - actual) <= max(0.6, 0.02 * abs(actual))


def check_arithmetic(sentence: str) -> list[dict]:
    """Return findings for verifiable computations stated in one sentence."""
    out = []
    for rx in _PCT_CHANGE:
        for m in rx.finditer(sentence):
            a, b, p = _num(m.group("a")), _num(m.group("b")), _num(m.group("p"))
            if a in (None, 0) or b is None or p is None:
                continue
            actual = (b - a) / a * 100
            word = m.group("w").lower()
            up = not re.match(r"de|drop|fall|fell|decl|reduc|cut|loss|shr|감소|하락|줄|급감", word)
            problems = []
            if up != (actual > 0) and actual != 0:
                problems.append(f"described as {'an increase' if up else 'a decrease'} but {a:g}→{b:g} is a {'decrease' if up else 'increase'}")
            if not _approx_equal(p, abs(actual)):
                problems.append(f"stated {p:g}% but ({b:g} − {a:g}) / {a:g} = {actual:+.1f}%")
            if problems:
                out.append({"kind": "percent_change", "span": m.group(0), "stated": p,
                            "computed": round(actual, 2), "problems": problems})
    for m in _MULT.finditer(sentence):
        a, b = _num(m.group("a")), _num(m.group("b"))
        if not a or b is None:
            continue
        factor = {"doubled": 2, "tripled": 3, "quadrupled": 4, "halved": 0.5}[m.group("w").lower()]
        if abs(b / a - factor) > 0.05 * factor:
            out.append({"kind": "multiplier", "span": m.group(0), "stated": factor,
                        "computed": round(b / a, 3),
                        "problems": [f"'{m.group('w')}' implies ×{factor:g} but {b:g}/{a:g} = ×{b / a:.2f}"]})
    for m in list(_SHARE.finditer(sentence)) + list(_SHARE_KO.finditer(sentence)):
        x, y, p = _num(m.group("x")), _num(m.group("y")), _num(m.group("p"))
        if not y or x is None or p is None or x > y:
            continue
        actual = x / y * 100
        if not _approx_equal(p, actual):
            out.append({"kind": "share", "span": m.group(0), "stated": p, "computed": round(actual, 2),
                        "problems": [f"stated {p:g}% but {x:g}/{y:g} = {actual:.1f}%"]})
    for rx in (_SUM, _TOTAL_FIRST):
        for m in rx.finditer(sentence):
            items = [_num(v) for v in re.findall(_NUM, m.group("items"))]
            items = [v for v in items if v is not None]
            t = _num(m.group("t"))
            if t is None or len(items) < 2:
                continue
            # ignore 4-digit years mixed into the list
            vals = [v for v in items if not (1900 <= v <= 2100 and v.is_integer())] or items
            if len(vals) < 2:
                continue
            s = sum(vals)
            if abs(s - t) > max(0.01 * abs(t), 0.5):
                out.append({"kind": "sum", "span": m.group(0), "stated": t, "computed": s,
                            "problems": [f"items sum to {s:g} but total stated as {t:g}"]})
    return out


_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.Pow: operator.pow, ast.USub: operator.neg}


def safe_eval(expr: str) -> Optional[float]:
    e = expr.lower().replace("×", "*").replace("÷", "/").replace("^", "**")
    e = re.sub(r"\bplus\b", "+", e)
    e = re.sub(r"\bminus\b", "-", e)
    e = re.sub(r"\b(?:times|multiplied by)\b", "*", e)
    e = re.sub(r"\bdivided by\b", "/", e)
    e = re.sub(r"(?<=\d)\s*x\s*(?=\d)", "*", e)
    e = e.replace(",", "")
    if not re.fullmatch(r"[\d.\s+\-*/()]+", e):
        return None

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            if isinstance(node.op, ast.Pow) and abs(ev(node.right)) > 100:
                raise ValueError("exponent too large")
            return _OPS[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.operand))
        raise ValueError("unsupported expression")

    try:
        return float(ev(ast.parse(e, mode="eval")))
    except (ValueError, SyntaxError, ZeroDivisionError, TypeError):
        return None


def check_math(p: Proposition) -> Optional[dict]:
    if p.claim_type != ClaimType.MATHEMATICAL:
        return None
    lhs = safe_eval(p.subject)
    rhs = parse_number(p.object or "")
    if lhs is None or rhs is None:
        return None
    if abs(lhs - rhs) > 1e-9 * max(1, abs(lhs)):
        return {"kind": "equation", "stated": rhs, "computed": lhs,
                "problems": [f"{p.subject} = {lhs:g}, not {rhs:g}"]}
    return None


# ------------------------------------------------------------------------ quotations

QUALIFIER_RX = re.compile(r"\b(not|no|never|only|unless|except|but|if|may|might|could|"
                          r"in mice|in rats|in animals|in vitro|preliminary|small|some|"
                          r"partly|partially|slightly|under|without)\b", re.I)


def _norm(s: str) -> str:
    return " ".join(tokens(s))


def speaker_matches(speaker: str, author: Optional[str], publisher: Optional[str]) -> bool:
    if not speaker:
        return False
    sp = set(re.sub(r"\b(dr|prof|professor|mr|mrs|ms|minister|senator|the)\b\.?", " ", speaker.lower()).split())
    sp = {w.strip(".,") for w in sp if len(w.strip(".,")) > 1}
    for cand in (author, publisher):
        if not cand:
            continue
        cw = {w.strip(".,") for w in cand.lower().split() if len(w.strip(".,")) > 1}
        if cw and sp and (cw <= sp or sp <= cw or (len(cw & sp) >= 1 and max(len(w) for w in cw & sp) >= 4)):
            return True
    return False


QUALIFIER_KO = re.compile(r"(?:지만|다만|단\s|경우에만|에서만|에게만|않|못|수\s?있|일부|부분적|아직|예비|소규모|동물\s?실험|쥐)")


def compare_quote(quote: str, original_sentences: list[str]) -> Optional[dict]:
    """Compare a quotation against candidate original sentences.  Returns a finding
    dict, or {"verbatim": True} if verbatim and context-preserving, or None if no
    plausible original was found."""
    nq = _norm(quote)
    best, best_sim = None, 0.0
    for s in original_sentences:
        ns = _norm(s)
        if nq and nq in ns:
            rest = ns.replace(nq, " ", 1)
            rx = QUALIFIER_KO if HANGUL.search(quote) else QUALIFIER_RX
            dropped = sorted(set(m.lower() for m in rx.findall(rest))
                             - set(m.lower() for m in rx.findall(nq)))
            if dropped and len(ns.split()) > len(nq.split()):
                return {"verbatim": True, "truncated": True, "original": s, "dropped": dropped,
                        "similarity": 1.0}
            return {"verbatim": True, "original": s}
        sim = jaccard(content_set(quote), content_set(s))
        if sim > best_sim:
            best, best_sim = s, sim
    if best is None or best_sim < 0.35:
        return None
    lang = "ko" if HANGUL.search(quote) else "en"
    changes = meaning_changes(lang, quote, lang, best)
    return {"verbatim": False, "original": best, "similarity": round(best_sim, 2),
            "changes": changes}


def meaning_changes(lang_a: str, a: str, lang_b: str, b: str) -> list[str]:
    """Compare negation, hedging, certainty and numbers between two renderings of
    (supposedly) the same statement.  Returns a list of detected changes."""
    out = []
    na, nb = numbers_in(a), numbers_in(b)
    if na != nb:
        out.append(f"numbers differ: {[f'{x:g}' for x in na]} vs {[f'{x:g}' for x in nb]}")
    for name, lex in (("negation", NEGATION_CUES), ("possibility modal", POSSIBILITY_CUES),
                      ("necessity modal", NECESSITY_CUES), ("universal quantifier", UNIVERSAL_CUES)):
        ca, cb = cue_count(lex, lang_a, a), cue_count(lex, lang_b, b)
        if ca < 0 or cb < 0:
            continue
        if (ca > 0) != (cb > 0):
            out.append(f"{name} {'present' if ca else 'absent'} in first, {'present' if cb else 'absent'} in second")
    return out


# ------------------------------------------------------------------------ translation

def align_sentences(orig: list[str], trans: list[str]) -> list[tuple[int, int]]:
    """Order-preserving alignment.  Equal counts: 1:1.  Otherwise relative position,
    refined by shared numbers."""
    if len(orig) == len(trans):
        return [(i, i) for i in range(len(orig))]
    pairs = []
    for j, t in enumerate(trans):
        rel = j / max(1, len(trans) - 1)
        cand = round(rel * max(0, len(orig) - 1))
        best = cand
        tn = set(numbers_in(t))
        if tn:
            scores = [(len(tn & set(numbers_in(o))), -abs(i - cand), i) for i, o in enumerate(orig)]
            sc = max(scores)
            if sc[0] > 0:
                best = sc[2]
        pairs.append((best, j))
    return pairs


def doc_sentences(text: str) -> list[str]:
    out = []
    for para in re.split(r"\n\s*\n", text):
        if para.strip().startswith("#") or not para.strip():
            continue
        out.extend(para[s:e] for s, e in split_sentences(para))
    return out


# ------------------------------------------------------------------------ inference

def inference_problems(conclusion: Proposition, premises: list[Proposition]) -> list[dict]:
    """Deterministic validity checks for a marked inference ("therefore ...")."""
    out = []
    cs = content_set(conclusion.subject + " " + (conclusion.object or ""))
    related = [p for p in premises if jaccard(cs, content_set(p.subject + " " + (p.object or ""))) >= 0.2
               or content_set(p.subject) & content_set(conclusion.subject)]
    if not related:
        return out
    if conclusion.claim_type == ClaimType.CAUSAL and conclusion.polarity == Polarity.POSITIVE:
        corr = [p for p in related if p.claim_type == ClaimType.CORRELATIONAL
                or p.stated_basis in (EvidenceBasis.OBSERVATIONAL, EvidenceBasis.SURVEY)]
        exper = [p for p in related if p.stated_basis in (EvidenceBasis.EXPERIMENTAL, EvidenceBasis.REVIEW)]
        if corr and not exper:
            out.append({"type": "correlation_to_causation", "premises": [p.id for p in corr],
                        "category": IssueCategory.UNSUPPORTED_CAUSAL_CLAIM,
                        "reason": "A causal conclusion is drawn from correlational/observational premises."})
    for p in related:
        dropped = []
        for dim in ("population", "location"):
            if getattr(p.scope, dim) and not getattr(conclusion.scope, dim):
                dropped.append(f"{dim}={getattr(p.scope, dim)}")
        if p.scope.conditions and not conclusion.scope.conditions:
            dropped.append("conditions=" + "; ".join(p.scope.conditions))
        if dropped:
            out.append({"type": "overgeneralisation", "premises": [p.id],
                        "category": IssueCategory.INVALID_INFERENCE,
                        "reason": "Conclusion drops scope restrictions of its premise: " + ", ".join(dropped) + "."})
            break
    for p in related:
        if p.quantifier in ("some", "many", "few", "most") and conclusion.quantifier in ("all", None) \
                and content_set(p.subject) & content_set(conclusion.subject) \
                and conclusion.quantifier == "all":
            out.append({"type": "quantifier_shift", "premises": [p.id],
                        "category": IssueCategory.INVALID_INFERENCE,
                        "reason": f"Premise quantifier '{p.quantifier}' does not license '{conclusion.quantifier}'."})
            break
    for p in related:
        if p.modality in (Modality.POSSIBLE, Modality.PROBABLE) and conclusion.modality == Modality.ASSERTED:
            out.append({"type": "modality_strengthening", "premises": [p.id],
                        "category": IssueCategory.INVALID_INFERENCE,
                        "reason": f"Premise is hedged ({p.modality.value}) but the conclusion is asserted as fact."})
            break
    return out


COUNT_ATTRIBUTE = re.compile(
    r"\b(population|number|count|total|headcount|membership|enrol\w*|attendance|turnout|votes|"
    r"residents|inhabitants|visitors|passengers|members|employees|workers|students|patients|"
    r"cases|deaths|births|users|subscribers|index|score|ratio|rank|ranking|age)\b"
    r"|인구|인원|수$|명수|건수|점수|순위|나이|연령|지수|비율|회원|가입자|관객|방문객|사망자|확진자", re.I)

VAGUE = re.compile(r"\b(many|some|several|a lot of|lots of|numerous|most|few|significant(?:ly)?|"
                   r"substantial(?:ly)?)\b|많은|일부|여러|상당수|다수의|몇몇", re.I)


def ambiguity_reasons(p: Proposition, has_pub_date: bool, unresolved_pronoun: bool) -> list[str]:
    out = []
    if unresolved_pronoun:
        note = next((n for n in p.extraction.notes if n.startswith("pronoun '") and "could refer" in n), None)
        out.append(note or f"subject '{p.surface.get('subject') or p.subject}' is a pronoun with no clear antecedent")
    bare = [n.split(":", 1)[1] for n in p.extraction.notes if n.startswith("number-without-unit:")]
    if bare:
        out.append(f"number '{bare[0]}' has no unit or measure")
    elif p.quantity is not None and p.quantity.unit is None and p.quantity.kind == "level" \
            and p.claim_type == ClaimType.STATISTICAL and not any(n.startswith("value-noun:") for n in p.extraction.notes) \
            and not COUNT_ATTRIBUTE.search(p.subject):
        out.append(f"number '{p.quantity.raw}' has no unit or measure")
    if p.scope.time and "relative-time" in p.extraction.notes and not has_pub_date:
        out.append(f"relative time '{p.scope.time}' with no publication date to anchor it")
    if p.claim_type in (ClaimType.STATISTICAL, ClaimType.CAUSAL, ClaimType.EMPIRICAL) \
            and p.quantity is None and VAGUE.search(norm_ws(p.surface.get("subject") or "")) \
            and re.match(r"^(many|some|several|numerous|a lot|lots|few)\b|^(?:많은|일부|여러|상당수|다수의|몇몇)\s", (p.surface.get("subject") or "").lower()):
        out.append(f"vague quantifier in '{p.surface.get('subject')}' without a number or reference class")
    return out
