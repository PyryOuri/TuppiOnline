# Five supported cards RAMI study at 0-0

Fixed before the first substantive result, 2026-10-04. Research authorized by
the owner's request; implementation is confined to this new output directory.

## Confirmed definition

For suit length L, a card with ordinary rank r (A=14, K=13, Q=12, J=11)
qualifies when L-1 >= 14-r. Any other card of that suit, including a higher
one, counts as a leg. The same support may qualify several cards. Count at
least five qualifying cards in at least three suits that contain qualifying
cards. AK=2; KQx=2; Qxx=1; AKQJ=4. These are prospective winners, not five
guaranteed tricks. The owner's answer confirmed this exact interpretation.

## Estimands and comparisons

1. Agreement: VRPO3 greedy policy versus the condition, on 8,192 independently
   shuffled deals, four blind shadow bid positions each, score 0-0. Report
   conditional RAMI agreement on qualifying hands separately from overall
   agreement. No earlier shown bid is visible to the evaluated policy.
2. Actual bidding cost: 2,048 independent base deals, four hand rotations,
   both tested partnerships, three arms: VRPO3 baseline; force RAMI when the
   condition qualifies and otherwise retain VRPO3; RAMI iff condition qualifies
   (this last arm is a separate interpretation, not assumed to be the owner's
   intended complete bidding strategy). All card play is identical VRPO3;
   within a chosen contract use VRPO3's highest-logit legal shown card.
   Native engine, project_target_v3, 0-0; policy-only sooli fallback declines
   offers as the repository's PolicyAgent wrapper does. Eight paired duplicate
   legs per base deal, 24 played games per base deal. Confidence intervals are
   over independent base-deal mean differences, not individual rotations.
3. Current best search: stratified shadow bid sample, equally split across
   four positions and qualified/unqualified hands. W128 initial comparison
   (256 bids); W1024 confirmation (128 bids) with nested samples. Current
   best configuration including VRPO1 strong-opponent/team rollouts, VRPO3
   anchor, card margin .003, bid margin .03, showing sampler fix, exact six
   trick tail and adaptive bids at W1024. Observation-based reseeding.
   Record selected bid and all searched action values. Reset history-sensitive
   sooli rollout state to fresh-deal defaults for each isolated bid. Search
   values are model estimates, not actual match outcomes or optimality proofs.
   Because samples are stratified, do not report their raw overall RAMI or
   agreement rates as population rates. Standardize by population strata.

## Evidence boundaries and validation

Seeds are fixed in study.py. No training, deployments, source modifications,
or changes to running servers. Check source/model/native hashes before/after.
Authoritative-engine differential check: 24 complete v3 deals, every actor,
legal set, observation encoding and final result; check native/PyTorch policy
choices. This passed 1,349 actions with zero choice disagreements before
the substantive simulations. Actual fast-policy outcomes and current-search
valuation will be clearly distinguished. Match equity uses the repository's
incumbent-derived continuation table, not newly simulated complete matches.

## Follow-up fixed after the initial screen

The initial fast-policy result and W1024 pilot (128 stratified bids) showed
substantial disagreements and too few observations to describe exactly-five
hands reliably. Increase W1024 to 1,024 stratified bids using the same frozen
sample order; do not change the rule or seed. Preserve the 128-bid pilot.
Also branch every qualifying shadow hand in the 8,192-deal bid sample into
RAMI versus NOLO, using each previous seat's VRPO3-preferred NOLO card and
VRPO3 continuation after the tested bid. Passing can lead to another RAMI.
These conditional outcomes are supplementary; report confidence intervals
clustered by original deal and distinguish them from the duplicate play test.
