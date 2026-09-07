# Game and bot infrastructure: measured efficiency plan

Date: 2026-09-07. Status: **review and plan. INF-01, INF-02 and INF-03 have
since been implemented and measured - every gate below was met, with
byte-identical outputs; see [efficiency_results.md](efficiency_results.md).
INF-04 to INF-06 are not started, and INF-04's and INF-05's gates must be
re-baselined against the post-INF-01/02 tree. One follow-up is outstanding and
belongs to another owner: `docs/nolo/tasks/source_manifest.json` still pins the
pre-INF-01 hashes of `src/tuppi_engine/observations.py` and
`src/tuppi_agents/void_lead.py`, so `tests/nolo/test_evidence.py::test_input_provenance`
reports provenance drift although every NOLO answer is unchanged.** The review
below is left as written, as the record of what was measured before any code
changed.

## Recommendation

There are worthwhile targets. Start with **repeated validation inside a single
engine operation, repeated construction of policy specifications, and duplicate
live observation projection**. These have identifiable callers, measurable costs,
and bounded changes that can preserve the existing rules and interfaces.

Then address the full-engine rollouts used for close contract declarations. They
take about **1.43 seconds per qualifying eight-sample decision** in this audit.
Optimising ordinary bot features is a subsequent search-throughput task: it has
little effect on today's ordinary deal execution but matters after expensive
engine work has already been removed from a search loop.

I do **not** recommend a wholesale engine rewrite or globally disabling state
validation. The proposed first engine change deliberately keeps both public input
validation and validation of newly constructed states. A plausible gain is tens
of percent on ordinary execution, not N10's 56-fold research-search result.

| Order | Target | Decision | Benefit and confidence |
| --- | --- | --- | --- |
| INF-01 | Nested engine validation | Proceed first | Broad benefit to ordinary play, evaluation and reference rollouts; high confidence in redundant work |
| INF-02 | Rebuilding fixed policy specifications | Proceed | Small change with direct benefit even to already accelerated search; high confidence |
| INF-03 | Repeated projection within a live update | Proceed | Small server change; about half the measured update CPU is duplicate projection; high confidence |
| INF-04 | Contract-evaluation rollout execution | Proceed after INF-01 measurement | Larger potential gain in a deployed bot decision; medium implementation confidence |
| INF-05 | Public inference and feature construction | Bounded follow-up after INF-02 | Significant inside fast search; benefit from a particular rewrite remains unproved |
| INF-06 | Analysis scheduling and cache validation | Separate responsiveness follow-up | Event-loop blocking observed; production concurrency and safe worker design still need measurement |

INF-01, INF-02 and INF-03 are logically independent. Integrate and measure each
separately; their percentages cannot be added. INF-04 should use the resulting
engine as its baseline. None of these tasks authorises a policy, sampling-law,
search-budget or playing-strength change.

## What was measured

Measurements used the requested
`/Users/pyryouri/.venvs/tuppi-product/bin/python`: Python 3.14.2 on arm64
macOS 26.6.2. HEAD was `6c006b6bae12f2833afad08d6895a00c8044ddc4`, with substantial
existing modified and untracked work. The measured source is the working tree,
not that commit alone. Source/test SHA-256 hashes were recorded before measurement.

Scratch scripts and machine-readable evidence are in
[`work/infrastructure_audit/`](../../work/infrastructure_audit/):

- `probe.py` and `report.json`: ordinary match execution, bot-only calls,
  engine call counts, live publication, and completed-deal review.
- `secondary.py` and `secondary.json`: qualifying contract evaluations, current
  fast UCT, training odds, and an in-process ASGI scheduling probe.
- `components.json`: separate specification, inference and feature timings.
- Named `.pstats` files: diagnostic profiles. Their instrumented times are not
  used as production latency or before/after speedup evidence.

Reproduce the principal probes from the repository root:

```sh
/Users/pyryouri/.venvs/tuppi-product/bin/python work/infrastructure_audit/probe.py
/Users/pyryouri/.venvs/tuppi-product/bin/python work/infrastructure_audit/secondary.py
```

