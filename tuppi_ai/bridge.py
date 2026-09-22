"""Conversions between the authoritative TuppiProject engine and the native core.

`obs_from_player_observation` is the only path by which an engine observation
reaches a native encoder, and it reads only PlayerObservation fields, which the
engine already restricts to what the observing seat may legally know.
"""

from __future__ import annotations

from tuppi_engine import EnginePhase, PlayCardAction, ShowAction
from tuppi_rules import Contract
from tuppi_rules.cards import card_from_index, card_to_index

from .native import NOLO, PH_DONE, PH_PLAY, PH_SHOW, RAMI, TcObs

_PHASE = {EnginePhase.SHOWING: PH_SHOW, EnginePhase.TRICK_PLAY: PH_PLAY}
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
    raise TypeError(f"unknown action {action!r}")


def engine_action(action: int, seat: int):
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
    o.n_shows = len(shows)
    for i, show in enumerate(shows):
        o.show_seat[i] = show.seat
        o.show_card[i] = card_to_index(show.shown_card)
        o.show_contract[i] = _CONTRACT[show.declared_contract]
        o.show_verbal[i] = int(show.verbal_required)
    o.contract = -1 if observation.contract is None else _CONTRACT[observation.contract]
    o.declarer = -1 if observation.declarer is None else observation.declarer
    o.first_leader = 0 if observation.first_leader is None else observation.first_leader
    n = 0
    for trick in observation.completed_tricks:
        for play in trick.plays:
            o.play_card[n] = card_to_index(play.card)
            o.play_seat[n] = play.seat
            n += 1
    for play in observation.current_trick:
        o.play_card[n] = card_to_index(play.card)
        o.play_seat[n] = play.seat
        n += 1
    o.n_played = n
    o.score[0] = observation.match_score.team0
    o.score[1] = observation.match_score.team1
    return o
