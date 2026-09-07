# Game and bot infrastructure: INF-01 to INF-03 implementation results

Date: 2026-09-07. Status: **INF-01, INF-02 and INF-03 implemented and measured;
every acceptance gate met. INF-04 to INF-06 not started.**

Companion to the [measured efficiency plan](efficiency_plan.md). That document
proposed the gates; this one records what was built and what the paired
measurements produced. Nothing here changes a rule, policy, sampling law,
search budget, schema, profile identity or playing strength.

## Result summary

| Task | Gate | Measured | Verdict |
| --- | --- | ---: | --- |
| INF-01 | 3 -> 1 deal validations per match observation | 3 -> 1 | pass |
| INF-01 | 2 -> 1 per direct deal observation | 2 -> 1 | pass |
| INF-01 | 4 -> 3 per ordinary nonfinal match action | 4 -> 3 | pass |
| INF-01 | >= 25% less CPU on the twelve-deal batch | **36.7% less** | pass |
| INF-01 | >= 20% less in each forced-contract stratum | NOLO 36.9%, RAMI 36.7% | pass |
| INF-02 | <= 1 catalogue build per UCT decision, any budget | 1 at budgets 2/4/8/16 | pass |
| INF-02 | >= 10% aggregate CPU on the six UCT positions | **22.4% less** | pass |
| INF-03 | 1 reconnect and 1 seat projection per recipient | 1 and 1 | pass |
| INF-03 | >= 35% less update CPU on the 6- and 12-trick four-recipient probes | **49.3% and 49.0% less** | pass |

Every gate above was measured with only that one task applied, against the same
baseline tree, as the plan required. Combined, all three together give 35.0% off
the twelve-deal batch, 21.8% off the six eight-simulation UCT decisions, and
80.8% / 81.1% off the two four-recipient live updates.

**Correctness: byte-identical.** A 24 MB canonical capture - every seat's
observation and ordered legal actions after every action of 12 deals, three
fixed complete matches, 216 public rejection cases with their exception classes
and messages, 28 search-decision payloads, and 31 groups of live wire messages -
is identical between the baseline and the implemented tree.

## What changed

Eight source files; no test file, schema, configuration, frozen artifact or
research bank was touched, and no file was added or removed from `src/`.

### INF-01 - validate once at each public boundary

`src/tuppi_engine/observations.py`, `match.py`, `transitions.py`.

Three private helpers now take a state that the immediate caller has already
validated: `_legal_actions_for_validated`, `_observation_for_validated` and
`_apply_action_validated`. The public `observation_for`, `legal_actions_for` and
`apply_action` keep their full input validation and then call the helper, so
their external contract is unchanged. `match_observation_for` and
`apply_match_action` reuse the deal validation that `validate_match_state`
already performs - `_validate_match_state` revalidates the active deal - instead
of repeating it one or two layers down.

Every actor, phase, action-type and follow-suit check is retained. Both new
state constructors keep validating themselves, which is why an ordinary action
still performs three deal validations rather than one. The exemption is
documented in each helper as covering exactly one synchronous call from a public
boundary inside the engine package; it is not carried across an agent callback,
an await, a separate public call or deserialisation. No "already validated"
flag, identity cache or unchecked `DealState` was introduced.

### INF-02 - resolve fixed specifications once per construction/decision

`src/tuppi_search/root_info_uct.py`, `src/tuppi_agents/void_lead.py`,
`src/tuppi_server/match_runner.py`, `src/tuppi_server/completed_deal_review.py`.

`decide` now resolves the frozen rollout specification once, before the
simulation loop, and passes it to `_build_non_root_agents` and to the
`rollout_policy_ids` field. Each simulation still constructs fresh per-seat
runtime agents; only the immutable content-addressed metadata is shared. There
is no cache and no shared mutable global: the caller owns the specification for
the duration of one decision.

`void_lead.py` gained `registered_specification`,
`void_lead_agent_from_specification` and `void_lead_agents_for_seats` so a
caller that needs several void-lead agents resolves the catalogue once.
`void_seeking_agents` and the two server sites that build a whole table now use
them. `construct_void_lead_agent` is unchanged in behaviour, including its
seat-before-profile rejection order.

`tuppi_search/multi_observer.py` needed no change: it already resolved its
showing and fallback specifications once per decision.

### INF-03 - reuse the projection already in the reconnect response

