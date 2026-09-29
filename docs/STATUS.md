# Status and results log

Newest first. Every equity figure is per base deal from `tuppi_ai.evaluate`
(4 rotations x 2 team assignments against `partner_aware_lead_v2` in the
authoritative TuppiProject engine, dealer 0, score 0-0 unless stated), with a
normal-approximation 95% interval over base deals. For scale: the incumbent's
own margin over its predecessor `partner_aware_v1` is +0.0054 [+0.0043, +0.0066]
on this instrument (TuppiProject's T4/T5 report +0.0057..+0.0064).

## Value net VN1, world counts, serial mode, branch evaluation (2026-09-29)

**Value net VN1** (`tuppi_ai/value.py`, `docs/VALUE_NET_PLAN.md`). A net from
full-information positions to the deal's equity change.

- **Training.** 4M rows of the search's own rollouts (clone play, sooli by
  the heuristics, exact 6-trick tail), from trick boundaries and from the end
  of bidding. The net is 512x3; validation R^2 0.745. Training runs on the
  GPU, with the packed rows unpacked and the 24 suit relabellings applied on
  the device.
- **Use.** Rollouts stop at a leaf and add the net's value.

Results:

- **Bid leaf at the end of bidding.** On 120 fresh bid positions against a
  4096-world full-rollout reference, the extra regret is +0.065e-3 ± 0.112
  per bid (within noise), and the bid search is about 100x faster.
  - Game test (512 deals, W=1024, against the live agent with E7):
    **+0.00010 [-0.00067, +0.00088]**, non-inferior, but only **1.09x** less
    CPU per deal. E7 had already removed most of the bid cost.
  - **The pre-registered speed bar was 1.5x, so it is not adopted.**
    Against fixed W=1024 without E7 it would have been 1.62x.
- **Card-play leaf.** On 207 positions, with the leaf placed 0, 1 or 2
  tricks after the decision's trick, the extra regret per decision is
  +1.34e-3 ± 0.31, +0.59e-3 ± 0.15 and +0.30e-3 ± 0.10, with no speed gain.
  A value net cannot resolve card-level differences; **dead.**
