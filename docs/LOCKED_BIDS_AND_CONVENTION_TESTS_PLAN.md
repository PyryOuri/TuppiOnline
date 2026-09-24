# Plan: locked bid cards, the NOLO convention test, the RAMI signal tests

Status: **Part A done** (locked bids, `project_target_v3`, 2026-09-23; see
`TASKS.md` T4); **Parts B and C not started.** Written 2026-09-23.

- The owner decided the same day to switch the project to **locked bid cards**,
  as in the real game.
- Background and the conventions themselves: [`CONVENTIONS.md`](CONVENTIONS.md).
- File:line references come from a read-only survey of the working trees on
  2026-09-23. Sooli work is in flight, so re-check the references before
  editing.

Three parts:

| Part | What | Needs locked bids? | Can start |
| --- | --- | --- | --- |
| **A** | Move the rules, engine, bot, server and client to locked bids | - | After decision D1, which the sooli implementer makes (`LOCKED_BIDS_RULESET_REVIEW.md`) |
| **B** | Test the table's NOLO short-suit system (variants V0-V4) | No: forced NOLO deals are the same under both | Now, in isolated worktrees |
| **C** | Test the RAMI signals (R1, R2, R4, R5) | Yes, for the final run; a pilot can run on v1 | Pilot after B's harness; final after A |

**Ground rules for all three:**

- Sooli work is active:
  - `TuppiProject-sooli` (branch `rules/project-target-v2-sooli`, engine
    commit `0fb48b0`);
  - TuppiAI `8a00f55`, plus uncommitted edits in `native/tuppi_core.h`,
    `native/tuppi_env.c`, `native/tuppi_sooli_policy.c`, `tuppi_ai/native.py`
    and `tuppi_ai/search.py`.

  Nothing here edits those files while that work is uncommitted.
- The TuppiProject main worktree carries another author's uncommitted edits
  (including `match_runner.py`, `analysis.py` and
  `docs/nolo/tasks/source_manifest.json`). Server changes must be coordinated,
  not overwritten.
- New code goes into **new files** where possible.

---

## Part A - Locked bid cards

### A0. The rule, as confirmed by the owner (2026-09-23)

- All four players choose a bid card and a declaration without seeing anyone
  else's. That includes the spoken counter-colour bid (*vastaväri*), which must
  be honoured.
- The bids are revealed in seat order from the forehand. The first RAMI makes
  its bidder the declarer.
- Bids after the first RAMI are **never revealed** and have no effect.
- NOLO results when all four bid NOLO.

### A1. The key simplification: only visibility changes

A bid after the first RAMI never takes effect. So the engine can keep asking
for bids in seat order and stopping at the first RAMI, provided that **a seat
choosing its bid sees no other seat's bid**. That gives the same outcomes and
the same information as locked bids.

- **Legal actions do not change**, and neither does contract resolution: the
  first RAMI in order declares. The survey confirmed that validation and
  resolution in `src/tuppi_rules/showing.py:34-172` depend only on the hand
  and on order.
- **What changes:**
  1. During SHOWING, a seat's observation omits the others' shows.
  2. `SHOW_ACCEPTED` events are withheld from other seats until showing
     resolves.
  3. At resolution, the accepted shows, which are exactly the revealed prefix,
     become public, as today.
- **Being asked to bid** tells a seat that every earlier seat passed. That is
  harmless: your bid only matters in exactly that case, so a rational player
  bids as if it were so. Humans in the app should still bid simultaneously, for
  fidelity (A6).

### A2. Ruleset identity (decision D1: delegated to the sooli implementer)

The owner asked for this to be decided by whoever implements v2, since they
know its state. The facts and options are set out for them in
[`LOCKED_BIDS_RULESET_REVIEW.md`](LOCKED_BIDS_RULESET_REVIEW.md).

Under the versioning policy, a change to observable behaviour needs a **new
ruleset id**. There are two ways to do it:

