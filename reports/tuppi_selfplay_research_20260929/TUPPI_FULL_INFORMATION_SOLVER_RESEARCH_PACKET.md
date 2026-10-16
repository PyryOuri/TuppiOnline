# Full-Information Tuppi: Exact Solving, Game Complexity, and What It Can Teach the AI Project

**Prepared:** 29 September 2026  
**Purpose:** Research handoff on the question: *What happens if all cards in Tuppi are visible, and how useful would an exact full-information solver be for understanding and improving the normal imperfect-information bot?*

---

# 1. Executive conclusion

If all four hands are visible and the contract is fixed, Tuppi becomes a finite deterministic perfect-information team game.

Therefore, for any fixed card-play state, there is in principle a well-defined optimal game-theoretic value under perfect play.

That does **not** imply that the result is obvious from the initial deal.

The important distinction is:

```text
mathematically determined
!=
human-obvious
!=
computationally trivial
```

A full-information Tuppi solver could therefore become a major research instrument for the project.

Its value would not primarily be as a direct policy teacher. Instead, it could separate two fundamentally different sources of difficulty:

1. **Tactical / computational difficulty**  
   How hard is the state even if all hidden cards are known?

2. **Information difficulty**  
   How much does the correct action depend on which hidden-card world is actually true?

That decomposition could answer whether current Tuppi AI limitations are mainly due to:

- insufficient tactical calculation;
- imperfect belief/inference;
- signalling and partner coordination;
- determinisation/strategy-fusion problems;
- or a combination.

---

# 2. Project context

The authoritative project is the v3 Tuppi environment.

Relevant known properties from the existing project handoff:

- Four seats.
- Opposite seats are permanent partners.
- 13 cards per player.
- No trumps.
- RAMI: teams seek tricks.
- NOLO: teams avoid tricks.
- Bidding uses a declaration plus an eligible card.
- Bids are made without seeing other bids.
- Reveal stops at the first RAMI.
- Bid legality depends on rank and red/black colour, including fallback rules.
- Sooli is a separate subgame with private exchange, dead partner hand, three-player trick play, ace-low handling, and a 24-point outcome.
- Matches use rising scores and end at 52 or more.

The current live search is a clone-driven determinisation system:

1. sample hidden hands consistent with observations;
2. compare legal actions through rollouts;
3. use a six-trick double-dummy tail.

That existing six-trick exact tail already establishes that the project has a natural interface for perfect-information solving in late play.

---

# 3. What "forced" can mean

Several distinct concepts should not be conflated.

## 3.1 Game-theoretically determined

A state has a single optimal value under perfect play.

This is the ordinary minimax / backward-induction notion.

For a state \(s\):

\[
V(s)=
\begin{cases}
U(s), & s\text{ terminal}\\
\max_{a\in A(s)} V(T(s,a)), & \text{Team A acts}\\
\min_{a\in A(s)} V(T(s,a)), & \text{Team B acts}
\end{cases}
\]

If the utility is zero-sum between the two teams, the value is well-defined.

All perfectly rational players with unlimited computation can agree on that value.

They do **not** necessarily need to agree on one unique move.

---

## 3.2 One team can force an outcome

A team has a strategy that guarantees a given result regardless of the opponent's responses.

Example:

```text
Team A can guarantee at least 7 tricks.
Team B can prevent Team A from taking 8.
```

This is stronger than simply saying the state has a value.

---

## 3.3 Path-invariant outcome

Every legal continuation, including bad play, produces the same result.

This is much stronger.

Many game-theoretically solved positions will not be path-invariant because mistakes can change the outcome.

---

## 3.4 Human-obvious outcome

A strong player can infer the result essentially by inspection or shallow analysis.

This is not guaranteed at all.

A position may have a mathematically exact value but require deep search to prove.

---

# 4. Why full-information Tuppi is still potentially difficult

Revealing all cards removes uncertainty, but it does not remove combinatorial search.

A crude upper-bound intuition comes from ordering each player's 13 cards:

\[
(13!)^4 \approx 1.5\times 10^{39}
\]

This is **not** the legal game-tree size. Follow-suit restrictions remove enormous numbers of impossible sequences.

The point is only that the space of complete play sequences is intrinsically large.

The real search complexity depends on:

