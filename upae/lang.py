"""Language identification and cross-language cue lexicons (deterministic).

Identification uses Unicode script detection followed by stop-word profile scoring.
It is adequate for document/paragraph level on the supported languages and reports
"und" (undetermined) with low confidence otherwise.  A model provider may replace it.
"""
from __future__ import annotations

import re

from .textutil import strip_accents

PROFILES = {
    "en": "the of and to in is that for it was on are with as be by this have from not or which were has been will "
          "just no but all can its their than more about after into only also new big day news",
    "de": "der die und das ist nicht ein eine zu den von mit sich des auf für im dem wird wurde sind auch es an werden bei",
    "fr": "le la les et des est une un du que dans pour pas en au qui sur sont par ne plus avec ce été",
    "es": "el la los las y de que es en un una por con para no del se su al lo como más fue son está",
    "it": "il la di che e è un una per non del della sono con in si le gli da al ha",
    "pt": "o a os as e de que é em um uma para não do da com por se no na foi são",
    "nl": "de het een en van is niet dat in te zijn op met voor er die werd wordt ook",
}
_PROFILE_SETS = {k: set(v.split()) for k, v in PROFILES.items()}

SCRIPTS = [
    ("ru", re.compile(r"[Ѐ-ӿ]")),
    ("el", re.compile(r"[Ͱ-Ͽ]")),
    ("ar", re.compile(r"[؀-ۿ]")),
    ("he", re.compile(r"[֐-׿]")),
    ("ko", re.compile(r"[가-힯]")),
    ("ja", re.compile(r"[぀-ヿ]")),
    ("zh", re.compile(r"[一-鿿]")),
]


def detect_language(text: str) -> tuple[str, float]:
    if not text or not text.strip():
        return "und", 0.0
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return "und", 0.0
    for code, rx in SCRIPTS:
        share = len(rx.findall(text)) / len(letters)
        if share > 0.3:
            return code, round(min(1.0, share), 2)
    words = re.findall(r"[a-zà-ÿœæß]+", text.lower())
    if not words:
        return "und", 0.0
    scores = {lang: sum(1 for w in words if w in s) for lang, s in _PROFILE_SETS.items()}
    best = max(scores, key=lambda k: (scores[k], k == "en"))
    ranked = sorted(scores.values(), reverse=True)
    ascii_only = all(c.isascii() for c in letters)
    if len(words) < 8:
        # Short texts ("No Guts, Just Data.", "Day 2."): a single shared function word
        # ("no", "data") is not evidence of a language.  Require two stop-word hits and a
        # lead over English; otherwise plain-ASCII text is treated as low-confidence English.
        if best != "en" and (scores[best] < 2 or scores[best] <= scores["en"]):
            return ("en", 0.3) if ascii_only else ("und", 0.1)
        if ranked[0] == 0:
            return ("en", 0.2) if ascii_only else ("und", 0.0)
    if ranked[0] == 0:
        return "und", 0.0
    margin = (ranked[0] - ranked[1]) / ranked[0]
    coverage = ranked[0] / len(words)
    conf = round(min(1.0, 0.5 * margin + 1.5 * coverage), 2)
    if len(words) < 8:
        conf = min(conf, 0.6)  # few words: never claim high certainty
    if conf < 0.2:
        return "und", conf
    return best, conf


