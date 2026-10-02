import unittest

from tuppi_ai.match_statistics import pair_result, summarize_pairs


def leg(result, censored=False):
    return {"result": result, "censored": censored, "deals": 20}


class MatchStatisticsTests(unittest.TestCase):
    def test_completed_complementary_pairs(self):
        rows = [pair_result(leg(1), leg(0)), pair_result(leg(1), leg(1))]
        summary = summarize_pairs(rows)
        self.assertEqual(summary["p_win"], 0.75)
        self.assertEqual(summary["p_win_bounds"], [0.75, 0.75])
        self.assertEqual(summary["complete_pairs"], 2)

    def test_censoring_is_not_a_draw(self):
        rows = [pair_result(leg(None, True), leg(1))]
        summary = summarize_pairs(rows)
        self.assertIsNone(summary["p_win"])
        self.assertIsNone(summary["ci95"])
        self.assertEqual(summary["p_win_bounds"], [0.5, 1])
        self.assertEqual(summary["pair_ties"], 0)

    def test_two_unknown_matches_have_full_bounds(self):
        summary = summarize_pairs([pair_result(leg(None, True), leg(None, True))])
        self.assertEqual(summary["p_win_bounds"], [0, 1])

    def test_empty_comparisons_and_completed_draws_fail(self):
        with self.assertRaises(ValueError):
            summarize_pairs([])
        with self.assertRaises(ValueError):
            pair_result(leg(0.5), leg(1))


if __name__ == "__main__":
    unittest.main()
