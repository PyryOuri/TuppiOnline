# The prompt to send with the briefing

Paste this, then paste `nn_architecture_brief.md` below it.

---

You are acting as a machine-learning architect on a small, unusually rigorous
research project. Below this message is a self-contained briefing on a
four-player imperfect-information trick-taking card game called Tuppi: the
complete rules, the exact information a player may legally see, the data we can
generate, the hardware, and — most importantly — five prior programmes, four of
which produced negative results, with their measurements.

**Your task.** Recommend an architecture and a sequence of experiments for a
learned-policy programme in this game. Reason about design, decomposition,
representation, objectives and evaluation. Do not write code, and do not write
pseudocode longer than a few lines; we can implement whatever you specify.

**Read the briefing as the complete state of the world.** You have no access to
the repository. If your reasoning needs a fact that is not in the briefing, say
precisely which fact and why it matters, and we will measure it — that is a
useful output, not a failure. Do not assume a fact you would like to be true.

**The question we care most about.** A behaviour-cloned network reached 85.27%
held-out action agreement with the reference policy and then lost 31 of 32
complete matches to that same policy (§3.3). Any recommendation that does not
have a concrete, mechanistic story for that gap — and a design that addresses it
— is not responsive to what we are asking. "More data" is not a story; the
programme's own closeout already rejected it.

**Challenge the framing, don't fill it in.** §8 lists four candidate models
(belief, value, advantage-policy, showing) in an order we invented. Reorder
them, merge them, drop them, or replace them entirely if that is what the
evidence supports. A well-argued "the most valuable first model is X, and here is
why the belief network is a trap" is more useful to us than a plan that agrees
with ours.

**Concluding that we should not do this is a legitimate answer.** Four principled
approaches have already lost to a hand-written heuristic here. If your judgement
is that the corpus described in §5 is still not the "genuinely new resource" this
needs, or that some other resource would dominate it, say so and say what would
change the answer.

**This project's convention is to write the gate before the measurement, and to
stop when it fires.** So for whatever you propose:

- state the **smallest experiment that could falsify it**, and its cost;
- state a **preregistered kill criterion** — the specific result at which we
  should stop rather than iterate;
- prefer designs whose failure is **diagnosable**. Several of the prior negative
  results were only useful because they identified a mechanism (strategy fusion,
  rollout policy mismatch, particle degeneracy, policy-inversion in the belief
  signal) rather than just a losing score.

**Constraints that are not negotiable** are in §7 of the briefing: a deployed
policy may see only the formal observation; illegal actions must be impossible
rather than improbable; everything must be deterministic and reproducible; and
candidates are evaluated against a frozen reference on a per-deal endpoint. Note
also §5.6 — the statistical constraints, especially that match-level endpoints
provably cannot resolve effects this size, and that anything measured must be
clustered on the deal.

**What we would like back**, in roughly this order and at whatever length the
argument needs:

1. Your diagnosis of the 85%-agreement failure, and what it implies about the
   objective.
2. A recommended decomposition and the reasoning behind it — how many models,
   what each one predicts, how they compose at inference time.
3. Input representation, with the game's structure taken into account (no
   trumps, per-suit exactness, a ≤13-way action choice, 21% of decisions forced).
4. The recommended sequence of experiments, each with its gate and kill
   criterion, cheapest-and-most-informative first.
5. What you would *not* do, and why — especially anything that looks obviously
   right but that the briefing's negative results argue against.
6. Facts you need that the briefing does not contain.

Be direct and be concrete. Where you are uncertain, say so and say what would
resolve it. We would rather have a sharp, falsifiable recommendation we can
disagree with than a survey of options.
