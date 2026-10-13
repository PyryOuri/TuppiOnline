"""Exercise lazy buffers through the native stepping/observation API."""
import ctypes as C
import numpy as np

from tuppi_ai import native


def test_native_state_and_observations_survive_lazy_buffer_creation():
    env = native.Env(2, seed=7, encoder=2, single_deal=True)
    assert not any(name in vars(env) for name in env._BUFFER_DTYPES)
    hands = [sum(1 << c for c in range(s * 13, (s + 1) * 13)) for s in range(4)]
    for index in range(2):
        env.set_deal(index, hands, dealer=index, score0=0, score1=0)
    features, masks, seats, phases = env.observe()
    assert features.shape == (2, native.feature_dim(2))
    assert "done" not in vars(env) and "info" not in vars(env)
    assert env.observe()[0] is features
    actions = []
    expected = []
    for index in range(2):
        deal = native.TcDeal.from_buffer_copy(bytes(env.deal(index)))
        observation = native.observe(deal, int(deal.cur))
        np.testing.assert_array_equal(features[index], native.encode(observation, encoder=2))
        assert int(seats[index]) == deal.cur and int(phases[index]) == deal.phase
        legal = native.legal(deal)
        assert list(np.flatnonzero(masks[index])) == legal
        actions.append(legal[0])
        assert native.lib.tc_apply(C.byref(deal), legal[0]) == 0
        expected.append(bytes(deal))
    env.step(np.asarray(actions, dtype=np.int32))
    assert all(bytes(env.deal(index)) == state for index, state in enumerate(expected))
    assert env.done.dtype == np.int32 and env.delta0.dtype == np.float32
    assert env.info.shape == (2, 8)


def test_compact_and_solver_interfaces_allocate_only_their_required_buffers():
    env = native.Env(3, seed=8, encoder=2)
    feat, mask, indices = env.observe_live()
    assert len(indices) == 3 and feat.shape[1] == native.feature_dim(2)
    assert not any(name in vars(env) for name in ("seat", "phase", "info", "done", "delta0"))
    actions = np.asarray([np.flatnonzero(row)[0] for row in mask], dtype=np.int32)
    env.step_live(indices, actions)
    env.dd_finish(0)
    assert "done" in vars(env) and "delta0" in vars(env)
    assert "info" not in vars(env)
