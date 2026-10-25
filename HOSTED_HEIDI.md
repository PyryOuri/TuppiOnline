# One hosted search table on the existing service

Release 3 offers Nelli 1.1 and Heidi 1.2 for new rooms (last section); the sections before it
describe the table as released in releases 1 and 2, and still hold for saved Heidi 1.1 rooms.

The image keeps `TUPPI_HOSTED_BOT_LEVEL=lite`. The old TuppiAI bot stays the
default in the browser menus. Nelli 1.0 remains available, and Heidi 1.1 is an
explicit online choice. Its profile is `tuppi_ai_heidi10_pib8_v1`: unchanged
W1024/PIB8, flat VRPO1/VRPO3 models, human T4/epsilon 0.8 and the existing tail
and bid rules. No PyTorch is installed in the final image.

The candidate adds fast-plan Stage 1: identical seat/holding history rows are
scored once and reused, with the same candidate and RNG streams. The hosted
OpenBLAS build is a new numerical identity because batching changes; fixed
reference qualification is required before release. No new model or reduced
search profile is introduced. Published browser WASM remains unchanged.

At most one unfinished Heidi 1.1 table is admitted. Paused, idle and temporarily
human-only Heidi tables keep their slot. Finish or close that table to free
it. Other rooms use their selected lite bots. A busy table never silently
switches to a weaker bot.

The dedicated native worker holds shared weights and serves Heidi seats
serially. The server sends only the acting seat's legal observation, current
human seats and private RNG/sooli cursor. A move is acknowledged after it is
saved. The worker timeout is 90 seconds; a timeout preserves the last committed
cursor and restarts the owned worker on the next request.

`TUPPI_HOSTED_HEIDI10=0` disables new Heidi offers while allowing existing
rooms to recover. New Heidi rooms use room-record v7. Before rolling back to
a server that only supports v1-v6, finish/close those trial rooms; an old
server cannot read v7. Do not rewrite their controllers as lite or PIB4.

This release also includes the owner's website hardening: per-client limits,
Content-Security-Policy and report counts, threaded room saves, released viewer
runtimes and the pinned Python base image. The immutable browser runtimes from
earlier releases remain served.

Qualification scopes and measured local limits are in
`qualification/hosted-heidi.json`. The resource fixture uses 0.5 CPU, 512 MiB
and no swap; it is an engineering trial, not a prediction of Render hardware
latency or a playing-strength result. Render deployment and physical-device
acceptance remain owner-run. The Blueprint's existing instance, disk and paid
resource settings are unchanged; automatic deploy is off.

## Names (release 2, 23 October 2026)

The online search bot (`tuppi_ai_heidi10_pib8_v1`) is shown as Heidi 1.1 and the
lite bot (`tuppi_ai_lite_c1h_v1`) as Nelli 1.0, formerly Heidi 1.0 and Heidi 0.5.
Only display names changed: profile keys, room records, flags such as
`TUPPI_HOSTED_HEIDI10` and decisions are the same. Locally, new Heidi games are
Heidi 1.1 (bot id `heidi11`) on the faster browser engine; Heidi 1.0 saves
continue on their retained engine.

## Heidi 1.2 and Nelli 1.1 (release 3)

New rooms offer TuppiAI (default), Nelli 1.1 and Heidi 1.2; Nelli 1.0 and Heidi 1.1 are no
longer offered but every saved room keeps its bot and name, and `POST /v1/rooms` still
accepts their keys. The new base network is a 768x4 QNet (`vrpo4_final`); in this package it is
the final VRPO4 actor. Nelli 1.1 is Nelli 1.0 (lite C1H) with the new network as its policy and safety-net
belief. Heidi 1.2 is Heidi 1.1 with the new network as its anchor only (the keep rule for bids and
play): its play-inference likelihood model stays VRPO3 and its rollouts VRPO1, so it searches
exactly as Heidi 1.1 and differs only where the two anchors' argmax differs.

| Profile key | Shown as | Bot | New rooms |
|---|---|---|---|
| `tuppi_ai_search_v1` | TuppiAI | hosted plain lite | offered (default) |
| `tuppi_ai_lite_c1h_v2` | Nelli 1.1 | lite C1H on `vrpo4_final.lite.npz` | offered |
| `tuppi_ai_heidi12_pib8_v1` | Heidi 1.2 | compact worker mode 4 (new network as the anchor only), W1024, PIB8 | offered when `TUPPI_HOSTED_HEIDI10=1` |
| `tuppi_ai_lite_c1h_v1` | Nelli 1.0 | unchanged | saved rooms only |
| `tuppi_ai_heidi10_pib8_v1` | Heidi 1.1 | unchanged (compact worker mode 2) | saved rooms only |

Flags are unchanged. `TUPPI_HOSTED_HEIDI10=1` (set in the image) starts the one compact worker
and enables both search profiles; `0` stops offering Heidi 1.2 and refuses new rooms with either
search key while saved rooms stay readable. The worker serves Heidi 1.1 and Heidi 1.2 tables, one
decision at a time, and at most one unfinished search table of either key is admitted
(`heidi_busy`). Heidi 1.2 checkpoints are `tuppi.hosted.controller.heidi12.v1`; Heidi 1.1
checkpoints keep `tuppi.hosted.controller.heidi10.v1` and, saved by the previous release under
manifest `8cb282aa...`, restore when the present manifest without the new network has that hash.
Room records reuse v6 (lite) and v7 (search); a server older than this release refuses a room
with a new key, so finish or close Nelli 1.1 and Heidi 1.2 rooms before a rollback.

The hosted `ai/` now carries the same native controller as the browser (TuppiAI
593589d, three network roles), the compact directory has three networks
(manifest sha256 `7df039e64004...`) and the lite package lists
`vrpo4_final.lite.npz`. The image qualifies modes 2 and 4 of the compact controller and both
Nelli bots in the final, PyTorch-free filesystem. New browser games offer Nelli 1.1 and Heidi
1.2 (runtime `d0ef4461...`); the four earlier runtimes stay served byte-identical.
Render deployment and physical-device acceptance remain owner-run.