- follow-suit constraints;
- transpositions;
- move equivalence;
- suit symmetry;
- exact terminal utility;
- pruning quality;
- trick-level bounds;
- relative-rank canonicalisation;
- whether all 13-trick deals can be solved cheaply in practice.

The bridge analogy is useful:

- full 52-card double-dummy bridge is nontrivial;
- nevertheless, highly optimised exact solvers can solve complete deals in practice;
- they rely on alpha-beta search, transposition tables, move ordering, suit/rank reductions, and domain-specific bounds.

This suggests a plausible Tuppi hypothesis:

> Full-information Tuppi may be exactly solvable for most or all ordinary 13-card deals in practical time, even though the result is far from visually obvious.

This remains an empirical question until benchmarked.

---

# 5. Proposed new research tool: Tuppi Double-Dummy Solver

Call the system:

```text
Tuppi-DD
```

Input:

```text
four hands
leader / current seat
partial trick
played-card history
contract
score context if utility depends on it
```

Output:

```text
exact game-theoretic value
set of optimal legal actions
value of every legal root action
optional principal variation
search proof statistics
```

For every state:

\[
V(s)
\]

and for every legal action:

\[
Q_{\mathrm{DD}}(s,a)
\]

should be available.

---

# 6. Solver semantics

The cleanest design is not to hard-code assumptions such as:

```text
RAMI = simply maximise raw tricks
NOLO = simply minimise raw tricks
```

unless these are exactly equivalent to the authoritative rules.

Instead, the terminal evaluation should derive from the authoritative game outcome.

Recommended layering:

```text
exact card-play outcome
        ↓
exact deal transition / score change
        ↓
optional match-value layer
```

This keeps the tactical solver independent of one potentially outdated match-equity table.

---

# 7. Basic exact recursion

Conceptually:

```text
solve(state):
    if terminal:
        return terminal_utility(state)

    if state in transposition_table:
        return cached_value

    legal = generate_legal_actions(state)

    if Team A acts:
        value = max(solve(child(state, a)) for a in legal)
    else:
        value = min(solve(child(state, a)) for a in legal)

    cache(state, value)
    return value
```

The challenge is not the recurrence.

The challenge is reducing the search enough that solving full deals is cheap.

---

# 8. High-priority solver optimisations

Candidate optimisations:

1. **Alpha-beta pruning**
2. **Transposition tables**
3. **Relative-rank canonicalisation**
4. **Move ordering**
5. **Equivalent-card pruning**
6. **Suit canonicalisation where legally valid**
7. **Trick-level upper/lower bounds**
8. **Exact late-game tables**
9. **Iterative deepening / proof search**
10. **Principal-variation caching**
11. **Team-aware move ordering**
12. **Contract-specific bounds for RAMI and NOLO**

Because Tuppi has no trumps, resolved card play may have more suit symmetry than bidding.

However, colour is relevant to bidding.

Therefore:

> Do not assume every suit permutation is valid for the full game.

A broader symmetry may become valid **after the contract is resolved** if red/black no longer affects card play. This must be confirmed against the authoritative rules.

---

# 9. First benchmark question

Before designing anything more sophisticated, measure:

> How expensive is exact full-information Tuppi from 13 cards per player?

Run random resolved-contract states with:

```text
13 tricks remaining
12
11
10
...
6
5
...
1
```

Record:

- wall time;
- node count;
- transposition hit rate;
- memory;
- number of legal root actions;
- optimal-action count;
- contract;
- seat;
- score context.

The existing six-trick exact tail gives a known lower-complexity reference point.

The critical empirical result is the curve:

\[
\text{solve cost} = f(\text{tricks remaining})
\]

If 13-trick solving is routinely practical, the implications are large.

If it explodes, that result is still scientifically valuable.

---

# 10. The most important use is not simply solving deals

Once exact solving exists, the project can study the **structure of Tuppi itself**.

For each full-information state, compute:

\[
Q_{\mathrm{DD}}(s,a)
\]

for every legal action.

Then quantify:

- how many optimal actions exist;
- how costly mistakes are;
- where tactical leverage occurs;
- when the result becomes structurally locked;
- which contract types are tactically sharper;
- whether early play matters much more than late play.

This produces a **Tuppi complexity atlas**.

---

# 11. Optimal-action multiplicity

Define:

\[
A^*(s)=\{a:Q_{\mathrm{DD}}(s,a)=V(s)\}
\]

and:

\[
N^*(s)=|A^*(s)|
\]

