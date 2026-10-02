"""After-deal review: the player's own decisions, re-decided by the bot.

For each decision a seat took in a completed deal, the best agent's search is
run again from exactly that seat's observation at the time (never the full
deal), with the agent's own settings. Every legal action is priced on the same
sampled worlds, so the gap between the played action and the bot's choice has
a paired standard error. A decision is flagged as a clear mistake only if the
gap is at least ``min_cost`` match equity, at least ``z`` standard errors,
and both still hold when re-searched with ``confirm_worlds`` fresh worlds.

Equity is the match-win probability (the equity model of `tuppi_ai.equity`),
so a cost of 0.01 is one percentage point of the chance to win the match.

Not flagged, by design: forced decisions; the sooli return (the bot plays the
heuristic there, search measured no better); near-ties.

Since 2026-10-02 the review prices moves exactly as the live bot does
(`DealReviewer.best`): the searching team's own seats are rolled out by the
live own-team policy (`best.TEAM_ROLLOUT`), the opponents by the clone, and
worlds honour showing-fallback restrictions (B0-S1). The live bot's policy
anchor (`best.KEEP`, 0.003) needs no counterpart: a flagged gap is at least
`min_cost` (0.01), so the bot itself would also leave the played action.

Calibration (`tools/review_calibrate.py`, docs/STATUS.md): at the defaults
(0.01, 2.5 SE, 1024 confirming worlds) the bot reviewing its own play flags
0.06 decisions per seat-deal and the incumbent 1.2. Re-run for reviewer v2
(2026-10-02, 48 v3 deals, runs/review_calib_v2.json): bot 0.052 and the
benchmark heuristic (now partner_aware_lead_v3) 0.93, so the defaults hold. The estimated costs are
the search's: the incumbent's flagged costs add up to about six times its
measured deficit, so they rank mistakes better than they measure them.
"""

from __future__ import annotations

import ctypes as C
from dataclasses import dataclass

import numpy as np

from . import native
from .bridge import action_id, obs_from_player_observation

KIND_BID = "bid"


@dataclass(frozen=True)
class ReviewedDecision:
    decision_index: int
    kind: str
    trick_index: int | None
    played: int          # native action id
    recommended: int     # native action id (the bot's choice)
    cost: float          # recommended value - played value (>= 0 when flagged)
    standard_error: float
    flagged: bool


def decision_kind(observation) -> tuple[str, int | None]:
    """(kind, trick index) of a decision from the engine observation."""
    phase = observation.phase.value
    if phase == "SHOWING":
        return KIND_BID, None
    if phase == "SOOLI_OFFER":
        return "sooli_offer", None
    if phase == "SOOLI_GIVE":
        return "sooli_give", None
    if phase == "SOOLI_RETURN":
        return "sooli_return", None
    sooli = phase == "SOOLI_PLAY"
    tricks = observation.sooli_tricks if sooli else observation.completed_tricks
    current = observation.sooli_current_trick if sooli else observation.current_trick
    prefix = "sooli_" if sooli else ""
    if not current:
        return prefix + "lead", len(tricks)
    led = current[0].card.suit
    follows = any(card.suit is led for card in observation.own_hand)
    return prefix + ("follow" if follows else "discard"), len(tricks)


