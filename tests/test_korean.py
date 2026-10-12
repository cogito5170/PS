"""Korean extraction, tokenisation, units, language detection and checks."""
import unittest

from upae.checks import check_arithmetic, meaning_changes
from upae.extract_ko import IMPLICIT_SUBJECT, extract_passage_text_ko
from upae.lang import detect_language
from upae.models import ClaimType, Modality, Polarity
from upae.pipeline import analyze
from upae.textutil import content_tokens, split_sentences, strip_josa
from upae.units import find_quantities


def one(text):
    ds = extract_passage_text_ko(text)
    assert len(ds) == 1, [(d.subject, d.predicate, d.object) for d in ds]
    return ds[0]


def doc(key, text, **kw):
    return {"key": key, "kind": kw.pop("kind", "news"), "text": text, "synthetic": True, "language": "ko", **kw}


def cats(g, red=None):
    return sorted(i.category.value for i in g.issues.values() if red is None or i.red == red)


class Foundations(unittest.TestCase):
    def test_sentence_split(self):
        t = "노르빅의 실업률은 6.1퍼센트였다. 이 프로그램은 비용을 줄이지 못한다."
        self.assertEqual(len(split_sentences(t)), 2)

    def test_josa_stripping(self):
        self.assertEqual(strip_josa("실업률은"), "실업률")
        self.assertEqual(strip_josa("노르빅에서"), "노르빅")
        self.assertEqual(strip_josa("나이"), "나이")      # noun ending in 이 stays
        self.assertIn("실업률", content_tokens("노르빅의 실업률은"))

    def test_korean_units_and_scales(self):
        qs = {q.raw: q for _, _, q in find_quantities("6.1퍼센트 300만 명 2조 원 4.2킬로미터")}
        self.assertEqual(qs["300만 명"].norm_value, 3_000_000)
        self.assertEqual(qs["2조 원"].dimension, "currency:KRW")
        self.assertEqual(qs["4.2킬로미터"].norm_value, 4200)
        self.assertEqual(qs["6.1퍼센트"].norm_unit, "percent")

    def test_language_detection_short_english(self):
        self.assertEqual(detect_language("No Guts, Just Data.")[0], "en")
        self.assertEqual(detect_language("Day 2.")[0], "en")
        self.assertLessEqual(detect_language("Day 2.")[1], 0.6)
        self.assertEqual(detect_language("El tratamiento no reduce el dolor.")[0], "es")
        self.assertEqual(detect_language("No es verdad.")[0], "es")
        self.assertEqual(detect_language("물류 20년이 BTC와 거시를 읽는다")[0], "ko")


