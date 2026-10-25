# Qualification files

- `reference-w128.json`, `reference-w1024.json`, `lite-reference.json`, `heidi-reference.json`,
  `compact-reference.json`: frozen references for the unchanged bots (legacy search, plain lite,
  Nelli 1.0, Heidi 1.1); unchanged by this release.
- `heidi12-reference.json` (Nelli 1.1, Python `LiteAgent(C1H, MODEL_V4)`) and
  `compact-reference-heidi12.json` (Heidi 1.2, WASM mode 4: the new network as the anchor only,
  VRPO3 the play-inference likelihood model, VRPO1 the rollouts) are generated from the network in
  `ai/models/vrpo4_final.pt` (sha256 0e980b4f3344...). They come from the final weights.
- `qualify*.py`, `package_lite.py`, `export_reference.py`, `run_reference.py`: the scripts the
  Dockerfile runs (see the Dockerfile for the exact commands).
- `heidi11-browser.json`, `browser-speed.json`, `hosted-heidi.json`: records of earlier releases.
- `heidi12-release.json`: this release's checks (browser, server, Linux image).
