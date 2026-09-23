# Merging the real-game work (sooli, locked bids, review, TuppiAI as the AI)

Written 2026-09-23. The work lives on branches because the main checkouts
carry another author's uncommitted work, which must not be overwritten.

| Repo | Branch (worktree) | Base |
| --- | --- | --- |
| TuppiProject | `rules/project-target-v3-locked-bids` (`~/Developer/TuppiProject-sooli`) | `622d559`, the main checkout's committed HEAD |
| TuppiClient | `feature/v3-locked-bids-sooli` (`~/Developer/TuppiClient-v3`) | `1d82b4b`, the main checkout's committed HEAD |
| TuppiAI | `main` (committed directly; own repo) | - |

## Rehearsal (done 2026-09-23, in throwaway worktrees)

The other author's uncommitted edits were applied as a temporary commit on top
of each base, and the branch was merged into it. Their working trees were only
read.

- **TuppiProject: merges cleanly**, no conflicts. On the merged tree (with their
  untracked packages copied in) the server, engine, rules, agents and NOLO tests
  give **1166 passed, 1 failed**: the only failure is the expected NOLO
  provenance pin below; the four server tests that fail on the branch alone
  pass with the other author's edits in.
- **TuppiClient: two conflicts, both generated files**
  (`Resources/Fixtures/manifest.json`, `sha256sums.json`). Resolve by
  re-running the sync from the merged TuppiProject; all 121 client tests then
  pass.

## Steps

1. The other author commits their work in both main checkouts, including the
   still-untracked `TuppiClient/Sources/TuppiClient/ReferencePolicy.swift` and
   its test (committed `HEAD` already references it and does not build
   without it).
2. TuppiProject main checkout: `git merge rules/project-target-v3-locked-bids`.
3. TuppiClient main checkout: `git merge feature/v3-locked-bids-sooli`; on the
   fixture conflict run, from TuppiProject,
   `python tools/sync_tuppi_client_bundle.py --client-root ../TuppiClient --sync`,
   then `git add Sources/TuppiClient/Resources/Fixtures` and commit.
4. Point `~/.venvs/tuppi-ai` (or the product venv) at the merged TuppiProject;
   the `tuppi-v2` venv and the two worktrees can then be removed
   (`git worktree remove`).

## Things to know after merging

- **NOLO evidence packet.** `docs/nolo/tasks/source_manifest.json` pins the hash
  of `src/tuppi_engine/observations.py`, which the branch changes (locked-bid
  masking, sooli fields); `tests/nolo/test_evidence.py` will report the drift.
  Every NOLO answer is unchanged (the NOLO path is untouched); re-pinning is the
  packet owner's decision.
- **Pre-existing test failures** (also on clean `622d559`): the audit variant
  list, the learning version pin, and four server tests tied to the other
  author's in-progress server edits. `tests/server/test_match_runner.py::
  test_async_submission_waits_before_ai_leads_a_new_trick` fails about 1 run in
  100: it plays a random live deal and asserts that an AI moves after the
  human's first action, which is false when that action completes a trick the
  human wins. A fixed deal would make it deterministic.
- **The live server now defaults** to `project_target_v3`, TuppiAI's bot when
  `tuppi_ai` is importable (with the after-deal review), and 0.5 s AI pacing.
  `RoomManager()` itself still defaults to v1, so embedded use and the tests
  are unchanged.
