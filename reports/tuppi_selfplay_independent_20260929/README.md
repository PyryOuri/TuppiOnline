# Independent self-play groundwork — 29 September 2026

Status: **real-engine correctness milestone passed**. This is a separate output
directory for the returned strength-maximisation packet. No active checkout,
installed library, training run, model checkpoint or live server was modified.
There is no neural learner or strength result in this milestone.

## Run

From the Developer workspace:

```sh
python3 -B audit_deliverables/tuppi_selfplay_independent_20260929/validate_tuppi.py
```

Uses the standard library and isolated copies of the authoritative engine,
rules and existing macOS native library. No dependency installation, GPU,
compiler or existing Python environment is required. The native snapshot is
platform-specific. Generated outputs stay here. Source identities are in
`SOURCE_MANIFEST.json`; the reduced ctypes binding was extracted from the
inspected source and its structure sizes are checked before native calls.

## Delivered

- `estimators.py`: masked probabilities, policy expectation, Q-boosting targets,
  PPO-V GAE control, actor-team conversion and clipped-surrogate numerical
  reference. Explicit terminal versus truncation behaviour.
- `validate_tuppi.py`: actual v3 engine/native differential collector and
  estimator checks, including exact enumeration of real late-game states.
- `TRAJECTORIES.jsonl`: 493 diagnostic decision records from 12 complete deals.
  Includes original parent ID, behaviour version/support, old log probability,
  acting seat, legal action IDs and an actor-feature fingerprint.
- `VALIDATION.json`: results and coverage. `IMPLEMENTATION_CONTRACT.md` specifies
  the remaining learner/adapter work and important corrections to the packet.

## Results

The run passed in approximately 2.3 seconds, covering SHOWING, TRICK_PLAY,
SOOLI_OFFER, SOOLI_GIVE, SOOLI_RETURN and SOOLI_PLAY. All four seat observations
and encoder-2 outputs were checked at every step. Native and authoritative
legal actions, actor, phase, trick totals, winning team, points, next score and
match-terminal flag agreed. Starts include 0–0, 48–0 and 0–48, exercising score
reset and match termination.

Eight ordinary positions with two tricks remaining were exhaustively evaluated
under a uniform legal-action continuation, totalling 86 paths. Exact-Q boosted
advantage error was zero in every case. One position had GAE advantage MSE 0.5
versus zero for Q-boosting; the other seven had zero for both. This demonstrates
the estimator mechanism on a real Tuppi suffix with an exact critic. It does
not establish that a learned critic can achieve that accuracy or improve play.

Other checks: hidden-initial-hand swap leaves bidding actor features unchanged;
masked support and old log probabilities agree; a zero critic at lambda=1
recovers realised returns; team signs are consistent; identical old/new policy
gives the expected PPO surrogate; the reverse recursion matches an independently
computed finite sum at lambda 0, 0.5, 0.95 and 1; terminal bootstrap is rejected,
while truncation bootstrap is retained.

The fixture reward is **Team-0 deal win/loss (+1/−1)**, not incumbent equity or
complete-match return. These are coverage policies, not clone or learned-agent
strength trials. The sample deliberately visits sooli and bids; it is not an
unbiased gameplay sample. Diagnostic trajectories store feature hashes rather
than training tensors, and are not a training dataset. This is a finite
correctness check, not proof of all possible engine states or information flows.

## Next independent work

Build the tensor implementation against this numerical reference, then the
on-policy collector and frozen-policy bookkeeping described in the contract.
Keep PPO-V and VRPO-Q comparable. Before any larger experiment, resolve the
sooli action-head boundary and select the intended deal/match return explicitly.
The packet's SP1 confirmation remains a separate prerequisite for comparisons;
this groundwork neither changes SP1 nor declares it confirmed.
