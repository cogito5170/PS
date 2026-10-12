"""Reproducible evaluation against labeled datasets (eval/DATASET_FORMAT.md).

Every number written by this module is *measured* by running the engine on the
dataset; nothing is estimated.  Metrics:

* issue detection P/R/F1 — strict (exact category) and family-level
* red-warning precision, false-alarm rate on cases labelled ``no_red``
* forbidden-category violations
* proposition extraction P/R (token-overlap matching against gold triples)
* relation P/R (labelled relations; precision over relation types that are labelled)
* status accuracy; independence-group pairwise accuracy
* traceability coverage (quote verbatim in passage, passage span = archive span,
  source metadata present)
* calibration of issue confidence (Brier score, ECE over 5 bins)
* compression ratio, latency per case / per proposition, model calls
"""
from __future__ import annotations

import json
import re
import statistics
import sys
import time
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path
from typing import Optional

from .models import ClaimType, IssueCategory
from .pipeline import analyze
from .textutil import content_set, jaccard, norm_ws

FAMILIES = {
    "CONTRADICTION": {"NUMERICAL_INCONSISTENCY", "CATEGORICAL_CONFLICT", "TEMPORAL_DISAGREEMENT",
                      "INTERNAL_INCONSISTENCY", "MISSING_CONDITION"},
    "INFERENCE": {"INVALID_INFERENCE", "UNSUPPORTED_CAUSAL_CLAIM"},
}
EXCLUDED_FROM_ISSUE_SCORING = {IssueCategory.SOURCE_UNAVAILABLE.value, IssueCategory.EXTRACTION_UNCERTAIN.value}


def family(cat: str) -> str:
    for f, members in FAMILIES.items():
        if cat in members:
            return f
    return cat


def _norm(s: str) -> str:
    return norm_ws(s).lower()


def _matches_sentence(g, pid: str, needle: str) -> bool:
    if pid in g.propositions:
        return _norm(needle) in _norm(g.propositions[pid].quote)
    if pid in g.sources:  # issue attached to a whole source
        return _norm(needle) in _norm(g.archive.get(pid, ""))
    return False


def _props_for(g, needle: str) -> list[str]:
    return [p.id for p in g.propositions.values()
            if p.claim_type != ClaimType.COMPOUND and _norm(needle) in _norm(p.quote)]


def _issue_touches(g, issue, needles: list[str]) -> bool:
    refs = list(issue.affected) + list(issue.conflicting)
    return any(_matches_sentence(g, r, n) for r in refs for n in needles)


