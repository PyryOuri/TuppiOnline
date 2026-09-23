# Handoff: locked bids, conventions research and the test plan

Written 2026-09-23 by the session that did the conventions research, for the
LLM implementing `project_target_v2` (sooli). The owner will point you here.

The owner wants you to:

1. decide how locked bids enter the ruleset line (D1, section 5);
2. do the implementation;
3. do the clean-up.

This file is self-contained: everything this session did, decided or found is
below, with pointers to the two longer documents.

| Document | What it holds |
| --- | --- |
| [`CONVENTIONS.md`](CONVENTIONS.md) | The conventions research: human-play conventions, the owner's answers, critical review, hand statistics |
| [`LOCKED_BIDS_AND_CONVENTION_TESTS_PLAN.md`](LOCKED_BIDS_AND_CONVENTION_TESTS_PLAN.md) | The plan: Part A locked bids, Part B the NOLO test, Part C the RAMI signal tests |
| This file | Handoff, decision D1, checklist |

---

## 1. What this session did, completely

**Files.** No code, config, rules, test or schema file was changed anywhere.
Nothing was committed. No bot, build, training or evaluation was run.

| File | State | What |
| --- | --- | --- |
| `TuppiAI/docs/CONVENTIONS.md` | new, untracked | The research notes |
| `TuppiAI/docs/LOCKED_BIDS_AND_CONVENTION_TESTS_PLAN.md` | new, untracked | The plan |
| `TuppiAI/docs/LOCKED_BIDS_RULESET_REVIEW.md` | new, untracked | This handoff |
| `TuppiAI/docs/TASKS.md` | modified (+18 lines) | New section "T4 - Locked bid cards and the convention tests" |

**Untouched:**

