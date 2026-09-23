"""Run TuppiProject's private-alpha server with TuppiAI bots in chosen AI seats.

The server, protocol and Swift client are TuppiProject's, unchanged. Only the
construction of AI seat agents is replaced at runtime, and all server state is
written to a separate directory (runs/human_server by default), so the normal
server's rooms and history are untouched.

    TUPPI_AI_SEATS="1:incumbent,2:search,3:incumbent" \
        ~/.venvs/tuppi-ai/bin/python tools/serve_human.py [--lan] [--port 8766]

Seat kinds: `incumbent` (partner_aware_lead_v2, the server's normal AI) and
`search` (the best TuppiAI agent, `tuppi_ai.best`). Seats not listed keep the
server's normal AI.

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
os.environ.setdefault("TUPPI_AI_SEATS", "1:incumbent,2:search,3:incumbent")
# One data directory per seat plan, so the report knows who sat where.
_SLUG = "_".join(p.replace(":", "-") for p in sorted(os.environ["TUPPI_AI_SEATS"].split(",")))
os.environ.setdefault("TUPPI_SERVER_DATA_DIR", str(ROOT / "runs" / "human_server" / _SLUG))
os.environ.setdefault("TUPPI_SERVER_PORT", "8766")


def _plan() -> dict[int, str]:
    raw = os.environ["TUPPI_AI_SEATS"]
    plan = {}
    for item in filter(None, (p.strip() for p in raw.split(","))):
        seat, kind = item.split(":")
        if kind not in ("incumbent", "search"):
            raise SystemExit(f"unknown seat kind {kind!r}")
        plan[int(seat)] = kind
    return plan


def main() -> None:
    from tuppi_server import app, match_runner

    from tuppi_ai.best import ROLLOUT, WORLDS, best_agents

    plan = _plan()
    worlds = int(os.environ.get("TUPPI_AI_WORLDS", str(WORLDS)))
    original = match_runner._construct_ai_agents

    def construct(seats, *, profile_key):
        agents = original(seats, profile_key=profile_key)
        searched = [s for s in seats if plan.get(s) == "search"]
        agents.update(best_agents(searched, worlds=worlds))
        return agents

    match_runner._construct_ai_agents = construct
    print(f"TuppiAI seat plan: {plan}; best agent ({ROLLOUT.name}, W={worlds})")
    print(f"server data dir: {os.environ['TUPPI_SERVER_DATA_DIR']}")
    app.main(sys.argv[1:])


if __name__ == "__main__":
    main()
