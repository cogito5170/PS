"""End-to-end: ingestion, traceability, integrity, report contract, stable IDs, diff, storage."""
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from upae.cli import main as cli_main
from upae.ingest import load_path
from upae.models import ClaimType
from upae.pipeline import analyze, snapshot
from upae.report import markdown_report
from upae.store import save, search

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "examples" / "corpus"
NOW = "2026-01-01T00:00:00+00:00"


class FakeProvider:
    name = "fake"
    calls = 0

    def extract(self, text, language):
        self.calls += 1
        sentence = text.split(".")[0] + "."
        return [{"sentence": sentence, "subject": "x", "predicate": "asserts", "object": None,
                 "claim_type": "empirical", "negated": False, "hedged": False, "quantity": None, "time": None,
                 "location": None, "population": None, "conditions": [], "english_gloss": "gloss"}]

    def translate(self, text, s, t):
        return None


class DemoCorpus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs = load_path(CORPUS)
        cls.g = analyze(cls.docs, now=NOW)

    def test_all_formats_ingested_and_failures_reported(self):
        connectors = {d.get("connector") for d in self.docs}
        self.assertTrue({"json", "text", "html", "pdf"} <= connectors)
        self.assertTrue(any("archived_scan" in l for l in self.g.limitations))

    def test_integrity(self):
        self.assertEqual(self.g.validate(), [])

    def test_traceability(self):
        for p in self.g.propositions.values():
            if p.claim_type == ClaimType.COMPOUND:
                continue
            pas = self.g.passages[p.passage_id]
            self.assertEqual(pas.text[p.quote_span[0]:p.quote_span[1]], p.quote)
            self.assertEqual(self.g.archive[pas.source_id][pas.char_start:pas.char_end], pas.text)
            src = self.g.sources[p.source_refs[0]]
            self.assertIsNotNone(src.retrieved_at)

    def test_no_fabricated_metadata(self):
        oat = next(s for s in self.g.sources.values() if s.key == "oat-post")
        self.assertIsNone(oat.title)
        self.assertIsNone(oat.url)
        self.assertIsNone(oat.publisher)

    def test_every_red_issue_has_required_fields(self):
        reds = [i for i in self.g.issues.values() if i.red]
        self.assertGreater(len(reds), 5)
        for i in reds:
            self.assertTrue(i.affected and i.category and i.reason and i.resolution and i.evidence, i.id)
            self.assertIsNotNone(i.severity)
            self.assertGreaterEqual(i.confidence, 0.5)

    def test_expected_findings_present(self):
        cats = {i.category.value for i in self.g.issues.values() if i.red}
        for c in ("ARITHMETIC_ERROR", "MISLEADING_QUOTATION", "TRANSLATION_DISCREPANCY", "UNSUPPORTED_CAUSAL_CLAIM",
                  "RETRACTED_SOURCE_DEPENDENCY", "NUMERICAL_INCONSISTENCY"):
            self.assertIn(c, cats)
        self.assertIn("CORRECTS", {r.type.value for r in self.g.relations.values()})

    def test_arithmetic_copies_reported_once(self):
        ar = [i for i in self.g.issues.values() if i.category.value == "ARITHMETIC_ERROR"]
        self.assertEqual(len(ar), 1)
        self.assertEqual(len(ar[0].affected), 3)

    def test_report_has_ten_sections(self):
        md = markdown_report(self.g, "T", NOW)
        heads = re.findall(r"^## (\d+)\. ", md, re.M)
        self.assertEqual(heads, [str(i) for i in range(1, 11)])

    def test_omissions_are_recorded(self):
        merged = [o for o in self.g.omissions if o.decision == "merged"]
        self.assertTrue(merged)
        self.assertTrue(all(o.into in self.g.propositions for o in merged))
        self.assertTrue(all(o.proposition_id in self.g.propositions for o in self.g.omissions))

    def test_stable_ids_and_diff(self):
        snap = snapshot(self.g)
        g2 = analyze(self.docs, now=NOW, previous=snap)
        self.assertEqual(sorted(self.g.propositions), sorted(g2.propositions))
        self.assertEqual(g2.changes["propositions_added"], [])
        self.assertEqual(g2.changes["issues_opened"], [])
        # add a document: existing IDs keep their numbers, new ones are appended
        docs = self.docs + [{"key": "zz-new", "kind": "news", "synthetic": True,
                             "text": "The population of Norvik was 1.2 million in 2020."}]
        g3 = analyze(docs, now=NOW, previous=snap)
        for pid, p in self.g.propositions.items():
            self.assertEqual(g3.propositions[pid].fingerprint, p.fingerprint)
        self.assertEqual(len(g3.changes["propositions_added"]), 1)
        self.assertTrue(g3.changes["sources_added"])

    def test_sqlite_roundtrip_and_search(self):
        d = tempfile.mkdtemp()
        try:
            db = Path(d) / "a.sqlite"
            save(snapshot(self.g), db)
            hits = search(db, "population Norvik")
            self.assertTrue(hits)
            self.assertIn("norvik", hits[0]["text"])
        finally:
            shutil.rmtree(d)

    def test_deterministic_output(self):
        g2 = analyze(self.docs, now=NOW)
        a, b = snapshot(self.g), snapshot(g2)
        a.pop("timings"), b.pop("timings")  # wall-clock measurements differ by design
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))


