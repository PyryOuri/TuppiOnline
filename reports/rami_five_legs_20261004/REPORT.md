# Five supported cards across three suits: RAMI at 0-0

Research completed 2026-10-04. **Useful strength signal, too broad as an automatic
RAMI trigger.** The current W1024 search bot bids RAMI on
65.2% of qualifying hands in the stratified
confirmation. Forcing RAMI whenever the condition qualifies changes equity by
-0.00273 [-0.00342, -0.00205] estimated match equity per deal against the strongest available
fast policy (VRPO3), with identical card play. The interval excludes zero.

## The owner's confirmed idea

A card has enough *legs* when it has enough other cards of its suit to support
its rank: A needs 0, K 1, Q 2, J 3, 10 4, and so on. Higher cards count as legs
too; support can be shared. For suit length L and rank r, qualify the card when
**L-1 >= 14-r**. Count at least five qualifying cards, with qualifying cards
in at least three different suits. This is a count of prospective winners,
not guaranteed tricks. AK counts 2, KQx 2, Qxx 1, AKQJ 4. Qualifying cards in
three suits is stronger than merely holding cards in three suits.

The owner confirmed “at least five” and this interpretation. The primary test
is a **sufficient trigger**: force RAMI on qualifying hands, otherwise retain
the bot's decisions. A separate test examines RAMI iff the condition holds;
that complete strategy was not assumed to be the owner's intended rule.

## Bots and evidence

VRPO3 (`models/vrpo3_final.pt`) is the current strongest documented standalone
policy and the policy anchor of the current best search bot. It supplies the
large, fast outcome experiment. This is not the older heuristic bot.

The strongest bid confirmation uses `best_agents(worlds=1024)`: VRPO1 on both
rollout teams, VRPO3 anchor, .003 card margin, .03 bid margin, showing sampler
fix, six-trick exact search tail and adaptive bidding. A W128 screen precedes
it. Both use current frozen source/model/native files in SOURCE_HASHES.json;
all hashes matched after the study. Source revision was
`d518f7329c34e4a9070df806b3a5ef937cb04387` with unrelated existing changes.

All runs use project_target_v3 (blind locked bids and sooli), score 0-0.
The policy-only runs use the repository's normal policy sooli fallback, which
declines offers. The search valuations include its sooli model. Search agents
are observation-seeded and their history-sensitive sooli options are reset
to fresh-deal defaults for each isolated bid. No source, models, training,
running servers or live settings were changed.

## Agreement and the five-card boundary

8,192 independent random deals provide 32,768 blind shadow bids, all four
positions. 7,594 hands (23.2%) qualify.
VRPO3 chooses RAMI on 66.2% of these
hands. Overall agreement of the complete yes/no rule with VRPO3 is
83.7%.

| Supported cards, at least 3 qualifying suits | Fast-policy hands | VRPO3 bids RAMI | W1024 hands | W1024 bids RAMI | RAMI made in paired fast play |
|---|---:|---:|---:|---:|---:|
| 5 | 4,355 | 54.5% | 293 | 52.6% | 60.9% |
| 6 | 2,277 | 77.7% | 150 | 76.0% | 68.9% |
| 7 | 775 | 91.2% | 50 | 94.0% | 81.2% |
| 8+ | 187 | 95.2% | 19 | 100.0% | 82.9% |

Exactly five is the weak part of the rule. Six is more convincing and seven
is a strong indicator, but these are exploratory descriptions, not validated
replacement thresholds. The last rows have fewer search observations.

Position also matters. Among qualifying hands:

| Bid position | VRPO3 bids RAMI | W1024 bids RAMI |
|---|---:|---:|
| Forehand / 1st | 57.1% | 53.1% |
| 2nd | 56.3% | 54.7% |
| 3rd | 67.8% | 71.1% |
| Dealer / 4th | 83.3% | 82.0% |

W1024 uses 1,024 shadow bids: 128 qualified and 128 unqualified per position.
Thus 512 qualified hands underpin the conditional recommendation rate
(65.2%; approximate deal-clustered
95% interval 61.0%–69.3%).
The stratified sample is not half-qualified in the population. Standardizing
to the large random sample gives overall agreement
84.5%, rather than treating its raw balanced
average as a population rate. The W128 screen had 256 bids.

## What following the rule costs

2,048 independent base deals × four hand rotations × both partnership
assignments × three arms = **49,152 played games**. In every arm, VRPO3 plays
all cards; only the tested partnership's contract decisions differ. Shown
cards are VRPO3's favourite legal cards within the chosen contract. Pairing
uses identical hands/dealer/score. Intervals use independent base-deal means
over the eight duplicate legs, not 49,152 independent observations.
Proportion intervals use deal-clustered influence estimates with a conservative
Wilson safeguard, so small all-success subgroups do not imply certainty.

| Strategy versus VRPO3 bidding | Estimated match-equity difference per deal, 95% CI |
|---|---:|
| Force RAMI when condition holds; otherwise use VRPO3 | -0.00273 [-0.00342, -0.00205] |
| RAMI only when condition holds; otherwise NOLO | -0.00427 [-0.00514, -0.00340] |

