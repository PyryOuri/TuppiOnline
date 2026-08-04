"""Showing search: contract choice, fallback semantics, and per-world contracts."""

from __future__ import annotations

import pytest

from tuppi_engine import EnginePhase, ShowAction, apply_action, observation_for
from tuppi_rules import (
    Contract,
    ELIGIBLE_SHOW_RANKS,
    card_color,
    contract_color,
    is_show_rank_eligible,
)

from tuppi_search.pimc import decide
from tuppi_search.rollout import SeatPolicies, complete_deal
from tuppi_search.worlds import build_world_set
from tuppi_search.random import SearchSeedHierarchy, information_state_digest

from .conftest import walk_deal


def _seeds(observation, configuration, seed="show"):
    return SearchSeedHierarchy(
        pimc_protocol=configuration.pimc_protocol_version,
        information_state=information_state_digest(observation),
        decision_seed=seed,
    )


def test_every_legal_show_action_is_evaluated(showing_position, smoke_config):
    decision = decide(
        showing_position.observation, configuration=smoke_config, decision_seed="s"
    )
    legal = showing_position.observation.legal_actions
    assert all(isinstance(action, ShowAction) for action in legal)
    assert len(decision.candidates) == len(legal)
    assert {item.action for item in decision.candidates} == set(legal)
    assert isinstance(decision.selected_action, ShowAction)


def test_both_contracts_appear_among_the_candidates(showing_position, smoke_config):
    decision = decide(
        showing_position.observation, configuration=smoke_config, decision_seed="s"
    )
    contracts = {item.action.declared_contract for item in decision.candidates}
    assert contracts == {Contract.NOLO, Contract.RAMI}


def test_multiple_legal_shown_cards_are_all_evaluated(
    showing_position, smoke_config
):
    decision = decide(
        showing_position.observation, configuration=smoke_config, decision_seed="s"
    )
    per_contract: dict[Contract, set] = {}
    for item in decision.candidates:
        per_contract.setdefault(item.action.declared_contract, set()).add(
            item.action.shown_card
        )
    assert all(len(cards) >= 1 for cards in per_contract.values())
    assert sum(len(cards) for cards in per_contract.values()) == len(
        decision.candidates
    )


def test_the_shown_card_remains_in_the_hand(showing_position, smoke_config):
    """``project_target_v1`` reveals the card but never reserves or removes it."""

    observation = showing_position.observation
    action = observation.legal_actions[0]
    after = apply_action(showing_position.deal_state, action)
    assert action.shown_card in after.hands[action.seat]
    assert len(after.hands[action.seat]) == len(
        showing_position.deal_state.hands[action.seat]
    )
    projected = observation_for(after, action.seat)
    assert action.shown_card in projected.own_hand
    del smoke_config


def test_verbal_fallback_semantics_are_preserved(showing_position):
    """The engine derives ``verbal_required``; the search never claims it."""

    observation = showing_position.observation
    for action in observation.legal_actions:
        after = apply_action(showing_position.deal_state, action)
        stored = after.show_actions[-1]
        assert stored.seat == action.seat
        assert stored.shown_card == action.shown_card
        assert stored.declared_contract is action.declared_contract
        # Priority 1 shows an eligible card of the contract's normal colour.
        if not stored.verbal_required:
            assert is_show_rank_eligible(stored.shown_card.rank)
            assert card_color(stored.shown_card) is contract_color(
                stored.declared_contract
            )
        else:
            # A verbal fallback either shows an eligible off-colour card, or an
            # ineligible card when no eligible rank is held at all.
            if is_show_rank_eligible(stored.shown_card.rank):
                assert card_color(stored.shown_card) is not contract_color(
                    stored.declared_contract
                )
            else:
                assert stored.shown_card.rank not in ELIGIBLE_SHOW_RANKS


def test_a_candidate_show_is_legal_in_every_sampled_world(
    showing_position, smoke_config
):
    """The observer's own hand is real in every world, so its shows always apply."""

    observation = showing_position.observation
    world_set = build_world_set(
        observation,
        configuration=smoke_config,
        seeds=_seeds(observation, smoke_config),
    )
    for world in world_set.worlds:
        for action in observation.legal_actions:
            after = apply_action(world.state, action)
            assert after.show_actions[-1].shown_card == action.shown_card