class KoreanExtraction(unittest.TestCase):
    def test_value_with_time(self):
        d = one("노르빅의 실업률은 2023년에 6.1퍼센트였다.")
        self.assertEqual((d.predicate, d.scope.time_norm, d.quantity.norm_value), ("has_value", [2023, 2023], 6.1))

    def test_negation_and_possibility(self):
        self.assertEqual(one("이 프로그램은 비용을 줄이지 못한다.").polarity, Polarity.NEGATIVE)
        d = one("커피는 두통을 줄일 수 있다.")
        self.assertEqual((d.predicate, d.modality), ("decreases", Modality.POSSIBLE))

    def test_causal_with_condition_and_quantity(self):
        d = one("정책 X는 실험 조건 A에서 비용을 20% 줄였다.")
        self.assertEqual((d.subject, d.predicate, d.object, d.scope.conditions), ("정책 x", "decreases", "비용", ["실험 조건 A"]))
        self.assertEqual(d.quantity.kind, "change")

    def test_population(self):
        self.assertEqual(one("이 약은 성인의 혈압을 낮춘다.").scope.population, "성인")
        self.assertEqual(one("이 백신은 6개월 미만 영아에게 효과가 없다.").scope.population, "6개월 미만 영아")

    def test_change_from_to(self):
        d = one("매출은 40억 원에서 50억 원으로 증가했다.")
        self.assertEqual((d.predicate, d.quantity.kind, d.quantity.from_value, d.quantity.to_value),
                         ("increased", "from_to", 4e9, 5e9))

    def test_attribution(self):
        d = one("통계청에 따르면, 실업률은 5.1퍼센트로 하락했다.")
        self.assertEqual((d.attribution.kind, d.attribution.speaker, d.predicate), ("reported", "통계청", "decreased"))
        d = one('김 박사는 "이 백신은 영아에게 효과가 없다"라고 말했다.')
        self.assertEqual((d.attribution.kind, d.attribution.speaker), ("quoted", "김 박사"))

    def test_claim_types(self):
        self.assertEqual(one("실업률이란 경제활동인구 중 실업자의 비율을 말한다.").claim_type, ClaimType.DEFINITION)
        self.assertEqual(one("제 생각에 새 도서관은 최고의 건물이다.").claim_type, ClaimType.OPINION)
        self.assertEqual(one("시는 차량 진입을 금지해야 한다.").claim_type, ClaimType.NORMATIVE)
        self.assertEqual(one("귀리우유 섭취는 높은 성적과 관련이 있다.").claim_type, ClaimType.CORRELATIONAL)

    def test_event_date_and_place(self):
        ds = extract_passage_text_ko("이 조약은 1712년 오를라비에서 체결되었다.")
        self.assertEqual(sorted(d.predicate for d in ds), ["signed_at", "signed_in"])

    def test_clause_structure(self):
        ds = extract_passage_text_ko("운동은 기억력을 높이고 불안을 줄인다.")
        self.assertEqual([(d.predicate, d.object) for d in ds], [("increases", "기억력"), ("decreases", "불안")])
        ds = extract_passage_text_ko("수요가 증가했기 때문에 가격이 올랐다.")
        self.assertEqual(ds[0].caused_by, 1)

    def test_pro_drop_and_contrast(self):
        d = one("AI 직원 8명을 만들었습니다.")
        self.assertEqual(d.subject, IMPLICIT_SUBJECT)
        d = one("결국 필요한 건 AI가 아니라 Workflow였습니다.")
        self.assertEqual((d.subject, d.object, d.inference_marker), ("필요한 것", "workflow", "결국"))


class KoreanRound2(unittest.TestCase):
    """Rules added after the blind Korean run (post-hoc, general phrasing patterns)."""

    def test_curly_quotes_do_not_split(self):
        t = "교수는 \u201c효과가 있었다. 하지만 단정할 수 없다\u201d라고 말했다. 다음 문장이다."
        self.assertEqual(len(split_sentences(t)), 2)

    def test_quote_after_adverbial(self):
        d = one('박 교수는 언론 인터뷰에서 "커피가 위험을 낮춘다"고 말했다.')
        self.assertEqual((d.attribution.kind, d.predicate), ("quoted", "decreases"))

    def test_units_and_comparatives(self):
        qs = {q.raw: q for _, _, q in find_quantities("18㎍/㎥ 25.1도 3만 그루 3위")}
        self.assertEqual(qs["18㎍/㎥"].dimension, "concentration")
        self.assertEqual(qs["25.1도"].norm_unit, "degC")
        d = one("서하시의 평균기온은 전년보다 1.8도 낮았다.")
        self.assertEqual((d.predicate, d.quantity.kind), ("decreased", "change"))

    def test_reported_judgement_and_completion_event(self):
        d = one("연구원은 성벽 축조가 1618년 무렵에 마무리된 것으로 판단했다.")
        self.assertEqual((d.attribution.kind, d.predicate), ("reported", "completed_in"))
        self.assertEqual(one("이 읍성은 1592년에 축조가 완료되었다.").predicate, "completed_in")

    def test_formal_negation_and_permission(self):
        self.assertTrue(meaning_changes("ko", "접종은 권장 사항이며 의무는 아닙니다.", "en", "Vaccination is mandatory for these groups."))
        self.assertFalse(meaning_changes("ko", "신분증을 지참하고 방문하면 됩니다.", "en", "Residents can visit a clinic with their ID."))

    def test_demonstrative_with_two_candidates_is_ambiguous(self):
        g = analyze([doc("a", "누리테크와 한결소프트가 계약을 체결했다. 그 회사는 인력을 늘릴 계획이라고 밝혔다.")])
        self.assertIn("AMBIGUOUS_PROPOSITION", cats(g))

    def test_rise_to_level_supports_recorded_value(self):
        g = analyze([doc("a", "서하강 하류 수위는 7.8m까지 올라갔다.", kind="social"),
                     doc("b", "서하강 하류 수위는 7.8m로 기록되었다.", kind="dataset", basis="dataset")])
        self.assertIn("DUPLICATES", {r.type.value for r in g.relations.values()})


