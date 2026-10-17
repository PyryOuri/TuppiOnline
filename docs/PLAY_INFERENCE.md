# Play inference (strength step 2, 2026-10-16)

The search's worlds have so far been drawn uniformly, subject only to the
hard facts: shown cards, played cards and voids. With play inference, the
search draws `mult` times more worlds and resamples them, systematically, by
the anchor policy's (VRPO3) likelihood of the other seats' past unforced
choices replayed in each world:

    prod_t [(1 - eps) * softmax(q_t / T)[a_t] + eps / k_t]

It applies only after the bidding and not in sooli play. It is set per
controller with `native.set_belief(env, ...)`, and it is off by default.

## Fixes found on the way (tests/test_history.py)

- **`tc_history_rows` used the wrong rules.** It replayed every deal under
  ruleset 1, so locked-bid (v3) bids were scored as if earlier bids had been
  visible.
- **It gave up on any deal with a sooli offer,** even a declined one, which
  is most RAMI deals.

## Gate: prediction of hidden cards

`tools/belief_gate.py` measures whether the weighting predicts card
locations better than uniform. Run on the owner's local replay games: 1,252
positions; NLL of each unseen card's true holder, paired against uniform
(about 0.97).

| Games | T2, eps 0.5, all other seats |
|---|---:|
| All-bot | −0.173 |
| A human among the observed seats | −0.128 |

Sharp weighting (eps 0.05) is worse than uniform, which matches the
September failures.

## W=128 screen against the live bot (pre-registered in 33c040a)

    PYTHONPATH=$PWD python -m tuppi_ai.evaluate --checkpoint "best:pib=4:pibt=2:pibe=0.5" \
        --opponent best --ruleset v3 --deals 1024 --workers 12 --seed belief-pib4-v1

**Result:** **+0.00505 [+0.00429, +0.00581] equity per deal**, over 1,024
base deals × 8 games. Detail:

- deal wins 54.5%;
- own declarations made 77.6%, against the live bot's 69.3%;
- 5,476 s on 12 workers, about 2.7 times the live bot's time per game (the
  belief step is single-threaded).

**Pass rule:** the point estimate is above 0, so the screen **passes**. The
W=1024 confirmation and a check against non-VRPO opponents are pending.

**Caveat:** the opponents are the bot itself, which the likelihood model
describes exactly. Against humans the model is approximate.

Run it from this worktree with `PYTHONPATH` set to it; the venv's editable
install otherwise imports the main TuppiAI checkout.

## W=1024 confirmation and robustness (2026-10-17)

**Memory.** A first 12-worker W=1024 run thrashed and was stopped. The
belief scored all 4,096 candidates at once, about 4 GB per worker. Since
`3aaa0d3` it scores them in batches of 256, the same draws and weights, at
about 0.9 GB per worker. The runs below used 10 workers.

- **W=1024 confirmation** (`best:w=1024:pib=4:pibt=2:pibe=0.5` against
  `best:w=1024`, 512 base deals, seed belief-pib4-w1024-v1): **+0.00695
  [+0.00586, +0.00804]**.
  - Deal wins 56.0%; own declarations made 75.9%, against the live bot's
    65.9%.
  - 18,097 s on 10 workers.
  - **Passes.**
- **Robustness against non-VRPO opponents** (the incumbent heuristic, W=128,
  1,024 base deals, seed belief-pib4-incumbent-v1):

  | Agent | Equity per deal against the incumbent |
  |---|---:|
  | With play inference | +0.02199 |
  | Live bot | +0.01935 |
  | **Paired difference** | **+0.00264 [+0.00183, +0.00345]** |

  The gain is smaller when the model does not describe the opponents, but it
  stays positive.

**Status:** this is a confirmed strength gain against bots, and robust
against non-VRPO opponents. Not yet in any product. The phone (WASM) timing
is untested.

## Cost (2026-10-17)

