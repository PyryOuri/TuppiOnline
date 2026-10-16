"""Playing one stream into records.

This is the only place in the corpus layer that chooses an action, and that is
deliberate.  Every deviation from on-policy play - the softened stratum's
randomisation, an epsilon branch, a forced arm - is decided here from an
explicit seed coordinate rather than by a stateful wrapper policy, so a stream
replays identically without depending on how many times an object was asked a
question.

Two engine-facing properties matter.

**Trusted transitions.** The whole loop runs inside
``tuppi_engine.trusted.trusted_transitions``, which is worth a measured 11.1x
(``docs/database/phase7_charter.md`` §1.3).  Deal boundaries stay validated by
construction, and every ``revalidation_period``-th deal is additionally checked
through the authoritative path, which that module's docstring names as a
condition of using it at all.  A deal that was checked carries
``FLAG_REVALIDATED``, so the guarantee is recorded in the data rather than
claimed in a log.

**No policy sees hidden state.** Hands come from the explicit deal and go
straight into the record.  Every action is chosen from a formal
``PlayerObservation`` produced by ``match_observation_for``; there is no other
path from a hand to a decision, which is what ``tests/corpus/test_privacy.py``
checks.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from tuppi_engine import (
    EnginePhase,
    ExplicitDeal,
    ShowAction,
    apply_match_action,
    begin_explicit_deal,
    create_match,
    match_observation_for,
    validate_match_state,
)
from tuppi_engine.trusted import trusted_transitions
from tuppi_match.streams import MatchStream
from tuppi_rules import Contract, MatchScore, Team

from .errors import CorpusConfigurationError
from .packing import canonical_hands
from .records import (
    FLAG_EPSILON_BRANCH,
    FLAG_FORCED_CONTRACT,
    FLAG_FORCED_PLAY,
    FLAG_MATCH_TERMINAL,
    FLAG_RESET,
    FLAG_REVALIDATED,
    FLAG_SOFTENED,
    FLAG_VERBAL_REQUIRED,
    DealRecord,
    MatchRecord,
)
from .seeds import derive_seed, uniform_below
from .strata import (
    BRANCH_EPSILON,
    BRANCH_FORCED_CONTRACT,
    BRANCH_FORCED_PLAY,
    TERMINATION_DEAL_CAP,
    TERMINATION_FORCED_BRANCH,
    TERMINATION_NATURAL,
    StreamPlan,
    construct_table,
    plan_stream,
)


GENERATION_SCHEMA_VERSION = "tuppi.corpus.generation.v1"


@dataclass(frozen=True, slots=True)
class GeneratedUnit:
    """One played match and its deals, before shard row indices are assigned."""

    match: MatchRecord
    deals: tuple[DealRecord, ...]


def match_ref_for(plan: StreamPlan, arm: int) -> str:
    """A public, hidden-state-free reference. Only its grammar is load-bearing."""

    return f"tdc-{plan.stream_index:09d}-{arm:1d}"


def _ranked(policy, observation):
    """The policy's own ranking, best first, without building diagnostics."""

    scored = policy.decide(observation, diagnostics=False).scored
    return tuple(
        sorted(scored.candidates, key=lambda item: item.selection_key, reverse=True)
    )


def _soften(policy, observation, seed: int, top_k: int, numerator: int, denominator: int):
    """Uniform among the policy's top *k* actions, with probability n/d."""

    if uniform_below(seed, denominator) >= numerator:
        return policy.choose_action(observation), False
    ranked = _ranked(policy, observation)
    limit = min(top_k, len(ranked))
    if limit <= 1:
        return ranked[0].action, False
    chosen = ranked[uniform_below(seed, limit, stride=1)].action
    return chosen, chosen != ranked[0].action


def _forced_contract_action(policy, observation, contract: Contract):
    """The policy's own best-ranked show action *for this contract*.

    Forcing the contract but letting the policy pick the card is the RAMI/NOLO
    threshold experiment's design: the counterfactual is the contract choice,
    not a differently-chosen card.
    """

    ranked = _ranked(policy, observation)
    for candidate in ranked:
        action = candidate.action
        if isinstance(action, ShowAction) and action.declared_contract is contract:
            return action
    return None


