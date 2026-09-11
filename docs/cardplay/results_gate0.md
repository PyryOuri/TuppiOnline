# Gate zero: serial, the gates did not overlap; parallel, they overlap with room

**Status: COMPLETE. Outcome: ADMISSIBLE_IN_PARALLEL at W=64 and W=128.**

Run 2026-09-11 with `work/cardplay/gate0_latency.py`, 12 cold deals per
configuration, single process, artifacts under
`/Users/pyryouri/Developer/tuppi_gate0_latency_20260911/`.

This is an **instrument gate, not science**. It has no pre-registration and no
estimator; it answers only whether a configuration can be run inside the
decision bound. It says nothing about strength.

## 1. What was measured, and why this shape

The admission margin the architecture review asked for is "a measured cold
maximum under 8 s against a 10 s failure bound". Every figure quoted before this
run — 56.7 s, 7.87 s, all of them — was **one warm decision on one fixed deal**,
which is a different quantity. This measures:

* **one decision**, not a throughput rate. `pimc.decide` is serial over
  candidates and over worlds, and `evaluation.py`'s multiprocessing is across
  games, so nothing in the package shortens a single decision. A deployed
  selector faces the bound on one opening lead while a person waits.
* **cold** — a fresh deal, gate, specification and agent per measurement, so
  nothing is amortised the way a repeated call on one fixed observation is.
* **a maximum**, because a failure bound is about the worst decision, not the
  average one.

## 2. Result

Cold maximum over 12 deals, seconds:

| W | `partner_aware_v1` | `partner_aware_lead_v2` | under 8 s margin |
| ---: | ---: | ---: | --- |
| 16 | 2.02 | 2.98 | both |
| 32 | **3.99** | **5.95** | both |
| 64 | 8.08 | 11.92 | **neither** |

**W=64 is not admissible under either continuation.** The frozen reference misses
the margin by 0.08 s while staying under the 10 s failure bound; the incumbent
continuation is over both.

## 3. The two gates do not overlap

C3 measured the deal-points effect clearing δ=0.001 only at W=64 — its 95 %
interval lower bound is +0.001226 there and +0.000954 at W=32, which does not
clear:

| W | C3 `G_deploy` | ci95 low | clears δ | admissible |
| ---: | ---: | ---: | --- | --- |
| 16 | +0.000891 | +0.000500 | no | yes |
| 32 | +0.001255 | +0.000954 | no | yes |
| 64 | +0.001470 | +0.001226 | **yes** | **no** |

So the largest budget that clears the latency gate is one step below the
smallest budget that clears the science gate. W=32 is close — its interval
lower bound misses δ by 0.000046 — but the pre-registered rule is the rule, and
a result that needs the bar moved to pass is not a result.

**Serially, this was the binding constraint on the branch, and it was
engineering rather than science.** Nothing here says the opening-lead selector
plays badly; it said the configuration where the effect was measured could not
be run inside the bound. Section 5 removes that constraint.

## 4. A 3x cost that was self-inflicted

The first run measured the incumbent continuation at 3x the frozen reference
(5.72 / 11.61 / 22.99 s). Profiling both showed its *rollouts* cost about the
same — 2.82 s against 2.53 s — and that the gap was **agent construction**:
`factory._construct_improved_if_declared` calls
`improved_specifications_by_profile_key()` once per construction, and that
function content-addresses every improved specification from scratch each time.
A PIMC decision constructs four agents per rollout, so at W=8 it was 416 calls
and 2.74 s of a 5.66 s decision — more than the rollouts.

That cost arrived with the delegation hook in `6651ec2` and went unnoticed
because nothing constructed improved agents in a tight loop until the rollout
did. The resolution is now memoised: the declarations are a module-level
constant, nothing mutates them, and a fresh dict is returned per call so no
caller can reach the cache. Both improved agent identities are unchanged and
pinned in `tests/agents/test_improved_registry.py`.

Effect: the incumbent fell from 3.0x the reference to 1.5x, and roughly halved at
every budget. It did not change the verdict, because the reference was never the
thing holding W=64 back.

## 5. Parallelism resolves it

`pimc.decide(workers=N)` evaluates a decision's candidates concurrently. Cold
maximum over 12 deals at 8 workers on a 14-core host:

| W | `partner_aware_v1` | `partner_aware_lead_v2` |
| ---: | ---: | ---: |
| 64 | **1.62** (from 8.08) | **2.24** (from 11.92) |
| 128 | **3.08** | **4.29** |

**W=64 clears the 8 s margin by 3.6-4.9x under either continuation, and W=128
clears it too.** The largest admissible budget moved from 32 to at least 128, so
it now sits above rather than below the smallest budget where C3 clears δ. The
branch is open on latency.

Two consequences beyond this gate. The incumbent continuation is affordable at
the budget the science needs, so closing the search/play mismatch no longer
costs anything measurable. And **C2 is now cheap**: extending the world-count
curve to W=128 to read the plateau costs 3.08 s per decision rather than tens of
seconds.

A note on precision. These are maxima, which is the conservative statistic, and
the host's load average reached 18 during the run — the measurement's own 8
workers account for most of that on 14 cores, but not obviously all of it. The
figures are internally consistent (W=128 is almost exactly twice W=64; the
incumbent is about 1.38x the reference throughout), and the conclusion has a
3.6x margin, so it is robust to contention of this size. It should not be quoted
to two decimal places as a property of other hosts.

### What parallelism is *not*

`docs/search/phase5d_c_optimization.md` rejected "asynchronous shared-tree
parallelism", and that is still rejected: it would change results. Candidate
parallelism cannot. The candidates are independent, each worker rebuilds the
same world set deterministically from the same seeds, and the summaries are
reassembled by `action_order_index` before the tie-break sees them, so
completion order cannot reach the selection.
`tests/search/test_pimc_parallel.py` requires the decision, the
`configuration_id` and the `agent_id` to be identical at every worker count.

Worker count is a runtime argument and part of no identity — where `config.py`'s
docstring already put it, beside output paths and whether diagnostics were
requested. Workers rebuild the world set rather than receive it: a
`SampledWorldSet` holds full `DealState` objects and each revalidates itself on
construction, so shipping one would pay the engine's whole-state check per world
per worker, reintroducing the cost the back-port removed. Rebuilding is 39 ms at
W=64.

Do not raise it inside an already-parallel arena. `tuppi_search.evaluation`
parallelises across matches; nesting the two oversubscribes the machine.

## 6. What this does not establish

* Nothing about strength. No deal was played by a scoped selector against
  anything.
* Nothing about throughput. A parallel decision uses 8 cores, so a campaign that
  also parallelises across matches cannot have both; the arena's worker count and
  a decision's worker count draw on the same machine.
* Nothing about hosts other than this one. The measurement is single-host,
  single-process, and the machine was quiet (load average 3.6); an earlier
  attempt during a load spike of 34 produced figures that were discarded.