class Providers(unittest.TestCase):
    def test_non_english_without_provider_is_a_limitation(self):
        g = analyze([{"key": "de", "kind": "news", "language": "de", "synthetic": True,
                      "text": "Die Arbeitslosenquote lag bei 6,1 Prozent und das ist nicht gut."}])
        self.assertEqual(len(g.propositions), 0)
        self.assertTrue(any("not extracted" in l for l in g.limitations))

    def test_model_output_is_marked_and_reviewed(self):
        prov = FakeProvider()
        g = analyze([{"key": "de", "kind": "news", "language": "de", "synthetic": True,
                      "text": "Die Arbeitslosenquote lag bei 6,1 Prozent und das ist nicht gut."}], provider=prov)
        p = next(iter(g.propositions.values()))
        self.assertFalse(p.extraction.deterministic)
        self.assertTrue(p.extraction.method.startswith("model:"))
        self.assertEqual(g.assessments[p.id].status.value, "HUMAN_REVIEW_REQUIRED")
        self.assertEqual(g.model_calls, 1)


class CLI(unittest.TestCase):
    def test_analyze_writes_outputs(self):
        d = tempfile.mkdtemp()
        try:
            rc = cli_main(["analyze", str(CORPUS), "--out", d, "--now", NOW])
            self.assertEqual(rc, 0)
            for f in ("report.md", "report.html", "analysis.json", "analysis.sqlite"):
                self.assertTrue((Path(d) / f).exists(), f)
            html = (Path(d) / "report.html").read_text(encoding="utf-8")
            self.assertIn('id="data"', html)
            self.assertNotIn("</script><", html.split('id="data"')[1].split("</script>")[0])
        finally:
            shutil.rmtree(d)


class DevRegression(unittest.TestCase):
    """Guards against regressions on the development set (not a generalisation claim)."""

    def test_dev_set(self):
        from upae.evaluate import run_dataset
        agg, _ = run_dataset(ROOT / "eval" / "dataset" / "dev.json")
        self.assertGreaterEqual(agg["issues_family"]["f1"], 0.9)
        self.assertEqual(agg["red"]["no_red_cases_with_false_alarm"], 0)
        self.assertEqual(agg["integrity_errors"], 0)
        self.assertEqual(agg["traceability"]["coverage"], 1.0)

    def test_dev_sns_set(self):
        from upae.evaluate import run_dataset
        agg, _ = run_dataset(ROOT / "eval" / "dataset" / "dev_sns.json")
        self.assertGreaterEqual(agg["issues_family"]["f1"], 0.9)
        self.assertEqual(agg["red"]["no_red_cases_with_false_alarm"], 0)
        self.assertEqual(agg["integrity_errors"], 0)

    def test_dev_ko_set(self):
        from upae.evaluate import run_dataset
        agg, _ = run_dataset(ROOT / "eval" / "dataset" / "dev_ko.json")
        self.assertGreaterEqual(agg["issues_family"]["f1"], 0.9)
        self.assertEqual(agg["red"]["no_red_cases_with_false_alarm"], 0)
        self.assertEqual(agg["integrity_errors"], 0)


if __name__ == "__main__":
    unittest.main()
