"""Contradiction semantics, evidence policy, status transitions, checks."""
import unittest

from upae.checks import check_arithmetic, compare_quote, meaning_changes, safe_eval
from upae.models import Assessment, FindingClass, IssueCategory, RelationType, Status
from upae.pipeline import analyze
from upae.status import TransitionError, allowed, transition


def doc(key, text, **kw):
    return {"key": key, "kind": kw.pop("kind", "web"), "text": text, "synthetic": True, **kw}


def rel_types(g):
    return sorted(r.type.value for r in g.relations.values())


def cats(g, red=None):
    return sorted(i.category.value for i in g.issues.values() if red is None or i.red == red)


class ContradictionSemantics(unittest.TestCase):
    def test_genuine_numeric(self):
        g = analyze([doc("a", "The Halden Bridge has a main span of 420 metres."),
                     doc("b", "The Halden Bridge has a main span of 380 metres.")])
        self.assertEqual(cats(g, red=True), ["NUMERICAL_INCONSISTENCY"])
        self.assertIn("CONTRADICTS", rel_types(g))

    def test_different_conditions_are_apparent(self):
        g = analyze([doc("a", "Policy X reduced costs by 20% under experimental conditions A."),
                     doc("b", "Policy X increased costs by 5% under experimental conditions B.")])
        self.assertEqual(cats(g, red=True), [])
        rel = next(r for r in g.relations.values() if r.type == RelationType.DIFFERS_IN_SCOPE)
        self.assertEqual(rel.dimensions, ["conditions"])

    def test_same_conditions_are_genuine(self):
        g = analyze([doc("a", "Policy X reduced costs by 20% under experimental conditions A."),
                     doc("b", "Policy X increased costs by 5% under experimental conditions A.")])
        self.assertIn("NUMERICAL_INCONSISTENCY", cats(g, red=True))

    def test_condition_on_one_side_only_is_unresolved(self):
        g = analyze([doc("a", "Policy X reduced costs by 20% under experimental conditions A."),
                     doc("b", "Policy X increased costs by 5%.")])
        issue = next(i for i in g.issues.values() if i.category == IssueCategory.MISSING_CONDITION)
        self.assertEqual(issue.finding_class, FindingClass.UNRESOLVED_CONTRADICTION)
        self.assertTrue(any("same conditions" in a for a in issue.assumptions))

    def test_different_years_are_apparent(self):
        g = analyze([doc("a", "Unemployment in Tarvia was 7.2% in 2019."),
                     doc("b", "Unemployment in Tarvia was 4.1% in 2022.")])
        self.assertEqual(cats(g, red=True), [])
        self.assertIn("DIFFERS_IN_SCOPE", rel_types(g))

    def test_unit_conversion_equivalence(self):
        g = analyze([doc("a", "The boiling point of water at sea level is 100 °C."),
                     doc("b", "The boiling point of water at sea level is 212 °F.")])
        self.assertEqual(rel_types(g), ["DUPLICATES"])

    def test_hedge_does_not_contradict(self):
        g = analyze([doc("a", "Coffee may reduce headaches."), doc("b", "Coffee does not reduce headaches.")])
        self.assertEqual(cats(g, red=True), [])

    def test_opinions_are_not_contradictions(self):
        g = analyze([doc("a", "In my opinion, the library is beautiful."), doc("b", "I think the library is ugly.")])
        self.assertEqual(cats(g), [])
        self.assertTrue(all(a.status == Status.OUT_OF_SCOPE for a in g.assessments.values()))

    def test_internal_inconsistency(self):
        g = analyze([doc("a", "The museum opened in 1987. It is popular. The museum opened in 1991.")])
        self.assertEqual(cats(g, red=True), ["INTERNAL_INCONSISTENCY"])

    def test_both_sides_preserved(self):
        g = analyze([doc("a", "The capital of Ostria is Lenburg."), doc("b", "The capital of Ostria is Varna.")])
        self.assertEqual(len(g.propositions), 2)
        self.assertTrue(all(p.superseded_by is None for p in g.propositions.values()))


