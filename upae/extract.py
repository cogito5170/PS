"""Deterministic (rule-based) English proposition extractor.

Pipeline per passage:  sentences → attribution / inference-marker stripping →
clause splitting (compound sentences, "because") → scope extraction (time,
location, population, conditions) → predicate pattern matching → modality,
polarity, quantity, quantifier, claim type → confidence.

Every draft keeps the verbatim sentence (``quote``) and its span inside the
passage.  Patterns are listed in ``PATTERNS`` order; the first match wins.  When
no pattern matches, a low-confidence fallback proposition is emitted and marked
for review rather than silently dropped.

Non-English passages are not handled here (see pipeline: translation alignment
or a model provider).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .models import Attribution, ClaimType, EvidenceBasis, Modality, Polarity, Quantity, Scope
from .textutil import normalize_phrase, norm_ws, split_sentences
from .units import YEAR_RE, find_quantities

EXTRACTOR_ID = "rule-en@1"

MONTHS = ("January|February|March|April|May|June|July|August|September|October|"
          "November|December")

UP_VERBS = ("increases|increased|increase|raises|raised|raise|boosts|boosted|boost|improves|"
            "improved|improve|doubles|doubled|double|triples|tripled|elevates|elevated|"
            "strengthens|strengthened|accelerates|accelerated|lifts|lifted|rose|rises|rise|"
            "grew|grows|grow|climbed|climbs|jumped|jumps|surged|surges|expanded|expands|"
            "gained|gains|went up|goes up")
DOWN_VERBS = ("reduces|reduced|reduce|lowers|lowered|lower|decreases|decreased|decrease|cuts|"
              "cut|halves|halved|halve|diminishes|diminished|weakens|weakened|slows|slowed|"
              "curbs|curbed|prevents|prevented|prevent|eliminates|eliminated|fell|falls|fall|"
              "dropped|drops|drop|declined|declines|decline|shrank|shrinks|shrink|plummeted|"
              "plunged|went down|goes down")
CAUSE_VERBS = ("causes|caused|cause|leads to|led to|lead to|results in|resulted in|result in|"
               "triggers|triggered|trigger|produces|produced|drives|drove|contributes to|"
               "contributed to|affects|affected|affect|influences|influenced|influence")
REQUIRE_VERBS = "requires|required|require|depends on|depended on|depend on|needs|needed"
CHANGE_INTRANSITIVE = {"rose", "rises", "rise", "grew", "grows", "grow", "climbed", "climbs",
                       "jumped", "jumps", "surged", "surges", "fell", "falls", "fall",
                       "dropped", "drops", "drop", "declined", "declines", "decline",
                       "shrank", "shrinks", "shrink", "plummeted", "plunged", "went up",
                       "goes up", "went down", "goes down", "increased", "increases",
                       "decreased", "decreases", "doubled", "halved", "tripled",
                       "expanded", "gained"}
AUX = (r"(?P<aux>(?:(?:does|do|did|has|have|had|can|could|may|might|will|would|should|must|"
       r"is likely to|are likely to|was likely to|is expected to|are expected to|"
       r"is projected to|appears to|appear to|seems to|seem to|tends to|tend to|"
       r"was found to|were found to|is known to|is believed to|has been shown to|"
       r"have been shown to|is set to)\s+)*(?:not\s+|never\s+|no longer\s+)?)")

EVENT_VERBS = ("born|founded|established|died|invented|discovered|published|built|completed|"
               "opened|launched|signed|elected|introduced|created|released|ratified|enacted")

OPINION_MARKERS = re.compile(
    r"^(?:i|we)\s+(?:think|believe|feel|reckon|suspect|guess)\b|^in my (?:opinion|view)\b|"
    r"^personally\b|^frankly\b|^honestly\b|^arguably\b|^to me\b", re.I)
EVALUATIVE = re.compile(
    r"\b(best|worst|greatest|terrible|awful|wonderful|excellent|amazing|beautiful|ugly|"
    r"overrated|underrated|disgraceful|brilliant|stupid|pointless|outrageous|fantastic|"
    r"horrible|admirable|shameful|boring|exciting|delicious)\b", re.I)
NORMATIVE = re.compile(r"\b(should|ought to|must not|must|need to|needs to|has to|have to)\b", re.I)
HEDGES = re.compile(r"\b(may|might|could|possibly|perhaps|potentially|suggests?|suggested|"
                    r"appears? to|seems? to|is thought to|is believed to)\b", re.I)
PROBABLE = re.compile(r"\b(likely|probably|presumably)\b", re.I)
FUTURE = re.compile(r"\b(will|is expected to|are expected to|is projected to|are projected to|"
                    r"is forecast to|are forecast to|is set to|are set to|is going to|are going to)\b", re.I)
NEGATION = re.compile(r"\b(not|never|no longer|cannot)\b|n't\b", re.I)
QUANTIFIER = re.compile(r"^(all|every|each|most|many|some|several|few|no|none of the|none)\s+", re.I)

REPORT_VERBS = ("said|says|say|reported|reports|report|claimed|claims|claim|stated|states|state|"
                "argued|argues|argue|found|finds|find|showed|shows|show|concluded|concludes|"
                "conclude|estimated|estimates|estimate|announced|announces|noted|notes|wrote|"
                "writes|suggested|suggests|suggest|confirmed|confirms|confirm|warned|warns|"
                "insisted|insists|maintains|maintained|asserted|asserts|believes|believe|"
                "demonstrated|demonstrates|indicated|indicates|revealed|reveals|added|adds|"
                "told reporters|explained|explains|observed|observes|predicted|predicts|"
                "hypothesized|hypothesised|hypothesize|hypothesise|record|records|recorded|"
                "document|documents|documented")
STUDY_WORDS = re.compile(r"\b(study|studies|trial|trials|experiment|survey|poll|analysis|"
                         r"meta-analysis|review|report|census|data|dataset|statistics|"
                         r"researchers|scientists|investigators|records|figures|paper|model)\b", re.I)

BASIS_CUES = [
    (EvidenceBasis.REVIEW, r"\b(meta-analys[ie]s|systematic review)"),
    (EvidenceBasis.EXPERIMENTAL, r"\b(randomi[sz]ed|controlled trial|clinical trial|experiment(?:al|s)?\b|placebo)"),
    (EvidenceBasis.OBSERVATIONAL, r"\b(observational|cohort|cross-sectional|case-control|"
                                  r"correlat\w*|associated with|linked to|link between)"),
    (EvidenceBasis.SURVEY, r"\b(survey|poll|questionnaire|respondents)\b"),
    (EvidenceBasis.DATASET, r"\b(census|dataset|official statistics|statistics show|data from|records show)"),
    (EvidenceBasis.ANECDOTAL, r"\b(anecdot\w*|in my experience|i noticed|my friend|a neighbour|a neighbor)"),
    (EvidenceBasis.EXPERT_OPINION, r"\b(experts? (?:say|believe|agree)|according to experts)"),
]

INFERENCE_MARKERS = re.compile(
    r"^(?:(?:and\s+)?(?:therefore|thus|hence|consequently|so|accordingly|it follows that|"
    r"this (?:proves|shows|demonstrates|means|confirms|suggests|implies)(?: that)?|"
    r"which (?:proves|shows|means|demonstrates|confirms)(?: that)?|"
    r"these (?:results|findings|data) (?:prove|show|demonstrate|mean|suggest)(?: that)?|"
    r"as a result|clearly))\s*,?\s+", re.I)
INLINE_INFERENCE = re.compile(
    r",?\s+(?:which|this|and this|and therefore|so)\s+(?:proves|shows|means|demonstrates|confirms)\s+(?:that\s+)?", re.I)

POPULATION_NOUNS = ("patients|adults|children|women|men|students|pupils|mice|rats|participants|"
                    "people|users|workers|households|firms|companies|smokers|non-smokers|"
                    "adolescents|infants|subjects|employees|teenagers|seniors|voters|residents|"
                    "farmers|cells|animals|volunteers|drivers|consumers|schools|hospitals|"
                    "countries|cities|men and women|individuals|respondents|"
                    "speakers|readers|athletes|soldiers|teachers|nurses|doctors|"
                    "cases|samples|plants|trees|fish|birds|cows|pigs|dogs|cats")

PRONOUNS = {"it", "they", "this", "that", "these", "those", "he", "she", "its", "them", "which",
            "그것", "이것", "저것", "그", "그녀", "그들", "이들"}

NON_LOCATIONS = {"january", "february", "march", "april", "may", "june", "july", "august",
                 "september", "october", "november", "december", "policy", "phase", "table",
                 "figure", "chapter", "section", "experiment", "study", "the"}


@dataclass
class Draft:
    subject: str
    predicate: str
    object: Optional[str]
    claim_type: ClaimType
    modality: Modality = Modality.ASSERTED
    polarity: Polarity = Polarity.POSITIVE
    direction: int = 0
    quantity: Optional[Quantity] = None
    quantifier: Optional[str] = None
    scope: Scope = field(default_factory=Scope)
    attribution: Attribution = field(default_factory=Attribution)
    quote: str = ""
    quote_span: tuple = (0, 0)
    sentence_index: int = 0
    clause: str = ""
    surface: dict = field(default_factory=dict)
    stated_basis: Optional[EvidenceBasis] = None
    confidence: float = 0.0
    method: str = ""
    notes: list = field(default_factory=list)
    inference_marker: Optional[str] = None
    group: int = 0                 # clause group id inside sentence (compound split)
    caused_by: Optional[int] = None  # index of draft that this draft is caused by ("because")
    ambiguous: list = field(default_factory=list)
    qualifies_previous: bool = False


# --------------------------------------------------------------------- scope extraction

_TIME_RE = re.compile(
    rf"\b(?P<prep>in|during|since|by|from|between|as of|until|before|after|throughout|over)\s+"
    rf"(?P<t>(?:the\s+)?(?:(?:early|late|mid)[- ])?(?:(?:{MONTHS})\s+)?(?:\d{{4}}s?)"
    rf"(?:\s*(?:-|–|to|and)\s*(?:(?:{MONTHS})\s+)?\d{{4}})?)", re.I)
_REL_TIME_RE = re.compile(r"\b(last year|this year|next year|last month|this month|recently|"
                          r"currently|nowadays|today|at present|these days)\b", re.I)
_COND_RES = [
    re.compile(r"(?:,\s*)?\b(?:but\s+)?only\s+(?P<c>(?:in|for|when|if|under|among|at|with)\s+[^,.;]+)", re.I),
    re.compile(r"(?:,\s*)?\bunder\s+(?P<c>[^,.;]+?)(?=\s*(?:,|\.|;|$|\band\b|\bbut\b))", re.I),
    re.compile(r"(?:,\s*)?\b(?P<k>if|when|unless|provided that|as long as|whenever)\s+(?P<c>[^,.;]+)", re.I),
    re.compile(r"(?:,\s*)?\bat\s+(?P<c>sea level|room temperature|high altitudes?|low altitudes?|"
               r"(?:a |an )?(?:[\w-]+\s+){0,3}(?:pressure|temperature|altitude|elevation|dose|doses|dosage|speed|concentration))\b", re.I),
    re.compile(r"(?:,\s*)?\bin\s+(?P<c>(?:a|an|the)\s+(?:[\w-]+\s+){0,3}(?:trial|experiment|laboratory|lab|simulation|setting|pilot|sample|model))\b", re.I),
    re.compile(r"(?:,\s*)?\bwith(?P<c>(?:out)?\s+(?:[\w-]+\s+){0,2}(?:treatment|supervision|irrigation|fertili[sz]er|subsidies|tutoring|insulation))\b", re.I),
]
# modifiers before the population noun must be lower-case words or numbers and
# not verbs, so "in Norvik employs 900 workers" is not read as a population
_POP_RE = re.compile(
    rf"\b(?i:among|in|for|of)\s+(?P<p>(?:(?!(?:is|are|was|were|has|have|had|employs|employ|"
    rf"employed|include|includes)\b)[a-z\d][\w-]*\s+){{0,3}}?(?i:{POPULATION_NOUNS})"
    rf"(?:\s+(?i:aged|over|under|with|from)\s+[\w\d-]+(?:\s+(?:and|to)\s+[\w\d-]+)?)?)\b")
_LOC_RE = re.compile(r"\b(?:in|across|throughout|within)\s+(?P<l>(?:the\s+)?(?:[A-Z][\w.-]+)(?:\s+(?:of\s+)?[A-Z][\w.-]+){0,3})")


def _year_range(t: str) -> Optional[list]:
    years = [int(y) for y in re.findall(r"\d{4}", t)]
    if not years:
        return None
    decade = re.search(r"(\d{4})s\b", t)
    if decade and len(years) == 1:
        return [years[0], years[0] + 9]
    return [min(years), max(years)]


def extract_scope(clause: str) -> tuple[str, Scope, list[str]]:
    """Remove scope phrases from the clause; return (clause_without_scope, scope, notes)."""
    scope = Scope()
    notes: list[str] = []
    work = clause

    def cut(m):
        nonlocal work
        work = work[:m.start()] + " " + work[m.end():]

    for rx in _COND_RES:
        while True:
            m = rx.search(work)
            if not m:
                break
            c = norm_ws(m.group("c"))
            kw = m.groupdict().get("k")
            scope.conditions.append(f"{kw.lower()} {c}" if kw else c)
            cut(m)
    m = _TIME_RE.search(work)
    if m:
        scope.time = norm_ws(m.group("t"))
        scope.time_norm = _year_range(m.group("t"))
        cut(m)
    else:
        m = _REL_TIME_RE.search(work)
        if m:
            scope.time = m.group(1).lower()
            notes.append("relative-time")
            cut(m)
    pops = []
    while (m := _POP_RE.search(work)):
        pops.append(normalize_phrase(m.group("p")))
        cut(m)
    if pops:
        scope.population = "; ".join(dict.fromkeys(pops))
    for m in _LOC_RE.finditer(work):
        cand = m.group("l")
        first = cand.split()[0].lower()
        if first in NON_LOCATIONS or (first == "the" and len(cand.split()) > 1 and cand.split()[1].lower() in NON_LOCATIONS):
            continue
        if m.start() == 0:
            continue
        cand = cand.rstrip(".,;:")
        scope.location = cand[4:] if cand.lower().startswith("the ") else cand
        cut(m)
        break
    work = norm_ws(re.sub(r"\s+([,.;])", r"\1", work)).strip(" ,;")
    return work, scope, notes


# --------------------------------------------------------------------- predicate patterns

def _mk(rx: str) -> re.Pattern:
    return re.compile(rx, re.I)


DEF_PATTERNS = [
    _mk(r"^(?P<s>.+?)\s+(?:is|are|was|were)\s+(?:officially\s+|commonly\s+|usually\s+)?defined\s+as\s+(?P<o>.+)$"),
    _mk(r"^(?:we|the authors?|this (?:paper|report|study|book|chapter))\s+defines?\s+(?P<s>.+?)\s+as\s+(?P<o>.+)$"),
    _mk(r"^(?P<s>.+?)\s+(?:is|are)\s+measured\s+as\s+(?P<o>.+)$"),
    _mk(r"^(?P<s>.+?)\s+refers?\s+to\s+(?P<o>.+)$"),
    _mk(r"^by\s+(?P<s>.+?),?\s+(?:we|i)\s+mean\s+(?P<o>.+)$"),
    _mk(r"^(?P<s>[^,]+?)\s+means\s+(?P<o>.+)$"),
]
CORR_PATTERNS = [
    _mk(rf"^(?P<s>.+?)\s+(?:is|are|was|were|has been|have been)\s+{AUX}(?P<adv>(?:strongly|weakly|positively|negatively|inversely|significantly|closely|statistically)\s+)*"
        r"(?:associated|correlated|linked|connected)\s+(?:with|to)\s+(?P<o>.+)$"),
    _mk(rf"^(?P<s>.+?)\s+{AUX}(?P<adv>(?:strongly|weakly|positively|negatively|inversely)\s+)*correlates?\s+with\s+(?P<o>.+)$"),
    _mk(r"^there\s+(?:is|was|exists)\s+(?P<neg>no\s+)?(?:a\s+)?(?P<adv>(?:strong|weak|positive|negative|inverse|significant|clear)\s+)*"
        r"(?:correlation|association|link)\s+between\s+(?P<s>.+?)\s+and\s+(?P<o>.+)$"),
]
MATH_RE = _mk(r"^(?P<lhs>[\d.,\s]+(?:\s*(?:[+\-*/×x÷^]|plus|minus|times|divided by|multiplied by)\s*[\d.,]+)+)\s*(?:=|equals|is equal to|is|makes|gives)\s*(?P<rhs>-?[\d.,]+)\s*$")
_DATE = rf"(?:(?:\d{{1,2}}\s+)?(?:{MONTHS})\s+(?:\d{{1,2}},?\s+)?)?\d{{4}}"
# up to four words may separate the verb from the date ("opened to boat traffic on 14 May 1831")
EVENT_RE = _mk(rf"^(?P<s>.+?)\s+(?:was|were|is|are|had been)\s+(?P<neg>not\s+)?(?P<v>{EVENT_VERBS})(?:\s+(?!in\b|on\b)[\w-]+){{0,4}}?\s+(?:in|on)\s+(?P<o>{_DATE})\b(?P<rest>.*)$")
EVENT_ACTIVE_RE = _mk(rf"^(?P<s>.+?)\s+(?P<neg>did not\s+)?(?P<v>died|opened|launched|closed|began|started|ended|collapsed)(?:\s+(?!in\b|on\b)[\w-]+){{0,4}}?\s+(?:in|on)\s+(?P<o>{_DATE})\b(?P<rest>.*)$")
# where an event took place: "was signed in the harbour town of Orlavy (in 1712)"
EVENT_PLACE_RE = re.compile(rf"^(?P<s>.+?)\s+(?:was|were)\s+(?P<v>(?i:{EVENT_VERBS}))\s+(?i:in|at)\s+(?:(?i:the)\s+)?(?:[a-z][\w-]*\s+){{0,3}}?(?:(?i:of)\s+)?(?P<place>[A-Z][\w-]+(?:\s+[A-Z][\w-]+)*)")
NOEFFECT_RE = _mk(r"^(?P<s>.+?)\s+(?:has|had|have|showed|shows|produced|produces)\s+(?:no|little)\s+(?:significant\s+|measurable\s+|detectable\s+)?(?:effect|impact|influence)\s+on\s+(?P<o>.+)$")
NODIFF_RE = _mk(r"^(?:.*?\b(?:found|showed|shows|reported|observed|saw)\s+)?(?:there\s+(?:was|is)\s+)?no\s+(?:significant\s+|statistically significant\s+|meaningful\s+)?difference\s+in\s+(?P<o>.+?)\s+between\s+(?P<s>.+?)\s+and\s+(?P<b>.+?)(?:\s+(?:after|over|at|in|during)\b.*)?$")
DIR_RE = _mk(rf"^(?P<s>.+?)\s+{AUX}(?P<v>{UP_VERBS}|{DOWN_VERBS})\b\s*(?P<o>.*)$")
CAUSE_RE = _mk(rf"^(?P<s>.+?)\s+{AUX}(?P<v>{CAUSE_VERBS})\b\s*(?P<o>.+)$")
REQUIRE_RE = _mk(rf"^(?P<s>.+?)\s+{AUX}(?P<v>{REQUIRE_VERBS})\b\s*(?P<o>.+)$")
HASVAL_RE = _mk(r"^(?P<s>.+?)\s+(?:has|had|have)\s+(?:a|an)\s+(?P<attr>[\w\s-]+?)\s+of\s+(?P<o>.+)$")
VALUE_RE = _mk(r"^(?P<s>.+?)\s+(?:(?:is|are|was|were)(?:\s+(?:now|currently|still|only|just))?(?P<neg>\s+not)?|stands at|stood at|reached|reaches|"
               r"totals|totaled|totalled|amounts to|amounted to|equals|equalled|equaled|averaged|"
               r"averages|measures|measured|came to|hit|hits|remained at|remains at|cost|costs|"
               r"weighs|weighed|spans|spanned|lasted|lasts)\s+(?P<o>.+)$")
COPULA_RE = _mk(r"^(?P<s>.+?)\s+(?P<v>is|are|was|were|has|have|had|contains|contain|consists of|"
                r"belongs to|lies in|is located in|borders|includes|include)(?P<neg>\s+not|n't)?\s+(?P<o>.+)$")
GENERIC_VERB_RE = _mk(r"^(?P<s>(?:[\w'-]+\s+){0,6}?[\w'-]+)\s+(?P<v>[a-z]+(?:s|ed))\b\s+(?P<o>.+)$")


def strip_month_may(text: str) -> str:
    """Remove the month name "May" from dates so it is not read as the modal verb."""
    return re.sub(r"\b(?:\d{1,2}(?:st|nd|rd|th)?\s+May|May\s+\d{1,2}(?:st|nd|rd|th)?\b|May\s+\d{4}|(?:early|late|mid-?)\s*May|(?:in|of|since|until|by)\s+May\b)", " ", text)


def _strip_aux_modality(aux: str) -> tuple[Modality, Polarity, list[str]]:
    aux = (aux or "").lower()
    notes = []
    pol = Polarity.NEGATIVE if re.search(r"\b(not|never|no longer)\b", aux) else Polarity.POSITIVE
    mod = Modality.ASSERTED
    if re.search(r"\b(may|might|could|appears? to|seems? to|tends? to)\b", aux):
        mod = Modality.POSSIBLE
    elif re.search(r"\blikely to\b", aux):
        mod = Modality.PROBABLE
    elif re.search(r"\b(will|is expected to|are expected to|is projected to|is set to)\b", aux):
        mod = Modality.PREDICTED
    if re.search(r"\bcan\b", aux):
        notes.append("ability-modal 'can'")
    return mod, pol, notes


def _split_quantity(text: str) -> tuple[str, Optional[Quantity], Optional[tuple]]:
    """Find the main quantity in an object phrase; return (text_without_q, q, from_to)."""
    num = r"[$€£]?\d[\d,]*(?:\.\d+)?(?:\s?%)?"
    ft = re.search(rf"\bfrom\s+(?P<a>{num}(?:\s+(?:percent|per cent|million|billion|thousand))?)\s+to\s+(?P<b>{num}(?:\s+(?:percent|per cent|million|billion|thousand))?)", text, re.I)
    if ft:
        qa = find_quantities(ft.group("a"))
        qb = find_quantities(ft.group("b"))
        if qa and qb:
            a, b = qa[0][2], qb[0][2]
            if b.unit is None and a.unit:
                b.unit, b.norm_unit, b.dimension = a.unit, a.norm_unit, a.dimension
                b.norm_value = b.value if a.norm_value is None else b.value * (a.norm_value / a.value if a.value else 1)
            if a.unit is None and b.unit:
                a.unit, a.norm_unit, a.dimension = b.unit, b.norm_unit, b.dimension
                a.norm_value = a.value * (b.norm_value / b.value if b.value else 1)
            q = Quantity(value=b.value, unit=b.unit, raw=ft.group(0), norm_value=b.norm_value,
                         norm_unit=b.norm_unit, dimension=b.dimension, kind="from_to",
                         from_value=a.norm_value if a.norm_value is not None else a.value,
                         to_value=b.norm_value if b.norm_value is not None else b.value)
            rest = (text[:ft.start()] + " " + text[ft.end():])
            return norm_ws(rest), q, (a, b)
    by = re.search(r"\bby\s+(?P<q>(?:about|around|approximately|roughly|nearly|almost|some|~)?\s*[$€£]?\d[^\s]*(?:\s+(?:percent|per cent|percentage points?|%|million|billion|thousand))?(?:\s+[a-z°/]+)?)", text, re.I)
    if by:
        qs = find_quantities(by.group("q"))
        if qs:
            q = qs[0][2]
            if q.norm_unit == "pp":
                q.kind = "change_pp"
            else:
                q.kind = "change"
            rest = text[:by.start()] + " " + text[by.start("q") + qs[0][1]:]
            return norm_ws(rest), q, None
    to = re.search(r"\bto\s+(?P<q>(?:about|around|approximately|roughly|nearly|almost|~)?\s*[$€£]?[\d][^\s]*(?:\s+(?:percent|per cent|%|million|billion|thousand))?(?:\s+[a-z°/]+)?)", text, re.I)
    if to:
        qs = find_quantities(to.group("q"))
        if qs:
            rest = text[:to.start()] + " " + text[to.end():]
            return norm_ws(rest), qs[0][2], None
    qs = [x for x in find_quantities(text) if x[2].kind != "year"]
    if qs:
        s, e, q = qs[0]
        rest = text[:s] + " " + text[e:]
        return norm_ws(rest), q, None
    return text, None, None


def _clean_np(text: str) -> str:
    t = norm_ws(text).strip(" ,;:.\"'")
    t = re.sub(r"^(?:that|whether)\s+", "", t, flags=re.I)
    t = re.sub(r"\s+(?:significantly|substantially|considerably|sharply|slightly|dramatically|markedly|steadily|modestly|strongly|greatly)$", "", t, flags=re.I)
    t = re.sub(r"^(?:significantly|substantially|considerably|sharply|slightly|dramatically|markedly|steadily|modestly|strongly|greatly)\s+", "", t, flags=re.I)
    t = re.sub(r"\s+(?:a|an|the)$", "", t, flags=re.I)
    return t.strip(" ,;:.")


def _direction(verb: str) -> int:
    v = verb.lower()
    if re.fullmatch(UP_VERBS, v):
        return 1
    if re.fullmatch(DOWN_VERBS, v):
        return -1
    return 0


def _quantifier(subject: str) -> tuple[Optional[str], str]:
    m = QUANTIFIER.match(subject)
    if not m:
        return None, subject
    q = m.group(1).lower()
    q = {"every": "all", "each": "all", "none of the": "none", "no": "none", "several": "some"}.get(q, q)
    return q, subject[m.end():]


def parse_clause(clause: str) -> Optional[dict]:
    """Parse one clause (scope already removed) into s/p/o fields."""
    c = clause.strip().rstrip(".!").strip()
    c = re.sub(r"^(?:and|but|while|whereas|however|moreover|furthermore|in addition|also|meanwhile|overall|notably|importantly|indeed),?\s+", "", c, flags=re.I)
    c = re.sub(r"^(?:correction|update|clarification|erratum|editor's note|note)\s*:\s*", "", c, flags=re.I)
    if not c:
        return None

    m = MATH_RE.match(c)
    if m:
        return dict(s=norm_ws(m.group("lhs")), p="equals", o=m.group("rhs").strip(),
                    ct=ClaimType.MATHEMATICAL, conf=0.95, method="rule:math@1")
    for rx in DEF_PATTERNS:
        m = rx.match(c)
        if m:
            return dict(s=m.group("s"), p="is_defined_as", o=m.group("o"),
                        ct=ClaimType.DEFINITION, conf=0.9, method="rule:definition@1")
    m = re.match(rf"^(?P<s>.+?)\s+was\s+(?P<v>{EVENT_VERBS})\s+at\s+(?P<o>[A-Z][\w-]+(?:\s+[A-Z][\w-]+)*)$", c)
    if m:
        return dict(s=m.group("s"), p=f"{m.group('v').lower()}_at", o=m.group("o"),
                    ct=ClaimType.EMPIRICAL, conf=0.75, method="rule:event-place@1")
    for rx in (EVENT_RE, EVENT_ACTIVE_RE):
        m = rx.match(c)
        if m:
            neg = bool(m.group("neg"))
            year = float(re.findall(r"\d{4}", m.group("o"))[-1])
            q = Quantity(value=year, raw=m.group("o"), kind="year", norm_value=year, dimension="year")
            return dict(s=m.group("s"), p=f"{m.group('v').lower()}_in", o=m.group("o"),
                        ct=ClaimType.EMPIRICAL, conf=0.9, method="rule:event-time@1",
                        quantity=q, neg=neg, rest=m.group("rest"))
    for rx in CORR_PATTERNS:
        m = rx.match(c)
        if m:
            adv = (m.groupdict().get("adv") or "").lower()
            d = -1 if re.search(r"negative|inverse", adv) else (1 if "positive" in adv else 0)
            aux = m.groupdict().get("aux") or ""
            mod, pol, notes = _strip_aux_modality(aux)
            if m.groupdict().get("neg"):
                pol = Polarity.NEGATIVE
            return dict(s=m.group("s"), p="correlates_with", o=m.group("o"),
                        ct=ClaimType.CORRELATIONAL, conf=0.85, method="rule:correlation@1",
                        direction=d, modality=mod, neg=pol == Polarity.NEGATIVE)
    m = NODIFF_RE.match(c)
    if m:
        return dict(s=m.group("s"), p="affects", o=m.group("o"), ct=ClaimType.CAUSAL,
                    conf=0.75, method="rule:no-difference@1", neg=True,
                    notes=[f"compared with {norm_ws(m.group('b'))}"])
    m = NOEFFECT_RE.match(c)
    if m:
        return dict(s=m.group("s"), p="affects", o=m.group("o"), ct=ClaimType.CAUSAL,
                    conf=0.85, method="rule:no-effect@1", neg=True)
    m = DIR_RE.match(c)
    if m and not re.search(r"\b(is|are|was|were)$", m.group("s").strip(), re.I):
        verb = m.group("v").lower()
        obj = m.group("o") or ""
        mod, pol, notes = _strip_aux_modality(m.group("aux"))
        d = _direction(verb)
        obj_rest, q, ft = _split_quantity(obj)
        obj_np = _clean_np(re.sub(r"^(?:by|to|from|in|over|during|on)\b.*$", "", obj_rest, flags=re.I))
        intransitive = verb in CHANGE_INTRANSITIVE and (not obj_np or re.match(r"^(?:by|to|from)\b", obj.strip(), re.I))
        if verb in ("doubled", "doubles", "double"):
            q = q or Quantity(value=100.0, raw=verb, norm_value=100.0, norm_unit="percent",
                              dimension="ratio", kind="change")
        if verb in ("halved", "halves", "halve"):
            q = q or Quantity(value=50.0, raw=verb, norm_value=50.0, norm_unit="percent",
                              dimension="ratio", kind="change")
        if intransitive or not obj_np:
            return dict(s=m.group("s"), p="increased" if d > 0 else "decreased", o=None,
                        ct=ClaimType.STATISTICAL, conf=0.85, method="rule:change@1",
                        direction=d, quantity=q, modality=mod, neg=pol == Polarity.NEGATIVE,
                        notes=notes, verb=verb)
        return dict(s=m.group("s"), p="increases" if d > 0 else "decreases", o=obj_np,
                    ct=ClaimType.CAUSAL, conf=0.8, method="rule:causal-direction@1",
                    direction=d, quantity=q, modality=mod, neg=pol == Polarity.NEGATIVE,
                    notes=notes, verb=verb)
    m = CAUSE_RE.match(c)
    if m:
        mod, pol, notes = _strip_aux_modality(m.group("aux"))
        verb = m.group("v").lower()
        p = "affects" if re.match(r"affect|influenc", verb) else "causes"
        obj = m.group("o")
        d = 0
        dm = re.match(r"^(?:an?\s+)?(?P<dir>increase|rise|growth|reduction|decrease|decline|drop|fall|higher|lower|more|less|fewer|greater)s?\s+(?:in|of)?\s*(?P<rest>.+)$", obj, re.I)
        if dm:
            word = dm.group("dir").lower()
            d = 1 if word in ("increase", "rise", "growth", "higher", "more", "greater") else -1
            obj = dm.group("rest")
            p = "increases" if d > 0 else "decreases"
        obj_rest, q, _ = _split_quantity(obj)
        return dict(s=m.group("s"), p=p, o=_clean_np(obj_rest), ct=ClaimType.CAUSAL, conf=0.8,
                    method="rule:causal@1", direction=d, quantity=q, modality=mod,
                    neg=pol == Polarity.NEGATIVE, notes=notes)
    m = REQUIRE_RE.match(c)
    if m:
        mod, pol, notes = _strip_aux_modality(m.group("aux"))
        return dict(s=m.group("s"), p="requires", o=_clean_np(m.group("o")), ct=ClaimType.EMPIRICAL,
                    conf=0.75, method="rule:requires@1", modality=mod,
                    neg=pol == Polarity.NEGATIVE)
    m = HASVAL_RE.match(c)
    if m:
        rest, q, _ = _split_quantity(m.group("o"))
        if q is not None:
            subj = f"{m.group('attr').strip()} of {m.group('s').strip()}"
            return dict(s=subj, p="has_value", o=None, ct=ClaimType.STATISTICAL, conf=0.85,
                        method="rule:has-value@1", quantity=q)
    m = VALUE_RE.match(c)
    if m:
        rest, q, ft = _split_quantity(m.group("o"))
        if q is not None and q.kind != "year" and not re.search(r"[a-z]{4,}", _clean_np(rest).replace("percent", "").replace("people", ""), re.I):
            return dict(s=m.group("s"), p="has_value", o=None, ct=ClaimType.STATISTICAL,
                        conf=0.85, method="rule:value@1", quantity=q, neg=bool(m.groupdict().get("neg")),
                        object_unit_noun=_clean_np(rest) or None)
        if q is not None and q.kind != "year":
            return dict(s=m.group("s"), p="has_value", o=_clean_np(rest) or None,
                        ct=ClaimType.STATISTICAL, conf=0.7, method="rule:value-noun@1",
                        quantity=q, neg=bool(m.groupdict().get("neg")),
                        object_unit_noun=_clean_np(rest) or None)
    m = COPULA_RE.match(c)
    if m:
        verb = m.group("v").lower()
        p = "is" if verb in ("is", "are", "was", "were") else ("has" if verb in ("has", "have", "had") else verb.replace(" ", "_"))
        o = m.group("o")
        neg = bool(m.group("neg"))
        if re.match(r"^not\s+", o, re.I):
            neg, o = True, o[4:]
        if re.match(r"^no\s+", o, re.I) and p == "has":
            neg, o = True, o[3:]
        _, q, _ = _split_quantity(o)
        return dict(s=m.group("s"), p=p, o=_clean_np(o), ct=ClaimType.EMPIRICAL, conf=0.7,
                    method="rule:copula@1", neg=neg,
                    quantity=q if q is not None and q.kind != "year" else None)
    m = GENERIC_VERB_RE.match(c)
    if m and m.group("v").lower() not in ("this", "has", "was", "is", "its", "news", "series"):
        _, q, _ = _split_quantity(m.group("o"))
        return dict(s=m.group("s"), p=m.group("v").lower(), o=_clean_np(m.group("o")),
                    ct=ClaimType.EMPIRICAL, conf=0.55, method="rule:generic-verb@1",
                    quantity=q if q is not None and q.kind != "year" else None)
    return None


# --------------------------------------------------------------------- sentence level

_QUOTE_AFTER = re.compile(rf'^(?P<sp>[^"“]+?),?\s+(?:{REPORT_VERBS})(?:\s+that)?\s*[:,]?\s*["“](?P<q>[^"”]+)["”]\s*\.?$', re.I)
_QUOTE_BEFORE = re.compile(rf'^["“](?P<q>[^"”]+?)[,.]?["”],?\s+(?P<sp>[^,]+?)\s+(?:{REPORT_VERBS})\s*\.?$', re.I)
_QUOTE_BEFORE2 = re.compile(rf'^["“](?P<q>[^"”]+?)[,.]?["”],?\s+(?:{REPORT_VERBS})\s+(?P<sp>[^,]+?)\s*\.?$', re.I)
_ACCORDING = re.compile(r"^(?:according to|as reported by|per|citing)\s+(?P<sp>[^,]+),\s*(?P<rest>.+)$", re.I)
_ACCORDING_END = re.compile(r"^(?P<rest>.+?),\s+according to\s+(?P<sp>[^,]+?)\.?$", re.I)
_REPORTED = re.compile(rf"^(?P<sp>.+?)\s+(?:has |have |had )?(?P<v>{REPORT_VERBS})\s+that\s+(?P<rest>.+)$", re.I)
_REPORTED_NOTHAT = re.compile(rf"^(?P<sp>(?:the |a |an |one |our |this |that |\d{{4}} )?(?:[\w-]+\s+){{0,5}}?(?:study|studies|trial|trials|experiment|survey|poll|analysis|meta-analysis|review|report|census|data|researchers|scientists|investigators|authors|paper|records|figures))\s+(?P<v>{REPORT_VERBS})\s+(?P<rest>.+)$", re.I)


def detect_basis(text: str) -> Optional[EvidenceBasis]:
    for basis, rx in BASIS_CUES:
        if re.search(rx, text, re.I):
            return basis
    return None


def split_clauses(sentence: str) -> list[tuple[str, int, Optional[int], bool]]:
    """Return clauses as (text, group, caused_by_index, qualifies_prev).

    * "; " and ", and/but/while/whereas" split independent clauses when both sides
      contain a recognisable predicate;
    * "A because B" yields [A, B] with A caused_by B;
    * shared-subject coordination "X reduces A and increases B" yields two clauses
      with the subject copied.
    """
    s = sentence.strip()
    out: list[tuple[str, int, Optional[int], bool]] = []
    m = re.match(r"^(?P<a>.+?),?\s+(?:because|since|as a result of the fact that)\s+(?P<b>[^,]+\b(?:is|are|was|were|has|have|had|\w+ed|\w+s)\b.+)$", s, re.I)
    if m and parse_clause(m.group("b")) and not re.match(r"^\d{4}", m.group("b")):
        return [(m.group("a"), 0, 1, False), (m.group("b"), 1, None, False)]
    # appositive event: "The Haldane Canal, opened in 1823, linked A with B."
    m = re.match(rf"^(?P<s>[^,]+),\s+(?P<v>{EVENT_VERBS}|opened|completed)\s+(?P<pp>(?:in|on)\s+{_DATE}),\s+(?P<rest>.+)$", s, re.I)
    if m:
        return [(f"{m.group('s')} was {m.group('v')} {m.group('pp')}", 0, None, False),
                (f"{m.group('s')} {m.group('rest')}", 1, None, False)]
    # event with both a place and a date yields two propositions (place, date)
    m = EVENT_PLACE_RE.match(s)
    if m and re.search(r"\b(?:in|on)\s+" + _DATE, s):
        dm = re.search(r"\b(?:in|on)\s+(" + _DATE + ")", s)
        return [(f"{m.group('s')} was {m.group('v')} at {m.group('place')}", 0, None, False),
                (f"{m.group('s')} was {m.group('v')} in {dm.group(1)}", 0, None, False)]
    parts = re.split(r";\s+|,\s+(?=(?:and|but|while|whereas)\s)|\s+(?=(?:but|whereas)\s)", s)
    merged: list[str] = []
    for part in parts:
        if merged and not _has_predicate(part):
            merged[-1] = merged[-1] + (", " if not part.startswith(("but", "whereas")) else " ") + part
        else:
            merged.append(part)
    for gi, part in enumerate(merged):
        qual = bool(re.match(r"^(?:but|although|though|however)\b", part.strip(), re.I)) and gi > 0
        # shared-subject verb coordination
        verbs = f"{UP_VERBS}|{DOWN_VERBS}|{CAUSE_VERBS}"
        mm = re.match(rf"^(?P<s>.+?\s+(?:{AUX}))(?P<a>(?:{verbs})\b.+?)\s+and\s+(?P<b>(?:{verbs})\b.+)$", part, re.I)
        if mm:
            subj = mm.group("s")
            out.append((subj + mm.group("a"), gi, None, qual))
            out.append((subj + mm.group("b"), gi, None, False))
            continue
        out.append((part, gi, None, qual))
    return out


def _has_predicate(text: str) -> bool:
    t = re.sub(r"^(?:and|but|while|whereas)\s+", "", text.strip(), flags=re.I)
    if len(t.split()) < 3:
        return False
    return parse_clause(extract_scope(t)[0]) is not None and bool(
        re.search(rf"\b(is|are|was|were|has|have|had|{UP_VERBS}|{DOWN_VERBS}|{CAUSE_VERBS}|{REQUIRE_VERBS}|correlates?|associated|linked)\b", t, re.I))


def extract_sentence(sentence: str, sent_index: int, span: tuple[int, int],
                     doc_basis: Optional[EvidenceBasis] = None,
                     paragraph_basis: Optional[EvidenceBasis] = None) -> list[Draft]:
    raw = sentence.strip()
    if raw.endswith("?") or len(raw.split()) < 3:
        return []
    work = raw
    attribution = Attribution()
    notes: list[str] = []
    claim_override: Optional[ClaimType] = None
    modality_override: Optional[Modality] = None

    # quotations
    for rx in (_QUOTE_AFTER, _QUOTE_BEFORE, _QUOTE_BEFORE2):
        m = rx.match(work)
        if m:
            attribution = Attribution(speaker=norm_ws(m.group("sp")), kind="quoted",
                                      quote=m.group("q").strip())
            work = m.group("q").strip()
            break
    if attribution.kind == "author":
        m = _ACCORDING.match(work) or _ACCORDING_END.match(work)
        if m:
            attribution = Attribution(speaker=norm_ws(m.group("sp")), kind="reported")
            work = m.group("rest")
        else:
            m = _REPORTED.match(work) or _REPORTED_NOTHAT.match(work)
            if m and len(m.group("sp").split()) <= 8 and parse_clause(extract_scope(m.group("rest"))[0]):
                sp = norm_ws(m.group("sp"))
                attribution = Attribution(speaker=sp, kind="reported")
                v = m.group("v").lower()
                if v.startswith(("suggest", "indicat")):
                    modality_override = Modality.POSSIBLE
                if v.startswith(("predict",)):
                    claim_override = ClaimType.PREDICTION
                if v.startswith(("hypothes",)):
                    claim_override = ClaimType.HYPOTHESIS
                if v.startswith(("believe",)) and not STUDY_WORDS.search(sp):
                    claim_override = ClaimType.OPINION
                work = m.group("rest")
    if attribution.speaker and re.fullmatch(r"(?:i|we)", attribution.speaker, re.I):
        attribution = Attribution()  # first-person reporting = author

    # opinion markers
    if OPINION_MARKERS.search(work):
        claim_override = ClaimType.OPINION
        work = re.sub(r"^(?:(?:i|we)\s+(?:think|believe|feel|reckon|suspect|guess)(?:\s+that)?|in my (?:opinion|view)|personally|frankly|honestly|arguably|to me),?\s+", "", work, flags=re.I)

    # inference markers
    marker = None
    m = INFERENCE_MARKERS.match(work)
    if m:
        marker = norm_ws(m.group(0)).strip(", ").lower()
        work = work[m.end():]
    premise_inline = None
    mi = INLINE_INFERENCE.search(work)
    if mi:
        premise_inline = work[:mi.start()]
        marker = norm_ws(mi.group(0)).strip(", ").lower()
        work = work[mi.end():]

    sent_basis = detect_basis(raw)
    drafts: list[Draft] = []
    clause_specs = []
    if premise_inline:
        clause_specs.append((premise_inline, 0, None, False, None))
        for c in split_clauses(work):
            clause_specs.append((c[0], c[1] + 1, None, c[3], marker))
    else:
        for c in split_clauses(work):
            clause_specs.append((c[0], c[1], c[2], c[3], marker))

    for idx, (clause, group, caused_by, qual, mk) in enumerate(clause_specs):
        ev = EVENT_RE.match(clause.strip().rstrip(".")) or EVENT_ACTIVE_RE.match(clause.strip().rstrip("."))
        if ev:
            # event-time claims: the year is the asserted value, not a scope restriction
            parsed = parse_clause(clause)
            stripped, scope, scope_notes = clause, Scope(), []
        else:
            stripped, scope, scope_notes = extract_scope(clause)
            parsed = parse_clause(stripped)
        conf_pen = 0.0
        if parsed is None:
            if len(stripped.split()) < 3:
                continue
            parsed = dict(s=stripped, p="asserts", o=None, ct=ClaimType.EMPIRICAL, conf=0.3,
                          method="rule:fallback@1")
        if parsed.get("rest"):
            rest_stripped, rest_scope, _ = extract_scope(parsed["rest"])
            for k in ("location", "population", "time"):
                if getattr(rest_scope, k) and not getattr(scope, k):
                    setattr(scope, k, getattr(rest_scope, k))
            scope.conditions.extend(rest_scope.conditions)
        subj_raw = parsed["s"]
        quantifier, subj_body = _quantifier(_clean_np(subj_raw))
        subject = normalize_phrase(subj_body)
        obj = normalize_phrase(parsed.get("o")) if parsed.get("o") else None
        ct = parsed["ct"]
        modality = parsed.get("modality", Modality.ASSERTED)
        polarity = Polarity.NEGATIVE if parsed.get("neg") else Polarity.POSITIVE
        if quantifier == "none":
            polarity = Polarity.NEGATIVE if polarity == Polarity.POSITIVE else Polarity.POSITIVE
            quantifier = "all"
        undated = strip_month_may(clause)
        if HEDGES.search(undated) and modality == Modality.ASSERTED:
            modality = Modality.POSSIBLE
        elif PROBABLE.search(undated) and modality == Modality.ASSERTED:
            modality = Modality.PROBABLE
        if FUTURE.search(clause) and ct not in (ClaimType.DEFINITION, ClaimType.MATHEMATICAL):
            modality = Modality.PREDICTED
            ct = ClaimType.PREDICTION if ct not in (ClaimType.CAUSAL,) else ct
        if modality_override and modality == Modality.ASSERTED:
            modality = modality_override
        if claim_override:
            ct = claim_override
        elif ct == ClaimType.EMPIRICAL and EVALUATIVE.search(clause):
            ct = ClaimType.OPINION
        elif NORMATIVE.search(clause) and ct not in (ClaimType.DEFINITION, ClaimType.MATHEMATICAL) \
                and not re.search(r"\bmust (?:have|be)\b", clause, re.I):
            ct = ClaimType.NORMATIVE
        if ct == ClaimType.EMPIRICAL and attribution.kind == "author" and doc_basis is None \
                and re.search(r"\b(we hypothesi[sz]e|our hypothesis)\b", raw, re.I):
            ct = ClaimType.HYPOTHESIS
        if attribution.kind in ("reported", "quoted") and modality == Modality.ASSERTED:
            modality = Modality.REPORTED
        if subject in PRONOUNS or subject.split(" ")[0] in ("it", "they", "this", "these", "he", "she"):
            conf_pen += 0.15
        if len(subject.split()) > 9:
            conf_pen += 0.1
        if len(clause_specs) > 1:
            conf_pen += 0.05
        d = Draft(
            subject=subject, predicate=parsed["p"], object=obj, claim_type=ct,
            modality=modality, polarity=polarity, direction=parsed.get("direction", 0),
            quantity=parsed.get("quantity"), quantifier=quantifier, scope=scope,
            attribution=Attribution(**attribution.to_dict()), quote=raw, quote_span=span,
            sentence_index=sent_index, clause=norm_ws(clause),
            surface={"subject": norm_ws(subj_raw), "predicate": parsed.get("verb") or parsed["p"],
                     "object": norm_ws(parsed["o"]) if parsed.get("o") else None},
            stated_basis=sent_basis or paragraph_basis or doc_basis,
            confidence=round(max(0.1, parsed["conf"] - conf_pen), 2), method=parsed["method"],
            notes=notes + scope_notes + parsed.get("notes", []), inference_marker=mk,
            group=group, caused_by=caused_by, qualifies_previous=qual,
        )
        if parsed.get("object_unit_noun") is not None and d.quantity is not None:
            d.notes.append(f"value-noun:{parsed['object_unit_noun']}")
        if d.quantity is not None and d.quantity.unit is None and d.quantity.kind in ("level",) \
                and not parsed.get("object_unit_noun"):
            d.ambiguous.append("number without unit")
        if d.quantity is not None:
            d.scope.units = d.quantity.unit
        drafts.append(d)
    # coordinated clauses with a shared subject share trailing scope phrases
    for d in drafts:
        for other in drafts:
            if other is d or other.group != d.group or other.sentence_index != d.sentence_index:
                continue
            for k in ("time", "time_norm", "location", "population"):
                if getattr(d.scope, k) is None and getattr(other.scope, k) is not None:
                    setattr(d.scope, k, getattr(other.scope, k))
            if not d.scope.conditions and other.scope.conditions:
                d.scope.conditions = list(other.scope.conditions)
    return drafts


def extract_passage_text(text: str, doc_basis: Optional[EvidenceBasis] = None) -> list[Draft]:
    """Extract drafts from a passage of English text."""
    paragraph_basis = detect_basis(text)
    drafts: list[Draft] = []
    for i, (s, e) in enumerate(split_sentences(text)):
        drafts.extend(extract_sentence(text[s:e], i, (s, e), doc_basis, paragraph_basis))
    return drafts


def contains_year_only(text: str) -> bool:
    return bool(YEAR_RE.fullmatch(text.strip()))
