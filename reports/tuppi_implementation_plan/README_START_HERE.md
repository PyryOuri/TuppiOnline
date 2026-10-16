# Tuppi implementation package

Prepared 25 September 2026 from the returned static repository audit.

## Use

Give the directory-access coding LLM `IMPLEMENTATION_MASTER_PROMPT.md`, this package, and the original audit bundle. The master prompt is self-contained about purpose and boundaries; `IMPLEMENTATION_SPEC.md` supplies the detailed algorithms and integration contracts. Keep the source capsules available for exact implementation evidence.

The first coding milestone is **C0 + C1 contract completion and pilot readiness**. It is not another audit and not a claim of improved play. Subsequent milestones cover C3b, C2, C4, C5 and the gated C3a model. The task graph records dependencies and required tests. A blocker in one branch need not prevent independent work elsewhere.

The default prompt requests isolated code plus bounded correctness checks when supplied as a coding task. It does not enable a training or benchmark campaign. Enable an experiment only through a separately approved manifest with numeric CPU/wall/memory limits, frozen hypotheses, candidate identity and independent splits. Do not alter the live bot or open protected banks.

## Contents

| File | Purpose |
|---|---|
| IMPLEMENTATION_MASTER_PROMPT.md / .txt | The prompt to supply to the coding LLM. |
| IMPLEMENTATION_SPEC.md | Concrete designs, interfaces, mathematical objectives, failure handling and experiment gates. |
| ACCEPTANCE_TESTS.md | Stable acceptance-test IDs; these are requested tests, not claimed passes. |
| EXECUTION_PLAN.json | Task dependency graph, scope and default disabled experiment phases. |
| PILOT_MANIFEST_TEMPLATE.json | Templates requiring approval and completion before experiments run. |
| SOURCE_MAP.json | Audit question/evidence provenance and links to design tasks. |
| verify_package.py | Read-only package and optional audit-payload integrity verification. |
| reference_math.py | Standard-library finite mathematical examples, independent of Tuppi. |
| DESIGN_MATH_RESULTS.json / DESIGN_MATH_TEST_LOG.txt | Results from running those examples here. |
| INPUT_VERIFICATION.json | Verification of the eleven supplied payload hashes and sizes. |
| PACKAGE_VALIDATION.json / PACKAGE_MANIFEST.json | Structural checks and hashes for this generated package. |

The original audit bundle is an input, not duplicated inside this archive. No model weights, native binaries, private rooms, human games or sealed data are included.

## What changed after the audit

The design now uses the audited encoder-2/1951-input identity and distinguishes installed binaries from rebuilt source. It does not assume that a deal-state clone clones a controller, that old match evaluation supports v3, or that score/dealer alone identifies the current match process.

C1 includes a research-only explicit-world evaluator and separates the variance-reduction mechanism from persistent-RNG advancement. C2 starts with a controlled clone predecessor model. C3b uses a conservative utility-equivalence certificate; C3a investigates a bounded configuration-mode model instead of asserting a 100-state reduction. C4 conditions receiver learning on the actual giver policy. C5 stores a legal contingent option and compares complete continuations, not independent per-world choices.

## Verification boundary

All eleven payloads listed in the supplied SHA256SUMS.txt matched their declared hashes and sizes. The Markdown and text handoffs are byte-identical. The supplied pre/post records agree on their common repository-state fields. These checks verify delivered bytes and internal consistency, not the truth of the originating audit or historical binary/source equivalence.

The included mathematical tests ran successfully. No Tuppi source, model, native library, fixture, benchmark or training job was executed here. All game-code acceptance tests remain to be implemented/run in the actual workspace. No playing-strength improvement is claimed.

## Immediate handoff result to request

Require an implementation report, actual code/patches, per-task state, exact test commands and logs, build/baseline manifests, validated legal fixtures with separate evaluator truth, and disabled pilot manifests. Request a precise blocker where necessary, not an invented pass or another broad research review.