def _forced_play_action(policy, observation, arm: int):
    """Arm 0 takes the policy's choice; arm 1 takes its runner-up.

    A runner-up rather than a random legal card, so the pair measures a decision
    a competent player might actually have made.
    """

    ranked = _ranked(policy, observation)
    if len(ranked) < 2:
        return None
    return ranked[min(arm, len(ranked) - 1)].action


def _epsilon_action(observation, seed: int):
    legal = observation.legal_actions
    return legal[uniform_below(seed, len(legal))]


def generate_stream(manifest, stream_index: int) -> tuple[GeneratedUnit, ...]:
    """Play one stream.  Paired strata return two arms; everything else one."""

    plan = plan_stream(manifest, stream_index)
    return tuple(_generate_arm(manifest, plan, arm) for arm in plan.arms)


def _generate_arm(manifest, plan: StreamPlan, arm: int) -> GeneratedUnit:
    if plan.is_paired:
        return _generate_paired_arm(manifest, plan, arm)
    stream = MatchStream.build(
        root_seed=manifest.root_seed,
        stream_index=plan.stream_index,
        initial_dealer=plan.initial_dealer,
    )
    table = construct_table(manifest, plan.policy_set_index)
    state = create_match(
        initial_score=MatchScore(*plan.initial_score),
        initial_dealer=stream.initial_dealer,
        match_ref=match_ref_for(plan, arm),
    )

    deals: list[DealRecord] = []
    deal_index = 0
    hands: tuple = ()
    shows: list[tuple] = []
    plays: list = []
    trick_ply = 0
    flags = 0
    branch_ply: int | None = None
    branched = False

    with trusted_transitions():
        while not state.terminal:
            if state.phase in (EnginePhase.AWAITING_DEAL, EnginePhase.DEAL_COMPLETE):
                # The cap gates *beginning* a deal. Checking it as the loop
                # condition instead would deal a deal and then exit without
                # playing it, discarding it silently - and would play nothing at
                # all at a cap of one, which is what the paired strata use.
                if deal_index >= plan.deal_cap:
                    break
                # Canonicalise before playing: packed hands are sets, and the
                # dealt order is behaviourally material (see packing.HAND_ORDER_ID),
                # so the record must describe the deal that was actually played.
                dealt = stream.deal(deal_index).explicit_deal(state.dealer)
                hands = canonical_hands(dealt.hands)
                state = begin_explicit_deal(
                    state, ExplicitDeal(dealer=dealt.dealer, hands=hands)
                )
                deal_index += 1
                shows, plays, trick_ply = [], [], 0
                flags, branch_ply, branched = 0, None, False
                continue

            actor = state.current_actor
            if actor is None:  # pragma: no cover - authoritative invariant
                raise CorpusConfigurationError("active state has no actor")
            observation = match_observation_for(state, actor)
            policy = table[actor]
            showing = state.phase is EnginePhase.SHOWING
            ply = len(shows) + trick_ply

            action = None
            if plan.stratum_name == "softened_reference":
                seed = derive_seed(
                    manifest.root_seed,
                    domain="soften",
                    stream=plan.stream_index,
                    deal=deal_index - 1,
                    ply=ply,
                    seat=actor,
                )
                action, moved = _soften(
                    policy,
                    observation,
                    seed,
                    manifest.softening_top_k,
                    manifest.softening_probability_numerator,
                    manifest.softening_probability_denominator,
                )
                if moved:
                    flags |= FLAG_SOFTENED
                    if branch_ply is None:
                        branch_ply = ply
            elif (
                not branched
                and plan.branch_kind == BRANCH_EPSILON
                and deal_index - 1 == plan.branch_deal
                and not showing
                and trick_ply == plan.branch_target
            ):
                action = _epsilon_action(
                    observation,
                    derive_seed(
                        manifest.root_seed,
                        domain="epsilon_action",
                        stream=plan.stream_index,
                        ply=ply,
                    ),
                )
                flags |= FLAG_EPSILON_BRANCH
                branch_ply, branched = ply, True
            elif (
                not branched
                and plan.branch_kind == BRANCH_FORCED_CONTRACT
                and showing
                and not shows
            ):
                wanted = Contract.RAMI if arm == 0 else Contract.NOLO
                action = _forced_contract_action(policy, observation, wanted)
                if action is not None:
                    flags |= FLAG_FORCED_CONTRACT
                    branch_ply, branched = ply, True
            elif (
                not branched
                and plan.branch_kind == BRANCH_FORCED_PLAY
                and not showing
                and trick_ply == plan.branch_target
            ):
                action = _forced_play_action(policy, observation, arm)
                if action is not None:
                    flags |= FLAG_FORCED_PLAY
                    branch_ply, branched = ply, True

            if action is None:
                action = policy.choose_action(observation)

            if showing:
                shows.append((action.shown_card, action.declared_contract))
            else:
                plays.append(action.card)
                trick_ply += 1

            state = apply_match_action(state, action)

            if state.phase in (EnginePhase.DEAL_COMPLETE, EnginePhase.MATCH_COMPLETE):
                if deal_index % manifest.revalidation_period == 0:
                    # The authoritative path, inside the trusted block, exactly
                    # as tuppi_engine.trusted documents: an explicit request is
                    # always honoured.
                    validate_match_state(state)
                    flags |= FLAG_REVALIDATED
                deals.append(
                    _deal_record(
                        state.completed_deals[-1].public_result,
                        hands=hands,
                        shows=tuple(shows),
                        plays=tuple(plays),
                        flags=flags,
                        branch_ply=branch_ply,
                        arm=arm,
                    )
                )

    if state.terminal:
        termination = TERMINATION_NATURAL
    elif plan.is_paired:
        termination = TERMINATION_FORCED_BRANCH
    else:
        termination = TERMINATION_DEAL_CAP

    winner = None
    if state.terminal:
        winner = 0 if state.score.team0 > state.score.team1 else 1

    match = MatchRecord(
        stream_index=plan.stream_index,
        initial_dealer=plan.initial_dealer,
        initial_score=tuple(plan.initial_score),
        final_score=(state.score.team0, state.score.team1),
        deals_played=len(deals),
        winner_team=winner,
        termination=termination,
        stratum=plan.stratum_index,
        policy_set=plan.policy_set_index,
        split=plan.split,
        pair_id=None if plan.pair_id is None else plan.pair_id * 2 + arm,
        first_deal_row=0,
    )
    return GeneratedUnit(match=match, deals=tuple(deals))


