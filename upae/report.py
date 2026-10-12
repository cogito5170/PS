"""Report generation: compact numbered Markdown report and a self-contained,
interactive HTML report (filters, graph exploration, source inspection,
drill-down from a proposition to its original passage)."""
from __future__ import annotations

import html
import json
from collections import Counter
from typing import Optional

from .graph import KnowledgeGraph
from .models import PROCESSING_VERSION, ClaimType, RelationType, Status

STATUS_LEGEND = {
    "SUPPORTED": "independent support ≥ τ, no comparable challenge",
    "CONTRADICTED": "independent challenge ≥ τ (or deterministic proof), no comparable support",
    "CONFLICTING_EVIDENCE": "support and challenge both present",
    "INSUFFICIENT_EVIDENCE": "only dependent copies or weak evidence",
    "UNVERIFIED": "no evidence beyond the assertion itself",
    "OUT_OF_SCOPE": "opinion / normative — recorded, not assessed as fact",
    "RETRACTED": "from a retracted source",
    "HUMAN_REVIEW_REQUIRED": "a review trigger fired",
}


def _loc(g: KnowledgeGraph, pid: str) -> str:
    p = g.propositions[pid]
    s = g.sources[p.source_refs[0]]
    pas = g.passages.get(p.passage_id) if p.passage_id else None
    bits = [s.id]
    if pas is not None and pas.page is not None:
        bits.append(f"p.{pas.page}")
    if pas is not None and pas.section:
        bits.append(f"§{pas.section}")
    if pas is not None:
        bits.append(pas.id)
    return " ".join(bits)


def _red(g: KnowledgeGraph, pid: str) -> bool:
    return any(g.issues[i].red_for(pid) for i in g.propositions[pid].issue_refs)


def _q(text: str, n: int = 220) -> str:
    t = " ".join(text.split())
    return t if len(t) <= n else t[: n - 1] + "…"


