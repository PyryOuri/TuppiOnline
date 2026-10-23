# Browser source snapshot

The hosted AI package in `ai/` is the release 1 hosted source (TuppiAI 4a0d44e:
compact controller with distinct (seat, hand) scoring), unchanged in release 2.

The current browser runtime (Heidi 1.1) is built from TuppiAI b30763c
(TuppiAI-heidi11-20261023: the Heidi table release merged with the Heidi fast
plan) with the build and memory-glue tools of TuppiBrowser-heidi11-20261023.
The retained Heidi 1.0 runtime (4341014e...) was built from c44dfbe
(TuppiAI-heidi-speed-20261022); its snapshot is kept beside it.
These files preserve the workspace paths used in each runtime's build manifest.

SOURCE.json records the browser AI commits and maps every compiler input into
this snapshot. Each runtime's build.json records the compiler version, commands
and output hashes. Rebuilding uses the pinned Emscripten 6.0.12 toolchain under
toolchains/emsdk in the restored workspace layout. Model weights are unchanged.
