"""Deterministic (rule-based) Korean proposition extractor.

Korean is SOV and agglutinative: the subject/topic is marked by a particle
(은/는/이/가), the object by 을/를, and the predicate comes last with tense,
negation (-지 않다/못하다), possibility (-ㄹ 수 있다) and politeness endings.
The extractor therefore:

  1. strips attribution (…에 따르면, "…"라고 말했다, …다고 밝혔다) and inference markers (따라서, 결국 …);
  2. splits clauses on 때문에 (cause), -지만/하지만 (qualification) and shared-subject -고;
  3. removes scope phrases: time (2023년에, 3달 후), population (성인의, …을 대상으로),
     conditions (실험 조건 A에서), known locations (서울에서);
  4. splits the subject at the first topic/subject particle;
  5. matches the predicate by verb stem into the same canonical predicates as the
     English extractor (increases, decreases, increased, has_value, is, correlates_with,
     is_defined_as, <event>_in …), so comparison, evidence and checks are shared.

Every draft keeps the verbatim sentence.  Unmatched clauses become low-confidence
``asserts`` propositions marked for review, never silently dropped.
"""
from __future__ import annotations

import re
from typing import Optional

from .extract import Draft
from .models import Attribution, ClaimType, EvidenceBasis, Modality, Polarity, Quantity, Scope
from .textutil import norm_ws, split_sentences, strip_josa
from .units import find_quantities

EXTRACTOR_ID = "rule-ko@1"
IMPLICIT_SUBJECT = "(화자)"  # omitted subject, attributed to the speaker/author

# ----------------------------------------------------------------------------- lexicons
UP_T = r"(?:높일|늘릴|증가시킬|개선할|향상시킬|강화할|촉진할|높이|높인|높였|높여|늘리|늘린|늘렸|늘려|증가시키|증가시킨|증가시켰|개선하|개선한|개선했|개선시키|개선시킨|개선시켰|향상시키|향상시킨|향상시켰|강화하|강화한|강화했|끌어올리|끌어올린|끌어올렸|촉진하|촉진한|촉진했)"
DOWN_T = r"(?:줄일|낮출|감소시킬|억제할|완화할|예방할|단축할|줄이|줄인|줄였|줄여|낮추|낮춘|낮췄|낮춰|감소시키|감소시킨|감소시켰|억제하|억제한|억제했|완화하|완화한|완화했|떨어뜨리|떨어뜨린|떨어뜨렸|예방하|예방한|예방했|단축하|단축한|단축했|단축시키|단축시킨|단축시켰)"
UP_I = r"(?:올라갔|올라간|올라가|증가할|늘어날|상승할|오를|높아질|증가하|증가한|증가했|증가해|증가됐|늘어나|늘어난|늘어났|늘었|상승하|상승한|상승했|올랐|오르|높아지|높아진|높아졌|확대되|확대된|확대됐|급증하|급증한|급증했|급등하|급등한|급등했)"
DOWN_I = r"(?:내려갔|내려간|내려가|감소할|줄어들|하락할|떨어질|낮아질|감소하|감소한|감소했|감소해|줄어들|줄어든|줄어들었|줄었|하락하|하락한|하락했|떨어지|떨어진|떨어졌|낮아지|낮아진|낮아졌|축소되|축소된|축소됐|급감하|급감한|급감했|급락하|급락한|급락했)"
CAUSE_V = r"(?:유발하|유발한|유발했|유발시|초래하|초래한|초래했|야기하|야기한|야기했|일으키|일으킨|일으켰)"
EVENT_V = {
    "설립": "founded", "창립": "founded", "창업": "founded", "개관": "opened", "개장": "opened",
    "개업": "opened", "개통": "opened", "문을 열": "opened", "출간": "published", "출판": "published",
    "발표": "announced", "체결": "signed", "서명": "signed", "완공": "completed", "준공": "completed",
    "태어": "born", "출생": "born", "사망": "died", "폐쇄": "closed", "폐업": "closed", "출시": "launched",
    "완료": "completed", "완성": "completed", "마무리": "completed", "마쳤": "completed", "끝났": "completed",
}
_EVENT_RE = "|".join(sorted((re.escape(k) for k in EVENT_V), key=len, reverse=True))
NEG = re.compile(r"지\s?(?:않|못)|(?:않았|않는|않습|않을|않아)|못(?:했|한|하|합)|(?<![가-힣])안\s|아니(?:다|었|며|었다|에요)|아닙|없(?:다|었|는|습)")
POSSIBLE = re.compile(r"(?:ㄹ|을|를|할|일|될|줄일|높일|있을)?\s?수\s?(?:도\s?)?있|가능성이\s?(?:있|높)|것으로\s?(?:보인다|보입니다|보였|추정)|듯(?:하|합)|것\s?같|추정(?:된다|됩니다)|일지도")
CANNOT = re.compile(r"수\s?(?:가\s)?없")
PREDICTED = re.compile(r"예정(?:이|입니|이다)|계획(?:이|입니)|전망(?:이|입니|이다)|ㄹ\s?것(?:이다|입니다)|(?:할|될|줄|늘|오를|낮출|높일)\s?것(?:이다|입니다|으로)|겠(?:다|습니다)")
NORMATIVE = re.compile(r"해야\s?(?:한다|합니다|할|하며)|하여야|돼야|되어야|(?:하지|해서는)\s?안\s?된다|필요가\s?있다")
OPINION_START = re.compile(r"^(?:제|내|저의|나의|우리의?)\s?(?:생각|의견|판단)(?:에는|에|으로는|은)[,\s]+|^개인적으로(?:는)?[,\s]+|^솔직히[,\s]+")
OPINION_END = re.compile(r"(?:라고|다고|고)\s?(?:생각한다|생각합니다|생각해요|믿는다|믿습니다|느낀다|느낍니다|본다|봅니다)\.?$")
EVALUATIVE = re.compile(r"최고|최악|훌륭|아름답|아름다운|멋지|멋진|형편없|끔찍|대단|추하|못생|역겨|감동적|지루")
INFERENCE = re.compile(r"^(?:따라서|그러므로|그래서|결국|즉|이에\s?따라|이처럼|이로써|이는\s.+?(?:보여준다|의미한다|증명한다|입증한다)|이것은\s.+?(?:보여준다|증명한다))[,\s]+")
COPULA_END = re.compile(r"(?:이었습니다|였습니다|입니다|이었다|였다|이다|이며|이에요|예요|임)\.?$")
VALUE_VERB = re.compile(r"(?:에|을|를|로|으로)?\s?(?:달했|달한|달한다|기록했|기록한|기록하|기록되|기록됐|집계됐|집계되|나타났|조사됐|측정됐|측정되|이른다|이르렀|이릅니다|이르는)")
STUDY_WORDS = re.compile(r"연구|조사|실험|시험|보고서|통계|분석|연구진|연구팀|자료|데이터|설문|센서스|인구조사")

