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
