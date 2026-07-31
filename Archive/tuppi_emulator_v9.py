#!/usr/bin/env python3
"""
Tuppi Emulator (4-player partnership) — CLI

Version: 1.9 (fix: duplicate @staticmethod; mac compatibility) (full-mode top-N move EV list) (human move-quality EV gap analysis) (post-deal EV analysis + study tools) (UI declutter + highlight; default rollouts=600; EV-based show) (fix: Rami lead tie bug + MC sampling fix) (fix: avoid double-counting current_trick in Monte Carlo sampling)

Implements:
- 52-card deck, no trumps
- 4 players, fixed partnerships (0&2 vs 1&3)
- Auction ("näyttö"): each player chooses one card face-down:
    * red card => RAMI, black => NOLO
    * reveal starts from forehand (left of dealer) clockwise
    * first revealed red sets RAMI declarer; further cards are not revealed
    * if no red revealed, contract is NOLO
  When using hand-cards for näyttö, this emulator enforces the common restriction:
    - you may not show with a 2 or a picture card (J/Q/K). If no suitable card
      exists for your intended color, you may declare verbally.
  (See e.g. Suomen Tuppiliitto "ei kuitenkaan kuvilla tai kakkosilla".)

- Play:
    * follow suit compulsory
    * highest of led suit wins (no trump)
    * In RAMI: leader to trick 1 is player RIGHT of declarer.
    * In NOLO: leader to trick 1 is forehand (left of dealer).

- Scoring (official rising mode by default):
    * RAMI: declarer side scores 4 points per trick above 6 if they take >=7.
            If declarer fails (<=6), defenders score 8 points per trick above 6.
    * NOLO: side with fewer tricks scores 4 points per trick missing from 7.
    * "Nousussa" scoring: only one side can have points at a time; if the
      non-rising side wins a hand (scores points), the game returns to 0–0.

AI:
- Three AI opponents (including your partner) using:
    * auction heuristics based on Rami Strength (RS) / Nolo Hand Index (NHI)
    * card play via one-ply Perfect-Information Monte Carlo (PIMC) with
      stochastic completions consistent with public info, and fast heuristic rollouts.
- No AI ever accesses other players' true hidden cards; it only uses its own
  hand + public history. (The engine knows all hands but does not leak them.)

Run:
    python tuppi_emulator.py

Options:
    python tuppi_emulator.py --human-seat 0 --rollouts 120 --flat-scoring

Notes:
- This is a faithful rules emulator with a strong (but not solved-optimal) AI.
  For equilibrium-level play you'd want CFR/ISMCTS training; this is a practical
  Monte Carlo + heuristic engine suitable for playing.

Author: ChatGPT
"""

from __future__ import annotations

import argparse
import math
import os
import random
import re
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Set, Tuple

# ----------------------------
# Card model
# ----------------------------

SUITS = ["♠", "♥", "♦", "♣"]
SUIT_CHARS = {"S": 0, "H": 1, "D": 2, "C": 3, "♠": 0, "♥": 1, "♦": 2, "♣": 3}
RANK_STR = {
    14: "A",
    13: "K",
    12: "Q",
    11: "J",
    10: "10",
    9: "9",
    8: "8",
    7: "7",
    6: "6",
    5: "5",
    4: "4",
    3: "3",
    2: "2",
}
STR_RANK = {
    "A": 14,
    "K": 13,
    "Q": 12,
    "J": 11,
    "10": 10,
    "9": 9,
    "8": 8,
    "7": 7,
    "6": 6,
    "5": 5,
    "4": 4,
    "3": 3,
    "2": 2,
}


# Encode card as int 0..51:
# card = suit*13 + (rank-2)  where rank in 2..14
def make_card(rank: int, suit: int) -> int:
    return suit * 13 + (rank - 2)


def card_rank(card: int) -> int:
    return (card % 13) + 2


def card_suit(card: int) -> int:
    return card // 13


def is_red(card: int) -> bool:
    return card_suit(card) in (1, 2)  # ♥ ♦


def card_str(card: int) -> str:
    return f"{RANK_STR[card_rank(card)]}{SUITS[card_suit(card)]}"


def short_card_str(card: int) -> str:
    # ASCII-friendly, e.g., AS, 10H, QD, 3C
    suit_letter = ["S", "H", "D", "C"][card_suit(card)]
    return f"{RANK_STR[card_rank(card)]}{suit_letter}"


def parse_card(token: str) -> Optional[int]:
    """
    Parse card from user input.
    Accepts e.g. "AS", "10H", "Qd", "7♠", "A♣".
    """
    token = token.strip()
    if not token:
        return None
    # normalize unicode suit to letter if present
    # Extract rank and suit
    m = re.match(r"^(10|[2-9AJQK])\s*([SHDC♠♥♦♣])$", token, re.IGNORECASE)
    if not m:
        return None
    r = m.group(1).upper()
    s = m.group(2).upper()
    rank = STR_RANK[r]
    suit = SUIT_CHARS[s]
    return make_card(rank, suit)


def sort_hand(hand: List[int]) -> List[int]:
    """
    Sort by suit (♠♥♦♣), then rank descending.
    """
    return sorted(hand, key=lambda c: (card_suit(c), -card_rank(c)))


# ----------------------------
# Contracts / Bidding
# ----------------------------


class Contract:
    RAMI = "RAMI"
    NOLO = "NOLO"


@dataclass(frozen=True)
class ShowBid:
    # Desired contract (RAMI or NOLO), decided privately at show selection time
    choice: str
    # The specific show card (if using a hand-card); None if verbal
    card: Optional[int]
    # True if the bid was verbal (no suitable card)
    verbal: bool = False


@dataclass
class ScoreState:
    rising: bool = True
    rising_team: Optional[int] = None  # 0,1 or None when "pöydässä"
    scores: Tuple[int, int] = (0, 0)  # (team0, team1)
    # Tournament-style totals (optional; tracked regardless)
    totals: Tuple[int, int] = (0, 0)


# ----------------------------
# Public observation handed to players (no hidden info)
# ----------------------------


@dataclass
class PublicState:
    contract: str
    declarer: Optional[int]  # seat index if RAMI; None if NOLO
    dealer: int
    leader: int  # seat to act first in current trick
    trick_index: int  # 0..12
    current_trick: List[Tuple[int, int]]  # list[(seat, card)] already played this trick
    played_cards: List[Tuple[int, int]]  # chronological all played cards
    tricks_won_by_team: Tuple[int, int]  # current tricks per team
    tricks_won_by_player: Tuple[int, int, int, int]
    revealed_show_cards: Dict[int, int]  # seat -> card (only those revealed)
    score_state: ScoreState

    def lead_suit(self) -> Optional[int]:
        if not self.current_trick:
            return None
        return card_suit(self.current_trick[0][1])


# ----------------------------
# Helper: teams
# ----------------------------


def team_of(seat: int) -> int:
    return 0 if seat % 2 == 0 else 1


# ----------------------------
# Metrics: RS (rami strength) and NHI (nolo hand index)
# ----------------------------


def hcp(hand: Sequence[int]) -> int:
    pts = 0
    for c in hand:
        r = card_rank(c)
        if r == 14:
            pts += 4
        elif r == 13:
            pts += 3
        elif r == 12:
            pts += 2
        elif r == 11:
            pts += 1
    return pts


def suit_lengths(hand: Sequence[int]) -> List[int]:
    lens = [0, 0, 0, 0]
    for c in hand:
        lens[card_suit(c)] += 1
    return lens


def rami_strength_RS(hand: Sequence[int]) -> float:
    H = hcp(hand)
    lens = suit_lengths(hand)
    ds_long = 0.5 * sum(max(0, l - 4) for l in lens)
    sci = sum((l - 3.25) ** 2 for l in lens)
    aces = sum(1 for c in hand if card_rank(c) == 14)
    return H + ds_long + 0.2 * sci + 0.5 * aces


def nolo_hand_index_NHI(hand: Sequence[int]) -> float:
    lens = suit_lengths(hand)
    v = sum(1 for l in lens if l == 0)
    s = sum(1 for l in lens if l == 1)
    d = sum(1 for l in lens if l == 2)
    L = max(lens)
    # quick counts
    T5 = sum(1 for c in hand if card_rank(c) >= 10)  # 10,J,Q,K,A
    H4 = sum(1 for c in hand if card_rank(c) >= 11)  # J,Q,K,A
    E = sum(1 for c in hand if card_rank(c) in (2, 3, 4))
    return 2 * T5 + 1 * H4 - 1.5 * E - 3 * v - 2 * s - 1 * d + 0.5 * max(0, L - 5)


