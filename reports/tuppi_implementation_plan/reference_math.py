"""Pure, finite mathematical checks for the implementation specification.

Standard library only. This is NOT a Tuppi engine, agent, or benchmark. It does
not import or execute any uploaded source, model, native library, or fixture.
The tests establish only the small identities and counterexamples stated here.
Run: python reference_math.py --json DESIGN_MATH_RESULTS.json
"""
from __future__ import annotations

import argparse
import json
import unittest
from fractions import Fraction as F
from itertools import product
from pathlib import Path
from typing import Sequence


def expectation(values: Sequence[F], probabilities: Sequence[F]) -> F:
    if len(values) != len(probabilities) or not values:
        raise ValueError("A nonempty value and probability pair is required")
    if any(p < 0 for p in probabilities) or sum(probabilities, F(0)) != 1:
        raise ValueError("Probabilities must be nonnegative and sum to one")
    return sum((v * p for v, p in zip(values, probabilities)), F(0))


def variance(values: Sequence[F], probabilities: Sequence[F]) -> F:
    mean = expectation(values, probabilities)
    return expectation([(v - mean) ** 2 for v in values], probabilities)


def cv_one_draw_distribution(d: Sequence[F], g: Sequence[F], p: Sequence[F],
                             beta: F) -> tuple[list[F], list[F]]:
    """One independent cheap draw and one expensive paired draw."""
    if len(d) != len(g) or len(d) != len(p):
        raise ValueError("Lengths differ")
    outcomes, probabilities = [], []
    for cheap, expensive in product(range(len(p)), repeat=2):
        outcomes.append(beta * g[cheap] + d[expensive] - beta * g[expensive])
        probabilities.append(p[cheap] * p[expensive])
    return outcomes, probabilities


def information_value(payoffs: Sequence[Sequence[F]], weights: Sequence[F],
                      keys: Sequence[str]) -> F:
    """One later action per key, not one per hidden world."""
    if not payoffs or len(payoffs) != len(weights) or len(keys) != len(weights):
        raise ValueError("Bad world dimensions")
    if sum(weights, F(0)) != 1 or any(w < 0 for w in weights):
        raise ValueError("Bad weights")
    n_actions = len(payoffs[0])
    if not n_actions or any(len(row) != n_actions for row in payoffs):
        raise ValueError("Bad action dimensions")
    groups: dict[str, list[int]] = {}
    for i, key in enumerate(keys):
        groups.setdefault(key, []).append(i)
    return sum((max(sum((weights[i] * payoffs[i][a] for i in ids), F(0))
                    for a in range(n_actions))
                for ids in groups.values()), F(0))


def solve_linear(a: Sequence[Sequence[F]], b: Sequence[F]) -> list[F]:
    """Small exact Gaussian elimination oracle; not a large-kernel solver."""
    n = len(b)
    if n == 0 or len(a) != n or any(len(row) != n for row in a):
        raise ValueError("Square nonempty system required")
    aug = [[F(x) for x in row] + [F(bi)] for row, bi in zip(a, b)]
    for col in range(n):
        pivot = next((i for i in range(col, n) if aug[i][col] != 0), None)
        if pivot is None:
            raise ValueError("Singular system: absorption/value not identified here")
        aug[col], aug[pivot] = aug[pivot], aug[col]
        scale = aug[col][col]
        aug[col] = [x / scale for x in aug[col]]
        for row in range(n):
            if row != col:
                scale = aug[row][col]
                aug[row] = [x - scale * y for x, y in zip(aug[row], aug[col])]
    return [row[-1] for row in aug]


def kernel_value(p: Sequence[Sequence[F]], r: Sequence[F]) -> list[F]:
    n = len(r)
    if len(p) != n or any(len(row) != n for row in p):
        raise ValueError("Kernel shape mismatch")
    for row, win in zip(p, r):
        if win < 0 or any(x < 0 for x in row) or sum(row, F(0)) + win > 1:
            raise ValueError("Invalid substochastic row")
    return solve_linear([[F(i == j) - p[i][j] for j in range(n)]
                         for i in range(n)], r)


