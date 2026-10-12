"""Command-line interface.

  python -m upae analyze <path> [--out DIR] [--previous DIR/analysis.json] [--query TEXT]
  python -m upae search <DIR/analysis.sqlite> <query>
  python -m upae evaluate [dataset.json ...] [--out EVALUATION_REPORT.md]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .ingest import load_path
from .pipeline import analyze, snapshot
from .providers import get_provider
from .report import html_report, markdown_report
from .store import save, search


def cmd_analyze(args) -> int:
    docs = load_path(args.path)
    previous = json.loads(Path(args.previous).read_text(encoding="utf-8")) if args.previous else None
    config = {}
    if args.query:
        config["query"] = args.query
    if args.max_core:
        config["max_core"] = args.max_core
    g = analyze(docs, config=config, provider=get_provider(args.provider), previous=previous,
                now=args.now)
    snap = snapshot(g)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "analysis.json").write_text(json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "report.md").write_text(markdown_report(g, args.title, args.now or snap["sources"][0]["retrieved_at"]
                                                   if snap["sources"] else None), encoding="utf-8")
    (out / "report.html").write_text(html_report(g, snap, args.title), encoding="utf-8")
    save(snap, out / "analysis.sqlite")
    red = sum(1 for i in g.issues.values() if i.red)
    print(f"{len(g.sources)} sources, {len(g.propositions)} propositions, {len(g.relations)} relations, "
          f"{len(g.issues)} issues ({red} red) → {out}/report.md, report.html, analysis.json, analysis.sqlite")
    integrity = [l for l in g.limitations if l.startswith("integrity:")]
    if integrity:
        print("INTEGRITY ERRORS:\n" + "\n".join(integrity), file=sys.stderr)
        return 2
    return 0


def cmd_search(args) -> int:
    for r in search(args.db, args.query, args.limit):
        print(f"{r['id']}  [{r['status']}]  {r['text']}  ({r['source']})")
    return 0


def cmd_evaluate(args) -> int:
    from .evaluate import main as eval_main
    return eval_main(args.datasets, args.out, args.json_out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="upae", description="Universal Proposition Analysis Engine")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("analyze", help="analyse a file or directory of documents")
    a.add_argument("path")
    a.add_argument("--out", default="out")
    a.add_argument("--previous", help="analysis.json of a previous run (stable IDs + change report)")
    a.add_argument("--query", help="relevance query used for ranking")
    a.add_argument("--max-core", type=int, dest="max_core")
    a.add_argument("--provider", default="none", help="none (default) | anthropic[:model]")
    a.add_argument("--title", default="Proposition Analysis Report")
    a.add_argument("--now", help="fixed timestamp (ISO 8601) for reproducible output")
    a.set_defaults(func=cmd_analyze)
    s = sub.add_parser("search", help="full-text search over a saved analysis")
    s.add_argument("db")
    s.add_argument("query")
    s.add_argument("--limit", type=int, default=20)
    s.set_defaults(func=cmd_search)
    e = sub.add_parser("evaluate", help="run the labeled evaluation datasets")
    e.add_argument("datasets", nargs="*", default=["eval/dataset/dev.json"])
    e.add_argument("--out", default=None, help="write a Markdown evaluation report")
    e.add_argument("--json-out", default=None, dest="json_out")
    e.set_defaults(func=cmd_evaluate)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
