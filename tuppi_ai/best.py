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
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROLLOUT = ROOT / "models" / "rollout_clone_small.pt"
EQUITY = ROOT / "models" / "equity_incumbent.json"
WORLDS = 128
SOLVER_TAIL = 6
SPEC = f"search:{ROLLOUT}:w={WORLDS}:dd={SOLVER_TAIL}:show=1"


def best_agents(seats=range(4), worlds: int = WORLDS, seed: int = 0) -> dict:
    from . import model as qmodel
    from .equity import Equity
    from .search import SearchAgent

    net = qmodel.load(ROLLOUT, "cpu")
    table = Equity.load(EQUITY).table
    return {s: SearchAgent(net, table, s, worlds=worlds, dd_left=SOLVER_TAIL, search_showing=1, seed=seed + s)
            for s in seats}
