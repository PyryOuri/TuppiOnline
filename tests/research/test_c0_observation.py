"""A05 legal observation transport; information keys; A10 truth separation of records."""

from __future__ import annotations

import pytest

from tuppi_ai.research.observation import (ObservationCodecError, information_key, observation_from_data,
                                           public_key)


def all_observations(state_iter):
    from tuppi_engine import match_observation_for

    for state in state_iter:
        for seat in range(4):
            yield match_observation_for(state, seat)


def states_along(truth):
    from tuppi_engine import action_from_data, apply_match_action

    from tuppi_ai.research.fixtures import replay

    state = replay(truth, 0)
    yield state
    for a in truth.action_history:
        state = apply_match_action(state, action_from_data(a))
        yield state


def sooli_deal_states(decline_both=False, second_accepts=False):
    """F03's constructed deck played to the end with clones and scripted sooli answers (no new deck)."""
    from tuppi_engine import match_observation_for, apply_match_action
    from tuppi_engine.state import ACTIVE_PHASES
    from tuppi_engine import ExplicitDeal, begin_explicit_deal

    from tuppi_ai.research.clone_policy import CloneGreedyAgent
    from tuppi_ai.research.fixtures import RuleAgent, f03_hands, rami_first
    from tuppi_ai.research.runner_v3 import new_match

    def answer(ob):
        want = False if decline_both else (ob.observing_seat == 0 if second_accepts else None)
        if want is None:
            return None
        return next(i for i, a in enumerate(ob.legal_actions) if a.play_sooli is want)

    clones = {s: CloneGreedyAgent(s) for s in range(4)}
    agents = {s: RuleAgent(s, clones[s], show=rami_first if s == 1 else None,
                           offer=(answer if (decline_both or second_accepts) else None)) for s in range(4)}
    state = begin_explicit_deal(new_match(), ExplicitDeal(dealer=0, hands=f03_hands()))
    out = [state]
    while state.phase in ACTIVE_PHASES:
        seat = state.current_actor
        state = apply_match_action(state, agents[seat].choose_action(match_observation_for(state, seat)))
        out.append(state)
    return out


@pytest.fixture(scope="module")
def corpus():
    from tuppi_ai.research.fixtures import load_fixture

    obs = []
    for fid in ("F01", "F02", "F03"):
        _p, _c, truth = load_fixture(fid)
        obs += list(all_observations(states_along(truth)))
    for kw in ({}, {"decline_both": True}, {"second_accepts": True}):
        obs += list(all_observations(sooli_deal_states(**kw)))
    return obs


def test_A05_full_wire_roundtrip_over_every_seat_and_phase(corpus):
    from tuppi_engine import observation_to_data

    phases = set()
    for o in corpus:
        data = observation_to_data(o)
        back = observation_from_data(data)
        assert back == o, o.phase
        assert observation_to_data(back) == data
        assert back.own_hand == o.own_hand and back.legal_actions == o.legal_actions  # order preserved
        phases.add((o.ruleset_id.value, o.phase.value))
    expected = {"SHOWING", "TRICK_PLAY", "SOOLI_OFFER", "SOOLI_GIVE", "SOOLI_RETURN", "SOOLI_PLAY",
                "DEAL_COMPLETE"}
    assert expected <= {p for _r, p in phases}, phases
    assert {r for r, _p in phases} == {"project_target_v3"}


def test_A05_locked_bids_masking_and_private_exchange_survive_transport(corpus):
    from tuppi_engine import observation_to_data

    locked = [o for o in corpus if o.phase.value == "SHOWING"]
    assert locked and all(o.show_actions == () for o in locked)
    assert {o.bids_locked for o in locked} >= {0, 1, 2}
    exchange = [o for o in corpus if o.soolaaja is not None and o.sooli_exchanged]
    assert exchange
    for o in exchange:
        back = observation_from_data(observation_to_data(o))
        participant = o.observing_seat in (o.soolaaja, (o.soolaaja + 2) % 4)
        assert (back.sooli_given_card is not None) == participant
        assert (back.sooli_returned_card is not None) == participant
        assert back.sooli_tricks == o.sooli_tricks and back.completed_tricks == ()


def test_A05_strict_inverse_rejects_tampered_records(corpus):
    from tuppi_engine import observation_to_data

    o = next(x for x in corpus if x.phase.value == "TRICK_PLAY" and x.show_actions)
    data = observation_to_data(o)
    tampered = [dict(data, extra=1),
                {k: v for k, v in data.items() if k != "team_tricks"},
                dict(data, show_actions=[dict(data["show_actions"][0],
                                              verbal_required=not data["show_actions"][0]["verbal_required"])]
                     + data["show_actions"][1:]),
                dict(data, publicly_shown_cards=data["publicly_shown_cards"][::-1])
                if len({p["card"] for p in data["publicly_shown_cards"]}) > 1 else dict(data, dealer=5)]
    for bad in tampered:
        with pytest.raises(ObservationCodecError):
            observation_from_data(bad)


def test_A05_information_key_excludes_protocol_refs_but_encoder_is_not_injective(corpus):
    """Features are not information keys: the encoder never sees the ruleset."""
    from dataclasses import replace

    import numpy as np
    from tuppi_rules import RulesetId

    import tuppi_ai.native as nat
    from tuppi_ai.bridge import obs_from_player_observation

    o = next(x for x in corpus if x.phase.value == "TRICK_PLAY" and x.contract.value == "RAMI"
             and x.legal_actions and x.soolaaja is None)
    v2 = replace(o, ruleset_id=RulesetId.PROJECT_TARGET_V2)
    f3 = nat.encode(obs_from_player_observation(o), encoder=2)
    f2 = nat.encode(obs_from_player_observation(v2), encoder=2)
    assert np.array_equal(f2, f3)
    assert information_key(o) != information_key(v2)
    moved = replace(o, match_ref="other-match", deal_ref="other-match/deal:0")
    assert information_key(moved) == information_key(o)
    assert information_key(o, own_memory={"option": [1]}) != information_key(o)
    # corpus holds the four seats of each state consecutively: same public key, distinct information keys
    j = next(j for j in range(0, len(corpus), 4) if corpus[j].phase.value == "TRICK_PLAY"
             and corpus[j].show_actions)
    seats = corpus[j:j + 4]
    assert [s.observing_seat for s in seats] == [0, 1, 2, 3]
    assert len({public_key(s) for s in seats}) == 1
    assert len({information_key(s) for s in seats}) == 4


def test_A10_decision_cases_hold_no_hidden_cards_and_leaks_are_detected():
    from dataclasses import replace

    from tuppi_ai.research.fixtures import load_fixture
    from tuppi_ai.research.records import TruthLeakError, check_no_truth

    for fid in ("F01", "F02", "F03", "F05"):
        _p, cases, truth = load_fixture(fid)
        for case in cases:
            check_no_truth(case, truth)
    _p, cases, truth = load_fixture("F02")
    case = cases[0]
    hidden = next(c for s, h in enumerate(truth.initial_hands) if s != case.observation["observing_seat"]
                  for c in h if c not in str(case.observation))
    leaky = replace(case, policy_snapshot_ref=f'"{hidden}"')
    with pytest.raises(TruthLeakError):
        check_no_truth(leaky, truth)
    with pytest.raises(TruthLeakError):
        replace(case, population={"hands": [hidden]})