class EvidencePolicy(unittest.TestCase):
    def test_copies_do_not_corroborate(self):
        g = analyze([doc("w", "The Corva dam cost 2.1 billion dollars to build."),
                     doc("c1", "The Corva dam cost 2.1 billion dollars to build.", reproduces="w"),
                     doc("c2", "The Corva dam cost 2.1 billion dollars to build.", reproduces="w")])
        statuses = {a.status for a in g.assessments.values()}
        self.assertEqual(statuses, {Status.INSUFFICIENT_EVIDENCE})
        self.assertIn("DEPENDENT_CORROBORATION", cats(g, red=False))

    def test_reputation_is_not_an_input(self):
        """Same texts, kinds swapped (textbook vs social post): identical assessments."""
        texts = ["The Lindqvist glacier is 14 kilometres long.", "The Lindqvist glacier is 9 kilometres long.",
                 "The Lindqvist glacier is 9 kilometres long."]
        g1 = analyze([doc("x", texts[0], kind="textbook"), doc("y", texts[1], kind="social", basis="dataset"),
                      doc("z", texts[2], kind="blog", basis="dataset")])
        g2 = analyze([doc("x", texts[0], kind="social"), doc("y", texts[1], kind="textbook", basis="dataset"),
                      doc("z", texts[2], kind="paper", basis="dataset")])
        s1 = [g1.assessments[p].status for p in sorted(g1.assessments)]
        s2 = [g2.assessments[p].status for p in sorted(g2.assessments)]
        self.assertEqual(s1, s2)
        self.assertEqual(s1[0], Status.CONTRADICTED)

    def test_primary_evidence_supports_low_reputation_claim(self):
        g = analyze([doc("blog", "The Arlo dam is 120 metres tall.", kind="blog"),
                     doc("s", "The height of the Arlo dam is 120 metres.", kind="dataset", basis="dataset")])
        blog = next(p for p in g.propositions.values() if g.sources[p.source_refs[0]].key == "blog")
        self.assertEqual(g.assessments[blog.id].status, Status.SUPPORTED)

    def test_retracted(self):
        g = analyze([doc("t", "Drug Z reduces relapse rates by 40% in adults.", retracted=True),
                     doc("r", "Drug Z reduces relapse rates in adults.", cites=["t"])])
        st = {g.sources[p.source_refs[0]].key: g.assessments[p.id].status for p in g.propositions.values()}
        self.assertEqual(st["t"], Status.RETRACTED)
        self.assertIn("RETRACTED_SOURCE_DEPENDENCY", cats(g, red=True))
        self.assertTrue(all(e.strength == 0 for e in g.evidence.values() if g.sources[e.source_id].retracted))

    def test_probable_error_side_only_is_red(self):
        g = analyze([doc("tb", "The Lindqvist glacier is 14 kilometres long.", kind="textbook"),
                     doc("s1", "The Lindqvist glacier is 9 kilometres long.", basis="dataset"),
                     doc("s2", "The Lindqvist glacier is 9 kilometres long.", basis="dataset")])
        issue = next(i for i in g.issues.values() if i.category == IssueCategory.NUMERICAL_INCONSISTENCY)
        self.assertEqual(issue.finding_class, FindingClass.PROBABLE_ERROR)
        tb = next(p.id for p in g.propositions.values() if g.sources[p.source_refs[0]].key == "tb")
        others = [p.id for p in g.propositions.values() if p.id != tb]
        self.assertTrue(issue.red_for(tb))
        self.assertFalse(any(issue.red_for(o) for o in others))
        self.assertEqual(len([i for i in g.issues.values() if i.red]), 1)