def markdown_report(g: KnowledgeGraph, title: str = "Proposition Analysis Report",
                    generated_at: Optional[str] = None) -> str:
    L: list[str] = []
    A = g.assessments
    red = [i for i in g.issues.values() if i.red]
    status_counts = Counter(a.status.value for pid, a in A.items()
                            if g.propositions[pid].claim_type != ClaimType.COMPOUND)
    src_words = sum(len(t.split()) for t in g.archive.values())
    core = [r for r in g.ranking if r["decision"] in ("core", "core_forced")]
    core_words = sum(len(g.propositions[r["id"]].text.split()) for r in core)
    L.append(f"# {title}")
    L.append("")
    L.append(f"Generated {generated_at or ''} · engine {PROCESSING_VERSION} · "
             f"model calls: {g.model_calls} · deterministic extraction: "
             f"{sum(1 for p in g.propositions.values() if p.extraction.deterministic)}/{len(g.propositions)}")
    L.append("")
    L.append(f"Corpus: {len(g.sources)} sources · {len(g.passages)} passages · "
             f"{sum(1 for p in g.propositions.values() if p.claim_type != ClaimType.COMPOUND)} propositions · "
             f"{len(g.relations)} relations · {len(g.issues)} issues (**{len(red)} red**). "
             f"Compression: {src_words} source words → {core_words} words in {len(core)} core statements "
             f"(ratio {core_words / src_words:.2f})." if src_words else "Corpus is empty.")
    L.append("")
    L.append("Status counts: " + ", ".join(f"{k} {v}" for k, v in sorted(status_counts.items())))
    L.append("")
    L.append("Notation: `pred(subject, object) = value | scope`; `¬` negation, `◇` hedged, `F` predicted, "
             "`X ⊢` attributed to X. 🔴 = carries a red issue (a detected problem, not proof of falsity).")
    L.append("")

    # 1
    L.append("## 1. Core propositions")
    L.append("")
    for n, r in enumerate(core, 1):
        p = g.propositions[r["id"]]
        mark = "🔴 " if _red(g, p.id) else ""
        L.append(f"{n}. {mark}**{p.id}** `{p.text}` — {A[p.id].status.value} · {_loc(g, p.id)}")
    L.append("")
    # 2
    L.append("## 2. Relationship graph")
    L.append("")
    rels = sorted(g.relations.values(), key=lambda r: (r.type.value, r.id))
    if rels:
        L.append("```mermaid")
        L.append("graph LR")
        for r in rels[:60]:
            arrow = "---" if not r.directed else "-->"
            L.append(f"  {r.source.replace('-', '')}[{r.source}] {arrow}|{r.type.value}| {r.target.replace('-', '')}[{r.target}]")
        L.append("```")
        L.append("")
        for r in rels:
            sym = "↔" if not r.directed else "→"
            extra = f" [{', '.join(r.dimensions)}]" if r.dimensions else ""
            L.append(f"- {r.id}: {r.source} {sym}{r.type.value}{sym if not r.directed else ''} {r.target}{extra} "
                     f"(conf {r.confidence:.2f}, {r.review_status.value}) — {r.rationale}")
    else:
        L.append("No relations detected.")
    L.append("")
    # 3
    L.append("## 3. Confirmed findings")
    L.append("")
    sup = [p for p in g.propositions.values() if A[p.id].status == Status.SUPPORTED]
    if not sup:
        L.append("None: no proposition reached independent support ≥ τ.")
    for n, p in enumerate(sup, 1):
        a = A[p.id]
        L.append(f"{n}. **{p.id}** `{p.text}` — S={a.support_strength:.2f} from {len(a.support_groups)} "
                 f"independent group(s) ({', '.join(a.support_groups)}); evidence "
                 f"{', '.join(e for e in p.evidence_refs if g.evidence[e].stance.value == 'supports')}.")
    L.append("")
    # 4
    L.append("## 4. Red-flagged problems")
    L.append("")
    if not red:
        L.append("No red warnings.")
    for n, i in enumerate(sorted(red, key=lambda i: (-["LOW", "MEDIUM", "HIGH", "CRITICAL"].index(i.severity.value), i.id)), 1):
        L.append(f"### 4.{n} 🔴 {i.id} — {i.category.value} ({i.finding_class.value})")
        L.append("")
        L.append(f"1. **Affected:** " + ", ".join(f"{x} `{g.propositions[x].text}` ({_loc(g, x)})"
                                                 if x in g.propositions else x for x in i.affected))
        L.append(f"2. **Category:** {i.category.value} · class {i.finding_class.value}")
        conflicting = [x for x in i.conflicting if x not in i.affected] or i.conflicting
        L.append(f"3. **Conflicting / relevant:** {', '.join(conflicting) or '—'}")
        L.append(f"4. **Reason:** {i.reason}")
        L.append(f"5. **Severity / confidence:** {i.severity.value} / {i.confidence:.2f} "
                 f"({'deterministic rule' if i.deterministic else 'model judgment'}: {i.detector})")
        ev_lines = []
        for x in i.evidence:
            if x in g.passages:
                ev_lines.append(f"{x} ({g.passages[x].source_id}): “{_q(g.passages[x].text)}”")
            elif x in g.evidence:
                ev_lines.append(f"{x} ({g.evidence[x].basis.value}, strength {g.evidence[x].strength})")
            elif x in g.sources:
                ev_lines.append(f"{x} ({g.sources[x].title or g.sources[x].key})")
        L.append("6. **Evidence:** " + ("; ".join(ev_lines) if ev_lines else "—"))
        L.append(f"7. **Would resolve:** {i.resolution}")
        if i.assumptions:
            L.append(f"   - Assumptions: {' '.join(i.assumptions)}")
        L.append("")
    # 5
    L.append("## 5. Conflicting evidence")
    L.append("")
    conf = [p for p in g.propositions.values()
            if A[p.id].status in (Status.CONFLICTING_EVIDENCE, Status.CONTRADICTED)]
    if not conf:
        L.append("None.")
    for p in conf:
        a = A[p.id]
        L.append(f"- **{p.id}** {a.status.value} `{p.text}` — S={a.support_strength:.2f}, C={a.challenge_strength:.2f}. "
                 f"{a.rationale}")
        for e in p.evidence_refs:
            ev = g.evidence[e]
            L.append(f"  - {e} {ev.stance.value} via {ev.via_proposition or 'logic'} "
                     f"({ev.source_id}, {ev.basis.value}, {'primary' if ev.primary else 'secondary'}, "
                     f"{ev.directness}, strength {ev.strength}, group {ev.independence_group})")
    L.append("")
    # 6
    L.append("## 6. Missing conditions or assumptions")
    L.append("")
    n6 = 0
    for r in g.relations.values():
        if r.type == RelationType.DIFFERS_IN_SCOPE:
            n6 += 1
            L.append(f"- {r.source} vs {r.target}: not contradictory — differ in {', '.join(r.dimensions)}. {r.rationale}")
    for i in g.issues.values():
        if i.category.value == "MISSING_CONDITION":
            n6 += 1
            L.append(f"- {i.id}: {', '.join(i.affected)} — {i.reason} Required: {' '.join(i.assumptions)}")
    for r in g.relations.values():
        if r.type == RelationType.CONTRADICTS and r.assumptions:
            n6 += 1
            L.append(f"- {r.id} ({r.source} vs {r.target}) is classified as a contradiction under the assumptions: "
                     + " ".join(r.assumptions))
    if not n6:
        L.append("None detected.")
    L.append("")
    # 7
    L.append("## 7. Unresolved questions")
    L.append("")
    amber = [i for i in g.issues.values() if not i.red]
    hrr = [p for p in g.propositions.values() if A[p.id].status == Status.HUMAN_REVIEW_REQUIRED]
    for i in amber:
        L.append(f"- {i.id} {i.category.value} ({i.finding_class.value}, {i.severity.value}, conf {i.confidence:.2f}) "
                 f"on {', '.join(i.affected)}: {i.reason} → {i.resolution}")
    for p in hrr:
        L.append(f"- {p.id} needs human review: {'; '.join(A[p.id].review_triggers)}")
    for d in g.derivations.values():
        if d.validity == "unknown":
            L.append(f"- {d.id}: validity of inference {', '.join(d.premises)} ⇒ {d.conclusion} "
                     f"('{d.marker}') not established by deterministic checks.")
    if not (amber or hrr):
        L.append("None.")
    L.append("")
    # 8
    L.append("## 8. Source references")
    L.append("")
    L.append("| ID | Kind | Title | Author / Publisher | Date | Locator | Lang | Indep. group | Notes |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for s in sorted(g.sources.values(), key=lambda s: s.id):
        loc = s.doi or s.canonical_url or s.url or s.isbn or "—"
        notes = []
        if s.synthetic:
            notes.append("synthetic")
        if s.retracted:
            notes.append("RETRACTED")
        if s.reproduces:
            notes.append(f"reproduces {s.reproduces}")
        if s.translation_of:
            notes.append(f"translation of {s.translation_of}")
        if s.duplicate_of:
            notes.append(f"duplicate of {s.duplicate_of}")
        if s.cites:
            notes.append(f"cites {', '.join(s.cites)}")
        if s.access_status != "accessible":
            notes.append(s.access_status)
        auth = " / ".join(x for x in (s.author, s.publisher) if x) or "not stated"
        L.append(f"| {s.id} | {s.kind.value} | {s.title or s.key} | {auth} | {s.published or 'not stated'} | "
                 f"{loc} | {s.language} | {s.independence_group} | {', '.join(notes)} |")
    L.append("")
    L.append("Metadata is reported only where present in the source; missing fields are marked 'not stated'.")
    L.append("")
    # 9
    L.append("## 9. Confidence and limitations")
    L.append("")
    fallback = sum(1 for p in g.propositions.values() if "fallback" in p.extraction.method)
    L.append(f"- Extraction is rule-based (English). {fallback} proposition(s) used the low-confidence "
             "fallback pattern and are marked for review.")
    L.append("- Confidence values are heuristic scores from documented formulas, not calibrated probabilities; "
             "see EVALUATION_REPORT.md for measured calibration.")
    L.append("- Status reflects only evidence present in this corpus; it is not a verdict on truth.")
    for lim in g.limitations:
        L.append(f"- {lim}")
    L.append("")
    # 10
    L.append("## 10. Changes since the previous analysis")
    L.append("")
    if not g.changes:
        L.append("No previous analysis supplied.")
    else:
        ch = g.changes
        for k, v in ch.items():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                v = [f"{x['id']}: {x['from']}→{x['to']}" for x in v]
            L.append(f"- {k.replace('_', ' ')}: {', '.join(v) if v else 'none'}")
    L.append("")
    L.append("## Appendix: timeline")
    L.append("")
    if not g.timeline and not g.predictions:
        L.append("No dated episodes or predictions found.")
    for n, ep in enumerate(g.timeline, 1):
        verdict = ("not checked (single source)" if not ep["checked"] else
                   f"consistent — start {ep['start_window'][0]}" + (f"…{ep['start_window'][1]}" if ep['start_window'][1] != ep['start_window'][0] else "")
                   if ep["consistent"] else f"🔴 inconsistent (gap {ep['conflict']['gap_days']} day(s))")
        L.append(f"{n}. **{ep['place']}** episode by {ep['author']}: {verdict}")
        for s in ep["statements"]:
            L.append(f"   - {s['source']} [{s['kind']}] “{_q(s['quote'], 90)}” → start ∈ {s['implied_start'][0]}…{s['implied_start'][1]} ({s['explanation']})")
    if g.predictions:
        L.append("")
        L.append("Predictions (time anchored to publication date):")
        for pr in g.predictions:
            L.append(f"- {pr['proposition']} `{pr['text']}` — due {pr['due'] or 'n/a'}: {pr.get('state', 'not checked')}")
    L.append("")
    L.append("## Appendix: omitted, merged and summarised propositions")
    L.append("")
    oc = Counter(o.decision for o in g.omissions)
    L.append("Counts: " + (", ".join(f"{k} {v}" for k, v in sorted(oc.items())) or "none"))
    L.append("")
    for o in g.omissions:
        if o.decision != "hidden_low_priority":
            L.append(f"- {o.proposition_id}: {o.decision}{' → ' + o.into if o.into else ''} — {o.reason}")
    hidden = [o.proposition_id for o in g.omissions if o.decision == "hidden_low_priority"]
    if hidden:
        L.append(f"- hidden (low priority, retained in analysis.json): {', '.join(hidden)}")
    L.append("")
    L.append("### Status legend")
    L.append("")
    for k, v in STATUS_LEGEND.items():
        L.append(f"- **{k}** — {v}")
    L.append("")
    return "\n".join(L)


# --------------------------------------------------------------------------- HTML

def html_report(g: KnowledgeGraph, snapshot: dict, title: str = "Proposition Analysis") -> str:
    data = {
        "sources": snapshot["sources"], "passages": snapshot["passages"],
        "propositions": snapshot["propositions"], "evidence": snapshot["evidence"],
        "relations": snapshot["relations"], "assessments": snapshot["assessments"],
        "issues": snapshot["issues"], "derivations": snapshot["derivations"],
        "ranking": snapshot.get("ranking", []), "omissions": snapshot.get("omissions", []),
        "limitations": snapshot.get("limitations", []), "changes": snapshot.get("changes"),
        "timeline": snapshot.get("timeline", []), "predictions": snapshot.get("predictions", []),
        "legend": STATUS_LEGEND, "version": PROCESSING_VERSION,
    }
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return _HTML.replace("__TITLE__", html.escape(title)).replace("__DATA__", payload)


_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Serif+KR:wght@400;700&family=Nanum+Myeongjo:wght@400;700&display=swap">
<style>
/* Typography: Korean text in Noto Serif KR (fallback Nanum Myeongjo); formulas in LaTeX's
   Latin Modern Math. Latin Modern Math is not on Google Fonts: it is used when installed
   locally (TeX Live / MiKTeX ship it) or when latinmodern-math.otf sits next to this file. */
@font-face{font-family:"LM Math";src:local("Latin Modern Math"),local("LatinModernMath-Regular"),
url("latinmodern-math.otf") format("opentype");font-display:swap}
@font-face{font-family:"KR Serif";src:local("Noto Serif KR"),local("NotoSerifKR-Regular"),
local("Nanum Myeongjo"),local("NanumMyeongjo");unicode-range:U+1100-11FF,U+3130-318F,U+A960-A97F,U+AC00-D7AF,U+D7B0-D7FF}
:root{--bg:#fbfaf8;--fg:#1d1d1f;--muted:#6b6b70;--card:#ffffff;--line:#e3e1dc;--accent:#2f5d8a;
--red:#b3261e;--red-bg:#fdecea;--amber:#8a5a00;--amber-bg:#fff4dc;--green:#1f6f43;--green-bg:#e7f4ec;--chip:#f0eee9}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#161618;--fg:#ececee;--muted:#a0a0a8;--card:#1f1f22;
--line:#34343a;--accent:#8ab4e0;--red:#ff8a80;--red-bg:#3a1d1b;--amber:#ffcc66;--amber-bg:#3a2f14;--green:#7fd1a0;--green-bg:#17301f;--chip:#2a2a2e}}
:root[data-theme="dark"]{--bg:#161618;--fg:#ececee;--muted:#a0a0a8;--card:#1f1f22;--line:#34343a;--accent:#8ab4e0;
--red:#ff8a80;--red-bg:#3a1d1b;--amber:#ffcc66;--amber-bg:#3a2f14;--green:#7fd1a0;--green-bg:#17301f;--chip:#2a2a2e}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.6 "KR Serif","Noto Serif KR","Nanum Myeongjo",serif}
:lang(ko),.ko{font-family:"Noto Serif KR","Nanum Myeongjo",serif}
.formula{font-family:"LM Math","Latin Modern Math","KR Serif","Noto Serif KR","Nanum Myeongjo","STIX Two Math","Cambria Math",serif;
font-size:16px;overflow-wrap:anywhere}
header{padding:20px 16px 8px;max-width:1200px;margin:auto}h1{font-size:22px;margin:0 0 4px}
.sub{color:var(--muted);font-size:13px}main{max-width:1200px;margin:auto;padding:0 16px 40px}
nav{display:flex;gap:6px;flex-wrap:wrap;margin:12px 0}nav button{border:1px solid var(--line);background:var(--card);color:var(--fg);
padding:6px 12px;border-radius:999px;cursor:pointer}nav button.on{background:var(--accent);color:var(--bg);border-color:var(--accent)}
.filters{display:flex;gap:8px;flex-wrap:wrap;margin:8px 0 12px}.filters select,.filters input{padding:6px 8px;border:1px solid var(--line);
border-radius:8px;background:var(--card);color:var(--fg);min-width:0;max-width:100%}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin:8px 0}
.card.red{border-left:4px solid var(--red);background:var(--red-bg)}.card.amber{border-left:4px solid var(--amber)}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12.5px;overflow-wrap:anywhere}
.chip{display:inline-block;padding:1px 8px;border-radius:999px;background:var(--chip);font-size:12px;margin-right:4px}
.s-SUPPORTED{background:var(--green-bg);color:var(--green)}.s-CONTRADICTED,.s-RETRACTED{background:var(--red-bg);color:var(--red)}
.s-CONFLICTING_EVIDENCE,.s-HUMAN_REVIEW_REQUIRED{background:var(--amber-bg);color:var(--amber)}
.redtxt{color:var(--red);font-weight:600}details>summary{cursor:pointer}mark{background:var(--amber-bg);color:inherit}
table{border-collapse:collapse;width:100%;font-size:13px}td,th{border-bottom:1px solid var(--line);padding:6px;text-align:left;vertical-align:top}
.tablewrap{overflow-x:auto}#graph{width:100%;height:520px;border:1px solid var(--line);border-radius:10px;background:var(--card)}
.legend span{margin-right:10px;font-size:12px}.muted{color:var(--muted)}ol li{margin:2px 0}
</style></head><body>
<header><h1>__TITLE__</h1><div class="sub" id="summary"></div></header>
<main>
<nav id="tabs"></nav>
<section id="view"></section>
</main>
<script id="data" type="application/json">__DATA__</script>
<script>
const D=JSON.parse(document.getElementById('data').textContent);
const P=Object.fromEntries(D.propositions.map(p=>[p.id,p])),S=Object.fromEntries(D.sources.map(s=>[s.id,s])),
T=Object.fromEntries(D.passages.map(p=>[p.id,p])),A=Object.fromEntries(D.assessments.map(a=>[a.proposition_id,a])),
E=Object.fromEntries(D.evidence.map(e=>[e.id,e])),I=Object.fromEntries(D.issues.map(i=>[i.id,i])),
R=Object.fromEntries(D.relations.map(r=>[r.id,r]));
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const isRed=pid=>(P[pid].issue_refs||[]).some(i=>I[i].red&&(!I[i].details.probable_error_on||I[i].details.probable_error_on.includes(pid)));
const props=D.propositions.filter(p=>p.claim_type!=='compound');
const red=D.issues.filter(i=>i.red);
document.getElementById('summary').textContent=`${D.sources.length} sources · ${props.length} propositions · ${D.relations.length} relations · ${D.issues.length} issues (${red.length} red) · ${D.version}`;
const tabs=[['Propositions',viewProps],['Problems',viewIssues],['Graph',viewGraph],['Sources',viewSources],['Changes & limits',viewChanges]];
let cur=0;const nav=document.getElementById('tabs');
function drawTabs(){nav.innerHTML='';tabs.forEach(([n,f],i)=>{const b=document.createElement('button');b.textContent=n;if(i===cur)b.className='on';b.onclick=()=>{cur=i;drawTabs();f()};nav.appendChild(b)})}
function loc(p){const t=T[p.passage_id];return `${p.source_refs[0]}${t&&t.page!=null?' p.'+t.page:''}${t&&t.section?' §'+esc(t.section):''} ${p.passage_id||''}`}
function passageHTML(p){const t=T[p.passage_id];if(!t)return '<span class="muted">no passage</span>';
 if(!p.quote_span)return esc(t.text);const[a,b]=p.quote_span;return esc(t.text.slice(0,a))+'<mark>'+esc(t.text.slice(a,b))+'</mark>'+esc(t.text.slice(b))}
function propCard(p,open){const a=A[p.id]||{};const rd=isRed(p.id);
 const ev=(p.evidence_refs||[]).map(e=>{const x=E[e];return `<li>${e} <b>${x.stance}</b> via ${x.via_proposition?`<a href="#" data-p="${x.via_proposition}">${x.via_proposition}</a>`:'logic'} · ${x.source_id} · ${x.basis} · ${x.primary?'primary':'secondary'} · ${x.directness} · strength ${x.strength} · group ${x.independence_group}${x.missing_method_details.length?' · missing: '+esc(x.missing_method_details.join(', ')):''}${x.conflicts_of_interest.length?' · COI: '+esc(x.conflicts_of_interest.join(', ')):''}</li>`}).join('');
 const rel=(p.relation_refs||[]).map(r=>{const x=R[r];const o=x.source===p.id?x.target:x.source;return `<li>${r} <b>${x.type}</b> ${x.source===p.id?'→':'←'} <a href="#" data-p="${o}">${o}</a> ${x.dimensions.length?'['+esc(x.dimensions.join(', '))+']':''} — ${esc(x.rationale)}</li>`}).join('');
 const iss=(p.issue_refs||[]).map(i=>`<li class="${I[i].red?'redtxt':''}">${i} ${I[i].category} (${I[i].finding_class}) — ${esc(I[i].reason)}</li>`).join('');
 const s=S[p.source_refs[0]];
 return `<div class="card ${rd?'red':''}" id="c-${p.id}"><details ${open?'open':''}><summary><b>${p.id}</b> <span class="chip s-${a.status}">${a.status}</span>${rd?'<span class="redtxt">● red</span> ':''}<span class="formula">${esc(p.text)}</span> <span class="muted">${loc(p)}</span></summary>
 <p lang="${T[p.passage_id]?T[p.passage_id].language:''}"><b>Original passage</b> (${esc(s.title||s.key)}${s.author?', '+esc(s.author):''}${s.published?', '+esc(s.published):''}):<br>${passageHTML(p)}</p>
 ${p.original_text?`<p><b>Original-language text:</b> ${esc(p.original_text)}</p>`:''}
 <p class="muted">type ${p.claim_type} · modality ${p.modality} · polarity ${p.polarity} · attribution ${p.attribution.kind}${p.attribution.speaker?' ('+esc(p.attribution.speaker)+')':''} · extraction ${esc(p.extraction.method)} conf ${p.extraction.confidence}${p.extraction.notes.length?' · '+esc(p.extraction.notes.join('; ')):''}</p>
 <p><b>Assessment:</b> ${esc(a.rationale)} (confidence ${a.confidence??'n/a'}, Belnap ${a.belnap}, S=${a.support_strength}, C=${a.challenge_strength})</p>
 ${ev?'<b>Evidence</b><ul>'+ev+'</ul>':''}${rel?'<b>Relations</b><ul>'+rel+'</ul>':''}${iss?'<b>Issues</b><ul>'+iss+'</ul>':''}</details></div>`}
function bindLinks(root){root.querySelectorAll('a[data-p]').forEach(a=>a.onclick=e=>{e.preventDefault();cur=0;drawTabs();viewProps(a.dataset.p)})}
function viewProps(focus){const v=document.getElementById('view');
 const statuses=[...new Set(D.assessments.map(a=>a.status))].sort(),srcs=D.sources.map(s=>s.id),cats=[...new Set(D.issues.map(i=>i.category))].sort();
 v.innerHTML=`<div class="filters"><input id="q" placeholder="search text…" aria-label="search"><select id="fs"><option value="">all statuses</option>${statuses.map(s=>`<option>${s}</option>`).join('')}</select>
 <select id="fc"><option value="">all issue categories</option>${cats.map(s=>`<option>${s}</option>`).join('')}</select><select id="fsrc"><option value="">all sources</option>${srcs.map(s=>`<option>${s}</option>`).join('')}</select>
 <select id="fr"><option value="core">core report</option><option value="all">all propositions</option><option value="red">red only</option></select></div><div id="list"></div>`;
 const core=new Set(D.ranking.filter(r=>r.decision!=='hidden_low_priority').map(r=>r.id));const order=Object.fromEntries(D.ranking.map(r=>[r.id,r.rank]));
 function draw(){const q=v.querySelector('#q').value.toLowerCase(),fs=v.querySelector('#fs').value,fc=v.querySelector('#fc').value,fsrc=v.querySelector('#fsrc').value,fr=v.querySelector('#fr').value;
  let L=props.filter(p=>(!q||(p.text+' '+p.quote).toLowerCase().includes(q))&&(!fs||A[p.id].status===fs)&&(!fsrc||p.source_refs.includes(fsrc))&&(!fc||p.issue_refs.some(i=>I[i].category===fc))&&(fr==='all'||(fr==='red'?isRed(p.id):core.has(p.id))));
  if(focus&&P[focus]&&!L.includes(P[focus]))L.unshift(P[focus]);
  L.sort((a,b)=>(order[a.id]??1e9)-(order[b.id]??1e9));
  const box=v.querySelector('#list');box.innerHTML=L.map(p=>propCard(p,p.id===focus)).join('')||'<p class="muted">No propositions match.</p>';bindLinks(box);
  if(focus){const el=document.getElementById('c-'+focus);if(el)el.scrollIntoView({block:'center'})}}
 v.querySelectorAll('input,select').forEach(x=>x.oninput=draw);if(focus)v.querySelector('#fr').value='all';draw()}
function viewIssues(){const v=document.getElementById('view');const order={CRITICAL:0,HIGH:1,MEDIUM:2,LOW:3};
 const L=[...D.issues].sort((a,b)=>(b.red-a.red)||(order[a.severity]-order[b.severity]));
 v.innerHTML=L.map(i=>`<div class="card ${i.red?'red':'amber'}"><b>${i.id}</b> ${i.red?'<span class="redtxt">RED</span>':''} <span class="chip">${i.category}</span><span class="chip">${i.finding_class}</span>
 <ol><li><b>Affected:</b> ${i.affected.map(x=>P[x]?`<a href="#" data-p="${x}">${x}</a> <span class="formula">${esc(P[x].text)}</span>`:x).join(', ')}</li><li><b>Category:</b> ${i.category}</li>
 <li><b>Conflicting / relevant:</b> ${(i.conflicting||[]).map(x=>P[x]?`<a href="#" data-p="${x}">${x}</a>`:x).join(', ')||'—'}</li><li><b>Reason:</b> ${esc(i.reason)}</li>
 <li><b>Severity / confidence:</b> ${i.severity} / ${i.confidence} (${i.deterministic?'deterministic':'model'}: ${esc(i.detector)})</li>
 <li><b>Evidence:</b> ${(i.evidence||[]).map(x=>T[x]?`${x}: “${esc(T[x].text)}”`:esc(x)).join('<br>')||'—'}</li><li><b>Would resolve:</b> ${esc(i.resolution)}</li></ol>
 ${i.assumptions&&i.assumptions.length?'<p class="muted">Assumptions: '+esc(i.assumptions.join(' '))+'</p>':''}</div>`).join('')||'<p>No issues.</p>';bindLinks(v)}
function viewGraph(){const v=document.getElementById('view');const types=[...new Set(D.relations.map(r=>r.type))];
 const pal={CONTRADICTS:'var(--red)',DIFFERS_IN_SCOPE:'var(--amber)',DUPLICATES:'var(--green)',ENTAILS:'var(--green)',REFINES:'var(--accent)',DERIVED_FROM:'var(--muted)',CAUSES:'var(--accent)',QUALIFIES:'var(--muted)',CORRECTS:'var(--accent)',SUPPORTS:'var(--green)'};
 v.innerHTML=`<div class="legend">${types.map(t=>`<span><svg width="18" height="8"><line x1="0" y1="4" x2="18" y2="4" stroke="${pal[t]||'var(--fg)'}" stroke-width="2"/></svg> ${t}</span>`).join('')}</div><svg id="graph" role="img" aria-label="proposition graph"></svg><p class="muted">Click a node to open the proposition. Red nodes carry red issues. Only propositions with relations are shown.</p>`;
 const ids=[...new Set(D.relations.flatMap(r=>[r.source,r.target]))];const svg=v.querySelector('#graph');const W=svg.clientWidth||800,H=520;
 const n=ids.map((id,i)=>({id,x:W/2+Math.cos(i/ids.length*6.283)*W*0.35,y:H/2+Math.sin(i/ids.length*6.283)*H*0.38,vx:0,vy:0}));const ix=Object.fromEntries(n.map((x,i)=>[x.id,i]));
 const links=D.relations.map(r=>({a:ix[r.source],b:ix[r.target],t:r.type}));
 for(let k=0;k<300;k++){for(let i=0;i<n.length;i++)for(let j=i+1;j<n.length;j++){let dx=n[i].x-n[j].x,dy=n[i].y-n[j].y,d=Math.max(1,Math.hypot(dx,dy)),f=1800/(d*d);n[i].vx+=f*dx/d;n[i].vy+=f*dy/d;n[j].vx-=f*dx/d;n[j].vy-=f*dy/d}
  links.forEach(l=>{const A1=n[l.a],B=n[l.b];let dx=B.x-A1.x,dy=B.y-A1.y,d=Math.max(1,Math.hypot(dx,dy)),f=(d-90)*0.02;A1.vx+=f*dx/d;A1.vy+=f*dy/d;B.vx-=f*dx/d;B.vy-=f*dy/d});
  n.forEach(p=>{p.vx+=(W/2-p.x)*0.002;p.vy+=(H/2-p.y)*0.002;p.x=Math.min(W-30,Math.max(30,p.x+p.vx*0.5));p.y=Math.min(H-20,Math.max(20,p.y+p.vy*0.5));p.vx*=0.6;p.vy*=0.6})}
 svg.setAttribute('viewBox',`0 0 ${W} ${H}`);
 svg.innerHTML=links.map(l=>`<line x1="${n[l.a].x}" y1="${n[l.a].y}" x2="${n[l.b].x}" y2="${n[l.b].y}" stroke="${pal[l.t]||'var(--fg)'}" stroke-width="2" opacity="0.8"><title>${l.t}</title></line>`).join('')+
  n.map(p=>`<g data-p="${p.id}" style="cursor:pointer"><circle cx="${p.x}" cy="${p.y}" r="9" fill="${isRed(p.id)?'var(--red)':'var(--accent)'}"><title>${esc(P[p.id].text)}</title></circle><text x="${p.x+11}" y="${p.y+4}" font-size="11" fill="var(--fg)">${p.id}</text></g>`).join('');
 svg.querySelectorAll('g[data-p]').forEach(g=>g.onclick=()=>{cur=0;drawTabs();viewProps(g.dataset.p)})}
function viewSources(){const v=document.getElementById('view');
 v.innerHTML='<div class="tablewrap"><table><tr><th>ID</th><th>Kind</th><th>Title</th><th>Author / publisher</th><th>Date</th><th>Locator</th><th>Lang</th><th>Group</th><th>Notes</th></tr>'+D.sources.map(s=>`<tr><td>${s.id}</td><td>${s.kind}</td><td>${esc(s.title||s.key)}</td><td>${esc([s.author,s.publisher].filter(Boolean).join(' / ')||'not stated')}</td><td>${esc(s.published||'not stated')}</td><td class="mono">${esc(s.doi||s.canonical_url||s.url||'—')}</td><td>${s.language}</td><td>${s.independence_group}</td><td>${[s.synthetic?'synthetic':'',s.retracted?'<span class="redtxt">RETRACTED</span>':'',s.reproduces?'reproduces '+s.reproduces:'',s.translation_of?'translation of '+s.translation_of:'',s.duplicate_of?'duplicate of '+s.duplicate_of:'',s.access_status!=='accessible'?s.access_status:''].filter(Boolean).join(', ')}</td></tr>`).join('')+'</table></div>'+
 D.sources.map(s=>`<details class="card"><summary>${s.id} passages</summary>${D.passages.filter(t=>t.source_id===s.id).map(t=>`<p lang="${t.language}"><span class="muted">${t.id}${t.page!=null?' p.'+t.page:''}${t.section?' §'+esc(t.section):''} [${t.language}]</span> ${esc(t.text)}</p>`).join('')}</details>`).join('')}
function viewChanges(){const v=document.getElementById('view');const c=D.changes;
 v.innerHTML='<h3>Changes since previous analysis</h3>'+(c?'<ul>'+Object.entries(c).map(([k,x])=>`<li>${k.replace(/_/g,' ')}: ${x.length?x.map(y=>typeof y==='object'?`${y.id}: ${y.from}→${y.to}`:y).join(', '):'none'}</li>`).join('')+'</ul>':'<p class="muted">No previous analysis supplied.</p>')+
 '<h3>Limitations</h3><ul>'+(D.limitations.map(l=>`<li>${esc(l)}</li>`).join('')||'<li>None recorded.</li>')+'</ul><h3>Status legend</h3><ul>'+Object.entries(D.legend).map(([k,x])=>`<li><b>${k}</b> — ${esc(x)}</li>`).join('')+'</ul>'+
 '<h3>Timeline</h3>'+(D.timeline.length?'<ul>'+D.timeline.map(e=>`<li class="${e.consistent?'':'redtxt'}"><b>${esc(e.place)}</b> (${esc(e.author)}): ${!e.checked?'single source':e.consistent?'consistent, start '+e.start_window.join('…'):'inconsistent, gap '+e.conflict.gap_days+' day(s)'}<ul>${e.statements.map(s=>`<li>${s.source} [${s.kind}] “${esc(s.quote)}” → ${s.implied_start.join('…')}</li>`).join('')}</ul></li>`).join('')+'</ul>':'<p class="muted">No dated episodes.</p>')+
 (D.predictions.length?'<h3>Predictions</h3><ul>'+D.predictions.map(p=>`<li>${p.proposition} <span class="formula">${esc(p.text)}</span> — due ${p.due||'n/a'}: ${esc(p.state||'')}</li>`).join('')+'</ul>':'')+
 '<h3>Omissions</h3><ul>'+D.omissions.map(o=>`<li>${o.proposition_id}: ${o.decision}${o.into?' → '+o.into:''} — ${esc(o.reason)}</li>`).join('')+'</ul>'}
drawTabs();viewProps();
</script></body></html>
"""
