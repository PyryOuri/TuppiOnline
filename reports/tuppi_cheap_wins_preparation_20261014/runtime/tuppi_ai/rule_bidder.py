"""Bid by a readable rule, play like the bot: what following the rule costs.

`RuleBidder` wraps a `SearchAgent`. At a bid with a choice it asks the rule
(`tuppi_ai.bid_models`) whether to declare RAMI, then shows the card the bot's
own search prefers among that contract's legal shows (so only the contract
decision differs from the bot). Every other decision is the bot's.
"""

from __future__ import annotations

import numpy as np

from .bid_features import bid_features
from .bridge import action_id, obs_from_player_observation


def features_of(observation) -> dict[str, float]:
    from tuppi_rules import card_to_code

    seat = observation.observing_seat
    position = (seat - observation.forehand) % 4
    score = observation.match_score
    own, opp = (score.team0, score.team1) if seat % 2 == 0 else (score.team1, score.team0)
    return bid_features([card_to_code(c) for c in observation.own_hand], position=position,
                        own_score=own, opp_score=opp)


class RuleBidder:
    handles_sooli = True

    def __init__(self, agent, model):
        self.agent = agent
        self.model = model
        self.last_values = None

    def choose_action(self, observation):
        from tuppi_engine import EnginePhase
        from tuppi_rules import Contract

        legal = observation.legal_actions
        if observation.phase is not EnginePhase.SHOWING or len(legal) == 1:
            action = self.agent.choose_action(observation)
            self.last_values = getattr(self.agent, "last_values", None)
            return action
        rami = bool(self.model.predict([features_of(observation)])[0])
        want = Contract.RAMI if rami else Contract.NOLO
        candidates = [a for a in legal if a.declared_contract is want] or list(legal)
        if len(candidates) == 1:
            self.last_values = None
            return candidates[0]
        agent = self.agent
        obs = obs_from_player_observation(observation)
        if obs.ruleset == 2:  # as SearchAgent.choose_action does
            cfg = agent.sooli
            agent.searcher.env.set_sooli(cfg["belief"], False, cfg["offer_play_heur"], cfg["lam"])
        searcher = agent.show_searcher or agent.searcher
        ids = [action_id(a) for a in candidates]
        values = searcher.action_values(obs, ids)
        self.last_values = {a: float(v) for a, v in zip(ids, values)}
        return candidates[int(np.argmax(values))]
