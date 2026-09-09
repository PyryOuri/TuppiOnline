# S1b results: the showing intervention is killed at this scope

**Status: COMPLETE. Outcome: SCIENTIFIC KILL.**

Pre-registration: [hypotheses_s1b.md](hypotheses_s1b.md), committed as `c3bfc56`
**before** the instrument was modified and before any S1b data existed. Run
2026-09-09. Artifacts at
`/Users/pyryouri/Developer/TuppiRuns/phase7/s1b/s1_headroom.json`.

The pre-registration predicted this outcome and stated three ways it could have
failed. None of them occurred.

---

## 1. The result

131 072 rollouts on fresh seeds (`tuppi-s1b-headroom-v1`), 192.7 s on 12 workers.

| Quantity | Value | 95% CI | Gate |
| --- | ---: | --- | --- |
| `G_deploy` — cross-fitted selector | +0.000131 | [+0.000000, +0.000273] | lower bound < δ, no PASS |
| **`G_legal_eb`** — what a perfect legal selector would gain | **+0.000233** | **[+0.000141, +0.000340]** | **upper bound < δ → KILL** |
| `G_legal_upper` — S1's unpowered bound, for reference | +0.001138 | [+0.000915, +0.001384] | still unreachable, as expected |
| `G_foresight` — the oracle | +0.005940 | — | — |
| signal share | 0.902 | — | ≫ 0.25, not degenerate |
| δ | 0.001000 | — | — |

`G_legal_eb`'s upper bound of **+0.000340 is a third of δ**. The pre-registered
scientific kill fires.

## 2. It replicated

Every quantity landed within noise of S1, on disjoint hands and disjoint
completions:

| | S1 | S1b |
| --- | ---: | ---: |
| `G_legal_eb` | +0.000217 | **+0.000233** |
| `G_deploy` | +0.000096 | +0.000131 |
| `G_foresight` | +0.006223 | +0.005940 |
| signal share | 0.894 | **0.902** |
| observations favouring the alternative | 9.6% | 10.2% |
| mean per-completion Δ | −0.0186 | −0.0194 |
| completions where the intervention mattered | 85.7% | 85.5% |
| reference's RAMI rate at the first show | 24.8% | 22.1% |

The pre-registration predicted `G_legal_eb` "between roughly +0.0001 and
+0.0004". It came in at +0.000233.

Its three named failure modes did not occur: the upper bound did not land above
δ, `G_deploy` did not reach δ, and the signal share did not collapse — it
reproduced to within 0.008.

## 3. What the kill establishes

**At the forehand's first showing decision, with the alternative card chosen by
the declared lowest-eligible-rank selector, against the frozen reference at 0-0,
a perfect observation-compatible selector is worth about +0.00023 equity per
deal — roughly a quarter of the funding threshold.**

Two readings of the same fact:

- **The signal is real and it says "don't deviate".** 90.2% of the spread across
  hands is genuine between-hand variation, not measurement noise. The forehand's
  hand does predict whether the other declaration would have been better. It
  almost always predicts that it would not: the intervention changes the outcome
  in 85.5% of completions and is worth −0.0194 on average.
- **The oracle's advantage is almost entirely unlearnable.** A perfect legal
  selector captures **3.9%** of what an oracle seeing the hidden layout captures
  (+0.000233 against +0.005940). The remaining 96% is irreducible hidden-layout
  variance — exactly the `G_legal ≤ G_foresight` gap the review argued §1.7 had
  conflated.

**Consequence: Experiment 2 is not funded on this scope.** There is nothing
worth amortising into a network here. The reference's declaration rule is
already within a quarter of a threshold of the best any observation-only policy
could do at this decision.

## 4. What it does not establish

Fixed in advance by `hypotheses_s1b.md` §4, and repeated because a kill invites
over-reading:

- **Nothing about card play**, which is 95.3% of decisions and untouched here.
- **Nothing about a freely chosen alternative card.** The alternative arm was one
  declared policy. The rules permit up to **26** legal showing actions and a
  candidate free to choose among them has a larger action space that was not
  tested.
- **Nothing about later showing seats**, which decide after observing passes —
  the policy-dependent inference this design deliberately avoided.
- **Nothing about non-zero scores.** Equity is strongly convex in the score and
  this was measured at 0-0 only.
- **Nothing about transfer.** Every seat was the reference.
- **Nothing about whether a learned Tuppi player is possible.**

## 5. What this cost, and what it bought

| | |
| --- | ---: |
| S1 + S1b together | 262 144 rollouts, **6.2 minutes** on the Mac |
| the deferred T1 corpus | 10M deals, 5.2 h Mac / 20.1 h Fedora |
| brute-forcing S1's broken gate instead | 13.5M rollouts, 5.1 h Mac / 19.8 h Fedora |

Six minutes closed the question that the charter had budgeted a 10M-deal corpus
and four network programmes to approach. That is the review's argument working
as intended: put the cheapest, most favourable, most diagnosable test first so
that a negative result is affordable.

It also cost one wasted experiment — S1's unpowered gate — which is itself the
argument for the ordering. A three-minute experiment can be wrong and thrown
away. A 20-hour corpus and a trained network cannot.

## 6. Where the programme goes

The review's Experiment 2 is dead at this scope. Three live questions remain,
each needing its own pre-registration and none authorised by this result:

1. **A freely chosen showing action.** Up to 26 legal actions rather than two.
   The oracle gain is +0.0059, so the ceiling is not zero; the question is
   whether a larger action space converts more of it. Cheap to test with the
   same instrument.
2. **Card play**, the review's Experiment 4 — 95.3% of decisions, and the corpus
   already measured that runner-up substitutions change the outcome in only
   25.7% of pairs, which is a different and harder signal problem.
3. **The reference against competent humans.** The review's closing suggestion,
   and the one thing no amount of self-play measures. With zero
   expert-validated strategy rules, this may dominate both of the above.

The charter's D7 stands: T1 remains deferred, and it should stay deferred until
one of those questions produces a reason to generate it.
