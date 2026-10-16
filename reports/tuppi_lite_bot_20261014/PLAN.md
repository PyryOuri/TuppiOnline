# Tuppi Lite: a much cheaper hosted bot, close to the live bot's strength

Pre-registered on 2026-10-14, before any strength measurement in this package.
The owner delegated the targets and margin. The owner approved about 2–4 hours
of local CPU for cost and strength evaluation, with no training. The bot is
primarily meant for server hosting.

## Reference

The **live bot** is TuppiAI `best_agents(worlds=1024)`:

- W1024, with E7 adaptive bids;
- VRPO1 rollouts for both teams;
- VRPO3 anchor, keep 0.003 for play and 0.03 for bids;
- sampler fix and a 6-trick DD tail.

`live128` is the same factory at W128. Its world gap was measured on the
older bot: W1024 − W128 = +0.00107 [+0.00016, +0.00197], on 512 deals, before
the anchor and strong-opponent changes.

## Targets (decided)

| Target | Value | Measured how |
|---|---|---|
| **Cost** | At most 1/8 of the live bot's CPU per bot-seat-deal | `cost_bench.py`, same 8 deals, this Mac, one thread |
| **Latency** | p95 decision at most 0.5 s on this Mac, one thread (proxy for about 1 s on one vCPU) | Same bench |
| **Strength margin δ** | 0.003 equity per deal against the live bot | See the rules below |

Why δ = 0.003:

- It is about 15% of the live bot's measured edge over the incumbent
  (≈ +0.0197).
- It is about 3× the measured W1024-vs-W128 gap.
- It is far below what is noticeable to human players over a session.
- It is also roughly the smallest difference this CPU budget can resolve.

## Arms (cheapest first)

- **L0:** the VRPO3 actor, greedy over legal actions, using the native MLP
  (no PyTorch at decision time). Sooli phases use the native observation-only
  sooli heuristics, `tc_sooli_policy`; the offer uses the 8-world exact
  solver.
- **L2:** L0, plus the live controller (VRPO3-anchored, keep 0.003) at
  W=128 for trick-play decisions with at most 6 tricks left. Rollouts there
  are pure double-dummy, with no network. Everything else is as in L0.
- **L4 (fallback):** `live128`. It meets the cost target only marginally,
  and its strength is anchored by the earlier world-count result.
- **Deferred:** L1 (suit ensemble), L3 (uncertainty-gated search) and L5
  (distillation). Run them only if L0/L2 fail, as a separate version.

## Procedure and decision rules

All evaluations use `tuppi_ai.evaluate` duplicate deals: 4 rotations × 2
seatings, ruleset v3, uniform scores, through the authoritative engine. The
value is candidate minus opponent per base deal, with 95% CI = mean ± 1.96 SE.

1. **Cost bench.** An arm failing the cost or latency target is dropped
   before any strength run.

2. **Screen.** Each surviving arm, cheapest first, plays head-to-head
   against `live128`: 512 base deals, seed `lite-screen-v1|<arm>`.
   - Passes if the point estimate of (arm − live128) > −0.002.
   - Rationale: with the +0.001 world gap, this corresponds to
     (arm − live1024) > −0.003.
   - The first, i.e. cheapest, passing arm is selected; costlier arms are
     not screened.

3. **Primary.** Extend the selected arm's screen to 1,024 base deals: seeds
   512–1023 of the same seed string, pooled with the screen.
   - Passes if the lower 95% bound of (arm − live128) > −0.002 − 0.002.
   - Rationale: the lower bound of (arm − live1024) is approximated as
     −0.003 − the W-gap uncertainty. It is stated loosely because the W-gap
     itself is an older estimate.
   - The point estimate must stay > −0.002.

4. **Confirmation against the live bot.** The selected arm plays
   head-to-head against `live1024`: 512 base deals, seed `lite-confirm-v1`.
   - Passes if the point estimate of (arm − live1024) > −0.003.
   - Its lower bound is reported but not gated; the budget cannot resolve
     ±0.003 at W1024.

5. **Guard.** The selected arm plays the heuristic `partner_aware_lead_v3`,
   2,048 base deals, seed `panel-p1b|heur`. It is paired per base deal with
   the stored live-W128 result on the same deals
   (`TuppiAI/runs/panel/P1b-A__heur__cand.json`; engine unchanged since).
   - Passes if the lower bound of (arm − live128 vs heuristic) > −0.005.
   - The live bot itself pays −0.0022 here for its strong-opponent model, so
     the guard only rules out large losses to weak play.

6. **Report.**
   - Cost ratios and latency.
   - RAMI declaration and sooli rates against the live bot.
   - A match-level translation of the per-deal difference.

If L0 fails the screen, L2 is screened next. If both fail, L4 is the
recommendation pending a new version for L1/L3. **Do not adjust margins,
seeds or deal counts after seeing results.** Report every run, including
failures.

## Scope

- No change to TuppiAI, TuppiProject-current, the server, the app or the
  installed library.
- New code lives only in this directory and imports TuppiAI read-only.
- No training. The CPU used is recorded in the results.
