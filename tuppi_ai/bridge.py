"""Conversions between the authoritative TuppiProject engine and the native core.

`obs_from_player_observation` is the only path by which an engine observation
reaches a native encoder, and it reads only PlayerObservation fields, which the
engine already restricts to what the observing seat may legally know.
"""

from __future__ import annotations

from tuppi_engine import EnginePhase, PlayCardAction, ShowAction
from tuppi_rules import Contract
from tuppi_rules.cards import card_from_index, card_to_index

from .native import (ACT_EXCHANGE, ACT_SOOLI_ACCEPT, ACT_SOOLI_DECLINE, NOLO, PH_DONE, PH_PLAY, PH_SHOW,
                     PH_SOOLI_GIVE, PH_SOOLI_OFFER, PH_SOOLI_PLAY, PH_SOOLI_RETURN, RAMI, TcObs)

_PHASE = {EnginePhase.SHOWING: PH_SHOW, EnginePhase.TRICK_PLAY: PH_PLAY}
# project_target_v2 engines add the sooli phases; a v1-only engine lacks them.
for _name, _ph in (("SOOLI_OFFER", PH_SOOLI_OFFER), ("SOOLI_GIVE", PH_SOOLI_GIVE),
                   ("SOOLI_RETURN", PH_SOOLI_RETURN), ("SOOLI_PLAY", PH_SOOLI_PLAY)):
    if hasattr(EnginePhase, _name):
        _PHASE[getattr(EnginePhase, _name)] = _ph
try:
    from tuppi_engine import SooliDecisionAction, SooliExchangeAction
except ImportError:  # v1-only engine
    SooliDecisionAction = SooliExchangeAction = None
_CONTRACT = {Contract.NOLO: NOLO, Contract.RAMI: RAMI}
_CONTRACTS = (Contract.NOLO, Contract.RAMI)


def mask_of(cards) -> int:
    m = 0
    for card in cards:
        m |= 1 << card_to_index(card)
    return m


def action_id(action) -> int:
    if isinstance(action, PlayCardAction):
        return card_to_index(action.card)
    if isinstance(action, ShowAction):
        return 52 + 52 * _CONTRACT[action.declared_contract] + card_to_index(action.shown_card)
    if SooliDecisionAction is not None and isinstance(action, SooliDecisionAction):
        return ACT_SOOLI_ACCEPT if action.play_sooli else ACT_SOOLI_DECLINE
    if SooliExchangeAction is not None and isinstance(action, SooliExchangeAction):
        return ACT_EXCHANGE + card_to_index(action.card)
    raise TypeError(f"unknown action {action!r}")


def engine_action(action: int, seat: int):
    if action in (ACT_SOOLI_DECLINE, ACT_SOOLI_ACCEPT):
        return SooliDecisionAction(seat=seat, play_sooli=action == ACT_SOOLI_ACCEPT)
    if action >= ACT_EXCHANGE:
        return SooliExchangeAction(seat=seat, card=card_from_index(action - ACT_EXCHANGE))
    if action < 52:
        return PlayCardAction(seat=seat, card=card_from_index(action))
    contract, card = divmod(action - 52, 52)
    return ShowAction(seat=seat, shown_card=card_from_index(card),
                      declared_contract=_CONTRACTS[contract])


def obs_from_player_observation(observation) -> TcObs:
    o = TcObs()
    o.hand = mask_of(observation.own_hand)
    o.seat = observation.observing_seat
    o.dealer = observation.dealer
    o.phase = _PHASE.get(observation.phase, PH_DONE)
    shows = observation.show_actions
    # project_target_v3 showing: no bid is visible, only how many were taken.
    o.n_shows = len(shows) + getattr(observation, "bids_locked", 0)
    for i, show in enumerate(shows):
        o.show_seat[i] = show.seat
        o.show_card[i] = card_to_index(show.shown_card)
        o.show_contract[i] = _CONTRACT[show.declared_contract]
        o.show_verbal[i] = int(show.verbal_required)
    o.contract = -1 if observation.contract is None else _CONTRACT[observation.contract]
    o.declarer = -1 if observation.declarer is None else observation.declarer
    o.first_leader = 0 if observation.first_leader is None else observation.first_leader
    sooli = getattr(observation, "soolaaja", None) is not None and getattr(observation, "sooli_exchanged", False)
    if sooli:
        tricks, current = observation.sooli_tricks, observation.sooli_current_trick
    else:
        tricks, current = observation.completed_tricks, observation.current_trick
    n = 0
    for trick in tricks:
        for play in trick.plays:
            o.play_card[n] = card_to_index(play.card)
            o.play_seat[n] = play.seat
            n += 1
    for play in current:
        o.play_card[n] = card_to_index(play.card)
        o.play_seat[n] = play.seat
        n += 1
    o.n_played = n
    o.score[0] = observation.match_score.team0
    o.score[1] = observation.match_score.team1
    ruleset = getattr(observation, "ruleset_id", None)
    o.ruleset = {"project_target_v2": 2, "project_target_v3": 3}.get(getattr(ruleset, "value", None), 1)
    o.trick_size = 3 if sooli else 4
    decisions = getattr(observation, "sooli_decisions", ())
    o.n_decisions = len(decisions)
    for i, (seat, accept) in enumerate(decisions):
        o.decision_seat[i] = seat
        o.decision_accept[i] = int(accept)
    soolaaja = getattr(observation, "soolaaja", None)
    o.soolaaja = -1 if soolaaja is None else soolaaja
    given = getattr(observation, "sooli_given_card", None)
    returned = getattr(observation, "sooli_returned_card", None)
    o.known_given = -1 if given is None else card_to_index(given)
    o.known_returned = -1 if returned is None else card_to_index(returned)
    return o