| Option | What | For | Against |
| --- | --- | --- | --- |
| **A2-i** | `project_target_v3` = v2 + locked bids, branched from the sooli branch | v2 stays valid for the sooli results now being produced (`tools/sooli_bank.py` and `tools/sooli_play_eval.py` exist); a small, clean delta | One more id; waits for v2's engine to settle |
| A2-ii | Put locked bids *into* v2 before any v2 result is recorded | One ruleset for the real game | Changes a ruleset another piece of work is building on right now; allowed only if no v2 result exists yet and the sooli work agrees |

My lean, stated in the review: choose (ii) only if no v2 result has been
recorded *and* the sooli-aware bidding search (SOOLI_PLAN D6) hasn't been
written yet. Otherwise choose (i).

`project_target_v1` stays unchanged either way.

### A3. Specification (TuppiProject, new branch from the sooli branch)

- `docs/rules/project_target_v3.md` and `.fi.md`: the v2 text plus a
  "Locked bids" section taken from A0. Include worked examples: a RAMI at the
  first seat means the other three bids are never seen; all-NOLO reveals all
  four.
- `docs/rules/project_target_v3_decisions.md`: v2's table plus one row for
  bid visibility.
- `configs/rules/project_target_v3.json` and its schema.
  - The survey found that `schemas/ruleset.schema.json:78-112` pins `showing`
    as a `const` (`order`, `shown_card_public`).
  - Add a field such as `bid_visibility: "locked_until_resolution"` in a new
    schema version. Do not edit the v1 or v2 schemas.
- `src/tuppi_rules/model.py`: add `PROJECT_TARGET_V3`, alongside `PROJECT_TARGET_V2`
  (`model.py:21-22` in the sooli tree).

### A4. Reference engine (TuppiProject)

**Observation.** In `src/tuppi_engine/observations.py:162-165`, when
`ruleset_id is V3` and the phase is SHOWING, pass empty
`show_actions` / `publicly_shown_cards` to every seat. Keep the invariant at
:83-86 consistent: both stay empty together.

**Events.** Two ways to handle `SHOW_ACCEPTED`
(`transitions.py:122-132`, `events.py:79-93`, `event_builder.py:69-80`,
`match.py:47,126,153`). Either:

- emit, per show, a public `BID_LOCKED` event that says who bid but not what,
  then a `SHOWING_REVEALED` event with the revealed prefix at resolution; or
- keep `SHOW_ACCEPTED` but withhold it from `public_events` until resolution.

Recommend the first, because it gives the client a clean reveal step.

**Other consumers of shows.** These mostly work in trick play, when the shows
are public again anyway, so they should be unaffected. Check them against the
empty-during-showing case:

- `public_inference.py:125`
- `tuppi_exact/constraints.py:133,521`
- `tuppi_belief/reconstruction.py:59,123`
- `tuppi_search/information_state.py:66-81`
- `tuppi_learning/encoding.py:188`
- `tuppi_llm/prompting.py:105`
- `tuppi_nolo/support.py:216-239`

**Agents.** The survey confirmed that every heuristic showing decision uses
only the agent's own hand plus the score (`tuppi_agents/showing.py:200-237`).
`ShowingContext.previous_show_actions` exists (`features.py:96-99`) but nothing
reads it. **So the incumbent already plays locked-bid correctly, and its
contract distribution is unchanged.**

**Tests.**

- **New v3 tests:**
  - no seat sees another's show or event during SHOWING;
  - the revealed prefix becomes public at resolution;
  - later bids never appear anywhere;
  - a property test over random prefixes, in the style of
    `tests/engine/test_properties.py:45`.
- **Existing tests that assume visibility:** they stay valid for v1 and v2,
  and each needs a v3 counterpart.
  - `tests/engine/test_observations.py:114`
  - `tests/agents/test_features.py:161`
  - `tests/search/test_showing.py:221`
  - `tests/search/test_information_set_invariance.py:237`
  - `tests/server/test_privacy_boundary.py:94`
- **NOLO evidence packet.** `docs/nolo/tasks/source_manifest.json:15` pins
  `observations.py`. Editing it trips `tests/nolo/test_evidence.py:60`. The
  manifest also has another author's uncommitted edits. Re-pinning is the
  packet owner's call; flag it, don't do it.

