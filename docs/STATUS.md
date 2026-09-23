# Status and results log

Newest first. Every equity figure is per base deal from `tuppi_ai.evaluate`
(4 rotations x 2 team assignments against `partner_aware_lead_v2` in the
authoritative TuppiProject engine, dealer 0, score 0-0 unless stated), with a
normal-approximation 95% interval over base deals. For scale: the incumbent's
own margin over its predecessor `partner_aware_v1` is +0.0054 [+0.0043, +0.0066]
on this instrument (TuppiProject's T4/T5 report +0.0057..+0.0064).

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
