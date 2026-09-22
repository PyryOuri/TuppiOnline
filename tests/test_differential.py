"""Differential tests: the native core against the authoritative TuppiProject engine.

Every step of every deal is compared: actor, phase, the legal action set, the
observation-only encoding (projected natively vs. built from the engine's
PlayerObservation), and the complete deal result and match transition.
"""

from __future__ import annotations

import random

import numpy as np
import pytest

from tuppi_engine import (
    EnginePhase,
    ExplicitDeal,
    apply_match_action,
    begin_explicit_deal,
    create_match,
    match_observation_for,
)
from tuppi_engine.trusted import trusted_transitions
from tuppi_rules import Contract, MatchScore, valid_show_cards
from tuppi_rules.cards import FULL_DECK, card_to_index

from tuppi_ai import native
from tuppi_ai.bridge import action_id, mask_of, obs_from_player_observation

_PHASE = {EnginePhase.SHOWING: native.PH_SHOW, EnginePhase.TRICK_PLAY: native.PH_PLAY}


def _random_score(rng):
    level = rng.randrange(13)
    if level == 0:
        return MatchScore(0, 0)
    return MatchScore(4 * level, 0) if rng.random() < 0.5 else MatchScore(0, 4 * level)


def _play_lockstep(hands, dealer, score, chooser, rng, check_all_seats=False):
    state = begin_explicit_deal(
        create_match(initial_score=score, initial_dealer=dealer, match_ref="diff-test"),
        ExplicitDeal(dealer=dealer, hands=hands))
    deal = native.new_deal([mask_of(h) for h in hands], dealer, score.team0, score.team1)
    steps = 0
    while state.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
        seat = state.current_actor
        assert deal.cur == seat
        assert deal.phase == _PHASE[state.phase]
        observation = match_observation_for(state, seat)
        py_legal = sorted(action_id(a) for a in observation.legal_actions)
        assert sorted(native.legal(deal)) == py_legal
        seats = range(4) if check_all_seats else (seat,)
        for s in seats:
            obs_py = obs_from_player_observation(match_observation_for(state, s))
            obs_nat = native.observe(deal, s)
            assert np.array_equal(native.encode(obs_py), native.encode(obs_nat)), (steps, s)
            if s == seat:
                assert sorted(native.legal_obs(obs_py)) == py_legal
        action = chooser(observation, rng)
        assert native.lib.tc_apply(deal, action_id(action)) == 0
        state = apply_match_action(state, action)
        steps += 1
    result = state.completed_deals[-1].public_result
    assert deal.phase == native.PH_DONE
    assert deal.contract == (native.RAMI if result.contract is Contract.RAMI else native.NOLO)
    assert deal.declarer == (-1 if result.declarer is None else result.declarer)
    assert deal.first_leader == result.first_leader
    assert tuple(deal.team_tricks) == tuple(result.team_tricks)
    assert deal.winner_team == result.deal_score.winner_team.value
    assert deal.points == result.deal_score.points
    assert bool(deal.stolen) == result.deal_score.stolen_rami
    after = (native.C.c_uint8 * 2)()
    over = native.lib.tc_next_score(deal.score, deal.winner_team, deal.points, after)
    assert (after[0], after[1]) == result.score_after.as_tuple()
    assert bool(over) == result.match_terminal
    return steps


def _random_choice(observation, rng):
    return rng.choice(observation.legal_actions)


def _deal(rng):
    cards = list(FULL_DECK)
    rng.shuffle(cards)
    return tuple(tuple(cards[s * 13:(s + 1) * 13]) for s in range(4))


@pytest.mark.parametrize("seed", range(4))
def test_random_play_matches_engine(seed):
    rng = random.Random(f"diff-random-{seed}")
    with trusted_transitions():
        for i in range(150):
            _play_lockstep(_deal(rng), rng.randrange(4), _random_score(rng), _random_choice,
                           rng, check_all_seats=(i % 10 == 0))


def test_incumbent_play_matches_engine():
    from tuppi_agents.improved_registry import (
        improved_agent_from_specification, improved_specifications_by_profile_key)
    spec = improved_specifications_by_profile_key()["partner_aware_lead_v2"]
    agents = {s: improved_agent_from_specification(spec, profile_key="partner_aware_lead_v2", seat=s)
              for s in range(4)}
    rng = random.Random("diff-incumbent")
    with trusted_transitions():
        for _ in range(150):
            _play_lockstep(_deal(rng), rng.randrange(4), _random_score(rng),
                           lambda obs, r: agents[obs.observing_seat].choose_action(obs), rng)


def test_show_fallback_hierarchy_matches_rules():
    """Priorities 2 and 3 are rare in random deals, so hands are built for them."""
    rng = random.Random("diff-show")
    ineligible = [c for c in FULL_DECK if not 3 <= c.rank.value <= 9]
    eligible = [c for c in FULL_DECK if 3 <= c.rank.value <= 9]
    red_eligible = [c for c in eligible if c.suit.value in ("hearts", "diamonds")]
    black_eligible = [c for c in eligible if c.suit.value in ("clubs", "spades")]
    hands = []
    for _ in range(300):
        hands.append(rng.sample(ineligible, 13))  # priority 3 for both contracts
        hands.append(rng.sample(ineligible, 12) + rng.sample(red_eligible, 1))
        hands.append(rng.sample(ineligible, 10) + rng.sample(black_eligible, 3))
        hands.append(rng.sample(FULL_DECK, 13))
    for hand in hands:
        m = mask_of(hand)
        for contract, k in ((Contract.NOLO, native.NOLO), (Contract.RAMI, native.RAMI)):
            assert native.lib.tc_valid_show_cards(m, k) == mask_of(valid_show_cards(hand, contract))
            for card in valid_show_cards(hand, contract):
                eligible_colour = (3 <= card.rank.value <= 9) and (
                    (card.suit.value in ("hearts", "diamonds")) == (contract is Contract.RAMI))
                assert native.lib.tc_verbal_required(card_to_index(card), k) == int(not eligible_colour)


def test_constructed_fallback_deals_play_through():
    """Whole deals where showing seats need the verbal fallbacks."""
    rng = random.Random("diff-fallback-deals")
    ineligible = [c for c in FULL_DECK if not 3 <= c.rank.value <= 9]
    with trusted_transitions():
        for _ in range(60):
            first = rng.sample(ineligible, 13)
            rest = [c for c in FULL_DECK if c not in first]
            rng.shuffle(rest)
            hands = [tuple(first)] + [tuple(rest[i * 13:(i + 1) * 13]) for i in range(3)]
            rot = rng.randrange(4)
            hands = tuple(hands[(s - rot) % 4] for s in range(4))
            _play_lockstep(hands, rng.randrange(4), _random_score(rng), _random_choice, rng,
                           check_all_seats=True)
