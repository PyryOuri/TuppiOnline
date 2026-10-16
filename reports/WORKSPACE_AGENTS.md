# Tuppi task discovery

For the pre-round expert-save strength review, read
`audit_deliverables/tuppi_expert_strength_20261016/REPORT.md` and
`POSITIONS.md`. Registered 2026-10-16: the owner's supplied local backup
contains one unfinished W1024 match, 36 completed deals (human plus bot won
21, two bots won 15). All recorded human choices with options (416) were
reviewed using the unchanged original runtime; 401 are below the app's 0.01
recommendation-gap cutoff. Twelve largest disagreements were repeated:
11 remain at least 0.01, none at least 0.04 in both seeds. This is a local
model-based review, not an overall human/bot strength ranking. Original data
is unchanged and remains local; no training, upload or deployment.
Partner-convention work is paused for this discussion. Its uncommitted,
unqualified prototype is isolated in `TuppiBrowser-pre-round`, branch
`pre-round/partner-conventions-20261016` from `9f28aa9`; see
`audit_deliverables/tuppi_pre_round_conventions_20261016/STATUS.md`.
Do not integrate or publish that prototype as a numbered round. Refresh
the product baseline and finish qualification when this work resumes.

For round 9 (a bot plays for a player who is away during a match), read
`audit_deliverables/tuppi_round9_standin_20261016/REPORT.md`. Registered
2026-10-16.

- **Server:** `TuppiProject-round6`, branch `feature/bot-cover-20261016`
  (`39118bc`).
- **Browser:** `TuppiBrowser-round7`, branch `feature/bot-cover-20261016`
  (`fafaaa4`).
- **Deploy repo:** pushed on the owner's instruction (2026-10-16). GitHub
  `main` is round 9 (`f050546`), on round 8 (`4490f5d`). The live service
  changes only when the owner presses Manual Deploy.