def evaluate_case(case: dict) -> dict:
    docs = case["documents"]
    t0 = time.perf_counter()
    g = analyze(docs, now="2026-01-01T00:00:00+00:00")
    elapsed = time.perf_counter() - t0
    exp = case.get("expected", {})
    res: dict = {"id": case["id"], "category": case["category"], "seconds": elapsed,
                 "n_props": sum(1 for p in g.propositions.values() if p.claim_type != ClaimType.COMPOUND),
                 "model_calls": g.model_calls}
    issues = [i for i in g.issues.values() if i.category.value not in EXCLUDED_FROM_ISSUE_SCORING]

    # ---- issues
    gold = exp.get("issues", [])
    strict_tp, fam_tp = 0, 0
    used_strict, used_fam = set(), set()
    gold_detail = []
    for gi in gold:
        cat = gi["category"]
        cands = [i for i in issues if _issue_touches(g, i, gi["affected"])]
        s = next((i for i in cands if i.category.value == cat and i.id not in used_strict), None)
        f = next((i for i in cands if family(i.category.value) == family(cat) and i.id not in used_fam), None)
        if s:
            strict_tp += 1
            used_strict.add(s.id)
        if f:
            fam_tp += 1
            used_fam.add(f.id)
        gold_detail.append({"category": cat, "strict": bool(s), "family": bool(f),
                            "red_expected": gi.get("red"), "red_got": (f.red if f else None)})
    # predicted issues that match no gold issue (family-level) are false positives, but
    # only issues that are *about* labelled phenomena can be judged: every predicted
    # issue counts, since the cases are small and fully labelled.
    res["issues"] = {"gold": len(gold), "pred": len(issues), "tp_strict": strict_tp, "tp_family": fam_tp,
                     "pred_matched_strict": len(used_strict), "pred_matched_family": len(used_fam),
                     "gold_detail": gold_detail,
                     "pred_detail": [{"id": i.id, "category": i.category.value, "red": i.red,
                                      "confidence": i.confidence, "matched": i.id in used_fam}
                                     for i in issues]}
    forbidden = set(exp.get("forbidden_issue_categories", []))
    res["forbidden_violations"] = sorted({i.category.value for i in issues if i.category.value in forbidden})
    red = [i for i in issues if i.red]
    res["red"] = {"n": len(red), "matched": sum(1 for i in red if i.id in used_fam),
                  "no_red_case": bool(exp.get("no_red")), "false_alarm": bool(exp.get("no_red")) and bool(red)}

    # ---- propositions
    gp = exp.get("propositions", [])
    prop_tp = 0
    for gold_p in gp:
        cands = _props_for(g, gold_p["sentence"])
        ok = False
        for pid in cands:
            p = g.propositions[pid]
            subj = jaccard(content_set(gold_p.get("subject", "")), content_set(p.subject)) >= 0.5 or \
                (content_set(gold_p.get("subject", "")) and content_set(gold_p.get("subject", "")) <= content_set(p.subject + " " + (p.object or "")))
            obj_gold = gold_p.get("object")
            obj = True if not obj_gold else bool(content_set(obj_gold) & content_set((p.object or "") + " " + (p.quantity.raw if p.quantity else "") + " " + p.subject))
            pol = gold_p.get("polarity", "positive") == p.polarity.value
            if subj and obj and pol:
                ok = True
                break
        prop_tp += ok
    sentences_with_gold = {_norm(x["sentence"]) for x in gp}
    pred_in_gold_sentences = [p for p in g.propositions.values() if p.claim_type != ClaimType.COMPOUND
                              and any(s in _norm(p.quote) for s in sentences_with_gold)]
    res["propositions"] = {"gold": len(gp), "tp": prop_tp, "pred_in_labeled_sentences": len(pred_in_gold_sentences)}

    # ---- relations
    gr = exp.get("relations", [])
    rel_tp = 0
    for gold_r in gr:
        a, b = gold_r["between"]
        pa, pb = set(_props_for(g, a)), set(_props_for(g, b))
        hit = any(r.type.value == gold_r["type"] and ((r.source in pa and r.target in pb) or (r.source in pb and r.target in pa))
                  for r in g.relations.values())
        rel_tp += hit
    labeled_types = {r["type"] for r in gr}
    pred_rel = [r for r in g.relations.values() if r.type.value in labeled_types]
    res["relations"] = {"gold": len(gr), "tp": rel_tp, "pred_of_labeled_types": len(pred_rel)}

    # ---- statuses
    gs = exp.get("statuses", [])
    st_ok, st_detail, calib = 0, [], []
    for gold_s in gs:
        pids = _props_for(g, gold_s["sentence"])
        got = sorted({g.assessments[p].status.value for p in pids})
        ok = gold_s["status"] in got
        st_ok += ok
        st_detail.append({"sentence": gold_s["sentence"], "expected": gold_s["status"], "got": got})
        for p in pids:
            c = g.assessments[p].confidence
            if c is not None:
                calib.append((c, g.assessments[p].status.value == gold_s["status"]))
    res["statuses"] = {"gold": len(gs), "correct": st_ok, "detail": st_detail}
    res["status_calibration"] = calib

    # ---- independence groups
    gg = exp.get("independent_groups")
    if gg:
        key_to_src = {s.key: s for s in g.sources.values()}
        gold_group = {k: i for i, grp in enumerate(gg) for k in grp}
        keys = [k for k in gold_group if k in key_to_src]
        pairs = list(combinations(sorted(keys), 2))
        agree = sum((gold_group[x] == gold_group[y]) ==
                    (key_to_src[x].independence_group == key_to_src[y].independence_group) for x, y in pairs)
        res["independence"] = {"pairs": len(pairs), "agree": agree}

    # ---- traceability
    props = [p for p in g.propositions.values() if p.claim_type != ClaimType.COMPOUND]
    ok = 0
    for p in props:
        pas = g.passages.get(p.passage_id)
        src = g.sources.get(p.source_refs[0])
        good = (pas is not None and src is not None and p.quote and p.quote in pas.text
                and g.archive[src.id][pas.char_start:pas.char_end] == pas.text
                and (p.quote_span is None or pas.text[p.quote_span[0]:p.quote_span[1]] == p.quote)
                and src.retrieved_at is not None)
        ok += bool(good)
    res["traceability"] = {"props": len(props), "traceable": ok}
    res["integrity_errors"] = g.validate()

    # ---- issue calibration
    res["issue_calibration"] = [(i.confidence, i.id in used_fam) for i in issues]

    # ---- compression
    src_words = sum(len(t.split()) for t in g.archive.values())
    core = [r["id"] for r in g.ranking if r["decision"] != "hidden_low_priority"]
    res["compression"] = {"source_words": src_words,
                          "core_words": sum(len(g.propositions[x].text.split()) for x in core)}
    return res