Both scripts measure existing implementations. The live probe substitutes only
the shuffle provider inside its own process to obtain a fixed legal deal. It
does not contact a server or change production code. Re-running overwrites these
scratch reports, so an implementation task must first freeze its own baseline.

### Ordinary play and bot decisions

The generator seed was `infrastructure-audit-2026-09-07-v1`, indices 0–3,
round-robin dealer starting at seat 0, and starting score 0–0. Each deal was
played with the current void-lead bot under forced NOLO, forced RAMI, and natural
showing: **12 legal deal executions, 656 actions** per batch. Forced showing used
the existing `forced_show_action`; subsequent play used unchanged bot decisions.
The four natural deals all resolved to RAMI, hence the forced-NOLO coverage.

After one warm-up batch, three batches took **1.855, 1.885 and 1.864 CPU seconds**.
All three had identical action digests. The median is about **155 ms per deal**.
This is a one-deal execution benchmark, not a full match, live network round trip,
or evaluator run including persistence and report assembly.

| Timed component | Median total CPU across the 12 deals | Approximate share of batch |
| --- | ---: | ---: |
| Observation construction | 0.693 s | 37.1% |
| Applying match actions | 0.989 s | 53.0% |
| Bot choice / forced-show selection | 0.117 s | 6.3% |
| Constructing four bots per deal | 0.056 s | 3.0% |
| Initial match/deal construction | 0.002 s | 0.1% |

Component medians are calculated separately; generation and harness overhead
account for the remainder. This table does not imply that all transition time
can be removed.

On **416 frozen trick-play observations**, ordinary bot calls took a median
71.9 ms total, or about **0.173 ms per decision**, over ten repetitions.
Separate ten-repeat component probes took 46.5 ms for complete feature bundles
and 30.3 ms for public inference alone. Those components overlap.

### Live publication and analysis

The actual `_broadcast_match`/`_send_match_update` path was run for four synthetic
authenticated connections with immediate in-memory sends. Each connection's
cursor was fixed at one event behind the runner. CPU medians of three repetitions:

| Position in one deterministic RAMI deal | Four-client update | Four duplicate observations alone |
| --- | ---: | ---: |
| Six completed tricks | 9.11 ms | 4.53 ms |
| Twelve completed tricks | 14.40 ms | 7.00 ms |
| Deal complete, match nonterminal | 27.36 ms | 13.00 ms |

These are measured components of the current path, **not a measured speedup**.
They exclude socket backpressure, physical networking, disk writes and UI work.
Four human recipients illustrate fan-out; a solo room has fewer recipients.

For that deal, completed-deal review with contract sampling disabled took
291 ms on its first request and 45 ms on an in-memory cache hit. An actual
in-process ASGI request delayed a scheduled 5 ms timer by **285 ms** on the cold
request and **40 ms** on the cached request. Both responses returned HTTP 200.
This demonstrates synchronous event-loop blocking, not measured multi-room load.

At deal end, constructing the private room persistence record took about
0.10 ms and encoding it took 0.35 ms for 66 kB. No disk write or `fsync` was timed.
These measurements do not justify replacing persistence.

### Deployed contract sampling and existing fast search

Configuration matters: `LiveMatchRunner` and `RoomManager` constructors default
to zero contract samples, but
[`RoomManager.from_environment`](../../src/tuppi_server/rooms.py) defaults
`TUPPI_CONTRACT_ROLLOUT_SAMPLES` to **8**. The live bot is the void-lead policy;
NOLO's N10 certificate adapter is not the default live bot.

I scanned first-show observations from the same generator, stopping at the first
three positions satisfying both current boundary conditions: indices **34, 48,
50**, found within the first 51 deals. At eight samples, their median CPU times
were **1.435, 1.421, 1.436 seconds**, versus approximately 0.36–0.38 ms with
sampling disabled. All three actually triggered the paired rollouts. Index 34
selected through the rollout result; the other two reported inconclusive
rollouts and retained the heuristic. This selection is not a trigger-frequency
estimate or playing-strength evaluation.