For round 8 (every player's dealt hands in the deal analysis), read
`audit_deliverables/tuppi_round8_hands_20261016/REPORT.md`. Registered
2026-10-16. The browser change is in worktree `TuppiBrowser-round7`, branch
`feature/all-hands-20261016` (`9f28aa9`). The deploy repo's local branch
`round8` (`4490f5d`) was pushed with round 9 (GitHub `main` = `f050546`).

For rounds 6 and 7 (owner requests 2026-10-16), read
`audit_deliverables/tuppi_round6_lobby_20261016/REPORT.md` and
`audit_deliverables/tuppi_round7_analysis_20261016/REPORT.md`.

- **Round 6:** lobby rename and host seat release, the fast offline bot by
  default, conceding a deal already decided at 0-0, and anonymous research
  results (`results.jsonl`).
- **Round 7:** analysis of a finished deal on the device with the
  full-search bot.

Worktrees:

- server `TuppiProject-round6` (`91a1351`, branch
  `feature/lobby-seats-20261016`);
- browser `TuppiBrowser-round6` (`2fab2c6`);
- browser `TuppiBrowser-round7` (`c33b3b7`, branch
  `feature/deal-analysis-20261016`).

Pushed on the owner's instruction (2026-10-16): GitHub `main` is round 7
(`94667f7`, on top of round 6 `daa4146`). The live service changes only when
the owner presses Manual Deploy. All image and upgrade
checks pass; device rendering is pending. Owner decisions: no "report a
problem" button and no Render test service.

For round 5 (Codex's entry flow merged with round 4), read
`audit_deliverables/tuppi_round5_integration_20261016/REPORT.md`. Registered
2026-10-16: TuppiBrowser worktree `TuppiBrowser-round5`, branch
`integration/round5-entry-flow-20261016` (`1597af1`). The deploy repo's local
branch `round5` (`cd940a2`) was pushed on the owner's instruction (2026-10-16): GitHub `main` = `cd940a2`. The live service updates only when the owner presses Manual Deploy. Its image passed the image check and
upgrades from `ff868e6` and from round 4. Real-phone review of the new entry
screens is pending.

For round 4 (safe redeploys and anonymous usage), read
`audit_deliverables/tuppi_round4_ops_20261016/REPORT.md`. Registered
2026-10-16 while friends test the live Render service (`ff868e6`). It fixes a
live bug (8 abandoned rooms refused every new room), adds an anonymous usage
line a minute in the logs, and makes clients show server restarts and fetch
newer releases. The image passed the image check and an upgrade from the live
image with an old-client tab and an in-flight move. Server worktree
`TuppiProject-round4` and browser worktree `TuppiBrowser-round4` are both on
branch `feature/round4-ops-20261016`. Pushed on the owner's instruction
2026-10-16: GitHub `main` = `60f7ea2` (round 4). The live service keeps running
`ff868e6` until the owner presses Manual Deploy (auto-deploy is off). Owner decisions: no "report a
problem" button and no Render test service. Redeploy only between games.

For the simpler online/offline entry candidate, read
`audit_deliverables/tuppi_entry_flow_20261016/REPORT.md` and `CANDIDATE.json`.
Registered 2026-10-16: `TuppiBrowser-entry-flow`, branch
`feature/entry-flow-20261016`, commit `264d8c2` (after `f687d41` and the first
UI pass `e80fcf5`), adds a deliberate home screen, focused invitation joining,
one join/create form, direct saved-game continuation and less table clutter.
Both release variants pass 47 bounded checks with unchanged runtime/engine
identity. No browser/device visual acceptance was performed. Not merged,
pushed or deployed. Concurrent round-4 commit `49c0b22` is preserved separately
and not included; keep its restart/update hooks during coordinated integration
and rerun both sets of checks. The live Render service was untouched.

For the isolated UI quality candidate, read
`audit_deliverables/tuppi_ui_quality_20261016/REPORT.md` and `CANDIDATE.json`.
Registered 2026-10-16: `TuppiBrowser-ui-quality`, branch
`feature/ui-quality-20261016`, commit `e80fcf5` on `e8736fd`, adds modal grouped
settings, clearer join/create and lobby actions, team scores, readable card
states, named confirmation and retained replay/table nodes. Both release
variants pass 28 bounded checks with unchanged runtime/engine identity.
No browser/device visual acceptance was performed. Not merged, pushed or
deployed. Preserve concurrent `TuppiBrowser-round4` work, especially its
`app.mjs` edits; integrate on a coordinated branch and rerun checks.

For the GitHub deployment repository and DEP-01, read
`audit_deliverables/tuppi_render_blueprint_fix_20261015/implementation/REPORT.md`.
Registered 2026-10-16: `deploy/TuppiNetwork-render` has remote
`PyryOuri/TuppiOnline` (private; set up by the owner's other session). The
DEP-01 fix, which drops `maxShutdownDelaySeconds` on the disk-backed service
and sets a 10 s drain, is pushed as `4fd112b` on GitHub `main`. Its image
passed the restart and recovery check at 0.5 CPU / 512 MB. `ff868e6` (round 3:
leaderboard, compact results, accessibility) was pushed on the owner's
instruction after its image passed the same check. GitHub `main` =
`ff868e6`. Updated 2026-10-16: Render accepted the Blueprint; the owner's
Render service is LIVE from `ff868e6` and the link is shared with friends for
online play (issue #1 closed). `autoDeployTrigger: off`, so a push does not
redeploy, but push nothing without the owner, and treat any redeploy or
restart as interrupting real players.

For deploying to Render, start with
`audit_deliverables/tuppi_render_readiness_20261015/REPORT.md`. Registered
2026-10-15: the owner chose Render Starter (`0.5c-512mb` plus a 1 GB disk,
about $7.25/month), a room-creation passcode (`TUPPI_ROOM_PASSCODE`, a Render
secret) and a publicly downloadable bot. The deploy repository is
`deploy/TuppiNetwork-render`, local `main` `6068bd1`, with no remote, built
from browser `acbfc44`, engine `9f62215` and ai `d573b63`. It adds a
per-nickname leaderboard, compact end-of-match updates and the accessibility
fixes, on top of round 2: persisted locked bids, storage safety,
stalled-connection timeouts, match summary and help. Image
`tuppi-online:render3` passed at 0.5 CPU / 512 MB (report "Round 3"). The
loopback test now refuses a busy port 18740; runs between 2026-10-15 16:32
and the fix had hit a stale server and were repeated.
The owner will create the GitHub repository and Render service later. Nothing
is uploaded or deployed.

For the second friend test (merged phone/lobby/pause/rematch build), read
`audit_deliverables/tuppi_friend_test2_20261015/README.md`. Registered
2026-10-15: server `feature/browser-network-20261014` at `7dff3a9` and
TuppiBrowser `development/phone-surface-20261015` and `main` at `fe4ea2d`
(fast-forwards). A frozen build in `.tuppi-friend-test-2/frozen` passed a
loopback preflight. No tunnel or host is running; starting one needs the
owner's go-ahead and both email addresses. Keep the first pilot's data.

For host pause/resume and same-group rematch (BE-01/FR-04), read
`audit_deliverables/tuppi_rematch_pause_20261015/REPORT.md`. Registered
2026-10-15: server branch TuppiProject-browser-network
`feature/rematch-pause-20261015` (`7dff3a9`) and client branch TuppiBrowser
`feature/rematch-pause-ui-20261015` (`fe4ea2d`, on the phone candidate). Host-only
commands are gated by `hello_ack.features`. Pause lands between committed
actions; rematch keeps seats and a result summary and starts a new match
identity. Rooms that use either write room_record.v4. Server, schema, app and
loopback lite-bot tests pass. The phone candidate
`development/phone-surface-20261015` now includes the move-placed fix
(`a24afe5`). Unmerged and unpublished; phone acceptance is pending.

For the server performance baseline (OBS-01), start with
`audit_deliverables/tuppi_server_baseline_20261015/REPORT.md`. Registered
2026-10-15: measurement only, loopback on this Mac with the lite bot and the
real network client. Eight paced rooms use under 10% of one core. The main
player-facing delay is the acknowledgement, which waits for paced bot
replies (p95 2.2 s, while the move is visible in ~23 ms). Full-record saves
grow quadratically with match length (a 119-deal scripted match reached
8.7 MB records, 1.1 s loop stalls and 700 MB). The final update carries an
unused 0.2–5.6 MB `match_result`. Unmerged branches: TuppiBrowser
`feature/move-placed-20261015` `a24afe5` (shows the move as placed; recommended
for the phone candidate) and TuppiProject-browser-network
`feature/static-streaming-20261015` `048f760` (no measured benefit; do not
merge). Nothing was published or deployed.

For the next private-friends UI milestone, read
`audit_deliverables/tuppi_private_friends_ui_20261015/REPORT.md` and
`VALIDATION_SUMMARY.json`. Registered 2026-10-15: the owner reports successful
bot addition and friend play on the frozen pilot (USER_ACCEPTANCE.json in the
pilot directory). Candidate `TuppiBrowser-phone` commit `3e1f1da` adds explicit
team/readiness lobby cards, optional nickname/hand preferences, invite-copy
fallback, connection states and deliberate login/reconnect controls. Twenty-seven
source/package checks and a separate complete lite-bot HTTP/WSS fixture with
restart/rejoin pass. New phone/lobby visual and lifecycle acceptance remains
pending. The live pilot on18840 was left running unchanged; do not replace it,
stop it or publish this candidate during their session. Hosting is undecided.

For the active protected friend pilot and first shared-release/phone candidate,
start with `audit_deliverables/tuppi_friend_pilot_20261015/REPORT.md` and
`audit_deliverables/tuppi_phone_implementation_20261015/REPORT.md`.
Registered 2026-10-15: the email-protected temporary tunnel and Mac lite host
are running from `.tuppi-friend-test/frozen`; consult `RUNNING.json` before any
process action. Safari's fetch receiver was repaired; two human WebSockets
connected. After HTTP401 recovery guidance, the owner confirms bot addition and
successful friend play (USER_ACCEPTANCE.json); terminal-match and deliberate
recovery checklist results have not been explicitly reported. Source `TuppiBrowser`
contains pilot hotfixes. `TuppiBrowser-phone`, branch
`development/phone-surface-20261015`, contains shared offline/network packaging,
adaptive portrait hand and initial compact phone composition. Automated checks
pass; new phone/device visual acceptance is pending. Do not insert development
changes into the active pilot or change hosting/audience. Preserve sealed prior
plans/recovery evidence. Restart approvals obtained so far covered their
specific restarts; do not assume permission to stop the active session.

For the same-Wi-Fi friend pilot and subsequent phone/private-friends development
programme, start with `audit_deliverables/tuppi_web_development_plan_20261015/README.md`.
Registered 2026-10-15: the owner selected two humans as partners plus two lite
bots for the first test and private games with friends as the audience. The
package contains the exact Mac/temporary protected-HTTPS recipe, a phone layout
specification, backend measurement/optimisation plan and a dependency-ordered
28-task backlog. A no-port in-process Mac lite/configuration/asset preflight
passes; protected email login, iPhone WSS and actual friend play remain pending.
The tunnel client was not found on PATH. No tunnel, sharing change, hosting
selection, product implementation or research programme was started. Follow the
user's next assignment; preserve the current source and prior evidence.

For offline updates and saved-game recovery, read
`audit_deliverables/tuppi_offline_recovery_20261015/REPORT.md` and `VALIDATION.json`.
Registered 2026-10-15: browser `7b0e774` and offline-only `b19a959` add explicit
original-save/current-installed-engine choices, one atomic previous-match copy,
backup access and verified same-worker cache repair. Original save state, RNG,
models and engine are unchanged. Both current and recovery saves protect their
runtimes. The owner-private Site source is `a087715`; all 29 prior immutable
files remain. Twenty-seven source/package/real-WASM gates and 56 authenticated
HTTPS file/MIME checks pass. New controls have no direct browser/device UI
validation; the earlier user iPhone acceptance remains recorded separately.
Close all Tuppi windows and reopen when a waiting-update notice appears. Hosting
remains undecided; no network server, audience change or research was activated.

For the slim hosted lite runtime, read
`audit_deliverables/tuppi_slim_lite_20261015/REPORT.md` and `VALIDATION.json`.
Registered 2026-10-15: browser `39bd7ca` and hosted engine `3df94ec` contain the
qualified default lite-only Docker runtime and strict level-specific model
manifests; a full-search build target remains available. Image size fell from
489,785,960 to 117,927,963 bytes (75.9%). Final-filesystem checks pass without
PyTorch or compilers, including 500 deals/28,036 exact actions and uint64 cursors.
Fresh game recovery, old-lite to slim midgame volume upgrade and three paired
startup measurements pass. Use `deploy/TuppiNetwork-slim-exact`; the earlier
`TuppiNetwork-slim` context is a preserved failed-reference attempt. The corrected
fixture uses the original lossless Python reference; diagnostic cursors are
strings to avoid JavaScript rounding. Original models, offline assets, prior
evidence and the live product are unchanged. Hosting and real-device network
acceptance remain separate; no service or upload was performed. The local VM
is stopped and owned test fixtures removed.

For the hosted bot level, start with
`audit_deliverables/tuppi_lite_bot_20261014/REPORT.md`. Registered 2026-10-14:
the owner selected the lite bot (VRPO3 policy, no search) for hosting. It uses
about 1/11,000 of W1024 CPU, is level with live W128, and scored −0.0031 per
deal against live W1024. `TUPPI_HOSTED_BOT_LEVEL=lite` is committed (2026-10-15) in
TuppiAI-hosted `d573b63`, TuppiProject-browser-network `3df4588` and
TuppiBrowser `d95bfe3`.
Parity with the evaluated bot holds on Mac (2,000 deals) and Linux (500
deals), and the local Linux image `tuppi-online:lite` passed its full check.
Hosting and device checks await the owner.

For the subsequent iPhone acceptance, read
`audit_deliverables/tuppi_iphone_acceptance_20261014/ACCEPTANCE.json`.
Registered 2026-10-14: the user reports that the iPhone tests pass and play runs
nicely on the previously selected iPhone 17 Pro Max. This is user acceptance;
the exact iOS/runtime fingerprint and per-check logs were not supplied. Preserve
the earlier sealed qualification records. The next proposed milestone is a
small real-device network alpha with bot-filled seats. Hosting remains undecided;
no temporary tunnel, new audience or paid service has been started by this note.

For the completed compact128 browser/hosted product integration, start with
`audit_deliverables/tuppi_compact128_integration_20261014/REPORT.md` and its
`VALIDATION.json`. Registered 2026-10-14: the qualified reward buckets, identical
rollout-model sharing, chunk128 and forced-row compaction are promoted into
`TuppiAI-hosted` and `TuppiBrowser`; the existing owner-private offline Site is
updated. Exact W128/W1024 and three paired W1024 rounds per backend pass, as do
19 release regressions and a complete trained Linux image game with restart,
reconnect and volume recovery. Median fixed-bank CPU reductions are 30.5% on
macOS, 41.1% on translated local Linux and 17.1% on Node WASM. These are separate
product-port measurements, not new strength or physical-device evidence. Models,
budgets, UI and the live Swift/native product are preserved. Older saves retain
their compatible runtime. Hosting and physical iPhone/native-host qualification
remain pending; no new research mechanism or paid/public network release was
activated. Preserve the original research packages and previous release evidence.

For further exact speed work on the analysis comparator, start with
`audit_deliverables/tuppi_speed_differential_20261014/HANDOFF.md`, after its
`REPORT.md`. Registered 2026-10-14: 200 fresh W1024 deals (10,904 decisions)
matched the reference bit for bit under compact128. The only non-exact
mechanism found is single-row Accelerate rounding (≤6.1e-5 in Q). The handoff
lists exact tasks: pad one-row network calls, sooli offer budget ladder, DD
bucket bounds, locked-bid row dedup. No profiling, strength runs or product
changes are authorised.

For the iPhone/offline and browser-network continuation, start with
`audit_deliverables/tuppi_offline_network_implementation_20261014/REPORT.md`.
Registered 2026-10-14: the owner-private offline HTTPS candidate is published;
the network adapter and bot-filled rooms are in `TuppiBrowser`, authoritative
host code in `TuppiProject-browser-network`, and portable/BLAS bot work in
`TuppiAI-hosted`. Source/Node/HTTP and frozen macOS W128/W1024 comparisons passed,
including a complete trained-bot loopback match. Local Linux x86-64/OpenBLAS
comparisons and a complete trained-bot image match with restart/reconnect and
replacement-container volume recovery also pass. Hosting remains undecided;
native host capacity and physical iPhone/Swift-browser acceptance remain
pending. No paid/public network release, training or live native integration
was performed. Preserve the
original research and planning packages.

These pointers apply when the user's task concerns Tuppi; they do not redirect
unrelated work in this workspace.

For current-product maintenance and the offline browser programme, start with
`audit_deliverables/tuppi_maturity_implementation_20261013/REPORT.md` and
`PRODUCT.md`. Registered 2026-10-13: release capture, cache cleanup, fixture
repairs and lazy native Python buffers are completed. Portable native work
is isolated in `TuppiAI-mature`, branch `maintenance/offline-browser-20261013`;
the local browser prototype is in `TuppiBrowser`. Synthetic WebAssembly
comparisons pass at W128 and W1024, including forced sooli probes. Actual
browser/offline/device acceptance and hosted publication remain pending.
The running server and installed app were preserved. Read the report's exact
validation boundaries before continuing; retain the original planning and
research packages.

For the coding work prepared while heuristic research occupies the CPU, start
with `audit_deliverables/tuppi_experiment_tools_20261002/IMPLEMENTATION_REPORT.md`.
Registered 2026-10-02: the follow-up implements checked paired comparisons and
frozen evaluation queues with job-boundary resume and wall-time budgets in
`TuppiAI-prior`, branch `research/policy-prior-infra-20261002`, latest commit
`0799508`. Small standard-library checks passed; runtime validation and actual
queues remain deferred. This does not authorise training or live integration.

For the preceding policy-prior and VRPO infrastructure snapshot, continue
with `audit_deliverables/tuppi_policy_prior_infrastructure_20261002/IMPLEMENTATION_REPORT.md`.
Registered 2026-10-02: isolated checkout `TuppiAI-prior`, branch
`research/policy-prior-infra-20261002`, commit `319e121` contains policy-prior
search, VRPO overhead/monitoring changes and evaluation infrastructure.
Only small standard-library checks passed; native/PyTorch validation, builds,
training and benchmarks remain deferred under the user's CPU restriction.
This is separate from the returned planning packages. Preserve those packages
and record runtime validation and results separately before live integration.

For self-play research after the first 100M programme, start with the returned
`audit_deliverables/tuppi_selfplay_research_20260929/TUPPI_SELFPLAY_STRENGTH_MAXIMISATION_PACKET.md`.
Registered 2026-09-29: this is the latest planning handoff for that programme;
it updates the adjacent `SELFPLAY_NEXT_METHODS_HANDOFF.md`, whose source
snapshot remains supporting evidence. The packet proposes repaired SP1 and
privileged-Q VRPO, with a PPO-V reference and matched-compute comparisons.
Its first step is to freeze and independently verify the current SP1 result;
refresh the actual run status and 100M accounting before drawing conclusions.
Registration is documentation-only, not validation of the proposed methods or
authorisation to train, run benchmarks, or deploy. Preserve both handoffs;
record subsequent implementation and results separately.

For the returned C0–C5 research implementation tasks, start with
`audit_deliverables/TUPPI_IMPLEMENTATION_HANDOFF.md`. It locates the immutable
implementation package, original source audit, first milestone and task DAG.
Also read `README.md` for checkout roles and `TuppiAI/docs/TASKS.md` for the
existing backlog. Do not confuse `TuppiProject-current` (v3 engine) with
`TuppiProject` (separate research checkout with concurrent work).

The 2026-09-25 handoff registration was documentation-only. Reading these
pointers does not activate the master prompt, authorise experiments, or mean
any implementation task has passed. Follow the user's current assignment;
when assigned implementation, use the package's dependency graph and gates.
Preserve both delivered packages as evidence and record subsequent progress
in a separate implementation output directory.