class KoreanAnalysis(unittest.TestCase):
    def test_genuine_and_scope(self):
        g = analyze([doc("a", "할덴 다리의 주경간은 420미터이다."), doc("b", "할덴 다리의 주경간은 380미터이다.")])
        self.assertEqual(cats(g, red=True), ["NUMERICAL_INCONSISTENCY"])
        g = analyze([doc("a", "타르비아의 실업률은 2019년에 7.2퍼센트였다."), doc("b", "타르비아의 실업률은 2022년에 4.1퍼센트였다.")])
        self.assertEqual(cats(g, red=True), [])
        g = analyze([doc("a", "이 약은 성인의 혈압을 낮춘다."), doc("b", "이 약은 어린이의 혈압을 낮추지 않는다.")])
        self.assertEqual(cats(g, red=True), [])
        self.assertIn("DIFFERS_IN_SCOPE", {r.type.value for r in g.relations.values()})

    def test_inference_and_arithmetic(self):
        g = analyze([doc("a", "설문조사 결과 귀리우유 섭취는 학생들의 높은 성적과 관련이 있다. 따라서 귀리우유는 성적을 높인다.")])
        self.assertEqual(cats(g, red=True), ["INVALID_INFERENCE", "UNSUPPORTED_CAUSAL_CLAIM"])
        self.assertTrue(check_arithmetic("매출은 40억 원에서 50억 원으로 50% 증가했다."))
        self.assertFalse(check_arithmetic("매출은 40억 원에서 50억 원으로 25% 증가했다."))
        self.assertTrue(check_arithmetic("응답자 120명 중 30명(40%)이 선호했다."))

    def test_quotation_and_translation(self):
        g = analyze([doc("o", "이 백신은 6개월 미만 영아에게 효과가 없다.", author="오르티즈", kind="paper"),
                     doc("n", '오르티즈 박사는 "이 백신은 6개월 미만 영아에게 효과가 있다"라고 말했다.')])
        self.assertEqual(cats(g, red=True), ["MISLEADING_QUOTATION"])
        self.assertTrue(meaning_changes("ko", "이 프로그램은 비용을 줄이지 못한다.", "en", "The programme can reduce costs."))
        self.assertFalse(meaning_changes("ko", "이 조치는 배출을 줄일 수 있다.", "en", "This measure may reduce emissions."))

    def test_coreference_and_event_place(self):
        g = analyze([doc("a", "케스마르크 조약은 전쟁을 끝냈다. 이 조약은 1712년 오를라비에서 체결되었다."),
                     doc("b", "케스마르크 조약은 1712년 브레닉에서 체결되었다.")])
        self.assertEqual(cats(g, red=True), ["CATEGORICAL_CONFLICT"])

    def test_relative_time_ambiguity_and_integrity(self):
        g = analyze([doc("a", "3달 후 퇴사한다. 그것은 40% 증가했다.")])
        self.assertEqual(cats(g), ["AMBIGUOUS_PROPOSITION", "AMBIGUOUS_PROPOSITION"])
        self.assertEqual(g.validate(), [])
        self.assertTrue(all(p.language == "ko" for p in g.propositions.values()))

    def test_mixed_language_document(self):
        g = analyze([{"key": "x", "kind": "social", "synthetic": True,
                      "text": "물류 20년이 BTC와 거시를 읽는다\n\nNo Guts, Just Data."}])
        langs = sorted({g.passages[p.passage_id].language for p in g.propositions.values()})
        self.assertEqual(langs, ["en", "ko"])
        self.assertEqual(g.limitations, [])


if __name__ == "__main__":
    unittest.main()