Interpretation:

### Large \(N^*\)

Many cards preserve the exact value.

The state is tactically forgiving.

### \(N^*=1\)

Exactly one card is optimal.

The state is tactically sharp.

This can be studied by:

- RAMI vs NOLO;
- trick number;
- leader/follower position;
- score;
- hand structure;
- legal-action count.

---

# 12. Exact action gap

Let the best action have value \(V_1\) and the best inferior action have value \(V_2\).

Define:

\[
\Delta(s)=V_1-V_2
\]

Interpretation:

### Small \(\Delta\)

Choosing an inferior card barely matters.

### Large \(\Delta\)

The state contains a consequential tactical decision.

This is much more useful than simply classifying a bot move as "correct" or "incorrect."

---

# 13. Tactical regret

For an AI action \(a_{\mathrm{AI}}\):

\[
R_{\mathrm{DD}}(s)
=
V(s)-Q_{\mathrm{DD}}(s,a_{\mathrm{AI}})
\]

This is **double-dummy regret**.

It measures the amount of value lost if the actual hidden deal had been fully known.

Important:

> This is not necessarily the true imperfect-information regret.

A real player may rationally choose a move that is suboptimal in the realised hidden world because the world was not known when the decision was made.

Therefore DD regret is a diagnostic quantity, not an automatic error label.

---

# 14. How early is a deal "decided"?

This question can be formalised in several ways.

## 14.1 Game-theoretic value known

In a mathematical sense, the minimax value exists from trick 0.

That definition is not interesting.

---

## 14.2 Guaranteed-outcome time

Record the earliest trick \(t\) at which one team can guarantee the final relevant outcome regardless of opponent responses.

---

## 14.3 Path-invariant time

Record the earliest trick where every legal continuation produces the same terminal result.

This is much stronger.

---

## 14.4 Value-stability time

Record when the same optimal value remains under all remaining plausible high-quality lines.

This may be a more practical notion than full path invariance.

---

# 15. Outcome-lock curves

For a large random sample, estimate:

\[
P(\text{outcome locked by trick }t)
\]

and:

\[
P(\text{optimal deal score guaranteed by trick }t)
\]

This could answer:

```text
Is Tuppi mostly decided in the first few tricks?
```

or:

```text
Do consequential choices remain deep into the hand?
```

That has immediate architecture implications.

If most value is decided early:

- spend search budget early;
- train early-play policy hardest;
- use cheaper late play.

If large value swings remain late:

- preserve strong reasoning throughout the deal.

---

# 16. The central AI use: separate tactical difficulty from information difficulty

The most important extension is to combine Tuppi-DD with sampled hidden worlds from real information states.

Suppose the real player sees information state \(I\).

There are many hidden-card worlds:

\[
w_1,w_2,\ldots,w_N
\]

consistent with \(I\).

For every world:

\[
Q_{\mathrm{DD}}(w,a)
\]

can be computed.

Now every real Tuppi decision can be classified along two axes.

---

# 17. Two-axis difficulty map

## Axis 1: tactical difficulty

How difficult is the state even if all cards are visible?

Possible measures:

- node count needed for proof;
- action gap;
- number of optimal actions;
- principal-variation depth;
- sensitivity to alternative lines.

---

## Axis 2: information sensitivity

How much does the preferred action vary across hidden-card worlds consistent with the player's actual information?

This gives four categories:

| | Hidden-world insensitive | Hidden-world sensitive |
|---|---|---|
| **Tactically easy** | essentially simple execution | belief / signalling problem |
| **Tactically hard** | search problem | search + imperfect-information problem |

This decomposition can directly guide AI investment.

---

# 18. World-action consensus

For information state \(I\), sample legal hidden worlds \(w\).

Define:

\[
C(I)=
\max_a
P_w[a\in A^*(w)]
\]

Call this:

> **Double-dummy action consensus**

Interpretation:

### \(C(I)\approx1\)

One action is optimal in almost every plausible world.

The hidden information barely matters for the choice.

### Low \(C(I)\)

The correct full-information action changes frequently depending on hidden cards.

The decision is highly information-sensitive.

---

# 19. DD-optimal action entropy

For each action, estimate:

\[
p_a=P_w[a\in A^*(w)]
\]

Then:

\[
H_{\mathrm{DD}}(I)
=
-\sum_a p_a\log p_a
\]

Interpretation:

### Low entropy

