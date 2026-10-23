# Heidi 1.2 and Nelli 1.1: AI side (2026-10-23)

Built to `audit_deliverables/tuppi_base_network_task_20261022/release/RELEASE_CONTRACT.md`,
including its amendment of 2026-10-23 ("anchor only"). Branch `feature/heidi12-20261023`
from `b30763c` (the Heidi 1.1 AI source). The new bots are the Heidi 1.1 and Nelli 1.0
controllers with a third network role: the 768x4 encoder-2 QNet in
`models/vrpo4_final.pt`. Heidi 1.2 uses it only as its anchor (the keep rule for bids and
play); its play-inference likelihood model stays VRPO3 (role 1) and its rollouts VRPO1
(role 0). Nelli 1.1 uses it for its policy and its safety net. Today that file is the
pilot stand-in (sha256 `bd1342e5…`); this document makes no strength claim about it.

## Native controller (`native/tuppi_browser.c`)

Roles: 0 rollouts (VRPO1 256x2), 1 anchor (VRPO3 512x4), 2 the new network (768x4).
Two helpers pick the decision-path networks; rollouts always use role 0:

- `anchor_model()`: role 2 in modes 3 and 4, role 1 otherwise. The search's keep rule for
  bids (margin 0.03) and play (0.003), the anchor-only bid (`tb_configure_bids(1)`) and
  the lite policy of modes 1 and 3.
- `likelihood_model()`: role 2 in mode 3 only, role 1 otherwise. The play-inference
  likelihood (`tc_env_set_belief` in `tb_configure_bot` and `tb_configure_inference`,
  modes 2 and 4) and the safety net's belief in modes 1 and 3 (the lite policy's own
  network).

So mode 4 searches exactly as mode 2 (same worlds, rollouts, likelihood weights, values and
cursors) and differs only where the keep rule's anchor (role 2 instead of role 1) has a
different argmax. `mode_ready(mode)` requires every network the mode reads: role 1 for modes
0-2, role 2 for mode 3, roles 1 and 2 for mode 4 (role 0 is required by `tb_configure`).

```c
int  tb_load_model(int role /* 0..2 */, int in_dim, int width, int blocks, int encoder,
                   int count, const float *params);
int  tb_configure(int n_worlds, const double *equity);   /* role 0 and role 1 or 2, else -1 */
int  tb_configure_bot(int mode /* 0..4 */, int people);  /* -1 unless the mode's roles are loaded (mode 4: 0, 1, 2) */
int  tb_configure_inference(int mult, int lanes);         /* modes 2 and 4 */
int  tb_configure_bids(int mode);                         /* 1 only in modes 2 and 4 */
int  tb_restore_net_context(int seat, uint32_t glo, uint32_t ghi, uint32_t blo, uint32_t bhi); /* modes 1, 3 */
int  tb_inference(int role /* 0..2 */, const uint8_t *features, int rows, float *out);
void tb_dispose(void);                                    /* frees all three roles */
```

| Mode | Bot | Network roles | Same as |
|---|---|---|---|
| Mode | Bot | Anchor | Likelihood | Network roles read | Same as |
|---|---|---|---|---|---|
| 0 | legacy search | 1 | (none) | 0, 1 | unchanged |
| 1 | Nelli 1.0 (lite C1H) | 1 | 1 | 1 (+0 loaded) | unchanged |
| 2 | Heidi 1.0 / 1.1 (search, PIB) | 1 | 1 | 0, 1 | unchanged |
| 3 | Nelli 1.1 | 2 | 2 | 2 (+0 loaded) | mode 1 with role 2 |
| 4 | Heidi 1.2 | 2 | 1 | 0, 1, 2 | mode 2 with role 2 as the anchor only |

`tb_configure` still leaves mode 0; with only roles {0, 2} loaded, `tb_choose` and
`tb_choose_observation` return -1 until `tb_configure_bot(3)`, and mode 4 is refused
(it needs role 1 for the likelihood). No function was added or removed, so the WASM
export list is unchanged.

## Hosted Python