`src/tuppi_server/app.py`.

`_send_match_update` now assembles the whole update from its single
`runner.reconnect(...)` result: the seat observation comes from
`reconnect["observation"]` rather than a second `runner.observation(seat)`, and
the terminal match result from `reconnect.get("match_result")` rather than a
second `reconnect` call. Authentication, cursor handling and send ordering are
untouched, there is no await between the reads, no cross-seat cache, and no
protocol change. Payload byte counts are identical at every probe point.

## Measured call counts

Counted by wrapping `_validate_deal_state_rules`, `_validate_match_state`,
`registered_profiles`, `LiveMatchRunner.reconnect` and the projection boundary
in the harness only. Identical at NOLO and RAMI and at trick indices 0, 6 and 12.

| Operation | Full deal validations before | after |
| --- | ---: | ---: |
| `match_observation_for`, active deal | 3 | **1** |
| `observation_for`, direct | 2 | **1** |
| `legal_actions_for` | 1 | 1 |
| `apply_match_action`, ordinary nonfinal | 4 | **3** |
| `apply_action`, direct | 2 | 2 |
| twelve-deal batch, total | 4640 | **2672** |

Terminal paths were audited separately and were not forced to those counts: the
deal-completing match action goes 6 -> 5 and a match observation of a completed
deal goes 4 -> 2.

| Registry catalogue builds | before | after |
| --- | ---: | ---: |
| one UCT decision, budget 2 | 5 | **1** |
| one UCT decision, budget 4 | 7 | **1** |
| one UCT decision, budget 8 | 11 | **1** |
| one UCT decision, budget 16 | 19 | **1** |
| four void-lead agents (`void_seeking_agents`) | 5 | **1** |

The eight-simulation figure of 11 reproduces the audit exactly. Builds no longer
scale with the simulation budget, and the CPU saved tracks the removed builds
(about 4 ms at budget 2, 10 ms at 8, 19 ms at 16 per decision) rather than the
budget.

| One live `match_update` | reconnects | seat projections |
| --- | ---: | ---: |
| four recipients, before | 4 | 8 |
| four recipients, after | 4 | **4** |
| one recipient, before | 1 | 2 |
| one recipient, after | 1 | **1** |

## Measured timings

Unprofiled paired measurements on the same host, six fresh processes a side in
`ABBAABBAABBA` order, five repetitions inside each process (30 measurements a
side for the batch). Pooled medians of CPU seconds. Python 3.14.2 on arm64
macOS 26.6.2, `~/.venvs/tuppi-product`.

### INF-01 alone

| Workload | baseline | INF-01 | change |
| --- | ---: | ---: | ---: |
| twelve-deal batch, warm | 1827.9 ms | 1157.3 ms | **36.7% less** |
| forced-NOLO stratum, timed sections | 629.5 ms | 397.2 ms | 36.9% less |
| forced-RAMI stratum, timed sections | 570.8 ms | 361.2 ms | 36.7% less |
| natural stratum, timed sections | 617.7 ms | 390.8 ms | 36.7% less |
| twelve-deal batch, fresh process first batch | 1824.7 ms | 1166.3 ms | 36.1% less |

Per-round medians were 1.813-1.841 s baseline and 1.149-1.171 s implemented, so
the separation is far larger than the run-to-run spread. The single action
digest was identical across all 60 measured batches.

### INF-02 alone

| Workload | baseline | INF-02 | change |
| --- | ---: | ---: | ---: |
| six UCT positions, budget 8 | 282.1 ms | 219.0 ms | **22.4% less** |
| six UCT positions, budget 2 | 85.0 ms | 61.0 ms | 28.2% less |
| six UCT positions, budget 4 | 150.1 ms | 113.3 ms | 24.5% less |
| six UCT positions, budget 16 | 543.0 ms | 430.3 ms | 20.8% less |
| four void-lead agents | 5.26 ms | 1.23 ms | 76.7% less |
| four separate `construct_void_lead_agent` calls | 4.24 ms | 4.31 ms | 1.5% more |

Last-trick contribution, reported separately as the plan asked: NOLO-12
16.4 -> 6.3 ms and RAMI-12 16.4 -> 6.2 ms, about 62% less each. Those positions
hold one card per player and therefore expose fixed setup overhead, not a
strategic choice; the early and middle positions improved 11.8-24.2%. The
per-call `construct_void_lead_agent` API is unchanged by design, and its 1.5%
row is within the noise of a 4 ms measurement.

