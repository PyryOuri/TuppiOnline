# Task backlog

Recorded 2026-09-24 from the project owner. **Status: not started** for all
three; nothing below has been executed.

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

**Open questions for the owner.** What "as good as it can get" means here:
stability, speed, look and feel, new features, match history, analysis? Which
complaints or wishes exist today? Mac only, or other devices too?

## T2 — Training functions that carry the bot's improvements to the human

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

**Open questions for the owner.** Live hints during play, review after each
deal, or both? How much detail per decision? Should drills (practice
positions) be generated from the owner's own mistakes?

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

## Suggested order (to decide with the owner)

T3 changes the rules underneath T1 and T2, so specifying it first avoids
redoing the other two. T2 depends on T1 only where it touches the client UI.