### A5. Native core and bot (TuppiAI, after the sooli native work is committed)

**Masking.** Take a ruleset flag, as v2 already does, and when it is v3 and the
phase is SHOW:

- **Encoder:** mask the per-show block (`tuppi_core.c:394-402`) and
  `F_SHOWN_HELD`. Keep the show count, because the actor and `F_SHOW_POS`
  (:421) depend on it.
- **`tc_observe`** (`tuppi_core.c:290-294`): copy the count only.

**Sampler during showing.** Stop pinning earlier shown cards
(`tuppi_search.c:211-214, 248-257, 380-383`) while a bid decision is being
searched. In each sampled world, earlier seats' NOLO shows must be *generated*
from their sampled hands, where `public_state` (:42-46) currently copies them.

- Use a random eligible card, which matches the owner's "bid cards are chosen
  at random".
- Optional refinement: reject sampled worlds in which an earlier seat's own
  policy would have bid RAMI. That is "they passed" as evidence, which the bot
  has never used.

**Play-outs.** The other seats' shows are the clone's greedy choice
(`tuppi_env.c:377-391`). With masking they become blind, as they should be.

**The clone.** Its showing inputs included earlier shows (`tools/gen_bc.py:56-69`,
one 156-way head). The incumbent it imitates ignored those inputs, so masking
should change little.

- **Check:** compare the clone's show agreement with the incumbent on
  blind-input decisions against its current figure (97.9% overall, `STATUS.md:216`).
- **If showing agreement drops by more than about 1 point:** regenerate
  showing labels under v3 observations (cheap: incumbent self-play) and
  fine-tune.

**Bridge.** `tuppi_ai/bridge.py:68-74` copies `observation.show_actions`. It
follows the engine automatically, but must pass the v3 flag to the native
observation.

**Differential tests.** Native v3 against the reference v3, step by step, in
the existing style, including the masked observations.

**Equity table.** Incumbent self-play contracts are unchanged (A4), so
`models/equity_incumbent.json` stays valid for the incumbent. Refit only if a
later study needs the search team's contract mix.

**Re-baseline** (~15 min for 512 base deals at W=128; complete matches are
optional, ~1.5 h). Under v3, measure:

- the best agent against the incumbent: 512 fresh base deals for equity per
  deal, plus complete matches;
- the showing breakdown, which `STATUS.md` records for v1 (declare 48.7%,
  made 79.6%).

Record everything in `docs/STATUS.md`. Some of the bot's showing edge came from
seeing earlier shows, so a drop is expected and is itself a result.

### A6. Server, protocol, client (coordinate with T1 and the other author's server edits)

**Collecting bids.**

- When showing starts, ask every human seat to **lock** a bid at once.
- Hold locked bids server-side, and feed them to the engine in seat order.
- Ask an AI seat only when its turn comes. Its decision is identical, because
  its observation hides the earlier bids.
- When the engine resolves, discard the remaining locked bids unseen.

Entry points: `app.py:317-405`, `match_runner.py:554, 664, 705-755`.
`contract_evaluation.py:61` receives the blind observation unchanged.

**What is sent to clients.**

- During SHOWING, each seat receives only "seat X has locked" (the
  `BID_LOCKED` event), never the card.
- At resolution, the reveal is sent in order.

`projection.py` does no per-seat event filtering today, so this is the one
place a leak could happen. Add a server test that captures every outgoing
message during SHOWING and asserts that no other seat's card or declaration
appears.

**Persistence.** `persistence_record` (`match_runner.py:430-462`) stores only
the revealed prefix. Discarded bids are **not persisted** (the real game never
reveals them).

**Schemas.**

- `schemas/network/websocket_message.schema.json:91-125`
- `schemas/engine/public_event_log.schema.json`
- `schemas/engine/player_observation.schema.json`
- `schemas/network/showing_ui_hints.schema.json`

Each gets new event types and a v3 ruleset id.

**Client (`TuppiClient/Sources/TuppiClient/`).**

