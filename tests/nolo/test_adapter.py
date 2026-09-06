"""N08 checks: the adapter must never claim a guarantee it is not delivering.

The interesting failures here are not crashes. They are an adapter that corrects
a card and then abandons the continuation that justified it, one whose answer
depends on which hidden world happens to be behind the observation, or one whose
``explain`` tells a different story from what ``choose_action`` played. Each has
a test below, and each would be a FAILED_CHECK rather than a rough edge.

The packet witnesses are slow (a full exact search each), so they are replayed
once per module and shared.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from tuppi_agents.void_lead import void_seeking_agents
from tuppi_engine import EnginePhase, PlayCardAction, apply_action, observation_for
from tuppi_rules import Contract, MatchScore, card_to_code
from tuppi_valuation.corpus import forced_show_action
from tuppi_nolo import adapter as adapter_module
from tuppi_nolo.adapter import (
    ADAPTER_PROFILE_KEY,
    FALLBACK_OUT_OF_CONTRACT,
    FALLBACK_OUT_OF_RANGE,
    FALLBACK_PLAN_MISMATCH,
    FALLBACK_UNRESOLVED,
    PLAN_COMPONENT,
    REASON_BASELINE_KEPT,
    REASON_PLAN_CONTINUATION,
    REASON_SECURITY_ONLY,
    REASON_UNIVERSAL,
    SECURITY_COMPONENT,
    construct_security_certified_agent,
)
from tuppi_nolo.certificates import CheckStatus, verify_certificate
from tuppi_nolo.fixtures import load_fixtures
from tuppi_nolo.runner import deal_state
from tuppi_nolo.support import SupportBudget, build_support, semantic_observation_key

PACKET = Path(__file__).resolve().parents[2] / "docs/nolo/tasks/fixtures.json"
STARVED = SupportBudget(3, 100, 40)


@pytest.fixture(scope="module")
def packet():
    return {f.id: f for f in load_fixtures(PACKET)}


def at(fixture, score=None):
    """The witness position, optionally moved to another scoreboard."""

    source = fixture if score is None else replace(fixture, starting_score=MatchScore(*score))
    state = source.replay()
    return state, observation_for(state, state.current_actor)


def decided(fixture, score=None, budget=None):
    state, observation = at(fixture, score)
    agent = construct_security_certified_agent(observation.observing_seat, budget=budget)
    action = agent.choose_action(observation)
    return agent, state, observation, action


#: Witness A costs a full three-trick exact search, so read-only tests share one
#: settled agent. It memoises by information key, so a shared instance answers a
#: repeat in microseconds and cannot drift between tests. Anything that drops a
#: plan or replays one takes a fresh agent instead, and uses the cheap witness B.
_SHARED: dict = {}


def shared(packet, name, score=None):
    key = (name, score)
    if key not in _SHARED:
        _SHARED[key] = decided(packet[name], score)
    return _SHARED[key]


def advance_to_own_turn(state, seat, agents):
    """Play the other seats with v2 until *seat* is on turn again."""

    while state.phase is EnginePhase.TRICK_PLAY and state.current_actor != seat:
        observation = observation_for(state, state.current_actor)
        state = apply_action(state, agents[state.current_actor].choose_action(observation))
    return state


# ------------------------------------------------------- acceptance endpoints


def test_A_takes_the_universal_correction_and_its_continuation_is_certified(packet):
    """`8S` is played, and the retained plan is re-verified from scratch: every
    compatible world and every other-seat legal continuation finishes at 7."""

    agent, _state, observation, action = shared(packet, "A")
    assert card_to_code(action.card) == "8S"
    report = agent.security_report(observation)
    assert report["claim"] == "UNIVERSAL" and report["corrected"] is True

    plan = agent.plan
    assert plan is not None and plan.claimed_bound == 7
    checked = verify_certificate(observation, plan.certificate, SupportBudget())
    assert checked.status is CheckStatus.EXACT_COMPLETE
    assert checked.terminal_totals == frozenset({7}), "every continuation must end at 7"


def test_B_plays_9C_and_then_the_certified_3C(packet):
    agent, state, observation, action = decided(packet["B"])
    assert card_to_code(action.card) == "9C"
    assert agent.security_report(observation)["claim"] == "SECURITY_ONLY"

    plan = agent.plan
    checked = verify_certificate(observation, plan.certificate, SupportBudget())
    assert checked.status is CheckStatus.EXACT_COMPLETE
    assert checked.terminal_totals == frozenset({4}), "the whole plan must end at 4"

    seat = observation.observing_seat
    later = advance_to_own_turn(apply_action(state, action), seat, void_seeking_agents())
    assert later.phase is EnginePhase.TRICK_PLAY
    next_observation = observation_for(later, seat)
    assert card_to_code(agent.choose_action(next_observation).card) == "3C"
    assert agent.security_report(next_observation)["outcome"] == REASON_PLAN_CONTINUATION


def test_B_still_plays_3C_when_no_further_search_is_possible(packet, monkeypatch):
    """The point of retaining a plan. A later budget failure must not be able to
    substitute an unverified continuation, so the replay path must not search at
    all — here any attempt to is made to explode."""

    agent, state, observation, action = decided(packet["B"])
    seat = observation.observing_seat
    later = advance_to_own_turn(apply_action(state, action), seat, void_seeking_agents())
    next_observation = observation_for(later, seat)

    def forbidden(*args, **kwargs):
        raise AssertionError("plan replay must not run a fresh search")

    monkeypatch.setattr(adapter_module, "solve_security", forbidden)
    assert card_to_code(agent.choose_action(next_observation).card) == "3C"


def test_C_preserves_the_baseline(packet):
    agent, _state, observation, action = decided(packet["C"])
    assert card_to_code(action.card) == "KC"
    report = agent.security_report(observation)
    assert report["corrected"] is False and report["claim"] == "TIE"
    assert agent.plan is None, "an unchanged action needs no future restriction"


@pytest.mark.parametrize(
    "name,score,expected,claim",
    [
        ("A", (0, 0), "8S", "UNIVERSAL"),
        ("A", (0, 40), "8S", "UNIVERSAL"),
        ("A", (40, 0), "QD", "TIE"),
        ("B", (0, 0), "9C", "SECURITY_ONLY"),
        ("B", (40, 0), "9C", "SECURITY_ONLY"),
        ("B", (0, 40), "3C", "TIE"),
    ],
)
def test_the_scoreboard_decides_whether_a_correction_is_worth_making(
    packet, name, score, expected, claim
):
    """N05's table, reproduced through the policy rather than through the maths.

    A score tie needs no special case in the adapter: the component is the score
    proxy, so two lines that price the same get the same value and v2's ranking
    breaks the tie back to the baseline.
    """

    agent, _state, observation, action = shared(packet, name, score)
    assert card_to_code(action.card) == expected
    assert agent.security_report(observation)["claim"] == claim


# --------------------------------------------------------- agreement and state


def test_choose_action_decide_and_explain_never_disagree(packet):
    _agent, _state, observation, _action = decided(packet["B"])
    agent = construct_security_certified_agent(observation.observing_seat)
    for _ in range(3):
        chosen = agent.choose_action(observation)
        decision = agent.decide(observation)
        record = agent.explain(observation)
        assert decision.action == chosen
        assert decision.scored.action == chosen
        assert record is not None
        assert agent.security_report(observation)["claim"] == "SECURITY_ONLY"


def test_repeated_diagnostic_calls_consume_nothing(packet):
    agent, _state, observation, first = decided(packet["B"])
    plan_before = dict(agent.plan.table)
    for _ in range(5):
        agent.explain(observation)
    assert agent.choose_action(observation) == first
    assert dict(agent.plan.table) == plan_before, "diagnostics must not spend the plan"


def test_the_same_observed_history_decides_the_same_behind_any_hidden_world(packet):
    """Substituting a compatible hidden layout must change nothing: the decision
    is a function of the observation, and the observation is identical."""

    _agent, _state, observation, action = decided(packet["B"])
    support = build_support(observation, SupportBudget())
    seat = observation.observing_seat
    seen = set()
    for world in support.research_worlds[:4]:
        substituted = observation_for(world.continuation.state, seat)
        assert semantic_observation_key(substituted) == semantic_observation_key(observation)
        other = construct_security_certified_agent(seat)
        seen.add(card_to_code(other.choose_action(substituted).card))
        assert other.security_report(substituted)["claim"] == "SECURITY_ONLY"
    assert seen == {card_to_code(action.card)}


def test_renaming_the_protocol_identifiers_changes_nothing(packet):
    """Match and deal references are protocol identities, not information."""

    _agent, _state, observation, action = decided(packet["B"])
    renamed_state = replace(packet["B"], id="B-renamed").replay()
    renamed = observation_for(renamed_state, renamed_state.current_actor)
    assert renamed.deal_ref != observation.deal_ref
    assert semantic_observation_key(renamed) == semantic_observation_key(observation)
    agent = construct_security_certified_agent(renamed.observing_seat)
    assert agent.choose_action(renamed) == action
    assert agent.security_report(renamed)["outcome"] == REASON_SECURITY_ONLY


def test_a_new_deal_clears_the_plan(packet):
    agent, _state, observation, _action = decided(packet["B"])
    assert agent.plan is not None
    seat = observation.observing_seat
    fresh = advance_to_own_turn(deal_state("nolo-info-dev-v1", 0), seat,
                                void_seeking_agents())
    agent.choose_action(observation_for(fresh, seat))
    assert agent.plan is None, "a new deal must not inherit an old guarantee"


def test_a_history_the_plan_does_not_own_drops_the_plan_rather_than_bluffing(packet):
    """If the seat did not play the certified card, the guarantee is gone. The
    adapter must say so and fall back, not play on under a stale certificate."""

    agent, state, observation, action = decided(packet["B"])
    seat = observation.observing_seat
    other = next(a for a in observation.legal_actions if a != action)
    diverged = advance_to_own_turn(apply_action(state, other), seat, void_seeking_agents())
    assert diverged.phase is EnginePhase.TRICK_PLAY
    foreign = observation_for(diverged, seat)
    baseline = void_seeking_agents()[seat].choose_action(foreign)

    assert agent.choose_action(foreign) == baseline
    assert agent.security_report(foreign)["outcome"] == FALLBACK_PLAN_MISMATCH
    assert agent.plan is None


# ----------------------------------------------------------------- delegation


def test_out_of_range_nolo_delegates_to_v2(packet):
    state = deal_state("nolo-info-dev-v1", 0)
    observation = observation_for(state, state.current_actor)
    agent = construct_security_certified_agent(observation.observing_seat)
    baseline = void_seeking_agents()[observation.observing_seat].choose_action(observation)
    assert agent.choose_action(observation) == baseline
    assert agent.security_report(observation)["outcome"] == FALLBACK_OUT_OF_RANGE


def test_rami_play_delegates_to_v2():
    """The adapter is a NOLO instrument and must not touch the other contract."""

    built = _rami_deal(1)
    observation = observation_for(built, built.current_actor)
    assert observation.contract is Contract.RAMI
    agent = construct_security_certified_agent(observation.observing_seat)
    baseline = void_seeking_agents()[observation.observing_seat].choose_action(observation)
    assert agent.choose_action(observation) == baseline
    assert agent.security_report(observation)["outcome"] == FALLBACK_OUT_OF_CONTRACT


def _rami_deal(index):
    from tuppi_eval.deals import DealerPolicy, generate_base_deal
    from tuppi_engine import ExplicitDeal, create_deal_state

    base = generate_base_deal(root_seed="nolo-info-dev-v1", index=index,
                             dealer_policy=DealerPolicy.ROUND_ROBIN, initial_dealer=0,
                             starting_score=MatchScore(0, 0))
    ref = f"nolo-n08-rami:{index}"
    state = create_deal_state(ExplicitDeal(dealer=base.dealer, hands=base.hands),
                              starting_score=MatchScore(0, 0), match_ref=ref,
                              deal_ref=f"{ref}/deal:0", deal_number=0, event_start_index=0)
    while state.phase is EnginePhase.SHOWING:
        observation = observation_for(state, state.current_actor)
        state = apply_action(state, forced_show_action(observation, Contract.RAMI))
    return state


def test_an_unresolved_search_delegates_and_says_why(packet):
    agent, _state, observation, action = decided(packet["A"], budget=STARVED)
    baseline = void_seeking_agents()[observation.observing_seat].choose_action(observation)
    assert action == baseline
    report = agent.security_report(observation)
    assert report["outcome"] == FALLBACK_UNRESOLVED
    assert report["status"] in {"SUPPORT_BUDGET", "SEARCH_BUDGET"}
    assert agent.plan is None, "an unresolved search may retain no guarantee"


# ------------------------------------------------------------- the score layout


def test_every_legal_action_is_scored_and_the_maximum_is_played(packet):
    agent, _state, observation, _action = shared(packet, "A")
    scored = agent.decide(observation).scored
    assert len(scored.candidates) == len(observation.legal_actions)
    assert scored.candidates[0].component_names[0] == SECURITY_COMPONENT
    best = max(scored.candidates, key=lambda c: c.selection_key)
    assert best.action_order_index == scored.selected_index
    assert card_to_code(scored.action.card) == "8S"


def test_the_inherited_v2_ranking_survives_underneath(packet):
    """The new component sits above v2's vector; v2's order is the tie-break."""

    agent, _state, observation, _action = shared(packet, "A")
    seat = observation.observing_seat
    mine = agent.decide(observation).scored
    theirs = void_seeking_agents()[seat].decide(observation).scored
    for candidate, inherited in zip(mine.candidates, theirs.candidates, strict=True):
        assert candidate.component_names[1:] == inherited.component_names
        assert candidate.score_vector[1:] == inherited.score_vector


def test_no_phase_four_catalogue_rule_is_introduced(packet):
    """A catalogue entry carries provenance tied to the frozen profiles, so the
    adapter must explain itself with a component and a reason code instead."""

    agent, _state, observation, _action = shared(packet, "A")
    seat = observation.observing_seat
    mine = agent.decide(observation).scored
    theirs = void_seeking_agents()[seat].decide(observation).scored
    assert {r for c in mine.candidates for r in c.rule_ids} == {
        r for c in theirs.candidates for r in c.rule_ids
    }


def test_the_explanation_distinguishes_universal_from_security_only(packet):
    universal, _s, universal_observation, _a = shared(packet, "A")
    security, _s2, security_observation, _a2 = decided(packet["B"])
    assert universal.security_report(universal_observation)["outcome"] == REASON_UNIVERSAL
    assert security.security_report(security_observation)["outcome"] == REASON_SECURITY_ONLY
    assert REASON_UNIVERSAL != REASON_SECURITY_ONLY != REASON_BASELINE_KEPT


def test_the_plan_component_names_itself_on_replay(packet):
    agent, state, observation, action = decided(packet["B"])
    seat = observation.observing_seat
    later = advance_to_own_turn(apply_action(state, action), seat, void_seeking_agents())
    scored = agent.decide(observation_for(later, seat)).scored
    assert scored.candidates[0].component_names[0] == PLAN_COMPONENT


# ------------------------------------------------------- boundaries and leaks


def test_no_earlier_package_imports_the_research_layer():
    """The one-directional rule, checked recursively rather than by top level."""

    root = Path(__file__).resolve().parents[2]
    earlier = ("tuppi_rules", "tuppi_engine", "tuppi_eval", "tuppi_agents",
               "tuppi_legacy", "tuppi_match", "tuppi_valuation", "tuppi_exact",
               "tuppi_belief", "tuppi_search", "tuppi_server")
    offenders = []
    for package in earlier:
        directory = root / "src" / package
        if not directory.is_dir():
            continue
        for module in sorted(directory.rglob("*.py")):
            if "tuppi_nolo" in module.read_text(encoding="utf-8"):
                offenders.append(module.relative_to(root).as_posix())
    assert offenders == [], f"the research layer must stay one-directional: {offenders}"


def test_the_adapter_identity_is_not_a_registered_profile():
    from tuppi_agents.registry import phase4_specifications_by_profile_key

    agent = construct_security_certified_agent(0)
    assert ADAPTER_PROFILE_KEY not in phase4_specifications_by_profile_key()
    assert agent.identity.startswith(ADAPTER_PROFILE_KEY + ":")


def test_nothing_the_policy_exposes_names_a_hidden_allocation(packet):
    from tuppi_nolo.runner import contains_forbidden_key

    agent, _state, observation, _action = decided(packet["B"])
    report = agent.security_report(observation)
    assert contains_forbidden_key(report) is None
    scored = agent.decide(observation).scored
    for candidate in scored.candidates:
        assert isinstance(candidate.action, PlayCardAction)
    assert contains_forbidden_key(
        [
            {"components": list(c.component_names), "scores": list(c.score_vector),
             "reasons": list(c.reason_codes)}
            for c in scored.candidates
        ]
    ) is None


def test_four_seats_never_share_a_controller(packet):
    """Each instance holds only its own plan; there is no team-level object."""

    from tuppi_nolo.adapter import security_certified_agents

    agents = security_certified_agents()
    assert len({id(a) for a in agents}) == 4
    assert all(a.plan is None for a in agents)
    _agent, _state, observation, action = decided(packet["B"])
    seat = observation.observing_seat
    agents[seat].choose_action(observation)
    assert agents[seat].plan is not None
    assert all(agents[other].plan is None for other in range(4) if other != seat)
