# Phase 6 results

## Scope

Phase 5 is frozen as a completed negative classical-search programme. Phase 6
tests a shared learned policy without PIMC, UCT, ISMCTS, behavioural
importance weighting, or search integration.

Environment: Python 3.14.2, macOS 26.5.2, arm64; PyTorch 2.13.0 and NumPy
2.5.2 in the optional local environment. MPS was built in PyTorch but
unavailable, so training and inference used CPU. The actor was
`seat_relative_actor_gru_deepsets_v2` with 41,900 parameters.

The preserved research artifacts are outside Git under
`/Users/pyryouri/Developer/TuppiRuns/phase6`:

| artifact | canonical identity |
| --- | --- |
| imitation corpus | `dataset:sha256:7c30cf5a655f02a7fdf97f552f066e98b420001794c06a6c7bf2c8b0b1769ce5` |
| corrected checkpoint | `checkpoint:sha256:d5a4d94d2e5598d87b26d7083bb89847462e30fa5cf78e1a4acad5d82f9fb385` |
| checkpoint weight state | `06fb182aff3d6a3455b2f2959ebefbcc783afa001b8fdb8acbae36165f5c50fe` |
| learned candidate | `agent:sha256:f0c8fc1b785d71ac4a2c023b0403bdc9dce196bac29125136694fa6e256c0a75` |
| frozen opponent | `agent:sha256:d8b426f1263c7ce32bdef82e4971dc2e494950f155e15db9b69fc6334a2ac929` |

The corpus uses 32/8/8 disjoint train/validation/held-out streams under root
seed `phase6-imitation-v1` and a recorded 20-deal generation cap. The
corrected run used seed 6, 15 epochs, batch size 256, learning rate 0.001, and
CPU execution. These identities and settings are part of the evidence; the
rounded values below are descriptive summaries.

## Milestone A

The first corpus had 20,769/7,576/7,061 train/validation/held-out examples
from disjoint streams. The initial model reached 82.33% held-out agreement.
After the one permitted correction for omitted public contract/trick-history
features, the held-out result was:

| metric | result |
| --- | ---: |
| overall agreement | 85.27% |
| showing agreement | 84.70% |
| trick agreement | 85.30% |
| RAMI agreement | 88.28% |
| NOLO agreement | 76.26% |
| declarer agreement | 83.74% |
| defender agreement | 89.80% |

The frozen corrective checkpoint was evaluated in 32 new complementary pairs
against `partner_aware_v1`:

| W/T/L | p(win) | failures | censoring |
| --- | ---: | ---: | ---: |
| 0/1/31 | 0.015625 | 0 | 0 |

Mean `D_match` was -0.96875. The direct strength result is consistent with the
imitation failure and does not justify CTDE.

The comparison used root seed `phase6-bc-strength-v1`, 32 complementary
complete-match pairs, and development result class. Rebuilding all stored pair
records reproduced the inference and secondary metrics exactly. The first pair
was also replayed from the preserved checkpoint and current engine, reproducing
`pair:sha256:8708781a7eddc08bc3b415acd6ed87ebbd1872e8a5048a6e0964b9963d5c10b0`.

## Closeout validation

The interrupted repository closeout was completed against the preserved
artifacts. Validation established that:

- corpus line counts are 20,769/7,576/7,061 and match the manifest;
- all labels are legal actions and stream identities are disjoint across splits;
- the manifest identity rebuilds exactly from its recorded content;
- the manifest, checkpoint sidecar, and evaluation satisfy their checked-in
  JSON Schemas;
- the corrected checkpoint metadata, payload configuration, checkpoint identity,
  and tensor-state digest agree;
- fresh held-out inference reproduces every recorded aggregate and the 85.27%
  agreement exactly;
- all 32 stored pair identities, paired inference, and secondary metrics rebuild;
- one complete complementary pair freshly replays to the stored identity; and
- all 20 focused Phase 6/version tests pass with the documented NumPy/PyTorch
  versions; and
- the full repository regression suite passes with 1,439 passed and two
  data-dependent search skips; and
- the staged source builds as the `tuppi_research-0.11.0` wheel with the
  learning package, documentation, and schemas included.

The read-only audit can be repeated from the repository root with:

```bash
PYTHONPATH=src python tools/phase6_verify_artifacts.py \
  --artifact-root /Users/pyryouri/Developer/TuppiRuns/phase6 \
  --replay-first-pair
```

The full 32-pair evaluation was not rerun from scratch during closeout because
the stored pairs passed canonical identity reconstruction and exact statistical
recalculation. The fresh one-pair replay provides an execution-level bridge
between the preserved checkpoint, current engine, and stored evaluation.

## Decision

Selected outcome: **R4 — imitation itself fails**. The learned actor did not
reproduce the transparent reference after the one specifically justified
encoder correction. Milestone B was not run, in accordance with the explicit
conditional kill criterion; there are therefore no RL seeds or selected RL
checkpoints to report.

Project-level recommendation: **continue only if a genuinely new resource is
available**, such as substantial expert-labelled observations or a separately
justified representation/data source. Do not create another rescue subphase or
run an unbounded parameter sweep. The evidence from Phases 4–6 does not justify
claiming a reliably stronger AI from the current synthetic-policy-only path.

The sealed promotion bank remains unopened. Phase 4/search/belief layers remain
frozen research baselines. This was one synthetic-policy corpus, one corrected
training seed, and one 32-pair development comparison; it is neither an expert-
strength claim nor a general result about learned Tuppi policies.
