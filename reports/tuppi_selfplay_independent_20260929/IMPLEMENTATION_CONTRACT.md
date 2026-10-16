# Learner implementation contract

## Primary-paper check

Verified [Fan & Farina, arXiv:2605.19235v1](https://arxiv.org/html/2605.19235v1),
§§3.2–4.2, equations 3.2–3.3. Q-boosting includes accumulated Expected-SARSA
residuals; Q minus its policy expectation alone is insufficient. The reference
implements that recurrence. The paper keeps actors on fresh trajectories and
permits critic-only replay. During actor optimisation it refreshes policy
expectations with current probabilities while freezing critic values and
detaching advantages. Its lambda=1 score-function result does not certify
clipped, repeatedly updated PPO or arbitrary off-policy replay. The DouDizhu
comparison matches approximate timesteps, not measured end-to-end compute:
about 2.65 billion steps and 55 hours on four RTX 5090s. Poker performance is
explicitly described as not a decisive win. These are reasons to test the
proposal locally, not forecasts of Tuppi strength.

## Fixed perspective and temporal units — local adapter requirements

Store all critic values and rewards in Team-0 perspective. Compute the full
temporal trace first; change sign only for the actor loss on Team-1 seats.
The expectation at the next row uses that row's actual acting-seat policy,
including opposing seats, not the policy of the seat that began the trace.
Seat parity identifies the fixed partnership; sooli does not change it.

Keep every intervening transition, including forced actions and sooli handling.
Exclude frozen-controller actions from actor updates but retain their effects
and correct continuation expectations in the critic trace. Do not concatenate
only one seat's turns and pretend a skipped interval was one ordinary step.

For complete-match training, a completed nonterminal deal is not a terminal.
Represent chance dealing explicitly or account for its expectation. The exact
pathwise residual check here uses deterministic within-deal transitions; an
unresolved random deal introduces additional chance noise. True match terminal
has zero bootstrap. A memory/time truncation retains a valid bootstrap and cuts
the sampled trace; a fresh match must never inherit the preceding match's trace.

## Real action-space issue discovered

The packet proposes a 156-output actor/Q head. Native v3 has 210 action IDs:
0–155 ordinary plays/bids; 156–157 sooli decisions; 158–209 exchanges. Sooli
card-play IDs reuse 0–51 but have different phase semantics. The reference
collector handles all 210; this is a diagnostic interface, not an architecture
decision. An unmodified 156-head learner cannot optimise all v3 decisions.

Choose explicitly between a frozen observation-local sooli controller and an
extended/phase-specific learned action head. For the frozen option, either
represent its decisions in the trace with its actual policy or define a
documented macro-transition with correctly aggregated rewards/discount. Do not
silently drop sooli episodes or mark an offer as terminal. Keep the SP1 control's
sooli treatment fixed when attributing an algorithmic effect.

## Actor/critic boundary

Actor entry point accepts only an engine `PlayerObservation` projection and
its legal mask. Critic input is separate, containing pre-action full state and
relevant history. Future realised actions or outcomes are targets, not critic
inputs: the packet's broad allowance of future-event information must not be
interpreted as permission for a baseline to depend on future realised actions.
No critic tensor, privileged latent or hidden-state ID enters actor forward.

The bidding hidden-hand swap check validates a narrow actual encoding property.
It does not prove neural-module isolation. Before training, add forward-hook
inspection and same-observation/different-truth tests across play and exchange
to the eventual tensor implementation. Retain an actor-only export test.

## Data and update contract

Persist parent match/deal identity before branching or augmentation, split ID,
row order, actor seat, ruleset, phase, legal mask, selected action, sampled
behaviour probabilities/logp, behaviour policy hash, critic snapshot hash,
reward perspective/scale, terminal/truncated flags, and complete simulator/
adapter identity. Assign whole matches to splits for match training. Replayed
critic data must retain its generating-policy identity. Actor batches must
reject mixed old-policy versions unless a separately specified correction is
implemented; actor replay is not the reference algorithm.

Current-policy expectation refresh needs successor rows for the entire trace,
including other seats. Arbitrarily shuffled independent decision minibatches
are insufficient to recompute the recurrence without cached ordered trajectory
information. Keep sampled old log probabilities fixed throughout actor epochs.
Detach target/advantage tensors. Do not update the critic halfway through an
actor epoch while still describing its values as frozen.

The present module has no autodiff, actor network, critic network, optimiser,
checkpoint loading, replay trainer or neural-policy rollout. Those interfaces
are the next milestone, not implied by the correctness pass.

## Reward alignment correction

Do not combine a terminal reward and a learned potential difference without
specifying terminal potential. For an undiscounted full match, a consistent
choice is base terminal win/loss plus Phi(next) − Phi(current), setting terminal
Phi=0 and holding the potential snapshot fixed within the rollout. The shaped
sum then equals base return minus initial Phi. If instead terminal Phi is set
to the terminal result, adding the same result as a base reward double-counts
it. Artificially cut deals require a bootstrap, not an invented terminal label.
Neither convention is implemented as a learned match-value model here.

## Integration gates remaining

1. Tensor outputs/gradients match numerical reference; legal masking includes
   negative-advantage clipping and zero-probability edge cases.
2. Full real-engine trajectory provenance, on-policy sampling and parent splits.
3. Explicit sooli boundary and phase coverage, including successful sooli.
4. Real consecutive deals/matches with terminal/truncation separation.
5. Actor-only export and full-state critic isolation.
6. Tiny CPU neural update with finite losses and checkpoint roundtrip, then
   compute measurement. No strength conclusion from that smoke update.
7. Independent seed/evaluation protocols before comparison with SP1.