def _prf(tp_p: int, n_pred: int, tp_g: int, n_gold: int) -> tuple:
    p = tp_p / n_pred if n_pred else None
    r = tp_g / n_gold if n_gold else None
    f = 2 * p * r / (p + r) if p and r else (0.0 if p is not None and r is not None else None)
    return p, r, f


def _calibration(pairs: list) -> dict:
    if not pairs:
        return {"n": 0}
    brier = sum((c - y) ** 2 for c, y in pairs) / len(pairs)
    bins = defaultdict(list)
    for c, y in pairs:
        bins[min(4, int(c * 5))].append((c, y))
    ece = sum(len(b) / len(pairs) * abs(statistics.mean(c for c, _ in b) - statistics.mean(y for _, y in b))
              for b in bins.values())
    table = {f"{k / 5:.1f}-{(k + 1) / 5:.1f}": {"n": len(b), "mean_conf": round(statistics.mean(c for c, _ in b), 3),
                                                "accuracy": round(statistics.mean(y for _, y in b), 3)}
             for k, b in sorted(bins.items())}
    return {"n": len(pairs), "brier": round(brier, 4), "ece": round(ece, 4), "bins": table}


def aggregate(results: list[dict]) -> dict:
    s = lambda path: sum(r[path[0]][path[1]] for r in results if path[0] in r)  # noqa: E731
    agg: dict = {"cases": len(results)}
    p, r, f = _prf(s(("issues", "pred_matched_strict")), s(("issues", "pred")), s(("issues", "tp_strict")), s(("issues", "gold")))
    agg["issues_strict"] = {"precision": p, "recall": r, "f1": f}
    p, r, f = _prf(s(("issues", "pred_matched_family")), s(("issues", "pred")), s(("issues", "tp_family")), s(("issues", "gold")))
    agg["issues_family"] = {"precision": p, "recall": r, "f1": f, "gold": s(("issues", "gold")), "pred": s(("issues", "pred"))}
    # per category (family match, gold side)
    per = defaultdict(lambda: {"gold": 0, "found": 0, "pred": 0, "pred_matched": 0})
    for res in results:
        for gd in res["issues"]["gold_detail"]:
            per[gd["category"]]["gold"] += 1
            per[gd["category"]]["found"] += gd["family"]
        for pd in res["issues"]["pred_detail"]:
            per[pd["category"]]["pred"] += 1
            per[pd["category"]]["pred_matched"] += pd["matched"]
    agg["per_category"] = dict(sorted(per.items()))
    # contradiction detection (family CONTRADICTION)
    cg = sum(1 for res in results for gd in res["issues"]["gold_detail"] if family(gd["category"]) == "CONTRADICTION")
    cf = sum(1 for res in results for gd in res["issues"]["gold_detail"] if family(gd["category"]) == "CONTRADICTION" and gd["family"])
    cp = sum(1 for res in results for pd in res["issues"]["pred_detail"] if family(pd["category"]) == "CONTRADICTION")
    cpm = sum(1 for res in results for pd in res["issues"]["pred_detail"] if family(pd["category"]) == "CONTRADICTION" and pd["matched"])
    p, r, f = _prf(cpm, cp, cf, cg)
    agg["contradiction_detection"] = {"precision": p, "recall": r, "f1": f, "gold": cg, "pred": cp}
    reds = sum(res["red"]["n"] for res in results)
    agg["red"] = {"total": reds, "matched_gold": sum(res["red"]["matched"] for res in results),
                  "precision": (sum(res["red"]["matched"] for res in results) / reds) if reds else None,
                  "no_red_cases": sum(res["red"]["no_red_case"] for res in results),
                  "no_red_cases_with_false_alarm": sum(res["red"]["false_alarm"] for res in results)}
    nr = agg["red"]["no_red_cases"]
    agg["red"]["false_alarm_case_rate"] = agg["red"]["no_red_cases_with_false_alarm"] / nr if nr else None
    red_exp = [(gd["red_expected"], gd["red_got"]) for res in results for gd in res["issues"]["gold_detail"]
               if gd["red_got"] is not None and gd["red_expected"] is not None]
    agg["red"]["red_label_agreement_on_found_issues"] = (sum(a == b for a, b in red_exp) / len(red_exp)) if red_exp else None
    agg["forbidden_violations"] = sum(len(res["forbidden_violations"]) for res in results)
    agg["propositions"] = {"gold": s(("propositions", "gold")), "tp": s(("propositions", "tp")),
                           "recall": (s(("propositions", "tp")) / s(("propositions", "gold"))) if s(("propositions", "gold")) else None,
                           "pred_in_labeled_sentences": s(("propositions", "pred_in_labeled_sentences"))}
    pg = agg["propositions"]
    pg["precision_proxy"] = (pg["tp"] / pg["pred_in_labeled_sentences"]) if pg["pred_in_labeled_sentences"] else None
    agg["relations"] = {"gold": s(("relations", "gold")), "tp": s(("relations", "tp")),
                        "recall": (s(("relations", "tp")) / s(("relations", "gold"))) if s(("relations", "gold")) else None,
                        "pred_of_labeled_types": s(("relations", "pred_of_labeled_types"))}
    agg["statuses"] = {"gold": s(("statuses", "gold")), "correct": s(("statuses", "correct")),
                       "accuracy": (s(("statuses", "correct")) / s(("statuses", "gold"))) if s(("statuses", "gold")) else None}
    ind = [res["independence"] for res in results if "independence" in res]
    agg["independence"] = {"pairs": sum(x["pairs"] for x in ind), "agree": sum(x["agree"] for x in ind)}
    agg["independence"]["accuracy"] = (agg["independence"]["agree"] / agg["independence"]["pairs"]) if agg["independence"]["pairs"] else None
    agg["traceability"] = {"props": s(("traceability", "props")), "traceable": s(("traceability", "traceable"))}
    agg["traceability"]["coverage"] = (agg["traceability"]["traceable"] / agg["traceability"]["props"]) if agg["traceability"]["props"] else None
    agg["integrity_errors"] = sum(len(res["integrity_errors"]) for res in results)
    agg["issue_calibration"] = _calibration([x for res in results for x in res["issue_calibration"]])
    agg["status_calibration"] = _calibration([x for res in results for x in res["status_calibration"]])
    sw = s(("compression", "source_words"))
    agg["compression_ratio"] = s(("compression", "core_words")) / sw if sw else None
    secs = [res["seconds"] for res in results]
    agg["latency"] = {"total_s": round(sum(secs), 4), "mean_case_ms": round(1000 * statistics.mean(secs), 2),
                      "max_case_ms": round(1000 * max(secs), 2),
                      "ms_per_proposition": round(1000 * sum(secs) / max(1, sum(res["n_props"] for res in results)), 3)}
    agg["model_calls"] = sum(res["model_calls"] for res in results)
    return agg


