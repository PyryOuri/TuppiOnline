# Shared execution background

This packet follows [framing 1](../framings/1.md); read its recommendation and
two witness explanations before implementation. It is deliberately narrower than
solving the full partnership game. All paths below are relative to the repository.

## Environment and boundaries

Repository: `/Users/pyryouri/Developer/TuppiProject`.
Interpreter: `/Users/pyryouri/.venvs/tuppi-product/bin/python`.
Run with `-B` to avoid incidental bytecode writes. No dependency installation is
needed for the initial implementation; use the standard library and repository
APIs. Check `git status --short`; unrelated pre-existing work must be preserved.

Proposed new implementation home: **`src/tuppi_nolo/`**, a research layer above
rules, engine, agents, valuation and exact analysis. It does not exist yet.
New tests: `tests/nolo/`. New compact reports: `docs/nolo/results/`.
Generated large or temporary run data: `work/nolo/<run-id>/` inside this repository,
kept separate from the compact reports and not automatically committed.

Earlier packages must not import this new layer. Do not edit `tuppi_agents`,
its registry, rule catalogue, existing policies, the clean rules/engine,
`pyproject.toml`, server code, or the closed search programme. A research agent
subclass may live in `tuppi_nolo/adapter.py`, using the real `RuleBasedPolicy`
ranking interface. It is not a new frozen profile or a live server option.

The charter and historical framing are immutable inputs. Record any correction
in a result document; do not silently repair the history. Production integration
would require a separate task addressing dependency direction and runtime limits.

## Definitions that must not be blurred

- **World/layout:** one allocation of remaining hidden cards to the three other
  seats. `Ω` is the complete set consistent with hard public information.
- **Support:** which worlds are possible. Uniform weights on this support are
  a declared reference measure, not a policy-conditioned posterior.
- **Information key:** one acting seat's own cards and public history, without
  hidden hands or protocol IDs. Indistinguishable worlds use the same future
  own action. Preserve own-hand/legal-action order when retaining baseline ties.
- **Plan:** one action at each future information key for the controlled seat.
  All other seats' legal actions remain possible unless a mode explicitly fixes
  one of their policies. The initial version fixes none of them.
- **Security value:** the smallest worst-case final trick count the controlled
  seat can guarantee for its partnership. The partner is also quantified over
  arbitrary legal actions in this first version. This is conservative protection
  achievable by one seat; it is not the exact cooperative-team equilibrium.
- **Universal improvement:** a candidate's certified upper trick bound is no
  greater than the baseline action's lower bound over *all* legal continuations,
  with a feasible strict case. B does not meet this stronger condition.
- **Security improvement:** candidate worst-case value is smaller under the
  same explicitly stated control model. It need not improve expected outcomes
  against opponents who make exploitable mistakes.

Card codes are rank followed by suit: `QD`, `8S`, `10C`. Trick indices and
positions are zero-based. Partnerships are seats `{0,2}` and `{1,3}`.

## Hard facts and objective corrections

Follow the authoritative rules, not an imported misère or bridge convention:
follow suit if able; no trump; highest led-suit rank wins and leads next; always
play all 13 tricks. Four NOLO shows retain the shown cards in the hands. Showing
fallbacks impose whole-hand exclusions. No dummy or private partner messages.

Hard exclusions may use seen cards, shown ownership, legal showing hierarchy,
proven voids, capacities and their logical consequences. They may **not** assume
“led lowest,” “ducked lowest,” or “won, therefore had no lower card.” B explicitly
contradicts the last claim as a deduction from global rationality.

`score_nolo(8,5)` gives the opponent 8 points; `(9,4)` gives 12. Losing margins
therefore can matter. An up-team loss resets regardless of magnitude; a down-team
win resets regardless of magnitude; a down-team loss adds points to the opponent
and can end the match. Winning overshoot past 52 adds no match-winning value.

For N01–N04 optimize own partnership's final trick count. N05 maps *all reachable
totals* to exact score states. If a scalar is needed, use the repository's
`match_transition_value`, explicitly labelled a score-state proxy, not match
equity. For exact comparison use its rational counterpart: terminal win/loss
`+1/-1`, otherwise `(own_score-opponent_score)/52` as a `Fraction`.

## Fixed fixtures and expected answers

All come from root seed `nolo-framing-2026-09-05`, forced canonical NOLO shows,
`partner_aware_lead_v2` at every seat, round-robin dealers, initial dealer 0.
The original 32 deals are development material, never a new holdout.

| Fixture | Position | Actual bot | Correct interpretation |
| --- | --- | --- | --- |
| A, index 31 | Trick 10, position 1, seat 2; `3H QD 8S`, facing `6C`; team totals 7/3 | `QD` | `8S` guarantees final own total 7 in all 20 worlds and all continuations; alternatives can yield 9 |
| B, index 6 | Trick 10, position 3, seat 0; `9C 3H 3C`, facing `6C 6H 5C`; totals 3/7 | `3C` | `9C → 3C` guarantees 4 in both worlds; duck has security value 5; `9C → 3H` yields 6 |
| C, index 1 | Trick 10, position 3, seat 2; `KC 2D 10D`, facing `7S 6S JD` | `KC` | Actual-layout oracle prefers `10D`; the 24 worlds reverse rankings. Do not issue a universal correction |

A: 560 unconstrained remaining-card partitions, 20 engine-legal. Aggregate
terminal paths: `8S={7:1680}`, `QD={7:360,8:360,9:480}`, and the same distribution
for `3H`. B: 90 partitions, 2 legal. `9C={4:16,6:8}`, `3C={3:8,5:8}`;
constraining the next own lead to `3C` leaves `{4:16}`. Counts are not probabilities.

