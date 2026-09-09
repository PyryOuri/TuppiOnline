"""How many of a decision's legal actions can change the deal's result?

Answers a question neither S1 nor the corpus measured directly: at a real
trick-play decision, does the choice matter at all? Every legal action is played
out under the frozen reference on the same hidden deal, and the distinct
outcomes are counted.

    PYTHONPATH=src python work/showing/decision_leverage.py

Result (400 sampled decisions, 2026-09-09): 5.27 legal actions collapse to 1.79
distinct outcomes, and at **50.3%** of decisions every legal action gives the
identical result. Combined with the 21.2% of decisions that have only one legal
action, about **61% of all decisions cannot change the deal outcome**.
"""

from __future__ import annotations

import collections
import statistics

from tuppi_agents.improved_registry import (
    corpus_reference_specification,
    improved_agent_from_specification,
)
from tuppi_corpus.packing import canonical_hands
from tuppi_corpus.seeds import derive_seed, uniform_below
from tuppi_engine import (
    EnginePhase,
    ExplicitDeal,
    apply_match_action,
    begin_explicit_deal,
    create_match,
    match_observation_for,
)
from tuppi_engine.trusted import trusted_transitions
from tuppi_match.streams import MatchStream
from tuppi_rules import MatchScore

SAMPLES = 400
REFERENCE = "partner_aware_lead_v2"


def main() -> int:
    specification = corpus_reference_specification()
    agents = {
        seat: improved_agent_from_specification(
            specification, profile_key=REFERENCE, seat=seat
        )
        for seat in range(4)
    }

    def fresh(hands):
        return begin_explicit_deal(
            create_match(
                initial_score=MatchScore(0, 0), initial_dealer=0, match_ref="leverage"
            ),
            ExplicitDeal(dealer=0, hands=hands),
        )

    def finish(state) -> tuple:
        while state.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
            seat = state.current_actor
            state = apply_match_action(
                state, agents[seat].choose_action(match_observation_for(state, seat))
            )
        result = state.completed_deals[-1].public_result
        return (
            result.team_tricks[0],
            result.deal_score.points,
            result.deal_score.winner_team.value,
        )

    distinct = collections.Counter()
    legal = collections.Counter()
    with trusted_transitions():
        for index in range(SAMPLES):
            stream = MatchStream.build(
                root_seed="leverage-v1", stream_index=index, initial_dealer=0
            )
            hands = canonical_hands(stream.deal(0).explicit_deal(0).hands)
            target = uniform_below(derive_seed("leverage-v1", sample=index), 40)
            state, seen, chosen = fresh(hands), 0, None
            while state.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
                seat = state.current_actor
                observation = match_observation_for(state, seat)
                if (
                    state.phase is EnginePhase.TRICK_PLAY
                    and len(observation.legal_actions) >= 2
                ):
                    if seen == target:
                        chosen = (state, observation)
                        break
                    seen += 1
                state = apply_match_action(
                    state, agents[seat].choose_action(observation)
                )
            if chosen is None:
                continue
            state, observation = chosen
            outcomes = {
                finish(apply_match_action(state, action))
                for action in observation.legal_actions
            }
            legal[len(observation.legal_actions)] += 1
            distinct[len(outcomes)] += 1

    total = sum(legal.values())
    spread = lambda counter: statistics.fmean(
        [key for key, count in counter.items() for _ in range(count)]
    )
    print(f"{total} trick-play decisions with >=2 legal actions, all branches played")
    print(f"  mean legal actions      {spread(legal):.2f}")
    print(f"  mean distinct outcomes  {spread(distinct):.2f}")
    print(
        f"  every action identical  {distinct[1]}/{total} = "
        f"{100 * distinct[1] / total:.1f}%"
    )
    forced = 0.212  # measured share of decisions with exactly one legal action
    inert = forced + (1 - forced) * distinct[1] / total
    print(f"  => decisions that cannot change the deal outcome: {100 * inert:.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