BASIS_CUES_KO = [
    (EvidenceBasis.REVIEW, r"메타\s?분석|체계적\s?문헌\s?고찰"),
    (EvidenceBasis.EXPERIMENTAL, r"무작위|대조\s?(?:군|실험|시험)|임상\s?시험|위약|실험\s?결과|실험에서"),
    (EvidenceBasis.OBSERVATIONAL, r"관찰\s?연구|코호트|상관|관련이\s?있|연관(?:이|되)"),
    (EvidenceBasis.SURVEY, r"설문|여론\s?조사|응답자"),
    (EvidenceBasis.DATASET, r"통계청|인구\s?조사|센서스|통계에\s?따르면|공식\s?통계|자료에\s?따르면"),
    (EvidenceBasis.ANECDOTAL, r"내\s?경험|제\s?경험|지인|친구가|옆집"),
    (EvidenceBasis.EXPERT_OPINION, r"전문가들?은|전문가에\s?따르면"),
]

POP_NOUNS = (r"(?:성인|어린이|아동|청소년|노인|고령자|학생|대학생|초등학생|환자|여성|남성|임산부|흡연자|"
             r"비흡연자|직장인|근로자|가구|기업|주민|참가자|응답자|생쥐|쥐|동물|운전자|소비자|유권자|"
             r"선수|교사|간호사|의사|영유아|영아|유아|신생아|청년)")
LOCATIONS = (r"(?:한국|대한민국|북한|미국|일본|중국|대만|태국|베트남|인도|독일|프랑스|영국|이탈리아|스페인|"
             r"캐나다|호주|러시아|브라질|멕시코|서울|부산|인천|대구|광주|대전|울산|세종|제주|경기도|강원도|"
             r"치앙마이|방콕|도쿄|오사카|베이징|상하이|뉴욕|런던|파리|베를린|[가-힣]{1,5}(?:특별시|광역시|시|군|구))")

_NUM = r"[$€£₩]?\d[\d,]*(?:\.\d+)?"
_NUMQ = rf"{_NUM}\s?(?:천|만|억|조)?\s?(?:퍼센트포인트|%p|퍼센트|%|명|원|달러|유로|엔|킬로미터|미터|톤|킬로그램|점|개월|시간|메가와트|기가와트|km|kg|m|도|℃|곳|개교|개|그루|회|건|위|㎍/㎥|ppm)?"


def detect_basis_ko(text: str) -> Optional[EvidenceBasis]:
    for basis, rx in BASIS_CUES_KO:
        if re.search(rx, text):
            return basis
    return None


