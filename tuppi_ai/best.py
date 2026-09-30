"""The current best TuppiAI player, in one place.

    from tuppi_ai.best import best_agents
    agents = best_agents()            # {seat: agent} for all four seats
    action = agents[seat].choose_action(player_observation)

Configuration (docs/STATUS.md has the evidence for every choice): at each
decision, including showing, 128 hidden-hand layouts are drawn uniformly from
those consistent with the seat's observation; every legal action is played out
in each by `models/rollout_clone_small.pt` (a behaviour clone of
partner_aware_lead_v2) for all four seats; the last 6 tricks are solved
exactly; the action with the best mean match-equity change (equity table
`models/equity_incumbent.json`) is chosen. The search runs in C on all cores.

Above 128 worlds (the live server uses 1024), bids use adaptive world
allocation (E7, docs/EFFICIENCY_PLAN.md): worlds in batches of 128, bids that
are confidently worse dropped, and an early stop once no bid can beat the
leader by 0.005. Tested non-inferior at 1024 worlds for about 1.5x less CPU
per deal (docs/STATUS.md). At 128 worlds or fewer nothing changes.

Own-team rollouts (2026-09-30, docs/SELFPLAY_PLAN.md): in the rollouts, the
searching team's own seats play the self-play policy SP1
(`models/sp1_policy_043.pt`); the opponents stay the clone, which models how
the incumbent opponents really play.
- At W=128: +0.00132 [+0.00041, +0.00222] against clone rollouts on all
  seats.
- At W=1024 with E7: +0.00058 [-0.00077, +0.00192], non-inferior.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROLLOUT = ROOT / "models" / "rollout_clone_small.pt"
#: Rollout policy of the searching team's own seats.
TEAM_ROLLOUT = ROOT / "models" / "sp1_policy_043.pt"
EQUITY = ROOT / "models" / "equity_incumbent.json"
WORLDS = 128
SOLVER_TAIL = 6
SPEC = f"search:{ROLLOUT}:w={WORLDS}:dd={SOLVER_TAIL}:show=1:team={TEAM_ROLLOUT}"
#: E7 adaptive worlds for bids, used when the world count exceeds one batch.
ADAPTIVE_BIDS = {"batch": 128, "z": 2.5, "delta": 0.005}


def best_agents(seats=range(4), worlds: int = WORLDS, seed: int = 0, team_rollout: bool = True) -> dict:
    """team_rollout=False: the clone on all rollout seats (the configuration
    before 2026-09-30, the research programme's pinned B0)."""
    from . import model as qmodel
    from .equity import Equity
    from .search import SearchAgent

    net = qmodel.load(ROLLOUT, "cpu")
    team_net = qmodel.load(TEAM_ROLLOUT, "cpu") if team_rollout else None
    table = Equity.load(EQUITY).table
    adaptive = ADAPTIVE_BIDS if worlds > ADAPTIVE_BIDS["batch"] else None
    return {s: SearchAgent(net, table, s, worlds=worlds, dd_left=SOLVER_TAIL, search_showing=1, seed=seed + s,
                           adaptive=adaptive, team_net=team_net)
            for s in seats}