def sigmoid(x: float) -> float:
    # stable
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    else:
        z = math.exp(x)
        return z / (1.0 + z)


def approx_P_rami_make(rs: float) -> float:
    # logistic fit to earlier RS->P(>=7) table: center ~15.34, scale ~3.48
    return sigmoid((rs - 15.34) / 3.48)


def approx_P_nolo_win(nhi: float) -> float:
    # lower NHI better. A practical mapping; calibrate roughly:
    # NHI=6 -> ~0.65, NHI=10 -> ~0.5, NHI=14 -> ~0.35
    return sigmoid((9.8 - nhi) / 2.8)


# ---- Approximate EV for contract choice (show decision) ----
# We use a lightweight Binomial(13,p) abstraction to translate hand metrics into:
#   - P(make RAMI) = P(T>=7)
#   - P(win NOLO)  = P(T<=6)
# then derive approximate EV using the actual scoring tables.
# This is intentionally conservative to avoid overcalling RAMI.

_NTRICKS = 13
_BINOM_COEF_13 = [math.comb(_NTRICKS, k) for k in range(_NTRICKS + 1)]


def _binom_pmf_13(k: int, p: float) -> float:
    return _BINOM_COEF_13[k] * (p**k) * ((1 - p) ** (_NTRICKS - k))


def _binom_cdf_13(k: int, p: float) -> float:
    # P(T <= k)
    return sum(_binom_pmf_13(i, p) for i in range(k + 1))


def _solve_p_for_cdf6(q: float) -> float:
    """
    Find p in (0,1) such that Binomial(13,p) CDF at 6 equals q.
    Monotone decreasing in p.
    """
    q = min(max(q, 1e-6), 1 - 1e-6)
    lo, hi = 1e-4, 1 - 1e-4
    for _ in range(40):
        mid = (lo + hi) / 2
        c = _binom_cdf_13(6, mid)
        if c < q:
            # p too high (CDF too small)
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def _solve_p_for_tail_ge7(q: float) -> float:
    """
    Find p such that P(T>=7) = q  <=>  CDF(6)=1-q.
    """
    q = min(max(q, 1e-6), 1 - 1e-6)
    target = 1 - q
    lo, hi = 1e-4, 1 - 1e-4
    for _ in range(40):
        mid = (lo + hi) / 2
        c = _binom_cdf_13(6, mid)
        if c > target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def approx_EV_rami_from_RS(rs: float) -> float:
    """
    Approximate EV for the declarer TEAM if this player becomes RAMI declarer,
    using P(make) derived from RS and a Binomial trick-share model.
    """
    q_make = approx_P_rami_make(rs)  # P(T>=7)
    p = _solve_p_for_tail_ge7(q_make)
    ev = 0.0
    for t in range(0, 14):
        prob = _binom_pmf_13(t, p)
        if t >= 7:
            s = 4 * (t - 6)
        else:
            s = -8 * (7 - t)
        ev += prob * s
    return ev


def approx_EV_nolo_from_NHI(nhi: float) -> float:
    """
    Approximate EV for the TEAM (your partnership) in NOLO, using P(win) from NHI.
    """
    q_win = approx_P_nolo_win(nhi)  # P(T<=6)
    p = _solve_p_for_cdf6(q_win)
    ev = 0.0
    for t in range(0, 14):
        prob = _binom_pmf_13(t, p)
        if t <= 6:
            s = 4 * (7 - t)
        else:
            s = -4 * (t - 6)
        ev += prob * s
    return ev


def approx_p_team_rami(rs: float) -> float:
    """Binomial trick-share parameter p for team tricks in RAMI, derived from RS->P(make)."""
    q_make = approx_P_rami_make(rs)
    return _solve_p_for_tail_ge7(q_make)


def approx_p_team_nolo(nhi: float) -> float:
    """Binomial trick-share parameter p for team tricks in NOLO, derived from NHI->P(win)."""
    q_win = approx_P_nolo_win(nhi)
    return _solve_p_for_cdf6(q_win)


def hand_feature_summary(hand: Sequence[int]) -> Dict[str, object]:
    lens = suit_lengths(hand)
    h = hcp(hand)
    top5 = sum(1 for c in hand if card_rank(c) >= 10)
    exits = sum(1 for c in hand if card_rank(c) in (2, 3, 4))
    voids = sum(1 for l in lens if l == 0)
    singles = sum(1 for l in lens if l == 1)
    doubles = sum(1 for l in lens if l == 2)
    return {
        "lens": lens,
        "hcp": h,
        "top5": top5,
        "exits": exits,
        "voids": voids,
        "singles": singles,
        "doubles": doubles,
        "RS": rami_strength_RS(hand),
        "NHI": nolo_hand_index_NHI(hand),
    }


# ----------------------------
# Legal moves
# ----------------------------


def legal_moves(hand: Sequence[int], lead_suit: Optional[int]) -> List[int]:
    if lead_suit is None:
        return list(hand)
    suited = [c for c in hand if card_suit(c) == lead_suit]
    return suited if suited else list(hand)


# ----------------------------
# Trick evaluation
# ----------------------------


def trick_winner(trick: List[Tuple[int, int]]) -> int:
    """
    trick: list[(seat, card)] in play order.
    Returns seat index of trick winner (highest rank in lead suit).
    """
    lead = card_suit(trick[0][1])
    best_seat, best_card = trick[0]
    best_rank = card_rank(best_card)
    for seat, card in trick[1:]:
        if card_suit(card) != lead:
            continue
        r = card_rank(card)
        if r > best_rank:
            best_rank = r
            best_seat, best_card = seat, card
    return best_seat


# ----------------------------
# Scoring
# ----------------------------


def score_deal(
    contract: str, declarer: Optional[int], tricks_team0: int, tricks_team1: int
) -> Tuple[int, int]:
    """
    Returns (winner_team, points_awarded_to_winner).
    """
    if contract == Contract.RAMI:
        assert declarer is not None
        dec_team = team_of(declarer)
        T_dec = tricks_team0 if dec_team == 0 else tricks_team1
        T_def = 13 - T_dec
        if T_dec >= 7:
            pts = 4 * (T_dec - 6)
            return dec_team, pts
        else:
            # stolen rami: defenders score double
            pts = 8 * (T_def - 6)  # >=8
            return 1 - dec_team, pts

    # NOLO
    if tricks_team0 < tricks_team1:
        min_tricks = tricks_team0
        pts = 4 * (7 - min_tricks)
        return 0, pts
    else:
        min_tricks = tricks_team1
        pts = 4 * (7 - min_tricks)
        return 1, pts


def utility_from_outcome(
    score_state: ScoreState, my_team: int, winner_team: int, points: int
) -> float:
    """
    Utility used inside Monte Carlo evaluation.
    Encodes "nousussa" risk: losing while rising destroys accumulated score.
    """
    if not score_state.rising:
        return points if winner_team == my_team else -points

    rising_team = score_state.rising_team
    t0, t1 = score_state.scores
    my_score = t0 if my_team == 0 else t1
    opp_score = t1 if my_team == 0 else t0

    if rising_team is None:
        # table: winner starts rising
        return points if winner_team == my_team else -points

    if rising_team == my_team:
        # we are rising: win adds points; loss resets us to 0
        return points if winner_team == my_team else -my_score

    # opponents rising
    if winner_team == my_team:
        # by winning, we knock them back to table (their score disappears)
        return opp_score
    else:
        # they extend their rise
        return -points


# ----------------------------
# Players
# ----------------------------


class Player:
    def __init__(self, seat: int, name: str):
        self.seat = seat
        self.name = name
        self.hand: List[int] = []

    def set_hand(self, cards: List[int]) -> None:
        self.hand = sort_hand(cards)

    def choose_show_bid(
        self, dealer: int, score_state: ScoreState, show_banned_ranks: Set[int]
    ) -> ShowBid:
        raise NotImplementedError

    def choose_play_card(self, pub: PublicState, show_banned_ranks: Set[int]) -> int:
        raise NotImplementedError


# ----------------------------
# Human player
# ----------------------------


