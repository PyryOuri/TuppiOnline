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

Since 2026-10-01 the own-team rollout model is VRPO1
(`models/vrpo1_actor_0504.pt`, privileged-critic PPO from SP1; +0.00605 over
SP1 without search).
- Against SP1 own-team rollouts at W=128: +0.00065 [-0.00009, +0.00138].
- At W=1024 with E7: +0.00041 [-0.00044, +0.00126], same CPU.

Policy-anchored search (2026-10-01): the agent keeps the VRPO1 policy's
action unless the searched best beats it by more than 0.003 equity (after
E7's adaptive bids).
- At W=128: +0.00305 [+0.00234, +0.00377] against plain search.
- At W=1024: +0.00267 [+0.00160, +0.00374], with 3% more CPU.

Since 2026-10-01 evening the anchor is VRPO3 (`models/vrpo3_final.pt`,
512x4; +0.00118 over VRPO2 without search).
- At W=128 (keep 0.012): +0.00176 [+0.00083, +0.00269] against the VRPO1
  anchor.
- At W=1024 (keep 0.003): +0.00005 [-0.00083, +0.00092], neutral, with 2%
  less CPU.

Sampler fix B0-S1 (2026-10-01): when a showing fallback is on record, the
worlds honour what it implies about the original hands. Before the fix, 69%
of the worlds drawn at such decisions were illegal.
- W=128 screen: +0.00014 [-0.00002, +0.00030], 931 of 1,024 deals
  identical.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROLLOUT = ROOT / "models" / "rollout_clone_small.pt"
#: Rollout policy of the searching team's own seats.
TEAM_ROLLOUT = ROOT / "models" / "vrpo1_actor_0504.pt"
EQUITY = ROOT / "models" / "equity_incumbent.json"
WORLDS = 128
SOLVER_TAIL = 6
#: Policy-anchored search: keep the own-team policy's action unless the
#: searched best beats it by more than this (equity).
KEEP = 0.003
#: The anchor policy (a 512x4 VRPO actor; the rollouts keep the faster VRPO1).
ANCHOR = ROOT / "models" / "vrpo3_final.pt"
SPEC = f"search:{ROLLOUT}:w={WORLDS}:dd={SOLVER_TAIL}:show=1:team={TEAM_ROLLOUT}:sf=1:keep={KEEP}:bp={ANCHOR}"
#: E7 adaptive worlds for bids, used when the world count exceeds one batch.
ADAPTIVE_BIDS = {"batch": 128, "z": 2.5, "delta": 0.005}


def best_agents(seats=range(4), worlds: int = WORLDS, seed: int = 0, team_rollout: bool = True,
                showing_fix: bool | None = None) -> dict:
    """team_rollout=False: the clone on all rollout seats and no policy anchor
    (the configuration before 2026-09-30, the research programme's pinned B0).
    showing_fix: worlds honour showing-fallback restrictions (B0-S1); a
    process-wide native setting, following team_rollout unless given, so the
    pinned B0 keeps the original sampler."""
    from . import model as qmodel
    from . import native

    if showing_fix is None:
        showing_fix = team_rollout
    if showing_fix:
        native.set_showing_fix(True)
    from .equity import Equity
    from .search import SearchAgent

    net = qmodel.load(ROLLOUT, "cpu")
    team_net = qmodel.load(TEAM_ROLLOUT, "cpu") if team_rollout else None
    anchor = qmodel.load(ANCHOR, "cpu") if team_rollout else None
    table = Equity.load(EQUITY).table
    adaptive = ADAPTIVE_BIDS if worlds > ADAPTIVE_BIDS["batch"] else None
    return {s: SearchAgent(net, table, s, worlds=worlds, dd_left=SOLVER_TAIL, search_showing=1, seed=seed + s,
                           adaptive=adaptive, team_net=team_net,
                           keep=KEEP if team_rollout else None, blueprint_net=anchor)
            for s in seats}