**Profile** (`tools/belief_profile.py`, one process, W=128, 3 deals): of
54 s, the belief's network pass took 36 s, single-threaded. Rollouts took 17 s,
and drawing and resampling well under 1 s. Per search, scoring the 512
candidates (about 14 history rows each) cost more CPU than rolling out the
128 worlds.

**Two exact changes:**

1. **Parallel scoring.** Candidates are drawn in order, then scored in fixed
   blocks of 32 on several threads (`tc_set_belief_lanes`, default all
   cores).
2. **Each distinct world played out once.** In trick play the rollouts are
   deterministic in their world (greedy moves, exact solver tail, no sooli
   left), so a world drawn n times is rolled out once and counted n times. A
   median of about 66 of the 128 resampled worlds is distinct. At a sooli
   offer, every copy is still played out.

**Exactness:** on 30 positions the worlds, values and per-world values are
bit-identical to `8a918a6`, and so are the game results of the profiled
deals. The worlds are the same at any thread count.
`test_repeated_worlds_are_played_out_once_with_the_same_values` covers the
deduplication.

**Wall time per deal for one game process** (8 games):

| Level | Live bot | Before | Now |
|---|---:|---:|---:|
| W=128 (3 deals) | 17.9 s | 53.9 s (3.0×) | 27.5 s (1.5×) |
| W=1024 (1 deal) | 19.3 s | 102.2 s (5.3×) | 33.4 s (1.7×) |

**CPU** rises when all cores score, because they contend for the matrix
units. At W=1024, 10 positions:

| Lanes | Wall | CPU |
|---:|---:|---:|
| 1 | 6.6 s | 7.6 s |
| 2 | 3.5 s | 6.9 s |
| 8 | 1.8 s | 10.8 s |
| all | 1.2 s | 15.3 s |

Two lanes cost no more CPU than one, so `evaluate.py` uses 2 (its processes
already fill the machine), and live play uses all cores for latency.
Deduplication saves about 27% of a belief search's rollout CPU.

**Update (later on 2026-10-17): deduplication is off.**
- In 12-process evaluations it made each worker's memory grow by about
  90 MB a minute. A T=1 tuning run reached about 60 GB in total and ran the
  Mac out of memory.
- The growth disappears with deduplication off, at about 0.6 GB per worker,
  flat, and also with the library from before this change. The cause is not
  found.
- It saved only about 9% of CPU and no wall time, so it is disabled
  (`dedup_worlds = 0` in `tuppi_env.c`). Parallel scoring stays.
- Results are unchanged either way: the search values are exact with or
  without it.

**W=128 screen rerun** (same command): **+0.00494 [+0.00415, +0.00573]**,
against +0.00505 before, so the strength is the same. It took 5,242 s against
5,476 s, so a full machine gains little: a saturated 12-worker run has no
spare cores, and that run used all lanes. The per-deal values differ between
the two runs because each worker's seeded random state carries over from
deal to deal and the deals are spread over workers in arrival order.
`runs/belief/screen-pib4-w128-fast.json`.

## Tuning (2026-10-17)

- **8 candidates per world against 4** (`best:pib=8` against `best:pib=4`,
  W=128, 1,024 base deals, seed belief-tune-pib8-v1): **+0.00113 [+0.00048,
  +0.00178]**. More candidates help. The scoring cost doubles.
- **T=1 against T=2** (`best:pib=4:pibt=1` against `best:pib=4:pibt=2`, W=128,
  1,024 base deals, seed belief-tune-t1-v1): **-0.00081 [-0.00152, -0.00010]**.
  Sharper weighting is worse, so T=2 stays. Memory stayed flat at about
  6.5–6.9 GB for 12 workers (7,062 s).
- **Memory, continued:** at W=1024 the worker memory still grew without
  deduplication, and with the older library too, at up to 70 MB a minute per
  worker. The cause is each worker spreading its searches over all cores
  while 10–12 workers compete. With one thread per worker it is flat at
  about 0.3 GB, so `evaluate.py` now runs workers single-threaded
  (`TUPPI_AI_SERIAL=0` restores the old mode). The moves are the same.
- **Next:** confirm `pib=8` at W=1024 before any product use.

