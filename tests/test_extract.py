import unittest

from upae.extract import extract_passage_text
from upae.models import ClaimType, Modality, Polarity


def one(text):
    ds = extract_passage_text(text)
    assert len(ds) == 1, [(d.subject, d.predicate, d.object) for d in ds]
    return ds[0]


class Extraction(unittest.TestCase):
    def test_causal_with_quantity_and_condition(self):
        d = one("Policy X reduces cost by 20% under experimental conditions A.")
        self.assertEqual((d.subject, d.predicate, d.object, d.direction), ("policy x", "decreases", "cost", -1))
        self.assertEqual(d.quantity.kind, "change")
        self.assertEqual(d.quantity.norm_value, 20)
        self.assertEqual(d.scope.conditions, ["experimental conditions A"])
        self.assertEqual(d.claim_type, ClaimType.CAUSAL)

    def test_negation_and_hedge(self):
        self.assertEqual(one("The vaccine does not cause autism.").polarity, Polarity.NEGATIVE)
        self.assertEqual(one("Coffee may reduce headaches.").modality, Modality.POSSIBLE)
        self.assertEqual(one("Exercise has no effect on memory.").polarity, Polarity.NEGATIVE)

    def test_prediction(self):
        d = one("The new law will increase tax revenue by 3% by 2030.")
        self.assertEqual(d.modality, Modality.PREDICTED)

    def test_correlation_is_not_causation(self):
        d = one("Coffee consumption is associated with lower mortality among adults.")
        self.assertEqual((d.predicate, d.claim_type), ("correlates_with", ClaimType.CORRELATIONAL))
        self.assertEqual(d.scope.population, "adults")

    def test_definition_and_event(self):
        self.assertEqual(one("Unemployment rate is defined as the share of the labour force without work.").claim_type,
                         ClaimType.DEFINITION)
        d = one("Albert Einstein was born in 1879 in Ulm.")
        self.assertEqual((d.predicate, d.object, d.scope.time, d.scope.location), ("born_in", "1879", None, "Ulm"))

    def test_statistic_with_time_and_location(self):
        d = one("Unemployment in Tarvia was 7.2% in 2019.")
        self.assertEqual((d.predicate, d.scope.time_norm, d.scope.location), ("has_value", [2019, 2019], "Tarvia"))

    def test_opinion_and_normative(self):
        self.assertEqual(one("In my opinion, the new stadium is the best in Europe.").claim_type, ClaimType.OPINION)
        self.assertEqual(one("The city should ban cars from the centre.").claim_type, ClaimType.NORMATIVE)

    def test_attribution_and_quotation(self):
        d = one("According to the ministry, unemployment fell to 5.1% in 2022.")
        self.assertEqual((d.attribution.kind, d.attribution.speaker, d.modality), ("reported", "the ministry", Modality.REPORTED))
        d = one('Dr. Smith said "the drug may reduce symptoms in mice".')
        self.assertEqual((d.attribution.kind, d.attribution.quote), ("quoted", "the drug may reduce symptoms in mice"))

    def test_compound_split_shares_subject_and_scope(self):
        ds = extract_passage_text("Exercise improves memory and reduces anxiety in older adults.")
        self.assertEqual([(d.predicate, d.object) for d in ds], [("increases", "memory"), ("decreases", "anxiety")])
        self.assertTrue(all(d.scope.population == "older adults" for d in ds))

    def test_because_split(self):
        ds = extract_passage_text("Prices rose because demand increased.")
        self.assertEqual(len(ds), 2)
        self.assertEqual(ds[0].caused_by, 1)

    def test_inference_marker(self):
        ds = extract_passage_text("Coffee drinkers live longer. Therefore, coffee extends life.")
        self.assertEqual(ds[-1].inference_marker, "therefore")

    def test_quote_is_verbatim_sentence(self):
        text = "First sentence here. The plant employs 900 workers."
        d = extract_passage_text(text)[-1]
        self.assertEqual(text[d.quote_span[0]:d.quote_span[1]], d.quote)

    def test_population_not_confused_with_verb_phrase(self):
        d = one("The Lumora plant in Norvik employs 900 workers.")
        self.assertIsNone(d.scope.population)
        self.assertEqual(d.scope.location, "Norvik")

    def test_unparseable_sentence_is_kept_with_low_confidence(self):
        d = one("Notwithstanding prior arrangements, heretofore unmentioned considerations apply.")
        self.assertLess(d.confidence, 0.5)


if __name__ == "__main__":
    unittest.main()
