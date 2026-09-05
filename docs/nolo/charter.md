# NOLO mathematics: pre-registered charter

**Status: pre-registration.** Written before any mathematics was chosen and
before any number was computed. Sections 4–9 are the standing brief handed to
each independent exploration. **This file must not be edited in light of
results** — the precedent is `docs/search/phase5d_a_hypotheses.md`. Findings go
in new documents; if the charter itself turns out to be wrong, record that in
the results and leave the original text standing.

---

## 1. The question

**What is the right mathematical object for a NOLO decision, and does reasoning
in it beat the current heuristic?**

NOLO only. RAMI is out of scope for this programme.

The goal is a stronger AI, not a theory for its own sake — but the route is
deliberately mathematical rather than another turn of the measure-a-heuristic
loop. The reason is recorded in the parent handoff (`docs/valuation/handoff.md`
§1): the A/B template *"can only find the best member of a family someone
thought of in advance, and it gives no bound on what lies outside that
family."* Two of the three refinements tried that way measured zero or
negative. This programme exists to look outside the family.

Machine learning is out of scope. Phase 6 already recorded a bounded imitation
failure; this is a search for structure, not a fit.

The motivating asymmetry: notrump play in bridge has a mature body of
mathematics behind it. Misère-style trick *avoidance* has very little. If that
gap is real, the theory this project needs may not exist yet in usable form.

## 2. Gate 0 — state the game as a mathematical object

Before any mathematics is chosen, produce a cold statement of what
`project_target_v1` actually is, read from `docs/rules/project_target_v1.md`
and `src/tuppi_rules/`, not from memory or from bridge analogy:

information structure and what each seat can observe; whether there is a trump
or normal-colour mechanism and what it does; what NOLO rewards exactly, and how
a deal is scored; the showing phase and how the contract is reached; and the
rising-score match layer above the deal.

Write it down before looking at any candidate theory. Everything downstream is
checked against this document. Its purpose is to stop bridge assumptions being
imported silently — see §5.9 below, which cost real time.

## 3. Gate 1 — three independent framings

**Three** explorations, conservative by choice. Two cannot show a spread and
give nothing to break a tie; three reveals whether independent starts converge.

Each runs in a **fresh context and does not see the others' output.** A single
thread anchors on its first plausible framing and then rationalises; the whole
point of the gate is to measure disagreement. Where the three disagree is the
information. Convergence from independent starts is weak evidence but real; one
confident thread is none.

Each exploration answers: **what area of mathematics governs NOLO play, and
why that one?** For every candidate area it names — including ones it rejects —
it states:

1. what object the area models, and the mapping to the Gate 0 statement;
2. what assumptions it needs, and whether they hold *here*;
3. what it predicts the current bot does wrong, concretely enough to point at a
   decision;
4. the cheapest observation that would falsify it;
5. why it survives, or does not survive, §6 below.

**Rejections are written up, with reasons.** The parent handoff's §2 is the most
valuable part of that document precisely because it records what failed.

## 4. What is already established about NOLO — do not re-derive

Assets, with their sources. `docs/valuation/phase_a_results.md` and
`phase_c_results.md` hold the full numbers and caveats.

- **Ducking decomposes into independent rounds**, so a holding's value is
  **additive across its own cards**, and only your lowest *k* matter when the
  suit is led *k* times. Spot cards are worth up to **1.63 tricks** within a
  fixed honour skeleton.
- **Bottom-holding closed form** `max(0, min(k, L) − M)`, and suit survival
  ≈ `(16 − L)/3`.
- **The mid-deal exhaustion law** (`suits.general_split_distribution`,
  `general_rounds_survived`, `expected_suit_tricks`): the opening law
  generalised to outstanding count, current hand sizes and proven voids.
  Reproduces the opening law exactly, and responds correctly to evidence — with
  5 held / 5 out, one void drops expected length winners 2.33 → 1.66, two voids
  force everything into one hand giving **0.000**.
- **Strength runs backwards in NOLO.** HCP's equity coefficient is **+0.0064 in
  RAMI and −0.0022 in NOLO**; all *shape* descriptors flip sign between
  contracts, *strength* ones only attenuate.