def run_dataset(path: str | Path) -> tuple[dict, list[dict]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    results = [evaluate_case(c) for c in data["cases"]]
    return aggregate(results), results


def _fmt(x) -> str:
    if x is None:
        return "n/a"
    if isinstance(x, float):
        return f"{x:.3f}"
    return str(x)


def markdown(name: str, agg: dict, results: list[dict]) -> str:
    L = [f"### Dataset `{name}` — {agg['cases']} cases", ""]
    L.append("| Metric | Value |")
    L.append("|---|---|")
    rows = [
        ("Issue detection, family-level P / R / F1", f"{_fmt(agg['issues_family']['precision'])} / {_fmt(agg['issues_family']['recall'])} / {_fmt(agg['issues_family']['f1'])} (gold {agg['issues_family']['gold']}, predicted {agg['issues_family']['pred']})"),
        ("Issue detection, strict-category P / R / F1", f"{_fmt(agg['issues_strict']['precision'])} / {_fmt(agg['issues_strict']['recall'])} / {_fmt(agg['issues_strict']['f1'])}"),
        ("Contradiction detection P / R / F1", f"{_fmt(agg['contradiction_detection']['precision'])} / {_fmt(agg['contradiction_detection']['recall'])} / {_fmt(agg['contradiction_detection']['f1'])} (gold {agg['contradiction_detection']['gold']}, predicted {agg['contradiction_detection']['pred']})"),
        ("Red warnings: total / matching a gold issue (precision)", f"{agg['red']['total']} / {agg['red']['matched_gold']} ({_fmt(agg['red']['precision'])})"),
        ("False-alarm rate on `no_red` cases", f"{agg['red']['no_red_cases_with_false_alarm']} of {agg['red']['no_red_cases']} ({_fmt(agg['red']['false_alarm_case_rate'])})"),
        ("Red/non-red agreement on found gold issues", _fmt(agg['red']['red_label_agreement_on_found_issues'])),
        ("Forbidden-category violations", str(agg['forbidden_violations'])),
        ("Proposition extraction recall (precision proxy)", f"{_fmt(agg['propositions']['recall'])} ({_fmt(agg['propositions']['precision_proxy'])}) — {agg['propositions']['tp']}/{agg['propositions']['gold']}"),
        ("Relation recall (predicted relations of labelled types)", f"{_fmt(agg['relations']['recall'])} — {agg['relations']['tp']}/{agg['relations']['gold']} ({agg['relations']['pred_of_labeled_types']})"),
        ("Status accuracy", f"{_fmt(agg['statuses']['accuracy'])} — {agg['statuses']['correct']}/{agg['statuses']['gold']}"),
        ("Evidence-independence pairwise accuracy", f"{_fmt(agg['independence']['accuracy'])} — {agg['independence']['agree']}/{agg['independence']['pairs']} pairs"),
        ("Source traceability coverage", f"{_fmt(agg['traceability']['coverage'])} — {agg['traceability']['traceable']}/{agg['traceability']['props']}"),
        ("Integrity violations", str(agg['integrity_errors'])),
        ("Issue-confidence calibration (Brier / ECE, n)", f"{_fmt(agg['issue_calibration'].get('brier'))} / {_fmt(agg['issue_calibration'].get('ece'))} (n={agg['issue_calibration']['n']})"),
        ("Status-confidence calibration (Brier / ECE, n)", f"{_fmt(agg['status_calibration'].get('brier'))} / {_fmt(agg['status_calibration'].get('ece'))} (n={agg['status_calibration']['n']})"),
        ("Report compression ratio (core words / source words)", _fmt(agg['compression_ratio'])),
        ("Latency: mean / max per case, per proposition", f"{agg['latency']['mean_case_ms']} ms / {agg['latency']['max_case_ms']} ms, {agg['latency']['ms_per_proposition']} ms"),
        ("Model calls (processing cost)", str(agg['model_calls'])),
    ]
    for k, v in rows:
        L.append(f"| {k} | {v} |")
    L.append("")
    L.append("Per issue category (gold found / gold; predicted matched / predicted):")
    L.append("")
    L.append("| Category | Recall | Precision |")
    L.append("|---|---|---|")
    for cat, v in agg["per_category"].items():
        L.append(f"| {cat} | {v['found']}/{v['gold']} | {v['pred_matched']}/{v['pred']} |")
    L.append("")
    L.append("Per case:")
    L.append("")
    L.append("| Case | Category | Gold issues found (family) | Predicted (red) | Forbidden violated | Statuses |")
    L.append("|---|---|---|---|---|---|")
    for r in results:
        L.append(f"| {r['id']} | {r['category']} | {r['issues']['tp_family']}/{r['issues']['gold']} | "
                 f"{r['issues']['pred']} ({r['red']['n']}) | {', '.join(r['forbidden_violations']) or '—'} | "
                 f"{r['statuses']['correct']}/{r['statuses']['gold']} |")
    L.append("")
    for cal_name in ("issue_calibration", "status_calibration"):
        cal = agg[cal_name]
        if cal.get("bins"):
            L.append(f"{cal_name.replace('_', ' ').capitalize()} bins: " + "; ".join(
                f"{k}: n={v['n']}, conf {v['mean_conf']}, acc {v['accuracy']}" for k, v in cal["bins"].items()))
            L.append("")
    return "\n".join(L)


def main(datasets: list[str], out: Optional[str] = None, json_out: Optional[str] = None) -> int:
    parts, dump = [], {}
    for ds in datasets:
        agg, results = run_dataset(ds)
        name = Path(ds).stem
        dump[name] = {"aggregate": agg, "cases": results}
        md = markdown(name, agg, results)
        parts.append(md)
        print(md)
    if out:
        Path(out).write_text("\n\n".join(parts) + "\n", encoding="utf-8")
    if json_out:
        Path(json_out).write_text(json.dumps(dump, indent=1, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:] or ["eval/dataset/dev.json"]))