- **VN2** (the bot's own value, learned from bot pair vs incumbent games):
  data is being generated (`tools/gen_value_games.py`). Its gain is confined
  to bids, whose whole search value over the clone's bids was about +0.003,
  so the +0.002 kill criterion is a long shot.

**World counts** (the same 512 fresh v3 deals, rs=1, paired; descriptive, not
pre-registered):

| Comparison | Difference in equity per deal | CPU |
| --- | --- | ---: |
| 1024 - 128 | **+0.00107 [+0.00016, +0.00197]** | 7.6x |
| 1024 - 256 | **+0.00111 [+0.00018, +0.00203]** | 3.9x |
| 256 - 128 | -0.00004 [-0.00102, +0.00094] | 2.0x |

- 1024 worlds is measurably stronger, and on these deals 256 captures none of
  that gain.
- By the rule fixed with the owner before the 256 run, the live server stays
  at 1024.

**Serial search mode** (`TUPPI_AI_SERIAL=1`, `native.set_parallel`; every move
identical). In the 12-worker evaluator on 96 deals:

- CPU is -11% (1,795 to 1,599 s), but wall time is +12% (138 to 155 s) when
  the evaluator is the only job, because parallel mode fills the spare cores
  and the end-of-run tail.
- With several jobs on the machine, the load drops from about 140 to about
  20 and the rest of the machine stays usable.
- Use it for background batch jobs; keep the default for a lone job.

**Branch-point evaluation** (`tuppi_ai/branch_eval.py`) was meant as a
lower-noise screen. It was validated on E6's 512 test deals and came out
**noisier than the game test**: sd 0.0181 per base deal, against 0.0090, at
the same CPU. A variant that deviates about 4.5 times per game adds each
branch's divergence. It is not used.

**Reproducibility note.** `evaluate.py` gives a worker a new chunk of 8 base
deals whenever it is free, and a search agent's random stream carries across
the deals it plays. So with more chunks than workers (for example 512 deals),
a rerun gives statistically equivalent but not bit-identical games. With at
most one chunk per worker (48 or 96 deals on 12 workers), reruns are
identical.

## Efficiency tasks E6, E7, E9: adaptive bids adopted for live play (2026-09-29)

Paired tests on 512 fresh v3 base deals against the incumbent, with
per-decision reseeding (`rs=1`) in both arms. The criterion was fixed in
advance: non-inferior when the 95% lower bound of variant minus reference is
above -0.0010 equity per deal.

| Task | Setting | Variant - reference | CPU per deal | Decision |
| --- | --- | --- | ---: | --- |
| E6 | W=128, one card per rank-equivalent group | -0.00057 [-0.00135, +0.00021] | -9% | **not adopted** |
| E7 | W=1024, adaptive worlds for bids (batch 128, z 2.5, delta 0.005) | -0.00032 [-0.00098, +0.00034] | **-32%** (1.48x) | **adopted, live** |

- **E6.** The choice between equivalent cards is not noise. The rollouts
  model how the incumbent's partner and opponents react to the exact card, and
  that reaction is real in play, so searching one card per group gives up
  some signalling value.
- **E7.** It passes by a narrow margin: the point estimate is slightly
  negative, and the test could not rule out a small loss.
  - Behaviour was unchanged: declarations 46.5% vs 46.8%, deals won 68.0% vs
    67.4%.
  - Bid time at 1024 worlds is about 2.7x lower.
  - Card play stays at fixed worlds. The offline screen found that the loose
    setting costs about 0.04-0.08e-3 per card-play decision, and the strict
    one saves only 1.3x.
  - `best.py` turns it on above 128 worlds, so the live server (1024) uses it
    and the 128-world default is bit for bit unchanged.
- **E9.** A solver tail of 5 costs 4% less CPU and a tail of 4 costs 1% more.
  Neither is clearly cheaper, so there was no strength test and no change.

The per-decision reseeding did not keep the arms paired: an early changed
decision diverges the rest of the deal, so only 32 of 512 (E6) and 82 of 512
(E7) deals came out identical. `tuppi_ai.branch_eval` (value-net branch) is
being built as a lower-noise screen for this kind of change.

## Exact speed-ups E0-E5: search 2.1-2.4x faster, same moves (2026-09-29)

Tasks E0-E5 of `docs/EFFICIENCY_PLAN.md`, on branch `perf/e0-e5` (worktree
`~/Developer/TuppiAI-perf`). Every change is exact: the moves and the
searched values are bit for bit those of the previous build.

**What changed.**

- **E0, tools.** `tools/profile_search.py` plays fixed v3 deals with the best
  agent on four seats, fingerprints every decision (action plus the exact bits
  of every searched value), and compares two source trees in separate
  processes. `tools/native_oracle.py` dumps exact outputs of the endgame
  solver, sooli solver, offer heuristic, sampler and network per library, for
  diffing.
- **E1, sooli offer.** The offer heuristic accepts when at least 4 of 8
  worlds survive, and the order in which the worlds are solved cannot change
  that count. So every world is first solved with a 2,000-node budget, and
  only while the answer is still open are the undecided worlds solved in full.
  - Proving survival is where the time goes: about 166k nodes per surviving
    world against about 1.7k per losing one, and the top 10% of solves take
    99% of the nodes.
  - The rng advances exactly as before.
  - The solver's thread-local state moved into a context struct, and the
    move representatives and transposition key are cheaper to compute.
- **E2, sampler.** The suit-split counting tables are cached per observation
  (8 entries per thread). They depend only on the free cards, the voids and
  the tilt, so a cached table is the table a rebuild would compute.
- **E3, endgame solver.**
  - The last trick is evaluated directly.
  - Move generation walks only the mover's own cards.
  - The canonical key walks only the live cards.
  - There are no thread-local reads in the recursion.
- **E4, network.**
  - The first layer adds the active features' columns in the same order as
    before, one 32-wide register tile at a time, after an eight-bytes-at-a-time
    scan for active features.
  - Layer norms run four rows at a time, each row's sums in its old order.
- **E5, batch settings.** Rollout chunk 128 in the worker initialisers of
  `evaluate.py` (so also `match_eval.py`), `bid_rule_eval.py`,
  `review_calibrate.py`, `sooli_bank.py` and `sooli_play_eval.py`.

**Checks.**

- Every oracle is identical on the old and new libraries:
  - 3,000 endgame solves;
  - 3,000 sooli solves;
  - 1,500 offers, decisions and rng states;
  - 19,200 world draws in every phase and belief mode, and the rng after them;
  - 3.7M logits.
- Profile fingerprints are identical in all 20 timed runs.
- A 48-deal v3 evaluation gives identical values for all 384 games under the
  old build, the E5-only build and the full build.
- All 35 tests pass.

**Speed.** Median of 5 paired runs, alternating order, best agent on four
seats, fixed v3 deals, chunk 32:

| Workload | Wall before -> after | CPU before -> after |
| --- | ---: | ---: |
| 12 deals, W=128 | 16.34 -> 7.57 s (**2.16x**) | 119.8 -> 57.1 s (2.10x) |
| 4 deals, W=1024 (live) | 30.53 -> 14.10 s (**2.17x**) | 335.8 -> 163.6 s (2.05x) |

Runs varied by under 2%.

By decision kind (wall time, W=1024):

- bids 2.75x;
- early RAMI card play 1.74x;
- late card play 2.67x;
- sooli 2.66x.

At W=128, bids are 2.85x.

**Evaluation throughput.** `tuppi_ai.evaluate --checkpoint best --ruleset v3
--deals 48 --workers 12`, one run each:

| Build | Wall | CPU |
| --- | ---: | ---: |
| before | 161.9 s | 2,157 s |
| E5 only | 155.9 s (-4%) | 2,052 s (-5%) |
| all of E1-E5 | **69.7 s (2.32x)** | **905 s (2.38x)** |

**Where the time goes now** (W=1024, busy CPU):

- rollout network 37%;
- sooli solver 30%;
- endgame solver 28%;
- sampler 1%.

**Tried, no gain:**
- a single full-window endgame solve instead of the binary search of
  null-window probes (5% slower);
- a column-major sparse first layer (2x slower);
- a suit-permutation-invariant sooli key (1%, not kept).

**Tried, much slower:** a non-canonical sooli key, 30x slower. The rank
canonicalisation is essential.

**Not installed.** The live server and the C0-C5 research pins still use
`TuppiAI/native/libtuppi.dylib` (`02d9b4fa...`); the new build is
`3d07008f...`. Installing it, and re-pinning
`tuppi_ai/research/identity.py`, is the owner's decision.

## Exact speed-ups for batch generation (2026-09-24)

Both keep every move bit-identical (12 fixed v3 deals, best agent on four
seats, same move fingerprint before and after; the bot is deterministic):

* **Sooli offer heuristic stops solving once settled.** It accepts when at
  least 4 of 8 sampled worlds survive; it now stops the solves when that is
  decided but still draws the remaining worlds, so the rng advances exactly
  as before. 156.2 -> 134.7 CPU-s for the 12 deals (-14%).
* **Rollout batch size is a setting** (`native.set_rollout_chunk`): 32 (the
  default, lowest latency for live play) or 128 (-7% total work, fewer cores
  per search) for jobs that run several processes; `gen_belief_tuppi.py` uses
  128.

Tried without gain: a 4x larger sooli solver table (134.8 CPU-s). CPU now:
bid searches 58%, early trick play 33%; inside them the sooli solver about
half of the busy time, the endgame solver and the rollout network about a
quarter each.

Generator throughput (48 deals, on battery): **1.04 deals/s with 3 workers**
(0.93 with 2), 10.5-10.7 CPU-s per deal, against 0.83 deals/s and 13.7 CPU-s
before. A long run needs `caffeinate -i`: an earlier measurement stalled when
the Mac slept.

## Belief net trained on TuppiAI's own play: pilot fails at 500 deals (2026-09-24)

Can a card-location net learned from the bots the owner plays beat the exact
odds? Pilot with early stopping: `tools/gen_belief_tuppi.py` 500 v3 deals (547
s; every 10th held out: 47 ordinary test deals; 85,696 training rows from 412
deals, every seat's view at every trick-play step), `belief_v1` fine-tuned
(`python -m tuppi_ai.belief --init runs/belief_v1.pt`, lr 3e-4, batch 1024,
3 or 10 epochs), measured by `tools/belief_eval.py` on the held-out deals and
on the owner's own 53 ordinary real-game deals from the server's saved rooms
(the human seat against three TuppiAI bots). Mean NLL per unseen card minus
the exact odds' (exact: 1.064 on both sets), 95% intervals clustered by deal:

| Net, alpha | Held-out self-play | Owner's games |
| --- | ---: | ---: |
| old `belief_v1`, 0.5 | +0.165 [+0.131, +0.199] | +0.190 [+0.154, +0.227] |
| fine-tuned 3 epochs, 0.5 | +0.176 [+0.148, +0.203] | +0.186 [+0.152, +0.220] |
| fine-tuned 10 epochs, 0.5 | +0.478 [+0.421, +0.535] | +0.490 [+0.433, +0.548] |
| old, 0.1 | +0.001 [-0.005, +0.007] | +0.001 [-0.006, +0.008] |
| fine-tuned 3 epochs, 0.1 | +0.002 [-0.004, +0.008] | +0.002 [-0.004, +0.008] |
| old / fine-tuned 3 epochs, 0.25 | +0.036 / +0.036 | +0.039 / +0.038 |

**Clear failure; stopped.** No net beats the exact odds at any trust; at alpha
0.1 they only tie. 412 deals do not teach the net TuppiAI's play: the short
fine-tune is the old net, the long one memorises the training deals (its
row-level hold-out, which shares deals with training, fell to 0.047 nats, a
leak, not skill). Learning TuppiAI's play in general would need deals in the
tens of thousands (the old net's data came from about 180,000 games), 7-33 h
at 0.83 deals/s, with an uncertain ceiling: the search picks among near-ties
by its own sampling noise, which says little about its cards. The owner's
games and the held-out self-play agree to within 0.03 on every row, so
self-play is a fair stand-in for the owner's use. The exact odds stay.

## Bid search: sooli offers resolved in parallel (2026-09-24)

Under project_target_v2/v3 a bid search plays every legal bid to the end in
128 worlds; most rollouts reach a RAMI, and the defenders' sooli offers in
them are answered by the heuristic, which runs the exact sooli solver on
sampled worlds. `search_core` resolved those rollouts one at a time, so a bid
search took 0.8-3.9 s on about one core, against 0.04-0.07 s on 6-9 cores for
the same search with no sooli in the rollouts. They now run in parallel
(`dispatch_apply`; each rollout's own rng stream seeded from one draw of the
shared one, so a search stays reproducible; the solvers' tables were already
per-thread; the log-factorial table is now filled once with `dispatch_once`).

| 8 v3 deals, best agent on all four seats | Before | After |
| --- | ---: | ---: |
| bid search (6 positions) | 0.84-3.91 s | 0.25-0.66 s |
| bid decision, mean | 2.15 s | 0.35 s |
| deal | 6.16 s | 1.50 s |
| cores busy | 1.8 of 14 | 7.9 of 14 |
| real-game analysis replay (TuppiProject, 4 deals) | 1.2-11.8 s | 1.3-2.1 s |

The work per deal is unchanged (about 12 CPU-seconds), so jobs that already
ran 12 processes gain little: the v3 evaluation of 128 base deals (seed v6)
took 527 s, 4.1 s per deal against 4.95 before. **Strength unchanged:** on
those 128 deals +0.0185 [+0.0139, +0.0231] against +0.0166 [+0.0132, +0.0199]
before, paired +0.0020 [-0.0038, +0.0077] (only the rollouts' random draws
changed; 65 of 1,024 games came out identical).

**Belief-net data from TuppiAI itself** (`tools/gen_belief_tuppi.py`): v3
self-play of the best agent, every seat's observation at every step of
ordinary trick play (about 200 rows per deal, against about 45 when only the
actor is recorded), the `gen_belief.py` format. 0.83 deals/s with two workers
(40 deals in 48 s, about 14 CPU-seconds per deal): 1,500 deals, about 300,000
rows, in about 30 minutes.

## Live odds tool against TuppiAI's bots (2026-09-24)

The training window's odds (TuppiProject `tuppi_server.training_analysis`):
exact uniform odds over the layouts consistent with the seat's observation,
and an "assumed" view adding four behavioural rules measured earlier on the
old reference bots. The owner plays against TuppiAI, so both were re-measured
there (`tools/odds_calibration.py`: 240 v3 deals, TuppiAI's best agent on all
four seats, authoritative engine, 1,217 trick-play positions of one observed
seat; 14 sooli deals counted, not measured). Mean negative log-likelihood of
each unseen card's true holder (lower is better; uniform over three seats is
1.099), 95% intervals clustered by deal:

| View | NLL per unseen card | vs exact |
| --- | ---: | ---: |
| **exact odds** | **1.065** [1.060, 1.069] | - |
| belief net `runs/belief_v1.pt`, alpha 0.5 | 1.256 | +0.191 [+0.172, +0.211] |
| belief net, alpha 1.0 | 1.710 | +0.646 [+0.602, +0.689] |
| assumed view (69% of positions) | 1.441 | +0.370 [+0.328, +0.411] |

* **The exact odds are calibrated** (every probability bucket within about
  0.02 of the observed frequency).
* **The belief net is overconfident against TuppiAI:** at alpha 1.0 its "0.9-1.0"
  bucket (mean 0.96) is right 42% of the time. It was trained on another
  policy's play (distilled search vs the clone), as the search result above
  already suggested. Not added to the tool.
* **The behavioural rules fail for TuppiAI's bots.** Firings and violations
  against the true hands: `show_lowest` 358 of 506 (the bot chooses its bid
  card by search; humans pick theirs freely), `follow_low` 753 of 2,752,
  `duck_high` 104 of 408, `win_high_last` 13 of 71. The assumed view excluded
  the true holder of 1,411 of 18,509 cards (7.6%); its median prior is 0.055.
  **The server now shows no assumed view in the real game or where TuppiAI
  plays** (TuppiProject `1347153`).

**The sooli view passes** (`tools/sooli_odds_calibration.py`, the bank of 600
soolis the bot itself accepted, a RAMI player at the first sooli lead, 400
layouts): facts-only 1.060 nats per unseen card, the search's sooli belief
(prefilter + tilt 0.3, `tuppi_ai/sooli_odds.py`) **1.007, paired -0.053 +-
0.004**, mostly on the soolaaja's cards (1.063 -> 0.955) and the dead hand
(1.063 -> 1.007); calibrated within about 0.01 below 0.6, slightly
overconfident at 0.6-0.8 (0.64 -> 0.57, 0.73 -> 0.61, few cards). It stays as
the sooli "assumed" view. Measured on the bot's own soolis; a human soolaaja
may call sooli on other hands.

## After-deal review (T2): calibrating "clear mistake"

The review (`tuppi_ai/review.py`, served through TuppiProject's
`/v1/rooms/{code}/deals/{n}/review`) re-decides each of a seat's decisions
from that seat's observation at the time with the best agent's search
(W=256; flags confirmed on 1,024 fresh worlds with the recommendation held
fixed, which removes the best-of-many selection bias from the reported
cost). Calibration (`tools/review_calibrate.py`, 60 v3 deals, bot seats 0/2
vs incumbent 1/3, every seat reviewed; 1,289 bot and 1,318 incumbent
decisions):

| Threshold (gap, SE) | Bot flags / seat-deal | Incumbent flags / seat-deal | Incumbent flagged cost / seat-deal |
| --- | ---: | ---: | ---: |
| 0.004, 2.5 | 0.125 | 1.74 | 0.046 |
| **0.01, 2.5 (default)** | **0.058** | **1.19** | **0.043** |
| 0.01, 3.0 | 0.042 | 1.15 | 0.042 |

The bot reviewing its own play is the false-alarm check: a player who plays
like the bot sees a flag about once every 17 deals. The incumbent's flags
are mostly leads (121 of 210 at 0.004), then follows, discards, sooli leads,
bids and sooli offers. **The estimated costs are inflated:** the incumbent's
flagged costs add up to about six times its measured deficit (~0.0075 per
seat-deal), the usual optimism of search values about the search's own
choices. The client therefore shows them as the bot's estimate and says that
the ranking is more reliable than the size. Review time: about 1 s per deal
(4 s for the first, which loads the model).

## project_target_v3 (locked bids + sooli): re-baseline against the incumbent

The same 512 base deals as the W=128 v1 result (seed v6), best agent against
`partner_aware_lead_v2` (with TuppiProject's sooli fallback: it never offers
sooli and defends one with simple heuristics), under `project_target_v3`
(`tuppi_ai.evaluate --ruleset v3`):

| Rules | Equity/deal vs incumbent | Deal win | Bot declares | Opp. RAMI stolen |
| --- | --- | ---: | ---: | ---: |
| v1 (earlier bids visible) | +0.0150 [+0.0135, +0.0165] | 66.5% | 48.5% | 22.7% |
| **v3 (blind bids, sooli)** | **+0.0152 [+0.0136, +0.0168]** | 66.5% | 46.9% | 22.1% |
| paired v3 - v1 | +0.0002 +- 0.0012 | | | |

Two effects that cancel: bidding blind loses part of the showing edge (the
bot declares less often: it can no longer see a partner's or an opponent's
earlier bid), and sooli adds: the bot played 93 soolis in 4,096 games (2.3%)
and won 68 (73%), +0.035 equity per sooli game. The 73% is against the
fallback's weak RAMI defence; against the bot's own RAMI play the banked
soolis survive ~34-39% (below). Clone check for masked bids: its bids agree
with the incumbent's 99.56% (99.84% with earlier bids visible), so no
fine-tune. The run took 2,535 s (v1: 857 s): sooli searches are costlier.

**Soolaaja play against the strong RAMI pair** (bank of the bot's own
soolis, RAMI pair = search with prefilter + tilt 0.3): heuristic soolaaja
0.334, searched soolaaja 0.390 (paired +0.056 +- 0.025; with heuristic
rollouts 0.376). The default searches.

## Sooli (project_target_v2): the bot's sooli decisions

Not on the instrument above: sooli needs `project_target_v2`, which the
incumbent does not play. Measured natively (the native core is lockstep-tested
against the v2 engine). Survival = the soolaaja takes no trick. Tools:
`tools/sooli_bank.py`, `tools/sooli_play_eval.py`, `tools/sooli_offer_check.py`.

**How often sooli is viable.** Over 15,570 random RAMI deals (shows by the
rollout clone), a defender whose sooli survives a perfect exchange and
perfect-information play exists in about 5% of RAMI deals, close to the
owner's human rate of ~1 in 20.

**The realistic bank** (`runs/sooli/bank_v1.pkl`): 1,219 soolis the bot
itself accepts (offer by search, margin 0.02; searched give; heuristic
return) out of 14,000 random deals, i.e. about 11% of RAMI deals, roughly
twice the human rate.

Soolaaja survival on that bank, by the RAMI pair's play (soolaaja heuristic;
+-0.027):

| RAMI pair | Survival |
| --- | --- |
| heuristic | 0.546 |
| search, uniform-with-prefilter belief | 0.419 |
| search, exposure tilt 0.2 / 0.3 / 0.45 | 0.366 / 0.346 / 0.366 |
| **search, prefilter + tilt 0.3 (default)** | **0.334** (paired -0.085 +- 0.026 vs. prefilter only) |
| search, plausible exchange + tilt 0.3 | 0.346 |
| reference: knows the soolaaja's hand | 0.203 |
| reference: perfect information | 0.110 |

The belief is what matters: the uniform sampler draws soolaaja hands with a
median exposure of 33, the banked soolaajas' real hands have 15. The tilt
reweights worlds by exp(-lambda * exposure); exposure against the rest of the
deck is a sum over suits of max(0, rank_i - 2i) in ace-low ranks, so the tilt
is sampled exactly inside the suit-split DP (0.1-0.3 ms per world, 15-180x
faster than rejection).

**The offer.** Against realised outcomes on 1,500 prefiltered offers (sooli
play by the heuristics for all three): the search with heuristic sooli play
in its rollouts gains +0.023 +- 0.006 equity per offer vs. never accepting;
the same search with the solver finishing the rollouts accepts only 28 of
1,500 (+0.004); the 8-world heuristic offer accepts 30 (+0.002); hindsight
would gain +0.059. Against the stronger RAMI pair (default search above), the
bank's accepted soolis still gain +0.050 +- 0.013 per sooli over declining,
positive in every predicted-gain bucket; predictions are about twice the
realised gain, so the 0.02 margin stays. These are very weak defending hands:
sooli caps the loss of an ordinary RAMI deal that would be lost heavily.

**The exchange** (PI survival after the exchange on positions that survive a
perfect exchange): heuristic give + heuristic return 0.573; searched give
0.619; a searched return never beat the heuristic "lowest card" return on
either bank (0.547 vs 0.573; 0.106-0.112 vs 0.110 with the new beliefs).
Each half of a perfect exchange is worth ~0.18-0.19 here, so the return is
where the most is left, and only better inference about the soolaaja's hand
can get it.

**Defaults** (`tuppi_ai/search.py`, `SOOLI_DEFAULTS`): offer by search with
margin 0.02; give and sooli play by search; return by the heuristic; beliefs
prefilter + tilt 0.3.

## 2026-09-24 — spending the speed: W=128 becomes the default

512 fresh base deals (seed v6), paired, both with the native search:

| Worlds | Equity/deal vs incumbent | Deal win |
| ---: | --- | ---: |
| 64 | +0.0137 [+0.0121, +0.0152] | 65.1% |
| **128** | **+0.0150** | 66.5% |
| difference | **+0.0013 +- 0.0011** | |

Small but real (the earlier 128-deal estimate was +0.0008 +- 0.0021).
Latency at W=128 with all cores: showing median 36 ms (max 43), card play
median 13 ms (max 61). `serve_human.py` and `human_report.py` now default to
128 worlds. Going further (256) is not planned: the curve is flattening.

## 2026-09-24 — exact speed-ups (same moves)

The per-decision search now runs entirely in C (`tc_search_values`): world
sampling, play-outs with a native forward pass of the rollout network
(`tuppi_mlp.c`: sparse first layer over the 0/1 features, Accelerate sgemm for
the rest), spread over all cores, and the solver tail. The solver's
transposition table now persists across solves (entries are exact bounds on a
pure function of the canonical position; contract polarity is in the key).

Checks: network logits within 3.6e-5 of PyTorch, argmax identical on 20,480
decisions; action values bit-identical to the Python search on 773 decisions;
**518 of 518 searched decisions identical** over 12 full deals through the
authoritative engine; solver answers independent of solve order; all tests pass.

| | Before | After |
| --- | ---: | ---: |
| per searched decision, one thread-equivalent | 34.9 ms | 9.5 ms (3.7x) |
| showing decision, whole machine (median / max) | ~570 / 650 ms | 24 / 30 ms |
| card play, whole machine (median / max) | ~100 / 570 ms | 8 / 49 ms |
| 128-deal evaluation on 13 workers | 319 s | 116 s (2.75x) |

The GPU is not used for play: a play-out step now costs ~0.5 ms on the CPU,
about one GPU round trip.

## 2026-09-23 (day) — where the gain comes from, and what does not add to it

**Breakdown** (256 base deals, seed v5, search W=64 vs the incumbent pair on
the same deals):

| | Incumbent pair | Search team |
| --- | ---: | ---: |
| deals where own team declares RAMI | 37.7% | 48.7% |
| RAMI made when own team declares | 71.8% | 79.6% |
| incumbent's RAMIs stolen when defending | 28.2% | 38.6% |
| NOLO deals won | 50.0% | 69.2% |

Better declarer play, better defence, better NOLO play, and more declarations
because more contracts are makeable.

**Where the time goes** (one base deal, single thread, 6.9 s): rollout network
forwards ~55%, solver tail ~24%, sampling and bookkeeping the rest. A native
port of the incumbent for rollouts would buy ~2x, not the orders of magnitude a
nested search would need.

**Refinements that are within noise** (same 128 deals, paired vs W=64
reference +0.0142):

| Variant | Paired |
| --- | --- |
| ties go to the blueprint's action | -0.0007 +- 0.0020 |
| deviate only if gain > 0.005 equity | **-0.0134 +- 0.0031** (the gain is many small improvements) |
| 256 worlds for showing decisions | +0.0010 +- 0.0023 |
| team seats rolled out by `xi1_small` | +0.0005 +- 0.0024 |

| stochastic opponent rollouts (softmax T=4), at home | -0.0004 +- 0.0022 |
| same, vs `legacy_heuristic_port_v1` (paired vs plain search) | -0.0015 +- 0.0017 |
| bonus on own RAMI declarations, +0.001 equity | -0.0030 +- 0.0024 (RAMI rate 85% -> 93%) |
| bonus +0.002 / +0.005 / +0.01 equity | -0.0057 / -0.0121 / -0.0130 |

Showing is already calibrated: many show decisions are near-ties, and any
push toward RAMI over-declares.

**Learned belief (card-location network).** Trained on 8M native self-play
positions (distilled-search team vs clone team): held-out NLL 0.436 nats per
unseen card vs 1.099 uniform-over-3 (TuppiProject Phase 5G-B's hard-uniform
baseline: 1.050). Using it:

* reweighting 1024 uniform candidates collapses (median ESS in early play 6
  of 1024 at alpha 0.5), so worlds are instead drawn *exactly* from the
  tempered product of the network's marginals over the hard-feasible set
  (`tc_sample_world_weighted`, a DP over cards x capacities; tested against
  enumeration);
* the search gets monotonically worse the more it trusts the belief: alpha
  0.25 -0.0001 +- 0.0024, alpha 0.5 -0.0022 +- 0.0026, alpha 1.0
  **-0.0075 +- 0.0030**.

Most likely the belief is confidently wrong about the *partner*, who is the
search agent (declares RAMI on ~50% of deals vs the clone's ~37%), not the
policies in the training data. Uniform worlds are the robust choice; beliefs
learned from bots would transfer to humans even less.

## 2026-09-23 (morning) — solver-tail depth

Same 128 deals (seed v3), W=64, paired against tail 6 (+0.0142):

| Tail | Equity/deal | Paired vs tail 6 | Time |
| --- | --- | --- | ---: |
| 4 tricks | +0.0144 | +0.0001 +- 0.0022 | 432 s |
| 6 tricks | +0.0142 | reference | 319 s |
| 8 tricks | +0.0117 | -0.0025 +- 0.0023 | 1453 s |

A longer perfect-information tail adds clairvoyance optimism and costs time;
6 is the setting.

## 2026-09-23 (morning) — expert iteration round 2 does not compound

947k decisions searched at W=64 over `xi1_small`, distilled together with the
round-1 data (2.3M rows, init from the round-1 nets):

| | Equity/deal | Note |
| --- | --- | --- |
| `xi2`, no search | +0.0021 [+0.0013, +0.0028] | round 1 was +0.0027 |
| `xi2_small`, no search | +0.0016 [+0.0008, +0.0024] | |
| search over `xi2_small`, W=64 | +0.0129 | paired -0.0013 +- 0.0023 vs search over the clone |

Distilled nets match the searched action only ~64% of the time: most of the
search's gain is calculation over the sampled layouts, which an
observation-only network does not recover from argmax labels. The loop as run
does not compound; the search itself carries the strength.

## 2026-09-23 — headline: W=64 search against the incumbent

| Endpoint | Sample | Result |
| --- | --- | --- |
| per-deal equity, fresh seed v4 | 384 base deals (3072 games) | **+0.0143 [+0.0125, +0.0161]**; 65.8% deals won; +4.2 points and 7.00 tricks per deal |
| **complete matches to 52**, fresh streams | 128 complementary pairs (256 matches) | **p_win 0.953 [0.928, 0.978]**; pairs 116 won / 12 tied / 0 lost; 0 censored; 20.1 deals per leg |
| replication, new stream seed match-v2 | 128 pairs | p_win 0.9375 [0.909, 0.966]; 112 / 16 / 0 |
| **pooled** | 256 pairs (512 matches) | **228 won / 28 tied / 0 lost; p_win 0.945** |
| vs `legacy_heuristic_port_v1` (not modelled by the rollouts) | 96 pairs | p_win 0.990; 94 / 2 / 0; 8.7 deals per leg |

Agent: `search:runs/bc_small.pt:w=64:dd=6:show=1` - uniform hard-feasible
worlds, every legal action (showing included) rolled out by the incumbent
clone, last 6 tricks solved exactly. Decision latency with the machine busy:
showing median 0.57 s (max 0.65 s), card play median 0.10 s (max 0.57 s).
For comparison, every earlier principled method in TuppiProject lost to the
incumbent's predecessor at p_win 0.0-0.16.

### Starting score

TuppiProject measured everything at 0-0. With starting scores drawn uniformly
over the 25 nonterminal states (192 base deals, seed scores-v1):

| Starting score | Base deals | Equity/deal |
| --- | ---: | --- |
| 0-0 | 10 | +0.0073 +- 0.0083 |
| someone up 4-24 | 94 | +0.0179 +- 0.0051 |
| someone up 28-48 | 88 | +0.0615 +- 0.0172 |
| all | 192 | +0.0373 [+0.0285, +0.0462] |

The search prices rollouts in match equity at the real score and the
incumbent is score-blind, so the edge grows where the rising-score rule bites.
Part of the growth is scale (equity swings are larger late in a match); the
complete-match result above already weights states by how often they occur.

### Transfer: is the edge general or a model of this opponent?

The search's rollouts play every other seat with the incumbent clone, so against
the incumbent it has an accurate opponent model. Against opponents it does not
model, the search's improvement over the incumbent (same deals, both measured
against the same opponent, 128 base deals, seed transfer-v1):

| Opponent | Search vs it | Incumbent vs it | Improvement | Share of home margin |
| --- | --- | --- | --- | ---: |
| `partner_aware_v1` | +0.0203 | +0.0054 | +0.0149 +- 0.0037 | 104% |
| `reactive_contract_v1` | +0.0208 | +0.0093 | +0.0115 +- 0.0033 | 80% |
| `legacy_heuristic_port_v1` | +0.0281 | +0.0189 | +0.0092 +- 0.0036 | 64% |

Mostly general, with compression against the most foreign opponent (the same
pattern TuppiProject's T5 found for the incumbent's own improvement).

## 2026-09-23 (night) — world count, expert iteration round 1

Paired comparisons on the same 128 base deals (seed v3). Search changes both
showing and play (show=1), solver tail 6, small clone as rollout policy unless
stated.

| Variant | Equity/deal | Paired vs reference | Deal win |
| --- | --- | --- | ---: |
| play-only search, W=16 | +0.0057 | reference for belief/showing rows | 55.5% |
| + showing search (show=1), W=16 | +0.0086 | +0.0029 +- 0.0028 vs play-only | 59.9% |
| two-stage showing (show=2), W=16 | +0.0076 | -0.0010 +- 0.0030 vs show=1 | 59.2% |
| show=1, **W=32** | +0.0120 | +0.0034 +- 0.0029 vs W=16 | 63.0% |
| show=1, **W=64** | **+0.0142** | **+0.0056 +- 0.0027 vs W=16** | **64.8%** |
| show=1, W=16, rollouts by round-1 net `xi1_small` | +0.0079 | -0.0007 +- 0.0030 vs clone rollouts | 59.8% |

Expert iteration round 1: 1.35M decisions searched (W=16, show=1) over the
small clone, distilled by cross-entropy on the searched action (20% imitation
data mixed in). The distilled networks, **without search**, beat the incumbent:

| Network | Base deals | Equity/deal | Deal win |
| --- | ---: | --- | ---: |
| `xi1` (768x4) | 1024 | +0.0027 [+0.0018, +0.0036] | 53.1% |
| `xi1_small` (256x2) | 1024 | +0.0025 [+0.0016, +0.0034] | 53.3% |

## 2026-09-23 — search beats the incumbent

| Candidate | Base deals | Equity/deal | Deal win | Notes |
| --- | ---: | --- | ---: | --- |
| search over clone, W=16, solver tail 6 (seed v1) | 128 | +0.0080 [+0.0055, +0.0105] | 58.2% | +0.35 tricks/deal |
| same, fresh seed v2 | 384 | **+0.0067 [+0.0051, +0.0082]** | 57.1% | +0.32 tricks, +2.0 points/deal |
| behaviour clone `bc_v1` (768x4, 98.1% agreement) | 1024 | +0.00004 | 50.2% | parity, as intended |
| small clone `bc_small` (256x2, 97.9%) | 1024 | -0.0003 | 49.8% | parity; 8x cheaper rollouts |

The search only changes trick play (showing is the clone's), so the whole
margin is card play.

## What did not work, and why (keep)

* **Plain DMC self-play from scratch (`dmc1`)**: -0.047 after 1.6M deals, and
  only +0.012 against an untrained network. Rare match-ending outcomes carry
  ~49% of the Monte Carlo target variance; the network learned state value and
  never separated card plays (median Q-spread 0.0019 equity).
* **Paired counterfactual branching from scratch (`pair1`)**: better data, same
  failure. Offline, a fresh network explained *none* of the branch-difference
  variance: under a near-random continuation, one changed card sends the rest of
  the deal down an unrelated path, so differences measure chaos, not the card.
* **Q-learning over a fixed blueprint (`pi1`)**: greedy on the learned Q was
  worse than the blueprint (-0.020); with a deviation margin it was neutral.
  Maximising noisy Q estimates over 13-26 showing actions over-declares RAMI
  (84% vs ~75%), the same selection optimism TuppiProject's Phase 5C saw.
* **Belief-weighted worlds (policy-based inference), first attempt**: 64
  uniform candidates weighted by the clone's likelihood of the other seats' past
  choices, 16 resampled. Worse than uniform on the same 128 deals: all seats
  -0.0068 +- 0.0025, opponents only -0.0054 +- 0.0024, opponents only with
  softened likelihood (T=3, eps=0.3) -0.0012 +- 0.0024. Two causes: the partner
  is the search agent, not the clone (37% of its choices differ), and
  resampling 16 from 64 collapses onto a handful of distinct worlds. Needs far
  more candidates or a better proposal, not a sharper model.
* **Phase 6's "imitation fails"** was data volume: 13M incumbent decisions give
  98.1% agreement and parity, against 20k decisions and 85% there.

## Throughput reference (M3 Max)

* native env, random policy: ~1.2M decisions/s (one core)
* authoritative Python engine + incumbent: ~740 deals/s on 12 workers
* DMC trainer: ~1400 deals/s; paired trainer: ~500 deals/s + ~900 branches/s
* batched search data (W=16, tail 6, small clone): ~210 searched decisions/s
* late-game solver: median 0.17 ms at 6 tricks left, 1.85 ms at 8, 6.5 ms at 9