- **Being on lead is not a liability.** Leader wins 25.5%, followers 22.2% /
  24.8% / 27.5% — flat. (RAMI's leader wins 71.6%; it is a different game.)
- **Followers unload high.** NOLO followers with a genuine choice play their
  highest **51.0%** of the time, and **78.8%** from fourth seat, dumping high
  cards onto a trick their side is taking anyway.
- **Discards are common**: ~30% of follower plays, and NOLO opponents shed
  1.45–1.71 of their 4–7 cards, so suits empty without being led.
- **The shipped NOLO lead** (`partner_aware_lead_v2`): shortest suit, lowest
  card within it — **−0.69 tricks, +13.9 pp**, and dominant (+12.2 pp even when
  opponents lead the same way). Within the suit, leading lowest is monotone
  across a rank-cap sweep; there is no middle ground.

**The open hook.** `suits.layouts()` enumerates every exact layout of a suit's
outstanding cards with its true probability — filtering it on observations *is*
exact Bayesian inference over that suit — and `play.walk_deal()` already
extracts the observations. **Nothing joins them.** The parent handoff notes
this is the machinery a real NOLO ducking decision needs (§1.1).

## 5. What was tried and failed — do not re-derive

Full detail in `docs/valuation/handoff.md` §2. NOLO-relevant summary:

- **The play-rule ↔ contract mapping was backwards** in the original code, and
  the two rules do not bracket the truth: K‑7‑2 over three leads takes 0.792
  tricks ducking and **exactly 0** competing.
- **Discards do not break the bottom-holding closed form** (mean error ≤ +0.020
  tricks; correlation with opponent discards ≈ 0). It survives because it
  conditions on the *observed* k.
- **"Void your cheapest suit" is worth nothing** (−0.007, z = −0.2). Length is
  the entire story.
- **Answering the partner's shortness signal measures negative** — leading
  their signalled short suit: +0.094 (z = +1.2); delayed, +0.053; honouring a
  partner's *proven* void ahead of your own shortest: +0.006 (z = +0.2). You
  give up your own void, which is worth −0.69.
- **Descriptor weights do not change between up and down** — no |z| reaches 2.
  What changes is scale: the same hand is worth ~2.6× more at either extreme.
- **Establishment with the wrong prior is worth nothing** (−0.032, z = −0.4).
  The same idea restricted to the first 3 tricks measured +0.254, and on the
  live mid-deal law **+0.360**. *The same idea is worthless or strong depending
  only on whether the probability law fits the position.*
- **A bridge maxim is a compressed summary of a specific information structure
  and a specific scoring rule.** Second-hand-low and third-hand-high, imported
  into following, measured −0.102 and −0.107; both together −0.207 (−5.0 pp).
  Second-hand-low is a *defensive* maxim that assumes a **visible dummy**;
  Tuppi has none. Check which of the two you are importing before assuming it
  transfers.

## 6. What survives not knowing the opponents' policy

The parent handoff calls this its most important methodological finding (§3.1),
and it is the sharpest known constraint on any inference scheme:

- **Certain**: a discard proves a void; cards seen are cards gone.
- **Robust under rationality, not policy**: a seat that took a trick it *could
  have ducked* held nothing below the current high. This fires often — **45% of
  NOLO follower choices** are in the branch where every held card would
  currently win.
- **Policy noise**: which low card someone ducks with, which rank a leader
  chooses. Assuming opponents duck their lowest makes a played card look highly
  informative (E[their length] 3.84 down to 1.40 against 3.36 unconditional);
  drop the assumption and read it as `min ≤ c`, and **1–5%** of that signal
  survives. The original table was measuring the bot's own determinism.

Related: `partner_aware_v1` leads its lowest card **100%** of the time, so any
lead-rank inference fitted on a corpus generated by it is measuring a constant.
The project owner confirms real players' leads are not predictably lowest.

**This is evidence to reckon with, not a prohibition.** A framing that needs
opponent policy is not excluded — but it must say how it survives §3.1, or why
that measurement does not bind it.

## 7. Leeway

**Nothing is ruled out.** No area of mathematics is off the table, including
ones this repository's evidence appears to disfavour, and including ones with
no precedent in trick-taking games. An exploration may propose that the right
object is something no one has applied here, and may argue that an existing
negative result was a failure of implementation or of endpoint rather than of
the idea — §4.2 is exactly that story, and §1.6 argues the same may be true of
the whole Phase 5 programme.

What leeway does not license: skipping the falsification question, or asserting
that a mapping holds without checking it against the Gate 0 statement.

Candidate areas are deliberately **not** listed anywhere in this charter. Naming
them would anchor the explorations and destroy the only property Gate 1 has.

## 8. Method of test

Any claim that reaches measurement follows the discipline the parent programme
paid for:

- **Pre-register before computing.** The first validation of the closed form
  reported "100% exact on 92 holdings" and was worthless: every case predicted
  zero and observed zero. **Check a test can fail before believing it passed** —
  this trap recurred and was caught both times only by a deliberate diagnostic.
  Use `tuppi_valuation.designed` to deal a chosen holding when the interesting
  regime is one random deals never reach.
- **Paired on identical deals**, always. Seed variation is larger than z-scores
  suggest: the same shipped policy measured **+0.164 (z = +2.4)** and **+0.360
  (z = +5.1)** on two seeds at 500 deals each. When a number moves, re-run
  like-for-like before believing the first explanation.
- **Per-deal or per-decision endpoints**, not whole-match win rate. A
  whole-match endpoint needs ~33 deals to resolve one sample, and effects of the
  size found here are invisible at 32 match pairs.
- **Cluster over deals** — the four seats share exactly 13 tricks and are not
  independent: `metrics.regress(..., cluster=lambda r: r.deal_id)`.
- **Control contract selection** with `ContractCondition.FORCED_NOLO`. Mean HCP
  per seat is 10.00 in every arm by construction, so that diagnostic cannot
  detect selection at all; the bias is in who declares.
- **Check dominance**, not just advantage: is it still ahead when the opponents
  play the same way?
- Fix corpora with `CorpusSpec` (profile, count, seed, starting score, contract
  condition) so a result is reproducible from the spec alone. Use
  `equity.record_equity_delta_at` when equity is the right outcome variable —
  though note the rising-score equity work has never yet changed a card anyone
  plays.

## 9. Repository constraints for anything that ships

From `docs/valuation/handoff.md` §7. Breaking these wastes a lot of time.

- **The Phase 4 registry is frozen** and digest-verified. Do not register or
  alter a profile — **subclass**, as `src/tuppi_agents/void_lead.py` does.
- A new policy expresses its preference as a **score component**, not a
  catalogued rule id; `SIMULATION_VALIDATED` provenance is forbidden for Phase 4,
  deliberately, so the baseline stays an independent yardstick.
- A policy must be a **real `RuleBasedPolicy`**: analysis reads the full ranking
  via `decide()`/`explain()`, and `ScoredActions` enforces that the selection
  *is* the lexicographic maximum. A wrapper overriding `choose_action` breaks
  diagnostics.
- **Package direction is one-way.** `tuppi_agents` may import neither
  `tuppi_valuation` nor `tuppi_exact` — which is why `void_lead.py` carries its
  own copy of the suit maths, pinned by a test asserting exact `Fraction`
  equality against the canonical version. Expect to do the same.

## 10. Stopping rules

Write the negative result and stop when: the mapping to the Gate 0 statement
fails on an assumption that cannot be repaired; the falsifying observation from
Gate 1 comes back against the framing; or the framing turns out to predict
exactly what the current heuristic already does, in which case it is an
explanation rather than an improvement — worth recording as such.

A direction abandoned with its reasons written down is a result. §2 of the
parent handoff is more useful than §4.

## 11. Artifacts

- `docs/nolo/game_object.md` — the Gate 0 statement.
- `docs/nolo/framings/{1,2,3}.md` — the three independent Gate 1 outputs,
  written before any comparison.
- `docs/nolo/framing_comparison.md` — the adversarial comparison, including
  where they disagreed.
- `docs/nolo/hypotheses.md` — pre-registered, before any measurement.
- Results documents thereafter, one per question settled.
