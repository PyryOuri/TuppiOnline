# One Heidi 1.0 table on the existing service

The image keeps `TUPPI_HOSTED_BOT_LEVEL=lite`. The old TuppiAI bot stays the
default in the browser menus. Heidi 0.5 remains available, and Heidi 1.0 is an
explicit online choice. Its profile is `tuppi_ai_heidi10_pib8_v1`: unchanged
W1024/PIB8, flat VRPO1/VRPO3 models, human T4/epsilon 0.8 and the existing tail
and bid rules. No PyTorch is installed in the final image.

The candidate adds fast-plan Stage 1: identical seat/holding history rows are
scored once and reused, with the same candidate and RNG streams. The hosted
OpenBLAS build is a new numerical identity because batching changes; fixed
reference qualification is required before release. No new model or reduced
search profile is introduced. Published browser WASM remains unchanged.

At most one unfinished Heidi 1.0 table is admitted. Paused, idle and temporarily
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
