"""Worker routing/configuration checks with dependency stubs; no native/Torch import."""

import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

from tuppi_ai import evaluate


class EvaluationConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.modules = {name: ModuleType(name) for name in
                        ("torch", "tuppi_ai.native", "tuppi_ai.equity", "tuppi_ai.incumbent")}
        self.modules["torch"].set_num_threads = Mock()
        self.native = self.modules["tuppi_ai.native"]
        self.native.set_rollout_chunk = Mock()
        self.native.set_showing_fix = Mock()
        self.native.set_dd_extra_nolo = Mock()
        self.modules["tuppi_ai.equity"].Equity = SimpleNamespace(load=Mock(return_value="equity"))
        self.incumbent = self.modules["tuppi_ai.incumbent"].incumbent_agents = Mock(return_value={0: "heuristic"})
        evaluate._W.clear()

    def tearDown(self):
        evaluate._W.clear()

    def test_search_settings_are_explicit(self):
        self.assertEqual(evaluate._search_global_settings("best"), (True, 0))
        self.assertEqual(evaluate._search_global_settings("search:model:sf=1:ddn=2"), (True, 2))
        self.assertEqual(evaluate._search_global_settings("search:model:prior=0.001"), (False, 0))
        self.assertIsNone(evaluate._search_global_settings("partner_aware_lead_v2"))

    def test_two_search_specs_route_through_the_search_factory(self):
        candidate, opponent = "search:model:sf=1:prior=0.001", "search:model:sf=1:keep=0.003"
        with patch.dict(sys.modules, self.modules), patch.object(evaluate, "_make_candidate", side_effect=lambda s: {0: s}) as factory:
            evaluate._init(candidate, opponent, "unused", "v1")
        self.assertEqual([call.args[0] for call in factory.call_args_list], [opponent, candidate])
        self.incumbent.assert_not_called()
        self.native.set_showing_fix.assert_called_once_with(True)
        self.native.set_dd_extra_nolo.assert_called_once_with(0)

    def test_conflicting_native_settings_fail_before_agent_creation(self):
        with patch.dict(sys.modules, self.modules), patch.object(evaluate, "_make_candidate") as factory:
            with self.assertRaises(ValueError):
                evaluate._init("search:model:sf=1", "search:model", "unused", "v1")
        factory.assert_not_called()

    def test_incumbent_opponent_and_default_settings_are_retained(self):
        with patch.dict(sys.modules, self.modules), patch.object(evaluate, "_make_candidate", return_value={0: "candidate"}):
            evaluate._init("search:model", "partner_aware_lead_v2", "unused", "v1")
        self.incumbent.assert_called_once_with("partner_aware_lead_v2")
        self.native.set_showing_fix.assert_called_once_with(False)
        self.native.set_dd_extra_nolo.assert_called_once_with(0)


if __name__ == "__main__":
    unittest.main()
