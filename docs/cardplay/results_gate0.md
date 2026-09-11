# Gate zero: the opening-lead selector fits the bound, but not at the budget the science needs

**Status: COMPLETE. Outcome: GATES_DO_NOT_OVERLAP.**

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

**This is the binding constraint on the branch, and it is engineering, not
science.** Nothing here says the opening-lead selector plays badly; it says the
configuration where the effect was measured cannot currently be run inside the
bound.

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

## 5. What would change the answer

**Within-decision parallelism.** The 13 candidates at an opening lead are
independent and each is deterministic given the shared world set, so evaluating
them concurrently and aggregating in canonical order would give a byte-identical
decision. Eight workers would put W=64 near 1-2 s under either continuation and
open the branch outright. It does not exist: `docs/search/phase5d_c_optimization.md`
records "simulations remain serial within one decision; parallelism remains at
the independent match/pair level", so building it is a deliberate change to a
recorded design property and an owner decision, not a detail.

The alternatives are worse. Running at W=32 accepts a budget where C3's own
instrument does not clear δ. Relaxing the 8 s margin is moving the bar after
seeing the number. Extending the world-count curve past 64 — the outstanding C2
item — raises the cost it would have to fit, not lowers it.

## 6. What this does not establish

* Nothing about strength. No deal was played by a scoped selector against
  anything.
* Nothing about a parallel configuration's real latency, which is projected from
  candidate independence and has not been measured.
* Nothing about hosts other than this one. The measurement is single-host,
  single-process, and the machine was quiet (load average 3.6); an earlier
  attempt during a load spike of 34 produced figures that were discarded.