### INF-03 alone

| Live `match_update` probe | baseline | INF-03 | change |
| --- | ---: | ---: | ---: |
| 6 completed tricks, four recipients | 8.86 ms | 4.56 ms | **48.6% less** |
| 12 completed tricks, four recipients | 13.98 ms | 7.22 ms | **48.3% less** |
| 6 completed tricks, one recipient | 2.24 ms | 1.16 ms | 47.9% less |
| 12 completed tricks, one recipient | 3.54 ms | 1.84 ms | 48.1% less |
| deal complete, match nonterminal, four recipients | 26.65 ms | 15.25 ms | 42.8% less |
| deal complete, match nonterminal, one recipient | 6.67 ms | 3.70 ms | 44.6% less |
| showing, four recipients | 1.84 ms | 1.11 ms | 40.1% less |

These are the audit's own components of the real `_broadcast_match` /
`_send_match_update` path with immediate in-memory sends. They exclude socket
backpressure, physical networking, disk writes and UI work, and they do not
remove the configured AI turn delay.

### All three together

| Workload | baseline | all three | change |
| --- | ---: | ---: | ---: |
| twelve-deal batch, warm | 1837.6 ms | 1194.7 ms | 35.0% less |
| six UCT positions, budget 8 | 286.6 ms | 224.1 ms | 21.8% less |
| 6 tricks, four recipients | 8.91 ms | 1.72 ms | 80.8% less |
| 12 tricks, four recipients | 13.90 ms | 2.63 ms | 81.1% less |
| deal complete, four recipients | 26.33 ms | 9.25 ms | 64.9% less |
| four void-lead agents | 5.38 ms | 1.28 ms | 76.2% less |

The percentages are not additive, and the live rows improve most in combination
because INF-03 halves the number of projections while INF-01 makes each one
cheaper. **No measured workload regressed**; the largest adverse movement
anywhere was 1.5% on a 4 ms agent-construction micro-probe, within its noise.

## Correctness verification

The plan forbids accepting a timing result over a correctness mismatch, so the
frozen inputs and canonical outputs were captured from the pre-edit tree first.
Source hashes of all 362 `src`/`tests` Python files were recorded before any
edit ([`source_hashes_before.json`](../../work/infrastructure_implementation/source_hashes_before.json))
and after ([`source_hashes_after.json`](../../work/infrastructure_implementation/source_hashes_after.json)):
exactly the eight files listed above differ, no test file changed, and nothing
was added or removed.

The capture compares, byte for byte through canonical JSON:

- **Ordinary play.** 12 deals (indices 0-3 x forced NOLO, forced RAMI, natural
  showing; 656 actions, 668 recorded steps). At every step, every seat's
  `match_observation_for`, every seat's direct `observation_for`, every seat's
  ordered `legal_actions_for`, and the whole accumulated public event log. Then
  each deal's `DealResult`. This covers both contracts, partial tricks, the
  showing fallback where all four seats show NOLO, made and stolen RAMI, and
  nonacting seats.
- **Match history.** Three fixed complete matches from separate deal streams
  (40, 40 and 29 deals; the third reaches 52 and terminates), including every
  deal result, the full public event history, score resets by the down team, and
  the terminal `MatchResult`.
- **Public rejection.** 216 cases: forged `DealState` values (tampered
  `deal_id`, swapped hands, tampered initial hands, wrong team tricks, tampered
  starting score, wrong actor, a completed phase on a partial deal, a forged
  trick winner, a dropped event, a cleared contract, a wrong first leader, a
  wrong declarer) pushed through `validate_deal_state`, `observation_for`,
  `legal_actions_for`, `apply_action` and `deal_result_from_state`, and the same
  forgeries nested inside a `MatchState` pushed through `validate_match_state`,
  `match_observation_for` and `apply_match_action`; forged `MatchState` fields;
  invalid seats of six kinds including `True` and `"0"`; wrong actor, revoke,
  foreign card, wrong-phase show and play, non-`Action` objects, `None`, and
  actions on a completed deal and a completed match. Exception **class, message
  and order** all match. Rejection order was probed explicitly: a forged state
  combined with an invalid seat still reports the state first.
  Three cases that the baseline already accepts - a forged `initial_score` on a
  match with no completed deals, which nothing cross-checks - still behave
  exactly as before; that is a pre-existing property, not something this task
  introduced or relaxed.
