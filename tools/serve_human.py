"""Run TuppiProject's private-alpha server with TuppiAI bots in chosen AI seats.

The server, protocol and Swift client are TuppiProject's, unchanged. Only the
construction of AI seat agents is replaced at runtime, and all server state is
written to a separate directory (runs/human_server by default), so the normal
server's rooms and history are untouched.

    TUPPI_AI_SEATS="1:incumbent,2:search,3:incumbent" \
        ~/.venvs/tuppi-v2/bin/python tools/serve_human.py [--lan] [--port 8766]

Rules: TUPPI_SERVER_RULESET, default project_target_v3 (the real game: locked
bids and sooli). That needs a TuppiProject with project_target_v3 (the
tuppi-v2 environment points at that branch) and the matching TuppiClient
build; set project_target_v1 to play the earlier rules with the tuppi-ai
environment. The search seats play sooli themselves; incumbent seats use
TuppiProject's simple sooli fallback (they never offer sooli).

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
os.environ.setdefault("TUPPI_SERVER_RULESET", "project_target_v3")
# One data directory per seat plan and ruleset, so the report knows who sat
# where and a server on other rules never meets these room records.
_SLUG = "_".join(p.replace(":", "-") for p in sorted(os.environ["TUPPI_AI_SEATS"].split(",")))
if os.environ["TUPPI_SERVER_RULESET"] != "project_target_v1":
    _SLUG += "_" + os.environ["TUPPI_SERVER_RULESET"]
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
    if os.environ.get("TUPPI_AI_REVIEW", "1") == "1":
        # After-deal review of the human's own decisions by the best agent's search.
        from tuppi_ai.review import ServerReviewer
        app.app.rooms.deal_reviewer = ServerReviewer()
    print(f"TuppiAI seat plan: {plan}; best agent ({ROLLOUT.name}, W={worlds}); "
          f"rules {os.environ['TUPPI_SERVER_RULESET']}; review "
          f"{'on' if os.environ.get('TUPPI_AI_REVIEW', '1') == '1' else 'off'}")
    print(f"server data dir: {os.environ['TUPPI_SERVER_DATA_DIR']}")
    app.main(sys.argv[1:])


if __name__ == "__main__":
    main()
