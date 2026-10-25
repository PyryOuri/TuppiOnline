# Browser source snapshot

The hosted AI package in `ai/` and the current browser runtime (Heidi 1.2 and Nelli 1.1,
runtime `d0ef4461...`) are both built from TuppiAI 593589d
(TuppiAI-heidi12-20261023: the Heidi 1.1 source with a third network role), with the build and
memory-glue tools of TuppiBrowser-heidi12-20261023. The hosted `ai/` therefore moves from the
release 1 hosted source (4a0d44e) to the same native controller the browser uses.

Retained runtimes keep their snapshots beside this one: Heidi 1.1 (31426bbf...) from
b30763c (TuppiAI-heidi11-20261023), Heidi 1.0 PIB8 (4341014e...) from c44dfbe
(TuppiAI-heidi-speed-20261022). These files preserve the workspace paths used in each
runtime's build manifest.

SOURCE.json records the browser AI commits and maps every compiler input into this
snapshot. Each runtime's build.json records the compiler version, commands and output
hashes. Rebuilding uses the pinned Emscripten 6.0.12 toolchain under toolchains/emsdk in
the restored workspace layout.
