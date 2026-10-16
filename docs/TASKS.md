# Task backlog

Recorded 2026-09-24 from the project owner. Each task's status is in its own
section: T1, T3 and T4 part A are done; T2 has its after-deal review; T4 parts
B and C (the convention tests) have not started.

## T1 — Make the application as good as it can get

**Scope.** The macOS Swift client (`TuppiClient`) and the private-alpha server
(`TuppiProject/src/tuppi_server`) as the owner uses them to play.

**Known starting points.**
- The new bot is reachable only through `tools/serve_human.py`, which swaps AI
  seats at runtime. Making it the normal AI means changing the server's AI
  construction and the network protocol's `agent_profile` enum (currently only
  `partner_aware_v1`, `partner_aware_lead_v2`); the client decodes that value.
- `TuppiProject` has another author's uncommitted work in exactly these server
  files (`match_runner.py`, `analysis.py`, `completed_deal_review.py`,
  `post_match_diagnostics.py`), so changes need coordinating, not overwriting.
- The bot now decides in ~13-36 ms; the server's 5 s AI pacing is a choice, not
  a need.

**Owner's answers (2026-09-23).** All four areas: the new bot as the normal
AI; the real-game app completed (history, replays, end-of-match analysis for
locked bids and sooli); table polish; stability and merging with the other
author's work. Mac only. AI pacing near-instant (0.5 s or less).

**Status: done (2026-09-23).** TuppiAI's bot is the live server's AI when
installed (profile `tuppi_ai_search_v1`, labelled "TuppiAI"), with the
after-deal review and 0.5 s pacing; the live server defaults to the real game
(`project_target_v3`). Sooli deals are archived and replayed; the end of a
match summarises the reviews. Table fixes found by rendering the live table to
images (`TableSnapshotTests`): the lock panel stayed up after locking, card
codes instead of symbols, generic seat names in tricks, an empty trick panel
before play. Restart tests mid-bidding and mid-sooli. Merge rehearsed:
`docs/MERGING_V3.md`.

## T2 — Training functions that carry the bot's improvements to the human

**Status: the after-deal review is done (2026-09-23); drills later, as the
owner decided.** The bot's search re-decides each of the player's decisions
from the player's own observation; only clear mistakes are listed (gap >= 0.01
equity and >= 2.5 SE, confirmed on fresh worlds). Server endpoint
(TuppiProject branch `rules/project-target-v3-locked-bids`, `deal_review.py`),
TuppiAI reviewer (`tuppi_ai/review.py`, installed by `tools/serve_human.py`),
client sheet after each deal (TuppiClient branch `feature/v3-locked-bids-sooli`).
Calibration in `docs/STATUS.md`.

**Scope.** The client's learning features: live training odds
(`tuppi_server/training_analysis.py`: suit splits, card locations), completed
deal review and same-shuffle replay (`completed_deal_review.py`, `analysis.py`),
post-match diagnostics.

**Ideas to evaluate when started.**
- The search already computes a value for every legal move at every decision,
  so review can show "your move vs the best move, and what the difference cost
  in match equity", for showing and card play, instead of comparing only with
  the old incumbent's replay.
- Point the review at where the bot measurably gains over the incumbent:
  RAMI declarations (48.7% vs 37.7% of deals, 79.6% made), defence (38.6% of
  opponents' RAMIs stolen vs 28.2%), NOLO (69.2% won), and score-dependent
  play (edge grows when someone is up).
- Flag only decisions where the value gap is clear, since many decisions are
  near-ties or inert (the gain is many small improvements).
- Guard against privacy leaks: live (in-hand) advice may use only the seat's
  own observation; hindsight review after the deal may use the full deal.

**Owner's answers (2026-09-23).** A review **after each deal** (no live
hints); **only clear mistakes**, one line each (your move, the bot's move, the
equity cost, the kind of decision); for the **real game's rules
(`project_target_v3`) first**, the v1 analysis stays as it is; **drills later**,
once the review has proved useful.