- `TableViews.swift:840-915` becomes a "lock your bid" panel for all seats at
  once.
- `ShownCardRevealView` (:775-836) plays the reveal sequence at resolution.
- Update `OnlineViews.swift:586-595` (hints), `ProtocolModels.swift:248-277`
  (decoding) and `LiveSessionStore.swift:528-545`. That last one counts
  `show_accepted` events, so its count changes.
- Replays and analysis list only revealed bids.

**Human benchmark.** `tools/serve_human.py` moves to v3 with the rest.

### A7. Exit criteria for Part A

1. All v3 normative tests pass. v1 and v2 tests are unchanged and still pass.
2. The native-vs-reference differential tests pass on v3.
3. Privacy tests pass in the engine and the server: no bid is visible to
   another seat before resolution, and discarded bids appear nowhere.
4. The clone check passes, or the clone is fine-tuned.
5. The v3 re-baseline is recorded.
6. The owner can play a v3 game in the app.

---

## Part B - The NOLO test: the table's short-suit system

**The question.** Which version of the table's NOLO system is best, and is it
better than competent free play? The table's version: each player's early
first lead is from their shortest suit, often its largest card, and a partner
with a strong hand returns it.

### B1. The conventions as code

**Definitions** (`tuppi_ai/conventions/nolo.py`, new):

- **Early:** a lead at trick ≤ `cutoff`, with `cutoff ∈ {3, 5, 7}`. The owner's
  rough figure is 5.
- **Initiator:** the first player of a partnership to make an early lead.
- **Responder:** their partner, at the responder's own first early lead, if
  the initiator's lead came first.
- **Initiator's lead:** the shortest suit held (length only; singleton honours
  included), with its **lowest** or its **largest** card depending on the
  variant. Ties between equally short suits go to the search.
- **Responder's choice:**
  - **return** the initiator's suit (the search chooses the card within it);
  - or lead their **own shortest**, as an initiator would;
  - if void in the initiator's suit, the responder leads their own shortest.
- **All other decisions:** the search decides.

**Variants.** The candidate pair plays the variant; the opponents always play
**V2**, the table standard.

