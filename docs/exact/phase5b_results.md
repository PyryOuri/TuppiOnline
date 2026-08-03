# Phase 5B results: the match-aware rules, diagnosed

Every number here comes from **development banks** created for Phase 5B with root
seeds that no earlier phase used. None is a promotion claim, none designates a
champion, and the promotion-sealed bank has still never been opened.

Source artifacts: `reports/phase5b/match_rule_diagnosis.json`,
`reports/phase5b/frozen_baseline.json`.

## What Phase 5A left open

Phase 5A measured `match_aware_v1` against the identical policy with all four
`match.*` rules switched off and found `p_win = 0.498`, CI `[0.481, 0.515]`,
sign-flip `p = 1.000`, with 237 of 256 pairs tied. It concluded that the rules
provide no measurable benefit, that the trend where they fire is unfavourable, and
it deferred two questions:

1. which of the rules is responsible;
2. whether the protect threshold at distance 4 is simply mis-set.

It also fixed the ground rules: a changed profile is a new agent, and it belongs on
fresh fixtures. Phase 5B honours both - eight new agent identities, none in the
Phase 4 registry, on two new banks.

## The answer, first

**The two play rules cannot help, and do not. The null lives in the two showing
rules. The protect threshold is not "mis-set" in any useful sense, because the
reachable score lattice leaves the parameter only three distinct behaviours - and
the more the rule fires, the worse the point estimate gets.**

| Rule | Phase | Status | Verdict |
| --- | --- | --- | --- |
| `match.play.coast_when_margin_worthless.v1` | play | **active** | Exactly match-neutral. Cannot help or hurt. |
| `match.play.secure_decisive_trick.v1` | play | **redundant** | Condition holds often; never changes a decision. |
| `match.show.protect_terminal_lead.v1` | show | active | The only negative point estimate. Monotone dose-response. |
| `match.show.reset_opponent_rise.v1` | show | active | Fires most often; indistinguishable from neutral. |

## Instrument 1: a proof, not a measurement

Fix the contract and the declarer. The deal outcome is a function of the trick split
alone, and the rising-score transition is a function of the deal outcome and the
starting score alone. So match utility is a function of the trick split alone, and
`monotonicity_certificate()` verifies exhaustively - every contract, every legal
declarer, every reachable score state, both teams, all fourteen splits, **250 cases,
0 failures** - that it is weakly monotone in the same direction as the deal points.

A weakly monotone transform of a zero-sum game leaves the minimax solution an
equilibrium. Therefore:

> Every trick-optimal card is also match-optimal, at every score state, under
> perfect information.

Two of the four rules change **cards**. Under perfect information neither can buy
anything, whatever the score. That is a structural verdict, established before a
single match is played, and it is why the diagnosis does not need a large sample to
settle half the question.

**Scope.** Perfect information only. Under imperfect information a team facing a
step-shaped utility - any win resets the opponents' rise, whatever the margin - may
rationally prefer maximizing the *probability* of a win over expected points. That
is a real effect. What Phase 4's rules do not do is compute it.

## Instrument 2: the exact activation census

216 deals (24 per score state across nine states), all four seats played by the
frozen `match_aware_v1`, every position re-decided with one rule switched off.
**590 showing decisions and 11 232 trick-play decisions.**

| Rule | Precondition held | Decisions changed | Status |
| --- | ---: | ---: | --- |
| `coast_when_margin_worthless` | 774 | 159 | active |
| `secure_decisive_trick` | **510** | **0** | **redundant** |
| `protect_terminal_lead` | - | 35 | active |
| `reset_opponent_rise` | - | 24 | active |

The precondition column is what makes `secure_decisive_trick` interpretable. Its
documented condition - RAMI, own partnership on exactly six tricks, a partner
holding the trick, a later seat able to beat it - held **510 times**, and the rule
changed the chosen card **zero times**. It is not unreachable; it is *redundant*.
The preference it expresses is already what `partner_aware_v1` chooses, so the rule
adds a name and no behaviour.

That distinction cannot be drawn from a decision-change count alone, and it changes
the remedy: an inert rule needs a wider condition, a redundant rule needs deleting.