def _generate_paired_arm(manifest, plan: StreamPlan, arm: int) -> GeneratedUnit:
    """Independent single deals, each forced, so both arms share a prior state.

    Not a match: a match's second deal would start from a score the first deal's
    forced action had already moved, and the two arms would no longer be a pair.
    Each deal therefore starts fresh from the scheduled score, and a pair is
    ``(stream_index, deal_number)``.
    """

    stream = MatchStream.build(
        root_seed=manifest.root_seed,
        stream_index=plan.stream_index,
        initial_dealer=plan.initial_dealer,
    )
    table = construct_table(manifest, plan.policy_set_index)
    deals: list[DealRecord] = []

    with trusted_transitions():
        for ordinal in range(plan.deal_cap):
            state = create_match(
                initial_score=MatchScore(*plan.initial_score),
                initial_dealer=plan.initial_dealer,
                match_ref=match_ref_for(plan, arm),
            )
            dealt = stream.deal(ordinal).explicit_deal(state.dealer)
            hands = canonical_hands(dealt.hands)
            state = begin_explicit_deal(
                state, ExplicitDeal(dealer=dealt.dealer, hands=hands)
            )
            shows: list[tuple] = []
            plays: list = []
            trick_ply = 0
            flags = 0
            branch_ply: int | None = None
            branched = False

            while state.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
                actor = state.current_actor
                observation = match_observation_for(state, actor)
                policy = table[actor]
                showing = state.phase is EnginePhase.SHOWING
                ply = len(shows) + trick_ply

                action = None
                if not branched and plan.branch_kind == BRANCH_FORCED_CONTRACT:
                    if showing and not shows:
                        wanted = Contract.RAMI if arm == 0 else Contract.NOLO
                        action = _forced_contract_action(policy, observation, wanted)
                        if action is not None:
                            flags |= FLAG_FORCED_CONTRACT
                            branch_ply, branched = ply, True
                elif (
                    not branched
                    and plan.branch_kind == BRANCH_FORCED_PLAY
                    and not showing
                    and trick_ply == plan.branch_target
                ):
                    action = _forced_play_action(policy, observation, arm)
                    if action is not None:
                        flags |= FLAG_FORCED_PLAY
                        branch_ply, branched = ply, True

                if action is None:
                    action = policy.choose_action(observation)
                if showing:
                    shows.append((action.shown_card, action.declared_contract))
                else:
                    plays.append(action.card)
                    trick_ply += 1
                state = apply_match_action(state, action)

            if ordinal % manifest.revalidation_period == 0:
                validate_match_state(state)
                flags |= FLAG_REVALIDATED
            record = _deal_record(
                state.completed_deals[-1].public_result,
                hands=hands,
                shows=tuple(shows),
                plays=tuple(plays),
                flags=flags,
                branch_ply=branch_ply,
                arm=arm,
            )
            # Each deal is its own fresh match, so the engine numbers them all
            # zero. The ordinal is what identifies the pair.
            deals.append(replace(record, deal_number=ordinal))

    match = MatchRecord(
        stream_index=plan.stream_index,
        initial_dealer=plan.initial_dealer,
        initial_score=tuple(plan.initial_score),
        final_score=tuple(plan.initial_score),
        deals_played=len(deals),
        winner_team=None,
        termination=TERMINATION_FORCED_BRANCH,
        stratum=plan.stratum_index,
        policy_set=plan.policy_set_index,
        split=plan.split,
        pair_id=None if plan.pair_id is None else plan.pair_id * 2 + arm,
        first_deal_row=0,
    )
    return GeneratedUnit(match=match, deals=tuple(deals))