class HumanPlayer(Player):
    def __init__(self, seat: int, name: str = "You"):
        super().__init__(seat, name)

    def choose_show_bid(
        self, dealer: int, score_state: ScoreState, show_banned_ranks: Set[int]
    ) -> ShowBid:
        print("\n=== SHOW (NÄYTTÖ) ===")
        print(f"Dealer: {dealer_name(dealer)}. You are {dealer_name(self.seat)}.")
        print("Choose ONE show card (not 2/J/Q/K by default).")
        print("Red (♥♦) -> RAMI ; Black (♠♣) -> NOLO.")
        print(
            "If you truly have no legal card of the desired color, you may type 'R' or 'N' to declare verbally."
        )
        print_hand(self.hand)

        legal_show = [c for c in self.hand if card_rank(c) not in show_banned_ranks]
        legal_red = [c for c in legal_show if is_red(c)]
        legal_black = [c for c in legal_show if not is_red(c)]

        if legal_red:
            print(
                "Legal red show cards:",
                ", ".join(card_str(c) for c in sorted(legal_red, key=card_rank)),
            )
        else:
            print("Legal red show cards: (none)")
        if legal_black:
            print(
                "Legal black show cards:",
                ", ".join(card_str(c) for c in sorted(legal_black, key=card_rank)),
            )
        else:
            print("Legal black show cards: (none)")

        while True:
            s = input("Show card (e.g., 7H, 9S, QD) or 'R'/'N': ").strip().upper()
            if s in ("R", "RAMI"):
                return ShowBid(choice=Contract.RAMI, card=None, verbal=True)
            if s in ("N", "NOLO"):
                return ShowBid(choice=Contract.NOLO, card=None, verbal=True)
            c = parse_card(s)
            if c is None:
                print("Could not parse. Try e.g. 10H, AS, 7D, 9C.")
                continue
            if c not in self.hand:
                print("You don't have that card.")
                continue
            if card_rank(c) in show_banned_ranks:
                print(
                    "That rank is not allowed for showing (by current rules). Choose another or declare verbally if needed."
                )
                continue
            # OK
            return ShowBid(
                choice=Contract.RAMI if is_red(c) else Contract.NOLO,
                card=c,
                verbal=False,
            )

    def choose_play_card(self, pub: PublicState, show_banned_ranks: Set[int]) -> int:
        # Display state
        contract = pub.contract
        lead = pub.lead_suit()
        print(f"\n--- Trick {pub.trick_index + 1}/13 | Contract: {contract} ---")
        print(f"Leader: {dealer_name(pub.leader)}")
        if pub.declarer is not None:
            print(
                f"Declarer: {dealer_name(pub.declarer)} (Team {team_of(pub.declarer)})"
            )
        t0, t1 = pub.tricks_won_by_team
        print(
            f"Tricks: Team0({dealer_name(0)}+{dealer_name(2)})={t0}  "
            f"Team1({dealer_name(1)}+{dealer_name(3)})={t1}"
        )

        if pub.current_trick:
            win_p, win_c = _partial_trick_winner(pub.current_trick)
            parts = []
            for p, c in pub.current_trick:
                cs = card_str(c)
                if p == win_p:
                    cs = _style(cs, "win")
                parts.append(f"{dealer_name(p)}:{cs}")
            played = " | ".join(parts)
            print(f"Current trick: {played}")
            print(f"Led suit: {SUITS[lead] if lead is not None else '-'}")

        # Legal cards
        lm = legal_moves(self.hand, lead)
        lm_sorted = sorted(lm, key=lambda c: (card_suit(c), card_rank(c)))
        print_hand(self.hand, highlight=lm_sorted)

        # Optional hint: type "H"
        while True:
            s = input("Play card (e.g., 4S, 10D) or '?' for hint: ").strip().upper()
            if s in ("?", "H", "HINT"):
                # Provide a hint using the same AI engine (from player's perspective).
                # This does NOT reveal hidden information; it is based only on public state + your hand.
                hint = MonteCarloAdvisor(rollouts=600).recommend_card_for_human(
                    self.hand, pub
                )
                print(f"Hint suggests: {card_str(hint)}")
                continue
            c = parse_card(s)
            if c is None:
                print("Could not parse. Try e.g. 10H, AS, 7D, 9C.")
                continue
            if c not in self.hand:
                print("You don't have that card.")
                continue
            if c not in lm:
                print("Illegal: you must follow suit if you can.")
                continue
            return c


# ----------------------------
# AI players
# ----------------------------


class HeuristicPolicy:
    """
    Fast, local policy used for rollouts (and as a fallback when rollouts=0).
    Uses only own hand + public trick context.
    """

    @staticmethod
    def choose_show_bid(
        hand: Sequence[int],
        seat: int,
        score_state: ScoreState,
        show_banned_ranks: Set[int],
    ) -> ShowBid:
        rs = rami_strength_RS(hand)
        nhi = nolo_hand_index_NHI(hand)

        # Risk-aware thresholding in rising mode: protect a big rise.
        base_thr = 17.0
        if score_state.rising and score_state.rising_team == team_of(seat):
            # if we are rising, be a bit more conservative near winning line
            my_score = score_state.scores[team_of(seat)]
            if my_score >= 40:
                base_thr += 1.0

        # Decide RAMI vs NOLO (black) using approximate EV.
        # Key point: RAMI has an asymmetric downside (stolen RAMI pays double to defenders),
        # so we require a clearly positive EV margin before showing red.
        ev_rami = approx_EV_rami_from_RS(rs)
        ev_nolo = approx_EV_nolo_from_NHI(nhi)

        # Conservative baseline: require ~+4 deal points EV to call RAMI.
        # Adjust for "nousussa" risk:
        # - if we are rising high, raise the bar (avoid catastrophic reset)
        # - if opponents are rising high, lower it slightly (gamble to reset them)
        rami_ev_min = 4.0
        if not score_state.rising:
            rami_ev_min = 3.0
        else:
            if score_state.rising_team is not None:
                if score_state.rising_team == team_of(seat):
                    my_score = score_state.scores[team_of(seat)]
                    if my_score >= 40:
                        rami_ev_min = 6.0
                else:
                    opp_score = score_state.scores[score_state.rising_team]
                    if opp_score >= 40:
                        rami_ev_min = 3.0

        # Small margin to prefer NOLO when close (conventionally correct).
        margin = 0.5
        if ev_rami >= rami_ev_min and ev_rami > ev_nolo + margin:
            choice = Contract.RAMI
        else:
            choice = Contract.NOLO

        # Choose a minimally-informative show card of correct color if possible.
        legal_show = [c for c in hand if card_rank(c) not in show_banned_ranks]
        if choice == Contract.RAMI:
            options = [c for c in legal_show if is_red(c)]
        else:
            options = [c for c in legal_show if not is_red(c)]
        if options:
            # reveal the lowest allowed rank in that color (min information)
            card = min(options, key=lambda c: card_rank(c))
            return ShowBid(choice=choice, card=card, verbal=False)
        else:
            return ShowBid(choice=choice, card=None, verbal=True)

    @staticmethod
    def choose_play_card(hand: Sequence[int], pub: PublicState, seat: int) -> int:
        contract = pub.contract
        lead = pub.lead_suit()
        lm = legal_moves(hand, lead)

        # Nolo heuristics (misère)
        if contract == Contract.NOLO:
            return HeuristicPolicy._play_nolo(hand, lm, pub, seat)

        # Rami heuristics (maximize tricks for your team)
        return HeuristicPolicy._play_rami(hand, lm, pub, seat)

    @staticmethod
    def _play_nolo(
        hand: Sequence[int], lm: List[int], pub: PublicState, seat: int
    ) -> int:
        lead = pub.lead_suit()
        my_team = team_of(seat)
        t0, t1 = pub.tricks_won_by_team
        my_tricks = t0 if my_team == 0 else t1

        # If leading: play absolute lowest, but avoid leading A/K/Q/J/10 if possible.
        if lead is None:
            # Prefer exits (2-4), else low card.
            exits = [c for c in lm if card_rank(c) in (2, 3, 4)]
            if exits:
                # accelerate voids only when rank low
                return min(
                    exits, key=lambda c: (card_rank(c), suit_lengths_for_card(hand, c))
                )
            # otherwise choose lowest rank; tie-break toward shortest suit
            return min(lm, key=lambda c: (card_rank(c), suit_lengths_for_card(hand, c)))

        # Following suit
        current_high = max(
            (card_rank(c) for p, c in pub.current_trick if card_suit(c) == lead),
            default=0,
        )
        # Try to lose: highest losing
        losing = [c for c in lm if card_suit(c) == lead and card_rank(c) < current_high]
        if losing:
            return max(losing, key=card_rank)

        # Forced to potentially win in suit
        pos_in_trick = len(pub.current_trick)  # 0-based before play
        is_last = pos_in_trick == 3
        suited = [c for c in lm if card_suit(c) == lead]

        if suited:
            if is_last:
                # if forced to win, purge high (classic)
                return max(suited, key=card_rank)
            else:
                # lowest winning to allow later overtakes
                return min(suited, key=card_rank)

        # Void (shouldn't happen because lm includes all)
        return HeuristicPolicy._nolo_discard_any(hand)

    @staticmethod
    def _nolo_discard_any(hand: Sequence[int]) -> int:
        """
        When void in the led suit (cannot follow), discard to reduce future forced wins.
        Priority: shed high liabilities first; tie-break toward creating/strengthening voids.
        """

        def liab(c: int) -> float:
            r = card_rank(c)
            if r == 14:
                return 4.0
            if r == 13:
                return 3.0
            if r == 12:
                return 2.0
            if r == 11:
                return 1.0
            if r == 10:
                return 0.5
            if r == 9:
                return 0.25
            return 0.0

        lens = suit_lengths(hand)

        def score(c: int) -> Tuple[float, int, int]:
            short_bonus = 1 if lens[card_suit(c)] <= 2 else 0
            # Higher is better for discarding: high liability + short-suit bonus + high rank
            return (liab(c), short_bonus, card_rank(c))

        return max(hand, key=score)

    @staticmethod
    def _play_rami(
        hand: Sequence[int], lm: List[int], pub: PublicState, seat: int
    ) -> int:
        lead = pub.lead_suit()
        my_team = team_of(seat)

        if lead is None:
            # Lead from the best available suit (honor weight + length bonus).
            # IMPORTANT: restrict to suits actually present in hand to avoid empty-candidate bugs in late endgames.
            lens = suit_lengths(hand)
            suits_in_hand = [s for s in range(4) if lens[s] > 0]
            if not suits_in_hand:
                # Should not happen (no cards), but keep robust.
                return lm[0] if lm else None

            def suit_strength(s: int) -> float:
                w = 0.0
                for c in hand:
                    if card_suit(c) != s:
                        continue
                    r = card_rank(c)
                    if r == 14:
                        w += 4
                    elif r == 13:
                        w += 3
                    elif r == 12:
                        w += 2
                    elif r == 11:
                        w += 1
                # Length bonus: prefer longer suits for establishing tricks
                w += 0.5 * max(0, lens[s] - 3)
                # Tiny base breaks all-zero ties without selecting empty suits
                w += 0.01 * lens[s]
                return w

            best_suit = max(suits_in_hand, key=lambda s: (suit_strength(s), lens[s]))
            candidates = [c for c in hand if card_suit(c) == best_suit]
            return max(candidates, key=card_rank)
        # Following suit: win with lowest winning if possible; else dump lowest
        current_high = max(
            (card_rank(c) for p, c in pub.current_trick if card_suit(c) == lead),
            default=0,
        )
        suited = [c for c in lm if card_suit(c) == lead]
        winning = [c for c in suited if card_rank(c) > current_high]
        if winning:
            return min(winning, key=card_rank)
        if suited:
            return min(suited, key=card_rank)
        # Void: discard lowest overall
        return min(lm, key=card_rank)


