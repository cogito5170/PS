import unittest

from upae.lang import detect_language, numbers_in
from upae.textutil import split_sentences
from upae.units import find_quantities, values_conflict


def sents(t):
    return [t[a:b] for a, b in split_sentences(t)]


class SentenceSplitting(unittest.TestCase):
    def test_labels_and_units_end_sentences(self):
        self.assertEqual(sents("Cost fell under conditions A. Coffee is good."),
                         ["Cost fell under conditions A.", "Coffee is good."])
        self.assertEqual(sents("Water boils at 100 °C. Sales rose."), ["Water boils at 100 °C.", "Sales rose."])

    def test_initials_and_abbreviations_do_not_split(self):
        self.assertEqual(len(sents("J. Smith said hi. John F. Kennedy was born in 1917. Dr. Who is here.")), 3)

    def test_quotes_are_not_split(self):
        self.assertEqual(len(sents('She said "It works. Really." Then left.')), 2)


class Quantities(unittest.TestCase):
    def q(self, text):
        return [x[2] for x in find_quantities(text)]

    def test_temperature_normalisation(self):
        c, = self.q("100 °C")
        f, = self.q("212 °F")
        self.assertAlmostEqual(c.norm_value, f.norm_value)
        self.assertFalse(values_conflict(c, f))

    def test_scale_and_currency(self):
        q, = self.q("$4.2 billion")
        self.assertEqual(q.norm_value, 4.2e9)
        self.assertEqual(q.dimension, "currency:USD")

    def test_year_is_not_a_magnitude(self):
        q, = self.q("in 2021")
        self.assertEqual(q.kind, "year")

    def test_approximate_tolerance(self):
        a, = self.q("about 20%")
        b, = self.q("21%")
        self.assertFalse(values_conflict(a, b))
        self.assertTrue(values_conflict(self.q("20%")[0], b))

    def test_original_representation_kept(self):
        q, = self.q("12 km")
        self.assertEqual((q.unit, q.raw, q.norm_value, q.norm_unit), ("km", "12 km", 12000, "m"))


class Language(unittest.TestCase):
    def test_detection(self):
        self.assertEqual(detect_language("Die Arbeitslosenquote lag bei 6,1 Prozent und das ist nicht gut.")[0], "de")
        self.assertEqual(detect_language("The rate was low and it is not expected to rise.")[0], "en")
        self.assertEqual(detect_language("El tratamiento no reduce el dolor en los adultos.")[0], "es")
        self.assertEqual(detect_language("Безработица снизилась")[0], "ru")
        self.assertEqual(detect_language("12345")[0], "und")

    def test_number_formats(self):
        self.assertEqual(numbers_in("6,1 Prozent"), [6.1])
        self.assertEqual(numbers_in("300.000 personas"), numbers_in("300,000 people"))


if __name__ == "__main__":
    unittest.main()