# ----------------------------------------------------------------------------- scope

def _years(t: str) -> Optional[list]:
    ys = [int(y) for y in re.findall(r"\d{4}", t)]
    return [min(ys), max(ys)] if ys else None


def extract_scope_ko(clause: str) -> tuple[str, Scope, list]:
    scope = Scope()
    notes: list = []
    work = " " + clause + " "

    def cut(m):
        nonlocal work
        work = work[:m.start()] + " " + work[m.end():]

    # conditions: "실험 조건 A에서", "실험실 환경에서", "~경우에만"
    for rx in (re.compile(r"(?P<c>(?:[가-힣A-Za-z0-9]+(?<![은는이가을를의에도])\s){0,2}조건\s?[A-Za-z0-9가-힣]*?)\s?(?:하에서|에서만|에서는|에서|하에)(?=\s)"),
               re.compile(r"(?<![\d가-힣])(?P<c>(?:[가-힣\d]+\s)?[가-힣]+\s?(?:실험|시험|모의실험|시뮬레이션|환경))(?:에서만|에서는|에서)(?=\s)"),
               re.compile(r"(?P<c>[가-힣]+\s?감독)\s?(?:하에서|하에)(?=\s)"),
               re.compile(r"(?P<c>[가-힣A-Za-z0-9\s]{2,30}?)\s?(?P<k>경우에만|경우에는|경우에|경우|때에만|때에는|때만)(?=[\s,])")):
        while (m := rx.search(work)):
            c = norm_ws(m.group("c"))
            if m.groupdict().get("k") and "만" in m.group("k"):
                c = f"only {c}"
            scope.conditions.append(c)
            cut(m)
    # population: "<N>명의 성인을 대상으로 (한 실험에서)", "성인의", "노인에게"
    m = re.search(rf"(?P<p>(?:[\d,]+명의\s)?(?:\d+\s?(?:세|살|개월)\s?(?:이상|이하|미만|초과)?\s)?(?:[가-힣]+(?<![은는이가을를의에도])\s)?{POP_NOUNS})(?:들)?(?:을|를)\s?대상으로(?:\s?(?:한|진행한|실시한|진행된))?(?:\s[가-힣\s]+?(?:실험|시험|연구|조사)에서)?(?=\s)", work)
    pops = []
    if m:
        pops.append(norm_ws(m.group("p")))
        cut(m)
    while (m := re.search(rf"(?<=\s)(?P<p>(?:\d+\s?(?:세|살|개월)\s?(?:이상|이하|미만|초과)?\s)?(?:[가-힣]+(?<![은는이가을를의에도])\s)?{POP_NOUNS})(?:들)?(?:에게서|에게|의|에서|중에서|중|사이에서)(?=\s)", work)):
        pops.append(norm_ws(m.group("p")))
        cut(m)
    if pops:
        scope.population = "; ".join(dict.fromkeys(pops))
    # time
    m = re.search(r"(?P<t>\d{4}년\s?\d{1,2}월(?:\s?\d{1,2}일)?|\d{4}년\s?(?:부터|~|-)\s?\d{4}년|\d{4}\s?[-~]\s?\d{4}년|\d{4}(?:년|시즌|학년도|회계연도|연도)(?:\s?(?:상반기|하반기|[1-4]분기|봄|여름|가을|겨울|초|말|무렵|경))?)(?:\s?(?:새벽|아침|오전|오후|저녁|밤))?(?:까지|부터|에는|에도|에|의|도|동안)?(?=\s|,)", work)
    if m:
        scope.time = norm_ws(m.group("t"))
        scope.time_norm = _years(m.group("t"))
        cut(m)
    else:
        m = re.search(r"(?P<t>작년|지난해|올해|금년|내년|어제|오늘|내일|최근|현재|요즘|지난달|이번\s?달|다음\s?달|지난주|이번\s?주|\d+\s?(?:달|개월|년|주|일)\s?(?:후|뒤|전|만에))(?:에는|에|부터|까지|에도)?(?=\s|,)", work)
        if m:
            scope.time = norm_ws(m.group("t"))
            notes.append("relative-time")
            cut(m)
    # location (gazetteer or administrative suffix)
    m = re.search(rf"(?<=\s)(?P<l>{LOCATIONS})(?:에서는|에서도|에서|의|에)(?=\s)", work)
    if m:
        scope.location = m.group("l")
        cut(m)
    return norm_ws(work).strip(" ,"), scope, notes


# ----------------------------------------------------------------------------- clause parsing

