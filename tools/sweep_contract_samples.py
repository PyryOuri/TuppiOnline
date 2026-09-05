#!/usr/bin/env python3
"""How much of the RAMI/NOLO decision does sampling recover that descriptors cannot?

``docs/valuation/rami_declaration.md`` establishes a ceiling: three different
descriptor rules — the bot's own, HCP >= 12, and HCP - 0.5*low >= 10 — all land
within three points of each other at about **34% of perfect foresight**, and the
full eight-descriptor regression explains only R^2 = 0.106. Its conclusion is
that the rest is "determined by things a point count cannot see - how the suits
actually lie".

Something in this codebase *can* see how the suits lie: the live server's
contract evaluator samples hidden-hand worlds from the hard-feasible set and
plays each one out under both contracts. It already runs, at eight samples by
default. Whether that is enough has never been measured.

This sweeps the sample count against perfect foresight on identical deals, so
the answer is a saturation curve rather than an argument. If the curve is still
climbing at 64, the cheap fix is a larger budget; if it flattens early, sampling
is not the missing ingredient either.

**The counterfactual here is RAMI against NOLO on the same deal**, which is what
``ContractCondition`` calls the counterfactual a showing decision actually needs.
That is *not* the counterfactual in `rami_declaration.md`, which compares
declaring against passing and letting the auction continue — a later seat then
declares 72% of the time. Numbers here are therefore not comparable with that
document's table; they answer the narrower, cleaner question.

Usage:
    python3 tools/sweep_contract_samples.py [--deals N] [--seed S]
                                            [--samples 0,4,8,16,32,64]
"""

from __future__ import annotations

import argparse
import collections


def deal_pair(seed: str, index: int, profile: str):
    """The same deal played out under each forced contract."""

    from tuppi_valuation.corpus import ContractCondition, CorpusSpec, play_one_deal

    arms = {}
    for condition in (ContractCondition.FORCED_RAMI, ContractCondition.FORCED_NOLO):
        spec = CorpusSpec(
            profile_key=profile,
            deal_count=index + 1,
            root_seed=seed,
            starting_score=(0, 0),
            condition=condition,
        )
        arms[condition] = play_one_deal(spec, index)
    return arms[ContractCondition.FORCED_RAMI], arms[ContractCondition.FORCED_NOLO]


def team_points(result, team: int) -> int:
    """Signed deal points from one team's side of the table."""

    score = result.public_result.deal_score
    return score.points if int(score.winner_team) == team else -score.points


def descriptors(hand):
    from tuppi_rules import Rank

    hcp = sum(
        {Rank.ACE: 4, Rank.KING: 3, Rank.QUEEN: 2, Rank.JACK: 1}.get(c.rank, 0)
        for c in hand
    )
    low = sum(1 for c in hand if c.rank.value <= 4)
    return hcp, low


def sampler_choice(observation, *, profile, sample_count: int) -> str:
    """What the live contract evaluator would declare at this sample budget."""

    from tuppi_agents import construct_agent, phase4_specifications_by_profile_key
    from tuppi_engine import ShowAction
    from tuppi_server.contract_evaluation import evaluate_contract_choice

    spec = phase4_specifications_by_profile_key()[profile]
    seat = observation.observing_seat
    policy = construct_agent(spec, seat=seat)
    agents = {s: construct_agent(spec, seat=s) for s in range(4)}
    decision = evaluate_contract_choice(
        observation,
        policy=policy,
        agents=agents,
        deal_number=0,
        event_index=0,
        sample_count=sample_count,
    )
    action = decision.action
    return (
        action.declared_contract.value
        if isinstance(action, ShowAction)
        else "NOLO"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deals", type=int, default=200)
    parser.add_argument("--seed", default="contract-sample-sweep-v1")
    parser.add_argument("--profile", default="partner_aware_v1")
    parser.add_argument("--samples", default="0,4,8,16,32,64")
    args = parser.parse_args()

    from tuppi_engine import EnginePhase, begin_explicit_deal, create_match
    from tuppi_engine import ExplicitDeal, match_observation_for
    from tuppi_rules import MatchScore

    budgets = [int(v) for v in args.samples.split(",") if v.strip()]
    stats = {b: collections.Counter() for b in budgets}
    rules = {"HCP>=12": collections.Counter(), "HCP-0.5low>=10": collections.Counter()}
    ceiling = 0
    counted = 0

    for index in range(args.deals):
        try:
            rami, nolo = deal_pair(args.seed, index, args.profile)
        except Exception:
            continue
        forehand = rami.public_result.forehand
        team = forehand % 2
        gain = team_points(rami, team) - team_points(nolo, team)
        if gain == 0:
            continue  # the contract made no difference to this deal
        counted += 1
        truth = "RAMI" if gain > 0 else "NOLO"
        ceiling += abs(gain)

        hand = rami.initial_hands[forehand]
        hcp, low = descriptors(hand)
        for name, choice in (
            ("HCP>=12", "RAMI" if hcp >= 12 else "NOLO"),
            ("HCP-0.5low>=10", "RAMI" if hcp - 0.5 * low >= 10 else "NOLO"),
        ):
            rules[name]["right" if choice == truth else "wrong"] += 1
            rules[name]["points"] += gain if choice == "RAMI" else -gain

        # the forehand's own showing observation, before anybody has acted
        state = create_match(
            initial_score=MatchScore(0, 0),
            initial_dealer=rami.public_result.dealer,
            match_ref="sweep",
        )
        state = begin_explicit_deal(
            state,
            ExplicitDeal(dealer=rami.public_result.dealer, hands=rami.initial_hands),
        )
        if state.phase is not EnginePhase.SHOWING:
            continue
        observation = match_observation_for(state, forehand)

        for budget in budgets:
            try:
                choice = sampler_choice(
                    observation, profile=args.profile, sample_count=budget
                )
            except Exception:
                continue
            cell = stats[budget]
            cell["right" if choice == truth else "wrong"] += 1
            cell["points"] += gain if choice == "RAMI" else -gain
            cell["declared"] += int(choice == "RAMI")

    if not counted:
        print("no deals where the contract changed the score")
        return 1

    print(f"deals where the contract mattered: {counted}   "
          f"perfect-foresight points: {ceiling}\n")
    print(f"{'policy':18s} {'n':>5} {'accuracy':>9} {'points':>8} {'% of ceiling':>13} "
          f"{'declares':>9}")
    for name, cell in rules.items():
        n = cell["right"] + cell["wrong"]
        if not n:
            continue
        print(f"{name:18s} {n:>5} {100*cell['right']/n:>8.1f}% {cell['points']:>8} "
              f"{100*cell['points']/ceiling:>12.1f}%")
    for budget in budgets:
        cell = stats[budget]
        n = cell["right"] + cell["wrong"]
        if not n:
            continue
        label = "heuristic only" if budget == 0 else f"sampler n={budget}"
        print(f"{label:18s} {n:>5} {100*cell['right']/n:>8.1f}% {cell['points']:>8} "
              f"{100*cell['points']/ceiling:>12.1f}% {100*cell['declared']/n:>8.1f}%")
    print("\nPoints are signed from the forehand's team. Perfect foresight would "
          "take every deal the right way, so its share is 100% by construction.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
