"""Differential tests for project_target_v2 (v1 + sooli): native core vs. engine.

Needs a TuppiProject engine with project_target_v2 (run with the tuppi-v2
environment); skipped otherwise. As for v1, every step is compared: actor,
phase, legal actions, the encodings built natively and from the engine's
PlayerObservation for every seat, and the complete result and transition.
"""

from __future__ import annotations

import random

import numpy as np
import pytest

tuppi_engine = pytest.importorskip("tuppi_engine")
if not hasattr(tuppi_engine, "SooliDecisionAction"):
    pytest.skip("engine without project_target_v2", allow_module_level=True)

from tuppi_engine import (  # noqa: E402
    EnginePhase,
    ExplicitDeal,
    SooliDecisionAction,
    apply_match_action,
    begin_explicit_deal,
    create_match,
    match_observation_for,
)
from tuppi_engine.state import ACTIVE_PHASES  # noqa: E402
from tuppi_engine.trusted import trusted_transitions  # noqa: E402
from tuppi_rules import Contract, MatchScore  # noqa: E402
from tuppi_rules.cards import FULL_DECK, Rank, card_to_index  # noqa: E402
from tuppi_rules.model import RulesetId  # noqa: E402

from tuppi_ai import native  # noqa: E402
from tuppi_ai.bridge import (  # noqa: E402
    _PHASE, action_id, engine_action, mask_of, obs_from_player_observation)


def _random_score(rng):
    level = rng.randrange(13)
    if level == 0:
        return MatchScore(0, 0)
    return MatchScore(4 * level, 0) if rng.random() < 0.5 else MatchScore(0, 4 * level)


def _deal(rng):
    cards = list(FULL_DECK)
    rng.shuffle(cards)
    return tuple(tuple(cards[s * 13:(s + 1) * 13]) for s in range(4))


def _play_lockstep(hands, dealer, score, chooser, rng, check_all_seats=True, ruleset=2):
    ruleset_id = {2: RulesetId.PROJECT_TARGET_V2, 3: RulesetId.PROJECT_TARGET_V3}[ruleset]
    state = begin_explicit_deal(
        create_match(initial_score=score, initial_dealer=dealer, match_ref="diff-v2",
                     ruleset_id=ruleset_id),
        ExplicitDeal(dealer=dealer, hands=hands))
    deal = native.new_deal([mask_of(h) for h in hands], dealer, score.team0, score.team1, ruleset=ruleset)
    steps = 0
    while state.phase in ACTIVE_PHASES:
        seat = state.current_actor
        assert deal.cur == seat, steps
        assert deal.phase == _PHASE[state.phase], steps
        observation = match_observation_for(state, seat)
        py_legal = sorted(action_id(a) for a in observation.legal_actions)
        assert sorted(native.legal(deal)) == py_legal, steps
        for s in (range(4) if check_all_seats else (seat,)):
            obs_py = obs_from_player_observation(match_observation_for(state, s))
            obs_nat = native.observe(deal, s)
            assert bytes(obs_py) == bytes(obs_nat), (steps, s)
            for version in (1, 2):
                a, b = native.encode(obs_py, encoder=version), native.encode(obs_nat, encoder=version)
                assert np.array_equal(a, b), (steps, s, version)
            if s == seat:
                assert sorted(native.legal_obs(obs_py)) == py_legal
        action = chooser(observation, rng)
        assert engine_action(action_id(action), seat) == action
        assert native.lib.tc_apply(deal, action_id(action)) == 0
        state = apply_match_action(state, action)
        steps += 1
    result = state.completed_deals[-1].public_result
    assert deal.phase == native.PH_DONE
    assert deal.contract == (native.RAMI if result.contract is Contract.RAMI else native.NOLO)
    assert deal.declarer == (-1 if result.declarer is None else result.declarer)
    assert tuple(deal.team_tricks) == tuple(result.team_tricks)
    assert deal.winner_team == result.deal_score.winner_team.value
    assert deal.points == result.deal_score.points
    assert deal.soolaaja == (-1 if result.soolaaja is None else result.soolaaja)
    assert [(deal.decision_seat[i], bool(deal.decision_accept[i])) for i in range(deal.n_decisions)] == \
        [tuple(d) for d in result.sooli_decisions]
    if result.soolaaja is None:
        assert bool(deal.stolen) == result.deal_score.stolen_rami
    else:
        assert not deal.stolen
        assert bool(deal.sooli_won) == (not result.deal_score.soolaaja_won_trick)
    after = (native.C.c_uint8 * 2)()
    over = native.lib.tc_next_score(deal.score, deal.winner_team, deal.points, after)
    assert (after[0], after[1]) == result.score_after.as_tuple()
    assert bool(over) == result.match_terminal
    return result


