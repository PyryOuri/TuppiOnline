"""Candidate rule layers for successors of partner_aware_lead_v2 (docs/HEURISTIC_PLAN.md).

A rule sees only what the player can see: its own hand, the cards played, the
legal actions, the contract, its position in the trick and the tricks left,
plus the heuristic's chosen action. It returns a replacement action id
(native numbering: card = suit * 13 + rank - 2) or None for no change. The
same functions drive the offline screen (`tools/rule_check.py`) and the
playable variants (`tuppi_ai/heuristic_variants.py`).
"""

from __future__ import annotations


def suit(c: int) -> int:
    return c // 13


def suit_cards(hand: int, s: int) -> list[int]:
    return [c for c in range(13 * s, 13 * s + 13) if (hand >> c) & 1]


def certain_winner(c: int, hand: int, played: set[int]) -> bool:
    """No unplayed higher card of the suit is outside the hand, so a lead of it wins the trick."""
    return all((hand >> h) & 1 or h in played for h in range(c + 1, 13 * suit(c) + 13))


def underlead_unsupported_honour(v: dict):
    """RAMI, leading: if the heuristic leads the top card of a suit and that card is not a
    certain winner, lead the suit's lowest card instead."""
    if v["contract"] != "RAMI" or v["pos"] != 0:
        return None
    h = v["heur"]
    same = suit_cards(v["hand"], suit(h))
    if len(same) < 2 or h != max(same) or certain_winner(h, v["hand"], set(v["played"])):
        return None
    return min(same)


def cash_singleton_winner(v: dict, max_tricks_left: int = 13):
    """RAMI, leading: lead a singleton that is a certain winner (the highest such)."""
    if v["contract"] != "RAMI" or v["pos"] != 0 or v["tricks_left"] > max_tricks_left:
        return None
    played = set(v["played"])
    cands = [c for c in v["legal"] if len(suit_cards(v["hand"], suit(c))) == 1
             and certain_winner(c, v["hand"], played)]
    if not cands or v["heur"] in cands:
        return None
    return max(cands, key=lambda c: c % 13)


def cash_singleton_winner_late(v: dict):
    return cash_singleton_winner(v, max_tricks_left=5)


RULES = {
    "underlead": underlead_unsupported_honour,
    "cash_singleton": cash_singleton_winner,
    "cash_singleton_late": cash_singleton_winner_late,
}


def apply_layers(layers: list[str], v: dict):
    """The first layer that changes the action wins; None if no layer fires."""
    for name in layers:
        a = RULES[name](v)
        if a is not None and a != v["heur"]:
            return a
    return None


def view_from_tcobs(obs, legal: list[int], heur: int) -> dict:
    """A rule view from a native observation (tuppi_ai.bridge.obs_from_player_observation)."""
    n = int(obs.n_played)
    return {"contract": "RAMI" if obs.contract == 1 else "NOLO", "pos": n % 4, "tricks_left": 13 - n // 4,
            "hand": int(obs.hand), "played": [int(obs.play_card[i]) for i in range(n)], "legal": legal,
            "heur": heur}
