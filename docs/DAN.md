# Dan prototype

Dan is a plain VRPO3 bot with an EV-limited preference for legal aces and kings
in early ordinary NOLO play. He uses a .002 equity allowance when leading tricks
1-3 and .001 in second position on tricks 1-2. There is no extra preference in
third or fourth position, in later play, in RAMI, or in sooli. These positions
are relative to the current trick. His total per-deal allowance is .004.

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

You play seat 0, with a plain bot partner in seat 2 and Dan opponents in seats
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
Checkpoint restore requires the same profile, model, code and native binary.

The standalone tools disable native parallelism and use one process. This
prototype is not yet wired into production hosted rooms or the browser menu.
The additive `tb_dan_choose_observation` and `tb_dan_choose` entry points use the
same native guard and caller-owned proposed contexts; modes 0-4 and their save
formats are preserved. A browser WASM build must include `tuppi_dan.c` and export
the new entry points before UI wiring. Native entry parity is not WASM or device
qualification.

## Bounded qualification tools

`tools/dan_probe.py --count 16 --out <file>` uses the first eligible roots of a
fixed finite seed roster. Eligibility uses context, legal cards and the base
choice, never rollout effects. `--audit --count 8` adds independent 512-layout
values. `--natural --count 64` runs a short ordinary-play legality/exposure
sample. CPU allocations must be registered before executing these tools.

`tests/test_dan.py` covers context rules, paired loss arithmetic, uncertainty,
complete legal candidates, transaction/cancellation, identity checks, actual
native overrides using an explicitly permissive test configuration, and the
native browser entry including equity-table reconfiguration. Default allowances
are never relaxed by the qualification tools.