```python
# tuppi_ai/lite.py
MODEL     = ROOT / "models" / "vrpo3_final.lite.npz"   # unchanged
MODEL_V4  = ROOT / "models" / "vrpo4_final.lite.npz"
def shared_mlp(path: Path = MODEL) -> native.Mlp       # one network per (resolved) file
class LiteAgent:
    def __init__(self, seat, mlp=None, rng=None, options=None, net_rng=None, model=None)
    def greedy_action(self, obs: native.TcObs, ids) -> int   # the unchanged greedy rule, factored out
# Nelli 1.1 = LiteAgent(seat, options=C1H, model=MODEL_V4); model=None plays exactly as before;
# mlp and model together raise ValueError.

# tuppi_ai/compact.py
MODES = (2, 4)
NETWORKS = ((0, "vrpo1_actor_0504.f32", 256, 2, 804508),
            (1, "vrpo3_final.f32", 512, 4, 3185820),
            (2, "vrpo4_final.f32", 768, 4, 6351516))
def model_identity(directory=None) -> {"manifest": ..., "sha256": sha256(models.json)}
class CompactController:
    def __init__(self, directory=None, mode=2)          # loads all three; mode 2 or 4
    mode: int                                            # the configured mode
    def choose(self, observation, context, human_seats=(), mode=None)
        # -> (action, next_context, values); mode None keeps the current mode, a different
        # mode calls tb_configure_bot(mode, people) and tb_configure_inference(8, 1) first
    def close(self)
```

`model_identity` requires exactly the three records above (a two-network directory is
refused); the manifest records every file's sha256 and each file is checked, so its hash
covers all files. Contexts are unchanged (three words; modes 2 and 4 restore them before
every decision).

## Compact directory (`models/compact`, written by `tools/export_compact.py`)

| File | Bytes | sha256 |
|---|---:|---|
| `models.json` | 2,133 | `4694a18c82eacf7b7ee3b6aea47d0a8138c999f6d9ed1a8bfce7951b12cb660c` |
| `vrpo1_actor_0504.f32` (role 0) | 3,218,032 | `beb1f890947748a3df254dc200b9433547babc9fe40388fe76ba82e0f01abbda` (unchanged) |
| `vrpo3_final.f32` (role 1) | 12,743,280 | `0e4bba619908ad3fa92a75fb118470b436ffa571caaca5e8f6aab497be633b47` (unchanged) |
| `vrpo4_final.f32` (role 2) | 25,406,064 | `528b85eb0c408087c6cb5c32cbebffe903757152f1619ffa343b0d10a55ba81b` (stand-in) |
| `equity.f64` | 400 | `8e01246f723210a8e0364a63748de460b94b6e5a513e8e747dc91744f1bc3f0b` (unchanged) |

`models.json` uses the browser's `tuppi.browser.assets.v1` record format and the same
code as the browser's `tools/export_models.py`; with the third record removed it is
byte-identical to the Heidi 1.1 file (`8cb282aa…`). The tool refuses to change the role
0/1 files or the equity table; `--check` compares without writing.
`models/hosted-models.json` adds `vrpo4_final.pt` (`bd1342e5…`) and
`vrpo4_final.lite.npz` (`b7c9900d…`, equal to a fresh export by `--check`).

Sunday (final weights): copy the actor to `models/vrpo4_final.pt`, then
`python tools/export_lite_model.py --model models/vrpo4_final.pt --out models/vrpo4_final.lite.npz`,
`python tools/export_compact.py`, update the two hashes in `hosted-models.json`
(`width/blocks` must stay 768x4 or `NETWORKS` must change), rebuild and rerun the tests.

## Verification

- Bit identity of modes 0, 1, 2 (`tests/test_heidi12.py`): the test builds the library
  with `native/tuppi_browser.c` from `b30763c` (other sources as now) and compares whole
  deals played by `tb_choose` — actions, every value as a hex float and all seven cursor
  words — against the new library with roles {0, 1} and with roles {0, 1, 2}: mode 0 (2
  deals, W128), mode 1 (5 deals, people marked and not), mode 2 (W128 PIB8 with people,
  2 deals including sooli offer/give/return/play; W256 PIB4 for the adaptive bid search).
  The same comparison was also run by hand against a build saved before editing
  (`native/libtuppi_before.dylib`, untracked): identical. After the anchor-only change
  (2026-10-23) the test passes again against `b30763c` and, with
  `TUPPI_BEFORE_LIBRARY` set to a build of `12a1a1f` (the previous Heidi 1.2 controller),
  against that build too; mode 3 traces (4 deals with a person marked on roles {0, 2}, 2
  deals on roles {0, 1, 2}) are identical to `12a1a1f`'s.