def _chooser(p_accept):
    def choose(observation, rng):
        legal = observation.legal_actions
        if isinstance(legal[0], SooliDecisionAction):
            return legal[1] if rng.random() < p_accept else legal[0]
        if observation.phase is EnginePhase.SHOWING:
            # NOLO often, so that several seats bid before a RAMI
            nolo = [a for a in legal if a.declared_contract.value == "NOLO"]
            if nolo and rng.random() < 0.5:
                return rng.choice(nolo)
        return rng.choice(legal)
    return choose


@pytest.mark.parametrize("seed,ruleset", [(0, 2), (1, 2), (2, 2), (0, 3), (1, 3)])
def test_random_v2_play_matches_engine(seed, ruleset):
    rng = random.Random(f"diff-v2-{seed}-{ruleset}")
    kinds = {"nolo": 0, "rami": 0, "sooli": 0}
    with trusted_transitions():
        for i in range(120):
            result = _play_lockstep(_deal(rng), rng.randrange(4), _random_score(rng), _chooser(0.6), rng,
                                    check_all_seats=(i % 4 == 0), ruleset=ruleset)
            kinds["nolo" if result.contract is Contract.NOLO else
                  "sooli" if result.soolaaja is not None else "rami"] += 1
    assert min(kinds.values()) > 0, kinds


def _safe_sooli_hand(rng):
    """A soolaaja hand that survives many tricks: aces and low cards."""
    low = [c for c in FULL_DECK if c.rank in (Rank.ACE, Rank.TWO, Rank.THREE, Rank.FOUR)]
    return rng.sample(low, 13)


def test_long_sooli_deals_match_engine():
    """Random play rarely survives many sooli tricks; low hands reach the 13-trick end."""
    rng = random.Random("diff-v2-long")
    lengths = []
    with trusted_transitions():
        for _ in range(80):
            safe = _safe_sooli_hand(rng)
            rest = [c for c in FULL_DECK if c not in safe]
            rng.shuffle(rest)
            others = [tuple(rest[i * 13:(i + 1) * 13]) for i in range(3)]
            dealer = rng.randrange(4)
            # Make a seat after the declarer likely hold the safe hand: any seat may declare.
            seat = rng.randrange(4)
            hands = others[:seat] + [tuple(safe)] + others[seat:]

            def choose(observation, r, safe_seat=seat):
                legal = observation.legal_actions
                if isinstance(legal[0], SooliDecisionAction):
                    return legal[1] if observation.observing_seat == safe_seat else legal[0]
                if observation.phase is EnginePhase.SOOLI_PLAY and observation.observing_seat == safe_seat:
                    # duck: the lowest legal card
                    return min(legal, key=lambda a: (card_to_index(a.card) % 13 + 1) % 13)
                return r.choice(legal)

            result = _play_lockstep(tuple(hands), dealer, _random_score(rng), choose, rng)
            if result.soolaaja is not None:
                lengths.append(len(result.sooli_tricks))
    assert lengths and max(lengths) == 13, lengths
