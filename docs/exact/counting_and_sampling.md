# Exact counting, and exactly uniform sampling

Two exact answers, and one caveat that matters more than either.

## Counting

`feasible_assignment_count(model)` returns the exact integer number of
hidden-hand assignments the hard public constraints permit. Not an estimate, not a
bound.

The method rests on one structural fact: **two unknown cards with the same
allowed-seat set are interchangeable.** Nothing in the constraint system can tell
them apart, so the whole problem collapses to a transportation problem over at
most fifteen equivalence classes (one per nonempty subset of the four seats) and
at most three open seats. A dynamic program over residual capacity vectors, with a
multinomial factor for the cards inside each class, counts it exactly - no
permanent, no inclusion-exclusion, no sampling.

A worked example, from `tests/exact/test_counting_and_sampling.py`. Two classes,
three open seats with capacities `(3, 2, 2)`:

| Class | Allowed seats | Cards |
| --- | --- | --- |
| A | `{0, 1}` | 4 |
| B | `{0, 1, 3}` | 3 |

Only two splits of class A are possible within the capacities:

- A splits `(2, 2)` - leaving `(1, 0, 2)`, so B must split `(1, 0, 2)`:
  `C(4;2,2) x C(3;1,0,2) = 6 x 3 = 18`
- A splits `(3, 1)` - leaving `(0, 1, 2)`, so B must split `(0, 1, 2)`:
  `C(4;3,1) x C(3;0,1,2) = 4 x 3 = 12`

Total 30, which the DP returns and brute-force enumeration confirms.

### Exact marginals

`exact_ownership_counts` gives, per unknown card, how many assignments place it at
each seat; `exact_uniform_marginals` converts those to exact `Fraction` values.
The reduction is simple and exact: pin the card to the seat, remove it from its
class, decrement that seat's capacity, and recount. The other cards of the class
stay free, because pinning one member of an interchangeable group says nothing
about the rest.

Two identities are asserted at every decision of replayed deals:

- the four per-seat counts sum to the total feasible count;
- the count for the *true* owner is always strictly positive.

The second is the soundness check restated in counting terms: an exclusion that
wrongly ruled out the truth would drive its count to zero.

## Sampling

`UniformFeasibleSampler` draws from the uniform distribution over feasible
assignments **exactly**. No Markov chain, no reject-the-whole-assignment loop, no
repair step.

The construction follows the count. For each prefix of the class decomposition
the DP already knows how many completions each residual capacity vector admits, so
choosing a split with probability proportional to
`multinomial(split) x completions(rest)` is uniform over assignments by
construction. Choosing *which* specific cards fill each part uses combination
unranking, which is uniform over the `C(n, k)` possibilities. Two exactly uniform
choices compose to an exactly uniform result.

### The integer source is unbiased

`DeterministicBitSource` draws bits from `sha256(seed || counter)` blocks and uses
**rejection** on exactly `bound.bit_length()` bits, so `below(bound)` is exactly
uniform on `range(bound)`.

The deal generator's documented `sha256_counter_fisher_yates_modulo_v1` shortcut
is deliberately not reused. Modulo bias is negligible when reducing 256 bits to
52, but a sampler whose entire claim is exact uniformity must not carry any bias
at all, and "negligible" is not "none".

Determinism: the stream seed is a content digest over the caller's seed and the
constraint model's own identity, so the same request reproduces the same
assignments in the same order, and a prefix of a longer draw equals a shorter
draw. No module-global random state is touched.

### Draws are independent, and repeats are kept

`sample(n)` draws `n` independent assignments. Duplicates are possible when the
feasible set is small, and they are **not** filtered: removing them would produce
a sample uniform over *distinct* assignments, which is a different distribution
and would need to be stated as such.

### Uniformity is tested, not asserted

`test_sampling_covers_every_feasible_assignment_uniformly` picks a position whose
exact count is small enough to enumerate, draws 200 times the count, and requires
that every feasible assignment appears and that the chi-square statistic stays
below three times its degrees of freedom. A sampler that missed part of the space,
or leaned within it, fails.

## The caveat: uniform-over-feasible is not a posterior

This is the most consequential sentence in the package.

A **posterior** over the opponents' hands would condition on the fact that the
opponents chose the actions they chose. Computing it requires a model of *how*
they choose - and this package contains no policy model whatsoever. What the
sampler produces is the **neutral reference measure**: every assignment the hard
facts permit is one object, weighted equally, because the facts genuinely cannot
distinguish them.

That makes it:

- **correct** as a determinization scheme whose bias is stated rather than hidden;
- **the right baseline** against which a later phase's belief model must justify
  itself - a belief model that cannot beat uniform-over-feasible has not earned
  its complexity;
- **wrong** to read as "the chance seat 2 holds the ace".

The distinction is enforced in the record, not only in prose:
`UniformFeasibleSampler.provenance()` emits
`is_posterior_over_opponent_hands: false` and a `posterior_caveat` string, and
`schemas/exact/hidden_hand_sampling.schema.json` declares that field `const false`
- a record claiming otherwise is schema-invalid.

## Cost

Counting is a DP over at most `14^3` capacity vectors and at most fifteen classes,
so it is microseconds even with 39 unknown cards, where the count itself is around
`8.4 x 10^16`. Sampling adds one DP walk plus one unranking per class. Neither is
a bottleneck; the exact solver is.
