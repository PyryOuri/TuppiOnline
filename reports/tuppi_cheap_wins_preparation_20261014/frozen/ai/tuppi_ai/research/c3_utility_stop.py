"""C3b: exact surrogate-utility stopping for ordinary rollouts (IMPLEMENTATION_SPEC.md section 5).

The native certificate lives in the research overlay (`utility_certificate` in
the patched tuppi_env.c, switch RESEARCH_OPT_UTILITY_STOP). This module is its
independent Python oracle and bookkeeping:

- `deal_utility` scores a final team-0 trick total through the AUTHORITATIVE
  rules objects (tuppi_rules DealScore + transition_rising_score) and the
  Python equity table, then rounds the equity change to float32 exactly as
  record_if_done does - so it is independent of the C finish()/tc_next_score
  it checks;
- `feasible_totals` is the conservative superset {t0, ..., t0 + r};
- `certificate` returns a `UtilityCertificate` only if every total in the
  superset gives the same utility. A certificate is an abstract evaluator
  result: it names no winner, trick total or next score.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import numpy as np

MODEL_ID = "c3b.superset_t0_to_t0_plus_r.float32_equity_delta.v1"


@dataclass(frozen=True)
class UtilityCertificate:
    value: float                 # float32-rounded team-0 equity change (as a Python float)
    candidate_final_trick_range: tuple[int, int]
    model_id: str = MODEL_ID


def feasible_totals(team0_done: int, completed_tricks: int) -> range:
    """Every final team-0 total is in {t0, ..., t0 + r}, r = 13 - completed (partial trick included)."""
    if not 0 <= completed_tricks <= 13 or not 0 <= team0_done <= completed_tricks:
        raise ValueError("inconsistent trick counts")
    return range(team0_done, team0_done + (13 - completed_tricks) + 1)


def deal_score(contract: int, declarer: int | None, team0_tricks: int):
    """The authoritative DealScore of an ordinary deal ending with `team0_tricks`."""
    from tuppi_rules import Contract, DealScore, Team

    t = (team0_tricks, 13 - team0_tricks)
    if contract == 0:
        w = Team.TEAM_0 if t[0] < t[1] else Team.TEAM_1
        return DealScore(Contract.NOLO, w, 4 * (7 - t[w.value]), t, None, False)
    dt = Team(declarer % 2)
    if t[dt.value] >= 7:
        return DealScore(Contract.RAMI, dt, 4 * (t[dt.value] - 6), t, dt, False)
    other = Team(1 - dt.value)
    return DealScore(Contract.RAMI, other, 8 * (t[other.value] - 6), t, dt, True)


@lru_cache(maxsize=None)
def deal_utility(score: tuple[int, int], dealer: int, contract: int, declarer: int | None, team0_tricks: int,
                 equity) -> float:
    """float32(V0(next score, next dealer) - V0(score, dealer)) through the authoritative rules."""
    from tuppi_rules import MatchScore, transition_rising_score

    after = transition_rising_score(MatchScore(*score), deal_score(contract, declarer, team0_tricks))
    delta = equity.team0(*after.as_tuple(), dealer + 1) - equity.team0(*score, dealer)
    return float(np.float32(delta))


def certificate(score, dealer, contract, declarer, team0_done, completed_tricks, equity):
    totals = feasible_totals(team0_done, completed_tricks)
    values = {deal_utility(tuple(score), dealer, contract, declarer, k, equity) for k in totals}
    if len(values) != 1:
        return None
    return UtilityCertificate(values.pop(), (totals.start, totals.stop - 1))


def certificate_of_deal(deal, equity):
    """The oracle certificate for a native ordinary TcDeal (None outside ordinary play)."""
    if deal.phase != 1 or deal.trick_size != 4 or deal.soolaaja >= 0 or deal.contract < 0:
        return None
    return certificate((deal.score[0], deal.score[1]), deal.dealer, deal.contract,
                       None if deal.contract == 0 else deal.declarer, deal.team_tricks[0], deal.n_played // 4, equity)


def reachable_utilities(deal, equity) -> set[float]:
    """Utilities of every legal continuation of a small native ordinary state (exhaustive)."""
    from .fixtures import enumerate_final_tricks

    return {deal_utility((deal.score[0], deal.score[1]), deal.dealer, deal.contract,
                         None if deal.contract == 0 else deal.declarer, k, equity)
            for k in enumerate_final_tricks(deal)}