Possible hidden worlds largely agree on what should be played.

### High entropy

Different hidden worlds imply different optimal actions.

Study this by:

- contract;
- trick number;
- seat within trick;
- score;
- legal-action count;
- bid history;
- card-class structure.

---

# 20. Why world-action consensus matters for determinisation search

The current Tuppi search samples hidden worlds and evaluates actions through world-specific rollouts.

If most important states have:

\[
C(I)>0.9
\]

then determinisation is structurally attractive.

Why?

Because although the worlds differ, the same action is usually best.

In that regime, the main remaining problems are likely:

- world sampling quality;
- rollout/value accuracy;
- search depth;
- compute.

A stronger DD tail could be extremely valuable.

---

If instead many important states have:

\[
C(I)<0.5
\]

then hidden-world identity strongly affects the full-information best move.

This is the regime where ordinary determinisation becomes structurally suspect.

More sampled worlds may reduce Monte Carlo variance, but they do not solve the fact that the search can implicitly condition action selection on hidden information unavailable to the actual player.

This motivates information-set methods, belief-aware search, or greater reliance on the observation-only self-play actor.

---

# 21. Clairvoyance / strategy-fusion gap

A particularly useful diagnostic compares two quantities.

First:

\[
V_{\mathrm{clairvoyant}}
=
E_w\left[\max_a Q_{\mathrm{DD}}(w,a)\right]
\]

This allows the decision maker to look at the hidden world and then choose the best action.

Second:

\[
V_{\mathrm{fixed}}
=
\max_a
E_w\left[Q_{\mathrm{DD}}(w,a)\right]
\]

This requires selecting one action across all worlds.

Define:

\[
G(I)
=
E_w[\max_a Q_{\mathrm{DD}}(w,a)]
-
\max_a E_w[Q_{\mathrm{DD}}(w,a)]
\]

Then:

\[
G(I)\ge0
\]

This quantity measures the value of being allowed to choose a different action after seeing the true hidden deal.

Call it:

> **clairvoyance gap**

or, more cautiously:

> **DD strategy-fusion diagnostic**

A large gap identifies states where determinisation can gain substantial artificial value from hidden information.

---

# 22. Important limitation of the clairvoyance gap

The quantity above is **not** the true imperfect-information game value.

Why?

Because:

- future information revelation matters;
- signalling matters;
- partner inference matters;
- opponent inference matters;
- current and future action policies are constrained by information sets;
- DD continuation assumes full information.

Therefore:

```text
large DD clairvoyance gap
```

means:

```text
this state is vulnerable to strategy-fusion-like reasoning
```

It does **not** mean:

```text
the exact imperfect-information value is known
```

This distinction must be preserved.

---

# 23. The strongest diagnostic question for the existing search

After Tuppi-DD exists, take real self-play/search information states and ask:

> Across all legally plausible hidden worlds, how often is the same action double-dummy optimal?

This single distribution may be highly informative about whether the current W128/W1024 determinisation architecture is fundamentally appropriate.

Possible finding A:

```text
high DD consensus
small clairvoyance gaps
```

Implication:

- determinisation is probably a good structural fit;
- invest in stronger world evaluation;
- push exact solving earlier;
- improve sampling only as needed.

Possible finding B:

```text
low DD consensus
large clairvoyance gaps
```

Implication:

- ordinary determinisation has a likely structural ceiling;
- more worlds alone may not fix it;
- information-set reasoning deserves more investment.

---

# 24. Do not directly imitate the DD oracle

This is critical.

Suppose two worlds \(w_1,w_2\) are indistinguishable to the acting player.

DD solver says:

\[
a_1\text{ is optimal in }w_1
\]

and:

\[
a_2\text{ is optimal in }w_2
\]

A real player cannot implement:

```text
if world == w1:
    play a1
else:
    play a2
```

because it does not know the world.

Training directly on those labels risks teaching a policy toward an impossible clairvoyant strategy.

This is a classic form of strategy-fusion error.

---

# 25. Tuppi-specific reason DD imitation can be actively misleading: signalling

In a double-dummy game, the partner already knows your cards.

Therefore signalling has no value.

In real Tuppi, a move may be useful because it communicates something to the partner.

So a move may be:

```text
DD-suboptimal
```

but:

```text
imperfect-information optimal
```

because of information transmission.

Likewise, deceptive or ambiguity-preserving play can have value against opponents only when cards are hidden.

