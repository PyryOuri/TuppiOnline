# N02 — Expose complete hard-feasible worlds from an observation

Status: WAITING_DEPENDENCY. Requires N01 PASS. Read BACKGROUND and
`src/tuppi_exact/{constraints,counting,sampling,continuation}.py`.

## Outputs and steps

Create `src/tuppi_nolo/support.py` and `tests/nolo/test_support.py`.
Public entry point: `build_support(observation, budget)`. Accept a
PlayerObservation only; reject a DealState or a fixture dictionary. Return a
typed exact/unresolved result, with private hypothetical states confined to the
research layer. No access to the real initial deal is allowed from this entry.

1. Require resolved NOLO and the shared remaining-trick limit. Build the existing
   HardConstraintModel and count feasible assignments before enumeration.
2. Enumerate assignments using `known_held`, residual `capacity`, `unknown_cards`
   and `allowed_seats(card)`. Visit cards in a deterministic constrained-first
   order, then canonical card order; seats in ascending order. Never assign a
   known card again. Sampling is not a substitute for full enumeration.
3. Build HiddenHandAssignment values and validate each through
   hypothetical_continuation. Reject illegal candidates; a rejection from the
   supposedly exact hard-model enumeration is an implementation error to report,
   not a reason to quietly shrink the support.
4. Build semantic observation keys from observable fields. Use the field design
   in `src/tuppi_search/information_state.py` as a reference, without modifying
   it. Exclude protocol IDs, sample index, hidden owner maps and full hands.
5. Keep optional weights absent. The result is a support, with no ducking or
   lowest-lead exclusions. Count/replay budgets must be deterministic.

## Acceptance endpoints

- A/B/C return exact supports of 20/2/24 and match N01's independently accepted
  world sets exactly. No duplicate, missing or illegal assignment.
- Swapping the actual hidden layout while preserving the observer's input, and
  renaming match/deal/sample references, changes neither support contents nor
  semantic decision key. Do not count hypothetical reference strings as content.
- In B after the public `9C` win, the remaining `3C` is still allowed at seat 0.
  Preferably test this from an opponent's observation, where the owner is hidden.
  No “rationality” exclusion may remove the engine-legal dealt layout.
- Showing fallback exclusions, shown owners and discard-proven voids agree with
  the existing exact tests, including contradictory evidence rejection.
- A 1-world budget yields SUPPORT_BUDGET on A/B/C, never “exact one world.”
  Repeated calls with identical inputs have identical semantic output.

Run `tests/nolo/test_support.py` and the existing exact constraint/counting/
continuation tests relevant to the imported paths. Report counts and budgets in
`docs/nolo/results/N02.md`. Any false exclusion blocks certificates and N03.