def _split_subject(c: str) -> tuple[Optional[str], str]:
    m = re.match(r"^(?P<s>.+?)\s?건\s+(?P<r>.+)$", c)  # 건 = 것은 (topic contraction)
    if m and m.group("s").strip():
        return m.group("s").strip() + " 것", m.group("r").strip()
    for rx in (r"^(?P<s>.+?)(?:은|는|도)\s+(?P<r>.+)$", r"^(?P<s>.+?)(?:이|가)\s+(?P<r>.+)$"):
        m = re.match(rx, c)
        if m and m.group("s").strip():
            return m.group("s").strip(), m.group("r").strip()
    return None, c


def _clean_subject(s: str) -> str:
    s = re.sub(r"^(?:이|그|저|해당|본)\s+", "", s.strip())
    return norm_ws(s)


def _clean_object(o: str) -> str:
    o = norm_ws(o).strip(" ,.")
    return strip_josa(o) if " " not in o else " ".join(o.split()[:-1] + [strip_josa(o.split()[-1])])


def _q(text: str) -> Optional[Quantity]:
    qs = [q for _, _, q in find_quantities(text) if q.kind != "year"]
    return qs[0] if qs else None


def _change_quantity(rest: str) -> tuple[str, Optional[Quantity]]:
    m = re.search(rf"(?P<a>{_NUMQ})에서\s+(?P<b>{_NUMQ})(?:으로|로)", rest)
    if m:
        a, b = _q(m.group("a")), _q(m.group("b"))
        if a and b:
            if b.unit is None and a.unit:
                b.unit, b.norm_unit, b.dimension = a.unit, a.norm_unit, a.dimension
            if a.unit is None and b.unit:
                a.unit, a.norm_unit, a.dimension = b.unit, b.norm_unit, b.dimension
            q = Quantity(value=b.value, unit=b.unit, raw=m.group(0), norm_value=b.norm_value,
                         norm_unit=b.norm_unit, dimension=b.dimension, kind="from_to",
                         from_value=a.norm_value, to_value=b.norm_value)
            return rest[:m.start()] + rest[m.end():], q
    m = re.search(rf"(?P<q>{_NUMQ})\s?(?:으로|로|까지)\s", rest + " ")
    if m:
        q = _q(m.group("q"))
        if q:
            return rest[:m.start()] + rest[m.end():], q
    m = re.search(rf"(?P<q>{_NUMQ})\s?(?:가량|정도|가까이|이상|넘게)?\s", rest + " ")
    if m:
        q = _q(m.group("q"))
        if q:
            q.kind = "change_pp" if q.norm_unit == "pp" else "change"
            if re.search(r"가량|정도|가까이|약\s", m.group(0)):
                q.approximate = True
            return rest[:m.start()] + rest[m.end():], q
    return rest, None