| Variant | Initiator | Responder |
| --- | --- | --- |
| V0 | Search (no convention) | Search |
| V1 | Shortest suit, lowest card | Own shortest |
| **V2** | Shortest suit, largest card | Return with a strong hand, else own shortest (the table's system) |
| V2r | Shortest suit, largest card | Always return |
| V3 | Shortest suit, lowest card | As V2 |
| V4 | As V2, but a very safe hand skips the convention (search decides) | As V2 |

**"Strong hand" and "very safe hand" are chosen by the data, from simple rules
people can apply:**

- (p1) holding a card of rank 2-6 in the initiator's suit;
- (p2) holding at most k aces or picture cards, with k ∈ {2, 3};
- (p3) holding a short suit (void, or 1-2 cards all ≤ 6).

**Instrument check:** V2 against V2 must score **exactly 0**, given common
random numbers (B3).

### B2. Reading (stage 2 only)

"Reading" means drawing only worlds consistent with what the convention says.

- **The initiator's suit** was their shortest leadable suit at the time of the
  lead. The partner reads it, and so do the opponents, because the convention
  is known to the whole table.
- **A V2 responder's return** implies that the chosen strong-hand rule holds.

Compare arms where the candidate pair reads against arms where it does not,
with the opponents reading in both.

### B3. Harness (new files; no edits to sooli-touched files)

**Isolation.**

- Run from a `git worktree` of TuppiAI at a pinned commit (≥ `8a00f55`, once
  the sooli edits are committed), with its own `native/build.sh` build.
- Run against a TuppiProject worktree at a pinned commit (the sooli branch tip
  is fine: v1 behaviour is unchanged there).
- Set `PYTHONPATH` explicitly. **Do not** rely on the venv's `.pth`, which
  points at the dirty main tree.
- Every output records both commits and the native library hash.

**Forced NOLO driver.** `tuppi_valuation`'s `ContractCondition` lives in
another author's untracked `corpus.py`, so write a tiny driver in the harness:
every seat bids NOLO with a **random** eligible card, which is how humans
choose.

**Duplicate runner** (`tuppi_ai/conv_eval.py`, new). `evaluate.py` supports
neither search-vs-search nor per-seat agents nor forced contracts (survey), so
this is a new runner:

- per-seat agent factories;
- 4 rotations × 2 team assignments per base deal, as in `evaluate.py:120-130`,
  with the same seeding scheme;
- a `ProcessPoolExecutor`;
- JSON output per game.

**Common random numbers.** Each search RNG is seeded from (base deal,
rotation, assignment, seat, decision index). Arms then differ only where the
convention acts.

**Convention agent** (`tuppi_ai/conventions/agent.py`, new). A wrapper around
the search agent:

- when a convention rule applies, it either plays the rule's card, or calls
  `native.search_values` on the rule's allowed subset
  (`native.py:352-360` accepts an action list);
- otherwise it defers to the plain search.

**Reading (stage 2)** needs worlds that satisfy a predicate.
`tc_search_values` samples internally with no hook (survey).

- Add one C entry point that evaluates *given* worlds. The evaluation part of
  `tc_search_values` (`tuppi_env.c:340-406`) does not depend on how worlds
  were drawn.
- Do the rejection sampling in Python over repeated `tc_sample_world` draws.
- This touches `tuppi_env.c`, so it waits for the sooli edits there to be
  committed, then lands as its own small commit with a test: given worlds equal
  to the internal draw must give bit-identical values.
- Log the acceptance rate. If more than 5,000 draws are needed for 128
  worlds, fall back to unconditioned sampling and count how often that
  happens.

### B4. Endpoints and estimator (fix before running)

- **Primary:** the candidate pair's **NOLO deal-win rate** minus the
  baseline's, paired by base deal, with a bootstrap clustered by base deal.
- **Secondary:** team tricks, and equity per deal at 0-0 from the equity
  table.
- **Selecting the strong-hand rule:** choose the best (rule, threshold) on
  one half of the base deals and report its effect on the other half only.
  Earlier project work showed that selecting and reporting on the same data
  inflates results.
- **Decision rule:** recommend a change to the table's system only if a
  variant beats V2 with a 95% interval excluding 0 on the primary endpoint.
  Otherwise report "no evidence to change the table's system". That is also a
  useful answer.

### B5. Size and compute

**Size.** Earlier lead studies saw large effects (+13.9 points) with 900 deals.
Differences between variants will be smaller: aim to resolve about ±1.5
points of deal-win rate. That means **1,000 base deals × 8 games** per arm.

**Compute.** The only recorded throughput is 128 base deals × 8 games in
116 s on 13 workers, with the search on two seats at W=64 (`STATUS.md:44`).

- That is about **0.9 s per base deal**, or ~1.8 s with the search on all four
  seats.
- W=128 is assumed to cost about 1.5× as much.
- An earlier version of this plan said ~30 h in total. That figure used
  single-decision latency, as if decisions ran one after another, and fixed
  large sizes for every arm. It was 3-4× too high.

| Stage | Arms | Base deals | Worlds | Machine time (estimate) |
| --- | --- | ---: | --- | --- |
| 0 - pilot | V0, and V2 vs V2 (the zero check) | 200 | 64 | ~12 min |
| 1 - screen | V0, V1, V2r, V3 at cutoff 5 | sized by the pilot (≤ 800) | 64 | ≤ ~1.6 h |
| 2 - follow-up | V4 and cutoffs 3 and 7, for the winner only | ≤ 800 | 64 | ≤ ~1.2 h |
| 3 - confirm and read | The winner vs V2, with and without reading | ≤ 800 | 128 | ≤ ~1.2 h |

**Part B total: about 4 h, less if the pilot shows smaller runs are enough.**
The pilot measures the paired spread between arms and sets the size of stages
1-3. With common random numbers, deals where the arms play identically differ
by exactly 0, so the needed size may be well below 800.

### B6. Deliverable

A short result in `docs/STATUS.md`, and in `CONVENTIONS.md` §4, a
**one-paragraph table rule**, for example: "lead the largest / lowest card of
your shortest suit up to trick N; return it when you hold a low card in it".
Include the evidence, or the statement that the table's version is as good as
anything tested.

### B7. Risks

- **The search's play-outs assume lead_v2-style future play.** The bot values
  positions as if nobody follows the table system later in the deal. This
  biases the comparison slightly towards V0 and V1. Acceptable; noted.
- **Exact reading is an upper bound** on what people extract.
- **"Early" and "strong" are fuzzy in human play.** The sweeps show how
  sensitive the answer is.

---

## Part C - The RAMI signal tests

**The question.** Do the whist-style signals help a pair that uses and reads
them, and how much do they give away to opponents who read them too?

### C1. The conventions as code (`tuppi_ai/conventions/rami.py`, new)

**"Free" set:** the legal actions whose search value is within ε of the
best. ε is set from the Monte Carlo standard error of the action values (to
be measured; start at 1 SE). A signal chooses only inside this set. If the
signal's card is not in it, the agent plays the best card. **So following a
signal costs about zero by construction**, and arm B checks that.

| Signal | When it applies | What it plays | What a reader infers |
| --- | --- | --- | --- |
| **R1** top of touching honours | Leading a card that belongs to a run of touching honours in hand | The top of the run (deterministic; touching cards are equivalent) | A lead of K means Q held and A not held, and so on |
| **R2** attitude | Following partner's lead while not winning (partner is winning and you won't overtake, or you can't beat the current winner), with ≥ 2 free cards | Encourage (holding A, K or Q, or ≥ 4 cards in the suit): the highest free card that is ≤ 8 and can never win. Otherwise the lowest. | Encourage: honour or length present. Discourage: absent. |
| **R4** first discard | The first time void in the deal | From the weakest suit (no A or K), the lowest free card | No A or K in that suit |
| **R5** return partner's suit | At your first lead after partner led a suit first | Partner's suit (the search chooses the card), unless the best alternative is better by more than δ | Nothing (a planning rule) |

### C2. Arms

**The four arms.** Both pairs are the search bot. The candidate pair uses the
arm's settings.

| Arm | Candidate pair | Opponents | Measures |
| --- | --- | --- | --- |
| A | Plain search | Plain search | Must be **exactly 0** (instrument check) |
| B | Signals, nobody reads | Plain | Cost of signalling |
| C | Signals, partner reads | Plain, not reading | Short-run value |
| D | Signals, partner reads | Plain, **reading ours** | Long-run value at a regular table |

**Order.**

1. Run **the bundle R1 + R2 + R4** first, in arms A-D.
2. Break it apart (R2 alone, then R1 + R4) only if the bundle's D − A interval
   excludes 0 in either direction.
3. **R5** runs separately: arm B only, strict and with the δ clause, because
   it is a lead rule with a possible cost.

**Noise arm** (after C2 in D): the signaller deviates 15% of the time, and
readers weight worlds (0.85 / 0.15) instead of rejecting them.

### C3. Deals, endpoints, estimator

**Deals.**

- **Final run:** v3 rules (Part A), natural contracts decided by the search's
  own showing, sooli offers always declined.
  - Common random numbers keep the contract identical across arms.
  - Report all deals, and RAMI deals separately.
- **Pilot:** allowed on v1, to debug and to size the run. Label pilot numbers
  as v1 and do not report them as the answer.

**Endpoints.**

- **Primary:** the candidate pair's equity per deal at 0-0 (duplicate, paired
  by base deal).
