"""Match equity for the rising score (same model as tuppi_valuation.equity).

A nonterminal state is (up team, level = score / 4 in 1..12) or 0-0, plus which
team deals next. Given a deal-outcome model the match is an absorbing Markov
chain and its absorption probabilities are the match win probabilities.
`native_table` lays team 0's equity out as the C environment expects:
row 0 = 0-0, rows 1..12 = team 0 up at that level, rows 13..24 = team 1 up;
column 1 when team 0 deals the deal about to be played.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

LEVELS = 13  # nonterminal levels 0..12; level 13 (52 points) ends the match


@dataclass(frozen=True)
class DealModel:
    dealer_win: float
    points_given_dealer: dict[int, float]
    points_given_other: dict[int, float]

    @classmethod
    def from_outcomes(cls, outcomes) -> "DealModel":
        """outcomes: iterable of (dealer_team_won: bool, points: int)."""
        dealer: dict[int, int] = {}
        other: dict[int, int] = {}
        for won, points in outcomes:
            bucket = dealer if won else other
            bucket[points] = bucket.get(points, 0) + 1
        nd, no = sum(dealer.values()), sum(other.values())
        return cls(nd / (nd + no),
                   {p: c / nd for p, c in sorted(dealer.items())},
                   {p: c / no for p, c in sorted(other.items())})

    def to_json(self) -> dict:
        return {"dealer_win": self.dealer_win,
                "points_given_dealer": {str(k): v for k, v in self.points_given_dealer.items()},
                "points_given_other": {str(k): v for k, v in self.points_given_other.items()}}

    @classmethod
    def from_json(cls, data: dict) -> "DealModel":
        return cls(data["dealer_win"],
                   {int(k): v for k, v in data["points_given_dealer"].items()},
                   {int(k): v for k, v in data["points_given_other"].items()})


def _outcomes(model: DealModel, we_deal: bool):
    for won_by_dealer, weight, law in ((True, model.dealer_win, model.points_given_dealer),
                                       (False, 1 - model.dealer_win, model.points_given_other)):
        for points, p in law.items():
            yield (won_by_dealer == we_deal), points, weight * p


def solve(model: DealModel, tol: float = 1e-14) -> dict[tuple[int, int, bool], float]:
    """P(we win) from (level, sign, we_deal); sign +1 we are up, -1 they are up, 0 at 0-0."""
    states = [(0, 0, d) for d in (False, True)] + [
        (lv, sg, d) for d in (False, True) for lv in range(1, LEVELS) for sg in (1, -1)]
    index = {s: i for i, s in enumerate(states)}
    rows = []
    for level, sign, we_deal in states:
        const, row = 0.0, []
        for we_won, points, p in _outcomes(model, we_deal):
            step = points // 4
            if level == 0:
                target = step
                if target >= LEVELS:
                    const += p * (1.0 if we_won else 0.0)
                    continue
                row.append((index[(target, 1 if we_won else -1, not we_deal)], p))
            elif we_won == (sign == 1):
                target = level + step
                if target >= LEVELS:
                    const += p * (1.0 if we_won else 0.0)
                    continue
                row.append((index[(target, sign, not we_deal)], p))
            else:
                row.append((index[(0, 0, not we_deal)], p))
        rows.append((const, row))
    value = np.full(len(states), 0.5)
    for _ in range(200_000):
        new = np.array([c + sum(p * value[j] for j, p in r) for c, r in rows])
        delta = np.max(np.abs(new - value))
        value = new
        if delta < tol:
            break
    return {s: float(value[i]) for s, i in index.items()}


def native_table(values: dict[tuple[int, int, bool], float]) -> np.ndarray:
    table = np.zeros((25, 2))
    for col, team0_deals in ((0, False), (1, True)):
        table[0, col] = values[(0, 0, team0_deals)]
        for level in range(1, LEVELS):
            table[level, col] = values[(level, 1, team0_deals)]
            table[12 + level, col] = values[(level, -1, team0_deals)]
    return table


class Equity:
    """Team-0 match equity and per-deal equity deltas."""

    def __init__(self, model: DealModel):
        self.model = model
        self.values = solve(model)
        self.table = native_table(self.values)

    def team0(self, score0: int, score1: int, dealer: int) -> float:
        if score0 >= 52:
            return 1.0
        if score1 >= 52:
            return 0.0
        row = 0 if score0 == 0 and score1 == 0 else (score0 // 4 if score0 else 12 + score1 // 4)
        return float(self.table[row, 1 if dealer % 2 == 0 else 0])

    def delta0(self, before: tuple[int, int], after: tuple[int, int], dealer: int) -> float:
        return self.team0(*after, dealer + 1) - self.team0(*before, dealer)

    def save(self, path: Path) -> None:
        path.write_text(json.dumps({"model": self.model.to_json(),
                                    "table": self.table.tolist()}, indent=1))

    @classmethod
    def load(cls, path: Path) -> "Equity":
        return cls(DealModel.from_json(json.loads(Path(path).read_text())["model"]))
