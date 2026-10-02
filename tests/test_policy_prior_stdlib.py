"""Tiny arithmetic checks; safe to run without Torch, NumPy, or the native library."""

import math
import unittest

from tuppi_ai.policy_prior import action_scores, hard_offsets, select_action, soft_offsets


class PriorScoringTests(unittest.TestCase):
    def test_matches_log_probability_rule(self):
        logits, q, tau = [1.2, -0.5, 0.1], [0.01, 0.013, 0.012], 0.002
        log_z = math.log(sum(math.exp(v) for v in logits))
        expected = max(range(3), key=lambda i: q[i] + tau * (logits[i] - log_z))
        self.assertEqual(select_action(q, soft_offsets(logits, tau)), expected)

    def test_logits_shift_and_extreme_values(self):
        self.assertEqual(soft_offsets([1001, 1000], 0.01), soft_offsets([1, 0], 0.01))
        self.assertEqual(soft_offsets([1e308, -1e308], 0), [0, 0])

    def test_search_can_overturn_weak_but_not_strong_preference(self):
        q = [0, 0.002]
        self.assertEqual(select_action(q, soft_offsets([0.1, 0], 0.001)), 1)
        self.assertEqual(select_action(q, soft_offsets([5, 0], 0.001)), 0)

    def test_zero_strength_is_plain_search_including_ties(self):
        self.assertEqual(select_action([0.2, 0.2], soft_offsets([0, 9], 0)), 0)

    def test_anchor_wins_boundary_tie(self):
        offsets, preferred = hard_offsets([0, 1], 0.003)
        self.assertEqual(select_action([0.003, 0], offsets, preferred), 1)
        self.assertEqual(select_action([0.003001, 0], offsets, preferred), 0)

    def test_actor_first_maximum_is_preserved(self):
        offsets, preferred = hard_offsets([1, 1, 0], 0)
        self.assertEqual(preferred, 0)
        self.assertEqual(select_action([0, 0, 0], offsets, preferred), 0)

    def test_single_action(self):
        self.assertEqual(select_action([0.1], soft_offsets([-500], 2)), 0)

    def test_rejects_invalid_scores_and_shapes(self):
        for values, offsets in (([], None), ([float("nan")], None), ([0], [0, 1]), ([0], [float("inf")])):
            with self.subTest(values=values, offsets=offsets), self.assertRaises(ValueError):
                action_scores(values, offsets)
        with self.assertRaises(ValueError):
            select_action([0], preferred=1)

    def test_rejects_invalid_prior_strength(self):
        for strength in (-1, float("nan"), float("inf")):
            with self.subTest(strength=strength), self.assertRaises(ValueError):
                soft_offsets([0, 1], strength)
            with self.subTest(margin=strength), self.assertRaises(ValueError):
                hard_offsets([0, 1], strength)


if __name__ == "__main__":
    unittest.main()