Therefore:

\[
\boxed{
\text{DD oracle = powerful diagnostic/critic}
\neq
\text{safe direct policy teacher}
}
\]

---

# 26. Safe and useful ways to use DD information

## 26.1 Exact search tail

Push the current six-trick exact tail deeper.

Benchmark:

```text
7 tricks
8 tricks
9 tricks
10 tricks
11 tricks
12 tricks
13 tricks
```

Then find the optimal dynamic switch point:

```text
search / rollout
    ↓
exact DD solve
```

---

## 26.2 Offline tactical error analysis

After a real game finishes, the full deal is known.

For every decision:

\[
R_{\mathrm{DD}}(s)
=
V(s)-Q_{\mathrm{DD}}(s,a_{\mathrm{played}})
\]

Use this to identify suspicious or tactically costly decisions.

Do not automatically call them mistakes under imperfect information.

---

## 26.3 Curriculum construction

Ideal training states may be those with:

- high DD action gap;
- high world-action consensus.

Why?

Because:

- the choice matters;
- the correct action is relatively insensitive to hidden-world identity.

These are strong candidates for supervised or auxiliary targets.

By contrast:

- high gap;
- low world consensus

should generally remain under information-aware self-play learning.

---

## 26.4 Privileged critic support

The self-play project is considering a training-only full-information critic.

DD values can be useful as:

- late-state critic targets;
- critic calibration checks;
- auxiliary losses;
- bootstrapping validation.

The actor must still use legal information only.

---

## 26.5 Search-error localisation

If search and DD disagree in a fully instantiated world, the cause is tactical/search error.

If search differs only because different worlds prefer different actions, the cause is information aggregation.

This is an unusually clean diagnostic split.

---

# 27. Bidding is a separate game-theoretic problem

Everything above assumes the contract is fixed.

Full-information bidding is different.

In Tuppi:

- bids contain declaration + eligible card;
- bids are selected without seeing other bids;
- reveal logic stops at first RAMI.

If all cards are visible but bids remain simultaneous/private until resolution, the bidding stage is not ordinary sequential perfect information.

However, once Tuppi-DD exists, every bid profile can be evaluated exactly downstream.

For bid profile:

\[
(b_0,b_1,b_2,b_3)
\]

resolve the resulting contract and compute:

\[
U(b_0,b_1,b_2,b_3)
\]

If opposite seats are treated as coordinated teams, define:

\[
B_A=(b_0,b_2)
\]

and:

\[
B_B=(b_1,b_3)
\]

Then the bidding stage becomes a finite simultaneous zero-sum matrix game:

\[
U(B_A,B_B)
\]

This can have:

- a pure equilibrium;
- multiple pure equilibria;
- or a mixed-strategy equilibrium.

Therefore:

> A visible deal can have a unique game-theoretic value without having one unique deterministic bid profile.

---

# 28. A possible Tuppi "par" concept

Once exact card-play values exist, it may be possible to define an analogue of bridge-style "par":

> the equilibrium result of the fully visible deal after optimal bidding and optimal play.

This would require correctly encoding:

- bid legality;
- reveal rules;
- score consequences;
- team utility;
- simultaneous action structure.

This should be treated as a later extension.

First build the resolved-contract card-play solver.

---

# 29. Match-level complication

Even if the entire current deal is visible, future deals remain random.

Therefore the current deal may determine:

```text
exact current deal score transition
```

but not:

```text
certain eventual match winner
```

unless the score transition itself ends the match.

This suggests three distinct targets:

1. exact tricks;
2. exact deal score;
3. expected complete-match value after the deal.

Recommended design:

> Keep Tuppi-DD authoritative only for exact card-play / deal transition. Layer match value on top.

This avoids coupling the exact solver to one historical match-equity table.

---

# 30. Proposed Tuppi complexity atlas

Once the solver is stable, generate a large corpus.

Suggested scale:

```text
100,000 to 1,000,000 random resolved-contract deals
```

For each initial deal, store:

- contract;
- seat;
- exact value;
- exact deal transition;
- number of legal root actions;
- number of optimal root actions;
- best-vs-second-best action gap;
- full root Q vector;
- principal variation;
- nodes expanded;
- transposition hits;
- solve time;
- memory;
- trick when outcome becomes guaranteed;
- trick when outcome becomes path-invariant if applicable.

