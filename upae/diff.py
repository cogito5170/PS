"""Changes since the previous analysis, matched by stable fingerprints."""
from __future__ import annotations


def _props(snap: dict) -> dict:
    return {p["fingerprint"]: p for p in snap.get("propositions", [])}


def _issue_fps(snap: dict) -> dict:
    fps = snap.get("fingerprints", {})
    return {fps.get(i["id"], i["id"]): i for i in snap.get("issues", [])}


def diff_snapshots(prev: dict, cur: dict) -> dict:
    pp, cp = _props(prev), _props(cur)
    pa = {a["proposition_id"]: a for a in prev.get("assessments", [])}
    ca = {a["proposition_id"]: a for a in cur.get("assessments", [])}
    status_changes = []
    for fp in sorted(set(pp) & set(cp)):
        old, new = pa.get(pp[fp]["id"], {}), ca.get(cp[fp]["id"], {})
        if old.get("status") != new.get("status"):
            status_changes.append({"id": cp[fp]["id"], "from": old.get("status"), "to": new.get("status")})
    pi, ci = _issue_fps(prev), _issue_fps(cur)
    ps = {s["key"]: s for s in prev.get("sources", [])}
    cs = {s["key"]: s for s in cur.get("sources", [])}
    return {
        "sources_added": sorted(cs[k]["id"] for k in set(cs) - set(ps)),
        "sources_removed": sorted(ps[k]["id"] for k in set(ps) - set(cs)),
        "sources_changed": sorted(cs[k]["id"] for k in set(cs) & set(ps)
                                  if cs[k].get("content_hash") != ps[k].get("content_hash")),
        "propositions_added": sorted(cp[f]["id"] for f in set(cp) - set(pp)),
        "propositions_removed": sorted(pp[f]["id"] for f in set(pp) - set(cp)),
        "status_changes": status_changes,
        "issues_opened": sorted(ci[f]["id"] for f in set(ci) - set(pi)),
        "issues_resolved": sorted(pi[f]["id"] for f in set(pi) - set(ci)),
    }