class StatusTransitions(unittest.TestCase):
    def test_table(self):
        self.assertTrue(allowed(Status.UNVERIFIED, Status.SUPPORTED))
        self.assertFalse(allowed(Status.RETRACTED, Status.SUPPORTED, "system"))
        self.assertTrue(allowed(Status.RETRACTED, Status.SUPPORTED, "human"))
        self.assertFalse(allowed(Status.OUT_OF_SCOPE, Status.SUPPORTED, "system"))

    def test_history_and_review_lock(self):
        a = Assessment(id="A-1", proposition_id="P-1")
        transition(a, Status.HUMAN_REVIEW_REQUIRED, "trigger")
        a.review_triggers = ["model judgment"]
        with self.assertRaises(TransitionError):
            transition(a, Status.SUPPORTED, "auto")
        a.review_triggers = []
        transition(a, Status.SUPPORTED, "trigger cleared")
        self.assertEqual([h["to_status"] for h in a.history], ["HUMAN_REVIEW_REQUIRED", "SUPPORTED"])

    def test_previous_retracted_status_blocks_automatic_change(self):
        prev = analyze([doc("a", "Drug Z reduces relapse rates in adults.", retracted=True)])
        from upae.pipeline import snapshot
        g = analyze([doc("a", "Drug Z reduces relapse rates in adults.")], previous=snapshot(prev))
        a = next(iter(g.assessments.values()))
        self.assertEqual(a.status, Status.RETRACTED)
        self.assertTrue(a.review_required)


class Checks(unittest.TestCase):
    def test_arithmetic(self):
        self.assertTrue(check_arithmetic("Sales rose from 40 to 50 in 2021, a 50% increase."))
        self.assertFalse(check_arithmetic("Sales rose from 40 to 50 in 2021, a 25% increase."))
        self.assertTrue(check_arithmetic("In the survey, 30 of 120 respondents, or 40%, agreed."))
        self.assertTrue(check_arithmetic("They got 40 million, 30 million and 10 million euros, a total of 90 million euros."))
        self.assertFalse(check_arithmetic("They got 40 million, 30 million and 20 million euros, a total of 90 million euros."))
        self.assertTrue(check_arithmetic("Output doubled from 10 to 30 tonnes."))
        self.assertTrue(check_arithmetic("Prices fell from 50 to 60, a 20% decrease."))

    def test_safe_eval(self):
        self.assertEqual(safe_eval("2 + 2"), 4)
        self.assertEqual(safe_eval("12 × 12"), 144)
        self.assertIsNone(safe_eval("__import__('os')"))

    def test_quote_comparison(self):
        orig = ["The tablet may reduce migraine frequency in adults, but only under supervised dosing."]
        self.assertTrue(compare_quote("the tablet may reduce migraine frequency", orig)["truncated"])
        self.assertTrue(compare_quote("the tablet reduces migraine frequency in adults", orig)["changes"])
        self.assertIsNone(compare_quote("completely unrelated words here", orig))

    def test_translation_cues(self):
        self.assertTrue(meaning_changes("de", "Das Programm kann die Kosten nicht senken.", "en", "The programme can reduce costs."))
        self.assertTrue(meaning_changes("fr", "Cette mesure peut réduire les émissions.", "en", "This measure must reduce emissions."))
        self.assertFalse(meaning_changes("fr", "Cette mesure peut réduire les émissions.", "en", "This measure may reduce emissions."))
        self.assertFalse(meaning_changes("de", "Die Quote lag bei 6,1 Prozent.", "en", "The rate was 6.1 percent."))

    def test_correlation_to_causation(self):
        g = analyze([doc("a", "Oat milk consumption is associated with higher exam scores among students. "
                              "Therefore, oat milk improves exam scores.")])
        self.assertEqual(cats(g, red=True), ["INVALID_INFERENCE", "UNSUPPORTED_CAUSAL_CLAIM"])
        self.assertEqual(next(iter(g.derivations.values())).validity, "invalid")


if __name__ == "__main__":
    unittest.main()