- **Search.** 28 rows: full `RootInfoUctDecision.to_data()` payloads for the six
  audited positions at budgets 2, 4, 8 and 16 - selected action, action rankings,
  visit counts, mean utilities, seeds, tree statistics, rollout policy ids and
  configuration digest - plus the whole specification catalogue, the agent and
  profile digests, and the void-lead error cases. Fresh agents remain four
  distinct objects, repeated catalogue calls return fresh containers, and
  mutating a returned configuration mapping still leaves the next construction
  unaffected.
- **Live projection.** 31 message groups: the exact `match_update` wire messages
  for four and for one recipient, at five probe points (showing, trick 0, 6
  completed tricks, 12 completed tricks, deal complete with the match
  nonterminal), each at three cursor positions - one event behind, a fresh
  reconnect at -1, and an already-current cursor with nothing new to send - plus
  the four per-seat `reconnect` payloads. Acting and nonacting seats both
  covered.
- **Completed-deal review.** The room analysis digest, and its cache hit still
  equal to the cold result.

Reduced per-section manifests are committed as
[`baseline_correctness_manifest.json`](../../work/infrastructure_implementation/baseline_correctness_manifest.json)
and [`current_correctness_manifest.json`](../../work/infrastructure_implementation/current_correctness_manifest.json);
they are identical apart from the recorded size and hash of the capture file
itself, which embeds the source path it was produced from.

## Reproducing

Evidence and scripts are in
[`work/infrastructure_implementation/`](../../work/infrastructure_implementation/).
`harness.py` takes a `--src` tree, so the same workload runs against two
revisions; it only calls public entry points plus the same private live-server
helpers the audit used, and never patches production code for speed.

```sh
PY=~/.venvs/tuppi-product/bin/python
# Freeze a baseline tree to compare against.
cp -R src /tmp/baseline_src   # or a checkout of the pre-change revision
$PY work/infrastructure_implementation/harness.py --src /tmp/baseline_src \
    --mode correctness --out /tmp/baseline.json
$PY work/infrastructure_implementation/harness.py --src src \
    --mode correctness --out /tmp/current.json
$PY work/infrastructure_implementation/compare.py /tmp/baseline.json /tmp/current.json
$PY work/infrastructure_implementation/harness.py --src src --mode counts \
    --out /tmp/counts.json
$PY work/infrastructure_implementation/paired.py baseline /tmp/baseline_src \
    current src all 5 /tmp/paired
$PY work/infrastructure_implementation/analyse.py /tmp/paired/all-paired.json
```

`analyse.py` prints the gate verdicts. `manifest.py` reduces a correctness
capture to the committable manifest. Re-running overwrites these outputs, so a
follow-up task must freeze its own baseline first.

## Regression protection

Two runs were needed, because `pyproject.toml`'s `testpaths` does not collect
`tests/nolo`, `tests/valuation`, `tests/llm` or `tests/rules` outside
`project_target_v1`. Both were run from the repository root with
`~/.venvs/tuppi-product/bin/python -m pytest -q`.

### The configured suite

```
7 failed, 1520 passed, 7 skipped in 996.46s (0:16:36)
```

Everything the plan named as protection for these three tasks passes:
`tests/engine` (148 tests), `tests/rules/project_target_v1`, the
reference-versus-fast differential tests including
`tests/search/test_phase5d_c_optimization.py`,
`tests/agents/test_profiles_and_identity.py`, the conformance and privacy
suites, the UCT and multi-observer determinism tests, and
`tests/server/test_asgi_app.py`, `test_match_runner.py` and
`test_privacy_boundary.py` - `test_accepted_websocket_action_is_durable_before_ack`
included. The 7 skips are the documented baseline: 5 in `tests/learning`
because `torch` is absent from this environment, 2 data-dependent ones in
`tests/search`.

All 7 failures are in `tests/exact`, are pre-existing, and are unrelated to
this work. Every one reports the same single drift string:

```
src/tuppi_agents/void_lead.py references tuppi_exact;
the Phase 5B layer must stay one-directional
```

