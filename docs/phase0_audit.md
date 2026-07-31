# Phase 0 audit: frozen legacy prototype

This document preserves the Phase 0 findings for the two frozen files in
`Archive/`. It describes the artifact identified as `legacy_v9_unverified`; it
does not define the rules for the future engine.

## Confirmed observations

- The workspace originally contained only `Archive/tuppi_emulator_v9.py`,
  `Archive/tuppi_gui_client_multi_v8.py`, and Finder metadata.
- The emulator combines card encoding, bidding, rules, mutable game state,
  scoring, human I/O, heuristic play, PIMC rollouts, and coaching output.
- Its normal CLI always creates one human and three AI players and has no
  finite all-AI or structured-output mode.
- The GUI is only a Tk LAN client. Its expected host/server is absent.
- There were no tests, package metadata, dependency lockfiles, experiment
  records, datasets, models, or learning code.
- The built-in agents do not directly read the true opponent hands during the
  normal decision path. That separation is conventional, not enforced.
- One module-global random stream is shared by deck shuffling, candidate
  ordering, Monte Carlo sampling, hints, and post-deal analysis.
- A seed reproduces an identical run only when the runtime, configuration, and
  sequence of interactions are also identical.

## Preliminary rule contradictions

These comparisons are preliminary observations against the Tuppiliitto page
available during the audit. They are not an authoritative or complete rules
specification.

- The current tournament text calls for separate red and black show cards,
  using playing cards only when separate show cards are unavailable. The
  legacy emulator always uses cards from the hand.
- The tournament text says a deal that drops the rising partnership is not
  played beyond seven tricks. The legacy emulator always plays 13 tricks.
- Current tournament matches normally use a finite deal count unless a tuppe
  ends the match. The legacy CLI runs until a partnership reaches 52 during a
  continuous rise.

Reference consulted during the preliminary comparison on 2026-07-31:
<https://tuppiliitto.com/index.php/saannot/tupen-yleiset-turnaussaeaennoet>

## Unverified historical claims

- The emulator header calls itself a faithful rules emulator and describes its
  AI as strong. Neither claim has supporting evidence in the repository.
- RS/NHI formulas, probability mappings, bidding thresholds, and prior fixes
  have no preserved source, calibration data, issue history, or evaluation.
- No historical match result or reported playing strength can be reproduced
  from the supplied artifact.

## Known legacy quirks

- An explicitly empty `show_banned_ranks` set is replaced with the default
  `{2, J, Q, K}` by the legacy constructor.
- Zero or negative rollout counts select the heuristic fallback.
- Non-positive move-analysis rollout counts are replaced with 200.
- Illegal AI actions can be replaced with the first legal card.
- `PublicState.score_state` can alias the live mutable `ScoreState` object.
- Agent objects own mutable hand lists used directly by the game loop.
- PIMC samples do not enforce all information implied by earlier play.
- Rollout budgets differ among constructor, CLI, advisor, hint, and analysis
  defaults. CLI wording also describes a per-move budget as per-decision.
- The bidding variable `base_thr` is calculated but unused.
- The GUI normalizes malformed banned-rank data and swallows several errors.

## Risks deferred to the future engine

- Formal, versioned rules and tournament-format definitions.
- Immutable player-specific observations and strict action validation.
- A trusted headless state machine with explicit invariants.
- Duplicate-deal and cross-play evaluation.
- Independent reproducible RNG streams throughout the clean engine.
- Exact endgame search, information-set search, belief models, training, and
  human-compatible coaching.

The archival adapter intentionally characterizes and executes the legacy code;
it does not repair these issues.
