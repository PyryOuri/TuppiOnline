# Calibration and evaluation protocol

Phase 5G-B uses independent synthetic streams for development, calibration, and
held-out testing. A stream root and stream index occur in exactly one split.
Synthetic actors use frozen observation-only Phase 4 policies; full hands and
the generating policy are private offline labels only.

The initial registered diagnostic uses one global epsilon of 0.10 and equal
mixture weights. These values are frozen before held-out evaluation; there is no
held-out tuning. The report includes owner NLL, Brier score, mean probability
assigned to the true owner, top-owner accuracy, entropy, ESS, zero-weight counts,
and reliability bins. NLL and Brier remain primary because top-owner recovery
alone hides overconfidence.

Matched-policy experiments ask whether the correct frozen policy can recover
information in known-policy games. Misspecified experiments ask how badly a
wrong policy can concentrate belief. The robust mixture is compared with the
hard-uniform prior and both single-policy controls. Showing-only, trick-only,
partner-only, and opponent-only ablations are descriptive and are not used to
retune the primary model.

Tiny late-game positions use the independent card-by-card enumerator in
`exact_reference.py`; the production sampler and posterior are not used to
generate the exact reference. Finite candidate results are reported as
approximations and are not described as exact posteriors.