Then repeat analogous measurements for sampled mid-hand states.

---

# 31. Complexity atlas questions

The atlas could answer:

### Tactical sharpness

How often is there exactly one optimal move?

### Forgiveness

How often do multiple moves preserve full value?

### Error cost

How large is the typical action gap?

### Contract difference

Is NOLO tactically more or less difficult than RAMI?

### Temporal concentration

Are the most important decisions concentrated in early tricks?

### Seat effect

Is leading more tactically difficult than following?

### Proof difficulty

Which state features predict exact-solver node count?

### Structural lock

How early is the eventual deal result effectively settled?

---

# 32. Information-sensitivity atlas

Take actual information states from:

- behavioural clone games;
- SP1;
- VRPO/PPO if available;
- W128/W1024 search games;
- strong human-like or historical policy games.

For each information state:

1. sample legal hidden worlds;
2. solve each world with Tuppi-DD;
3. compute world-specific root Q values;
4. aggregate.

Store:

- DD action consensus;
- DD action entropy;
- clairvoyance gap;
- mean action values;
- action-value variance across worlds;
- rank instability;
- contract;
- trick;
- score;
- bid history;
- acting seat.

---

# 33. A stronger information-sensitivity metric: rank instability

For actions \(a_i,a_j\), calculate how often their ordering reverses across worlds.

Example:

\[
P_w(Q(w,a_i)>Q(w,a_j))
\]

If this is close to 0 or 1:

- ordering is stable.

If close to 0.5:

- hidden information strongly affects which is better.

A state can therefore have:

- high DD entropy but small value differences;
- low DD entropy but large tactical consequences;
- high rank instability;
- stable robust action.

These distinctions matter.

---

# 34. Robust-action value

Another useful quantity:

\[
V_{\mathrm{robust}}(I,a)
=
E_w[Q_{\mathrm{DD}}(w,a)]
\]

and:

\[
a_{\mathrm{robust}}
=
\arg\max_a E_w[Q_{\mathrm{DD}}(w,a)]
\]

This is **not** automatically the correct imperfect-information action because DD continuation still assumes full future information.

However, it is useful as a diagnostic baseline.

Compare:

- learned actor action;
- determinisation search action;
- robust-DD action;
- per-world clairvoyant actions.

Large disagreements identify states worth deeper study.

---

# 35. Potential decomposition of bot errors

For a decision where the final true deal is known:

### Case A

Bot differs from exact DD even in the true world, and DD consensus is high.

Likely issue:

- tactical policy/search weakness.

### Case B

Bot differs from true-world DD, but DD consensus is low.

Likely issue:

- uncertainty-sensitive state;
- cannot call this a simple tactical error.

### Case C

Determinisation search differs from robust-DD despite high consensus.

Likely issue:

- rollout/value/sampling weakness.

### Case D

Determinisation follows clairvoyant world-specific actions and consensus is low.

Likely issue:

- strategy-fusion / aggregation problem.

This gives the project a much stronger error taxonomy than simple win-rate comparison.

---

# 36. How this can guide search investment

The solver can tell us whether the current search bottleneck is:

## Search depth

If world-action consensus is high but the search still chooses wrong.

Response:

- deeper search;
- stronger exact tail;
- better move ordering;
- better value estimates.

---

## Belief quality

If correct action depends heavily on hidden worlds and the current sampler systematically misses important worlds.

Response:

- improve posterior sampling;
- better bid/play-conditioned beliefs.

---

## Strategy fusion

If world-specific best actions differ substantially and ordinary determinisation overvalues clairvoyance.

Response:

- information-set search;
- observation-consistent policy constraints;
- ReBeL-like or public-belief methods;
- stronger observation-only self-play actor.

---

## Partner signalling

If DD evaluations systematically disagree with strong self-play in low-information states where signalling matters.

Response:

- preserve self-play learning;
- do not use DD as direct teacher;
- explicitly study communication conventions.

---

# 37. How this can guide self-play data allocation

Self-play states can be prioritised according to:

\[
\text{importance}
\times
\text{tactical gap}
\times
\text{information sensitivity}
\]

Potential categories:

### High gap + high consensus

Excellent candidate for:

- supervised auxiliary target;
- tactical curriculum;
- search distillation.

### High gap + low consensus

Best candidate for:

- proper imperfect-information self-play;
- belief learning;
- information-set analysis.

