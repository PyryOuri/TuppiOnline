# Status and results log

Newest first. Every equity figure is per base deal from `tuppi_ai.evaluate`
(4 rotations x 2 team assignments against `partner_aware_lead_v2` in the
authoritative TuppiProject engine, dealer 0, score 0-0 unless stated), with a
normal-approximation 95% interval over base deals. For scale: the incumbent's
own margin over its predecessor `partner_aware_v1` is +0.0054 [+0.0043, +0.0066]
on this instrument (TuppiProject's T4/T5 report +0.0057..+0.0064).

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
