"""The native double-dummy solver against TuppiProject's exact late-game solver."""

from __future__ import annotations

import random

from tuppi_engine import (EnginePhase, ExplicitDeal, apply_match_action, begin_explicit_deal,
                          create_match, match_observation_for)
from tuppi_engine.trusted import trusted_transitions
from tuppi_exact.solver import solve_late_game
from tuppi_rules import MatchScore
from tuppi_rules.cards import FULL_DECK

from tuppi_ai import native
from tuppi_ai.bridge import action_id, mask_of


def test_dd_matches_exact_solver_on_late_positions():
    rng = random.Random("dd-vs-exact")
    checked = {"RAMI": 0, "NOLO": 0}
    with trusted_transitions():
        while min(checked.values()) < 120:
            cards = list(FULL_DECK)
            rng.shuffle(cards)
            hands = tuple(tuple(cards[s * 13:(s + 1) * 13]) for s in range(4))
            dealer = rng.randrange(4)
            state = begin_explicit_deal(
                create_match(initial_score=MatchScore(0, 0), initial_dealer=dealer, match_ref="dd-test"),
                ExplicitDeal(dealer=dealer, hands=hands))
            deal = native.new_deal([mask_of(h) for h in hands], dealer)
            stop = rng.randrange(4 * 8 + 1, 4 * 12)  # 5 or fewer tricks remaining
            while state.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
                active = state.active_deal
                if state.phase is EnginePhase.TRICK_PLAY and len(active.completed_tricks) * 4 + len(active.current_trick) >= stop:
                    solution = solve_late_game(active)
                    assert native.dd_team0_tricks(deal) == solution.optimal_team0_tricks_final
                    checked[active.contract.value] += 1
                    break
                obs = match_observation_for(state, state.current_actor)
                action = rng.choice(obs.legal_actions)
                if state.phase is EnginePhase.SHOWING and checked["NOLO"] < checked["RAMI"]:
                    # Steer showing toward NOLO so both contracts are covered.
                    nolo = [a for a in obs.legal_actions if a.declared_contract.value == "NOLO"]
                    action = rng.choice(nolo)
                native.lib.tc_apply(deal, action_id(action))
                state = apply_match_action(state, action)


def test_persistent_cache_gives_order_independent_results():
    """The solver's cache persists across solves; answers must not depend on order."""
    rng = random.Random("dd-order")
    positions = []
    while len(positions) < 400:
        deck = list(range(52))
        rng.shuffle(deck)
        d = native.new_deal([sum(1 << c for c in deck[i * 13:(i + 1) * 13]) for i in range(4)], rng.randrange(4))
        stop = rng.randrange(4 * 6, 4 * 9 + 3)  # 7 down to 4 tricks left, some mid-trick
        while d.phase != native.PH_DONE and not (d.phase == native.PH_PLAY and d.n_played >= stop):
            legal = native.legal(d)
            if d.phase == native.PH_SHOW and rng.random() < 0.5:
                nolo = [a for a in legal if (a - 52) // 52 == 0]
                legal = nolo or legal
            native.lib.tc_apply(d, rng.choice(legal))
        if d.phase == native.PH_PLAY:
            positions.append(d)
    first = [native.dd_team0_tricks(p) for p in positions]
    order = list(range(len(positions)))
    for _ in range(2):
        rng.shuffle(order)
        again = {i: native.dd_team0_tricks(positions[i]) for i in order}
        assert all(again[i] == first[i] for i in range(len(positions)))
