# External architecture review

**Provenance.** Written by an external reasoning model with **no access to this
repository**, in response to `nn_architecture_prompt.md` and
`nn_architecture_brief.md`. Received 2026-09-08. Reproduced verbatim below; the
text is unedited.

**Status: not yet acted on.** Nothing in this document has been implemented or
adopted. Several of its claims are checkable against the repository, and
`nn_architecture_review_checks.md` records which of them were checked and what
was found — read that alongside this.

---

Recommendation
Start with a learned, tightly restricted showing override—not a belief network, not a general value network, and not another replacement policy.
The first candidate should decide whether to replace the frozen reference’s first showing action, then leave every subsequent decision to the reference. Train it on the measured value of that intervention, using continuations executed by observation-only policies.
This isolates the proposed improvement from the three largest confounders: compounding learned decisions, a partner whose behaviour differs from the assumed continuation, and policy-dependent inference from earlier actions. Only after this candidate passes should you fund a card-play model.
I would not generate the 10M-deal corpus yet. The valuable new resource is the ability to generate controlled counterfactuals—not the number of terminal-return-labelled decision rows.
1. The cloning failure: what probably happened, and what must be measured
The agreement number conceals several different errors
An action-agreement objective treats all of these identically:
Playing a different card that produces the same outcome.
Choosing a different shown card while declaring the same contract.
Making an expensive declaration error.
Mishandling a partnership situation that changes several subsequent tricks.
Those are not comparable mistakes. Your own runner-up experiment demonstrates that many substitutions have no effect under the measured continuation. Conversely, the scoring rules permit a relatively small number of declaration or boundary errors to have large consequences.
There is also substantial forced-action inflation. If the clone’s test set had the same 21.2% forced-action share as the later corpus, its agreement on genuine choices would have been approximately
$$ \frac{0.8527-0.212}{1-0.212}=81.3\%. $$
That is nearly one disagreement in five genuine choices—not one in seven.
Under the same distributional assumption, a partnership controlling half the decisions would make approximately four disagreements per deal, or 100 per average match. These are illustrative exposure counts, not a causal explanation of the reported match result. The old test-set forced-action rate and deployed disagreement rate are missing.
Do not calculate \(0.85^{1350}\) and call that the explanation. Only half the actions belong to the candidate partnership; errors are dependent; many disagreements are harmless; and match length itself changes with policy.
My leading diagnosis
My working explanation is:
The clone made some costly errors in the less accurately imitated branches, particularly NOLO and showing; those errors changed subsequent observations and partner interactions, producing further errors outside the supervised training distribution. The rising-score rule then converted that altered deal-outcome distribution into a severe match disadvantage.
This is a concrete mechanism, but its components are hypotheses, not established findings.
The distribution-shift component is precisely the issue that motivates DAgger: an imitation learner changes the distribution of observations on which it must subsequently act. High agreement on reference-generated observations does not control its error on its own trajectories.
Your result does not establish that the GRU was too small, that DeepSets was unsuitable, or that beliefs were missing. Nor does the match-level power warning erase the result: the observed match disadvantage deserves explanation. What remains unidentified is where the damage occurred and how much was already present at the single-decision level.
The diagnostic that distinguishes these explanations
Before training anything, measure four quantities on paired deals:
Quantity    What it distinguishes
Single-deviation loss: clone action versus reference action, followed by reference continuation in both branches    Whether disagreements are intrinsically expensive
The same measurement on clone-reached observations, versus reference-reached observations    Whether distribution shift increases decision damage
Showing-only clone and play-only clone    Whether most damage originates in contract selection or card play
Partnership factorial: reference/reference, clone/reference, reference/clone, clone/clone    Whether deploying two approximations introduces an additional coordination penalty
For showing, separate contract agreement from exact shown-card agreement. For play, separate NOLO/RAMI and lead/follow/discard. Report the concentration of loss: for example, how much of total measured damage comes from the worst decile of disagreements.
The single-deviation experiment must use the same hidden deal in both branches, with every continuation agent receiving only its own formal observation. It measures the consequence of an intervention; it does not give the deployed policy hidden information.
These measurements lead to different conclusions:
Large losses from isolated substitutions favour a cost-sensitive objective.
Much greater losses on clone-reached observations favour on-policy data collection.
A large additional clone/clone penalty requires continuation and partner alignment.
Little per-deal damage but a large match deficit requires investigation of score-state weighting and the endpoint, not more imitation training.
My proposed architecture addresses all three policy mechanisms by construction in its first experiment. It changes at most one decision, evaluates that decision by its consequence, and preserves the partner and subsequent continuation exactly.
The objective should be expected consequence—not agreement or “which branch won”
For an observation \(o\), reference action \(b(o)\), alternative action \(a\), and specified continuation profile \(C\), the relevant quantity is
$$ A_C(o,a) = \mathbb E\!\left[ U(Y_a)-U(Y_{b(o)}) \mid o,\ C \right]. $$
Here \(Y\) is the completed deal outcome and \(U\) is a preregistered utility.
This is a cost-sensitive policy-improvement objective. The methodological distinction between imitating an action and using its cost-to-go is the central point of AggreVaTe. Its guarantees should not simply be imported into this partnership game, but the distinction is directly applicable.
DAgger alone would address observation-distribution shift while retaining the reference’s action choices as the target. I would not run a DAgger rescue of the old clone. I would use candidate-generated observations later, but label them with intervention values rather than merely corrective reference actions.
Resolve the utility before selecting a model
If the ultimate objective is winning matches, signed deal points are a surrogate, not the authoritative utility. At 48–0, awarding additional value to a larger winning margin is explicitly wrong.
I recommend per-deal frozen-continuation match equity as the primary endpoint, with signed points, tricks and deal-win rate as diagnostic endpoints.
This need not require complete-match rollouts. Subject to confirming independent fresh deals and no additional cross-deal policy state, the reference continuation has only:
25 nonterminal score configurations: 0–0 and twelve positive scores for either team;
four dealer positions.
That is 100 nonterminal deal-boundary states, not a neural-network problem.
Estimate the reference’s deal-outcome transition probabilities and solve the resulting absorbing Markov chain for \(V_B(s,d)\), the reference-continuation probability that a specified team eventually wins. Then value a completed deal by
$$ U(Y;s,d)=V_B\!\left(T(s,d,Y)\right), $$
with terminal states assigned 0 or 1. A paired action label is the difference between the two resulting continuation values.
This retains a per-deal endpoint, accounts for resets and overshoot, and avoids crediting one terminal bit across 1,350 decisions. It is not the same as measuring the complete candidate’s eventual match-win probability: it explicitly values the deal under a common frozen future continuation.
First establish what “equity” in Part 4 already means. Reuse it only if its definition supports this interpretation. Do not switch between points and equity after seeing which produces significance.
2. Recommended decomposition
First challenge: the reported 3.3× ceiling is not a learnable ceiling
Part 4 does not establish that a legal learned policy has 3.3× the reference’s attainable value.
For a binary intervention, let \(\Delta\) be its realised gain over the reference on the hidden deal. The observation-compatible opportunity is
$$ G_{\mathrm{legal}} = \mathbb E_o\!\left[ \max\{0,\mathbb E[\Delta\mid o]\} \right]. $$
A branch oracle observing the hidden layout obtains
$$ G_{\mathrm{foresight}} = \mathbb E[\max\{0,\Delta\}]. $$
In general,
$$ G_{\mathrm{legal}}\le G_{\mathrm{foresight}}, $$
and the gap can be arbitrarily large.
For illustration, suppose \(\Delta=-1+\epsilon\), where \(\epsilon\) is independently either −20 or +20. Every pair changes the outcome. Foresight finds profitable overrides in half the cases. No observation-only learner should ever override.
Accordingly:
The low descriptor \(R^2\) does not distinguish missing observable structure from irreducible hidden-layout variation. Nor does one eight-descriptor regression establish a ceiling for every nonlinear function of those descriptors.
Likewise, the highly significant mean forced-contract difference establishes an average treatment effect, not useful input-dependent treatment selection. An always-pass policy can exploit a negative average without learning anything.
The first substantive experiment must therefore measure observation-compatible headroom.
Initial deployment: one neural model plus the unchanged reference
Model S: showing intervention advantage
Scope: initially, the forehand’s first showing decision at the preregistered starting score, preferably 0–0.
Input: the formal observation.
Output: expected utility gain from one precisely defined alternative showing action over the reference’s actual showing action.
Composition: take the alternative only when the predicted advantage exceeds a validation-selected, subsequently frozen threshold. Otherwise execute the reference action. Every later showing and card-play action remains reference-controlled.
The alternative must be a complete legal action, not just “RAMI” or “NOLO”. For example:
Preserve the reference’s actual action as the baseline.
For the other declaration, use a fixed legal-card selector, such as lowest eligible rank with ties broken by the engine’s legal-action order.
That is a comparison between two executable policies. It includes the effect of revealing different cards; it is not falsely presented as an isolated contract effect.
A forehand NOLO declaration must allow later players to declare RAMI. “Force this player to say NOLO” and “force the final contract to be NOLO” are different interventions. The existing forced-contract corpus cannot be assumed suitable until that distinction is resolved.
Why this is an unusually clean first model
At the first showing decision:
There is no earlier action sequence to invert.
The model cannot have changed the distribution of its own input.
Only one learned intervention occurs.
The actual partner is the partner used in the labels.
Conditional hidden deals can be generated without conditioning on behavioural history.
It is also possible to evaluate this policy from held-out paired outcomes without inserting the network into a rollout loop: the network selects one of two already executed branches.
Later deployment: a separate card-play advantage model
Model P: legal-action residual scorer
Only after Model S passes, train a card-play scorer for
$$ A_B(o,a)=Q_B(o,a)-Q_B(o,b(o)), \qquad A_B(o,b(o))=0. $$
The network should score only actual members of the legal tuple. Anchor the reference action’s advantage to zero exactly.
Initially, permit one intervention at a predetermined observation-identifiable decision per deal, not replacement of all card play. A concrete scope is the forehand’s first nonforced play; whether an earlier own play was forced can be reconstructed from the current hand and public history.
Only later consider repeated overrides, using a predefined candidate-on-policy collection phase and continuations matching the deployed partnership.
I would keep showing and play parameters separate. Their target distributions, eligible histories and decision semantics differ, and there is no current evidence that joint optimisation would improve either. Reuse encoding code; do not assume shared weights are beneficial.
Thus the proposed programme has:
Initially one neural model; eventually at most two, plus a small frozen continuation-equity table.
Baseline retention resembles the motivation behind safe policy improvement methods, but a neural advantage threshold does not inherit a formal safety guarantee merely because it falls back to a baseline. Actual paired deployment tests remain necessary.
Why neither N1 nor N2 belongs first
Better beliefs do not repair strategy fusion. Averaging incompatible world-specific plans remains wrong with a perfect posterior.
A value network does not automatically repair rollout mismatch. A value function trained under reference continuation estimates reference-continuation value. Deploying it where both partners subsequently act differently changes what it is supposed to predict.
Moreover, pooling returns from different generating policies does not create a universal \(Q\). It estimates a mixture whose meaning depends on those policies and their sampling weights. More generally, imperfect-information search cannot assume that a public history has a policy-independent continuation value; that issue motivates the richer state formulation used in ReBeL.
For the initial experiment, avoid both problems rather than introducing models intended to compensate for them.
3. Representation
Preserve exact state explicitly; learn the uncertain strategic relationships
I would use a rank-ordered per-suit representation, not another small pooled hand vector that must rediscover elementary card accounting.
For each suit, retain thirteen fixed rank positions. Useful channels include:
Own holding, publicly known ownership, played status and hard feasible-owner masks.
Current-trick participation and the public high card.
Exact per-suit posterior summaries, where available at acceptable inference cost.
The posterior summaries should describe holdings, such as ownership marginals, suit-length distributions, or probabilities of possessing cards above or below a specified rank. Do not silently turn these into “probability of winning the trick” without specifying the card-selection behaviour involved.
Feed each suit through a shared small multilayer perceptron, then combine all four suit embeddings jointly with public context.
For Model S, start around 0.1–0.3M parameters: two per-suit layers of width 128 and a small joint head are ample for the first test. This is a fixed starting architecture, not a claim that its capacity is sufficient. Its sufficiency is part of the gate.
For Model P, add an action scorer receiving:
The candidate card’s rank and suit representation.
The joint four-suit representation.
Current-trick and partnership context.
A small chronological history encoder, for example a 64-unit GRU.
The GRU should provide a behavioural-history channel. It should not be responsible for remembering which cards have disappeared or reconstructing proven voids: those are exact features.
No trumps does not imply independent suit values
Suit-level trick resolution is simple. Complete play is not suit-independent. Discards, lead transitions, hand capacities, partner holdings and showing constraints couple suits.
Therefore, use shared per-suit computation followed by cross-suit interaction, not
$$ Q(o,a)=\sum_s Q_s(o_s,a_s) $$
as an asserted decomposition.
Important legality detail: showing can have more than 14 legal actions
The measured maximum of 14 is not a rules-derived maximum.
Under priority 3, a hand containing no ranks 3–9 can show any of its thirteen cards under either declaration: 26 legal showing actions. Such a hand is possible because the deck contains 24 cards outside ranks 3–9.
Keep the scorer ragged over the engine’s tuple. Do not hard-code a 14-action showing limit.
Forced choices should bypass neural scoring entirely, but their actions must still enter subsequent public-history encodings.
Two inference assumptions need correction
“Took a trick” is not a hard no-lower-card deduction
I would not promote the purported rationality-based ducking inference to a hard ownership mask.
A simple partnership counterexample exists: the fourth player can overtake a partner who is already winning, shed a dangerous high card, and leave the partnership’s current trick total unchanged. That player may hold a lower card and still have a sound reason not to duck.
The empirical frequency in §3.4 can remain valid. The inference is nevertheless behavioural, not logically entailed by the rules.
Similarly, “could have ducked” for another player may require that player’s hidden hand. It can be a training label; it is not automatically an observation-derived input.
An exact hard-constraint posterior is not a policy-free posterior of the full history
The exact per-suit posterior is exact under its stated conditioning assumptions. If behavioural action likelihoods are excluded, it is not the posterior obtained by conditioning on a known policy’s complete behaviour.
That is acceptable: it is an excellent structural reference. But mixing training policies does not make policy assumptions disappear; it replaces one behavioural prior with a population prior.
For now, use exact hard-information summaries as features. Do not multiply suit marginals into a fictitious independent whole-hand distribution.
Also enforce data augmentation only after checking the entire label-generating pipeline. Colour-preserving suit permutations are symmetries of the rules, but a reference policy’s absolute-suit tie-breaking can break symmetry of its continuation values.
4. Experiments and preregistered gates
Common evaluation contract
I propose a minimum worthwhile gain of
$$ \delta=0.001 $$
in frozen-continuation equity per evaluated deal. That is a proposed funding threshold, not a measured property of Tuppi. Change it before generating results, not afterwards.
For a forehand-only candidate evaluated under complementary team assignments, only one assignment may contain an intervention. Report the full complementary per-deal effect—not merely gain conditional on an override or a showing opportunity.
Use fixed test sizes, frozen candidates and fresh test deals. Put all counterfactual branches, complementary assignments and score variants of the same underlying deal into one cluster. For repeated hidden completions of the same observation, use an outer observation/hand cluster as well.
For promotion, use one-sided 97.5% lower bounds. With at most one showing candidate and one play candidate subjected to confirmatory promotion, this provides a simple allocation of a 5% false-promotion budget. Architecture and threshold selection belong exclusively to training/validation.
Estimate required test size from a separate variance pilot:
$$ N\approx \left[ \frac{(z_{1-\alpha}+z_{0.8})\sigma_D}{\delta} \right]^2 $$
for 80% power when the true improvement is \(2\delta\) and promotion requires exceeding \(\delta\). Here \(\sigma_D\) must be the standard deviation of the actual deal-cluster contrast, not the raw forced-branch outcome.
The provided signed-point standard deviations cannot determine equity-endpoint power.
Cost convention
The following rollout costs extrapolate the supplied rates of 556 and approximately 74 deals/s. They exclude neural inference, training and additional conditional-sampling overhead.
Completed-deal rollout equivalents    Mac estimate    Fedora estimate
131,072    4 minutes    30 minutes
440,000    13 minutes    99 minutes
1,000,000    30 minutes    3.75 hours
These are planning calculations, not measurements of the proposed workloads.
Experiment 0 — Endpoint and clone failure audit
Budget: 4,096 independent base deals for the diagnostic profiles, with a total cap of approximately 100,000 deal/suffix rollout equivalents. Neural runtime must be measured.
Run the diagnostic comparisons described in §1. Include a reference-delegating wrapper that must reproduce the reference byte-for-byte. Check the deployed clone’s action against its evaluation implementation on identical observations.
If the existing equity definition is unsuitable, calibrate the small reference-continuation table using a separate corpus; a provisional cap is one million independent deal rollouts allocated across boundary states. Carry calibration uncertainty into equity comparisons rather than treating an estimated table as exact.
Gate: no training until legality, information-boundary and reference-identity controls pass, and the primary utility has an unambiguous definition.
Kill criterion: any information leak, action-path discrepancy or unreproduced reference identity stops this run. If the clone does not show a per-deal deficit on the chosen utility, stop attributing its failure to generic per-decision inferiority and investigate score-state exposure and match evaluation instead.
This experiment need not select a neural architecture. Its job is to prevent another programme from addressing the wrong mechanism.
Experiment 1 — Measure observation-compatible showing headroom
This is the smallest substantive experiment I would fund to falsify the proposed programme.
Sample 512 first-showing observations. For each, generate 128 independent hidden completions conditional on the same own hand and public context. Evaluate the two complete showing actions, followed by reference policies throughout.
Cost:
$$ 512\times128\times2=131{,}072 $$
completed-deal rollouts.
At this first decision, conditional sampling avoids the difficult problem of conditioning a joint hidden-hand distribution on behavioural history.
For each observation, use one half of the completions to choose an action and the other half to estimate that choice’s value; swap halves and aggregate. This evaluates an observation-compatible Monte Carlo selector without letting selection exploit the evaluated hidden world.
Do not call the maximum of noisy sample means an estimated ceiling. Report a cross-fitted achievable value and, separately, a conservative upper bound on legal headroom that includes conditional Monte Carlo uncertainty and sampling uncertainty across hands.
Pass: the cross-fitted observation-compatible selector’s lower confidence bound exceeds \(\delta\) on the deployment-normalised endpoint.
Scientific kill: an upper confidence bound on legal headroom falls below \(\delta\). No network can rescue this restricted action-and-continuation problem.
Budget kill: at the fixed completion budget, the experiment remains inconclusive and does not meet the pass criterion. Stop this programme rather than escalating completions indefinitely. Label the result inconclusive, not evidence that all learning is impossible.
This also yields a serious non-neural candidate. If this selector wins and its showing latency is acceptable, a neural model is an amortisation of a working legal decision procedure, not a speculative source of strength.
Experiment 2 — Train one showing advantage model
Data budget: 100,000 distinct training observations, 20,000 validation observations, and up to 100,000 fresh test observations, each with the two executable branches. At one hidden completion each, that is 440,000 rollouts.
The existing pairs can be used after their intervention semantics and continuation identities are verified. Do not assume every mixed-population pair has the desired reference-continuation target.
Training objective: squared error on the paired utility difference. Retain zero differences and the original sampling weights. Scaling targets by a fixed constant is fine.
Do not instead classify which branch won. That optimises the probability of a positive difference, not its expectation. Large negative tails are particularly relevant to RAMI.
Preregister one neural architecture and one training schedule. Compare against the reference and a descriptor regression fitted on the same interventions and labels. A simple raw-card linear comparator is also worthwhile; it tests whether depth is contributing anything.
Choose the override threshold from a small declared set—for example \(0,\delta,2\delta\)—using validation only.
Promotion gate: on fresh test deals:
The candidate’s lower bound on gain over the reference exceeds \(\delta\).
Its lower bound on gain over the descriptor comparator exceeds zero.
Kill: failure of either condition at the preregistered test budget ends this neural showing attempt. No architecture enlargement, new loss function or extra data tier after viewing the test result.
If a simple comparator succeeds and the network adds nothing, ship the simpler policy and stop the neural branch.
Experiment 3 — Test transfer before widening scope
The primary reference comparison and cross-policy evaluation answer different questions. Keep them separate.
With the partner initially fixed to the reference, evaluate the candidate against genuinely reserved opponent-policy families on identical deals. Use continuations actually executed by those opponents.
Gate for a transferable-policy claim: prespecified simultaneous noninferiority bounds exceed \(-\delta\) in each reserved family, alongside the reference improvement.
Kill: a failed transfer gate stops expansion as a purported generally stronger policy. A reference-only improvement remains a measured best response, not evidence of human-level or population-general strength.
This distinction matters even at first showing. There is no earlier policy signal to invert there, but the best declaration can still depend on how the subsequent players behave.
Do not add later showing seats automatically. Once earlier learned passes change which seats reach their decisions, that is a new sequential-policy experiment requiring new reached-state data and an additional frozen gate.
Experiment 4 — Card-play intervention model, still one intervention per deal
Proceed only after the initial showing programme has demonstrated useful legal-information learning.
For a fixed observation-identifiable play scope, collect 100,000 root decisions. At each, evaluate:
The reference action.
Its runner-up.
One uniformly sampled other legal action, where one exists.
This costs at most 300,000 suffix rollouts and introduces action coverage beyond the heuristic’s top two. Use an independent all-legal-action audit on a smaller set to establish whether the candidate set is omitting obvious opportunity.
Train Model P on paired advantages, anchored at zero for the reference action.
Keep zero labels. “No difference on this hidden deal under this continuation” is useful evidence. It is not proof that two actions are strategically equivalent, but discarding such cases would change the target distribution.
Do not repeatedly rerun the same deterministic continuation on the same hidden deal; it produces no additional information. New information requires new hidden deals or explicitly different continuation policies.
Promotion gate: the deployed single-intervention policy’s lower bound exceeds \(\delta\) over its frozen comparison policy on fresh paired deals.
Kill: failure at the fixed budget ends this play-model attempt. Do not reinterpret a high action-ranking score or lower regression error as success.
Experiment 5 — Permit repeated learned actions only after continuation alignment
This is where the clone’s mechanism can return.
Before allowing multiple overrides, preregister one collection/update phase in which both candidate seats use the actual frozen candidate snapshot. Collect candidate-reached observations and generate intervention labels using that same partnership’s continuation.
Then freeze the updated model and test the actual two-seat deployment, not a single learned seat with a reference partner.
Gate: improvement over both the original reference and the last promoted restricted candidate, with the same per-deal utility and clustering.
Kill: if isolated interventions win but the repeated two-seat policy fails, stop the expansion. Retain the successful restricted candidate. Do not add another on-policy round after that gate fires.
This phase explicitly tests whether individually useful changes remain useful when their downstream states and partner interactions accumulate.
5. What I would not do—and what is realistic computationally
Do not start a learned belief programme
The current belief proposal has an attractive supervised metric and an unestablished route to stronger decisions.
It risks spending the budget predicting many card locations accurately without changing the few action rankings that matter. It also does not solve strategy fusion or continuation mismatch.
A later belief model needs one of two specific purposes:
Acceleration: approximate the existing exact hard-information calculations with a measured speed benefit and bounded downstream policy degradation.
Additional behavioural information: improve decision utility across genuinely disjoint policy families, not merely improve ownership likelihood against related deterministic generators.
Those are different projects. Neither is currently a prerequisite for Model S.
Do not distil perfect-information optimal values as though they were legal continuation values
An exact five-trick double-dummy value belongs to a different information game.
Regressing it onto an observation does not remove the privileged future decision-making inside its target. It can produce an accurate prediction of the wrong quantity.
Such a solver could be useful for diagnostics or a separately gated auxiliary experiment. I would not make it the initial value target or assume it fixes search.
Do not learn a RAMI-success classifier with a fixed 62% threshold
The relevant comparison is against the actual alternative showing action, including later declarations, outcome margins and current match state.
The empirical break-even probability is a population summary, not a universal decision rule.
Do not pool the whole corpus into a generic value loss
Ten million deals do not become 546 million independent outcome observations because their terminal returns are copied onto every decision.
More importantly, a return generated by one continuation profile is not automatically a label for another. Preserve policy identities and intervention metadata. Use diverse trajectories for coverage, but do not lose the meaning of the quantity being estimated.
Limited reinforcement learning is realistic; unrestricted self-play is not yet justified
The hardware does not rule out reinforcement learning. Batched approximate policy iteration with a bounded number of deal-level collection rounds is realistic in principle. The missing quantity is measured end-to-end throughput and its learning curve.
I would place an environment-in-the-loop pilot on the Fedora machine:
Several CPU environment workers maintaining many independent deal states.
A central inference process using the 1070.
Fixed batches, initially 64 pending observations.
Forced moves resolved without neural calls.
Frozen policy snapshots during each collection round.
Batch by a deterministic schedule of environment slots and decision rounds—not wall-clock queue timeouts or worker completion order.
The Mac remains preferable for bulk reference-only counterfactual generation. A small model might also permit efficient batched Mac CPU inference, but that must be measured rather than inferred from its generation advantage.
For scale: at an illustrative measured rate of 20 completed deals/s, one million deal rollouts take about 14 hours. At 5/s, they take about 56 hours. Neither is inherently excluded by an unlimited-wall-clock host. These are scenarios, not throughput predictions.
I would cap the first interactive programme at a predetermined collection budget, such as one million deal rollouts and one update phase. Do not use complete-match terminal rewards when the deal-boundary continuation utility is available.
There is precedent for Monte Carlo learning with encoded legal actions and parallel actors in imperfect-information card games, notably DouZero. Its reported four-GPU training setup, however, is not evidence that an analogous programme will be efficient on this hardware or successful in Tuppi.
Verify the execution stack before budgeting the GPU
Current PyTorch packaging reinforces the briefing’s warning: a September 2026 announcement states that published CUDA 12.6 binaries are being removed from the 2.15 line, ending that prebuilt path for older architectures. Pin a locally verified compatible build; do not plan around “latest PyTorch”.
Also distinguish deterministic execution on a pinned stack from byte-identical results across CPU, CUDA and Metal. PyTorch explicitly does not guarantee reproducibility across platforms or releases, even with identical seeds. Use an authoritative inference backend and treat a backend change as a new runtime identity requiring conformance tests.
6. Facts needed before implementation
Missing fact    Why it matters
Exact definition of Part 4 equity, including continuation policy and score/dealer weighting    Determines whether the existing target already represents the desired utility
Future-deal independence and any permitted cross-deal policy state    Determines whether the 100-state continuation table is valid
Forced-contract intervention semantics, including shown-card selection and later declarations    Determines whether existing pairs identify an executable showing intervention
Policy identities and continuation metadata for every paired stratum    Prevents training a mixture value while interpreting it as reference-continuation advantage
Clone contract-only agreement, nonforced agreement, deployed disagreement rate and single-deviation losses    Distinguishes harmful action errors, distribution shift and partnership interaction
What makes reserved policies genuinely different    Determines whether cross-policy testing measures transfer or merely variation within one behavioural family
Exact posterior conditioning assumptions, interfaces and inference latency    Determines which features are valid and whether exact computation should be used directly
Acceptable showing/play latency, verified 1070 execution, and end-to-end batched inference throughput    Determines whether the working first-showing Monte Carlo selector needs neural amortisation at all
There is one additional strategic fact worth obtaining before a much larger investment: how the reference actually performs against competent humans, and which errors those humans identify reproducibly. With zero expert-validated strategy rules, that may be more valuable than another large synthetic corpus.
Bottom line
The first programme should ask:
Can information legally available before the first show identify profitable deviations from the reference, when all consequences are evaluated under an executable, correctly matched continuation?
That question is cleaner than any of N1–N4 as originally ordered.
If the answer is no at the preregistered budget, stop this programme. That does not mathematically exclude every possible learned card player; it rejects the proposed investment on a particularly favourable, diagnosable test.
If the answer is yes, train a small advantage model to amortise that decision procedure, preserve the reference everywhere else, and expand only through separately gated interventions.
The resource to fund is controlled, observation-compatible policy improvement—not a larger imitation dataset and not a better predictor of an ill-defined value.
