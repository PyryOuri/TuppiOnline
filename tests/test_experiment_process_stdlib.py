"""Process-control tests run tiny Python snippets only; no Torch/native/game work."""

import os
import signal
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from tuppi_ai import experiment_queue as queue
from tuppi_ai.experiment_io import read_json

ROOT = Path(__file__).resolve().parents[1]


class ProcessTests(unittest.TestCase):
    def test_acknowledged_worker_executes_only_after_pid_callback(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            marker, log = directory / "marker", directory / "process.log"
            argv = [sys.executable, "-c", "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text('ok')", str(marker)]
            recorded = []

            def started(pid):
                self.assertFalse((directory / "go.json").exists())
                recorded.append(pid)

            env = os.environ.copy()
            env["PYTHONPATH"] = str(ROOT)
            with patch("tuppi_ai.experiment_io.os.fsync"):
                outcome = queue._launch(argv, str(ROOT), env, log, 15, started)
            self.assertEqual(outcome["status"], "completed")
            self.assertEqual(marker.read_text(), "ok")
            self.assertEqual(read_json(directory / "child.json")["pid"], recorded[0])

    def test_failed_pid_recording_never_releases_the_workload(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            marker = directory / "marker"
            argv = [sys.executable, "-c", "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text('bad')", str(marker)]
            env = os.environ.copy()
            env["PYTHONPATH"] = str(ROOT)
            with patch("tuppi_ai.experiment_io.os.fsync"), self.assertRaises(ValueError):
                queue._launch(argv, str(ROOT), env, directory / "process.log", 15,
                              lambda pid: (_ for _ in ()).throw(ValueError("state save failed")))
            self.assertFalse(marker.exists())
            self.assertFalse((directory / "go.json").exists())

    def test_cleanup_escalates_if_descendants_survive_the_parent(self):
        process = Mock(pid=123456789)
        with patch.object(queue, "_group_alive", side_effect=[True, False]), patch.object(queue.os, "killpg") as kill:
            queue._stop(process)
        self.assertEqual([call.args for call in kill.call_args_list],
                         [(123456789, signal.SIGTERM), (123456789, signal.SIGKILL)])

    def test_normal_or_failed_parent_exit_also_cleans_up_descendants(self):
        for code in (0, 1):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as temporary:
                process = Mock(pid=123456789)
                process.wait.return_value = code
                with patch("tuppi_ai.experiment_io.os.fsync"), \
                        patch.object(queue.subprocess, "Popen", return_value=process), \
                        patch.object(queue, "_group_alive", return_value=True), \
                        patch.object(queue, "_stop") as stop:
                    outcome = queue._launch([sys.executable, "-c", "pass"], str(ROOT), {},
                                            Path(temporary) / "process.log", 1, lambda pid: None)
                stop.assert_called_once_with(process)
                self.assertEqual(outcome["status"], "completed" if code == 0 else "failed")


if __name__ == "__main__":
    unittest.main()
