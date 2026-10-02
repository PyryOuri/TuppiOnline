"""Deferred integration checks: requires Torch and the isolated native build."""

from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest

from tuppi_ai.search import Searcher


def searcher(worlds=4):
    sr = object.__new__(Searcher)
    sr.worlds, sr.env, sr.mlp, sr.dd_left, sr.rng = worlds, None, None, 6, None
    return sr


def test_prior_is_used_during_pruning_and_stopping():
    batches = np.array([[-0.001, 0.002], [0.001, 0.002]])

    def world_values(env, mlp, obs, ids, batch, tail, rng):
        return batches[:, ids]

    with patch("tuppi_ai.search.native.search_world_values", side_effect=world_values):
        raw = searcher()
        _, best, drawn = raw.adaptive_values(None, [0, 1], 2, 1, 0)
        assert (best, drawn) == (1, 2)
        prior = searcher()
        _, best, drawn = prior.adaptive_values(None, [0, 1], 2, 1, 0, [0.003, 0], 0)
        assert (best, drawn) == (0, 4)
        assert prior.last_action_worlds == [4, 4]


def test_zero_prior_reproduces_unregularized_allocation():
    def values(env, mlp, obs, ids, batch, tail, rng):
        return np.tile([0.001, 0.003], (batch, 1))[:, ids]

    with patch("tuppi_ai.search.native.search_world_values", side_effect=values):
        a = searcher().adaptive_values(None, [0, 1], 2, 2.5, 0.005)
        b = searcher().adaptive_values(None, [0, 1], 2, 2.5, 0.005, [0, 0])
        np.testing.assert_array_equal(a[0], b[0])
        assert a[1:] == b[1:]


def test_invalid_prior_fails_before_native_work():
    with patch("tuppi_ai.search.native.search_world_values") as work:
        with pytest.raises(ValueError):
            searcher().adaptive_values(SimpleNamespace(), [0, 1], 2, 2.5, 0.005, [0])
        work.assert_not_called()
