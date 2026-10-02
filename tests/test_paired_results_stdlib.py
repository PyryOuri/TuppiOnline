import tempfile
import unittest
from pathlib import Path

from tuppi_ai.experiment_io import digest, read_json, write_json
from tuppi_ai.paired_results import CONTEXT_SCHEMA, RESULT_SCHEMA, compare, validate_result


def result(values=(0.001, 0.002, -0.003), candidate="candidate"):
    rows = [{"index": i, "deal_id": digest({"deal": i}), "score": [0, 0], "value": value}
            for i, value in enumerate(values)]
    return {"schema": RESULT_SCHEMA, "candidate": candidate, "opponent": "partner_aware_lead_v2",
            "seed": "paired-test", "ruleset": "project_target_v3", "scores": "uniform",
            "base_deals": len(values), "values": list(values), "deal_records": rows, "seconds": 10,
            "evaluation_context": {"schema": CONTEXT_SCHEMA, "inputs_sha256": digest({"source": "fixture"}),
                                   "candidate_inputs_sha256": digest(candidate), "inventory_sha256": digest("inventory"),
                                   "workers": 1, "design": "4_rotations_2_teams", "chunksize": 8,
                                   "controller_state": "persistent_per_worker"}}


class PairedResultTests(unittest.TestCase):
    def test_paired_mean_and_interval_use_differences(self):
        candidate, reference = result((0.03, 0.05, 0.07)), result((0.02, 0.04, 0.06), "reference")
        report = compare(candidate, reference)
        self.assertAlmostEqual(report["equity_delta"], 0.01)
        self.assertLess(report["standard_error"], 1e-16)
        self.assertEqual(report["validation_level"], "deal_ids_and_frozen_inputs")

    def test_pairing_uses_identity_not_row_order(self):
        a, b = result(), result((0, 0, 0), "reference")
        a["deal_records"].reverse()
        a["values"].reverse()
        self.assertAlmostEqual(compare(a, b)["equity_delta"], 0)

    def test_mismatched_metadata_is_rejected(self):
        for key, value in (("seed", "different"), ("ruleset", "project_target_v2"),
                           ("scores", "zero"), ("opponent", "another_profile")):
            b = result()
            b[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                compare(result(), b)

    def test_unequal_sets_and_counts_are_not_truncated(self):
        with self.assertRaises(ValueError):
            compare(result(), result((0, 0)))
        b = result()
        b["deal_records"][0]["deal_id"] = digest({"different": True})
        with self.assertRaises(ValueError):
            compare(result(), b)

    def test_duplicate_ids_records_and_invalid_values_fail(self):
        variants = []
        b = result()
        b["deal_records"][1]["deal_id"] = b["deal_records"][0]["deal_id"]
        variants.append(b)
        b = result()
        b["values"][0] = 0.9
        variants.append(b)
        for value in (float("nan"), float("inf"), True):
            b = result()
            b["values"][0] = value
            variants.append(b)
        for b in variants:
            with self.subTest(b=b), self.assertRaises(ValueError):
                compare(result(), b)

    def test_frozen_inputs_and_worker_counts_must_match(self):
        for key, value in (("inputs_sha256", digest("different")), ("workers", 2)):
            b = result()
            b["evaluation_context"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                compare(result(), b)

    def test_legacy_is_explicit_and_labeled(self):
        a, b = result(), result((0, 0, 0), "reference")
        for row in (a, b):
            for key in ("schema", "deal_records", "evaluation_context"):
                del row[key]
        with self.assertRaises(ValueError):
            compare(a, b)
        report = compare(a, b, allow_legacy=True)
        self.assertEqual(report["validation_level"], "legacy_metadata_only")
        self.assertEqual(len(report["warnings"]), 2)

    def test_different_candidate_assets_and_queue_inventories_are_attested_not_rejected(self):
        a, b = result(), result(candidate="reference")
        b["evaluation_context"]["inventory_sha256"] = digest("another queue")
        report = compare(a, b)
        self.assertNotEqual(report["candidate_context"]["candidate_inputs_sha256"],
                            report["reference_context"]["candidate_inputs_sha256"])
        self.assertNotEqual(report["candidate_context"]["inventory_sha256"],
                            report["reference_context"]["inventory_sha256"])

    def test_candidate_provenance_must_be_present_and_valid(self):
        for key in ("candidate_inputs_sha256", "inventory_sha256"):
            b = result()
            b["evaluation_context"][key] = "unknown"
            with self.subTest(key=key), self.assertRaises(ValueError):
                compare(result(), b, allow_legacy=True)

    def test_legacy_opt_in_does_not_override_known_mismatches(self):
        b = result()
        b["seed"] = "wrong"
        with self.assertRaises(ValueError):
            compare(result(), b, allow_legacy=True)

    def test_ruleset_is_not_inferred_from_a_seed_named_v3(self):
        b = result()
        b["seed"] = "tuppi-ai-eval-v3"
        del b["ruleset"]
        with self.assertRaises(ValueError):
            validate_result(b, allow_legacy=True)

    def test_incomplete_new_schema_never_falls_back_to_legacy(self):
        b = result()
        del b["deal_records"]
        with self.assertRaises(ValueError):
            validate_result(b, allow_legacy=True)

    def test_input_json_rejects_duplicate_keys_and_nonfinite_values(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "input.json"
            for data in ('{"seed":"a","seed":"b"}', '{"value":NaN}', '{"value":Infinity}'):
                path.write_text(data)
                with self.subTest(data=data), self.assertRaises(ValueError):
                    read_json(path)

    def test_exclusive_report_publication_preserves_existing_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "report.json"
            write_json(path, {"original": True}, replace=False)
            with self.assertRaises(FileExistsError):
                write_json(path, {"replacement": True}, replace=False)
            self.assertEqual(read_json(path), {"original": True})


if __name__ == "__main__":
    unittest.main()
