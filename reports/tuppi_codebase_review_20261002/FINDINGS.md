# Findings and proposed fixes

No production fixes were applied. Four control-flow issues were reproduced by [source_probes.py](tools/source_probes.py), which AST-extracts actual function bodies and supplies dependency stubs. It imports no Tuppi module, Torch, NumPy or native library and executes no game. Exact source hashes and outputs are in [SOURCE_PROBES.json](SOURCE_PROBES.json), with a final repeat in [SOURCE_PROBES_CURRENT.json](SOURCE_PROBES_CURRENT.json) after the factory acquired a RAMI-margin setting. Native effects follow from inspected setter semantics; end-to-end impact still needs runtime checks.

## F01 — Factory configuration depends on earlier calls

**Source:** [best.py](../../TuppiAI/tuppi_ai/best.py), `best_agents`, line 76 in the probe snapshot. **Priority:** high for baseline identity, conditional on multiple configurations sharing one process.

The factory calls `native.set_showing_fix(True)` when requested, but never calls it with False. After constructing a normal fixed-sampler bot, `best_agents(team_rollout=False, showing_fix=False)` leaves the fix on despite the documented pinned-B0 contract. Probe output: setter calls `[True]`, effective flag still True.

**Fix:** make the setting explicit and symmetric at process initialization; reject incompatible controllers in one native-library process. Simply toggling the flag during a second factory call also changes existing agents, so a symmetric setter alone does not solve coexistence. Longer-term, move the option into an environment/search context, or isolate differing comparators by process/library.

**Acceptance:** construct both orders and verify actual sampled-world mode; verify pinned B0 uses its original mode in isolation; incompatible live objects must fail rather than silently change. Frozen historical baselines remain unchanged.

## F02 — Two searched sides can silently inherit one global configuration

**Source:** [evaluate.py](../../TuppiAI/tuppi_ai/evaluate.py), `_init` and `_make_candidate`. **Priority:** high before searched-opponent comparisons.

Worker initialization constructs opponent and candidate in the same native process. The factory sets `sf` and `ddn` only when nonzero and has no main-checkout conflict preflight. A side requesting `sf=0` after one requesting `sf=1` inherits the fixed sampler. Probe output after the two search specs: `[True]`, effective fix True for both.

**Fix already prepared:** `TuppiAI-prior/evaluate.py` parses settings first, rejects incompatible searched-side flags and explicitly initializes compatible flags. Validate and integrate that small patch. Settings with different values cannot coexist merely by changing construction order; extra NOLO tail depth has the same class of issue.

**Acceptance:** both orders of conflicting `sf`/`ddn` fail before model/controller creation; equal settings route correctly; heuristic opponents remain supported; a real two-search smoke test attests the effective settings.

## F03 — Censored matches are treated as draws

**Source:** [match_eval.py](../../TuppiAI/tuppi_ai/match_eval.py), `_leg`, `measure_pair`, `evaluate_matches`. **Priority:** high when any leg reaches its cap.

A nonterminal leg returns `result=0.5, censored=True`. Aggregation includes that number in `p_win` and the normal interval. A zero-action stub at cap demonstrates the exact branch. A capped leg has an unknown eventual result; it is not a tied completed match. Historical comparisons reporting zero censored legs are not affected by this particular trigger.

**Fix already prepared:** `TuppiAI-prior/match_statistics.py` and `match_eval.py` keep unknown outcomes and publish bounds; `research/runner_v3.py` already distinguishes unresolved outcomes. If there are U unknown legs among N, a simple identification interval is known wins/N to (known wins+U)/N, respecting complementary-pair grouping for inference. This bound is distinct from sampling uncertainty.

**Acceptance:** no censoring reproduces completed-leg statistics; one/two unknown legs produce proper bounds; consumers handle null `p_win`/`ci95`; capped results never enter the tie count.

## F04 — Adaptive allocation can exceed its world cap

**Source:** [search.py](../../TuppiAI/tuppi_ai/search.py), `Searcher.adaptive_values`, line 122 in the probe snapshot. **Priority:** medium; normal W1024/batch128 is divisible and avoids this trigger.

The method always requests a full batch and tests `drawn >= worlds` afterward. With cap 200, batch 128 and unresolved equal means, it draws 256 worlds. If batch exceeds capacity, native root pricing can instead fail. Zero/one-size batches also need validation because paired SE uses `ddof=1`.

**Fix:** either restrict supported caps to positive multiples of batch>=2 and validate at the public factory, or use `min(batch, remaining)` with defined handling for a one-world last batch. The newest isolated queue preflight rejects non-multiple caps, but direct constructors/main CLI still require a policy. Preserve the existing divisible-case RNG/output behavior.

**Acceptance:** caps below/equal/above batch, nonmultiples, invalid zero/negative inputs, forced early stop, and exact divisible-case parity.

## R01 — Known v3 sooli-setting persistence remains part of the comparator

**Source:** [search.py](../../TuppiAI/tuppi_ai/search.py), `choose_action`, `_sooli_action`; [TASKS.md](../../TuppiAI/docs/TASKS.md), T5. **Status:** source-confirmed, intentionally retained by the owner in earlier work.

Ordinary rollout sooli settings reset only under `obs.ruleset == 2`. Sooli calls mutate environment settings, so v3 ordinary decisions can inherit them. Some data/profiling tools reset settings per game, while retained controllers preserve their state. Therefore lifecycle and reset policy belong in the comparator identity.