**Caveat.** Divergence is counted along the frozen agent's own trajectory. It
measures how often a rule changes a decision the base agent actually faces, not
what happens if a variant plays every decision of a match. Instrument 5 answers
that.

## Instrument 3: exact perfect-information verdicts

Where a play rule changed the card and the position was inside the solver's exact
range (5 tricks), the position was solved on the **real** hands and both candidate
cards compared.

`coast_when_margin_worthless`: **143 verdicts, 143 neutral, 0 helps, 0 hurts.**

That is the rule's own precondition coming true. It fires only when the deal win is
already secured and further margin cannot move the match, so under perfect
information every legal card reaches the same match state. In **37 of the 143** it
spent deal points - which is exactly what it is for, and exactly why deal points are
the wrong currency for judging it. Both currencies are recorded so the disagreement
is visible.

16 further divergences were outside the exact budget and are reported as such rather
than filled in.

## Instrument 4: uniform-measure verdicts

The same comparison, but over 16 exactly-uniform samples of the feasible hidden
hands per decision, each solved exactly, with the verdict counting worlds in which
one card reaches a strictly better match state.

`coast_when_margin_worthless`: **140 decisions, all neutral** (3 had no solvable
sampled world).

So coasting is match-neutral under imperfect information too - not merely under the
perfect-information idealization. The precondition is a *hard* public fact, so every
feasible world agrees the deal is decided.

**Measure caveat.** Uniform-over-feasible is a neutral reference measure, **not** a
posterior over opponent hands: a posterior would condition on how the opponents
chose their observed actions, and this package models no policy. The record carries
`is_posterior_over_opponent_hands: false` as a schema-enforced field.

## Instrument 5: the fresh-design complete-match ablation

128 complementary pairs per comparison on the new `phase5b_rule_ablation_v1` bank,
safety cap 704: **2 048 complete matches, about 62 000 deals, 0 censored legs, 0
failed legs.** Mean leg length 30.5 deals, median 24, maximum 142.

The candidate is always the frozen `match_aware_v1` and the opponent is the variant,
so **`p_win` above 0.5 means the changed rule helps.**

| Variant (rule changed) | `p_win` | 95 % CI | sign-flip p | W / T / L |
| --- | ---: | --- | ---: | --- |
| `coast_when_margin_worthless` off | 0.500 | [0.500, 0.500] | 1.000 | 0 / **128** / 0 |
| `secure_decisive_trick` off | 0.500 | [0.500, 0.500] | 1.000 | 0 / **128** / 0 |
| `protect_terminal_lead` off | **0.488** | [0.475, 0.501] | 0.251 | 0 / 125 / 3 |
| `reset_opponent_rise` off | 0.508 | [0.484, 0.532] | 0.762 | 6 / 118 / 4 |
| `match_protect_distance` = 0 | 0.488 | [0.475, 0.501] | 0.251 | 0 / 125 / 3 |
| `match_protect_distance` = 2 | 0.488 | [0.475, 0.501] | 0.251 | 0 / 125 / 3 |
| `match_protect_distance` = 6 | 0.500 | [0.500, 0.500] | 1.000 | 0 / **128** / 0 |
| `match_protect_distance` = 8 | 0.512 | [0.499, 0.525] | 0.247 | **3** / 125 / 0 |

Read the two play rules first. Turning either off changes **nothing**: all 128 pairs
tie, across 512 matches and roughly 15 000 deals. That is not a small effect
estimated imprecisely - it is a deterministic statement about these fixtures, and it
is exactly what instruments 1 to 4 predicted. Coasting changes cards but never the
match state; the decisive-trick rule never changes a card at all.

## The protect threshold: the question has fewer answers than it looks

Phase 5A asked whether distance 4 is simply mis-set. Answering needs one exact
observation about the ruleset.

Every deal-point award under `project_target_v1` is a multiple of four, and an
unreset score is a sum of such awards, so **the only rising scores a partnership can
hold mid-match are the multiples of four from 4 to 48.**
`reachable_positive_scores()` derives this from the scoring functions rather than
assuming it. `match.show.protect_terminal_lead.v1` fires when `52 - own_score <=
match_protect_distance`, so the parameter's whole range collapses onto that lattice:

