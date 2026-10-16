# Tuppi research

This branch (`research`) is the index of the Tuppi bot-strength research. The
code lives in this same repository on separate branches, with their full
history. `main` is the Render deploy package and is not touched by research.

Backed up on 2026-10-16 from the owner's workspace.

## Where the code is

| Branch prefix | Local repository | What it is |
|---|---|---|
| `ai/*` | `TuppiAI` | The bot: native C engine and search (`native/`), Python bridge, self-play and VRPO training, value nets, trained models (`models/`) |
| `engine/*` | `TuppiProject` | Authoritative Python rules engine (`tuppi_rules`, `tuppi_engine`), evaluation and match tooling, heuristic agents, the online server (`tuppi_server`) |

### Bot (`ai/…`)

| Branch | Contents |
|---|---|
| `ai/sp/selfplay` | Self-play SP1 and VRPO1–3 (privileged-critic) training. **VRPO3 is the live policy anchor.** Strength work parked 2026-10-01. Plans: `docs/SELFPLAY_PLAN.md`, `docs/SCALING_PLAN.md`. |
| `ai/perf/e6-e9` | Exact search speed-ups (E0–E9; adaptive bids above 128 worlds, live). |
| `ai/maintenance/compact128-port-20261014` | compact128 search (bit-identical to the reference on 200 W1024 deals). |
| `ai/maintenance/hosted-bot-20261014` | The PyTorch-free **lite** bot (VRPO3 policy, no search) that the online server uses. |
| `ai/maintenance/offline-browser-20261013` | Portable SIMD/WASM runtime and browser controller (the offline app's bot). |
| `ai/research/policy-prior-infra-20261002` | Policy-prior search, paired comparisons and frozen evaluation queues (infrastructure; runtime validation deferred). |
| `ai/vn/value-net` | Value-net work and the fast sooli offer model. |
| `ai/main` | Main line (strong opponent model deployed, robustness P1b). |
| `ai/wip/research-snapshot-20261016` | **Unreviewed** snapshot of uncommitted work in the main checkout: the C0–C5 research implementation (`tuppi_ai/research`, `native/research`, `tests/research`). |

### Rules engine and server (`engine/…`)

| Branch | Contents |
|---|---|
| `engine/rules/project-target-v3-locked-bids` | **Current rules (v3: locked bids, sooli)** and the `partner_aware_lead_v3` heuristic. |
| `engine/rules/project-target-v2-sooli` | Sooli phases (v2). |
| `engine/heur/partner-aware-lead-v3` | The v3 heuristic programme. |
| `engine/phase7/reference-policy-identity` | The earlier research checkout (Phase 7 decision corpus). |
| `engine/experiment/rami-nolo-threshold` | The RAMI–NOLO threshold experiment. |
| `engine/feature/bot-cover-20261016` | The online server as deployed in round 9: rooms, rematch, pause, concede, lobby fixes, bot stand-ins, anonymous results (`results.jsonl`). |
| other `engine/feature/*`, `engine/maintenance/*` | Earlier steps of the online server; kept for history. |

## Reports (`reports/` in this branch)

These are the research plans and results, copied from the workspace's
`audit_deliverables` (text and result files only).

- **Self-play:** `tuppi_selfplay_research_20260929`,
  `tuppi_selfplay_independent_20260929`.
- **Search speed and exactness:** `tuppi_speed_*`, `tuppi_cheap_wins_*`,
  `tuppi_additional_exact_wins_20261014`.
- **The lite bot level:** `tuppi_lite_bot_20261014`.
- **C0–C5 research contract:** `TUPPI_IMPLEMENTATION_HANDOFF.md` and
  `tuppi_implementation_*`. Also `tuppi_design_*`, `tuppi_codebase_review_*`,
  `tuppi_experiment_tools_*` and `tuppi_policy_prior_infrastructure_*`.
- **RAMI:** `rami_five_legs_*`, `rami_threshold_bank_*`.
- **Strength against people (2026-10-16):**
  - `tuppi_expert_strength_20261016`: the move-by-move analysis plan and
    scripts.
  - `tuppi_expert_duplicate_20261016`: the duplicate replay of the expert's
    deals with a bot in their seat, as scripts.
- `WORKSPACE_AGENTS.md`: the workspace's task index. It points to local paths
  and registers each work item.

### Deliberately not included

- **Player data:** the expert's save, the analyses and replays of it, and
  friend-test data. These stay on the owner's Mac.
- **Training runs:** about 34 GB in `runs/`.
- **Archives:** `.zip` packages, logs and large data files.

## Current state of the strength research (2026-10-16)

- **The expert match.** One unfinished match: an expert player with a bot
  partner against two bots, at 1024 worlds. The expert's team won 21 of 36
  deals, and the tricks were 234–234. The bot is not clearly stronger than
  the expert.
- **The main known weakness.** The search samples hidden hands uniformly,
  subject only to hard constraints: shown cards, cards played and voids.
  It draws no inference from how players bid or play. See
  `ai/…/native/tuppi_search.c` (`tc_sample_world`). This also means the bot
  cannot read a partner's convention.
- **Step 1, in progress.** A duplicate replay of the expert's deals: the
  same cards, a bot in the expert's seat, 8 seeds per deal, against a
  bot-seed noise floor.
- **Step 2, approved later.** Play-inference: weight sampled hands by how
  likely the observed bids and plays are under the bot's own policy.
- **Later steps.** Partnership conventions (use and read), RAMI calibration
  against strong defence, and more self-play.

**Testing protocol:** screen at 128 worlds; confirm at 1024 only those that
pass, or changes sensitive to the world count.

## Setting up

- **Python 3.14** with PyTorch for training. The online server needs only
  the standard library plus `uvicorn`.
- **Native engine:** `sh native/build.sh` in an `ai/*` checkout (`--blas`
  for OpenBLAS on Linux).
- **Running both together:** put `engine/src` and the `ai` checkout on
  `PYTHONPATH`, as the server tests do:
  `PYTHONPATH=src:../TuppiAI-hosted pytest tests/server`.
- **The browser runtime (WASM):** build it from `ai/maintenance/offline-browser-20261013`
  with the pinned Emscripten SDK, as in TuppiBrowser's `tools/build.py`.