def suit_lengths_for_card(hand: Sequence[int], card: int) -> int:
    # used as tie-break: prefer shortest suit
    lens = suit_lengths(hand)
    return lens[card_suit(card)]


class MonteCarloAI(Player):
    def __init__(self, seat: int, name: str, rollouts: int = 1200):
        super().__init__(seat, name)
        self.rollouts = rollouts

    def choose_show_bid(
        self, dealer: int, score_state: ScoreState, show_banned_ranks: Set[int]
    ) -> ShowBid:
        return HeuristicPolicy.choose_show_bid(
            self.hand, self.seat, score_state, show_banned_ranks
        )

    def choose_play_card(self, pub: PublicState, show_banned_ranks: Set[int]) -> int:
        # If only one legal move, play it
        lead = pub.lead_suit()
        lm = legal_moves(self.hand, lead)
        if len(lm) == 1:
            return lm[0]
        if self.rollouts <= 0:
            return HeuristicPolicy.choose_play_card(self.hand, pub, self.seat)

        # Evaluate each move with rollouts
        best_card = None
        best_val = -1e18
        # small random shuffle to break ties
        cand = lm[:]
        random.shuffle(cand)
        for c in cand:
            v = self._estimate_value(pub, c)
            if v > best_val:
                best_val = v
                best_card = c
        assert best_card is not None
        return best_card

    def _estimate_value(self, pub: PublicState, first_card: int) -> float:
        """
        One-ply PIMC:
        - Sample completions consistent with public info and our hand.
        - For each completion, force first_card, then rollout with heuristic policy.
        - Return mean utility for our team.
        """
        my_team = team_of(self.seat)
        # Public known cards: played + revealed show cards (that are not played yet)
        played_set = {c for _, c in pub.played_cards}
        # Include current trick already played
        played_set |= {c for _, c in pub.current_trick}

        # Fixed known cards by player (from revealed show cards), if not played yet
        fixed_by_player: Dict[int, List[int]] = {i: [] for i in range(4)}
        for p, c in pub.revealed_show_cards.items():
            if c not in played_set:
                fixed_by_player[p].append(c)

        # Remaining counts per player
        # Each player has 13 total; subtract how many they've already played.
        played_count = [0, 0, 0, 0]
        # NOTE: pub.played_cards already includes cards in pub.current_trick (engine appends every play).
        # Do NOT double-count current_trick here, or sampled hands become too small and may empty early.
        for p, _ in pub.played_cards:
            played_count[p] += 1
        remaining_count = [13 - played_count[p] for p in range(4)]

        # Unknown pool: all cards minus (our hand) minus played minus fixed known of others
        all_cards = set(range(52))
        fixed_cards = set()
        for p in range(4):
            if p == self.seat:
                continue
            for c in fixed_by_player[p]:
                fixed_cards.add(c)

        # Ensure we don't treat our own revealed show card as fixed for others
        # (it's already in our hand)
        unknown_pool = list(all_cards - played_set - set(self.hand) - fixed_cards)
        # sanity
        if len(unknown_pool) < 0:
            unknown_pool = []

        total_utility = 0.0
        N = self.rollouts

        # Precompute order-of-play for speed
        for _ in range(N):
            # sample hands for other players
            pool = unknown_pool[:]
            random.shuffle(pool)

            hands: Dict[int, List[int]] = {i: [] for i in range(4)}
            hands[self.seat] = list(self.hand)  # copy

            # assign fixed known cards to others first
            for p in range(4):
                if p == self.seat:
                    continue
                hands[p] = list(fixed_by_player[p])

            # now fill remaining
            idx = 0
            for p in range(4):
                if p == self.seat:
                    continue
                need = remaining_count[p] - len(hands[p])
                if need < 0:
                    need = 0
                if idx + need > len(pool):
                    need = max(0, len(pool) - idx)
                hands[p].extend(pool[idx : idx + need])
                idx += need

            # Simulate to end (starting from pub state, forcing first_card)
            util = simulate_from_state(pub, hands, self.seat, first_card, my_team)
            total_utility += util

        return total_utility / max(1, N)


# ----------------------------
# Monte Carlo advisor for human hints (same logic as AI, but never sees hidden cards)
# ----------------------------


class MonteCarloAdvisor:
    def __init__(self, rollouts: int = 120):
        self.rollouts = rollouts

    def recommend_card_for_human(self, hand: Sequence[int], pub: PublicState) -> int:
        lead = pub.lead_suit()
        lm = legal_moves(hand, lead)
        if len(lm) == 1:
            return lm[0]
        if self.rollouts <= 0:
            return HeuristicPolicy.choose_play_card(
                hand, pub, seat=-1
            )  # seat not used in heuristic rami much

        # Evaluate each move with rollouts from the human seat (pub data has no "self seat" here)
        # We infer "self seat" as the one whose turn it is (not encoded explicitly);
        # since this is called inside HumanPlayer on their turn, we can find it:
        seat = infer_turn_seat(pub)
        my_team = team_of(seat)

        # Build a temporary MonteCarloAI-like evaluation with this hand
        best_c, best_v = None, -1e18
        cand = lm[:]
        random.shuffle(cand)
        for c in cand:
            v = estimate_value_generic(pub, hand, seat, my_team, c, self.rollouts)
            if v > best_v:
                best_v = v
                best_c = c
        return best_c if best_c is not None else lm[0]


def infer_turn_seat(pub: PublicState) -> int:
    # turn seat is the next seat in clockwise order after last in current_trick, or leader if empty.
    if not pub.current_trick:
        return pub.leader
    last_seat = pub.current_trick[-1][0]
    return (last_seat + 1) % 4