The primary loss is about **0.273 percentage points of
estimated match-win probability after one deal**. This is an absolute change
in the repository's continuation-equity model. It is not a measured
full-match win-rate change, percentage of mathematical optimality, or a
claim that the same loss holds against human opponents. The equity table
comes from the incumbent continuation model. Raw points and deal wins are
also preserved in RESULTS.json.

The W1024 bot passes on 178 of the 512
qualifying bids. On those overrides, forcing RAMI with its best searched
RAMI card changes its own model value by
-0.01414 on average. Leaving
its action unchanged when it already bids RAMI gives a model difference of
-0.00492 per
qualifying bid in this balanced-position sample. These are **search-model
estimates per bid**, separate from the played per-deal result above.

## RAMI versus passing on the same qualifying hand

Every qualifying shadow hand was played twice: RAMI and NOLO, with the other
bids and card play following VRPO3. Earlier seats were forced to NOLO using
their preferred NOLO cards, so these are shadow-context comparisons, not
the naturally occurring distribution after earlier bot passes. Passing may
let someone else declare RAMI. This adds **15,188 paired-branch games**.

| Qualifying group | Hands | RAMI made | Team wins after pass | RAMI minus pass equity, 95% CI |
|---|---:|---:|---:|---:|
| All qualifying | 7,594 | 65.9% | 42.0% | +0.00957 [+0.00787, +0.01127] |
| VRPO3 would bid RAMI | 5,030 | 73.0% | 36.4% | +0.02511 [+0.02313, +0.02709] |
| VRPO3 would pass | 2,564 | 52.0% | 53.0% | -0.02091 [-0.02383, -0.01798] |
| Exactly five supported cards | 4,355 | 60.9% | 46.1% | -0.00122 [-0.00341, +0.00097] |

On qualifying hands that VRPO3 rejects, forcing RAMI averages
-3.93 signed points,
versus +1.73 after passing.
This is the source of the automatic trigger's cost: the bot separates the
good qualifying hands from the weaker ones. The aggregate condition can
favour RAMI while still being an inferior automatic decision rule.

## Concrete counterexample

These examples were selected for a clear model disagreement, not to estimate
how common such hands are. Both the fast policy and W1024 choose NOLO.

- Position: Forehand / 1st. Hand: ♥ K 5; ♦ K Q 10 6 4 3 2; ♣ J 5; ♠ K 5.
- Supported cards by suit (♥ ♦ ♣ ♠): [1, 3, 0, 1]; total five across three suits.
- W1024's best RAMI-minus-NOLO searched value: -0.05738 equity.

The count omits which higher ranks are held, missing higher cards, suit
entries and blocking, the rest of the hand's NOLO prospects, partner support,
and position. Cards with legs can become winners without providing five
usable tricks or making seven partnership tricks sufficiently likely.

## Interpretation and limits

Use the condition as a strength screen. At 0-0, exactly five supported cards
across three suits does not justify automatic RAMI; the bot rejects many such
hands. Six or seven increases its confidence, but a fixed count still misses
important hand and position information. This study does not establish a
replacement rule or mathematical optimality.

Actual paired outcomes were played with the strongest fast standalone policy,
not four W1024 search agents. W1024 confirms bidding decisions and records
model values; those values are not independent actual outcome validation.
The .03 bid anchor means the deployed search choice need not maximize its
own raw rollout mean. Adaptive search can value different discarded actions
on different numbers of worlds. Do not equate a rollout-value gap with proof
of a wrong bid or treat the bot as an oracle.

## Reproduction and artifacts

- PROTOCOL.md: original frozen design and explicitly dated follow-up.
- study.py: counting predicate, seeded deals, differential validation,
  bid samples, paired policy play and search confirmation.
- analyse.py and RESULTS.json: complete numeric summaries, cluster intervals,
  subgroup results, example hands and integrity checks.
- policy_bids.json, policy_games.json, policy_branches.json: underlying data.
- search_bids_w128.json, search_bids_w1024.json: decisions and all searched values.
- search_bids_w1024_pilot128.json: preserved initial pilot.
- SOURCE_HASHES.json and validation.json: source/model freeze and engine checks.

Run `study.py validate --n 24`, `bids --n 8192`, `games --n 2048 --chunk 64`,
`branches --chunk 256`, `search --n 256 --worlds 128`, and
`search --n 1024 --worlds 1024` with the existing tuppi-v2 Python, then
`analyse.py`. The fixed seed is `rami-five-legs-20261004-v1`.

Validation compared 24 complete v3 deals with the authoritative engine:
1,349 actions, all legal sets/actors/observation encodings/results matched;
zero native/PyTorch policy-choice disagreements. Duplicate baseline cancels
exactly against itself in both partnership assignments on every base deal.
No live deployment or GUI validation is claimed.

Source references: [best.py](../../TuppiAI/tuppi_ai/best.py),
[policies.py](../../TuppiAI/tuppi_ai/policies.py),
[equity.py](../../TuppiAI/tuppi_ai/equity.py),
[v3 rules](../../TuppiProject-current/docs/rules/project_target_v3.md),
and [policy sooli fallback](../../TuppiProject-current/src/tuppi_agents/sooli.py).
Authoritative current configuration was read from source because older status
prose describes earlier opponent models.