### Low gap + high consensus

Low priority.

### Low gap + low consensus

Potentially strategically interesting but probably low immediate value unless signalling is important.

---

# 38. How this interacts with the self-play programme

The current proposed self-play direction is:

```text
behavioural clone / SP1
    ↓
privileged-Q VRPO
    ↓
match alignment
    ↓
selective search distillation
    ↓
population hardening
    ↓
search-integrated deployment
```

Tuppi-DD would sit alongside this as a diagnostic and exact-search tool.

It should **not** replace self-play.

Possible interaction:

```text
self-play generates realistic information states
                ↓
sample legal hidden worlds
                ↓
Tuppi-DD solves them
                ↓
measure tactical difficulty + information sensitivity
                ↓
allocate search / training effort intelligently
```

---

# 39. Strongest immediate research sequence

## Stage 1 — Extract / generalise the existing exact tail

The current search already uses a six-trick DD tail.

Identify:

- exact solver interface;
- assumptions;
- rule coverage;
- RAMI/NOLO support;
- Sooli support;
- state representation;
- transposition design;
- performance.

---

## Stage 2 — Push horizon systematically

Benchmark exact solving from:

```text
6, 7, 8, 9, 10, 11, 12, 13 tricks remaining
```

Do not assume full-deal solving is expensive until measured.

---

## Stage 3 — Validate exactness

Use:

- brute force on tiny states;
- transposition-disabled checks;
- symmetry checks;
- known constructed positions;
- comparison against current six-trick solver.

---

## Stage 4 — Build root action-value API

For any state return:

```text
Q_DD(s, a)
```

for every legal action.

This is more useful than returning only the best move.

---

## Stage 5 — Build the first complexity atlas

Start with perhaps:

```text
10,000–100,000 random initial resolved-contract deals
```

Measure:

- solve cost;
- optimal-action multiplicity;
- action gaps;
- contract differences.

---

## Stage 6 — Add self-play information states

Sample realistic information states from current bots.

Generate legal hidden worlds and solve them.

Compute:

- consensus;
- entropy;
- clairvoyance gap;
- rank instability.

---

## Stage 7 — Decide what Tuppi fundamentally is

The result should answer:

```text
mostly tactical?
mostly informational?
both?
```

and more importantly:

```text
where?
```

by contract, trick, seat and score.

---

# 40. Highest-value first empirical plots

If implementing this branch, the first plots should be:

### Plot 1

```text
median / p90 / p99 exact solve time
vs
tricks remaining
```

### Plot 2

```text
distribution of N*(s)
```

optimal-action count.

### Plot 3

```text
distribution of DD action gap
```

### Plot 4

```text
probability outcome is locked
vs
trick number
```

### Plot 5

```text
DD world-action consensus
vs
trick number
```

### Plot 6

```text
clairvoyance gap
vs
trick number
```

### Plot 7

```text
tactical difficulty
vs
information sensitivity
```

2D density / hexbin.

### Plot 8

```text
current bot DD regret
vs
DD consensus
```

This helps distinguish likely tactical mistakes from uncertainty-sensitive decisions.

---

# 41. Decision implications

## Result pattern A

```text
full deals solve cheaply
high DD consensus
small clairvoyance gaps
```

Conclusion:

> Tuppi is much more tactically deterministic than expected.

Research priority:

- aggressive exact-tail expansion;
- deeper determinisation;
- stronger tactical teacher;
- less urgent need for sophisticated information-set solvers.

---

## Result pattern B

```text
full deals solve cheaply
low DD consensus
large clairvoyance gaps
```

Conclusion:

> Tactical solving is easy, but hidden information fundamentally changes decisions.

Priority:

- self-play;
- beliefs;
- signalling;
- information-set reasoning;
- caution with determinisation.

---

## Result pattern C

```text
full deals hard to solve
high consensus
```

Conclusion:

> Main challenge is tactical computation.

Priority:

- specialised solver;
- search optimisation;
- value networks;
- deeper DD tails.

---

## Result pattern D

```text
full deals hard to solve
low consensus
```

Conclusion:

> Tuppi is genuinely difficult on both axes.

Priority:

- hybrid architecture;
- strong learned policy;
- search;
- belief reasoning;
- potentially more advanced game-theoretic methods.

---

# 42. Why this branch is unusually valuable

Most AI experiments answer:

```text
Did bot B beat bot A?
```