def estimate_value_generic(
    pub: PublicState,
    my_hand: Sequence[int],
    my_seat: int,
    my_team: int,
    first_card: int,
    rollouts: int,
) -> float:
    played_set = {c for _, c in pub.played_cards}
    played_set |= {c for _, c in pub.current_trick}

    fixed_by_player: Dict[int, List[int]] = {i: [] for i in range(4)}
    for p, c in pub.revealed_show_cards.items():
        if c not in played_set:
            fixed_by_player[p].append(c)

    played_count = [0, 0, 0, 0]
    # NOTE: pub.played_cards already includes cards in pub.current_trick (engine appends every play).
    # Do NOT double-count current_trick here, or sampled hands become too small and may empty early.
    for p, _ in pub.played_cards:
        played_count[p] += 1
    remaining_count = [13 - played_count[p] for p in range(4)]

    all_cards = set(range(52))
    fixed_cards = set()
    for p in range(4):
        if p == my_seat:
            continue
        for c in fixed_by_player[p]:
            fixed_cards.add(c)

    unknown_pool = list(all_cards - played_set - set(my_hand) - fixed_cards)
    total_utility = 0.0
    N = rollouts

    for _ in range(N):
        pool = unknown_pool[:]
        random.shuffle(pool)
        hands: Dict[int, List[int]] = {i: [] for i in range(4)}
        hands[my_seat] = list(my_hand)
        for p in range(4):
            if p == my_seat:
                continue
            hands[p] = list(fixed_by_player[p])

        idx = 0
        for p in range(4):
            if p == my_seat:
                continue
            need = remaining_count[p] - len(hands[p])
            if need < 0:
                need = 0
            if idx + need > len(pool):
                need = max(0, len(pool) - idx)
            hands[p].extend(pool[idx : idx + need])
            idx += need

        total_utility += simulate_from_state(pub, hands, my_seat, first_card, my_team)

    return total_utility / max(1, N)


# ----------------------------
# Simulation for Monte Carlo evaluation
# ----------------------------


def simulate_from_state(
    pub: PublicState,
    hands: Dict[int, List[int]],
    seat_to_force: int,
    forced_card: int,
    my_team: int,
) -> float:
    """
    Simulate from current public state to end of deal under a full sampled completion.
    - hands: remaining cards for each player at this point.
    - forced_card: the card seat_to_force will play now.
    Uses HeuristicPolicy for all subsequent decisions.
    Returns utility for my_team based on score_state.
    """
    # Clone state variables
    contract = pub.contract
    declarer = pub.declarer
    dealer = pub.dealer
    leader = pub.leader
    trick_index = pub.trick_index
    current_trick = list(pub.current_trick)
    played_cards = list(pub.played_cards)

    tricks_won_by_player = list(pub.tricks_won_by_player)
    t0, t1 = pub.tricks_won_by_team

    # Determine turn seat
    turn_seat = infer_turn_seat(pub)
    assert turn_seat == seat_to_force, (
        "simulate_from_state called not on forced player's turn"
    )

    # Play forced card (must be legal in this sampled hand)
    lead_suit = pub.lead_suit()
    lm = legal_moves(hands[seat_to_force], lead_suit)
    if forced_card not in lm:
        # if somehow illegal in sampled completion, fall back to a legal move to avoid crashes
        forced_card = lm[0]
    hands[seat_to_force].remove(forced_card)
    current_trick.append((seat_to_force, forced_card))
    played_cards.append((seat_to_force, forced_card))

    # Continue current trick until 4 cards
    while len(current_trick) < 4:
        next_seat = (current_trick[-1][0] + 1) % 4
        lead_suit_now = card_suit(current_trick[0][1])
        lm2 = legal_moves(hands[next_seat], lead_suit_now)
        # build a minimal public view for the heuristic (only needs current trick + counts)
        sim_pub = PublicState(
            contract=contract,
            declarer=declarer,
            dealer=dealer,
            leader=leader,
            trick_index=trick_index,
            current_trick=list(current_trick),
            played_cards=list(played_cards),
            tricks_won_by_team=(t0, t1),
            tricks_won_by_player=tuple(tricks_won_by_player),
            revealed_show_cards=pub.revealed_show_cards,
            score_state=pub.score_state,
        )
        c = HeuristicPolicy.choose_play_card(hands[next_seat], sim_pub, next_seat)
        if c not in lm2:
            # enforce legality if heuristic picked illegal (should be rare)
            c = lm2[0]
        hands[next_seat].remove(c)
        current_trick.append((next_seat, c))
        played_cards.append((next_seat, c))

    # Score the trick
    win_seat = trick_winner(current_trick)
    win_team = team_of(win_seat)
    tricks_won_by_player[win_seat] += 1
    if win_team == 0:
        t0 += 1
    else:
        t1 += 1
    leader = win_seat
    trick_index += 1
    current_trick = []

    # Play remaining tricks
    while trick_index < 13:
        # leader leads
        lead_seat = leader
        # play 4 cards
        trick: List[Tuple[int, int]] = []
        for offset in range(4):
            p = (lead_seat + offset) % 4
            lead_suit_now = card_suit(trick[0][1]) if trick else None
            lm_p = legal_moves(hands[p], lead_suit_now)
            sim_pub = PublicState(
                contract=contract,
                declarer=declarer,
                dealer=dealer,
                leader=lead_seat,
                trick_index=trick_index,
                current_trick=list(trick),
                played_cards=list(played_cards),
                tricks_won_by_team=(t0, t1),
                tricks_won_by_player=tuple(tricks_won_by_player),
                revealed_show_cards=pub.revealed_show_cards,
                score_state=pub.score_state,
            )
            c = HeuristicPolicy.choose_play_card(hands[p], sim_pub, p)
            if c not in lm_p:
                c = lm_p[0]
            hands[p].remove(c)
            trick.append((p, c))
            played_cards.append((p, c))

        win_seat = trick_winner(trick)
        win_team = team_of(win_seat)
        tricks_won_by_player[win_seat] += 1
        if win_team == 0:
            t0 += 1
        else:
            t1 += 1
        leader = win_seat
        trick_index += 1

    # Deal outcome
    winner_team, pts = score_deal(contract, declarer, t0, t1)
    return utility_from_outcome(pub.score_state, my_team, winner_team, pts)


# ----------------------------
# Printing helpers
# ----------------------------

# Terminal styling (ANSI) — used purely for readability.
# If output is not a TTY or NO_COLOR is set, falls back to bracket markers.
_ANSI_OK = sys.stdout.isatty() and os.getenv("NO_COLOR") is None


def _style(text: str, kind: str) -> str:
    if not _ANSI_OK:
        if kind == "win":
            return f"[{text}]"
        if kind == "you":
            return f"<{text}>"
        if kind == "lead":
            return f"({text})"
        return text
    if kind == "win":
        return f"\033[1;92m{text}\033[0m"  # bold green
    if kind == "you":
        return f"\033[1;96m{text}\033[0m"  # bold cyan
    if kind == "lead":
        return f"\033[1;93m{text}\033[0m"  # bold yellow
    return text


def _partial_trick_winner(trick: List[Tuple[int, int]]) -> Tuple[int, int]:
    """
    Winner so far in an incomplete trick.
    Returns (seat, card) of current winning play (highest in led suit).
    """
    assert trick, "empty trick"
    lead = card_suit(trick[0][1])
    best_seat, best_card = trick[0]
    best_rank = card_rank(best_card)
    for seat, card in trick[1:]:
        if card_suit(card) != lead:
            continue
        r = card_rank(card)
        if r > best_rank:
            best_rank = r
            best_seat, best_card = seat, card
    return best_seat, best_card


def dealer_name(seat: int) -> str:
    return ["P0", "P1", "P2", "P3"][seat]


def print_hand(hand: Sequence[int], highlight: Optional[Sequence[int]] = None) -> None:
    """
    Print hand grouped by suit with ranks.
    Optionally highlight a subset (legal moves) by prefixing '*'.
    """
    highlight_set = set(highlight) if highlight is not None else set()
    by_suit: Dict[int, List[int]] = {s: [] for s in range(4)}
    for c in hand:
        by_suit[card_suit(c)].append(c)
    out_lines = []
    for s in range(4):
        cards = sorted(by_suit[s], key=lambda c: -card_rank(c))
        parts = []
        for c in cards:
            mark = "*" if c in highlight_set else " "
            parts.append(f"{mark}{RANK_STR[card_rank(c)]}")
        out_lines.append(f"{SUITS[s]}: " + " ".join(parts))
    print("Your hand:" if highlight is None else "Your hand (legal marked '*'):")
    for ln in out_lines:
        print("  " + ln)


