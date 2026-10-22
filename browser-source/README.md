# Browser source snapshot

The hosted AI package in `ai/` remains the deployed 2b3681a source.
The browser WASM uses c44dfbe from TuppiAI-heidi-speed-20261022, with the
build and memory-glue tools from TuppiBrowser-heidi-speed-20261022.
These files preserve the workspace paths used in the runtime build manifest.

SOURCE.json records the browser AI commit and maps every compiler input
into this snapshot. The runtime build.json records compiler version, commands
and output hashes. Rebuilding uses the pinned Emscripten 6.0.12 toolchain
under toolchains/emsdk in the restored workspace layout. Model weights are
unchanged and are included in ai/models and the versioned web runtime.
