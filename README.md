# TuppiAI

A strength-first Tuppi bot, built beside TuppiProject rather than inside it.
TuppiProject's `tuppi_rules` / `tuppi_engine` stay the authoritative reference;
everything here is either a fast re-implementation differential-tested against
them, or a player that talks to them only through `PlayerObservation`.

## Current best agent

`search:runs/bc_small.pt:w=128:dd=6:show=1` - at every decision (showing and
card play), 128 hidden-hand layouts are drawn uniformly from those consistent
with the seat's observation, every legal action is played out in each by a
behaviour clone of `partner_aware_lead_v2`, the last 6 tricks are solved
exactly, and the action with the best mean match-equity change is chosen.
Against the incumbent: +0.0150 equity per deal over 512 fresh base deals
(+0.0013 +- 0.0011 over 64 worlds on the same deals). The match figures were
measured with 64 worlds: 94.5% of complete matches (228 won / 28 tied / 0 lost
over 256 duplicate pairs on two seeds).
The search runs in C (`native/tuppi_env.c: tc_search_values`, network forward
in `native/tuppi_mlp.c`); a decision takes ~13 ms (card play, median) to ~36 ms
(showing) using all cores. See
`docs/STATUS.md` for every result, including what failed.

## Layout

| Path | What |
| --- | --- |
| `native/tuppi_core.c` | Rules, deal state machine, scoring, match transition, observation-only feature encoder (1223 binary features) |
| `native/tuppi_env.c` | Batched self-play environment (N matches in lockstep, per-deal match-equity reward) |
| `native/tuppi_search.c` | Exactly uniform sampler of hidden hands under hard public constraints |
| `native/tuppi_dd.c` | Perfect-information solver for late positions (RAMI and NOLO polarity) |
| `native/tuppi_mlp.c` | Native forward pass of the rollout network (Accelerate) |
| `tuppi_ai/bridge.py` | `PlayerObservation` -> native observation; action ids <-> engine actions |
| `tuppi_ai/equity.py` | Rising-score match equity (same model as `tuppi_valuation.equity`) |
| `tuppi_ai/train.py` | Deep Monte Carlo self-play (DouZero-style), one shared Q-network |
| `tuppi_ai/agent.py` | The learned policy as an engine agent |
| `tuppi_ai/search.py` | Determinized rollout search over the learned policy, optional solver tail |
| `tuppi_ai/evaluate.py` | Per-deal duplicate evaluation vs `partner_aware_lead_v2` in the authoritative engine |
| `tuppi_ai/match_eval.py` | Complete-match duplicate evaluation (match win probability) |
| `tests/` | Differential, sampler and solver tests |

## Setup

```sh
python3.14 -m venv ~/.venvs/tuppi-ai
~/.venvs/tuppi-ai/bin/pip install numpy torch pytest
# make TuppiProject's packages and this repo importable (no install into either repo)
SP=$(~/.venvs/tuppi-ai/bin/python -c "import site; print(site.getsitepackages()[0])")
echo /Users/pyryouri/Developer/TuppiProject/src > "$SP/tuppi_project_src.pth"
echo /Users/pyryouri/Developer/TuppiAI > "$SP/tuppi_ai_src.pth"
native/build.sh
~/.venvs/tuppi-ai/bin/python -m pytest -q
```

## Common commands

```sh
PY=~/.venvs/tuppi-ai/bin/python
$PY tools/fit_equity.py --deals 20000                      # equity table from incumbent self-play
$PY -m tuppi_ai.train --name dmc1 --hours 4                  # self-play training (MPS)
$PY tools/watch_eval.py --run dmc1                           # score each checkpoint vs the incumbent
$PY -m tuppi_ai.evaluate --checkpoint runs/dmc1/latest.pt --deals 2000
$PY -m tuppi_ai.evaluate --checkpoint "search:runs/dmc1/latest.pt:w=32:dd=6" --deals 256
$PY -m tuppi_ai.match_eval --checkpoint runs/dmc1/latest.pt --pairs 256
```

## Evaluation endpoint

Per base deal: 4 rotations x 2 team assignments against the incumbent, dealer
0, the candidate team's match-equity change averaged over the 8 games. The
incumbent against itself scores exactly 0; `partner_aware_v1` scores
-0.0054 [-0.0066, -0.0043] over 1024 base deals, reproducing TuppiProject's
T4/T5 control margin (+0.0057..+0.0064). The complete-match evaluator scores
identical teams at exactly 0.5.