# ----------------------------
# Game engine
# ----------------------------


class TuppiGame:
    def __init__(
        self,
        human_seat: int = 0,
        rollouts: int = 600,
        rising_scoring: bool = True,
        seed: Optional[int] = None,
        show_banned_ranks: Optional[Set[int]] = None,
        analysis_level: str = "basic",
        analysis_move_rollouts: Optional[int] = None,
        analysis_topn: int = 3,
    ):
        if seed is not None:
            random.seed(seed)

        self.show_banned_ranks = show_banned_ranks or {2, 11, 12, 13}  # 2,J,Q,K
        self.analysis_level = analysis_level
        self.analysis_move_rollouts = analysis_move_rollouts
        self.analysis_topn = max(1, int(analysis_topn))

        self.score_state = ScoreState(
            rising=rising_scoring, rising_team=None, scores=(0, 0), totals=(0, 0)
        )
        self.dealer = 0

        # Build players
        self.players: List[Player] = []
        for seat in range(4):
            if seat == human_seat:
                self.players.append(HumanPlayer(seat))
            else:
                self.players.append(
                    MonteCarloAI(seat, name=dealer_name(seat), rollouts=rollouts)
                )

    def run(self) -> None:
        print("\n=== TU P P I  (4-player partnership) ===")
        print("Seats: P0 P1 P2 P3 clockwise. Partnerships: Team0=P0+P2 vs Team1=P1+P3.")
        print(
            f"Scoring mode: {'RISING (nousussa)' if self.score_state.rising else 'FLAT (both can score)'}"
        )
        print(f"AI rollouts per decision: {self._ai_rollouts()}")
        print(
            "Show (näyttö) restriction: cannot show with ranks:",
            ", ".join(RANK_STR[r] for r in sorted(self.show_banned_ranks)),
        )
        print("Type '?' at your play prompt for a hint.\n")

        hand_no = 0
        while True:
            hand_no += 1
            print(f"\n================= HAND {hand_no} =================")
            self.play_one_hand()
            w = self.check_winner()
            if w is not None:
                print(f"\n*** GAME OVER: Team {w} wins! ***")
                print(self.scoreboard_str(final=True))
                break
            self.dealer = (self.dealer + 1) % 4

    def _ai_rollouts(self) -> int:
        for p in self.players:
            if isinstance(p, MonteCarloAI):
                return p.rollouts
        return 0

    def check_winner(self) -> Optional[int]:
        t0, t1 = self.score_state.scores
        if self.score_state.rising:
            if (
                self.score_state.rising_team is not None
                and self.score_state.scores[self.score_state.rising_team] >= 52
            ):
                return self.score_state.rising_team
            return None
        else:
            if t0 >= 52 and t1 >= 52:
                return 0 if t0 >= t1 else 1
            if t0 >= 52:
                return 0
            if t1 >= 52:
                return 1
            return None

    def scoreboard_str(self, final: bool = False) -> str:
        t0, t1 = self.score_state.scores
        rising = self.score_state.rising_team
        mode = "RISING" if self.score_state.rising else "FLAT"
        s = f"[{mode}] Score Team0={t0}  Team1={t1}"
        if rising is None:
            s += "  (pöydässä)"
        else:
            s += f"  (nousussa: Team{rising})"
        if not self.score_state.rising:
            return s
        # show totals for interest
        tot0, tot1 = self.score_state.totals
        if final:
            s += f"\nTournament-style totals (for reference): Team0={tot0} Team1={tot1}"
        return s

    def play_one_hand(self) -> None:
        # Snapshot score state at start of deal (for post-mortem bidding evaluation)
        score_state_before = ScoreState(
            rising=self.score_state.rising,
            rising_team=self.score_state.rising_team,
            scores=self.score_state.scores,
            totals=self.score_state.totals,
        )

        # Human move log for post-deal move-quality analysis
        human_move_log: List[Dict[str, object]] = []

        # Deal
        deck = list(range(52))
        random.shuffle(deck)
        hands = [sort_hand(deck[i * 13 : (i + 1) * 13]) for i in range(4)]
        for i, p in enumerate(self.players):
            p.set_hand(hands[i])

        # Show stage (simultaneous choice; then reveal in order)
        forehand = (self.dealer + 1) % 4
        show_bids: Dict[int, ShowBid] = {}
        for p in self.players:
            show_bids[p.seat] = p.choose_show_bid(
                self.dealer, self.score_state, self.show_banned_ranks
            )

        revealed_show_cards: Dict[int, int] = {}
        contract = Contract.NOLO
        declarer: Optional[int] = None

        print("\n--- REVEAL SHOW CARDS ---")
        for k in range(4):
            seat = (forehand + k) % 4
            bid = show_bids[seat]
            if bid.card is not None:
                # reveal the actual card (public)
                print(
                    f"{dealer_name(seat)} shows {card_str(bid.card)} -> {'RAMI' if bid.choice == Contract.RAMI else 'NOLO'}"
                )
                revealed_show_cards[seat] = bid.card
            else:
                print(
                    f"{dealer_name(seat)} declares {'RAMI' if bid.choice == Contract.RAMI else 'NOLO'} verbally"
                )
            if bid.choice == Contract.RAMI:
                contract = Contract.RAMI
                declarer = seat
                print(
                    f"==> Contract is RAMI. Declarer is {dealer_name(seat)}. (Further show cards are not revealed.)"
                )
                break
        else:
            contract = Contract.NOLO
            declarer = None
            print(
                "==> Contract is NOLO (no-one showed RAMI). All show cards were revealed."
            )

        # Determine first leader
        if contract == Contract.NOLO:
            leader = forehand
        else:
            assert declarer is not None
            leader = (declarer - 1) % 4  # right of declarer

        # Trick play
        played_cards: List[Tuple[int, int]] = []
        tricks_by_player = [0, 0, 0, 0]
        tricks_by_team = [0, 0]

        for trick_index in range(13):
            current_trick: List[Tuple[int, int]] = []
            lead_suit: Optional[int] = None

            for offset in range(4):
                seat = (leader + offset) % 4
                pl = self.players[seat]
                # Build public observation
                pub = PublicState(
                    contract=contract,
                    declarer=declarer,
                    dealer=self.dealer,
                    leader=leader,
                    trick_index=trick_index,
                    current_trick=list(current_trick),
                    played_cards=list(played_cards),
                    tricks_won_by_team=(tricks_by_team[0], tricks_by_team[1]),
                    tricks_won_by_player=tuple(tricks_by_player),
                    revealed_show_cards=dict(revealed_show_cards),
                    score_state=self.score_state,
                )
                c = pl.choose_play_card(pub, self.show_banned_ranks)

                # Enforce legality
                lm = legal_moves(pl.hand, lead_suit)
                if c not in lm:
                    # If human attempted illegal, re-prompt inside HumanPlayer; AI should rarely do this.
                    if isinstance(pl, HumanPlayer):
                        print("Illegal move detected. Please choose again.")
                        c = pl.choose_play_card(pub, self.show_banned_ranks)
                    else:
                        c = lm[0]

                        # If this is the human seat, record decision context for post-deal move-quality analysis.
                if isinstance(pl, HumanPlayer):
                    # Snapshot public state BEFORE the human plays (information set at decision time).
                    pub_snap = PublicState(
                        contract=contract,
                        declarer=declarer,
                        dealer=self.dealer,
                        leader=leader,
                        trick_index=trick_index,
                        current_trick=list(current_trick),
                        played_cards=list(played_cards),
                        tricks_won_by_team=(tricks_by_team[0], tricks_by_team[1]),
                        tricks_won_by_player=tuple(tricks_by_player),
                        revealed_show_cards=dict(revealed_show_cards),
                        score_state=score_state_before,
                    )
                    human_move_log.append(
                        {
                            "seat": seat,
                            "trick_index": trick_index,
                            "pos": len(current_trick) + 1,
                            "pub": pub_snap,
                            "hand": list(pl.hand),
                            "played": c,
                        }
                    )
                # Play card
                pl.hand.remove(c)
                current_trick.append((seat, c))
                played_cards.append((seat, c))
                if lead_suit is None:
                    lead_suit = card_suit(c)

            win_seat = trick_winner(current_trick)
            win_team = team_of(win_seat)
            tricks_by_player[win_seat] += 1
            tricks_by_team[win_team] += 1

            win_card = next(c for p, c in current_trick if p == win_seat)
            # highlight winner card (and the human player's card if present)
            human_seat = next(
                (pl.seat for pl in self.players if isinstance(pl, HumanPlayer)), None
            )
            parts = []
            for p, c in current_trick:
                cs = card_str(c)
                if c == win_card:
                    cs = _style(cs, "win")
                elif human_seat is not None and p == human_seat:
                    cs = _style(cs, "you")
                parts.append(f"{dealer_name(p)}:{cs}")
            trick_str = " | ".join(parts)
            print(
                f"Trick {trick_index + 1}: {trick_str}  -> Winner: {dealer_name(win_seat)} (Team{win_team})"
            )

            leader = win_seat

        # Deal scoring
        t0, t1 = tricks_by_team
        winner_team, pts = score_deal(contract, declarer, t0, t1)

        print("\n--- DEAL RESULT ---")
        print(f"Contract: {contract}")
        print(f"Tricks: Team0={t0} Team1={t1}")
        if contract == Contract.RAMI:
            dec_team = team_of(declarer) if declarer is not None else None
            print(f"Declarer team was Team{dec_team}.")
        print(
            f"Winner of deal: Team{winner_team} for {pts} points (deal points, per rules)."
        )
        self._apply_scoring(winner_team, pts)
        # Post-deal analysis (EVs, metrics)
        self._post_deal_analysis(
            hands,
            score_state_before,
            show_bids,
            human_move_log,
            revealed_show_cards,
            forehand,
            contract,
            declarer,
            tricks_by_player,
            tricks_by_team,
            winner_team,
            pts,
        )
        print(self.scoreboard_str())

    def _post_deal_analysis(
        self,
        initial_hands: List[List[int]],
        score_state_before: ScoreState,
        show_bids: Dict[int, ShowBid],
        human_move_log: List[Dict[str, object]],
        revealed_show_cards: Dict[int, int],
        forehand: int,
        contract: str,
        declarer: Optional[int],
        tricks_by_player: List[int],
        tricks_by_team: List[int],
        winner_team: int,
        pts: int,
    ) -> None:
        """
        Post-deal diagnostic output intended for study.
        Prints each player's approximate EV for choosing RAMI vs NOLO from their private hand metrics,
        plus compact hand-shape descriptors and actual trick counts.
        """
        if self.analysis_level == "none":
            return

        print("\n=== ANALYSIS (post-deal) ===")
        print(
            "Approximate hand-based EVs for each player if they alone could choose the contract."
        )
        print(
            "Note: These are *private-hand* approximations (Binomial model + RS/NHI maps), not solved equilibria.\n"
        )

        # Header
        hdr = (
            f"{'Seat':<4} {'Tm':<2} {'Tr':>2} {'Imp':<3} {'Show':<14} "
            f"{'HCP':>3} {'S/H/D/C':<9} "
            f"{'RS':>5} {'P7+':>5} {'EV_R':>6}  "
            f"{'NHI':>5} {'P<=6':>5} {'EV_N':>6}  {'Rec':<4}"
        )
        print(hdr)
        print("-" * len(hdr))

        human_seat = next(
            (pl.seat for pl in self.players if isinstance(pl, HumanPlayer)), None
        )

        # Auction order & counterfactual "pivotality" (retrospective):
        # 'P' marks a seat whose show choice, if flipped, would have changed the contract outcome in THIS deal.
        order = [(forehand + k) % 4 for k in range(4)]

        def auction_outcome(ch: Dict[int, str]) -> Tuple[str, Optional[int]]:
            for s in order:
                if ch[s] == Contract.RAMI:
                    return Contract.RAMI, s
            return Contract.NOLO, None

        choices0 = {s: show_bids[s].choice for s in range(4)}
        actual_cf_contract, actual_cf_decl = auction_outcome(choices0)

        for seat in range(4):
            hand = initial_hands[seat]
            feat = hand_feature_summary(hand)
            rs = float(feat["RS"])
            nhi = float(feat["NHI"])
            p_rami_make = approx_P_rami_make(rs)
            ev_rami = approx_EV_rami_from_RS(rs)
            p_nolo_win = approx_P_nolo_win(nhi)
            ev_nolo = approx_EV_nolo_from_NHI(nhi)

            # Recommendation using the same EV gate as the AI show logic, but evaluated at START-of-deal score state.
            rami_ev_min = 4.0 if score_state_before.rising else 3.0
            if score_state_before.rising and score_state_before.rising_team is not None:
                if score_state_before.rising_team == team_of(seat):
                    my_score = score_state_before.scores[team_of(seat)]
                    if my_score >= 40:
                        rami_ev_min = 6.0
                else:
                    opp_score = score_state_before.scores[
                        score_state_before.rising_team
                    ]
                    if opp_score >= 40:
                        rami_ev_min = 3.0
            margin = 0.5
            rec = (
                Contract.RAMI
                if (ev_rami >= rami_ev_min and ev_rami > ev_nolo + margin)
                else Contract.NOLO
            )

            bid = show_bids.get(seat)
            if bid is None:
                show_str = "-"
            else:
                if bid.card is None:
                    show_str = f"{bid.choice} (verbal)"
                else:
                    cst = card_str(bid.card)
                    # mark whether it was actually revealed during auction
                    if seat in revealed_show_cards:
                        show_str = f"{bid.choice} {cst}"
                    else:
                        # unrevealed intent (use braces)
                        show_str = f"{bid.choice} {{{cst}}}"

            # Mismatch marker: '!' means the seat chose opposite of the recommendation AND was pivotal in this deal.
            bid_choice = bid.choice if bid is not None else None
            mismatch = bid_choice is not None and bid_choice != rec

            flipped = dict(choices0)
            flipped[seat] = (
                Contract.NOLO if choices0[seat] == Contract.RAMI else Contract.RAMI
            )
            flip_contract, flip_decl = auction_outcome(flipped)
            pivotal = flip_contract != actual_cf_contract or flip_decl != actual_cf_decl
            imp = "P" if pivotal else "."
            if mismatch and pivotal and show_str != "-":
                show_str = "!" + show_str

            lens = feat["lens"]
            lens_str = f"{lens[0]}/{lens[1]}/{lens[2]}/{lens[3]}"

            seat_label = dealer_name(seat)
            if human_seat is not None and seat == human_seat:
                seat_label = _style(seat_label, "you")

            line = (
                f"{seat_label:<4} {team_of(seat):<2} {tricks_by_player[seat]:>2} {imp:<3} "
                f"{show_str:<14} "
                f"{int(feat['hcp']):>3} {lens_str:<9} "
                f"{rs:>5.1f} {p_rami_make:>5.2f} {ev_rami:>6.1f}  "
                f"{nhi:>5.1f} {p_nolo_win:>5.2f} {ev_nolo:>6.1f}  {rec:<4}"
            )
            print(line)

        # Bidding impact summary
        pivots = []
        for s in range(4):
            flipped = dict(choices0)
            flipped[s] = (
                Contract.NOLO if choices0[s] == Contract.RAMI else Contract.RAMI
            )
            fc, fd = auction_outcome(flipped)
            if fc != actual_cf_contract or fd != actual_cf_decl:
                pivots.append(dealer_name(s))
        earliest_red = (
            dealer_name(actual_cf_decl) if actual_cf_decl is not None else "(none)"
        )
        order_names = [dealer_name(s) for s in order]
        print(
            f"\nBidding (counterfactual): reveal order {', '.join(order_names)}; earliest red = {earliest_red}; pivotal seats = {', '.join(pivots) if pivots else '(none)'}"
        )

        # Team-level quick diagnostics
        t0, t1 = tricks_by_team
        print("\nTeam outcomes:")
        print(
            f"  Contract played: {contract}"
            + (f" (Declarer: {dealer_name(declarer)})" if declarer is not None else "")
        )
        print(f"  Tricks: Team0={t0}  Team1={t1}")
        print(f"  Deal winner: Team{winner_team} for {pts} points")

        # Contract difficulty snapshot (approx, from declarer hand for RAMI; from partners for NOLO)
        if contract == Contract.RAMI and declarer is not None:
            feat_d = hand_feature_summary(initial_hands[declarer])
            rs_d = float(feat_d["RS"])
            ev_d = approx_EV_rami_from_RS(rs_d)
            p_make = approx_P_rami_make(rs_d)
            exp_tr = 13.0 * approx_p_team_rami(rs_d)
            print(
                f"  Declarer strength (approx): RS={rs_d:.1f}, P(make>=7)={p_make:.2f}, EV_RAMI={ev_d:.1f}, E[team tricks]={exp_tr:.1f}"
            )
        elif contract == Contract.NOLO:
            ev_team = []
            for tm in (0, 1):
                seats = [0, 2] if tm == 0 else [1, 3]
                evs = [
                    approx_EV_nolo_from_NHI(
                        float(hand_feature_summary(initial_hands[s])["NHI"])
                    )
                    for s in seats
                ]
                ev_team.append(sum(evs) / 2.0)
            print(
                f"  Team NOLO EV indicators (avg of partners): Team0={ev_team[0]:.1f}, Team1={ev_team[1]:.1f}"
            )

        # If full analysis requested, reveal all hands + show intents.
        if self.analysis_level == "full":
            print("\nFull hands (post-mortem):")
            for seat in range(4):
                hand = sort_hand(initial_hands[seat][:])
                feat = hand_feature_summary(hand)
                print(
                    f"\n{dealer_name(seat)} (Team{team_of(seat)}): "
                    f"HCP={feat['hcp']} RS={feat['RS']:.1f} NHI={feat['NHI']:.1f} "
                    f"Top5={feat['top5']} Exits(2-4)={feat['exits']} "
                    f"Voids/Sing/Dbl={feat['voids']}/{feat['singles']}/{feat['doubles']}"
                )
                # Print suit groups compactly
                print_hand(hand)

        # ----------------------------
        # Move-quality analysis (human only)
        # ----------------------------
        if human_seat is not None and human_move_log:
            rN = (
                self.analysis_move_rollouts
                if self.analysis_move_rollouts is not None
                else self._ai_rollouts()
            )
            # Fallback if no MonteCarloAI exists (should not happen): use 200
            if rN is None or rN <= 0:
                rN = 200

            print("\n=== MOVE QUALITY (your cardplay) ===")
            print(
                f"Estimator: information-set Monte Carlo (PIMC) with {rN} rollouts per legal move."
            )
            print(
                "EV units: same state-adjusted utility used by the AI (accounts for nousussa resets)."
            )
            print(
                "Columns: EV_you = estimated utility of your chosen card; EV_AI = best estimated utility among legal plays; Gap = EV_AI - EV_you.\n"
            )

            hdr2 = f"{'Tr':>2} {'Pos':>3} {'Led':>3} {'#L':>3}  {'You':<6} {'AI':<6} {'EV_you':>8} {'EV_AI':>8} {'Gap':>7} {'2nd':<6}"
            print(hdr2)
            print("-" * len(hdr2))

            total_gap = 0.0
            worst = (0.0, None)  # (gap, record)
            for rec in human_move_log:
                pub = rec["pub"]  # PublicState
                hand0 = rec["hand"]  # list[int]
                chosen = rec["played"]
                seat = rec["seat"]
                lead_suit = pub.lead_suit()
                lm = legal_moves(hand0, lead_suit)
                # If somehow the chosen card is not in lm (shouldn't happen), skip evaluation.
                if chosen not in lm:
                    continue

                # Evaluate all legal moves
                vals: Dict[int, float] = {}
                my_team = team_of(seat)
                for c in lm:
                    vals[c] = estimate_value_generic(pub, hand0, seat, my_team, c, rN)

                best = max(vals, key=vals.get)
                best_val = vals[best]
                chosen_val = vals[chosen]
                sorted_moves = sorted(vals.items(), key=lambda kv: kv[1], reverse=True)
                # second best
                second = None
                second_val = None
                if len(sorted_moves) >= 2:
                    second = sorted_moves[1][0]
                    second_val = sorted_moves[1][1]

                gap = best_val - chosen_val
                # Clamp tiny negative gaps due to Monte Carlo noise
                if gap < 0 and gap > -0.25:
                    gap = 0.0
                total_gap += max(0.0, gap)

                if gap > worst[0]:
                    worst = (gap, rec)

                led = SUITS[lead_suit] if lead_suit is not None else "-"
                line = (
                    f"{rec['trick_index'] + 1:>2} {rec['pos']:>3} {led:>3} {len(lm):>3}  "
                    f"{card_str(chosen):<6} {card_str(best):<6} "
                    f"{chosen_val:>8.2f} {best_val:>8.2f} {gap:>7.2f} "
                    f"{(card_str(second) if second is not None else '-'): <6}"
                )
                print(line)
                if self.analysis_level == "full":
                    topn = min(self.analysis_topn, len(sorted_moves))
                    tops = []
                    for rank_i in range(topn):
                        c_i, v_i = sorted_moves[rank_i]
                        tag = "*" if c_i == chosen else ""
                        tops.append(f"{rank_i + 1}) {card_str(c_i)}{tag} {v_i:+.2f}")
                    # indent under the row for readability
                    print("".ljust(9) + "Top moves: " + " | ".join(tops))

            print("\nMove-quality summary:")
            print(f"  Total EV gap (sum over your turns): {total_gap:.2f}")
            if worst[1] is not None:
                wrec = worst[1]
                print(
                    f"  Largest single-turn gap: {worst[0]:.2f} at Trick {wrec['trick_index'] + 1}, Pos {wrec['pos']} (you played {card_str(wrec['played'])})."
                )
            print("=== END MOVE QUALITY ===\n")

        print("=== END ANALYSIS ===\n")

    def _apply_scoring(self, winner_team: int, pts: int) -> None:
        # update totals (for reference; tournament-like bookkeeping)
        tot0, tot1 = self.score_state.totals
        if winner_team == 0:
            tot0 += pts
        else:
            tot1 += pts
        self.score_state.totals = (tot0, tot1)

        if not self.score_state.rising:
            s0, s1 = self.score_state.scores
            if winner_team == 0:
                s0 += pts
            else:
                s1 += pts
            self.score_state.scores = (s0, s1)
            return

        # rising mode (nousussa)
        rising_team = self.score_state.rising_team
        s0, s1 = self.score_state.scores

        if rising_team is None:
            # table -> winner starts rising with pts
            if winner_team == 0:
                self.score_state.scores = (pts, 0)
            else:
                self.score_state.scores = (0, pts)
            self.score_state.rising_team = winner_team
            return

        if winner_team == rising_team:
            # continue rising
            if winner_team == 0:
                self.score_state.scores = (s0 + pts, 0)
            else:
                self.score_state.scores = (0, s1 + pts)
            return

        # opponents scored: back to table (0-0)
        self.score_state.scores = (0, 0)
        self.score_state.rising_team = None