The index-34 profile recorded **16 `_run_branch` calls, 866 engine transitions
and 3,456 full deal validations**. A requested NOLO branch can still resolve to
RAMI through subsequent showing; an optimisation must preserve that behaviour.

Current standard eight-simulation root-information UCT was also measured on deal
0 under both forced contracts, at trick indices 0, 6 and 12. CPU medians were:

| Contract | Early | Middle | Last trick |
| --- | ---: | ---: | ---: |
| NOLO | 83.7 ms | 46.2 ms | 17.6 ms |
| RAMI | 82.0 ms | 45.5 ms | 17.1 ms |

This search **already uses `FastTrickState`**. Its early/middle profiles are led
by rollout bot decisions and feature construction, not full engine replay.
Each measured decision nevertheless called
`phase4_specifications_by_profile_key` **11 times**, constructing **88 agent
specifications**. A separate registry build cost about **1.09 ms**. The last-trick
positions have only one card per player; they expose fixed setup overhead, not
a meaningful strategic choice. Early/middle positions also showed the repetition.

## Task plans and clear endpoints

The numbers below are proposed acceptance gates, not achieved improvements.
Before editing, an executor must materialise fixed inputs and canonical baseline
outputs from the then-current tree, save its source hashes, and distinguish any
new concurrent edits. Do not regenerate frozen research banks or rewrite their
expected outcomes to accommodate a discrepancy.

For performance acceptance, use unprofiled paired measurements on the same host,
at least five repetitions, alternating implementation order. Report warm and
fresh-process results separately where caching matters. Report CPU, wall time,
operation counts and retained memory. A correctness mismatch fails the task even
if the timing target passes. No new regression above 5% in another measured
workload should be accepted without an explicit explanation and decision.

### INF-01 — Validate once at each public boundary

**Trace:** [`observations.py`](../../src/tuppi_engine/observations.py),
[`match.py`](../../src/tuppi_engine/match.py),
[`transitions.py`](../../src/tuppi_engine/transitions.py),
[`state.py`](../../src/tuppi_engine/state.py).

`match_observation_for` validates the match, including its active deal;
`observation_for` validates that deal again; `legal_actions_for` validates it
again. A normal `apply_match_action` validates the input active deal through the
match, then through `apply_action`, then validates the new `DealState`, then
validates that new deal through the new `MatchState`.

The operation probes confirmed **three full deal validations per match
observation and four per nonfinal match action** in both contracts at all three
measured stages. These validations replay earlier plays, recheck initial hands
and identity, and reconstruct expected events. The work grows within a deal.

**Change outline:** introduce private helpers that operate on a state already
validated by the immediate caller. Public `observation_for` and
`legal_actions_for` retain their full input checks. `match_observation_for` can
reuse its match validation through both helper layers. Similarly,
`apply_match_action` can call a private action dispatcher after its own input
validation. Keep all actor, phase, action and follow-suit checks. Keep both new
state constructors and their existing validation.

The first scope therefore targets **3 → 1** validations for match observation,
**2 → 1** for direct deal observation, and **4 → 3** for an ordinary nonfinal
match action. Terminal paths must be audited separately; do not force these
counts onto terminal result construction. Do not carry a validation exemption
across an agent callback, await, separate public call, or deserialisation.

**Why this scope:** it removes nested duplicate checks while keeping today's
defensive public contract. `frozen=True` alone is not a validation certificate:
the repo explicitly tests forged objects. Caching “validated” by object identity,
skipping `__post_init__`, or returning an unchecked `DealState` is outside scope.

**Pass:** the call-count reductions above; at least **25% less CPU** on the
12-deal batch and at least 20% in each forced-contract stratum; byte-identical
ordered legal actions, observations, public events and results. Check every seat
after every action, both contracts, partial tricks, showing fallback cases,
made/stolen RAMI, score resets and terminal scores. Replay several fixed complete
matches as a separate check of match-history handling.