| Distance | Scores where the rule can fire | Equivalent to |
| ---: | --- | --- |
| 0, 2 | none | **rule off** |
| 4, 6 | 48 | each other (4 is the Phase 4 setting) |
| 8 | 44, 48 | - |
| 12 | 40, 44, 48 | - |

Both predictions of that lattice are confirmed independently and exactly:

- **distances 0 and 2 reproduce "rule off" precisely** - same 137 contract flips in
  the showing census, same 0/125/3 pair outcomes, same CI, same p-value;
- **distance 6 reproduces distance 4 precisely** - 0 contract flips, all 128 pairs
  tied.

So the protect distance has three reachable behaviours in the range Phase 4 could
have chosen: off, fire-at-48, and fire-at-44-and-48. And the point estimates run
monotonically the wrong way:

```text
rule off          p_win 0.488  (off wins 3 pairs, loses 0)
distance 4 or 6   baseline
distance 8        p_win 0.512  (base wins 3 pairs, loses 0)
```

Two independent contrasts, same direction: **the more the protect rule fires, the
worse it does.** There is no nearby better setting to find, because there is no
nearby setting at all.

## The showing rules are the only ones that can matter

A dedicated showing census - 9 037 showing decisions over 3 456 deals, replaying only
the showing phase - separates *what* the showing rules change:

| Variant | Eligible decisions | Contract flips | Card-only changes |
| --- | ---: | ---: | ---: |
| `protect_terminal_lead` off | 928 | 137 | **0** |
| `reset_opponent_rise` off | 2 035 | 329 | **0** |
| `match_protect_distance` = 0 | 928 | 137 | 0 |
| `match_protect_distance` = 2 | 928 | 137 | 0 |
| `match_protect_distance` = 6 | 928 | **0** | 0 |
| `match_protect_distance` = 8 | 928 | 142 | 0 |

Card-only changes are zero everywhere, which matters: the shown card is public but
changes no contract, no leader, and no trick, so **only a contract flip can move a
match.** The showing rules do nothing else.

They also have room to bite. The mean distance from the RAMI score to its threshold
is `-2.45`, and **2 634 of 9 037** decisions sit within 2 points of the threshold -
so a `+3` or `-2` shift lands in a dense region. "The rule never fires" is not the
explanation.

`reset_opponent_rise` fires most (329 flips) and is the closest to genuinely
neutral: `p_win = 0.508`, CI `[0.484, 0.532]`, `p = 0.762`, with wins and losses
split 6-4. `protect_terminal_lead` fires less and is the only rule with a negative
estimate.

## What this does and does not establish

**Established exactly, not statistically:**

- match utility is weakly monotone in the trick split (250/250 cases);
- no card-changing rule can help under perfect information;
- coasting is match-neutral in 143/143 exactly-solved real positions and 140/140
  uniform-measure ones;
- `secure_decisive_trick` changes zero of 11 232 decisions despite its condition
  holding 510 times;
- the protect distance has only three reachable behaviours, and distances 0/2 and
  4/6 are pairwise identical.

**Not established:**

- **that either showing rule is harmful.** Every interval contains 0.5. With 128
  pairs the CI half-width is about 0.013 to 0.024, so only effects larger than a
  couple of percentage points are resolvable. Phase 5A estimated that a one-point
  edge needs 1 500 to 3 000 pairs; this design has roughly a tenth of that.
- **that the 3-0 and 3-0 pair splits mean anything on their own.** Sign-flip
  p-values of 0.25 are what three-of-three looks like by chance.
- **anything about a stronger opponent.** All comparisons pit `match_aware_v1`
  against a near-clone of itself, so 118 to 128 of 128 pairs tie and the design has
  little to measure. The rules might matter against a policy that plays differently.

## Recommendation, stated as a recommendation

On this evidence:

1. **Delete `match.play.secure_decisive_trick.v1`.** It is redundant, not
   mis-tuned: its condition holds and its preference never differs from what the
   policy already chose.
2. **Keep `match.play.coast_when_margin_worthless.v1` only if a reason other than
   strength justifies it.** It is provably and measurably match-neutral, so it
   cannot help; it is also cheap and correct, and it makes a true property of the
   ruleset explicit in the policy.