# ----------------------------
# CLI entrypoint
# ----------------------------


def main():
    ap = argparse.ArgumentParser(
        description="Play Tuppi (4-player partnership) vs 3 AIs in the terminal."
    )
    ap.add_argument(
        "--human-seat",
        type=int,
        default=0,
        choices=[0, 1, 2, 3],
        help="Seat index for the human player (0..3). Partners are opposite: (0,2) and (1,3).",
    )
    ap.add_argument(
        "--rollouts",
        type=int,
        default=600,
        help="Monte Carlo rollouts per AI decision (higher = stronger but slower).",
    )
    ap.add_argument(
        "--flat-scoring",
        action="store_true",
        help="Use flat scoring (both teams accumulate). Default is official rising scoring (nousussa).",
    )
    ap.add_argument(
        "--seed", type=int, default=None, help="Random seed for reproducibility."
    )
    ap.add_argument(
        "--show-ban",
        type=str,
        default="2,J,Q,K",
        help="Comma-separated ranks banned from showing (default '2,J,Q,K'). Example: '2,K' for a looser variant.",
    )
    ap.add_argument(
        "--analysis",
        type=str,
        default="basic",
        choices=["none", "basic", "full"],
        help="Post-deal analysis output: none/basic/full (EV tables, hand metrics; full also prints all hands and show intents).",
    )
    ap.add_argument(
        "--analysis-move-rollouts",
        type=int,
        default=None,
        help="Rollouts per decision for post-deal move-quality analysis (EV gap). Default: same as --rollouts.",
    )
    ap.add_argument(
        "--analysis-topn",
        type=int,
        default=3,
        help="In --analysis full, print the top-N legal moves and their EVs for each of your turns (default 3).",
    )
    args = ap.parse_args()

    banned = set()
    for tok in args.show_ban.split(","):
        t = tok.strip().upper()
        if not t:
            continue
        if t in STR_RANK:
            banned.add(STR_RANK[t])
        else:
            raise SystemExit(f"Unknown rank in --show-ban: {tok}")

    game = TuppiGame(
        human_seat=args.human_seat,
        rollouts=args.rollouts,
        rising_scoring=not args.flat_scoring,
        seed=args.seed,
        show_banned_ranks=banned,
        analysis_level=args.analysis,
        analysis_move_rollouts=args.analysis_move_rollouts,
        analysis_topn=args.analysis_topn,
    )
    game.run()


if __name__ == "__main__":
    main()