**Protection:** run `tests/engine`, `tests/rules/project_target_v1`, affected
agent/server suites, and reference-vs-fast differential tests. Explicitly retain
rejection of forged identity, winner, hands, scores, events, wrong actor/phase,
revokes and terminal actions, including exception classes and rejection order
where callers rely on them. An output mismatch or weakened public rejection is
a hard failure. If the timing gate fails, report the smaller result and stop
before attempting an incremental-validation redesign.

### INF-02 — Resolve fixed specifications once per construction/decision

**Trace:** [`registry.py`](../../src/tuppi_agents/registry.py),
[`profiles.py`](../../src/tuppi_agents/profiles.py),
[`factory.py`](../../src/tuppi_agents/factory.py),
[`root_info_uct.py`](../../src/tuppi_search/root_info_uct.py), and the corresponding
helper in [`multi_observer.py`](../../src/tuppi_search/multi_observer.py).

`_frozen_policy_specification` rebuilds the complete catalogue, even though a
decision repeatedly requests the same fixed policy. Each simulation still needs
fresh per-seat runtime agents; it does not need fresh content-addressed metadata.

**Change outline:** first resolve specifications once per search decision and
pass them to agent-construction helpers. Apply the same principle when creating
four void-lead agents. Prefer explicit ownership of immutable specifications to
a shared mutable global dictionary. If a catalogue cache is later worthwhile,
retain defensive validation of externally supplied/custom specifications and
return fresh public containers. Never reuse runtime agents across seats or
simulations just to obtain the metadata saving.

**Pass:** at most one catalogue build per UCT decision, independent of simulation
budget; identical specifications, profile/configuration digests, action rankings,
visit counts, values, seeds and complete decision payloads. Fresh agent instances
must remain distinct. Seek **at least 10% aggregate CPU reduction** on the six UCT
positions and report the last-trick contribution separately. Include budgets
2, 4, 8 and one larger diagnostic budget to show that registry construction no
longer scales with simulation count.

**Protection:** `tests/agents/test_profiles_and_identity.py`, conformance and
privacy tests, and affected UCT/multi-observer determinism tests. Mutating a
returned configuration mapping must not affect another construction. This task
does not justify a new policy identity if all behavioural bytes remain identical.

### INF-03 — Reuse the projection already in the reconnect response

**Trace:** [`TuppiASGIApp._send_match_update`](../../src/tuppi_server/app.py) and
[`LiveMatchRunner.reconnect`](../../src/tuppi_server/match_runner.py).

`reconnect()` already returns the authenticated seat's observation and, when
terminal, its match result. `_send_match_update` ignores the observation and
projects it again; at match termination it calls `reconnect()` again for the
result. There is no await between those synchronous computations.

**Change outline:** assemble the existing update from that single reconnect
result. Keep authentication, cursor behaviour and send ordering intact. This
does not require a cross-seat cache or a protocol change.

**Pass:** one reconnect call and one seat observation projection per recipient;
identical canonical messages for acting/nonacting seats, stale reconnects, deal
completion and match completion. Seek **at least 35% less update CPU** on the
six- and twelve-trick four-recipient probes, measured against the same engine
revision. Also report one-recipient results.

**Protection:** `tests/server/test_asgi_app.py`, `test_match_runner.py` and
`test_privacy_boundary.py`; preserve `test_accepted_websocket_action_is_durable_before_ack`.
Never share a complete observation between seats. The saving here is
milliseconds and server capacity; it will not remove the configured turn delay.

### INF-04 — Accelerate contract rollout suffixes

**Trace:** [`evaluate_contract_choice` and `_run_branch`](../../src/tuppi_server/contract_evaluation.py).
Compare the existing
[`FastTrickState`](../../src/tuppi_search/fast_trick.py) and
[`Phase 5D-C differential tests`](../../tests/search/test_phase5d_c_optimization.py).

