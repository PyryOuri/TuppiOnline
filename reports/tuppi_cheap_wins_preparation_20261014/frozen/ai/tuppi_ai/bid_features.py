"""Human-countable features of a bidding position (project_target_v3).

Everything here is something a player can count at the table from their own
thirteen cards and the situation: high-card points and controls, shape, low
cards, stoppers, NOLO-safe suits, whether a silent show is available, the seat
and the score. Bids are blind under locked bids, so this is (up to the exact
cards) everything the bot knows when it bids; `tools/bid_explain.py` fits
readable rules on it.
"""

from __future__ import annotations

from collections.abc import Sequence

SUITS = ("H", "D", "C", "S")
RED = {"H", "D"}
HCP = {14: 4, 13: 3, 12: 2, 11: 1}
TARGET = 52  # the match is won at 52 points


def _rank(code: str) -> int:
    body = code[:-1]
    return {"J": 11, "Q": 12, "K": 13, "A": 14}.get(body) or int(body)


def _quick_tricks(ranks: list[int]) -> float:
    """Classic defensive tricks: AK 2, AQ 1.5, A 1, KQ 1, K with a guard 0.5."""
    s = set(ranks)
    if 14 in s and 13 in s:
        return 2.0
    if 14 in s and 12 in s:
        return 1.5
    if 14 in s:
        return 1.0
    if 13 in s and 12 in s:
        return 1.0
    if 13 in s and len(ranks) >= 2:
        return 0.5
    return 0.0


def _stopper(ranks: list[int]) -> bool:
    """A, Kx, Qxx or Jxxx: the suit cannot simply be run against you."""
    n, s = len(ranks), set(ranks)
    return 14 in s or (13 in s and n >= 2) or (12 in s and n >= 3) or (11 in s and n >= 4)


FEATURES = (
    "hcp", "aces", "kings", "queens", "jacks", "controls", "honours", "top_five", "quick_tricks",
    "longest", "second_longest", "shortest", "voids", "singletons", "doubletons", "balanced",
    "long_suit_points", "low_cards", "very_low_cards", "mid_cards", "stoppers",
    "nolo_safe_suits", "high_short_honours", "low_short_suits", "red_silent", "black_silent",
    "position", "own_score", "opp_score", "score_diff", "own_to_target", "opp_to_target",
    "old_rami_score", "old_nolo_score",
)


def bid_features(hand: Sequence[str], *, position: int, own_score: int, opp_score: int) -> dict[str, float]:
    """`hand`: 13 card codes ("QH", "10S"); `position`: 0 = forehand .. 3."""
    by_suit = {s: sorted((_rank(c) for c in hand if c[-1] == s), reverse=True) for s in SUITS}
    ranks = [r for rs in by_suit.values() for r in rs]
    lengths = sorted((len(rs) for rs in by_suit.values()), reverse=True)
    f: dict[str, float] = {}
    f["hcp"] = sum(HCP.get(r, 0) for r in ranks)
    f["aces"] = ranks.count(14)
    f["kings"] = ranks.count(13)
    f["queens"] = ranks.count(12)
    f["jacks"] = ranks.count(11)
    f["controls"] = 2 * f["aces"] + f["kings"]
    f["honours"] = sum(1 for r in ranks if r >= 11)
    f["top_five"] = sum(1 for r in ranks if r >= 10)
    f["quick_tricks"] = sum(_quick_tricks(rs) for rs in by_suit.values())
    f["longest"], f["second_longest"], f["shortest"] = lengths[0], lengths[1], lengths[3]
    f["voids"] = lengths.count(0)
    f["singletons"] = lengths.count(1)
    f["doubletons"] = lengths.count(2)
    f["balanced"] = float(lengths in ([4, 3, 3, 3], [4, 4, 3, 2], [5, 3, 3, 2]))
    f["long_suit_points"] = sum(max(0, n - 4) for n in lengths)
    f["low_cards"] = sum(1 for r in ranks if r <= 4)
    f["very_low_cards"] = sum(1 for r in ranks if r <= 3)
    f["mid_cards"] = sum(1 for r in ranks if 5 <= r <= 9)
    f["stoppers"] = sum(_stopper(rs) for rs in by_suit.values())
    # NOLO: a suit you can follow low in without winning tricks, and honours
    # that are hard to get rid of because the suit is short.
    f["nolo_safe_suits"] = sum(1 for rs in by_suit.values() if rs and rs[0] <= 7)
    f["high_short_honours"] = sum(1 for rs in by_suit.values() if 1 <= len(rs) <= 2 and rs[0] >= 11)
    f["low_short_suits"] = sum(1 for rs in by_suit.values() if 1 <= len(rs) <= 2 and rs[0] <= 6)
    # Showing without speaking: RAMI with a red 3-9, NOLO with a black 3-9.
    f["red_silent"] = float(any(c[-1] in RED and 3 <= _rank(c) <= 9 for c in hand))
    f["black_silent"] = float(any(c[-1] not in RED and 3 <= _rank(c) <= 9 for c in hand))
    f["position"] = position
    f["own_score"], f["opp_score"] = own_score, opp_score
    f["score_diff"] = own_score - opp_score
    f["own_to_target"], f["opp_to_target"] = TARGET - own_score, TARGET - opp_score
    # The old reference bot's rule (partner_aware_v1), for comparison.
    f["old_rami_score"] = f["hcp"] + 0.5 * f["aces"] + 0.25 * (f["aces"] + f["kings"]) \
        + 0.5 * max(0, lengths[0] - 4)
    f["old_nolo_score"] = 1.5 * f["low_cards"] + 3 * f["voids"] + 2 * f["singletons"] + f["doubletons"] \
        - f["top_five"] - 0.5 * f["honours"]
    assert set(f) == set(FEATURES)
    return f
