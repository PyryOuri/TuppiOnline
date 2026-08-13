# Model-performance methodology

Tuppi policy evaluation uses a hierarchy because no single inexpensive metric
captures both local card-play quality and the continuous rising-score objective.
The final strength question is always: **which policy wins more naturally
completed matches to at least 52?** Deal outcomes are earlier, cheaper evidence,
not a replacement definition of strength.

## Evaluation hierarchy

### 1. Behaviour and correctness diagnostics

Action agreement, legality, determinism, latency, solver agreement, and targeted
scenario tests answer whether a candidate behaves as intended. They do not show
that it is stronger. In particular, agreement with a reference policy measures
imitation rather than match performance.

### 2. Paired deal-level development screen

`src/tuppi_eval/` runs the same base deal through the canonical eight seat/card
transformations. All metrics are reduced to one value per complete eight-game
block before inference. The report contains three complementary endpoints:

| Endpoint | Block value | What it detects |
| --- | --- | --- |
| Official deal utility | mean signed Tuppi deal points | margins and asymmetric RAMI penalties |
| Deal-win advantage | mean `+1` for Team A win, `-1` for Team B win | how often the policy wins a deal, independent of margin |
| Match-transition utility | mean bounded value of the authoritative post-deal score | resets, accumulated rise, and terminal wins at `>= 52` |

For deal-win advantage, the reported Team A probability is
`(1 + mean advantage) / 2`. For match-transition utility, terminal wins/losses
are `+1/-1`; nonterminal values are the signed rising-score lead divided by 52.
A reset is therefore zero at 0-0, and a win at 52 and an overshoot to 56 both
have value `+1`. This utility is a score-state ordering, **not exact nonterminal
match equity**.

Each endpoint gets the same paired outputs: block count, mean, confidence
intervals, block win/tie/loss counts, and paired sign tests. The eight
transformations are never counted as independent observations.

These screens are useful for rejecting clear regressions and choosing which
candidates justify expensive match evaluation. They are explicitly emitted as
`role = development_screening_only` and `promotion_eligible = false`. There is
no weighted composite: disagreement between endpoints is information about the
candidate and must remain visible.

### 3. Authoritative complete-match strength evaluation

`src/tuppi_match/` is the strength instrument. Every independent stream produces
two complementary legs with candidate and opponent partnerships swapped. Both
legs use the same deterministic deal stream, dealer, and starting score and run
until a partnership naturally reaches at least 52.

For leg outcome `Y = +1` when the even partnership wins:

```text
D_match = (Y_even_leg - Y_odd_leg) / 2
```

The complete pair, not a leg, deal, trick, or decision, is the independent
unit. The primary result is candidate match-win probability
`(1 + mean(D_match)) / 2`, with paired uncertainty and pair win/tie/loss counts.
Total accumulated deal points are not a separate strength endpoint: the rising
score resets, and the rules terminate the match at 52 or more.

## Candidate-selection rule

Use fresh deterministic development banks for screening. Predeclare the
candidate and comparison before inspecting its result. A candidate may advance
to complete matches when the deal-level evidence is practically promising and
does not reveal a material contract, score-state, legality, latency, or privacy
regression. Numerical improvement on a screen is not itself promotion evidence.

Accept a strength claim only from a fresh, fixed complete-match comparison whose
paired interval and effect size support the claim under the applicable frozen
protocol. Censored or failed pairs are excluded and reported, never converted to
draws. The sealed promotion bank remains governed separately and is not opened
by either evaluator.

## Machine-readable fields

Deal-mode `evaluation_result.json` summary schema `tuppi.eval.summary.v2` adds:

```text
supporting_inference.deal_win_advantage
supporting_inference.match_transition_utility
supporting_inference.independent_unit
supporting_inference.role
supporting_inference.promotion_eligible
```

Match mode marks this block unavailable so the legacy fixed-sequence evaluator
cannot be mistaken for the authoritative complete-match protocol.

## Reproduction

Existing evaluation manifests need no new command-line flags. Re-run a deal-mode
manifest with the normal evaluator command; the additional paired fields are
written automatically. Run the definitive strength protocol with the commands
documented in [the complete-match protocol](../match/complete_match_protocol.md).

