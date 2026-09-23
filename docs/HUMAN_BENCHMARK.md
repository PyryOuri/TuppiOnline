# Human benchmark: playing with and against TuppiAI

The only way to learn whether the bot is strong *for people* is people. This
uses TuppiProject's own server and the Swift client unchanged; only the AI
seats are swapped, and all server state goes to `TuppiAI/runs/human_server`,
so your normal rooms and history are not touched.

## Start the server

```sh
cd /Users/pyryouri/Developer/TuppiAI
TUPPI_AI_SEATS="1:incumbent,2:search,3:incumbent" \
  ~/.venvs/tuppi-v2/bin/python tools/serve_human.py          # add --lan for another device
```

This plays the real game, `project_target_v3`: locked bids (you lock your bid
without seeing anyone's; the bids are revealed in order once everyone has
locked) and sooli (after a RAMI the defenders are asked in turn). It needs the
TuppiProject branch `rules/project-target-v3-locked-bids` (the `tuppi-v2`
environment points at that worktree, `TuppiProject-sooli`) and a client built
from the TuppiClient branch `feature/v3-locked-bids-sooli` (worktree
`TuppiClient-v3`: `DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
swift run`). For the old rules use `TUPPI_SERVER_RULESET=project_target_v1`
with `~/.venvs/tuppi-ai`. Search seats play sooli themselves; incumbent seats
never offer sooli. The deal and match analysis buttons are hidden in v3 rooms
(the analysis is built for v1 deals).

After each deal the table bar shows the bot's review of your own decisions
("Jako N: 2 selvää virhettä"): the clear mistakes only, re-decided from what
you knew at the time. `TUPPI_AI_REVIEW=0` turns it off.

It listens on port **8766** (the normal server uses 8765), so point the client
at `http://127.0.0.1:8766`. Create a room with three AI seats; you are seat 0.

Seat plans worth playing (seat 2 is your partner, 1 and 3 are opponents):

| Plan | `TUPPI_AI_SEATS` | What it measures |
| --- | --- | --- |
| A | `1:incumbent,2:search,3:incumbent` | you + new bot vs the old bot |
| B | `1:search,2:incumbent,3:search` | you + old bot vs the new bot |
| C | `1:search,2:search,3:search` | you + new bot vs the new bot (hardest table) |

Decisions take about 0.1-0.7 s; the server's own 5 s pacing
(`TUPPI_SERVER_AI_ACTION_DELAY_SECONDS`) still applies and can be lowered.

## Caveat about labels

The network protocol only allows the AI profile names `partner_aware_v1` and
`partner_aware_lead_v2`, so the client will label TuppiAI seats as
`partner_aware_lead_v2`. Sessions against this server land in the client's
local archive like any other; note the dates you played here, or the room
codes, so they can be separated from normal play.

## How results will be read

Every deal you play is stored with its full shuffle. Afterwards each deal is
replayed with a bot in your seat on the same cards (same partner, same
opponents), and your seat's match-equity change is compared with the bot's:
a duplicate comparison, so luck of the cards cancels. With a few hundred deals
this detects only large differences (roughly +-0.006 equity/deal at 95%), which
is exactly the question: is either of us far ahead?
