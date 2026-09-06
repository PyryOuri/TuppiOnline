# N08 — Make the certified choices executable in a research agent

Status: WAITING_GATE. Requires N07 GO, all earlier correctness checks, and G1
adoption of this branch or an explicit user waiver. This task creates an offline
research agent only. It does not register, deploy or rename a live bot.

## Outputs and steps

Create `src/tuppi_nolo/adapter.py`, `tests/nolo/test_adapter.py` and
`docs/nolo/results/N08.md`. Subclass the actual v2 RuleBasedPolicy in this new
research layer. Baseline showing, RAMI, out-of-range NOLO and unresolved decisions
delegate to v2. Do not modify the existing agents/search/server packages.

1. Entry points accept PlayerObservation and existing PublicFeatures only.
   No private DealState, fixture identifier or real deal lookup may enter the
   adapter. Construct hypothetical supports only from the observation.
2. Rank eligible NOLO actions by the completely solved, verified worst-case
   score-state proxy from N05. Use v2's ranking as the tie break. Both UNIVERSAL
   and SECURITY_ONLY changes may occur, but explanations must distinguish them.
   On incomplete initial search, use the baseline and record the reason.
3. Implement the preference as a score component for **every** legal action,
   using CandidateEvaluation/ScoredActions as in `void_lead.py`. The chosen action
   must be the lexicographic maximum. Do not override choose_action to contradict
   decide/explain. Add no catalogue rule or validation provenance to Phase 4.
4. Honour the whole certified continuation. A's action needs no future own
   restriction. B does: taking `9C` and then falling back to the baseline's `3H`
   is a failed implementation. Retain the verified finite plan, indexed by root
   information key, so its next choice can be executed without another costly
   search. Consume no plan branch merely because decide/explain is called.
   Clear plans at a new deal; reject mismatched histories. Reserve complete plan
   availability before committing the first card. A budget failure later may
   not silently substitute an unverified continuation while keeping the guarantee.
   Declare this as a finite-memory research strategy: memory contains only its
   own earlier observations and verified plans. Do not claim it is a stateless
   Phase 4 policy. Invariance comparisons must supply the same observed history
   and configuration; hidden hands must never populate this memory.
5. The supplied control model permits arbitrary partner actions. Each seat may
   therefore execute its own certified plan without reading a partner's private
   plan or hand. Do not introduce a shared omniscient team controller.

## Acceptance endpoints

- A chooses `8S`; the played continuation finishes at 7 for every compatible
  world and all other-seat legal continuations.
- B at score `(0,0)` chooses `9C` and subsequently `3C`; all compatible worlds
  and other-seat continuations finish at 4. An exhausted fresh-search budget at
  that second decision still executes the already verified `3C` plan.
- B and A score-tie variants from N05 preserve the baseline at the initial
  decision. C preserves `KC`. No guessed posterior drives a correction.
- choose_action, decide and explain agree on identical observations regardless
  of repeated diagnostic calls. Hidden-world substitutions and protocol-ID
  renaming along the same observed history do not change decisions or semantic
  explanations. Explicitly test
  plan replay, repeated calls, new-deal reset and mismatched-history detection.
- New recursive architecture check: earlier packages do not import tuppi_nolo;
  policy input/output exposes no hidden allocations. Existing architecture and
  frozen-profile checks pass without digest changes.
- On the completed N07 position list, record p50/p95/max latency, transition
  counts, plan sizes and fallback rates. This is an offline cost report, not a
  claim of suitability for the live server. No arbitrary runtime claim is needed
  to complete this task.

Run `tests/nolo/test_adapter.py` and the shared boundary checks. Any disagreement
between the certified plan and played action is FAILED_CHECK, even if a small
simulation happens to look favourable. Freeze one candidate configuration/hash
after passing; N09 cannot select among variants on its evaluation bank.
