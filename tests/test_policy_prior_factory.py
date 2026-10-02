"""Deferred factory wiring checks; requires Torch and the isolated native build."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tuppi_ai import evaluate
from tuppi_ai.search import SearchAgent


def test_search_factory_passes_opt_in_prior_configuration():
    with patch.dict(evaluate._W, {"equity": SimpleNamespace(table="table")}), \
            patch("tuppi_ai.model.load", return_value=SimpleNamespace(encoder=2)), \
            patch("tuppi_ai.search.SearchAgent", return_value="agent") as factory:
        agents = evaluate._make_candidate("search:unused:prior=0.001:record_prior=1:adb=128:adp=1")
    assert len(agents) == 4
    for call in factory.call_args_list:
        assert call.kwargs["policy_prior"] == 0.001
        assert call.kwargs["record_prior"] is True
        assert call.kwargs["keep_adaptive"] is False
        assert call.kwargs["adaptive"]["play"] is True


@pytest.mark.parametrize("kwargs", [
    {"policy_prior": 0.001, "keep": 0.003},
    {"keep_adaptive": True},
    {"policy_prior": -0.001},
    {"policy_prior": 0.001, "equiv": True},
    {"policy_prior": 0.001, "rami_bonus": 1},
    {"policy_prior": 0.001, "search_showing": 2},
])
def test_invalid_arms_fail_before_allocating_native_searchers(kwargs):
    with patch("tuppi_ai.search.Searcher") as searcher:
        with pytest.raises(ValueError):
            SearchAgent(SimpleNamespace(encoder=2), None, 0, **kwargs)
        searcher.assert_not_called()