def parse_clause_ko(c: str) -> Optional[dict]:
    c = norm_ws(c).rstrip(".!").strip()
    c = re.sub(r"^(?:그리고|또한|하지만|그러나|한편|특히|다만|게다가)[,\s]+", "", c)
    c = re.sub(r"^(?:정정|수정|업데이트|알림)\s*:\s*", "", c)
    if not c:
        return None
    # definitions
    for rx in (r"^(?P<s>.+?)(?:이)?란\s+(?P<o>.+?)(?:을|를)\s?(?:말한다|뜻한다|의미한다|가리킨다|말합니다|뜻합니다|의미합니다)",
               r"^(?P<s>.+?)(?:은|는)\s+(?P<o>.+?)(?:을|를)\s?(?:의미한다|뜻한다|말한다|가리킨다|의미합니다|뜻합니다)",
               r"^(?P<s>.+?)(?:은|는)\s+(?P<o>.+?)(?:으로|로)\s?정의(?:된다|한다|됩니다|했다|되었다|됐다)"):
        m = re.match(rx, c)
        if m:
            return dict(s=m.group("s"), p="is_defined_as", o=_clean_object(m.group("o")),
                        ct=ClaimType.DEFINITION, conf=0.85, method="rule:definition@1")
    s, rest = _split_subject(c)
    if s is None:
        # Korean routinely omits the subject (pro-drop); it is attributed to the speaker
        s, rest = IMPLICIT_SUBJECT, c
    neg = bool(NEG.search(rest)) or bool(CANNOT.search(rest))
    # "A가 아니라 B" — the asserted value is B
    contrast = re.match(r"^(?P<n>.+?)(?:이|가)?\s?아니라\s+(?P<p>.+)$", rest)
    notes = []
    if contrast:
        notes.append(f"contrasted with '{norm_ws(contrast.group('n'))}'")
        rest = contrast.group("p")
        neg = bool(re.search(r"지\s?(?:않|못)|없", rest))
    # effect on / no effect on
    m = re.search(r"^(?P<o>.+?)에\s?(?:[가-힣]+\s)?영향을\s?(?:미치|미친|미쳤|준|줬|주|끼치|끼쳤)", rest)
    if m:
        return dict(s=s, p="affects", o=_clean_object(m.group("o")), ct=ClaimType.CAUSAL, conf=0.8,
                    method="rule:affects@1", neg=neg, notes=notes)
    # correlation
    m = re.search(r"^(?P<o>.+?)(?:과|와|하고)\s?(?:(?P<adv>높은|강한|약한|양의|음의|뚜렷한|유의미한)\s)?(?:상관관계가|상관이|관련이|연관이|관계가|연관성이)\s?(?:있|없)", rest) \
        or re.search(r"^(?P<o>.+?)(?:과|와)\s?(?:(?P<adv>밀접하게|강하게)\s)?(?:관련되어|연관되어|관련돼|연관돼)\s?(?:있|없)", rest)
    if m:
        adv = m.groupdict().get("adv") or ""
        return dict(s=s, p="correlates_with", o=_clean_object(m.group("o")), ct=ClaimType.CORRELATIONAL,
                    conf=0.8, method="rule:correlation@1", neg=neg or "없" in rest[m.start():m.end() + 2],
                    direction=-1 if "음의" in adv else (1 if "양의" in adv else 0))
    # causes
    m = re.search(rf"^(?P<o>.+?)(?:을|를)\s?{CAUSE_V}", rest)
    if m:
        return dict(s=s, p="causes", o=_clean_object(m.group("o")), ct=ClaimType.CAUSAL, conf=0.75,
                    method="rule:causes@1", neg=neg)
    # transitive direction: "X는 Y를 (N%) 줄인다/높였다"
    m = re.search(rf"^(?P<o>.+?)(?:을|를)\s+(?P<mid>.*?)(?P<v>{UP_T}|{DOWN_T})", rest)
    if m:
        d = 1 if re.match(UP_T, m.group("v")) else -1
        _, q = _change_quantity(m.group("mid") + " ")
        return dict(s=s, p="increases" if d > 0 else "decreases", o=_clean_object(m.group("o")),
                    ct=ClaimType.CAUSAL, conf=0.8, method="rule:causal-direction@1", direction=d,
                    quantity=q, neg=neg, verb=m.group("v"))
    # comparative: "X는 전년보다 1.8도 낮았다"
    m = re.search(rf"보다\s+(?:약\s)?(?P<q>{_NUMQ})?\s?(?P<v>높았|높다|높은|많았|많다|낮았|낮다|낮은|적었|적다)", rest)
    if m:
        d = 1 if m.group("v").startswith(("높", "많")) else -1
        q = _q(m.group("q") or "")
        if q is not None:
            q.kind = "change_pp" if q.norm_unit == "pp" else "change"
        lvl = _q(rest[:m.start()])
        return dict(s=s, p="increased" if d > 0 else "decreased", o=None, ct=ClaimType.STATISTICAL,
                    conf=0.75, method="rule:comparative@1", direction=d, quantity=q, neg=neg,
                    notes=[f"level {lvl.raw}"] if lvl else [])
    # intransitive change: "X는 (A에서 B로 | N%로 | N%) 증가했다"
    m = re.search(rf"(?P<v>{UP_I}|{DOWN_I})", rest)
    if m:
        d = 1 if re.match(UP_I, m.group("v")) else -1
        _, q = _change_quantity(rest[:m.start()] + " ")
        return dict(s=s, p="increased" if d > 0 else "decreased", o=None, ct=ClaimType.STATISTICAL,
                    conf=0.8, method="rule:change@1", direction=d, quantity=q, neg=neg, verb=m.group("v"))
    # recorded value: "X는 N에 달했다 / N을 기록했다"
    m = VALUE_VERB.search(rest)
    if m:
        q = _q(rest[:m.start()])
        if q is not None:
            return dict(s=s, p="has_value", o=None, ct=ClaimType.STATISTICAL, conf=0.8,
                        method="rule:value-verb@1", quantity=q, neg=neg)
    # requires
    m = re.search(r"^(?P<o>.+?)(?:이|가|을|를)\s?필요(?:하|로\s?하|로\s?한|합)", rest)
    if m:
        return dict(s=s, p="requires", o=_clean_object(m.group("o")), ct=ClaimType.EMPIRICAL, conf=0.7,
                    method="rule:requires@1", neg=neg)
    # copula: "X는 Y(이)다" / value "X는 N단위였다"
    if COPULA_END.search(rest):
        o = COPULA_END.sub("", rest).strip()
        q = _q(o)
        if q is not None and not re.search(r"[가-힣]{2,}", re.sub(_NUMQ, " ", o)):
            return dict(s=s, p="has_value", o=None, ct=ClaimType.STATISTICAL, conf=0.8,
                        method="rule:value@1", quantity=q, neg=neg)
        ct = ClaimType.OPINION if EVALUATIVE.search(o) else ClaimType.EMPIRICAL
        return dict(s=s, p="is", o=_clean_object(o), ct=ct, conf=0.65, method="rule:copula@1",
                    neg=neg, quantity=q, notes=notes)
    # negative copula: "X는 Y가 아니다"
    m = re.match(r"^(?P<o>.+?)(?:이|가)?\s?아니(?:다|었다|에요|었습니다|ㅂ니다|입니다)", rest)
    if m:
        return dict(s=s, p="is", o=_clean_object(m.group("o")), ct=ClaimType.EMPIRICAL, conf=0.65,
                    method="rule:copula@1", neg=True)
    # existence: "X는 Y가 있다/없다"
    m = re.match(r"^(?P<o>.+?)(?:이|가)\s?(?P<v>있|없)", rest)
    if m:
        return dict(s=s, p="has", o=_clean_object(m.group("o")), ct=ClaimType.EMPIRICAL, conf=0.6,
                    method="rule:existence@1", neg=m.group("v") == "없")
    # generic transitive verb: "X는 Y를 V…"
    m = re.match(r"^(?P<o>.+?)(?:을|를)\s+(?P<v>[가-힣]+)", rest)
    if m:
        q = _q(m.group("o"))
        return dict(s=s, p=verb_stem(m.group("v")), o=_clean_object(m.group("o")), ct=ClaimType.EMPIRICAL,
                    conf=0.5, method="rule:generic-verb@1", neg=neg, quantity=q)
    # final predicate with a complement but no object marker: "X는 2025시즌을 3위로 마쳤다"
    m = re.match(r"^(?P<o>.+?)\s+(?P<v>[가-힣]+(?:다|요|니다))$", rest)
    if m and not COPULA_END.search(rest):
        return dict(s=s, p=verb_stem(m.group("v")), o=_clean_object(m.group("o")), ct=ClaimType.EMPIRICAL,
                    conf=0.45, method="rule:final-predicate@1", neg=neg, quantity=_q(m.group("o")))
    # bare predicate: "(나는) 퇴사한다"
    m = re.match(r"^(?P<v>[가-힣]+?)(?:한다|합니다|했다|했습니다|하였다|할\s?(?:것이다|예정이다|계획이다))\.?$", rest)
    if m:
        return dict(s=s, p=m.group("v"), o=None, ct=ClaimType.EMPIRICAL, conf=0.5,
                    method="rule:bare-predicate@1", neg=neg)
    return None


