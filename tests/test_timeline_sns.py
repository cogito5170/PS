"""SNS-style text and cross-post timeline consistency."""
import unittest
from datetime import date

from upae.extract_ko import extract_passage_text_ko
from upae.lang import detect_language
from upae.pipeline import analyze
from upae.sns import normalize_sns
from upae.timeline import duration_days, resolve, statements_for

AUTHOR = "@example_traveler"


def post(key, published, text, lang="ko", **kw):
    return {"key": key, "kind": "social", "author": AUTHOR, "published": published, "text": text,
            "language": lang, "synthetic": True, **kw}


class Normalisation(unittest.TestCase):
    def test_emoji_hashtags_bullets_and_gaejosik(self):
        self.assertEqual(normalize_sns("✅ 출시 완료함"), "출시 완료한다.")
        self.assertEqual(normalize_sns("#치앙마이 한달살기 시작했음 ㅋㅋㅋ"), "치앙마이 한달살기 시작했다.")
        self.assertEqual(normalize_sns("- 매출 20% 증가!!!"), "매출 20% 증가!")
        self.assertEqual(normalize_sns("No Guts, Just Data. 📦₿"), "No Guts, Just Data.")

    def test_unit_symbols_survive(self):
        self.assertEqual(normalize_sns("The boiling point is 212 °F."), "The boiling point is 212 °F.")
        self.assertIn("㎍/㎥", normalize_sns("18㎍/㎥ 측정됨"))

    def test_lines_are_sentences_and_nominal_endings(self):
        ds = extract_passage_text_ko("치앙마이에 온 지 이틀\n아직 결론은 없음\n대신 기록합니다")
        self.assertEqual(len({d.sentence_index for d in ds}), 3)
        self.assertEqual(ds[0].predicate, "elapsed_since")
        d = extract_passage_text_ko("3달 후 퇴사 → 디지털 노마드 전환 중")[0]
        self.assertEqual(d.predicate, "전환")

    def test_intention_is_a_prediction(self):
        d = extract_passage_text_ko("데이터가 쌓인 뒤에 판단하려고 합니다.")[0]
        self.assertEqual(d.modality.value, "predicted")

    def test_slogan_is_not_negated(self):
        g = analyze([{"key": "x", "kind": "social", "synthetic": True, "text": "No Guts, Just Data."}])
        p = next(iter(g.propositions.values()))
        self.assertEqual((p.polarity.value, p.quantifier), ("positive", None))
        self.assertEqual(detect_language("No Guts, Just Data.")[0], "en")


class Resolution(unittest.TestCase):
    PUB = date(2026, 8, 11)

    def test_relative_expressions(self):
        self.assertEqual(resolve("내일부터", self.PUB)[0], date(2026, 8, 12))
        self.assertEqual(resolve("tomorrow", self.PUB)[0], date(2026, 8, 12))
        self.assertEqual(resolve("10월", self.PUB)[:2], (date(2026, 10, 1), date(2026, 10, 31)))
        self.assertEqual(resolve("다음 달", self.PUB)[:2], (date(2026, 9, 1), date(2026, 9, 30)))
        self.assertEqual(resolve("3 days ago", self.PUB)[0], date(2026, 8, 8))
        a, b, _ = resolve("3달 후", self.PUB)
        self.assertLessEqual(a, date(2026, 11, 9))
        self.assertGreaterEqual(b, date(2026, 11, 9))
        self.assertIsNone(resolve("한 달", self.PUB))   # a bare duration is not a time point

    def test_durations(self):
        self.assertEqual([duration_days(x) for x in ("이틀", "한 달", "3주", "two weeks", "a month", "보름")],
                         [2, 30, 21, 14, 30, 15])

    def test_statement_kinds(self):
        kinds = lambda t, d: [s["kind"] for s in statements_for(t, d, None)]  # noqa: E731
        self.assertEqual(kinds("내일부터 가족과 함께 치앙마이에서 한 달을 살아봅니다.", self.PUB), ["start"])
        self.assertEqual(kinds("치앙마이에 온 지 이틀.", date(2026, 8, 13)), ["elapsed"])
        self.assertEqual(kinds("Day 2.", date(2026, 8, 13)), ["day_count"])
        self.assertEqual(kinds("한 달 동안 태국에서 Atlas를 만드는 데 집중했습니다.", date(2026, 9, 12)), ["past_duration"])
        self.assertEqual(kinds("Tomorrow we fly to Lisbon for two weeks.", self.PUB), ["start"])
        self.assertEqual(kinds("Three days since we arrived in Lisbon.", self.PUB), ["elapsed"])