class DealReviewer:
    """Prices a seat's decisions with the best agent's search."""

    reviewer_id = "tuppi_ai.best_search_review.v2"

    def __init__(self, net, equity_table, *, worlds: int = 256, confirm_worlds: int = 1024,
                 dd_left: int = 6, min_cost: float = 0.01, z: float = 2.5, seed: int = 0,
                 sooli: dict | None = None, team_net=None):
        from .search import SOOLI_DEFAULTS

        self.mlp = native.Mlp(net)
        self.worlds, self.confirm_worlds, self.dd_left = worlds, confirm_worlds, dd_left
        self.min_cost, self.z = min_cost, z
        self.sooli = {**SOOLI_DEFAULTS, **(sooli or {})}
        self.env = native.Env(max(worlds, confirm_worlds) * 26, seed, equity_table, single_deal=True,
                              encoder=net.encoder)
        self._team_mlp = None
        if team_net is not None:  # the reviewed seat's team rolls out with this policy
            if team_net.encoder != net.encoder:
                raise ValueError("the own-team rollout net must use the same encoder")
            self._team_mlp = native.Mlp(team_net)
            self.env.set_team_rollout(self._team_mlp)
        self.rng = C.c_uint64(seed * 7919 + 17)

    @classmethod
    def best(cls, **kwargs) -> "DealReviewer":
        """The live bot's pricing: clone opponents, own-team policy rollouts, the sampler fix."""
        from . import model as qmodel
        from .best import EQUITY, ROLLOUT, SOLVER_TAIL, TEAM_ROLLOUT
        from .equity import Equity

        native.set_showing_fix(True)  # process-wide, as best_agents sets it
        kwargs.setdefault("team_net", qmodel.load(TEAM_ROLLOUT, "cpu"))
        return cls(qmodel.load(ROLLOUT, "cpu"), Equity.load(EQUITY).table, dd_left=SOLVER_TAIL, **kwargs)

    def _values(self, obs: native.TcObs, ids: list[int], worlds: int) -> np.ndarray:
        # The same rollout settings as SearchAgent: sooli play inside rollouts
        # by the heuristics, except when pricing a sooli exchange or sooli card.
        cfg = self.sooli
        in_sooli = obs.phase in native.SOOLI_PHASES and obs.phase != native.PH_SOOLI_OFFER
        self.env.set_sooli(cfg["belief"], False, False if in_sooli else cfg["offer_play_heur"], cfg["lam"])
        return native.search_world_values(self.env, self.mlp, obs, ids, worlds, self.dd_left, self.rng)

    def _gap(self, per_world: np.ndarray, ids: list[int], played: int) -> tuple[int, float, float]:
        mean = per_world.mean(axis=0)
        best = int(np.argmax(mean))
        p = ids.index(played)
        diff = per_world[:, best] - per_world[:, p]
        se = float(diff.std(ddof=1) / np.sqrt(len(diff))) if len(diff) > 1 else float("inf")
        return best, float(diff.mean()), se

    def review_one(self, index: int, observation, action) -> ReviewedDecision | None:
        """None for a forced decision."""
        legal = observation.legal_actions
        if len(legal) < 2:
            return None
        kind, trick = decision_kind(observation)
        obs = obs_from_player_observation(observation)
        ids = [action_id(a) for a in legal]
        played = action_id(action)
        best, gap, se = self._gap(self._values(obs, ids, self.worlds), ids, played)
        recommended = ids[best]
        clear = kind != "sooli_return" and recommended != played and gap >= self.min_cost and gap >= self.z * se
        if clear:
            # Confirm on fresh, larger worlds with the recommendation held fixed:
            # choosing the best of many noisy means inflates the first gap, so
            # the reported cost is this unbiased paired estimate instead.
            pair = [recommended, played]
            per_world = self._values(obs, pair, self.confirm_worlds)
            diff = per_world[:, 0] - per_world[:, 1]
            gap = float(diff.mean())
            se = float(diff.std(ddof=1) / np.sqrt(len(diff)))
            clear = gap >= self.min_cost and gap >= self.z * se
        return ReviewedDecision(index, kind, trick, played, recommended, gap, se, clear)

    def review(self, decisions) -> list[ReviewedDecision]:
        """`decisions`: (engine observation, engine action) pairs of one seat, in order."""
        out = []
        for index, (observation, action) in enumerate(decisions):
            item = self.review_one(index, observation, action)
            if item is not None:
                out.append(item)
        return out


class ServerReviewer:
    """TuppiProject's ``tuppi_server.deal_review.DealReviewer`` backed by the best agent's search."""

    reviewer_id = DealReviewer.reviewer_id

    def __init__(self, reviewer: DealReviewer | None = None):
        self.reviewer = reviewer or DealReviewer.best()

    def review_decisions(self, decisions):
        from tuppi_server.deal_review import ReviewFinding

        from .bridge import engine_action

        findings = []
        for decision in decisions:
            item = self.reviewer.review_one(decision.decision_index, decision.observation, decision.action)
            if item is not None and item.flagged:
                findings.append(ReviewFinding(
                    decision_index=decision.decision_index,
                    recommended=engine_action(item.recommended, decision.action.seat),
                    cost=item.cost,
                    standard_error=item.standard_error,
                ))
        return findings