`capability_containment` in `src/tuppi_exact/integrity.py` scans the raw text of
every module in the earlier packages for the substring `tuppi_exact`.
`src/tuppi_agents/void_lead.py` - untracked work in progress that predates this
task - mentions it twice, in its module docstring and in a comment that exists
precisely to record that the module must *not* import the exact layer. There is
no import; the containment property itself holds. The other six failures are
downstream of that one list entry: `integrity_report()["holds"]`, the
baseline-verifies-against-itself check, both CLI integrity tests and the
documentation test, while `archive_manifest_problems` and
`sealed_bank_problems` are empty.

This was verified rather than assumed. Running `capability_containment` against
the frozen pre-edit tree and against the implemented tree returns the identical
one-element list, and the two mentions are byte-identical in the frozen copy of
`void_lead.py` taken before any edit:

```
BASELINE tree problems: ['src/tuppi_agents/void_lead.py references tuppi_exact; ...']
CURRENT  tree problems: ['src/tuppi_agents/void_lead.py references tuppi_exact; ...']
```

Resolving it means either rewording those two comments in untracked work in
progress or making the scan inspect imports instead of raw text. Both belong to
whoever owns `void_lead.py` and the Phase 5B boundary, not to this efficiency
task, so nothing here was changed to make the check pass.

### Outside the configured testpaths

`tests/nolo`, `tests/valuation`, `tests/llm` and the wider `tests/rules` were
run separately:

```
1 failed, 731 passed, 1 skipped in 1442.30s (0:24:02)
```

The single skip is the opt-in `tests/llm/test_live_smoke.py` gate. The single
failure is a **real consequence of this change** rather than a pre-existing
condition:

```
FAILED tests/nolo/test_evidence.py::test_input_provenance
source drift (do not update expected answers):
  src/tuppi_engine/observations.py
  src/tuppi_agents/void_lead.py
```

`docs/nolo/tasks/source_manifest.json` (committed, dated 2026-09-05) pins the
SHA-256 of the thirteen sources that produced the N01 expected answers, and two
of them are files INF-01 and INF-02 edit. On the frozen pre-edit tree all
thirteen matched, so this drift is attributable to this task and to nothing
else.

**It is provenance drift, not an answer change.** Every substantive NOLO
evidence test still passes with the new engine - the replayed observations,
world enumerations, oracle values, cooperative values and terminal counts are
all unchanged - and the byte-identical correctness capture above covers
`observations.py` exhaustively. Only the recorded hash of the input source is
stale.

Nothing here was edited to make it pass. Per the plan's own rule - do not
regenerate frozen research artifacts or rewrite expected outcomes to
accommodate a discrepancy - the manifest is left alone. Re-pinning it is a
provenance decision for the owner of the NOLO evidence packet: the honest
update is to re-record the two hashes and note that the sources changed without
changing any answer, which is exactly what the capture demonstrates. That is
deliberately not done here.

## Limits

- These are component measurements on one host, not full-match throughput, real
  network latency, disk `fsync`, multi-room saturation or playing strength. The
  live rows exclude socket backpressure and UI work.
- The INF-01 gain is concentrated in observation projection and in transitions;
  it does not reduce the intentional AI turn delay, which is pacing rather than
  compute.
- The INF-02 gain is a fixed per-decision saving. It does not make the search
  itself cheaper, so the relative benefit shrinks as the simulation budget grows
  (28.4% at budget 2 down to 21.0% at 16).
- Deal-complete live updates remain the most expensive projection point
  (9.25 ms for four recipients after all three changes, from 26.3 ms).

## Reassessment of the remaining tasks

The plan asked for a reassessment after these three. Nothing measured here
contradicts its ordering, and two entries should now be re-baselined:

- **INF-04 (contract rollout suffixes)** is still the largest single deployed
  cost and is now the clear next target, but its 1.43 s baseline was measured on
  the pre-INF-01 engine. Its "2x faster triggered evaluation" gate must be
  re-measured against this engine first: those rollouts are dominated by full
  engine transitions and validations, so part of the gate may already be met.
- **INF-05** should be re-profiled before any feature rewrite. Its 20% endpoint
  was defined for the post-INF-02 search, which now exists; with registry
  construction gone, feature construction and public inference are a larger
  share of what remains at the early and middle positions.
- **INF-06** is untouched by this work. The synchronous analysis path still
  replays the stored transcript through the engine; that replay is now cheaper
  per action, but the event-loop blocking it causes is a scheduling problem, not
  a per-action cost, and still needs its own bounded task.

No broader engine rewrite, global validation change, kernel consolidation or
concurrency redesign is justified by these results.
