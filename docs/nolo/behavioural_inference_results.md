# Results: behavioural inference for the training overlay

Answers `docs/nolo/behavioural_inference_hypotheses.md`. That document is
pre-registered and stays as written; corrections to it are recorded here.

## What shipped

Both candidate rules ship, as a labelled layer beside the hard facts, off by
default. One of them only after its statement was corrected.

| rule | firings | excluded a card actually held | verdict |
| --- | ---: | ---: | --- |
| `duck_high` | 158 | 0 (0.0%) | sound |
| `win_high`, every follower | 371 | 206 (**55.5%**) | **unsound — rejected** |
| `win_high_last`, fourth seat only | 348 | 0 (0.00%) | sound |

Median cards excluded per firing: 3 for `win_high_last` (max 10), so it is the
more informative of the two.

## The correction, and why it matters

`win_high` was first tested against *every* follower who beat the current high.
It failed at 55.5% and was rejected. That rejection was wrong, and the fault was
in the test rather than the rule: the proposal had always been stated for the
**last player**, and the test did not condition on it.

Splitting by seat position shows two opposite behaviours that the pooled number
had averaged into noise:

| seat | decisions with ≥2 winning options | played highest | played lowest |
| --- | ---: | ---: | ---: |
| fourth (win already certain) | 7 | **100%** | 0% |
| second or third (can still be overtaken) | 17 | 23.5% | **76.5%** |

The reason is strategic, and it is specific to NOLO. A seat that can still be
overtaken and is forced to beat the current high plays its **lowest** winner,
because playing high would *maximise* the chance of actually taking the trick —
the one outcome it is trying to avoid. It would rather a later hand took it.
Only in fourth seat is the trick already lost to that seat, and only there does
shedding the highest card become the obvious play.

So the underlying idea — a high card is pure liability in NOLO, get rid of the
worst one you safely can — is correct, and it generates *both* shipped rules.
What changes with seat position is which card is the worst one you can safely
shed.

Sample sizes for the seat split are small (7 and 17). The soundness test that
gates shipping is the 348-firing one, and that is what the rule rests on.

## Method note

The pre-registration specified a corpus-based measurement with two profiles, two
seeds and a cluster bootstrap. That was over-scoped for the decision actually
being made. What gates a display layer is not a population parameter with a
confidence interval; it is whether an exclusion ever deletes a card the opponent
really held, which is answerable exactly, in one pass, against the true hands.

That check now lives in `tests/server/test_training_analysis.py` rather than in a
report, so it runs on every commit and cannot silently regress. The heavier
protocol remains the right standard for a claim that changes how the bot plays,
which this is not.

## Standing limitation

Unchanged from the pre-registration §7, and it is the reason the layer is a
toggle rather than the default. These rates describe a **deterministic
program**. A rule that matches it 348 times out of 348 has been reverse
engineered, not discovered: `docs/valuation/handoff.md` §3.2 is the warning that
inference fitted on this corpus is measuring a constant.

Both rules do have a strategic argument behind them that should survive a human
opponent, which is more than the rejected order-statistic reads of §3.1 ever
had. But nothing here establishes that a human plays this way, and the overlay
is therefore built to show what the assumption costs rather than to hide it
inside a single number.