class Timelines(unittest.TestCase):
    def test_consistent_posts(self):
        g = analyze([post("p1", "2026-08-11", "내일부터 가족과 함께 치앙마이에서 한 달을 살아봅니다."),
                     post("p2", "2026-08-13", "치앙마이에 온 지 이틀\nDay 2"),
                     post("p3", "2026-09-12", "한 달 동안 태국에서 여행보다 일에 집중했습니다.")],
                    now="2026-10-12T00:00:00+00:00")
        ep = next(e for e in g.timeline if e["checked"])
        self.assertTrue(ep["consistent"])
        self.assertEqual(ep["start_window"], ["2026-08-12", "2026-08-12"])
        self.assertFalse([i for i in g.issues.values() if i.red])
        pred = next(p for p in g.predictions if p["due"] == "2026-08-12")
        self.assertTrue(pred["state"].startswith("fulfilled"))

    def test_inconsistent_posts(self):
        g = analyze([post("p1", "2026-08-11", "내일부터 치앙마이에서 한 달을 살아봅니다."),
                     post("p2", "2026-08-25", "치앙마이에 온 지 이틀.")])
        issue = next(i for i in g.issues.values() if i.category.value == "TEMPORAL_DISAGREEMENT")
        self.assertTrue(issue.red)
        self.assertGreaterEqual(issue.details["timeline"]["conflict"]["gap_days"], 10)
        self.assertIn("CONTRADICTS", {r.type.value for r in g.relations.values()})
        self.assertEqual(g.validate(), [])

    def test_english_inconsistent(self):
        g = analyze([post("e1", "2026-05-01", "Tomorrow we fly to Lisbon for two weeks.", lang="en"),
                     post("e2", "2026-05-20", "Day 3 in Lisbon.", lang="en")])
        self.assertIn("TEMPORAL_DISAGREEMENT", {i.category.value for i in g.issues.values() if i.red})

    def test_different_authors_are_not_one_episode(self):
        a = post("p1", "2026-08-11", "내일부터 치앙마이에서 한 달을 살아봅니다.")
        b = post("p2", "2026-08-25", "치앙마이에 온 지 이틀.", author="@someone_else")
        g = analyze([a, b])
        self.assertFalse([i for i in g.issues.values() if i.category.value == "TEMPORAL_DISAGREEMENT"])

    def test_prediction_past_due_and_pending(self):
        g = analyze([post("p1", "2026-09-18", "10월, 첫 번째 서비스를 시작합니다.")], now="2026-11-05T00:00:00+00:00")
        self.assertNotIn("PREDICTION_PAST_DUE", {i.category.value for i in g.issues.values()})  # no later posts
        self.assertTrue(g.predictions[0]["state"].startswith("past due"))
        g = analyze([post("p1", "2026-09-18", "10월, 첫 번째 서비스를 시작합니다."),
                     post("p2", "2026-11-03", "요즘 날씨가 춥습니다.")], now="2026-11-05T00:00:00+00:00")
        self.assertIn("PREDICTION_PAST_DUE", {i.category.value for i in g.issues.values()})
        g = analyze([post("p1", "2026-09-18", "10월, 첫 번째 서비스를 시작합니다.")], now="2026-10-12T00:00:00+00:00")
        self.assertEqual(g.predictions[0]["state"], "pending")
        self.assertEqual(g.predictions[0]["due"], "2026-10-31")

    def test_activity_episode_without_place(self):
        g = analyze([post("a", "2026-08-03", "어제 수술받고 입원함\n#입원일기"),
                     post("b", "2026-08-05", "입원 열흘째\n#입원일기"),
                     post("c", "2026-08-07", "내일 퇴원 예정\n입원 엿새 만에 집에 감\n#입원일기")])
        issue = next(i for i in g.issues.values() if i.category.value == "TEMPORAL_DISAGREEMENT")
        self.assertIn("열흘째", issue.reason)

    def test_english_activity_start_and_finish(self):
        g = analyze([post("a", "2026-07-10", "Starting the ridge trail hike tomorrow\n#ridgetrail", lang="en"),
                     post("b", "2026-07-12", "Day 2 on the ridge trail\n#ridgetrail", lang="en"),
                     post("c", "2026-07-25", "Finished the ridge trail today after two weeks of walking\n#ridgetrail", lang="en")])
        ep = next(e for e in g.timeline if e["checked"])
        self.assertTrue(ep["consistent"], ep)
        self.assertFalse([i for i in g.issues.values() if i.red])

    def test_cross_line_share(self):
        g = analyze([post("a", "2026-09-30", "이번 달 결산\n목표 200km 중 150km 달성\n달성률 85%임")])
        self.assertIn("ARITHMETIC_ERROR", {i.category.value for i in g.issues.values() if i.red})
        g = analyze([post("a", "2026-09-30", "이번 달 결산\n목표 200km 중 150km 달성\n달성률 75%임")])
        self.assertNotIn("ARITHMETIC_ERROR", {i.category.value for i in g.issues.values()})

    def test_transition_timestamps_use_analysis_time(self):
        g = analyze([post("a", "2026-09-30", "제 생각에 새 도서관은 최고의 건물이다.")], now="2026-01-02T03:04:05+00:00")
        a = next(iter(g.assessments.values()))
        self.assertEqual(a.status.value, "OUT_OF_SCOPE")
        self.assertEqual({h["at"] for h in a.history}, {"2026-01-02T03:04:05+00:00"})

    def test_relative_time_without_date_stays_ambiguous(self):
        g = analyze([{"key": "bio", "kind": "social", "author": AUTHOR, "language": "ko", "synthetic": True,
                      "text": "3달 후 퇴사 → 디지털 노마드 전환 중"}])
        self.assertIn("AMBIGUOUS_PROPOSITION", {i.category.value for i in g.issues.values()})


if __name__ == "__main__":
    unittest.main()