# Cue lexicons used to compare an original with its translation.
NEGATION_CUES = {
    "en": r"\b(not|no|never|none|neither|nor|without|cannot)\b|n't\b",
    "de": r"\b(nicht|kein|keine|keinen|keiner|keinem|nie|niemals|ohne|weder)\b",
    "fr": r"\b(ne|n'|pas|jamais|aucun|aucune|sans|ni)\b",
    "es": r"\b(no|nunca|ningun|ninguna|ninguno|sin|ni|jamas)\b",
    "it": r"\b(non|mai|nessun|nessuna|senza|ne)\b",
    "pt": r"\b(nao|nunca|nenhum|nenhuma|sem|nem)\b",
    "nl": r"\b(niet|geen|nooit|zonder|noch)\b",
}
# Modal force classes.  A translation must preserve the *class* of modality
# (possibility vs necessity vs plain assertion) and universal quantification.
POSSIBILITY_CUES = {
    "en": r"\b(may|might|could|can|possibly|perhaps|maybe|likely|probably|suggests?|appears?|seems?)\b",
    "de": r"\b(kann|konnen|kannst|konnte|konnten|koennte|mag|moglicherweise|vielleicht|wahrscheinlich|deutet|scheint)\b",
    "fr": r"\b(peut|peuvent|pourrait|pourraient|peut-etre|probablement|semble|semblent|suggere)\b",
    "es": r"\b(puede|pueden|podria|podrian|quizas|quiza|tal vez|posiblemente|probablemente|sugiere|parece)\b",
    "it": r"\b(puo|possono|potrebbe|potrebbero|forse|probabilmente|sembra|suggerisce)\b",
    "pt": r"\b(pode|podem|poderia|poderiam|talvez|provavelmente|parece|sugere)\b",
    "nl": r"\b(kan|kunnen|zou|zouden|misschien|waarschijnlijk|lijkt)\b",
}
NECESSITY_CUES = {
    "en": r"\b(must|always|necessarily|certainly|definitely|proves?|invariably|guarantees?)\b",
    "de": r"\b(muss|mussen|muessen|immer|notwendigerweise|sicher|definitiv|beweist|garantiert)\b",
    "fr": r"\b(doit|doivent|toujours|necessairement|certainement|prouve|garantit)\b",
    "es": r"\b(debe|deben|siempre|necesariamente|ciertamente|demuestra|garantiza)\b",
    "it": r"\b(deve|devono|sempre|necessariamente|certamente|dimostra|garantisce)\b",
    "pt": r"\b(deve|devem|sempre|necessariamente|certamente|prova|garante)\b",
    "nl": r"\b(moet|moeten|altijd|noodzakelijk|zeker|bewijst|garandeert)\b",
}
UNIVERSAL_CUES = {
    "en": r"\b(all|every|each|none|nobody)\b",
    "de": r"\b(alle|jede|jeder|jedes|keiner|niemand)\b",
    "fr": r"\b(tous|toutes|chaque|aucun|personne)\b",
    "es": r"\b(todos|todas|cada|ninguno|nadie)\b",
    "it": r"\b(tutti|tutte|ogni|nessuno)\b",
    "pt": r"\b(todos|todas|cada|nenhum|ninguem)\b",
    "nl": r"\b(alle|elke|ieder|niemand)\b",
}
# Korean is agglutinative: cues are verb endings and adverbs, matched without \b.
NEGATION_CUES["ko"] = r"(?:지\s?(?:않|못)|않는|않았|않습|않을|못한|못했|못하|아니다|아닌|아니었|없다|없었|없는|없습|결코|전혀)"
POSSIBILITY_CUES["ko"] = r"(?:수\s?(?:도\s?)?있|가능성|아마|것\s?같|보인다|보입니다|추정|듯하|듯합|모른다)"
NECESSITY_CUES["ko"] = r"(?:반드시|항상|언제나|해야|하여야|틀림없|확실히|증명|입증)"
UNIVERSAL_CUES["ko"] = r"(?:모든|모두|전부|누구나|아무도|예외\s?없이)"

# backwards-compatible aliases
HEDGE_CUES = POSSIBILITY_CUES
CERTAINTY_CUES = NECESSITY_CUES


def cue_count(kind: dict, lang: str, text: str) -> int:
    rx = kind.get(lang)
    if rx is None:
        return -1  # unsupported language
    if lang == "en":
        from .extract import strip_month_may
        text = strip_month_may(text)
    if lang in ("ko", "ja", "zh"):
        # NFKD would decompose Hangul syllables into jamo; match the text as written
        return len(re.findall(rx, text))
    return len(re.findall(rx, strip_accents(text.lower())))


def numbers_in(text: str) -> list[float]:
    """Language-neutral numeric tokens, accepting both 1,234.5 and 1.234,5 styles."""
    out = []
    for raw in re.findall(r"\d+(?:[.,]\d+)*", text):
        s = raw
        if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?", s):      # 1.234,5
            s = s.replace(".", "").replace(",", ".")
        elif re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", s):    # 1,234.5
            s = s.replace(",", "")
        else:
            s = s.replace(",", ".")
        try:
            out.append(float(s))
        except ValueError:
            continue
    return sorted(out)
