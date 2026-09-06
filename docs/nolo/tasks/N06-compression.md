# N06 — Try one exact reduction in computation

Status: WAITING_DEPENDENCY; optional. Requires N04 PASS. A negative speed result
does not block N07 using the unoptimized reference. Do not add new heuristics,
drop worlds, introduce approximate probabilities, or relax correctness limits.

## Fixed question and outputs

Question: can exact repeated-subproblem caching reduce engine transitions while
preserving root values and valid continuation plans?

Create `src/tuppi_nolo/cache.py`, `tests/nolo/test_cache.py`, and
`docs/nolo/results/N06.md`. Add a cache-enabled option to the new security code;
the uncached path must remain available as an independent comparison.

Before timing, write the proposed key and why it is sufficient. Start
conservatively: root identity, objective/control model, score, public partial
trick and actor, accumulated team tricks, remaining hand order/canonical cards,
and the complete set of feasible remaining allocations. All private allocations
are inferred from the observation, never read from the real deal. A cache key
may internally describe that inferred set; an **own action key may not identify
one hidden world**. Never use just suit lengths or the union of unknown cards.

Preserve the distinctions needed by the root's information history and baseline
tie rule. Cache values/optimal-action sets rather than transplanting another
history's absolute plan keys. Reconstruct and verify a plan for the current
history. If a coarser key's sufficiency cannot be explained, retain the finer key
and accept a possible negative performance result. No second optimisation is
allowed in this task.

## Comparison set and endpoints

Use A/B/C plus the first 32 deals of seed `nolo-info-dev-v1`, index 0–31,
initial score `(0,0)`, initial dealer 0, forced NOLO, all-v2 play. Examine all
decisions with two or more legal actions and at most three remaining tricks,
not only oracle disagreements. Freeze the position list before comparing paths.

- Correctness PASS: zero differences in exact root values, claim type or root
  action between paths; all exported plans pass N03. Plans may differ only
  among certified equivalent continuations and may not change baseline ties.
- Cost PASS: at least 20% fewer engine transition calls in aggregate on the
  identical positions solved completely by both paths. Report this matched set
  and also every excluded/budget-limited position; do not claim expanded coverage
  from a matched-set timing figure.
- Budget PASS: no false exact answer after a limit, bounded cache size, explicit
  counters for cache hits/entries and actual transition calls. Report wall time
  separately; compare medians of three repeats without conflating them with
  mathematical work counts.
- If correctness passes but savings are below 20%, outcome `NO USEFUL SPEED
  GAIN`; keep the simple uncached default. The 20% target is a prospective
  engineering threshold, not a claim from prior evidence.

Run `tests/nolo/test_cache.py`. A single value or certificate discrepancy is
FAILED_CHECK and rejects the optimisation. Do not weaken equivalence tests to
make it faster. N07 may use only a version that passed correctness.
