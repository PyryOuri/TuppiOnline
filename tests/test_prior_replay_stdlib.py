import copy
import unittest

from tools.prior_replay import SCHEMA, summarize


def bank():
    return [{"kind": "manifest", "schema": SCHEMA, "ruleset": "project_target_v3", "worlds": 1024},
            {"kind": "decision", "deal": 0, "step": 1, "phase": "TRICK_PLAY",
             "action_ids": [2, 8], "values": [0, 0.002], "actor_logits": [5, 0],
             "world_counts": [1024, 1024], "baseline_action": 2},
            {"kind": "completion", "decisions": 1}]


class ReplayTests(unittest.TestCase):
    def test_changes_are_diagnostics_not_strength_evidence(self):
        result = summarize(bank(), [0, 0.001])
        self.assertEqual(result["arms"][0]["changed_decisions"], 1)
        self.assertEqual(result["arms"][1]["changed_decisions"], 0)
        self.assertFalse(result["strength_evidence"])

    def test_partial_pricing_is_not_treated_as_full_world_evidence(self):
        records = bank()
        records[1]["world_counts"] = [128, 1024]
        result = summarize(records, [0.001])
        self.assertEqual(result["eligible_decisions"], 0)
        self.assertEqual(result["skipped_partial_pricing"], 1)
        self.assertIsNone(result["arms"][0]["mean_model_Q_change"])

    def test_invalid_action_alignment_fails(self):
        records = bank()
        records[1]["baseline_action"] = 9
        with self.assertRaises(ValueError):
            summarize(records, [0.001])

    def test_duplicate_and_unfinished_banks_fail(self):
        records = bank()
        records.insert(2, copy.deepcopy(records[1]))
        with self.assertRaises(ValueError):
            summarize(records, [0.001])
        with self.assertRaises(ValueError):
            summarize(bank()[:-1], [0.001])


if __name__ == "__main__":
    unittest.main()