def verb_stem(word: str) -> str:
    """Strip common tense/politeness endings from a Korean verb for display."""
    return re.sub(r"(?:했습니다|하였습니다|합니다|했다|한다|하였다|었습니다|았습니다|였습니다|됐다|된다|었다|았다|였다|해야|하고|하여|해서|하는|한|할|했|하|다)$", "", word) or word


def _event(clause: str) -> Optional[dict]:
    m = re.match(rf"^(?P<s>.+?)(?:은|는|이|가)\s+(?P<t>\d{{4}}년(?:\s?\d{{1,2}}월)?(?:\s?\d{{1,2}}일)?)(?:\s?(?:봄|여름|가을|겨울|초|말|무렵|경))?(?:에)?\s+(?:(?P<place>[가-힣A-Za-z]+)에서\s+)?(?:[가-힣]+(?:이|가|을|를)\s+)?(?P<v>{_EVENT_RE})", clause)
    if not m:
        return None
    verb = EVENT_V[m.group("v")]
    year = float(re.findall(r"\d{4}", m.group("t"))[0])
    out = [dict(s=m.group("s"), p=f"{verb}_in", o=m.group("t"), ct=ClaimType.EMPIRICAL, conf=0.85,
                method="rule:event-time@1",
                quantity=Quantity(value=year, raw=m.group("t"), kind="year", norm_value=year, dimension="year"),
                neg=bool(NEG.search(clause[m.end():])))]
    if m.group("place"):
        out.append(dict(s=m.group("s"), p=f"{verb}_at", o=m.group("place"), ct=ClaimType.EMPIRICAL,
                        conf=0.75, method="rule:event-place@1", neg=False))
    return {"multi": out}