- Anchor only (`test_mode4_is_mode2_with_role2_as_the_anchor_only`): modes 2 and 4 decide
  from the same position and restored cursor on 80 roots at W128 PIB8 with a person marked
  (bids, play, sooli phases) and 8 bid roots at W256 (adaptive search). Values and all seven
  cursor words are equal on every root; where roles 1 and 2 have the same argmax the whole
  decision is equal; where they differ each mode's action is its own anchor's keep rule
  (recomputed from the recorded values at W128). With the stand-in, 20 of 69 W128 roots with
  a choice of bid or card have different argmaxes.
- Hosted mode 2: `CompactController(mode=2)` with three networks loaded equals mode 2 of the
  old build (roles {0, 1}) at W1024/PIB8 on six fixed engine roots (actions, cursors,
  values exactly); switching 2 → 4 → 2 per call repeats mode 2 exactly and the switched
  mode 4 equals a controller created in mode 4. Mode 4 has mode 2's values and cursors on
  every root (on these six roots the two networks agree, so the decisions are equal too).
- The browser's `deploy/qualify_compact.py` (TuppiBrowser `aa8a310`, fixture
  `compact-reference.json` `51c5fc19…`, from published WASM) passes on this controller with
  the three-network directory: 9 roots, phases {0, 1, 3, 4, 5, 6}, max value error 0.0,
  no PyTorch.
- Mutation checks: a `policy_model()` that ignores role 2 fails the anchor and lite parity
  tests; a changed mode-2 likelihood temperature fails both bit-identity tests. The
  `12a1a1f` library (role 2 as the mode-4 likelihood) fails the anchor-only test (values
  differ at the first play root) and the refusal test (mode 4 accepted without role 1).

## Tests

`PYTHONPATH=<this tree>:<TuppiProject>/src TUPPI_NATIVE_LIBRARY=native/libtuppi.dylib nice -n 10 python -m pytest -q tests`:
85 passed in 117 s on 23 October after the anchor-only change (72 existing, unchanged, also
72 passed on the `b30763c` baseline; 13 new in `tests/test_heidi12.py`). New tests, with
`tests/tb_controller.py` as their subprocess harness:

- V4 lite export equals the checkpoint bitwise (native forward); `shared_mlp` caches one
  network per file; `LiteAgent(model=...)`.
- `LiteAgent(model=MODEL_V4).greedy_action` equals the Torch model's masked argmax on 2,000
  observations from native self-play rollouts (bids and play): 0 differences (native and
  Torch logits differ by at most about 1e-5).
- Native mode 3 equals Python `LiteAgent(C1H, MODEL_V4)` and mode 1 equals `LiteAgent(C1H)`
  move for move and cursor for cursor on engine deals (339 and 226 decisions), no PyTorch.
- Missing roles are refused (load role 3; configure with role 0 only; mode 3 without role 2;
  modes 0-2 without role 1; mode 4 without role 1 or role 2; per-mode gates of inference,
  bids, net context).
- Anchor-only bids: mode 4 returns role 2's argmax and mode 2 role 1's on 16 roots (4 of them
  tell the networks apart), with no RNG draw.
- Mode 4 is mode 2 with role 2 as the anchor only (above, Verification).
- Mode 3 on roles {0, 2}: bids and the first four tricks are role 2's argmax; a rebuilt
  controller with the prefix replayed and all cursors restored finishes 4 deals exactly;
  mode 1 likewise on role 1.
- The compact directory and the V4 lite file equal fresh exports; two-network manifests and
  modes other than 2 and 4 are refused.

## Deviations from the contract

- `tools/export_lite_model.py`: `--model` without `--out` is refused (the research version
  wrote that checkpoint over the product `vrpo3_final.lite.npz`); `--check` works with both.
- `model_identity` refuses the old two-network directory instead of accepting it, so a
  package missing `vrpo4_final.f32` fails at start-up rather than at the first Heidi 1.2 move.
- `tb_choose` / `tb_choose_observation` also return -1 when the current mode's network is
  missing (new guard; unreachable with the old loading rules).