- **Secondary:**
  - split by declaring side and defending side;
  - RAMI made rate;
  - steal rate (the doubled points);
  - declaring-side tricks.

**Size.** At most about 1,000 base deals × 8 games per arm. The W=64-vs-128
comparison resolved ±0.0011 at 512 base deals in full games. A pilot of 200
base deals sets the real size.

**Compute.** With the search on four seats plus bidding decisions, full deals
cost about 1.9 s per base deal at W=64.

| Step | Arms | Machine time (estimate) |
| --- | --- | --- |
| Pilot | 200 base deals × 2 arms | ~15 min |
| Bundle | Arms B, C, D at ≤ 1,000 base deals, plus arm A (the zero check) on 50 | ≤ ~1.6 h |
| R5 and the noise arm | - | ≤ ~1 h |

**Part C total: about 3 h.**

### C4. Deliverable

For each signal: adopt, adopt with changes, or drop. The owner gets a one-page
"table card" of the adopted ones, with their D − A values, and a note for
each on how often it came up.

### C5. Risks

- **The play-outs' clone never signals.** Only the root decision reads
  signals, so the bot under-uses information that a human partner would keep
  using all deal. That biases the test *against* the signals, which is
  acceptable for a keep-or-drop decision.
- **Choosing ε.** Too loose, and signals cost real play (arm B catches it).
  Too tight, and signals rarely fire (report the firing rate).