def test_sampled_worlds_may_resolve_to_different_contracts(
    showing_position, smoke_config
):
    """Nothing forces equal realized contracts across worlds or candidates.

    Later seats in a rollout make their own showing decisions from their own
    observations, so one candidate can end up as NOLO in one world and as a RAMI
    defence in another. Forcing them to agree would silently remove the very
    uncertainty the search exists to average over.
    """

    observation = showing_position.observation
    seat = observation.observing_seat
    world_set = build_world_set(
        observation,
        configuration=smoke_config,
        seeds=_seeds(observation, smoke_config),
    )
    nolo_candidate = next(
        action
        for action in observation.legal_actions
        if action.declared_contract is Contract.NOLO
    )
    outcomes = []
    for world in world_set.worlds:
        forced = apply_action(world.state, nolo_candidate)
        outcome = complete_deal(
            forced,
            policies=SeatPolicies(configuration=smoke_config, root_seat=seat),
            root_seat=seat,
            actions_already_simulated=1,
        )
        outcomes.append(
            (outcome.summary.contract, outcome.summary.declarer)
        )
    # A NOLO declaration by this seat does not fix the deal's contract: a later
    # seat may still declare RAMI.
    assert all(item[0] in (Contract.NOLO, Contract.RAMI) for item in outcomes)


def test_a_rami_declaration_ends_showing_and_sets_the_declarer(
    showing_position, smoke_config
):
    observation = showing_position.observation
    rami = next(
        action
        for action in observation.legal_actions
        if action.declared_contract is Contract.RAMI
    )
    after = apply_action(showing_position.deal_state, rami)
    assert after.phase is EnginePhase.TRICK_PLAY
    assert after.contract is Contract.RAMI
    assert after.declarer == rami.seat
    # RAMI's first leader is the seat immediately before the declarer.
    assert after.first_leader == (rami.seat - 1) % 4
    del smoke_config


def test_four_nolo_shows_resolve_to_nolo_with_no_declarer(smoke_config):
    """The all-NOLO continuation must be reachable and correctly resolved."""

    for position in walk_deal(stream_index=4):
        state = position.deal_state
        if state.phase is not EnginePhase.SHOWING:
            continue
        working = state
        completed = True
        for _ in range(4):
            if working.phase is not EnginePhase.SHOWING:
                completed = False
                break
            actor = working.current_actor
            nolo = next(
                (
                    action
                    for action in observation_for(working, actor).legal_actions
                    if action.declared_contract is Contract.NOLO
                ),
                None,
            )
            if nolo is None:
                completed = False
                break
            working = apply_action(working, nolo)
        if not completed:
            continue
        assert working.contract is Contract.NOLO
        assert working.declarer is None
        assert working.first_leader == working.forehand
        del smoke_config
        return
    pytest.skip("no all-NOLO showing sequence was constructible")


def test_later_simulated_players_receive_only_local_observations(
    showing_position, smoke_config, monkeypatch
):
    """Showing rollouts must respect the same boundary as trick-play rollouts."""

    from tuppi_engine import PlayerObservation

    log: list = []
    original = SeatPolicies.build

    def recording_build(self):
        agents = original(self)

        class _Recorder:
            def __init__(self, delegate, seat):
                self._delegate = delegate
                self._seat = seat

            @property
            def identity(self):
                return self._delegate.identity

            def choose_action(self, observation):
                log.append((self._seat, observation))
                return self._delegate.choose_action(observation)

        return tuple(_Recorder(agent, seat) for seat, agent in enumerate(agents))

    monkeypatch.setattr(SeatPolicies, "build", recording_build)
    decide(
        showing_position.observation, configuration=smoke_config, decision_seed="s"
    )
    assert log
    showing_calls = [
        item for item in log if item[1].phase is EnginePhase.SHOWING
    ]
    assert showing_calls, "no simulated showing decision was made"
    for seat, observation in log:
        assert isinstance(observation, PlayerObservation)
        assert observation.observing_seat == seat


def test_showing_decisions_are_deterministic(showing_position, smoke_config):
    first = decide(
        showing_position.observation, configuration=smoke_config, decision_seed="s"
    )
    again = decide(
        showing_position.observation, configuration=smoke_config, decision_seed="s"
    )
    assert first.selected_action == again.selected_action
    assert [item.mean_utility for item in first.candidates] == [
        item.mean_utility for item in again.candidates
    ]