C: 24 layouts; per-world cooperative full-information minimax pairs
`(KC,10D): count` are `(4,6):6`, `(4,5):6`, `(6,5):6`, `(6,6):3`, `(4,4):3`.
Uniform-reference means are `19/4` and `21/4`; not imperfect-information values.
All-actions final own-total bounds are `[4,6]` for each legal root card. The
single-controlled-seat security values are consequently 6 for all three cards:
the all-actions upper bound is 6 and the more favourable cooperative oracle has
a value of 6 in at least one world for each card. N04 must verify, not assume,
that consequence. With ties, preserve the baseline action.

Do not silently replace the baseline with `partner_aware_v1`. `CorpusSpec`
accepts only registered keys, so its `profile_key="partner_aware_v1"` identifies
the base corpus inputs but **does not select v2**. Build deals with
`generate_base_deal`, force shows, and explicitly supply `void_seeking_agents()`.

## Existing code to reuse

| Need | Existing API / file | Important limit |
| --- | --- | --- |
| Reconstruct fixture | `create_deal_state`, `apply_action`, `observation_for` in `tuppi_engine` | Hand order affects canonical showing/ties; preserve it |
| Force NOLO | `tuppi_valuation.corpus.forced_show_action(obs, Contract.NOLO)` | Call until showing ends; declarations remain engine-legal |
| Generate fixed deals | `tuppi_eval.deals.generate_base_deal`, `DealerPolicy.ROUND_ROBIN` | Record root seed, index, dealer and score |
| Current baseline | `tuppi_agents.void_lead.void_seeking_agents` | Construct fresh agent instances for separate runs |
| Hard support | `HardConstraintModel.build(obs)` in `tuppi_exact.constraints` | Fields: `known_held`, `unknown_cards`, `capacity`, `allowed_seats(card)` |
| Count support | `feasible_assignment_count(model)` in `tuppi_exact.counting` | Exact count; sampling cannot prove completeness |
| Validate a world | `HiddenHandAssignment` + `hypothetical_continuation(obs, assignment)` | Replays the whole public history through engine legality |
| Reference oracle | `solve_late_game(state)` in `tuppi_exact.solver` | Full information, cooperative partner; not the new security objective |
| Information-key precedent | `src/tuppi_search/information_state.py` | Study its observable fields; do not change the closed search layer |
| Strategy-fusion negative control | `docs/search/tiny_exact_information_reference.md` | Its expectation objective differs from the proposed worst-case one |
| Suit count bounds | `tuppi_valuation.suits.general_split_distribution`, `layouts` | No guessed action likelihood, exogenous lead count, or independent-suit value |
| Per-card audit | `walk_deal`, `verify_flow_conservation` in `tuppi_valuation.play` | Research result is a harness input, not a policy input |
| Scoring | `score_nolo`, `transition_rising_score`, `match_transition_value` in `tuppi_rules` | Last function is a proxy, not estimated nonterminal match equity |
| Paired summaries | `tuppi_eval.statistics.paired_value_summary` | Supply one reduced value per independent base deal |

## Initial budgets and fail-closed behaviour

Freeze these for N02–N05: at most 3 tricks remaining, 100 hard-feasible worlds,
2,000 unconstrained partitions for the independent check, and 100,000 engine
transitions per decision operation, including hypothetical replay and verification
when that operation uses them. Count actual transition calls, not merely cache
misses. A caller may grant a separately recorded verification budget; report it
separately, never as free computation. No sampled subset earns an exact claim.

Return `OUT_OF_SCOPE`, `SUPPORT_BUDGET`, or `SEARCH_BUDGET` with no asserted exact
value when those limits stop the operation. Use `INVALID_INPUT` for inconsistent
evidence and propagate unexpected programming errors. Do not catch every
exception and relabel bugs as uncertainty. Stop a manual run after a declared
wall-time cap and report incomplete work without discarding its denominator.

Decision reports must separate `EXACT_COMPLETE` / unresolved status from
`UNIVERSAL`, `SECURITY_ONLY`, `TIE`, or `UNCLASSIFIED` claim type. Include root
information key, sorted legal actions, world count, root action values or bounds,
objective/control-model identifiers, selected action, plan, verifier result,
engine transition count and fallback reason. Diagnostic private worlds belong in
a separate test/report structure; do not return them through an agent explanation.

## Test discipline

Add only meaningful tests for the mathematics and boundaries. A report mentioning
“exact” is not itself evidence. Include deliberate wrong choices, missing worlds,
missing plan branches, hidden-layout changes under the same observation, zero
budget, and score ties. Test negative cases before trusting a passing certificate.

Run focused new tests for each task using:

```bash
/Users/pyryouri/.venvs/tuppi-product/bin/python -B -m pytest -q tests/nolo/<task_test_file>.py
```

The task supplies the filename. These commands describe future checks; the test
files are not yet created. Once imports or the research adapter exist, also run
the relevant existing boundary tests:

```bash
/Users/pyryouri/.venvs/tuppi-product/bin/python -B -m pytest -q tests/agents/test_architecture.py tests/exact/test_integrity_and_variants.py tests/search/test_architecture.py
```

Record pre-existing failures separately. Do not fix unrelated failures or update
frozen digests to get green output. Every task ends with the completion report
specified in the queue README, including honest negative or unresolved endpoints.
