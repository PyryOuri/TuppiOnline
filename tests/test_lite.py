"""The hosted lite bot: exported weights, PyTorch-free play and deterministic cursors."""
import random
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]

PLAY = """
import random, sys
from tuppi_engine import ExplicitDeal, apply_match_action, begin_explicit_deal, create_match, match_observation_for
from tuppi_engine.state import ACTIVE_PHASES
from tuppi_rules import MatchScore, RulesetId
from tuppi_rules.cards import FULL_DECK
from tuppi_ai.lite import lite_agents
from tuppi_ai.bridge import action_id
agents = lite_agents(); trace = []
for i in range(int(sys.argv[1])):
    rng = random.Random(f'lite-test|{i}'); cards = list(FULL_DECK); rng.shuffle(cards)
    hands = tuple(tuple(cards[s*13:(s+1)*13]) for s in range(4))
    state = begin_explicit_deal(create_match(initial_score=MatchScore(4*(i % 13), 0), initial_dealer=i % 4,
        match_ref='lite-test', ruleset_id=RulesetId.PROJECT_TARGET_V3), ExplicitDeal(dealer=i % 4, hands=hands))
    while state.phase in ACTIVE_PHASES:
        seat = state.current_actor; action = agents[seat].choose_action(match_observation_for(state, seat))
        trace.append(action_id(action)); state = apply_match_action(state, action)
print('torch' in sys.modules, hash(tuple(trace)), [a.rng.value for a in agents.values()])
"""


def test_exported_weights_equal_the_checkpoint_bitwise():
    from tuppi_ai import model, native
    from tuppi_ai.best import ANCHOR
    from tuppi_ai.lite import load_mlp
    net = model.load(ANCHOR, "cpu")
    a, b = native.Mlp(net), load_mlp()
    feat = (np.random.default_rng(1).random((64, native.feature_dim(a.encoder))) < 0.08).astype(np.uint8)
    assert a.encoder == b.encoder and a.width == b.width
    assert np.array_equal(a.forward(feat).view(np.uint32), b.forward(feat).view(np.uint32))


def test_lite_bot_plays_without_pytorch_and_repeats_exactly():
    run = lambda: subprocess.run([sys.executable, "-c", PLAY, "6"], capture_output=True, text=True, check=True,
                                 cwd=ROOT).stdout.split(maxsplit=2)
    first, second = run(), run()
    assert first[0] == "False"  # torch never imported
    assert first == second


def test_sooli_cursor_is_the_only_state_and_restores():
    from tuppi_ai import native
    from tuppi_ai.lite import LiteAgent, initial_cursor
    agent = LiteAgent(2)
    assert agent.rng.value == initial_cursor(2)
    restored = LiteAgent(2, rng=12345)
    assert restored.rng.value == 12345 and restored.mlp is agent.mlp
