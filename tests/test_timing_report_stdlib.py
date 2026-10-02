import unittest

from tools.vrpo_timing_report import summarize


class TimingTests(unittest.TestCase):
    def test_old_log_projection(self):
        rows = [{"iteration": i, "rollout_s": 1, "total_s": 30 if i % 3 == 0 else 10,
                 **({"vs_ref": [0, 0.1]} if i % 3 == 0 else {})} for i in range(1, 7)]
        result = summarize(rows, 3, 12, warmup=0)
        self.assertAlmostEqual(result["evaluation_overhead_h"], 40 / 3600)
        self.assertAlmostEqual(result["projected_same_iterations_h"], 70 / 3600)

    def test_direct_timings_and_no_periodic_checks(self):
        rows = [{"iteration": 1, "rollout_s": 1, "total_s": 10, "evaluation_s": 2}]
        self.assertAlmostEqual(summarize(rows, 3, 0)["projected_same_iterations_h"], 8 / 3600)

    def test_rejects_nonmonotonic_or_empty_logs(self):
        with self.assertRaises(ValueError):
            summarize([])
        rows = [{"iteration": 1, "rollout_s": 1, "total_s": 10}] * 2
        with self.assertRaises(ValueError):
            summarize(rows)


if __name__ == "__main__":
    unittest.main()
