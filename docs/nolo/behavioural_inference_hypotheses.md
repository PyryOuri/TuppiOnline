# Pre-registered: behavioural inference for the training overlay

**Status: pre-registration.** Written before the measurement was run. **Must not
be edited in light of the numbers** — the precedent is
`docs/search/phase5d_a_hypotheses.md`. Results go in a separate document. If a
hypothesis here turns out to be badly posed, say so in the results and leave
this text standing.

---

## 1. The question

The training overlay currently reasons from **hard facts only**: cards seen are
gone, a discard proves a void, a `verbal_required` show proves a whole-hand
exclusion, and a shown card is known to still be held. It uses nothing about
*which* card an opponent chose to play. `tuppi_exact.counting` is explicit that
its measure is "not a posterior over opponents' hands, because a real posterior
depends on the policies that produced the observed actions."

Two candidate behavioural rules would add exactly that, and both are expressible
as ordinary card exclusions in the existing `HardConstraintModel` — so if they
hold, the entire exact pipeline (split law, per-card marginals, ~8 ms) applies
unchanged, with no new mathematics and no belief model.

The question is whether they are true often enough, and informative enough, to
be worth showing — and what should be shown to a **learner** rather than to a
bot-beating tool.

## 2. The candidate rules, stated exactly

Let seat `S` follow suit `L`, let `h` be the highest rank of `L` played so far in
the current trick, and let `c` be the card `S` plays.

**Rule (a) — duck high.** If `c < h`, then `S` holds no card of `L` with rank
strictly between `c` and `h`.
*Rationale: high cards are pure liability in NOLO, so when losing the trick
anyway, shedding the most dangerous card that still loses is close to forced.*

**Rule (b) — win high.** If `c > h`, then `S` holds no card of `L` above `c`.
*Rationale: a trick already being taken is the cheapest place to dump a high
card.*

Both exclusions are **monotone**: a seat cannot gain cards, so an exclusion
established at one trick remains true for the rest of the deal.

Deferred, not measured here: the partner's NOLO lead being their shortest suit
(measured at 100% in `docs/valuation/handoff.md` §1.4). It constrains a hand's
shape across suits rather than naming excluded cards, so it needs different
machinery and is out of scope for this measurement.

## 3. The vacuity guard

**Mandatory.** "Played the largest losing card" is automatically true when only
one losing card is held. A denominator that includes forced plays inflates the
rate toward 100% while measuring nothing — this is §2.7's trap, where a
validation reported "100% exact on 92 holdings" and every case predicted zero
and observed zero.

Every rate below is therefore conditioned on the **non-trivial branch**:

- rule (a): `S` holds **at least two** cards of `L` below `h`;
- rule (b): `S` holds **at least two** cards of `L` above `h`.

Both the trivial and non-trivial counts are reported. A rate is not to be quoted
without its denominator. **An earlier informal probe by the assistant did not
apply this conditioning and its 100%/57% figures are therefore not evidence for
anything; they are superseded by this measurement.**

## 4. Hypotheses

**H1 — rule (a) describes the reference policy.** On the non-trivial branch, the
proportion of ducks played with the highest losing card. Reported per profile,
with a cluster-bootstrap interval.

**H2 — rule (b) describes the reference policy.** The same for wins played with
the highest card above `h`.

**H3 — soundness against ground truth (decisive).** Applying each rule's
exclusions across a deal, the proportion of firings that exclude a card the seat
**actually held**, checked against the true hands. This is the test that matters:
a rule can describe the policy well and still be wrong often enough to poison the
model, and an excluded-but-true card makes the constraint system infeasible.

**H4 — informativeness.** When a rule fires, how many cards it excludes, and the
resulting reduction in `feasible_assignment_count`. A rule that is always true
but excludes nothing is not worth shipping.

**H5 — stability across the two references.** Whether the rates differ between
`partner_aware_v1` and `partner_aware_lead_v2`. Only the *leads* were changed
(§4.1), so following behaviour is expected to be identical — a pre-registered
expectation that is allowed to fail.

## 5. Pre-specified decision rules

Written now so the outcome cannot be rationalised afterwards.

**Ship a rule as a labelled layer** only if all three hold:

1. non-trivial rate **≥ 95%**, lower bound of the interval ≥ 90%;
2. ground-truth exclusion error (H3) **≤ 1%**;
3. median cards excluded per firing **≥ 1**.

**Reject** if any of: ground-truth error **> 5%**; non-trivial rate **< 90%**;
median cards excluded is 0.

**Between those bands**, ship only behind an explicit toggle, defaulted off, with
the measured rate shown next to it.

**Under-powered** if fewer than **500 non-trivial observations** per rule per
profile: report as under-powered and do not ship on it, rather than quoting the
point estimate.

The informal probe suggests (a) may pass and (b) may fail at roughly 57%.
Recording that expectation here means a contrary result is reportable rather
than convenient.

## 6. Method

- **Corpus**: `CorpusSpec` fixing profile, deal count, seed and starting score,
  with `ContractCondition.FORCED_NOLO` — mean HCP per seat is 10.00 in every arm
  by construction, so that diagnostic cannot detect contract selection (§3.4).
- **Profiles**: `partner_aware_v1` and `partner_aware_lead_v2`, measured
  separately and never pooled. All four seats run the profile under test; this
  measures bot opponents, which is what sits at the table today.
- **Clustering**: bootstrap over `deal_id`
  (`metrics.regress(..., cluster=lambda r: r.deal_id)`). One deal contributes
  many correlated follower decisions; the four seats share exactly 13 tricks
  (§3.3).
- **Two independent seeds.** The same shipped policy has measured +0.164 and
  +0.360 on two seeds at 500 deals each; one seed is not a measurement.
- **Falsifiability check before believing any result**: confirm the non-trivial
  branch actually fired with a real denominator, and that the ground-truth test
  is capable of returning a violation at all. If either cannot fail, the run is
  vacuous and is reported as such.

## 7. What this measurement does not establish

It describes **a deterministic program**, not the game. A rate of 100% against a
bot means the rule *is* that bot's rule — the §3.2 warning that inference fitted
on this corpus is "measuring a constant." Nothing here licenses the claim that
human opponents duck high, and the project owner has already confirmed real
players' leads are not predictably lowest.

This bears directly on the product decision. The overlay exists to make a
*person* better at Tuppi. A number silently sharpened by an assumption about how
these particular bots play teaches a read that may not survive a human table.
Whatever ships should therefore show the hard-fact figure and the
assumed-behaviour figure **side by side**, with the assumption named, so the
difference between them is visible as the cost of the assumption rather than
hidden inside a single confident percentage.

## 8. Artifacts

- `tools/measure_nolo_following.py` — the measurement, reproducible from the
  corpus spec alone.
- `docs/nolo/behavioural_inference_results.md` — the numbers, the denominators,
  and the decision that follows from §5.
