# Tuppi implementation — next LLM entry point

**Self-play research routing (2026-09-29):** for the first 100M programme and
subsequent learning methods, use the returned
[Strength-Maximisation Research Packet](tuppi_selfplay_research_20260929/TUPPI_SELFPLAY_STRENGTH_MAXIMISATION_PACKET.md).
It updates the earlier self-play handoff. This page remains the C0–C5 entry
point; registering the self-play packet does not activate experiments.

Registered 2026-09-25. **Progress 2026-09-26: every contract task is done.**
C0+C1 milestone complete (C1.03 PILOT_READY); C3b, C2, C3a, C4 and C5 contract
tasks CONTRACT_PASS; 109 contract tests pass; pilots, confirmation and
deployment remain NOT_AUTHORISED. Start from
[the implementation report](tuppi_implementation_output/IMPLEMENTATION_REPORT.md)
and [IMPLEMENTATION_STATE.json](tuppi_implementation_output/IMPLEMENTATION_STATE.json).
Owner-approved measurements then set aside C1, C5 and C2 (no meaningful gain), and the owner stopped the package's pilots. **Return deliverable for the planning LLM:** the single self-contained file `audit_deliverables/TUPPI_IMPLEMENTATION_RETURN.txt`; the full evidence is in `audit_deliverables/Tuppi_Implementation_Return.zip` (folder `tuppi_implementation_return/`, start at `RETURN_TO_PLANNER.md`; verify with `verify_return.py`).

(Original registration note: the package was received and integrity-checked on
2026-09-25; that registration step ran no game code.)

## Read in this order

1. [Package overview](tuppi_implementation_plan/README_START_HERE.md).
2. [Implementation master prompt](tuppi_implementation_plan/IMPLEMENTATION_MASTER_PROMPT.md).
3. [Implementation specification](tuppi_implementation_plan/IMPLEMENTATION_SPEC.md).
4. [Acceptance tests](tuppi_implementation_plan/ACCEPTANCE_TESTS.md) and
   [execution DAG](tuppi_implementation_plan/EXECUTION_PLAN.json).
5. [Original repository audit](tuppi_design_20260925_184608/TUPPI_DESIGN_HANDOFF.md),
   its [index](tuppi_design_20260925_184608/TUPPI_DESIGN_HANDOFF_INDEX.json), and
   both source supplements in that same directory. The
   [source map](tuppi_implementation_plan/SOURCE_MAP.json) connects them to tasks.

The returned implementation specification governs the proposed implementation
design; the audit establishes the earlier source snapshot. The later package
includes design refinements, so do not use the earlier audit's sketches as a
replacement for the specification. Check present source drift before editing;
do not reset the workspace to reproduce the snapshot.

## First milestone and task status

**First milestone: C0 + C1 contract completion and pilot readiness.**
Use `EXECUTION_PLAN.json` as the authoritative task/dependency list:

- `C0.01`–`C0.07`: identity/import checks, legal records, ReplayFork,
  isolated native evaluation, fixtures, v3 runners and statistics.
- `C1.01`–`C1.03`: analytical world proxy, fixed-coefficient estimator,
  branch integration and pilot readiness.
- Subsequent correctness tasks cover C3b, C2, C4, C5 and gated C3a;
  follow actual DAG dependencies rather than treating this list as a schedule.
- `P.*`, `CONFIRM`, `COMPOSE` and `DEPLOY` remain separately gated.

All 27 tasks are marked NOT_STARTED in the returned plan. No
`IMPLEMENTATION_STATE.json` was created during registration: the implementing
LLM should initialise and maintain it in its new output directory as directed
by the master prompt. Do not modify the returned plan to manufacture progress.

The package's `execution_enabled` flags describe its default coding scope
**when the master prompt is assigned as a coding task**. They are not evidence
of permission to run anything during this documentation-only handoff.
Pilot, training, confirmation and deployment defaults remain disabled.
Preserve the as-is baseline, retained v3 configuration issue, protected banks,
private rooms, installed native library and other authors' dirty work.

## Workspace mapping

Paths below are relative to the Developer workspace root:

| Alias | Directory | Role |
|---|---|---|
| AI | `TuppiAI/` | Search, native core, clone and research integration |
| ENGINE | `TuppiProject-current/` | Authoritative v3 engine/server checkout |
| RESEARCH | `TuppiProject/` | Separate analytical/support research; preserve concurrent changes |
| CLIENT | `TuppiClient-current/` | Current client; no deployment work in the first milestone |

Do not load both engine checkout versions into one Python process. Environment
and source hashes must be checked by the implementing LLM, not assumed from
these directory labels.

## Integrity check performed

From the workspace root:

```text
python3 audit_deliverables/tuppi_implementation_plan/verify_package.py --audit-dir audit_deliverables/tuppi_design_20260925_184608
```

Exit 0; `successful: true`; 14 package payloads, 11 original audit payloads,
27 tasks and 74 acceptance-test IDs checked; no problems;
`game_code_executed: false`. This verifies hashes and task/reference structure,
not mathematical correctness, game-code acceptance or playing strength.
The included mathematical result files remain the external package's reported
results; they were not rerun during registration.

## Suggested next-session instruction

> Start the Tuppi implementation task at
> `audit_deliverables/TUPPI_IMPLEMENTATION_HANDOFF.md`. Use the returned master
> prompt and specification to implement the first C0+C1 milestone within their
> bounded correctness scope. Preserve experiment/deployment gates and record
> actual per-task progress, commands, results and blockers separately from the
> immutable input packages.