**Change outline:** keep exact sampling and authoritative showing/prefix
construction. Once a branch has resolved its contract, execute its simulated
trick-play suffix through an audited fast representation. Start by assessing
reuse of `FastTrickState`, which supports both contracts, rather than creating
another kernel. Conversion must preserve **every seat's hand order**, all public
history and score. Its observation/assignment constructor is not automatically
a safe replacement for a validated state conversion.

Keep the engine as an independent reference. Do not make earlier packages import
`tuppi_search`, and do not replace the live authoritative match state. Decide the
smallest legal adapter location before editing. N10's NOLO-only compact backend
is not a complete replacement for these mixed-contract branches.

**Pass:** initially use indices 34/48/50 and samples 0/8, then a frozen larger
set covering earlier NOLO shows and RAMI resolution at every possible showing
position. Require identical sampled assignments, all per-branch observations and
actions, final tricks/scores, aggregate records, selected contracts and fallback
reasons. Include failed and inconclusive evaluations in the denominator. Preserve
the 56-action guard and illegal-action handling. Seek **at least 2x faster
triggered evaluation relative to the post-INF-01 engine**, with unchanged sample
count. This is a performance gate, not evidence for changing contract decisions.

**Protection:** `tests/server/test_contract_evaluation.py`, completed-deal replay
tests, sampling/continuation tests and cross-kernel differential checks. Results
from the live evaluation and four-bot replay must retain their separate schema
fields and policy identities. Stop if identical actions or the dependency
direction cannot be preserved with a bounded adapter.

### INF-05 — Optimise public features only where they dominate

**Trace:** [`PublicInference.build`](../../src/tuppi_agents/public_inference.py),
[`build_features`](../../src/tuppi_agents/features.py), and per-action queries in
[`partner_aware.py`](../../src/tuppi_agents/partner_aware.py).

After fast transitions, early UCT makes hundreds of ordinary bot calls. Here
feature construction matters. In ordinary play, eliminating *all* choice cost
would save only about 6% of this audit's batch, so this is lower priority there.

**Change outline:** profile again after INF-02. Investigate compact internal
owner/suit sets and facts reused across candidate actions within one decision,
while returning the exact existing public inference object. Preserve every
singleton/capacity deduction and the refinement stopping rule. A smaller exact
implementation is useful; dropping deductions changes the policy.

Do not start with a history-spanning feature cache. Different observations,
different seats and different hypothetical hands require different inference.
The existing [Phase 5F report](../search/phase5f_profiling.md) found no reusable
observer contexts in one full traversal; that historical finding argues for
measuring hit rates before introducing another cache.

**Pass:** exact inference fields, complete candidate scores and diagnostics on
all frozen observations and existing information-set-invariance tests. Proposed
worthwhile endpoint: **20% less early/middle fast-UCT CPU after INF-02**, with
unchanged simulation counts and outcomes. If local feature changes do not reach
this endpoint, retain the negative finding and stop expanding the rewrite.

### INF-06 — Keep expensive analysis from blocking unrelated play

**Trace:** synchronous `_http_command` dispatch in
[`app.py`](../../src/tuppi_server/app.py), analysis methods in
[`rooms.py`](../../src/tuppi_server/rooms.py), and
[`validate_completed_deal_review_against_runner`](../../src/tuppi_server/completed_deal_review.py).

The cache-hit review path correctly avoids rerunning the policy, but still
replays the complete stored bot transcript through the engine to validate it.
Current HTTP dispatch performs this synchronously. Live AI choice already uses
`asyncio.to_thread`; simply adding the same call there would duplicate existing
work rather than solve this analysis-path issue.

**Next bounded task:** after the smaller changes, measure one and four analysis
requests while a separate room serves health/ping/action traffic. If blocking
persists, evaluate a bounded worker arrangement using immutable, authenticated
request snapshots, with room mutation and result publication owned by the event
loop. Include duplicate-request coalescing and a bounded queue. A thread alone
is not evidence of higher CPU throughput; measure responsiveness and throughput
separately before choosing threads or processes.

