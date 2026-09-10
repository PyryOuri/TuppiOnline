# C3 results: 64 worlds clears δ, at 1.08 s per decision on ten cores

**Status: COMPLETE. Outcome: AFFORDABLE at W = 64.**

Pre-registration: [hypotheses_c3.md](hypotheses_c3.md), committed as `8eb1d67`
before `work/cardplay/c3_worlds.py` existed. Run 2026-09-10, 511 of 512
observations, 850,304 rollouts, 1,108 s at ten workers. Artifacts under
`/Users/pyryouri/Developer/tuppi_c3_worlds_20260910/`.

## 1. Instrument gates — all three pass

Checked before any science was read, per §4.

| Gate | Result |
| --- | --- |
| **I1** `G_deploy(W) <= G_foresight` for every W | **pass** (foresight +0.016136) |
| **I2** paired increments non-negative | **pass** — every one positive |
| **I3** decelerating: `32->64 < 4->8` | **pass** (0.000215 < 0.000530) |

Paired increments: `1->2` +0.000549, `2->4` +0.000098, `4->8` +0.000530,
`8->16` +0.000509, `16->32` +0.000363, `32->64` +0.000215.

This is the first run in the sequence whose estimator survived its own
consistency checks. S1 lost a run to an unreachable gate and C1 to an
inconsistent one; declaring I1–I3 in advance is what changed.

## 2. The curve

| W | `G_deploy` | 95% CI | rollouts/decision | s single | s ×10 | clears δ |
| ---: | ---: | --- | ---: | ---: | ---: | :---: |
| 1 | **−0.000794** | [−0.001975, +0.000393] | 13 | 0.17 | 0.02 | no |
| 2 | −0.000246 | [−0.001151, +0.000652] | 26 | 0.34 | 0.03 | no |
| 4 | −0.000148 | [−0.000820, +0.000530] | 52 | 0.68 | 0.07 | no |
| 8 | +0.000382 | [−0.000136, +0.000906] | 104 | 1.36 | 0.14 | no |
| 16 | +0.000891 | [+0.000500, +0.001284] | 208 | 2.71 | 0.27 | no |
| 32 | +0.001255 | [+0.000954, +0.001574] | 416 | 5.42 | 0.54 | no |
| **64** | **+0.001470** | **[+0.001226, +0.001717]** | 832 | 10.84 | **1.08** | **yes** |

Measured throughput inside this run: 767 rollouts/s aggregate on ten workers,
77 rollouts/s per process.

`G_deploy(64) = +0.001470` reproduces C1's +0.001441 under the same conditioning
to within 2%, on a fresh seed. That is a genuine replication of the one number
C1's defect did not touch.

## 3. Two results worth separating from the headline

**A one-world selector is actively harmful.** `G_deploy(1) = −0.000794`. Picking
the argmax over a single sampled world is picking noise, and the reference's own
choice beats noise. §4 explicitly declined to assert `G_deploy(1) ≈ 0` as a gate,
recording that a small positive value was expected there. It is neither zero nor
positive — the non-gate was right to exist and my stated expectation for it was
still wrong.

**δ is cleared only at W = 64.** §7 predicted "clearing δ between W = 8 and
W = 32". W = 32's lower bound is +0.000954, just under δ = 0.001. **The prediction
is wrong**, the second miss in two runs: C1's direction and now C3's threshold
location. Recording both because §7 exists for exactly this.

**64 worlds is not the asymptote.** I3 passed, so the curve is decelerating, but
the `32->64` increment is still +0.000215. The plateau lies somewhere above
+0.00147, so the perfect observation-only selector — the quantity C2 is meant to
bound — is plausibly around +0.0016 to +0.0020. **Descriptive only.** An asymptote
read off seven correlated points is not a substitute for a declared estimator, as
§6 said in advance.

Ratio to foresight: `G_deploy(64) / G_foresight` = **9.1%**, against the **3.9%**
S1b measured for a perfect observation-only selector at showing.

## 4. What "affordable" does and does not mean

**Does:** 832 rollouts for one opening-lead decision, **1.08 s on ten of this
machine's fourteen cores**, comfortably inside the ten-second requirement.

**Does not:**

- **Single-process it is 10.84 s — over budget.** The result depends on
  parallelism, which the charter permits but which interacts with the watchdog
  rule that an overrun is a failure rather than a silent fallback. Ten cores for
  one card, while a server and UI also run, is a scheduling claim this run does
  not test.
- **This is the opening lead only.** Later decisions have fewer arms and shorter
  rollouts, so they are cheaper, but C3 measured none of them and the per-deal
  total is not established.
- **Both arms continue with the frozen reference.** This is opening-lead
  selection, not PIMC play. A real search agent replaces the continuation too, and
  nothing here says what that costs or gains.
- **It is not production qualification.** The ten-second requirement covers
  showing, encoding, transfers, synchronisation and first-move lazy initialisation
  under a watchdog, on a machine doing other work. A measured decision cost on an
  idle host is a necessary condition, not the qualification.

## 5. What this licenses

A **changed premise** for reopening world-sampling search, which the charter lists
as not a current implementation order. The premise that changed: at the opening
lead, a 64-world sampler beats the frozen reference by +0.00147 equity per deal
with an interval excluding δ, replicated across two conditioning models and two
seeds, and it costs about a second on this machine.

Reopening is a governance decision, not mine. What it does **not** license is a
candidate: no policy was modified, none was promoted, and `research_candidates`
gained no entry.

## 6. Cost

| | Rollouts | Wall clock |
| --- | ---: | ---: |
| C3 | 850,304 | 18 min at 10 workers |
| C1 both variants | 1,657,344 | 40 min |
| S1 + S1b | 262,144 | 6.2 min |
| the deferred T1 corpus | 10M deals | 5.2 h |

Eighteen minutes produced a replicated above-δ signal, a cost curve, and the
first estimator in this sequence to pass its own consistency checks.