This branch can answer:

```text
Why is Tuppi difficult?
```

and:

```text
What kind of reasoning does the bot actually need?
```

That is a deeper and more transferable result.

An exact oracle gives:

- ground truth for full-information tactics;
- a way to quantify information sensitivity;
- a way to diagnose determinisation;
- a way to separate tactical from epistemic error;
- a principled method for allocating search compute;
- better training-state selection;
- better analysis of self-play improvements.

---

# 43. What this research must not claim

Do not claim:

- that DD-optimal means normal-play optimal;
- that full-information regret equals real decision regret;
- that a high clairvoyance gap is an exact exploitability measure;
- that sampled legal worlds equal the true behavioural posterior;
- that signalling is irrelevant because DD says so;
- that a full-information solver solves the imperfect-information game;
- that the current search is good or bad until the diagnostics are measured.

Keep these concepts separate.

---

# 44. Core research questions

The branch can be summarised by the following questions.

### RQ1

How expensive is exact full-information Tuppi as a function of tricks remaining?

### RQ2

How many initial full-information deals have a unique optimal root action?

### RQ3

How large are exact tactical action gaps?

### RQ4

How early do deal outcomes become guaranteed or path-invariant?

### RQ5

Across hidden worlds consistent with a real information state, how often is the same DD action optimal?

### RQ6

How large is the DD clairvoyance gap?

### RQ7

Where in the game are decisions primarily tactical versus information-sensitive?

### RQ8

Does current determinisation search fail mainly because of tactical evaluation, sampling, or strategy fusion?

### RQ9

Can the exact-search horizon be pushed substantially beyond six tricks without excessive latency?

### RQ10

Can DD-derived diagnostics improve self-play state selection and search distillation without leaking hidden information into the actor?

---

# 45. Strongest single experiment

If only one experiment is run after building Tuppi-DD, it should be:

> **Take real information states from current strong Tuppi play, sample many legally consistent hidden worlds, solve each world exactly, and measure how often the same action is optimal across worlds.**

The primary outputs are:

\[
C(I)
\]

DD action consensus,

\[
H_{\mathrm{DD}}(I)
\]

DD action entropy,

and:

\[
G(I)
\]

clairvoyance gap.

This directly tests whether the current determinisation architecture is aligned with the structure of the game.

---

# 46. Recommended project status

This should be treated as a **serious auxiliary research branch**, not merely a side curiosity.

Priority should still remain below the main self-play strength programme unless implementation proves very cheap.

However, if the existing six-trick solver can be generalised quickly, the expected information value is high.

The research branch is especially attractive because either outcome is useful:

### If full deals are easy to solve

Exact DD becomes a powerful practical component and diagnostic tool.

### If full deals are hard to solve

The node-count/complexity results establish that Tuppi has substantial intrinsic perfect-information tactical complexity.

---

# 47. Final conceptual model

A useful way to think about Tuppi is:

\[
\boxed{
\text{Tuppi difficulty}
=
\text{perfect-information tactical complexity}
+
\text{hidden-information complexity}
+
\text{partner/opponent communication effects}
}
\]

Tuppi-DD isolates the first term.

Sampling hidden worlds around real information states allows measurement of the second.

Comparing DD prescriptions with strong self-play behaviour helps expose the third.

That makes this research branch potentially much more valuable than simply asking whether a visible-card version of Tuppi is "easy."

The central goal is not to prove that the full-information game is solvable.

It is to use exact solving to understand **what kind of game Tuppi actually is**, and therefore what kind of AI has the best chance of becoming maximally strong.

---

# 48. Immediate implementation instruction for the next LLM/engineer

> Inspect the existing six-trick double-dummy implementation and determine whether it can be generalised into an exact resolved-contract Tuppi solver. Preserve authoritative v3 legality and scoring. Build a root-action-value API, not only a best-move API. Benchmark exact solve time and node count from 6 through 13 tricks remaining. Once exact solving is validated, generate an initial complexity atlas of random RAMI/NOLO deals. Then sample real information states from current bot play, generate legally consistent hidden worlds, solve them independently, and measure DD action consensus, action entropy, clairvoyance gap and rank instability. Use these measurements to determine whether current Tuppi difficulty is predominantly tactical, informational, or both, and whether determinisation search is structurally appropriate. Do not use DD actions as direct normal-play labels without accounting for strategy fusion and signalling.