def _deal_record(
    result, *, hands, shows, plays, flags: int, branch_ply, arm: int
) -> DealRecord:
    score = result.deal_score
    points = (
        (score.points, 0) if score.winner_team is Team.TEAM_0 else (0, score.points)
    )
    if result.show_actions and result.show_actions[-1].verbal_required:
        flags |= FLAG_VERBAL_REQUIRED
    if result.match_terminal:
        flags |= FLAG_MATCH_TERMINAL
    reset = (result.score_before.team0 > 0 and result.score_after.team0 == 0) or (
        result.score_before.team1 > 0 and result.score_after.team1 == 0
    )
    if reset:
        flags |= FLAG_RESET
    return DealRecord(
        match_row=0,
        deal_number=result.deal_number,
        dealer=result.dealer,
        forehand=result.forehand,
        contract=result.contract,
        declarer=result.declarer,
        first_leader=result.first_leader,
        hands=tuple(tuple(hand) for hand in hands),
        shows=shows,
        plays=plays,
        trick_winners=tuple(trick.winner for trick in result.completed_tricks),
        team_tricks=tuple(result.team_tricks),
        deal_points=points,
        score_before=(result.score_before.team0, result.score_before.team1),
        score_after=(result.score_after.team0, result.score_after.team1),
        flags=flags,
        branch_ply=branch_ply,
        stratum_detail=arm,
    )


def assign_rows(units: tuple[GeneratedUnit, ...]) -> tuple[tuple, tuple]:
    """Flatten generated units into a shard's match and deal tables."""

    matches: list[MatchRecord] = []
    deals: list[DealRecord] = []
    for unit in units:
        match_row = len(matches)
        matches.append(replace(unit.match, first_deal_row=len(deals)))
        for deal in unit.deals:
            deals.append(replace(deal, match_row=match_row))
    return (tuple(matches), tuple(deals))


__all__ = [
    "GENERATION_SCHEMA_VERSION",
    "GeneratedUnit",
    "assign_rows",
    "generate_stream",
    "match_ref_for",
]