- TuppiProject (`622d559`, branch `phase7/reference-policy-identity`, with
  another author's uncommitted edits);
- TuppiProject-sooli (`0fb48b0`);
- TuppiClient (`1d82b4b`).

**Not mine, left alone** in TuppiAI:

- the sooli edits in `native/tuppi_core.h`, `native/tuppi_env.c`,
  `native/tuppi_sooli_policy.c`, `tuppi_ai/native.py` and `tuppi_ai/search.py`;
- `tools/sooli_bank.py`, `tools/sooli_offer_check.py`, `tools/sooli_play_eval.py`;
- `.DS_Store`.

**Outside the repos:**

- The hand-statistics scripts ran in a temporary scratchpad, which will
  disappear. Their core, seeds and results are in `CONVENTIONS.md`
  (appendix). They are plain Python on random hands and can be rerun from
  there.
- This session also keeps private notes on its own machine. Everything
  relevant to you is copied into this file.

**Read-only surveys.** This session mapped the showing code across the engine,
agents, rules, server, client, native core, search, evaluator and clone. The
facts are in section 4 and the plan's Part A.

---

## 2. What the owner decided (please don't reopen)

**Rules.**

- **Switch to locked bid cards, as in the real game.**
  - All four players choose a bid card and declaration without seeing anyone
    else's. That includes the spoken counter-colour bid (*vastaväri*), which
    must be honoured.
  - Bids are revealed in seat order from the forehand. The first RAMI declares.
  - Bids after the first RAMI are **never revealed**.
- **In the app:**
  - humans lock their bids simultaneously;
  - unrevealed bids are never shown back and never stored.
- **Who decides D1:** you, not the owner, because you know v2's state.

**Human play at the owner's table, the baseline for the tests:**

- **The NOLO short-suit convention.**
  - Every player's *early* first lead (roughly the first 5 tricks; none at
    trick 9) comes from their shortest suit, singleton honours included.
  - Which card is not fixed, but it is most commonly the largest.
  - A partner with a strong hand leads that suit back ("supports the
    teammate"); with a worse hand, they lead their own shortest.
  - Top players skip it when it would cost tricks, especially with very good
    NOLO cards. "Very good" is subjective; one example is a couple of short
    suits holding only very low cards.
  - Its strength is not verified.
- **Other habits:**
  - bid cards are chosen roughly at random;
  - players throw a bad card onto a partner's trick unless they don't want to
    lead next;
  - players don't count HCP, but could be taught;
  - agreements are not announced;
  - human-vs-human games are not recorded.

**Conventions work:**

- The goal is conventions that improve **human** play, not bot strength. The
  bot is only the measuring instrument.
- The owner accepted the RAMI signals (R1, R2, R4, R5 in `CONVENTIONS.md`
  §5.3) as the conventions to test.
- The owner found a first compute estimate of ~30 h far too much. Keep
  experiments small and sized by pilot runs.

---

## 3. What was found (short; details in `CONVENTIONS.md`)

1. **The rules gap.** `project_target_v1` models *sequential* showing: a seat's
   observation during SHOWING includes earlier shows. The real game uses locked
   bids. The legacy emulator had locked bids; the v1 spec replaced them.
2. **Locked bids are mostly a visibility change.** A bid after the first RAMI
   never takes effect. So keeping sequential collection, while hiding other
   seats' bids until showing resolves, gives the same outcomes and the same
   information. Being asked to bid reveals only that earlier seats passed,
   which is the one case in which your bid matters anyway.
3. **The incumbent's showing ignores earlier shows.** It already plays locked
   bids correctly, so incumbent contract mixes and the equity table are
   unchanged. **The search bot does use earlier shows,** through sampler
   pinning and the clone's inputs, so its showing results were measured in the
   sequential game and must be re-baselined.
4. **The table's NOLO system is not the one the bot tested.**
   - The bot tested lowest card first, with no return.
   - The table plays largest card first, and a strong partner returns the suit.
   - The earlier finding "returning measures ≤ 0" was measured on the bot's
     combination. It doesn't refute the table's.
5. **Where conventions can help.** The test used: a free choice, a partner
   decision that depends on hidden cards suit by suit, and information the play
   wouldn't reveal in time.
   - NOLO mostly fails it, because the cards dictate the play.
   - RAMI small-card follows and discards pass it.
   - So:
     - the bid-card high-card signal (C1) is demoted;
     - C2 and C3 are already table practice;
     - the pass-card RAMI support signal (S1) is impossible with locked bids.
6. **The compute estimate was corrected** from ~30 h to ~7-8 h. The error: I
   used single-decision latency rather than the evaluator's parallel
   throughput. The one recorded figure is 128 base deals in 116 s on 13
   workers with the search on 2 seats (`STATUS.md:44`), so all estimates are
   extrapolations. The first pilot will give the real per-deal cost.

---

## 4. Implementation facts (survey, 2026-09-23 working trees; re-check before editing)

### Where locked bids touch the code

| Layer | What changes | Where |
| --- | --- | --- |
| Rules | Nothing: legal actions and resolution depend only on the hand and the order | `tuppi_rules/showing.py:34-172` (identical in both trees) |
| Engine | During SHOWING, no other seat's shows in the observation; withhold `SHOW_ACCEPTED` until resolution (or use `BID_LOCKED` + `SHOWING_REVEALED`) | `observations.py:162-165` (and :187-189 in the sooli tree); invariant :83-86; `transitions.py:122-132`; `events.py:79-93`; `event_builder.py:69-80`; `match.py:47,126,153` |
| Ruleset plumbing | The sooli tree threads `ruleset_id` (`match.py:70`, `deal.py:88-91`) and branches on `PROJECT_TARGET_V2` | `tuppi_rules/model.py:21-22` |
| Config / schema | `showing` is a `const` in `schemas/ruleset.schema.json:78-112`, so a visibility field needs a new schema version | sooli: `ruleset.v2.schema.json` |
| Agents | None needed: showing reads only the hand and the score | `tuppi_agents/showing.py:200-237`; `ShowingContext.previous_show_actions` is unread (`features.py:96-99`) |
| Other consumers of shows | Check the empty-during-showing case | `public_inference.py:125`; `tuppi_exact/constraints.py:133,521`; `tuppi_belief/reconstruction.py:59,123`; `tuppi_search/information_state.py:66-81`; `tuppi_learning/encoding.py:188`; `tuppi_llm/prompting.py:105`; `tuppi_nolo/support.py:216-239` |
| Native encoder | During SHOW: mask the per-show block and `F_SHOWN_HELD`, keeping the count (the actor and `F_SHOW_POS` use it); in `tc_observe`, copy only the count | `tuppi_core.c:394-402, 421, 290-294` |
| Native sampler | While searching a bid, don't pin earlier shown cards; generate earlier seats' NOLO shows per sampled hand (random eligible card, as humans do) | `tuppi_search.c:211-214, 248-257, 380-383`; `public_state` :42-46 |
| Native play-outs | Other seats' bids become blind once the encoder masks | `tuppi_env.c:377-391` |
| Clone | Its showing inputs included earlier shows (one 156-way head). Check blind-input agreement; fine-tune if it drops by more than about 1 point | `tools/gen_bc.py:56-69`, `bc.py`, `model.py` |
| Server | Collect human bids simultaneously; ask AI seats in turn; discard remaining bids unseen; no per-seat event filtering exists today (the leak risk) | `app.py:317-405, 412, 446-470`; `match_runner.py:430-462, 554, 664, 705-755` (another author's uncommitted edits); `projection.py` |
| Schemas | New events and a v3 id | `schemas/network/websocket_message.schema.json:91-125`, `schemas/engine/public_event_log.schema.json`, `player_observation.schema.json`, `showing_ui_hints.schema.json` |
| Client | A "lock your bid" panel for all seats; a reveal sequence at resolution | `TableViews.swift:840-915, 775-836`; `OnlineViews.swift:586-595`; `ProtocolModels.swift:248-277`; `LiveSessionStore.swift:528-545` (counts `show_accepted`) |

**Tests that assume visibility.** They stay valid for v1 and v2; each needs a
v3 counterpart:

- `tests/engine/test_observations.py:114`
- `tests/agents/test_features.py:161`
- `tests/search/test_showing.py:221`
- `tests/search/test_information_set_invariance.py:237`
- `tests/server/test_privacy_boundary.py:94`

**The NOLO evidence packet pins `observations.py`.**
`docs/nolo/tasks/source_manifest.json:15` in the main TuppiProject tree, with
another author's uncommitted edits, feeds `tests/nolo/test_evidence.py:60`.
Editing the file trips that test. Re-pinning is the packet owner's call.

### Facts the test harness needs

- **`tuppi_ai/evaluate.py` is too limited.** It supports neither
  search-vs-search nor per-seat agents nor forced contracts, and it plays only
  SHOWING and TRICK_PLAY. A new runner is needed (`tuppi_ai/conv_eval.py` in
  the plan).
- **`tuppi_valuation`'s forced contracts are not usable.** They live in another
  author's **untracked** `corpus.py` in the main TuppiProject tree. Write a
  small forced-NOLO driver in the harness.
- **World sampling is internal to C only.** `tc_search_values` samples
  internally (`tuppi_env.c:331-339`) with no hook for a filter. Its evaluation
  part (:340-406) does not depend on how worlds were drawn, so adding one entry
  point that "searches given worlds" is straightforward. **That file carries
  your uncommitted edits**, so this waits for you.
- **`native.search_values` accepts an action list** (`native.py:352-360`), so
  a wrapper can search a subset of actions.
- **`SearchAgent` does not keep per-action values** (`search.py:212-295`), and
  that file also carries your edits. The plan wraps it in a new file.
- **The venv's `.pth` points at the dirty TuppiProject main tree.** For
  experiments, pin `PYTHONPATH` to clean worktrees and record both commits and
  the native library hash.

---

## 5. Decision D1: where do locked bids go?

| | (i) `project_target_v3` = v2 + locked bids | (ii) Fold locked bids into v2 now |
| --- | --- | --- |
| Versioning policy | Clean: v2 stays as it is | Allowed only if **no result has been recorded under v2** |
| Your sooli results | Keep their meaning | Any existing v2 result becomes ambiguous |
| Work | One more ruleset id on top of v2's `ruleset_id` threading | Amend v2's specification, config, schema, tests and native flag |
| Showing search | Sooli-aware bidding (SOOLI_PLAN D6) is built for sequential v2, then adjusted | Built once, directly for locked bids |
| End state | The real game is v3 | The real game is v2 |

**The facts that decide it** (only you can check them):

1. **Has any result been recorded under v2?** For example, from
   `tools/sooli_bank.py`, `sooli_play_eval.py` or `sooli_offer_check.py`. If
   yes, choose (i).
2. **Is D6 (sooli-aware bidding) written yet?** If not, and (1) is "no", (ii)
   saves doing that work twice.
3. **How close is v2 to done?** If v2 is nearly final, (i) avoids reopening it.

**Lean:** choose (ii) only if (1) is "no" *and* D6 is unwritten; otherwise (i).
`project_target_v1` stays untouched either way.

---

## 6. Checklist: implementation and clean-up

Order and effort come from the plan, where the details are.

**Now**

- [ ] Fill in section 8 (D1 and what you will take on).
- [ ] Commit the conventions documents in TuppiAI, **by explicit path only**:
  `docs/CONVENTIONS.md`, `docs/LOCKED_BIDS_AND_CONVENTION_TESTS_PLAN.md`,
  `docs/LOCKED_BIDS_RULESET_REVIEW.md`, `docs/TASKS.md`. Never `git add -A`:
  the working tree also holds your uncommitted sooli work and `.DS_Store`.
- [ ] Commit your own sooli edits to `search.py` and `tuppi_env.c`. The
  harness waits for them.

**Part A: locked bids** (plan A3-A7)

- [ ] Specification, decisions table, config and schema for the chosen id.
- [ ] Engine visibility plus events, with v3 tests: no bid visible to another
  seat before resolution; the revealed prefix public afterwards; discarded bids
  nowhere; a property test.
- [ ] Native masking and sampler changes, with differential tests against the
  reference.
- [ ] Clone check, and a fine-tune if needed.
- [ ] Re-baseline the best agent under the new rules (~15-30 min), recorded in
  `docs/STATUS.md`.
- [ ] Server, protocol and client: simultaneous locking and the reveal step.
  Add a message-capture privacy test. Coordinate with the other author's server
  edits and with T1.
- [ ] `tools/serve_human.py` moves to the new rules.

**Parts B and C: the tests** (plan B, C and "Shared infrastructure")

- [ ] Pinned experiment environment, `conv_eval.py`, the convention wrapper,
  the forced-NOLO driver, and a "search given worlds" C entry point, tested
  bit-identical to the internal draw.
- [ ] Write the pre-registration before each confirmatory run.
- [ ] Part B: pilot (~12 min), then stages sized by the pilot (about 4 h
  total).
- [ ] Part C: pilot on v1 is allowed; the final run is on the new rules (about
  3 h total).

**Clean-up afterwards**

- [ ] Update `docs/STATUS.md` with the results.
- [ ] Put the deliverables into `CONVENTIONS.md`: the table rule in §4, and
  adopt or drop for each signal in §5.3.
- [ ] Set T4's status in `TASKS.md`.
- [ ] Tell the NOLO-packet owner about the `observations.py` pin; don't re-pin
  it yourself.
- [ ] Remove the "re-check before editing" caveats from the plan once the
  references have been verified.

---

## 7. Gotchas from earlier work on this machine

**Toolchain.**

- Build C with the Xcode toolchain:
  `DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer` plus
  `-isysroot $(xcrun --sdk macosx --show-sdk-path)`. The CommandLineTools SDK
  linker fails with "tapi error: malformed file".
- `native/build.sh` does an atomic rename, so it is safe while other runs are
  going.
- Only one training process on MPS at a time; two starve each other.

**Environments.**

- TuppiAI venv: `~/.venvs/tuppi-ai`.
- TuppiProject venv: `~/.venvs/tuppi-product`. There is no in-repo `.venv`,
  because the tree is iCloud-synced.

**TuppiProject tests.**

- The configured suite takes ~17-21 min, so run it in the background.
- `testpaths` omits `tests/nolo`, `tests/valuation`, `tests/llm`,
  `tests/research` and parts of `tests/rules`. Run them as a second pass
  before calling anything clean.
- Known baseline failure in the main tree:
  `tests/learning/test_boundaries_and_schemas.py::test_product_package_increment_does_not_change_frozen_learning_layer`
  (a version pin).

**Boundary scans read raw module text** (`tuppi_exact.integrity`,
`tuppi_search.validation`). Naming an outer package in a *comment* inside an
inner one reports a dependency that does not exist.

**Never `git add -A docs`** in TuppiProject: it once swept another author's
untracked files into a commit.

**Evaluation.** Denominate results in deals, not matches. Pair on the same
deals, and pre-register the *estimator* as well as the threshold: an earlier
study wasted a run because its statistic could never reach the gate.

---

## 8. Decision and report back (fill in)

- Chosen option (i or ii): **(i)**. v2 results exist (`runs/sooli/bank_v1.pkl`
  and the play/offer evaluations recorded in `STATUS.md`), so v2 stays as it
  is and the real game is v3.
- Ruleset id / branch: `project_target_v3` = v2 + locked bids. TuppiProject
  branch `rules/project-target-v3-locked-bids`, from the sooli branch
  (worktree `TuppiProject-sooli`); TuppiClient on its own branch in a
  separate worktree.
- Which checklist items you take on, and which you leave: all of Part A
  (owner's request of 2026-09-23: "do the server, protocol and swift client,
  also implement the locked bids"), plus sooli in the server, protocol and
  client. Parts B and C are left for their session.
- When your edits to `search.py` / `tuppi_env.c` are committed: TuppiAI
  `3040f63` (with `tuppi_search.c`, `tuppi_sooli_policy.c`, `native.py`).
- Anything in the plan you disagree with: nothing so far. The native sampler
  changes land in `tuppi_search.c`, as the plan says.

**Still open with the owner** (not blocking):

- Do players use any RAMI signals today (the card led from A-K, high-low,
  discards)?
- Is there a traditional way to choose the sooli give and return?
