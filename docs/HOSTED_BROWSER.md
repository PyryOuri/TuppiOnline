# Hosted browser candidate

This checkout is isolated from `TuppiProject-current`; no live service was
restarted. The game protocol remains `tuppi.network.v1`, ruleset v3.

Run `tuppi_server.hosted_site:create_hosted_site` with one ASGI worker and the
prepared container's environment. It serves the prebuilt browser and the
existing room API from the same HTTPS origin. Only the origin declared by
`TUPPI_BROWSER_ORIGINS` or Render's `RENDER_EXTERNAL_URL` is accepted from
browsers. Native clients without Origin continue using seat credentials.

The initial boundary admits eight active rooms, 32 retained rooms, 32 sockets and one active
bot-filled match. Requests are size/time bounded. Idle lobbies are archived
after one day, idle playing/completed rooms after seven days; connected rooms
and active jobs are preserved. At the retention limit, the oldest disconnected completed room is archived
to admit a new match. Completed rooms do not consume active room capacity.
Archived records remain private for operator
recovery. Deployments must budget archive/backup storage separately.

Two admission threads feed one spawned native bot process. Reusable controllers
restore each room's own cursor before searching. Hosted match record v5 stores
those cursors privately; v1–v4 remain readable. An old v4 record has no trained
controller cursor and therefore cannot promise the same future random stream.
Unrevealed human bids remain ephemeral as in the existing contract: after a
server restart, players may need to lock those bids again. Revealed actions and
public history are replayed and validated. None of these private fields enter
player observations.

Room joins/configuration are locked after startup, seating changes clear
readiness, and HTTP changes broadcast the new lobby. Per-room locks order
authentication, configuration, ready/actions and bot continuation. Disconnect
errors in one socket do not abort broadcasts to other players. Checkpoints
persist applied human/bot actions before broadcasting; recovery at the final
human card preserves the exact deal boundary.

Hosted startup requires the trained profile, W1024, frozen model hashes and
successful bot initialisation. Review, training analysis and sooli odds APIs
are disabled for this candidate. No heuristic substitution is allowed.

The local Node/ASGI tests complete matches with 1–4 simulated humans and the
remaining seats handled by the first-legal transport fixture. These checks
cover transport/privacy/reconnect/reload/restart, not trained-bot strength.
Separate synthetic W128/W1024 comparisons qualify the trained controller.
Linux execution, capacity and physical Swift/browser/iPhone acceptance remain
release gates. See the workspace implementation report for current results.