Treat a trusted in-memory analysis artifact and a record loaded from disk as
different boundaries. Disk/restart input must still undergo full validation.
Avoiding repeated validation of an in-memory result would require private
ownership, immutable content or a verifiable content binding, correct
deal/seat/schema/policy/sample-configuration identity, and defensive copies on
return. The current public mutable room cache must not simply become trusted.

**Pass:** no changed response bytes or seat permissions; existing restart,
tampered-cache, stale-policy and caller-mutation checks pass. Proposed operational
gate: p99 unrelated-room response below 50 ms and at least 80% reduction in
analysis-induced excess lag on the same host, over at least 100 requests in a
two-minute bounded run. Account for cancellation, room progression and queue
capacity; no stale result may be applied to live state. Do not weaken
durability-before-acknowledgement. If the remaining latency is already acceptable,
defer a worker/cache redesign rather than introducing concurrency for its own sake.

## Ideas deliberately not recommended now

- **Global “already validated” flags, disabling validators, or an unchecked
  production `DealState`:** changes the defensive contract and can hide forged
  history. INF-01 has a smaller, auditable opportunity first.
- **Replacing every engine with N10's compact backend:** it is a research-only
  NOLO representation. UCT already has a different fast path; showing, RAMI,
  persisted events and authoritative match coordination still need coverage.
  Kernel consolidation is maintenance work until a shared contract and benefit
  are demonstrated. The [N10 report](../nolo/results/N10.md) does not predict a
  56x improvement to live play or to search already using compact transitions.
- **Approximate suit laws or weakened hard inference:** changes bot behaviour
  and can invalidate exact claims. `_rounds_survived` already caches its exact
  finite-parameter law; no uncached-law bottleneck was demonstrated here.
- **Skipping candidate scoring on a forced card or replacing `choose_action`
  independently of `decide`:** could save some construction, but complete rankings
  and diagnostics have an explicit conformance contract. Address measured common
  work before creating divergent execution paths.
- **More workers as the first remedy:** ordinary evaluation and research jobs
  can benefit from process parallelism, but redundant work remains per worker.
  No host saturation, RAM or multi-room capacity study was done in this audit.
- **Database migration, event-log compaction, or relaxed atomic persistence:**
  the measured one-deal JSON cost was small, disk latency was not measured, and
  restart/acknowledgement guarantees are tested. Long-match full-history scans
  and record growth are visible in code but need their own measurements first.
- **Compiled engine, GPU, or whole-game card bitset rewrite:** no current evidence
  justifies the build/maintenance scope. Compact internal sets in INF-05 can be
  considered without changing public card types or canonical ordering.
- **Reducing the configured AI delay:** it is intentional pacing (default five
  seconds, host-configurable), not compute overhead. Keep it separate when timing.

## Limits, verification and stopping rule

This audit read engine/rules boundaries, baseline bot construction and scoring,
the relevant evaluator path, current search fast paths, and server projection,
analysis and persistence code. It also read the existing architecture and
profiling reports before proposing changes. Existing tests were inspected as
contracts; the full regression suite was **not run**, because no production code
was changed. The measurements exercised legal engine execution and compared
repeated action digests and cached review content; they are not a replacement for
the implementation gates above.

Not measured: full-match throughput, evaluator disk/report overhead, long-match
history growth, physical client rendering, real network latency, disk `fsync`,
multi-room saturation, cold deployed eight-sample completed-deal reviews, or
playing strength. Six training-odds calls were also timed, at about 0.46–11.9 ms
median depending on position; that sample does not establish a serious standalone
training-analysis bottleneck.

All pre-existing source and test files remained unchanged. No game/bot behaviour,
rules, schemas, profiles, production data, or frozen research artifacts were
edited. The only new review output is this plan plus local scratch evidence.

Confidence is **high** that INF-01–03 remove avoidable work, **medium** in their
eventual end-to-end gains and the INF-04 adapter, and **conditional** for INF-05–06.
The most useful contrary evidence would be a paired implementation measurement
showing little total benefit after preserving all contracts, or realistic live
load showing another bottleneck dominates. Complete the first three bounded
changes, measure their combined result, and reassess before committing to a
broader infrastructure project.