**Added 2026-09-24 (owner's request).**
- **History analysis for the real game.** "Analysoi" works for sooli and
  locked-bid deals (`tuppi.analysis.real_game_deal.v1`): all four dealt hands,
  both exchanged cards of a sooli deal (the dead hand is shown), a replay of
  the same cards by four TuppiAI bots under the real rules, the comparison, and
  the review of the player's decisions linked to the replay. Room access keys
  are kept in `room-credentials.json`, so deals from closed rooms can be
  analysed while the server keeps the room.
- **Live odds during sooli.** The training window works in sooli deals with
  TuppiAI's sampler (`tuppi_ai/sooli_odds.py`): facts-only odds, and the bot's
  sooli inference (the soolaaja's hand is a sooli hand) behind the trust
  slider; measured to beat the facts-only odds on the bot's own soolis.
- **No behavioural assumptions in the real game.** The odds window's
  "assumed" rules were measured on the old bots and fail against TuppiAI's
  (and humans pick bid cards freely), so the server leaves them out there;
  the plain odds are calibrated. The belief net was worse and is not used
  (`docs/STATUS.md`, "Live odds tool against TuppiAI's bots").

## T3 — Add the "sooli" submode

**Status: done except training features (Phase F).** Rules given by the owner on 2026-09-24,
key questions answered the same day; the analysis and phased plan are in
`docs/SOOLI_PLAN.md`. Implemented (2026-09-23): ruleset `project_target_v2`
(TuppiProject branch `rules/project-target-v3-locked-bids`, which carries v2
and v3), the native core, solver, sampler and heuristics, the searched sooli
bot (results in `docs/STATUS.md`), and sooli in the server, protocol and
Swift client (TuppiClient branch `feature/v3-locked-bids-sooli`). Not merged
into the main checkouts, which carry other authors' uncommitted work.

**Consequences once specified.**
- TuppiProject's versioning policy: any change to legal actions, contract
  resolution, scoring or match transitions needs a **new ruleset identifier**
  (not an edit of `project_target_v1`), with config, reference implementation,
  fixtures and normative tests.
- Every layer changes: `tuppi_rules`, `tuppi_engine`, the native C core and its
  differential tests, the solver's polarity, the equity model, the server
  protocol and the client UI.
- The bot: the incumbent has no sooli play to imitate, so the behaviour-clone
  rollout policy cannot cover sooli deals. Search needs a rollout policy for
  them (new heuristics, or learning from scratch in the native engine, which
  earlier proved slow), and this is the least predictable part of T3.

## T4 - Locked bid cards and the convention tests

**Status: Part A (locked bids) done; Parts B and C (convention tests) not
started.** Ruleset `project_target_v3` = v2 + locked bids, through the engine,
native core, bot, server, protocol and client (same branches as T3); decision
D1 and the details are in `docs/LOCKED_BIDS_RULESET_REVIEW.md` section 8. On
2026-09-23 the owner decided to switch to
locked bid cards, as in the real game: nobody sees another player's bid before
bidding. The owner also asked for two convention tests, one for the table's
NOLO short-suit system and one for the RAMI signals. The plan is in
`docs/LOCKED_BIDS_AND_CONVENTION_TESTS_PLAN.md`; the background is in
`docs/CONVENTIONS.md`.

- **The rules change** needs a new ruleset id, recommended `project_target_v3`
  = v2 + locked bids.
- **It touches every layer:**
  - specification;
  - reference engine;
  - native core and bot;
  - server, protocol and client, which overlaps T1.
- **The NOLO test** needs no rules change and can start first.

## T5 - The bot's bidding in words a player can use

**Status: planned and parked (2026-09-24), owner's decision: build now, run
later.** Can TuppiAI's RAMI/NOLO decision be described with countable hand
features (HCP, controls, lengths, low cards, stoppers, seat, score), and what
does bidding by that description cost? Plan, prerequisites and pass criteria
fixed in advance: `docs/BIDDING_EXPLANATION_PLAN.md`. Built and tested at toy
size: the game database (`tools/gen_game_db.py`, reusable), features, readable
models, the rule bidder and the play test; start with
`bash tools/run_bidding_pilot.sh` (~3 h of machine time). The ruleset-3
sooli-settings leak in `SearchAgent.choose_action` is left unfixed by the
owner's decision (minor); the database resets it per game.

## T6 — Returned C0–C5 research implementation package

**Status: received and integrity-checked; implementation NOT_STARTED
(2026-09-25).** The owner requested discoverability markings for the next
implementation LLM, not execution in this registration step.

Start at [the implementation handoff](../../audit_deliverables/TUPPI_IMPLEMENTATION_HANDOFF.md).
The immutable package is in `../../audit_deliverables/tuppi_implementation_plan/`;
its `EXECUTION_PLAN.json` defines 27 tasks and their dependencies.
The first milestone is **C0+C1 contract completion and pilot readiness**.
Follow that graph for this programme; keep pilots, training, confirmation and
live deployment gated. This does not start T5's separate bidding pilot or
replace the earlier T1–T5 records.

## T7 — Faster search at the same strength

**Status (2026-09-29): E0-E5 done and installed. E7 (adaptive bids) was
adopted and committed (`da299a3`); it takes effect on the live server after
its next restart. E6 was not adopted, E9 was closed, and E8 was not started.
Value nets VN1 and VN2 were tested and neither was adopted (branch
`vn/value-net`, `docs/VALUE_NET_PLAN.md` there).** The
owner asked for a review of the native core and the bot for speed-ups that
keep the strength.

E0-E5 are commit `7388c36` on `main`. The live server was restarted on the
new library (`3d07008f`) on 2026-09-29.
Every move and searched value is identical, and the measured gains are:

- search 2.16x (W=128) and 2.17x (W=1024) in wall time;
- the 12-worker evaluator 2.32x.

The results are in `docs/STATUS.md`.

The C0–C5 research identity checks accept the upgrade (owner's request,
2026-09-29). The audit values are unchanged. A HEAD that descends from the
audited one is accepted, and an installed library is accepted if it is
registered in `POST_AUDIT_UPGRADES` (`tuppi_ai/research/identity.py`) with its
reason. All 109 research tests pass. Register each later library the same
way.
Profile, evidence and gates are in `docs/EFFICIENCY_PLAN.md`.

At W=1024 (live) busy CPU splits into:

- the sooli solver, 39%: almost all of it is the offer heuristic inside the
  bid rollouts;
- the endgame solver, 27%;
- the rollout network, 26%: mostly its sparse first layer;
- the sampler, 5%.

Bids take about half of all decision time. The Python engine takes 0.4%.

**Exact tasks** (same moves bit for bit, gated by a move fingerprint):

- **E0** baseline and fingerprint harness, first;
- **E1** faster sooli solver;
- **E2** sampler DP built once per observation; coordinate with the unmerged
  B0-S1 sampler fix in `../tuppi_execution_sampler_v1`;
- **E3** faster endgame solver;
- **E4** network first layer from an active-index list;
- **E5** rollout chunk 128 in the evaluators.

**Approximate tasks** (paired strength test, owner-approved compute):

- **E6** one card per rank-equivalent group: 22% of card-play actions, and
  9% of searches skipped;
- **E7** adaptive world allocation, mainly for the noise-dominated bids;
- **E8** a cheaper offer model in rollouts;
- **E9** solver-tail depth by cost.

Build to a separate library path until the gates pass. The live server and
the C0–C5 research pins (`tuppi_ai/research/identity.py`) use the installed
`native/libtuppi.dylib`.

## T8 — Self-play strength research: returned planning packet

**Status: planning handoff registered 2026-09-29; no implementation or
experiment is authorised by this registration.** For the first 100M self-play
programme and subsequent methods, start with the
[Strength-Maximisation Research Packet](../../audit_deliverables/tuppi_selfplay_research_20260929/TUPPI_SELFPLAY_STRENGTH_MAXIMISATION_PACKET.md).
It updates the adjacent `SELFPLAY_NEXT_METHODS_HANDOFF.md`; preserve both.

The proposed comparison is repaired SP1 versus privileged-Q VRPO, with a
PPO-V reference, matched total compute, complete-match evaluation and search
transfer. First refresh and freeze the actual SP1 checkpoint, configuration,
binary identity and 100M accounting, then independently verify its result
when assigned execution. The packet's scientific proposals remain unvalidated
here. Record future progress separately from the returned packet and the
earlier source snapshot. The inspected self-play checkout was `TuppiAI-sp/`.

## Earlier suggested order (T1–T3; to decide with the owner)

T3 changes the rules underneath T1 and T2, so specifying it first avoids
redoing the other two. T2 depends on T1 only where it touches the client UI.
