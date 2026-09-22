"""Run TuppiProject's private-alpha server with TuppiAI bots in chosen AI seats.

The server, protocol and Swift client are TuppiProject's, unchanged. Only the
construction of AI seat agents is replaced at runtime, and all server state is
written to a separate directory (runs/human_server by default), so the normal
server's rooms and history are untouched.

    TUPPI_AI_SEATS="1:incumbent,2:search,3:incumbent" \
        ~/.venvs/tuppi-ai/bin/python tools/serve_human.py [--lan] [--port 8766]

Seat kinds: `incumbent` (partner_aware_lead_v2, the server's normal AI) and
`search` (TuppiAI search agent; checkpoint from TUPPI_AI_CHECKPOINT). Seats not
listed keep the server's normal AI.

Caveat: the protocol only allows the profile names partner_aware_v1 and
partner_aware_lead_v2, so the client still labels every AI seat
"partner_aware_lead_v2" even when a seat plays TuppiAI. Record which seats were
which (the server prints the plan at start-up).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("TUPPI_SERVER_DATA_DIR", str(ROOT / "runs" / "human_server"))
os.environ.setdefault("TUPPI_SERVER_PORT", "8766")


def _plan() -> dict[int, str]:
    raw = os.environ.get("TUPPI_AI_SEATS", "1:incumbent,2:search,3:incumbent")
    plan = {}
    for item in filter(None, (p.strip() for p in raw.split(","))):
        seat, kind = item.split(":")
        if kind not in ("incumbent", "search"):
            raise SystemExit(f"unknown seat kind {kind!r}")
        plan[int(seat)] = kind
    return plan


def main() -> None:
    from tuppi_server import app, match_runner

    from tuppi_ai import model as qmodel
    from tuppi_ai.equity import Equity
    from tuppi_ai.search import SearchAgent

    plan = _plan()
    checkpoint = os.environ.get("TUPPI_AI_CHECKPOINT", str(ROOT / "runs" / "bc_small.pt"))
    worlds = int(os.environ.get("TUPPI_AI_WORLDS", "32"))
    net = qmodel.load(checkpoint, "cpu")
    table = Equity.load(ROOT / "runs" / "equity_incumbent.json").table
    original = match_runner._construct_ai_agents

    def construct(seats, *, profile_key):
        agents = original(seats, profile_key=profile_key)
        for seat in seats:
            if plan.get(seat) == "search":
                agents[seat] = SearchAgent(net, table, seat, worlds=worlds, dd_left=6,
                                           search_showing=True, seed=seat)
        return agents

    match_runner._construct_ai_agents = construct
    print(f"TuppiAI seat plan: {plan}; search checkpoint {checkpoint}, W={worlds}")
    print(f"server data dir: {os.environ['TUPPI_SERVER_DATA_DIR']}")
    app.main(sys.argv[1:])


if __name__ == "__main__":
    main()