def split_clauses_ko(s: str) -> list[tuple[str, int, Optional[int], bool]]:
    s = s.strip()
    m = re.match(r"^(?P<b>.+?)(?:기|었기|았기|였기)?\s?때문에[,\s]+(?P<a>.+)$", s)
    if m and len(m.group("b").split()) >= 2:
        b = re.sub(r"(?:했|었|았|였|하|되|됐)$", lambda x: x.group(0), m.group("b").strip())
        if not re.search(r"다$", b):
            b = b + "다"
        return [(m.group("a"), 0, 1, False), (b, 1, None, False)]
    parts = re.split(r",\s*(?=(?:하지만|그러나|반면에?|그리고)\s)|(?<=지만),?\s+|;\s+", s)
    out = []
    for gi, part in enumerate(parts):
        qual = gi > 0 and bool(re.match(r"^(?:하지만|그러나|반면)", part.strip()))
        if gi > 0 and parts[gi - 1].endswith("지만"):
            qual = True
        if part.endswith("지만"):
            part = part[:-2] + "다"
        # shared-subject coordination: "X는 A를 높이고 B를 줄인다"
        mm = re.match(r"^(?P<s>.+?(?:은|는|이|가)\s+)(?P<a>.+?(?:을|를)\s+[가-힣]+?)고,?\s+(?P<b>.+?(?:을|를)\s+.+)$", part)
        if mm:
            out.append((mm.group("s") + mm.group("a") + "다", gi, None, qual))
            out.append((mm.group("s") + mm.group("b"), gi, None, False))
            continue
        out.append((part, gi, None, qual))
    return out