def next_score(score: tuple[int, int], winner: int, points: int) -> tuple[int, int]:
    """Pure arithmetic interpretation of the supplied rising-score rules.

    It intentionally is not represented as an authoritative engine function.
    """
    if winner not in (0, 1) or points <= 0 or points % 4:
        raise ValueError("Invalid winner or positive award")
    if any(x < 0 or x % 4 or x >= 52 for x in score) or all(score):
        raise ValueError("Invalid nonterminal source score")
    if score == (0, 0):
        return (points, 0) if winner == 0 else (0, points)
    up = 0 if score[0] else 1
    if winner != up:
        return (0, 0)
    return (score[0] + points, 0) if up == 0 else (0, score[1] + points)


def unresolved_bounds(wins: int, losses: int, unresolved: int) -> tuple[F, F]:
    if min(wins, losses, unresolved) < 0 or wins + losses + unresolved == 0:
        raise ValueError("Nonempty nonnegative counts required")
    total = wins + losses + unresolved
    return F(wins, total), F(wins + unresolved, total)


class MathematicalChecks(unittest.TestCase):
    def setUp(self) -> None:
        self.d = [F(0), F(2)]
        self.g = [F(1), F(-1)]
        self.p = [F(1, 2), F(1, 2)]

    def test_cv_wrong_proxy_is_unbiased(self) -> None:
        vals, ps = cv_one_draw_distribution(self.d, self.g, self.p, F(7, 3))
        self.assertEqual(expectation(vals, ps), expectation(self.d, self.p))

    def test_cv_independent_variance_identity(self) -> None:
        beta = F(2, 3)
        vals, ps = cv_one_draw_distribution(self.d, self.g, self.p, beta)
        residuals = [d - beta * g for d, g in zip(self.d, self.g)]
        expected = beta**2 * variance(self.g, self.p) + variance(residuals, self.p)
        self.assertEqual(variance(vals, ps), expected)

    def test_dependent_batches_do_not_obey_independent_variance_formula(self) -> None:
        beta = F(2, 3)
        vals, ps = cv_one_draw_distribution(self.d, self.g, self.p, beta)
        # Reusing exactly the same draw in both terms leaves D alone.
        dependent = [beta * g + d - beta * g for d, g in zip(self.d, self.g)]
        self.assertNotEqual(variance(vals, ps), variance(dependent, self.p))

    def test_constant_proxy_does_not_reduce_variance(self) -> None:
        vals, ps = cv_one_draw_distribution(self.d, [F(4), F(4)], self.p, F(9))
        self.assertEqual(variance(vals, ps), variance(self.d, self.p))

    def test_zero_beta_retains_expensive_mean(self) -> None:
        vals, ps = cv_one_draw_distribution(self.d, self.g, self.p, F(0))
        self.assertEqual(expectation(vals, ps), F(1))
        self.assertEqual(variance(vals, ps), F(1))

    def test_reference_noise_cancels_mse_difference_not_ratio(self) -> None:
        refs = [F(-3), F(3)]
        noisy_a = expectation([(F(1) - r)**2 for r in refs], self.p)
        noisy_b = expectation([(F(2) - r)**2 for r in refs], self.p)
        self.assertEqual(noisy_b - noisy_a, F(4) - F(1))
        self.assertNotEqual(noisy_a / noisy_b, F(1, 4))

    def test_indistinguishable_worlds_share_action(self) -> None:
        pay = [[F(1), F(0)], [F(0), F(1)]]
        self.assertEqual(information_value(pay, self.p, ["same", "same"]), F(1, 2))
        clairvoyant = sum((p * max(row) for p, row in zip(self.p, pay)), F(0))
        self.assertEqual(clairvoyant, F(1))

    def test_observed_information_permits_different_actions(self) -> None:
        pay = [[F(1), F(0)], [F(0), F(1)]]
        self.assertEqual(information_value(pay, self.p, ["observed0", "observed1"]), F(1))

    def test_nonuniform_posterior_and_optimal_policy_bound(self) -> None:
        pay = [[F(1), F(0)], [F(0), F(1)]]
        weights = [F(3, 4), F(1, 4)]
        optimum = information_value(pay, weights, ["same", "same"])
        self.assertEqual(optimum, F(3, 4))
        for baseline_action in (0, 1):
            base = sum((w * row[baseline_action] for w, row in zip(weights, pay)), F(0))
            self.assertGreaterEqual(optimum, base)
        action_gap = sum((w * (row[1] - row[0]) for w, row in zip(weights, pay)), F(0))
        self.assertLess(action_gap, 0)

    def test_consequential_event_uses_full_denominator(self) -> None:
        probability = [F(1, 4), F(3, 4)]
        event = [True, False]
        gap = [F(2, 5), F(9, 10)]
        unconditional = expectation([g if e else F(0) for g, e in zip(gap, event)], probability)
        self.assertEqual(unconditional, F(1, 4) * F(2, 5))
        self.assertNotEqual(unconditional, F(2, 5))

    def test_receiver_message_distribution_uses_giver_policy(self) -> None:
        prior = [F(1, 2), F(1, 2)]
        p_message_given_hand = [F(9, 10), F(1, 10)]
        mass = sum((p * q for p, q in zip(prior, p_message_given_hand)), F(0))
        posterior = [p * q / mass for p, q in zip(prior, p_message_given_hand)]
        self.assertEqual(posterior, [F(9, 10), F(1, 10)])
        self.assertNotEqual(posterior, prior)
        self.assertEqual(expectation([F(1), F(0)], posterior), F(9, 10))

    def test_kernel_residual_is_zero(self) -> None:
        p = [[F(1, 4), F(1, 4)], [F(0), F(1, 2)]]
        r = [F(1, 4), F(1, 8)]
        v = kernel_value(p, r)
        self.assertEqual(v, [F(5, 12), F(1, 4)])
        for i in range(2):
            self.assertEqual(v[i], r[i] + sum((p[i][j] * v[j] for j in range(2)), F(0)))

    def test_policy_kernel_difference_identity(self) -> None:
        pb = [[F(1, 4), F(1, 4)], [F(0), F(1, 2)]]
        rb = [F(1, 4), F(1, 8)]
        pc = [[F(1, 8), F(1, 4)], [F(1, 8), F(1, 4)]]
        rc = [F(1, 3), F(1, 4)]
        vb, vc = kernel_value(pb, rb), kernel_value(pc, rc)
        rhs = [rc[i] - rb[i] + sum(((pc[i][j] - pb[i][j]) * vb[j]
                                  for j in range(2)), F(0)) for i in range(2)]
        gap = solve_linear([[F(i == j) - pc[i][j] for j in range(2)] for i in range(2)], rhs)
        self.assertEqual(gap, [vc[i] - vb[i] for i in range(2)])

    def test_nonabsorbing_kernel_is_not_fabricated(self) -> None:
        with self.assertRaises(ValueError):
            kernel_value([[F(1)]], [F(0)])

    def test_score48_margin_and_reset(self) -> None:
        for points in (4, 8, 24, 28, 56):
            self.assertGreaterEqual(next_score((48, 0), 0, points)[0], 52)
            self.assertEqual(next_score((48, 0), 1, points), (0, 0))
            self.assertGreaterEqual(next_score((0, 48), 1, points)[1], 52)
            self.assertEqual(next_score((0, 48), 0, points), (0, 0))

    def test_score48_does_not_determine_winner(self) -> None:
        # Assume the frozen surrogate values a reset at 1/2.
        outcomes = [F(1) if next_score((48, 0), winner, 4)[0] >= 52 else F(1, 2)
                    for winner in (0, 1)]
        self.assertEqual(set(outcomes), {F(1), F(1, 2)})

    def test_unresolved_match_bounds(self) -> None:
        self.assertEqual(unresolved_bounds(3, 5, 2), (F(3, 10), F(1, 2)))
        self.assertEqual(unresolved_bounds(4, 6, 0), (F(2, 5), F(2, 5)))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, help="Write the pure-check summary")
    args = parser.parse_args()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(MathematicalChecks)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if args.json is not None:
        payload = {
            "scope": "Pure finite mathematical examples; no Tuppi source/native/model execution",
            "tests_run": result.testsRun,
            "failures": len(result.failures),
            "errors": len(result.errors),
            "successful": result.wasSuccessful(),
            "game_tests_run": 0,
            "strength_experiments_run": 0,
        }
        args.json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