**Proposal:** when reopened, initialize all applicable v2/v3 rollout settings at a clearly defined boundary, then separately rebaseline and evaluate. Do not silently fix this in a historical comparator or assume a reset-per-deal diagnostic reproduces live retained behavior.

## R02 — Worker history affects stochastic-controller evaluation

**Source:** [evaluate.py](../../TuppiAI/tuppi_ai/evaluate.py), `_W`, `measure`, `evaluate`; [search.py](../../TuppiAI/tuppi_ai/search.py), `reseed`; [runner_v3.py](../../TuppiAI/tuppi_ai/research/runner_v3.py).

Main evaluation creates agents once per worker and carries their RNG/environment state across games and tasks. Without observation reseeding, changing worker layout/task assignment can change search samples. Same deck seed is not a full policy-state identity. The research runner supports fresh indexed bundles and retained independent match legs; the newest queue records persistent-worker semantics but does not remove them.

**Proposal:** for confirmation use fresh indexed controllers for duplicate bundles and fresh retained controllers per match leg, or define and attest a deterministic scheduling/RNG design. Preserve old instruments for historical reproduction. Record lifecycle in every result. Test worker-count/order invariance for the selected new design; do not claim existing stochastic self-play identity necessarily yields exact zero/0.5 on every row.

## R03 — Adaptive pruning and final scoring can disagree

**Source:** [search.py](../../TuppiAI/tuppi_ai/search.py), `adaptive_values`, `_keep_blueprint`, and the RAMI-bonus change observed during review.

Main applies anchor keep after E7 allocation, comparing means that can have different sample counts. A new main change also applies RAMI bonuses after adaptive pruning and recomputes argmax over returned means, including dropped actions. Allocation was made on raw Q, while the final decision can use another objective. The final factory's `RAMI_MARGIN=0.0` leaves that bonus inactive by default. This is a supported control-flow risk for changed objectives; no harmful full game was demonstrated here.

**Proposal:** apply deterministic objective offsets inside leadership/elimination/stopping, track per-action counts, and never reselect a dropped action from a stale mean unless it is deliberately repriced. `TuppiAI-prior` supplies integrated keep and soft-prior arms, and rejects several incompatible combinations. Treat each as a different tested policy, not an exact speed optimization.

## R04 — Main VRPO endpoint and resume semantics need strengthening

**Source:** [vrpo.py](../../TuppiAI/tuppi_ai/vrpo.py), `iterate`/`main`; [isolated infrastructure document](../../TuppiAI-prior/docs/POLICY_PRIOR_INFRASTRUCTURE.md).

Main saves actors on periodic checks, with no unconditional final snapshot. An off-cadence stop can leave the last trained state unsaved; reusing an existing name appends logs and rewrites config without a full resume contract. These are source-confirmed behaviors; the final endpoint was not exercised on a real learner here.

**Proposal already prepared:** validate isolated finalization, cadence-zero support and nonempty-directory refusal. A complete resume feature additionally needs optimizer states, iteration, all RNGs, configuration, curriculum/controller state and source/model/native identities. Actor/critic weight snapshots alone are not a full resume checkpoint.

## R05 — Small self-play jobs can use row-level holdout

**Source:** [selfplay.py](../../TuppiAI/tuppi_ai/selfplay.py), `Learner.collect`.

The normal holdout is by whole self-play batch. If the resulting vector is all held out or none held out, the fallback assigns the first tenth of rows to holdout. That can divide one parent trajectory across fitting and validation. This is especially relevant to small validation/smoke settings; it does not establish that the large SP1 run used the fallback.

**Proposal:** retain parent/deal IDs in captured rows and split by parent; alternatively require enough full batches and fail a scientifically scored run when disjoint splits are unavailable. Validate absence of parent overlap before gates are used.

## R06 — Offline heuristic intervals use decisions as independent units

**Source:** [rule_check.py](../../TuppiAI/tools/rule_check.py), `check`.

The screen computes SE over changed decisions and rescales it to a per-deal sum. Multiple changes share a deal, and unchanged deals are absent from that variance calculation. It is a diagnostic, not confirmation inference, but its interval should not be interpreted as a clustered game-strength interval.

**Proposal:** retain original parent/deal IDs, sum changes per original deal including zeros, then calculate uncertainty across parents. Preserve the one-step continuation qualification. Card-play rankings still need complete candidate trajectories; showing maxima over true-world action outcomes additionally need calibration against implementable choices, as the H2 failure already demonstrated.

## Documentation repair backlog

| Current gap | Proposed small repair |
|---|---|
| AI README describes clone-only rollouts and older two-asset bot | Link a dated current configuration table; distinguish W128 factory from W1024 live |
| Efficiency plan says exact speedups are not installed and sampler fix unmerged | Add a current-status banner with dates/commits; retain historical task reasoning |
| Engine README mixes v1 restrictions and v3 runtime capabilities | Identify supported rulesets/analysis endpoints in one current product table |
| Task records say T6 not started despite later contract completion/screens | Add current programme status pointer to implementation output; preserve dated registration |
| Main/prior/source checkpoints evolve while old hashes remain in handoffs | Record newer evidence separately; immutable handoffs keep their original identity |
| Current review calibration numbers predate changing rollout models | Version calibration by reviewer/model/configuration and rerun only when approved |

This delivery fills the missing cross-project guides. It does not rewrite immutable handoffs or automatically activate repair/experimental tasks.
