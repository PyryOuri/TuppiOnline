# Dan 1.1 prototype

Dan 1.1 uses plain VRPO3 card play with an EV-limited preference for legal aces
and kings in early ordinary NOLO play. He uses a .03 equity allowance when
leading tricks 1-3 and .02 in second position on tricks 1-2. There is no extra
card preference in third or fourth position, in later play, in RAMI, or in
sooli. These positions are relative to the current trick. His total per-deal
allowance is .05. These larger allowances replace the previous nearly inactive
.002/.001/.004 prototype settings; the uncertainty multiplier remains 2.

His bids use Nelli 1.1's actual VRPO4 network. When NOLO is legal, a Nelli RAMI
bid must beat the best NOLO bid by at least 14.0 actor-score units or Dan 1.1
chooses NOLO instead. A Nelli NOLO is never promoted to RAMI. This is a policy
score margin, not an EV estimate or a calibrated probability. A hand with no
legal NOLO option retains its legal RAMI choice. Nelli 1.1's bidding policy is
greedy VRPO4; its C1H safety net does not apply during showing.

The margin was increased from 2.0 at the owner's request for quite conservative
RAMI bidding. It was chosen from existing development bid scores to target
roughly 10% RAMI bids on that benchmark; it is not a forced frequency or a claim
about every table. The NOLO card-play allowances and guard remain unchanged.

The native guard compares every legal card on the same 64 hard-feasible hidden
layouts, continued by VRPO3 with no solver tail or recursive personality. It
requires the high card's loss plus two paired standard errors to fit the
allowance against both the plain choice and the best estimated card. A rejected
preference leaves the plain choice intact. This is an approximate guard under
the frozen equity table and rollout model, not a guarantee of true EV or a
measured difficulty level. Existing profile modes 0-4 are unchanged.

## Local terminal preview

From this checkout, with the matching project_target_v3 engine importable:

```sh
export PYTHONPATH="$PWD:../TuppiProject-heidi12-20261023/src"
export VECLIB_MAXIMUM_THREADS=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
/Users/pyryouri/.venvs/tuppi-v2/bin/python tools/play_dan.py --deals 3
```

You play seat 0, with a plain bot partner in seat 2 and Dan 1.1 opponents in seats
1 and 3. `--dan-seats 2,3` puts Dan in the partnership too. The preview uses
ordinary bids. Strong bot tables may produce few NOLO deals, so the habit can
be infrequent. The qualification probe explicitly constructs legal NOLO games
to inspect the rule; it does not estimate natural strength or frequency.

## Transactional agent API

```python
dan = DanAgent(seat=1)
decision = dan.propose_action(observation)
next_game = apply_match_action(game, decision.action)
dan.commit_action(decision)
saved = dan.checkpoint()
restored = DanAgent.from_checkpoint(saved)
dan.close()
restored.close()
```

Proposing, polling and aborting leave the committed cursors and ledger intact.
Pending choices and the last accepted receipt survive JSON checkpoints. A stale
proposal is refused. `choose_action` is a convenience for synchronous serial
engine loops; cancellable callers must use the explicit transaction above.
Checkpoint restore requires the same profile, models, code and native binary.
The name and version are explicit in the profile and checkpoints. Old Dan
prototype checkpoints are refused; the original checkout and binary remain
available separately for their replay.

The standalone tools disable native parallelism and use one process. This
prototype is not yet wired into production hosted rooms or the browser menu.
The additive `tb_dan_choose_observation` and `tb_dan_choose` entry points use the
same native guard and caller-owned proposed contexts. Dan 1.1 requires model
role 2 for showing; a missing network is an error, not a fallback to another
bidding policy. Modes 0-4 and their save formats are preserved. A browser WASM
build must include `tuppi_dan.c` and export
the new entry points before UI wiring. Native entry parity is not WASM or device
qualification.

## Bounded qualification tools

`tools/dan_probe.py --count 16 --out <file>` uses the first eligible roots of a
fixed finite seed roster. Eligibility uses context, legal cards and the base
choice, never rollout effects. `--audit --count 8` adds independent 512-layout
values. `--seed-start 512` selects the separately frozen fresh roster.
`--natural --count 64` runs a short ordinary-play legality/exposure
sample. CPU allocations must be registered before executing these tools.

`tools/dan11_bidding.py --deals 1024 --seed-start 2048 --out <file>` compares
Dan 1.1 with Nelli 1.1 on fresh identical shadow-bid observations. Earlier seats
are legally forced NOLO to expose later positions; these are conditional bid
rates, not human bidding rates or match-strength results.

`tests/test_dan.py` covers context rules, paired loss arithmetic, uncertainty,
complete legal candidates, transaction/cancellation, identity checks, actual
native overrides using an explicitly permissive test configuration, and the
native browser entry including equity-table reconfiguration and the VRPO4 bid
path. It also checks that the bid rule only vetoes borderline RAMI, preserves
forced legal contracts, and records the Dan 1.1 name. Defaults are never changed
by the qualification tools.