3. **Do not retune `match_protect_distance`.** The lattice leaves nothing to tune,
   and both available contrasts point the wrong way.
4. **Do not conclude the showing rules are harmful.** Re-measure at 1 500+ pairs
   against a genuinely different opponent before deciding, and treat any such
   change as a new agent identity on new fixtures.

None of these is licensed to be applied silently. Each would produce a new agent,
and a new agent belongs to a later experiment on fixtures it has not seen.

## Reproduction

```bash
source "$HOME/.venvs/tuppi-research/bin/activate"
cd "$HOME/Developer/TuppiProject"

python -m tuppi_exact.runner integrity --verify reports/phase5b/frozen_baseline.json
python -m tuppi_exact.runner variants
python -m tuppi_exact.runner monotonicity

# Exact instruments only, about 2 minutes.
python -m tuppi_exact.runner diagnose \
  --census-deals 24 --samples-per-decision 16 --show-census-deals 384 \
  --output "$HOME/TuppiRuns/phase5b/diagnosis_full.json"

# The fresh-design match ablation: about 96 minutes at six workers.
python -m tuppi_exact.runner ablate \
  --pairs 128 --safety-cap 704 --workers 6 \
  --output "$HOME/TuppiRuns/phase5b/rule_ablation_128.json"
```

Write experiment output outside the repository and outside any cloud-synced
directory.

## Environment: the relocation, measured

Phase 5A recorded a stalled CLI subprocess test under an iCloud-synced working
tree. The repository now lives at `~/Developer/TuppiProject` with its virtual
environment at `~/.venvs/tuppi-research`, run output at `~/TuppiRuns/phase5b`, and
cache at `~/Library/Caches/TuppiResearch`.

Measured after relocation, Python 3.14.3, `/usr/bin/time -p`:

| Measurement | Before Phase 5B | After Phase 5B |
| --- | --- | --- |
| Import of `tuppi_engine`, `tuppi_eval`, `tuppi_agents`, `tuppi_match` (+ `tuppi_exact` after) | 0.10 s warm, 0.21 s cold | 0.11 s warm, 0.81 s cold |
| `test_documented_module_command_runs_without_gui_or_network` | **0.22 s** | **0.22 s** |
| Collection of the whole suite | 0.20 s (901 tests, 0.61 s wall) | 0.26 s (1 049 tests, 0.69 s wall) |
| Full suite | 901 passed in 443.92 s | 1 049 passed in 480.28 s |

The previously problematic subprocess test needed no timeout change: 0.22 s against
a 20 s limit is roughly a ninety-fold margin. The timeout was **not** raised, and
the stall did not recur in any run.

Phase 5B adds 148 tests for 36 s, so the exact layer's own suite is about 7 % of
total runtime - which is what keeps the brute-force solver cross-check and the
schema validation affordable on every commit.

`tuppi_exact.integrity.working_tree_location` now reports whether a tree is
cloud-synced, so the hazard is visible rather than remembered.

Verified once at the start of Phase 5B and unchanged since: `HEAD` is `7186032`, the
worktree is clean, the two Archive artifacts still hash to their manifest values,
and the only Git remote was an auto-created local path to the old
`~/Documents/TuppiProject` clone. That remote was renamed to
`documents-readonly-fallback` with its push URL disabled and the branch upstream
unset, so the read-only fallback stays reachable for `fetch` but cannot receive a
push. No genuine external remote existed to preserve.

## Deferred to the next phase

1. The sealed bank stays closed. Nothing here is promotion evidence.
2. Build the belief layer on top of `HardConstraintModel`, and justify it against
   uniform-over-feasible rather than against nothing.
3. Add PIMC or ISMCTS using the five exact capabilities as its determinizer and
   evaluator, with `partner_aware_v1` as the development reference opponent.
4. Re-estimate match length and `sd(D)` for the search agent before sizing its
   evaluation.
5. Re-measure the two showing rules at 1 500+ pairs against a genuinely different
   opponent, if they are still of interest once a search agent exists.
6. Only then open the sealed bank, once, with a recorded reason.
