# Human RAMI threshold: blind borderline-hand session

The purpose is to describe when a human bids RAMI at 0-0, compared with a
frozen strong bot's estimates. This is a behavioural measurement, not a
right/wrong examination or a playing-strength result.

## Deal construction

Generate fresh deterministic uniform full 52-card shuffles under v3 rules.
Select hands using only the bidding player's observation and sampled hidden
worlds; the actual partner/opponent hands must not decide inclusion. Retain
the complete shuffled deck for reproducibility and optional later branches.
Use no source deal from the existing pilot or current research experiment.
Vary suit lengths, high-card structure and supported-card counts; include
hands on both sides of the five-supported-card idea rather than teaching that
rule before measuring it.

The bank contains 40 distinct deal families, ten per bidding position. Per
position: two hands in each of four close bands (RAMI minus NOLO value
-0.010 to -0.003, -0.003 to 0, 0 to 0.003, 0.003 to 0.010), plus one
negative and one positive shoulder (-0.030 to -0.010, 0.010 to 0.030).
Thus 32 close calls plus eight reference hands. These bounds use repository
match-equity units, not raw points or literal measured match-win chances.
Final selection will use independent common-world confirmation estimates;
record uncertainty and do not present estimated signs as exact truth.

Screen a bounded reproducible candidate pool with the current best search at
W128. Confirm candidate shown cards with W1024 current best search, then price
fixed legal RAMI/NOLO representatives using 4,096 independent common worlds.
The final two representatives are selected before those confirmation worlds.
Freeze bot modules, models, native library, configuration, seeds and complete
selection ledger. Earlier NOLO bids are neither exposed nor supplied to the
human; the bot's adapter evaluates the bid conditional on reaching that seat.

## App session

Add a separate RAMI-threshold mode to the isolated training client. Load the
bank locally, randomize and persist its order, and show only the player's own
13 cards, seat and 0-0 score. The player chooses RAMI or NOLO; the shown card
is standardized by the prepared reference. Save the immutable initial choice,
confidence, optional reason and elapsed time. Pause/resume preserves order.
No odds, branch play, answer editing, bot choice or reference values appear
until all forty decisions are committed. Protect a paused session as well.

At completion show RAMI proportions by reference band, seat and supported
card count, agreement with the current bot, and an exploratory 50% choice
threshold when response variation supports fitting it. Keep fresh first
responses separate from familiar repeats. Exclude this mode from learning
error/accuracy statistics and the existing adjudicated forty-task assessment.
Do not call disagreement a human error. Export through the existing archive
export; a dedicated analysis tool will also produce a self-contained report.

## Verification and delivery

Check 52 unique cards/13 per seat, exact engine observations, all legal show
options, blind bids, 0-0, family uniqueness, quota counts and source hashes.
Add focused app tests for delayed feedback, immutable answers, assistance
blocking, persistence, completeness and threshold reporting. Run the existing
training tests, build a separate updated preview, and verify its packaged bank.
Preserve existing preview, live app, running servers and concurrent research.
The final handoff includes the bank, generation/selection ledger, protocol,
validation report and launch instructions. No human answers are fabricated.