- **Readers use exact rules,** so the result is an upper bound for people.
- **Machine time is shared with the sooli work.**

---

## Shared infrastructure (build once, in Part B)

| Piece | File | Notes |
| --- | --- | --- |
| Pinned experiment environment | `docs/` note + script | Worktrees, explicit `PYTHONPATH`, and the two commits plus native hash in every output |
| Duplicate runner, search vs search | `tuppi_ai/conv_eval.py` | Per-seat agents; forced NOLO; common random numbers; workers |
| Convention agent wrapper | `tuppi_ai/conventions/agent.py` | Rules restrict or choose; otherwise the plain search |
| Search on given worlds + rejection sampling | one C entry point in `tuppi_env.c` + Python | After the sooli edits there are committed; tested bit-identical |
| Analysis | `tools/conv_report.py` | Paired estimates, clustered bootstrap, split-sample selection |
| Pre-registration | `docs/prereg_conv_B.md`, `..._C.md` | Written before each confirmatory run: endpoint, estimator, arms, n, decision rule |

## Order and rough effort

Effort estimates are for one focused session and include tests. Machine time is
listed separately.

| Step | Work | Depends on | Effort | Machine |
| --- | --- | --- | --- | --- |
| 1 | D1 (v3 vs folding into v2), decided by the sooli implementer from `LOCKED_BIDS_RULESET_REVIEW.md` | - | - | - |
| 2 | B harness + the NOLO rules + pilot + stage 1 | Sooli edits in `search.py` committed (the wrapper subclasses it) | 1-2 days | ~2 h |
| 3 | A3-A4: v3 specification and reference engine | Step 1; sooli branch stable | 1-2 days | - |
| 4 | B stages 2-3, including the given-worlds entry point | Sooli edits in `tuppi_env.c` committed | 1 day | ~2.5 h |
| 5 | A5: native v3, clone check, differential tests, re-baseline | Steps 3 and 4 | 1-2 days | ~0.5 h |
| 6 | C: the RAMI signals (pilot on v1 any time after step 4; final on v3) | Step 5 | 1-2 days | ~3 h |
| 7 | A6: server, protocol, client | Step 3; coordination with the server edits and T1 | 2-4 days | - |

After this plan: the C4 seat-threshold study (`CONVENTIONS.md` §5.4) needs
step 5. It is the natural next experiment once v3 exists.

## Decisions (updated 2026-09-23)

1. **D1 (ruleset id):** delegated by the owner to the sooli implementer. See
   [`LOCKED_BIDS_RULESET_REVIEW.md`](LOCKED_BIDS_RULESET_REVIEW.md) and its
   "Decision" section.
2. **App:** humans lock their bids simultaneously. Unrevealed bids are never
   shown back, and never stored (owner: yes).
3. **Compute:** the owner found ~30 h too much. It was also a 3-4× overestimate
   (B5). The revised total is **about 7-8 h** (B ~4 h, A5 ~0.5 h, C ~3 h),
   run as pilot-sized chunks of at most 2 h, around the sooli work.
4. **V2's "strong hand returns the teammate's suit":** confirmed by the owner.
   "Their best suit" means the teammate's short suit.
