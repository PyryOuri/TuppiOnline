"""Queue tests use tiny fixture files and a fake launcher; no model/game workloads."""

import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tuppi_ai import experiment_queue as queue
from tuppi_ai.experiment_io import read_json, write_json
from tuppi_ai.paired_results import compare
from test_paired_results_stdlib import result


class QueueTests(unittest.TestCase):
    def setUp(self):
        # Queue state semantics do not require disk-barrier timing. Atomic
        # publication itself is exercised separately in the IO tests.
        sync = patch("tuppi_ai.experiment_io.os.fsync")
        sync.start()
        self.addCleanup(sync.stop)
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name).resolve()
        self.checkout, self.engine = self.base / "ai", self.base / "engine"
        for path in (self.checkout / "tuppi_ai", self.checkout / "native", self.checkout / "models",
                     self.engine / "src" / "tuppi_engine", self.engine / "configs" / "rules"):
            path.mkdir(parents=True)
        (self.checkout / "tuppi_ai" / "source.py").write_text("# fixture source\n")
        (self.checkout / "native" / "libtuppi.dylib").write_bytes(b"fixture, not a native library")
        (self.checkout / "native" / "core.c").write_text("/* fixture */\n")
        (self.checkout / "models" / "equity.json").write_text("{}\n")
        self.plan = {"schema": queue.PLAN_SCHEMA, "checkout": str(self.checkout), "engine": str(self.engine),
                     "python": sys.executable, "equity": "models/equity.json", "budget_wall_seconds": 20,
                     "max_workers": 1, "jobs": [
                         {"id": identity, "kind": "deal_eval", "candidate": f"profile:{identity}",
                          "opponent": "partner_aware_lead_v2", "seed": "paired-test", "ruleset": "v3",
                          "scores": "uniform", "samples": 3, "workers": 1, "wall_seconds": 10}
                         for identity in ("baseline", "variant")] + [
                         {"id": "comparison", "kind": "paired_analysis", "candidate_result": "variant",
                          "reference_result": "baseline", "wall_seconds": 2}]}
        self.plan_path, self.directory = self.base / "plan.json", self.checkout / "runs" / "queue"
        self.now, self.calls = 0.0, []

    def tearDown(self):
        self.temporary.cleanup()

    def prepare(self):
        write_json(self.plan_path, self.plan)
        queue.prepare(self.plan_path, self.directory)

    def launcher(self, argv, cwd, env, log, timeout, started):
        self.calls.append(argv)
        started(123456789)
        self.assertEqual(env["PYTHONPATH"], f"{self.engine / 'src'}:{self.checkout}")
        output = Path(argv[argv.index("--out") + 1])
        if timeout < 1:
            self.now += timeout
            return {"status": "timed_out", "returncode": -15}
        if argv[2] == "tuppi_ai.evaluate":
            candidate = argv[argv.index("--checkpoint") + 1]
            r = result(candidate=candidate)
            del r["evaluation_context"]
        else:
            r = compare(read_json(Path(argv[3])), read_json(Path(argv[4])))
        write_json(output, r)
        self.now += 1
        return {"status": "completed", "returncode": 0}

    def run_queue(self, **kwargs):
        return queue.run(self.directory, execute=True, launch=self.launcher, clock=lambda: self.now, **kwargs)

    def test_dry_run_never_launches_a_workload(self):
        self.prepare()
        with patch.object(queue, "_launch", side_effect=AssertionError("must not launch")):
            summary = queue.run(self.directory)
        self.assertEqual(summary["jobs"]["baseline"]["status"], "pending")
        self.assertFalse((self.directory / "attempts").exists())

    def test_queue_completes_and_resume_skips_completed_jobs(self):
        self.prepare()
        summary = self.run_queue()
        self.assertTrue(all(row["status"] == "completed" for row in summary["jobs"].values()))
        self.assertEqual(summary["wall_charged_seconds"], 3)
        self.run_queue()
        self.assertEqual(len(self.calls), 3)

    def test_failed_attempt_requires_explicit_retry(self):
        self.prepare()

        def failure(*args):
            self.now += 1
            return {"status": "failed", "returncode": 1}

        queue.run(self.directory, execute=True, launch=failure, clock=lambda: self.now)
        self.run_queue()
        self.assertEqual(len(self.calls), 1)  # independent variant runs; failed baseline is not retried
        self.run_queue(retry_failed=True)
        state = read_json(self.directory / "state.json")
        self.assertEqual(state["jobs"]["baseline"]["status"], "completed")
        self.assertEqual(len(state["jobs"]["baseline"]["attempts"]), 2)

    def test_budget_limits_child_timeout_and_counts_failed_work(self):
        self.plan["budget_wall_seconds"] = 1.5
        self.prepare()
        summary = self.run_queue()
        self.assertEqual(summary["wall_charged_seconds"], 1.5)
        self.assertEqual(summary["jobs"]["variant"]["status"], "timed_out")
        self.assertEqual(summary["jobs"]["comparison"]["status"], "pending")
        self.assertEqual(len(self.calls), 2)

    def test_changed_source_and_completed_results_are_not_reused(self):
        self.prepare()
        source = self.checkout / "tuppi_ai" / "source.py"
        original = source.read_text()
        source.write_text("changed\n")
        with self.assertRaises(ValueError):
            self.run_queue()
        source.write_text(original)
        self.run_queue()
        state = read_json(self.directory / "state.json")
        (self.directory / state["jobs"]["baseline"]["result"]).write_text("{}")
        with self.assertRaises(ValueError):
            self.run_queue()

    def test_configuration_changes_require_a_new_queue(self):
        self.prepare()
        frozen = read_json(self.directory / "frozen.json")
        frozen["plan"]["jobs"][0]["seed"] = "changed"
        write_json(self.directory / "frozen.json", frozen)
        with self.assertRaises(ValueError):
            queue.inspect(self.directory)

    def test_separate_candidate_queues_share_context_without_sharing_inventory(self):
        checkpoints = [self.checkout / "models" / f"actor-{i}.pt" for i in range(2)]
        for i, path in enumerate(checkpoints):
            path.write_bytes(f"fixture checkpoint {i}".encode())
        contexts = []
        for i, checkpoint in enumerate(checkpoints):
            self.plan["jobs"] = [dict(self.plan["jobs"][0], candidate=str(checkpoint))]
            write_json(self.plan_path, self.plan)
            frozen = queue.prepare(self.plan_path, self.checkout / "runs" / f"queue-{i}")
            contexts.append(queue._evaluation_context(frozen["plan"]["jobs"][0], frozen))
        self.assertEqual(contexts[0]["inputs_sha256"], contexts[1]["inputs_sha256"])
        self.assertNotEqual(contexts[0]["candidate_inputs_sha256"], contexts[1]["candidate_inputs_sha256"])
        self.assertNotEqual(contexts[0]["inventory_sha256"], contexts[1]["inventory_sha256"])
        a, b = result(), result(candidate="reference")
        a["evaluation_context"], b["evaluation_context"] = contexts
        self.assertEqual(compare(a, b)["validation_level"], "deal_ids_and_frozen_inputs")

    def test_opponent_equity_and_explicit_extra_inputs_are_shared_context(self):
        opponent = self.checkout / "models" / "opponent.pt"
        extra = self.checkout / "models" / "common.json"
        opponent.write_bytes(b"opponent fixture")
        extra.write_text("{}")
        self.plan["jobs"] = [dict(self.plan["jobs"][0], opponent=f"search:{opponent}:w=128")]
        self.plan["extra_inputs"] = [str(extra)]
        contexts = []
        for i, changed in enumerate((None, opponent, self.checkout / "models" / "equity.json", extra)):
            if changed:
                changed.write_bytes(changed.read_bytes() + b" ")
            write_json(self.plan_path, self.plan)
            frozen = queue.prepare(self.plan_path, self.checkout / "runs" / f"queue-{i}")
            self.assertEqual(frozen["plan"]["extra_inputs"], [str(extra)])
            contexts.append(queue._evaluation_context(frozen["plan"]["jobs"][0], frozen))
        self.assertEqual(len({c["inputs_sha256"] for c in contexts}), 4)

    def test_incompatible_paired_jobs_fail_before_freezing(self):
        for key, value in (("seed", "different"), ("ruleset", "v2"), ("scores", "zero"), ("samples", 4)):
            plan = copy.deepcopy(self.plan)
            plan["jobs"][1][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                queue.normalize(plan, self.base)

    def test_cycles_duplicate_ids_worker_caps_and_unknown_fields_fail(self):
        variants = []
        plan = copy.deepcopy(self.plan)
        plan["jobs"][0]["depends_on"] = ["comparison"]
        variants.append(plan)
        plan = copy.deepcopy(self.plan)
        plan["jobs"][1]["id"] = "baseline"
        variants.append(plan)
        plan = copy.deepcopy(self.plan)
        plan["jobs"][0]["workers"] = 2
        variants.append(plan)
        plan = copy.deepcopy(self.plan)
        plan["jobs"][0]["workerz"] = 1
        variants.append(plan)
        for plan in variants:
            with self.subTest(plan=plan), self.assertRaises(ValueError):
                queue.normalize(plan, self.base)

    def test_unexpected_worker_result_is_not_published(self):
        self.prepare()

        def wrong(argv, cwd, env, log, timeout, started):
            r = result(candidate="wrong")
            write_json(Path(argv[argv.index("--out") + 1]), r)
            return {"status": "completed", "returncode": 0}

        summary = queue.run(self.directory, execute=True, launch=wrong, clock=lambda: self.now)
        self.assertEqual(summary["jobs"]["baseline"]["status"], "failed")
        self.assertIsNone(summary["jobs"]["baseline"]["result"])

    def test_existing_queue_directory_and_missing_native_are_rejected(self):
        self.prepare()
        with self.assertRaises(ValueError):
            queue.prepare(self.plan_path, self.directory)
        (self.checkout / "native" / "libtuppi.dylib").unlink()
        with self.assertRaises(ValueError):
            queue.prepare(self.plan_path, self.checkout / "runs" / "another")

    def test_source_added_after_freezing_is_rejected(self):
        self.prepare()
        (self.checkout / "tuppi_ai" / "new.py").write_text("# added\n")
        with self.assertRaises(ValueError):
            self.run_queue()

    def test_changed_inputs_during_a_successful_worker_prevent_publication(self):
        self.prepare()

        def mutate(*args):
            outcome = self.launcher(*args)
            (self.checkout / "native" / "core.c").write_text("/* changed */\n")
            return outcome

        summary = queue.run(self.directory, execute=True, launch=mutate, clock=lambda: self.now)
        self.assertEqual(summary["jobs"]["baseline"]["status"], "failed")
        self.assertIsNone(summary["jobs"]["baseline"]["result"])

    def crash_state(self, pid):
        frozen, state = queue.load(self.directory)
        row = state["jobs"]["baseline"]
        row["status"] = "running"
        row["attempts"] = [{"status": "running", "allocated_seconds": 10, "pid": pid,
                             "directory": "attempts/baseline/1"}]
        state["wall_charged_seconds"] = 10
        (self.directory / "attempts" / "baseline" / "1").mkdir(parents=True)
        write_json(self.directory / "state.json", state)

    def test_vanished_runner_keeps_full_reserved_budget(self):
        self.prepare()
        self.crash_state(123456789)
        with patch.object(queue, "_group_alive", return_value=False):
            self.run_queue()
        state = read_json(self.directory / "state.json")
        self.assertEqual(state["wall_charged_seconds"], 11)
        self.assertEqual(state["jobs"]["baseline"]["status"], "interrupted")
        self.assertEqual(len(state["jobs"]["baseline"]["attempts"]), 1)

    def test_live_child_process_prevents_a_second_runner(self):
        self.prepare()
        self.crash_state(123456789)
        with patch.object(queue, "_group_alive", return_value=True), self.assertRaises(ValueError):
            self.run_queue(retry_failed=True)
        self.assertEqual(self.calls, [])

    def test_unacknowledged_launch_can_be_recovered_without_starting_old_work(self):
        self.prepare()
        self.crash_state(None)
        self.run_queue()
        state = read_json(self.directory / "state.json")
        self.assertEqual(state["jobs"]["baseline"]["status"], "interrupted")
        self.assertEqual(state["wall_charged_seconds"], 11)

    def test_budget_history_corruption_is_rejected(self):
        self.prepare()
        self.crash_state(None)
        state = read_json(self.directory / "state.json")
        state["wall_charged_seconds"] = 0
        write_json(self.directory / "state.json", state)
        with self.assertRaises(ValueError):
            queue.inspect(self.directory)

    def test_queue_lock_prevents_duplicate_execution(self):
        self.prepare()
        with queue._lock(self.directory), self.assertRaises(ValueError):
            self.run_queue()
        self.assertEqual(self.calls, [])

    def test_agent_spec_preflight_freezes_models_and_rejects_bad_settings(self):
        checkpoint = self.checkout / "models" / "actor.pt"
        checkpoint.write_bytes(b"fixture checkpoint")
        normalized, inputs = queue._spec("search:models/actor.pt:w=128:prior=0.001:show=1", self.checkout, self.engine)
        self.assertIn(str(checkpoint), normalized)
        self.assertIn(checkpoint, inputs)
        for suffix in ("w=0", "prior=nan", "prior=0.001:keep=0.003", "keep_adaptive=1", "sf=2",
                       "w=129:adb=128", "w=128:adb=1", "prior=0.001:show=2", "typo=1", "w=128:w=64",
                       "bt=0", "be=1.1", "dd=14", "bs=typo"):
            with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                queue._spec(f"search:models/actor.pt:{suffix}", self.checkout, self.engine)
        spec, _ = queue._spec("profile:partner_aware_lead_v2", self.checkout, self.engine, opponent=True)
        self.assertEqual(spec, "partner_aware_lead_v2")

    def test_attempt_paths_and_process_ids_are_validated(self):
        self.prepare()
        self.crash_state(123456789)
        original = read_json(self.directory / "state.json")
        for key, value in (("directory", "../../outside"), ("pid", 0)):
            state = copy.deepcopy(original)
            state["jobs"]["baseline"]["attempts"][0][key] = value
            write_json(self.directory / "state.json", state)
            with self.subTest(key=key), self.assertRaises(ValueError):
                queue.inspect(self.directory)


if __name__ == "__main__":
    unittest.main()