def extract_sentence_ko(raw: str, sent_index: int, span: tuple, doc_basis=None,
                        paragraph_basis=None) -> list[Draft]:
    raw = raw.strip()
    if raw.endswith("?") or len(raw.split()) < 2:
        return []
    work = raw
    attribution = Attribution()
    claim_override = None
    modality_override = None
    m = re.match(r'^(?P<sp>.+?)(?:은|는|이|가)\s+(?:[^"“]{0,40}?\s)?["“](?P<q>[^"”]+)["”]\s*(?:이)?(?:라고|고)\s*(?:말했|밝혔|주장했|강조했|덧붙였|설명했|전했|말했습니다|밝혔습니다)', work) \
        or re.match(r'^(?P<sp>.+?)(?:은|는|이|가)\s*["“](?P<q>[^"”]+)["”]\s*(?:이)?(?:라고|고)\s*(?:말했|밝혔|주장했|강조했|덧붙였|설명했|전했|말했습니다|밝혔습니다)', work) \
        or re.match(r'^["“](?P<q>[^"”]+)["”]\s*(?:이)?(?:라고|고)\s*(?P<sp>.+?)(?:은|는|이|가)\s*(?:말했|밝혔|주장했|강조했|덧붙였)', work)
    if m:
        attribution = Attribution(speaker=norm_ws(m.group("sp")), kind="quoted", quote=m.group("q").strip())
        work = m.group("q").strip()
    else:
        m = re.match(r"^(?P<sp>[^,]+?)에\s?따르면[,\s]+(?P<rest>.+)$", work)
        if m:
            attribution = Attribution(speaker=norm_ws(m.group("sp")), kind="reported")
            work = m.group("rest")
        else:
            m = re.match(r"^(?P<sp>.+?)(?:은|는|이|가)\s+(?P<rest>.+?)(?:다|이라|라)고\s+(?P<v>밝혔|발표했|보고했|말했|주장했|추정했|전했|설명했|강조했|예측했|분석했|추산했|보도했)", work)
            if m and len(m.group("sp").split()) <= 6:
                attribution = Attribution(speaker=norm_ws(m.group("sp")), kind="reported")
                rest = m.group("rest")
                # "…520km라고 밝혔다": a quoted noun predicate needs the copula back
                work = rest + ("이다" if m.group(0)[len(m.group("sp")):].find(rest + "라고") >= 0
                               or not re.search(r"[가-힣]$", rest) else "다")
                if m.group("v").startswith(("예측",)):
                    claim_override = ClaimType.PREDICTION
                if m.group("v").startswith(("추정", "추산")):
                    modality_override = Modality.POSSIBLE
    if attribution.kind == "author":
        # "연구원은 X가 1618년 무렵에 마무리된 것으로 판단했다" (reported judgement)
        m = re.match(r"^(?P<sp>.+?)(?:은|는)\s+(?P<rest>.+?)\s?것으로\s+(?P<v>판단했|보고\s?있|추정했|분석했|평가했|결론지었|파악했|알려졌|확인됐)", work)
        if m and len(m.group("sp").split()) <= 5:
            rest = m.group("rest")
            rest = re.sub(r"된$", "되었다", rest)
            rest = re.sub(r"(?<![가-힣])한$|한$", "했다", rest) if not rest.endswith("되었다") else rest
            rest = re.sub(r"인$", "이다", rest)
            attribution = Attribution(speaker=norm_ws(m.group("sp")), kind="reported")
            work = rest
            if m.group("v").startswith(("추정", "보고")):
                modality_override = Modality.POSSIBLE
    if OPINION_START.search(work) or OPINION_END.search(work):
        claim_override = ClaimType.OPINION
        work = OPINION_START.sub("", work)
        work = re.sub(r"(?:라고|다고|고)\s?(?:생각한다|생각합니다|생각해요|믿는다|믿습니다|느낀다|느낍니다|본다|봅니다)\.?$", "다", work)
    marker = None
    m = INFERENCE.match(work)
    if m:
        marker = norm_ws(m.group(0)).strip(", ")
        work = work[m.end():]
    sent_basis = detect_basis_ko(raw)
    drafts: list[Draft] = []
    for clause, group, caused_by, qual in split_clauses_ko(work):
        ev = _event(clause)
        if ev:
            parsed_list, scope, scope_notes = ev["multi"], Scope(), []
            rest_scope_src = clause
            _, scope_extra, _ = extract_scope_ko(rest_scope_src)
            scope.location = scope_extra.location
            scope.population = scope_extra.population
        else:
            stripped, scope, scope_notes = extract_scope_ko(clause)
            parsed = parse_clause_ko(stripped)
            if parsed is None:
                if len(stripped) < 4:
                    continue
                parsed = dict(s=stripped, p="asserts", o=None, ct=ClaimType.EMPIRICAL, conf=0.3,
                              method="rule:fallback@1")
            parsed_list = [parsed]
        for parsed in parsed_list:
            ct = parsed["ct"]
            modality = Modality.ASSERTED
            if POSSIBLE.search(clause) and not CANNOT.search(clause):
                modality = Modality.POSSIBLE
            if PREDICTED.search(clause) and ct not in (ClaimType.DEFINITION, ClaimType.MATHEMATICAL):
                modality = Modality.PREDICTED
                if ct != ClaimType.CAUSAL:
                    ct = ClaimType.PREDICTION
            if modality_override and modality == Modality.ASSERTED:
                modality = modality_override
            if claim_override:
                ct = claim_override
            elif NORMATIVE.search(clause) and ct not in (ClaimType.DEFINITION,):
                ct = ClaimType.NORMATIVE
            if attribution.kind in ("reported", "quoted") and modality == Modality.ASSERTED:
                modality = Modality.REPORTED
            subj = _clean_subject(parsed["s"])
            quantifier = None
            qm = re.match(r"^(모든|모두|대부분의|대부분|많은|일부|상당수의|여러)\s+", subj)
            if qm:
                quantifier = {"모든": "all", "모두": "all", "대부분의": "most", "대부분": "most",
                              "많은": "many", "일부": "some", "상당수의": "many", "여러": "some"}[qm.group(1)]
                subj = subj[qm.end():]
            d = Draft(
                subject=subj.lower(), predicate=parsed["p"],
                object=parsed.get("o").lower() if parsed.get("o") else None, claim_type=ct,
                modality=modality, polarity=Polarity.NEGATIVE if parsed.get("neg") else Polarity.POSITIVE,
                direction=parsed.get("direction", 0), quantity=parsed.get("quantity"),
                quantifier=quantifier, scope=Scope(**scope.to_dict()),
                attribution=Attribution(**attribution.to_dict()), quote=raw, quote_span=span,
                sentence_index=sent_index, clause=norm_ws(clause),
                surface={"subject": norm_ws(parsed["s"]), "predicate": parsed.get("verb") or parsed["p"],
                         "object": parsed.get("o")},
                stated_basis=sent_basis or paragraph_basis or doc_basis,
                confidence=round(parsed["conf"] - (0.05 if len(drafts) else 0), 2),
                method=f"{EXTRACTOR_ID}/{parsed['method']}",
                notes=list(scope_notes) + parsed.get("notes", []), inference_marker=marker,
                group=group, caused_by=caused_by, qualifies_previous=qual,
            )
            if d.quantity is not None:
                d.scope.units = d.quantity.unit
            drafts.append(d)
    # coordinated clauses share trailing scope
    for d in drafts:
        for other in drafts:
            if other is d or other.group != d.group:
                continue
            for k in ("time", "time_norm", "location", "population"):
                if getattr(d.scope, k) is None and getattr(other.scope, k) is not None:
                    setattr(d.scope, k, getattr(other.scope, k))
    return drafts


def extract_passage_text_ko(text: str, doc_basis: Optional[EvidenceBasis] = None) -> list[Draft]:
    paragraph_basis = detect_basis_ko(text)
    drafts: list[Draft] = []
    for i, (s, e) in enumerate(split_sentences(text)):
        drafts.extend(extract_sentence_ko(text[s:e], i, (s, e), doc_basis, paragraph_basis))
    return drafts
