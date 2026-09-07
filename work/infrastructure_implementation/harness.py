"""Paired baseline/candidate harness for the INF-01..INF-03 efficiency tasks.

The same file is executed against two different ``src`` trees, chosen with
``--src``, so the identical workload measures the baseline and the candidate.
It only calls public package entry points plus the same private live-server
helpers the read-only audit used; it never patches production code for speed.

Modes
-----
``correctness``  canonical artifacts (observations, legal actions, events,
                 results, rejection classes, decisions, wire messages)
``counts``       validation, registry-build and projection call counts
``timing``       CPU/wall workloads for the INF-01..INF-03 acceptance gates
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_parser = argparse.ArgumentParser()
_parser.add_argument("--src", required=True)
_parser.add_argument("--mode", required=True,
                     choices=("correctness", "counts", "timing"))
_parser.add_argument("--out", required=True)
_parser.add_argument("--reps", type=int, default=5)
_parser.add_argument("--only", default="all")
ARGS = _parser.parse_args()

sys.path.insert(0, str(Path(ARGS.src).resolve()))

import asyncio  # noqa: E402
import dataclasses  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import platform  # noqa: E402
import statistics  # noqa: E402
import time  # noqa: E402
from collections import defaultdict  # noqa: E402
from unittest.mock import patch  # noqa: E402

import tuppi_engine  # noqa: E402

assert Path(tuppi_engine.__file__).resolve().is_relative_to(
    Path(ARGS.src).resolve()
), f"imported {tuppi_engine.__file__} instead of the requested tree"

from tuppi_engine import (  # noqa: E402
    CompletedTrick,
    DealState,
    EnginePhase,
    ExplicitDeal,
    MatchState,
    PlayCardAction,
    ShowAction,
    action_to_data,
    apply_action,
    apply_match_action,
    begin_explicit_deal,
    canonical_json_bytes,
    create_match,
    deal_result_from_state,
    deal_result_to_data,
    event_to_data,
    legal_actions_for,
    match_observation_for,
    match_result_from_state,
    match_result_to_data,
    observation_for,
    observation_to_data,
    validate_deal_state,
    validate_match_state,
)
from tuppi_agents.void_lead import construct_void_lead_agent, void_seeking_agents  # noqa: E402
from tuppi_eval.deals import DealerPolicy, generate_base_deal  # noqa: E402
from tuppi_rules import Contract, MatchScore  # noqa: E402
from tuppi_search.root_info_uct import RootInfoUctConfiguration, decide  # noqa: E402
from tuppi_server.app import Connection, TuppiASGIApp  # noqa: E402
from tuppi_server.match_runner import LiveMatchRunner  # noqa: E402
from tuppi_server.rooms import Room, RoomManager, Session  # noqa: E402
from tuppi_valuation.corpus import forced_show_action  # noqa: E402

SEED = "infrastructure-audit-2026-09-07-v1"
STRATA = (("NOLO", Contract.NOLO), ("RAMI", Contract.RAMI), ("natural", None))


def digest(data) -> str:
    return hashlib.sha256(canonical_json_bytes(data)).hexdigest()


def summary(values) -> dict:
    ordered = sorted(values)
    return dict(n=len(values), median=statistics.median(values),
                minimum=ordered[0], maximum=ordered[-1], total=sum(values))


def timed(fn, repeats: int):
    cpus, walls = [], []
    result = None
    for _ in range(repeats):
        c, w = time.process_time(), time.perf_counter()
        result = fn()
        cpus.append(time.process_time() - c)
        walls.append(time.perf_counter() - w)
    return dict(cpu=summary(cpus), wall=summary(walls)), result


def base_deal(index: int, dealer: int | None = None) -> ExplicitDeal:
    deal = generate_base_deal(root_seed=SEED, index=index,
                              dealer_policy=DealerPolicy.ROUND_ROBIN,
                              initial_dealer=0, starting_score=MatchScore())
    return ExplicitDeal(dealer=deal.dealer if dealer is None else dealer,
                        hands=deal.hands)


# --------------------------------------------------------------- workloads

def play_one_deal(index: int, contract, *, collect: bool = False):
    """One deal exactly as the audit measured it, optionally recording state."""

    sections: dict[str, list[float]] = defaultdict(list)
    mark = time.process_time()
    agents = tuple(construct_void_lead_agent(seat) for seat in range(4))
    sections["agents"].append(time.process_time() - mark)
    deal = base_deal(index)
    mark = time.process_time()
    state = begin_explicit_deal(
        create_match(initial_score=MatchScore(), initial_dealer=deal.dealer,
                     match_ref=f"infra:{index}:{contract}"),
        deal,
    )
    sections["construction"].append(time.process_time() - mark)
    actions, snapshots, trace = [], [], []
    while not state.active_deal.complete:
        actor = state.current_actor
        mark = time.process_time()
        observation = match_observation_for(state, actor)
        sections["observation"].append(time.process_time() - mark)
        mark = time.process_time()
        action = (forced_show_action(observation, contract)
                  if contract is not None and observation.phase is EnginePhase.SHOWING
                  else agents[actor].choose_action(observation))
        sections["choice"].append(time.process_time() - mark)
        if collect:
            trace.append(dict(
                actor=actor,
                action=action_to_data(action),
                phase=state.active_deal.phase.value,
                every_seat_observation=[
                    observation_to_data(match_observation_for(state, seat))
                    for seat in range(4)
                ],
                every_seat_legal_actions=[
                    [action_to_data(item)
                     for item in legal_actions_for(state.active_deal, seat)]
                    for seat in range(4)
                ],
                every_seat_deal_observation=[
                    observation_to_data(observation_for(state.active_deal, seat))
                    for seat in range(4)
                ],
                events=[event_to_data(event) for event in state.public_events],
            ))
        snapshots.append((state, observation, action))
        actions.append(action_to_data(action))
        mark = time.process_time()
        state = apply_match_action(state, action)
        sections["transition"].append(time.process_time() - mark)
    row = dict(index=index,
               forced=None if contract is None else contract.value,
               resolved=state.active_deal.contract.value,
               actions=len(actions), action_digest=digest(actions),
               sections={key: summary(value) for key, value in sections.items()})
    if collect:
        trace.append(dict(
            actor=None, action=None, phase=state.active_deal.phase.value,
            every_seat_observation=[
                observation_to_data(match_observation_for(state, seat))
                for seat in range(4)
            ],
            every_seat_legal_actions=[
                [action_to_data(item)
                 for item in legal_actions_for(state.active_deal, seat)]
                for seat in range(4)
            ],
            every_seat_deal_observation=[
                observation_to_data(observation_for(state.active_deal, seat))
                for seat in range(4)
            ],
            events=[event_to_data(event) for event in state.public_events],
        ))
        row["trace"] = trace
        row["deal_result"] = deal_result_to_data(
            deal_result_from_state(state.active_deal))
    return row, snapshots, state


def engine_batch(*, collect: bool = False):
    return [play_one_deal(index, contract, collect=collect)[0]
            for _, contract in STRATA for index in range(4)]


def uct_positions():
    """The six audited fast-UCT positions: deal 0, both contracts, 0/6/12."""

    positions = []
    for label, contract in STRATA[:2]:
        _, snapshots, _ = play_one_deal(0, contract)
        for depth in (0, 6, 12):
            _, observation, _ = next(
                row for row in snapshots
                if row[1].contract is contract
                and len(row[1].completed_tricks) == depth
                and not row[1].current_trick
            )
            positions.append((f"{label}-{depth}", observation))
    return positions


def live_broadcast_fixture():
    """The audit's live fixture: one deterministic RAMI deal, four AI seats."""

    with patch("tuppi_server.match_runner.generate_live_deal",
               side_effect=lambda *, dealer: base_deal(0, dealer)):
        runner = LiveMatchRunner(match_ref="infra-live",
                                 ai_seats=frozenset(range(4)),
                                 auto_run_ai=False)
    manager = RoomManager()
    sessions = {f"test-{seat}": Session(f"test-{seat}", seat, f"Player {seat}")
                for seat in range(4)}
    room = Room(code="AUDIT0", host_token="test-0", sessions=sessions,
                runner=runner, lifecycle="started")
    manager._rooms[room.code] = room
    app = TuppiASGIApp(manager)
    messages: list[dict] = []

    async def send(message):
        messages.append(message)

    connections = [Connection(room.code, f"test-{seat}", seat, send)
                   for seat in range(4)]
    return app, room, runner, connections, messages


def advance_live(runner):
    actor = runner.current_actor
    action, evaluation = runner._choose_ai_action(actor)
    runner._apply_ai_action(actor, action=action, contract_evaluation=evaluation)


def is_probe_point(runner) -> bool:
    deal = runner.state.active_deal
    return (len(deal.completed_tricks) in (0, 6, 12, 13)
            and not deal.current_trick)


# ------------------------------------------------------------- correctness

def forge(obj, **overrides):
    """Build a frozen-but-unvalidated copy, exactly as the engine tests do."""

    forged = object.__new__(type(obj))
    for field in dataclasses.fields(type(obj)):
        object.__setattr__(forged, field.name,
                           overrides.get(field.name, getattr(obj, field.name)))
    return forged


def outcome(fn):
    try:
        value = fn()
    except BaseException as exc:  # noqa: BLE001 - the class is the contract
        return dict(raised=type(exc).__name__, message=str(exc))
    return dict(raised=None, value_type=type(value).__name__)


def forged_deal_variants(state: DealState):
    hands = list(state.hands)
    swapped = list(hands)
    if hands[0] and hands[1]:
        swapped[0] = (hands[1][0],) + hands[0][1:]
        swapped[1] = (hands[0][0],) + hands[1][1:]
    trick = state.completed_tricks[0]
    forged_trick = forge(trick, winner=(trick.winner + 2) % 4)
    return {
        "deal_id": dict(deal_id="sha256:" + "0" * 64),
        "match_ref": dict(match_ref="other-match"),
        "deal_ref": dict(deal_ref=state.match_ref + "/deal:9"),
        "hands_swapped": dict(hands=tuple(swapped)),
        "team_tricks": dict(team_tricks=(9, 0)),
        "starting_score": dict(starting_score=MatchScore(5, 0)),
        "current_actor": dict(current_actor=(state.current_actor + 1) % 4),
        "phase_complete": dict(phase=EnginePhase.DEAL_COMPLETE),
        "trick_winner": dict(
            completed_tricks=(forged_trick,) + state.completed_tricks[1:]),
        "dropped_event": dict(events=state.events[:-1]),
        "contract_cleared": dict(contract=None),
        "first_leader": dict(first_leader=(state.first_leader + 1) % 4),
        "initial_hands": dict(initial_hands=tuple(swapped)),
        "declarer": dict(declarer=None if state.declarer is None else
                         (state.declarer + 1) % 4),
    }


def forged_match_variants(state: MatchState):
    return {
        "match_ref": dict(match_ref="other-match"),
        "score": dict(score=MatchScore(7, 0)),
        "dealer": dict(dealer=(state.dealer + 1) % 4),
        "phase": dict(phase=EnginePhase.DEAL_COMPLETE),
        "dropped_public_event": dict(public_events=state.public_events[:-1]),
        "no_active_deal": dict(active_deal=None),
        "initial_score": dict(initial_score=MatchScore(3, 0)),
    }


def capture_rejections():
    """Every public rejection this task is forbidden to weaken."""

    _, snapshots, terminal_deal_state = play_one_deal(0, Contract.RAMI)
    mid = next(row for row in snapshots
               if len(row[1].completed_tricks) == 6 and not row[1].current_trick)
    match_state, observation, action = mid
    deal_state = match_state.active_deal
    partial = next(row for row in snapshots
                   if row[1].phase is EnginePhase.TRICK_PLAY
                   and len(row[1].current_trick) == 2)
    showing = snapshots[0]

    rows: dict[str, dict] = {}

    def record(name, fn):
        rows[name] = outcome(fn)

    # Forged private deal state through every public deal entry point.
    for label, overrides in forged_deal_variants(deal_state).items():
        forged = forge(deal_state, **overrides)
        record(f"deal/{label}/validate", lambda f=forged: validate_deal_state(f))
        record(f"deal/{label}/observation", lambda f=forged: observation_for(f, 0))
        record(f"deal/{label}/legal_actions", lambda f=forged: legal_actions_for(f, 0))
        record(f"deal/{label}/apply", lambda f=forged: apply_action(f, action))
        record(f"deal/{label}/result", lambda f=forged: deal_result_from_state(f))
        # Rejection order: an invalid state must be reported before a bad seat.
        record(f"deal/{label}/observation_bad_seat",
               lambda f=forged: observation_for(f, 9))
        record(f"deal/{label}/legal_actions_bad_seat",
               lambda f=forged: legal_actions_for(f, 9))
        forged_match = forge(match_state, active_deal=forged)
        record(f"match_with_forged_deal/{label}/validate",
               lambda f=forged_match: validate_match_state(f))
        record(f"match_with_forged_deal/{label}/observation",
               lambda f=forged_match: match_observation_for(f, 0))
        record(f"match_with_forged_deal/{label}/observation_bad_seat",
               lambda f=forged_match: match_observation_for(f, 9))
        record(f"match_with_forged_deal/{label}/apply",
               lambda f=forged_match: apply_match_action(f, action))

    for label, overrides in forged_match_variants(match_state).items():
        forged = forge(match_state, **overrides)
        record(f"match/{label}/validate", lambda f=forged: validate_match_state(f))
        record(f"match/{label}/observation", lambda f=forged: match_observation_for(f, 0))
        record(f"match/{label}/observation_bad_seat",
               lambda f=forged: match_observation_for(f, 9))
        record(f"match/{label}/apply", lambda f=forged: apply_match_action(f, action))

    # Valid states, illegitimate requests.
    for seat in (9, -1, "0", True, None, 1.0):
        record(f"seat/{seat!r}/observation", lambda s=seat: observation_for(deal_state, s))
        record(f"seat/{seat!r}/legal_actions",
               lambda s=seat: legal_actions_for(deal_state, s))
        record(f"seat/{seat!r}/match_observation",
               lambda s=seat: match_observation_for(match_state, s))

    other = (action.seat + 1) % 4
    record("action/wrong_actor", lambda: apply_action(
        deal_state, PlayCardAction(seat=other, card=deal_state.hands[other][0])))
    record("action/wrong_actor_match", lambda: apply_match_action(
        match_state, PlayCardAction(seat=other, card=deal_state.hands[other][0])))
    record("action/show_in_trick_play",
           lambda: apply_action(deal_state, showing[2]))
    record("action/play_in_showing", lambda: apply_action(
        showing[0].active_deal, action))
    record("action/not_an_action", lambda: apply_action(deal_state, "play"))
    record("action/not_an_action_match",
           lambda: apply_match_action(match_state, "play"))
    record("action/none", lambda: apply_action(deal_state, None))
    record("action/terminal_deal",
           lambda: apply_action(terminal_deal_state.active_deal, action))
    record("action/terminal_match",
           lambda: apply_match_action(terminal_deal_state, action))
    record("observation/no_active_deal", lambda: match_observation_for(
        create_match(initial_score=MatchScore(), initial_dealer=0,
                     match_ref="pristine"), 0))
    record("observation/no_active_deal_bad_seat", lambda: match_observation_for(
        create_match(initial_score=MatchScore(), initial_dealer=0,
                     match_ref="pristine"), 9))
    record("result/incomplete_deal",
           lambda: deal_result_from_state(deal_state))
    record("result/incomplete_match",
           lambda: match_result_from_state(match_state))

    # A revoke: an off-suit card while the led suit is still held.
    partial_state = partial[0].active_deal
    led = partial_state.current_trick[0].card.suit
    actor = partial_state.current_actor
    hand = partial_state.hands[actor]
    if any(card.suit is led for card in hand):
        offsuit = next((card for card in hand if card.suit is not led), None)
        if offsuit is not None:
            record("action/revoke", lambda: apply_action(
                partial_state, PlayCardAction(seat=actor, card=offsuit)))
            record("action/revoke_match", lambda: apply_match_action(
                partial[0], PlayCardAction(seat=actor, card=offsuit)))
    # A card the actor does not hold at all.
    foreign = next(card for seat in range(4) if seat != actor
                   for card in partial_state.hands[seat])
    record("action/foreign_card", lambda: apply_action(
        partial_state, PlayCardAction(seat=actor, card=foreign)))
    return rows


def capture_full_matches():
    """Several fixed complete matches, as a separate match-history check."""

    rows = []
    for start in (0, 16, 32):
        agents = tuple(construct_void_lead_agent(seat) for seat in range(4))
        state = create_match(initial_score=MatchScore(), initial_dealer=0,
                             match_ref=f"infra-match:{start}")
        index = start
        deals = []
        while not state.terminal and index < start + 40:
            state = begin_explicit_deal(state, base_deal(index, state.dealer))
            while not state.active_deal.complete:
                actor = state.current_actor
                observation = match_observation_for(state, actor)
                state = apply_match_action(
                    state, agents[actor].choose_action(observation))
            deals.append(deal_result_to_data(state.completed_deals[-1].public_result))
            index += 1
        rows.append(dict(
            start=start, deals=len(deals), terminal=state.terminal,
            score=[state.score.team0, state.score.team1],
            deal_results=deals,
            public_events=[event_to_data(event) for event in state.public_events],
            match_result=(match_result_to_data(match_result_from_state(state))
                          if state.terminal else None),
        ))
    return rows


def capture_uct():
    rows = []
    for label, observation in uct_positions():
        for budget in (2, 4, 8, 16):
            configuration = RootInfoUctConfiguration.build(simulation_budget=budget)
            decision = decide(observation, configuration=configuration,
                              decision_seed="infra-search-v1")
            rows.append(dict(position=label, budget=budget,
                             decision=decision.to_data()))
    # Fresh runtime agents must stay distinct objects.
    agents = void_seeking_agents()
    rows.append(dict(position="void_seeking_agents", budget=None, decision=dict(
        identities=[agent.identity for agent in agents],
        distinct_objects=len({id(agent) for agent in agents}),
        classes=[type(agent).__name__ for agent in agents],
    )))
    subset = void_seeking_agents(seats=(0, 2))
    rows.append(dict(position="void_seeking_agents_subset", budget=None, decision=dict(
        identities=[agent.identity for agent in subset],
        distinct_objects=len({id(agent) for agent in subset}),
        classes=[type(agent).__name__ for agent in subset],
    )))
    from tuppi_agents import phase4_specifications_by_profile_key
    from tuppi_eval.identities import agent_spec_to_data
    first = phase4_specifications_by_profile_key()
    second = phase4_specifications_by_profile_key()
    mutated = phase4_specifications_by_profile_key()
    key = sorted(mutated)[0]
    try:
        mutated[key].configuration["profile"] = "tampered"
        mutation = "accepted"
    except Exception as exc:  # noqa: BLE001
        mutation = type(exc).__name__
    third = phase4_specifications_by_profile_key()
    rows.append(dict(position="registry", budget=None, decision=dict(
        catalogue=[{k: agent_spec_to_data(v) for k, v in sorted(first.items())}],
        stable=digest({k: agent_spec_to_data(v) for k, v in sorted(first.items())})
        == digest({k: agent_spec_to_data(v) for k, v in sorted(second.items())}),
        fresh_containers=first is not second,
        mutation_outcome=mutation,
        unaffected_after_mutation=digest(
            {k: agent_spec_to_data(v) for k, v in sorted(third.items())})
        == digest({k: agent_spec_to_data(v) for k, v in sorted(first.items())}),
    )))
    rows.append(dict(position="void_lead_error", budget=None, decision=dict(
        bad_seat=outcome(lambda: construct_void_lead_agent(9)),
        bad_profile=outcome(lambda: construct_void_lead_agent(0, profile_key="nope")),
        bad_batch_profile=outcome(lambda: void_seeking_agents("nope")),
        bad_batch_seats=outcome(lambda: void_seeking_agents(seats=(0, 7))),
    )))
    return rows


def capture_live_messages():
    """Exact wire messages for acting, nonacting, stale and terminal cases."""

    app, room, runner, connections, messages = live_broadcast_fixture()
    app._connections[room.code] = {c.token: c for c in connections}
    rows = []
    while not runner.state.completed_deals:
        advance_live(runner)
        if not is_probe_point(runner):
            continue
        for cursor_label, cursor in (("one_behind", runner.event_cursor - 1),
                                     ("fresh", -1),
                                     ("current", runner.event_cursor)):
            for count in (4, 1):
                messages.clear()
                for connection in connections[:count]:
                    connection.last_event_index = cursor
                app._connections[room.code] = {
                    c.token: c for c in connections[:count]}
                asyncio.run(app._broadcast_match(room.code))
                rows.append(dict(
                    tricks=len(runner.state.active_deal.completed_tricks),
                    cursor=cursor_label, recipients=count,
                    terminal=runner.terminal,
                    messages=[json.loads(m["text"]) for m in messages],
                ))
        app._connections[room.code] = {c.token: c for c in connections}
        for connection in connections:
            connection.last_event_index = runner.event_cursor
    # Directly compare the reconnect payload with the update projection.
    rows.append(dict(tricks=None, cursor="reconnect", recipients=0,
                     terminal=runner.terminal,
                     messages=[runner.reconnect(seat=seat,
                                                last_applied_event_index=-1)
                               for seat in range(4)]))
    return rows


def capture_completed_review():
    app, room, runner, connections, _ = live_broadcast_fixture()
    while not runner.state.completed_deals:
        advance_live(runner)
    manager = app.rooms
    review = manager.completed_deal_analysis_for_session(
        code=room.code, token="test-0", deal_number=0)
    cached = manager.completed_deal_analysis_for_session(
        code=room.code, token="test-0", deal_number=0)
    return dict(equal=review == cached, digest=digest(review))


def run_correctness():
    output = dict(
        src=str(Path(ARGS.src).resolve()),
        python=sys.version, platform=platform.platform(),
        engine_batch=engine_batch(collect=True),
        full_matches=capture_full_matches(),
        rejections=capture_rejections(),
        uct=capture_uct(),
        live_messages=capture_live_messages(),
        completed_review=capture_completed_review(),
    )
    return output


# ----------------------------------------------------------------- counts

class Counter:
    def __init__(self):
        self.deal_validations = 0
        self.match_validations = 0
        self.catalogue_builds = 0
        self.reconnects = 0
        self.seat_projections = 0

    def reset(self):
        self.__init__()

    def snapshot(self):
        return dict(deal_validations=self.deal_validations,
                    match_validations=self.match_validations,
                    catalogue_builds=self.catalogue_builds,
                    reconnects=self.reconnects,
                    seat_projections=self.seat_projections)


COUNTER = Counter()


def install_counters():
    import tuppi_agents.registry as registry
    import tuppi_engine.match as match_module
    import tuppi_engine.state as state_module
    import tuppi_server.projection as projection
    from tuppi_server.match_runner import LiveMatchRunner as Runner

    real_deal = state_module._validate_deal_state_rules

    def counted_deal(state):
        COUNTER.deal_validations += 1
        return real_deal(state)

    state_module._validate_deal_state_rules = counted_deal

    real_match = match_module._validate_match_state

    def counted_match(state):
        COUNTER.match_validations += 1
        return real_match(state)

    match_module._validate_match_state = counted_match

    real_profiles = registry.registered_profiles

    def counted_profiles():
        COUNTER.catalogue_builds += 1
        return real_profiles()

    registry.registered_profiles = counted_profiles

    real_reconnect = Runner.reconnect

    def counted_reconnect(self, **kwargs):
        COUNTER.reconnects += 1
        return real_reconnect(self, **kwargs)

    Runner.reconnect = counted_reconnect

    real_projection = projection.match_observation_for

    def counted_projection(state, seat):
        COUNTER.seat_projections += 1
        return real_projection(state, seat)

    projection.match_observation_for = counted_projection


def measure(name, fn, rows):
    COUNTER.reset()
    error = None
    try:
        fn()
    except BaseException as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"
    rows[name] = dict(COUNTER.snapshot(), error=error)


def run_counts():
    install_counters()
    rows: dict[str, dict] = {}
    for label, contract in STRATA[:2]:
        _, snapshots, terminal = play_one_deal(0, contract)
        for depth in (0, 6, 12):
            match_state, observation, action = next(
                row for row in snapshots
                if len(row[1].completed_tricks) == depth and not row[1].current_trick)
            seat = observation.observing_seat
            deal_state = match_state.active_deal
            measure(f"{label}-{depth}/match_observation_for",
                    lambda s=match_state, t=seat: match_observation_for(s, t), rows)
            measure(f"{label}-{depth}/observation_for",
                    lambda s=deal_state, t=seat: observation_for(s, t), rows)
            measure(f"{label}-{depth}/legal_actions_for",
                    lambda s=deal_state, t=seat: legal_actions_for(s, t), rows)
            measure(f"{label}-{depth}/apply_match_action",
                    lambda s=match_state, a=action: apply_match_action(s, a), rows)
            measure(f"{label}-{depth}/apply_action",
                    lambda s=deal_state, a=action: apply_action(s, a), rows)
        # Terminal paths are audited separately, never forced to the same counts.
        final_match, _, final_action = snapshots[-1]
        measure(f"{label}-final/apply_match_action",
                lambda s=final_match, a=final_action: apply_match_action(s, a), rows)
        measure(f"{label}-final/apply_action",
                lambda s=final_match.active_deal, a=final_action: apply_action(s, a),
                rows)
        measure(f"{label}-complete/match_observation_for",
                lambda s=terminal: match_observation_for(s, 0), rows)
        measure(f"{label}-complete/deal_result_from_state",
                lambda s=terminal.active_deal: deal_result_from_state(s), rows)

    measure("engine/one_deal_natural", lambda: play_one_deal(0, None), rows)
    measure("engine/twelve_deal_batch", engine_batch, rows)

    for label, observation in uct_positions():
        for budget in (2, 4, 8, 16):
            configuration = RootInfoUctConfiguration.build(simulation_budget=budget)
            measure(f"uct/{label}/budget-{budget}",
                    lambda o=observation, c=configuration: decide(
                        o, configuration=c, decision_seed="infra-search-v1"), rows)
    measure("agents/void_seeking_agents", void_seeking_agents, rows)
    measure("agents/four_construct_calls",
            lambda: tuple(construct_void_lead_agent(seat) for seat in range(4)), rows)

    app, room, runner, connections, messages = live_broadcast_fixture()
    app._connections[room.code] = {c.token: c for c in connections}
    probe = 0
    while not runner.state.completed_deals:
        advance_live(runner)
        if not is_probe_point(runner):
            continue
        tricks = len(runner.state.active_deal.completed_tricks)
        for count in (4, 1):
            def broadcast(count=count):
                messages.clear()
                app._connections[room.code] = {
                    c.token: c for c in connections[:count]}
                for connection in connections[:count]:
                    connection.last_event_index = runner.event_cursor - 1
                return asyncio.run(app._broadcast_match(room.code))
            measure(f"live/probe-{probe}/tricks-{tricks}/recipients-{count}",
                    broadcast, rows)
        probe += 1
        app._connections[room.code] = {c.token: c for c in connections}
        for connection in connections:
            connection.last_event_index = runner.event_cursor
    return rows


# ----------------------------------------------------------------- timing

def run_timing():
    reps = ARGS.reps
    output: dict[str, object] = dict(src=str(Path(ARGS.src).resolve()),
                                     reps=reps,
                                     python=sys.version,
                                     platform=platform.platform(),
                                     machine=platform.machine())
    want = ARGS.only

    if want in ("all", "inf01"):
        cold, rows = timed(engine_batch, 1)
        output["engine_batch_cold"] = cold
        output["engine_batch_cold_digest"] = digest(
            [row["action_digest"] for row in rows])
        warm = []
        for _ in range(reps):
            timing, rows = timed(engine_batch, 1)
            strata: dict[str, float] = defaultdict(float)
            for row in rows:
                key = row["forced"] or "natural"
                strata[key] += sum(
                    row["sections"][name]["total"]
                    for name in ("observation", "transition", "choice",
                                 "agents", "construction"))
            warm.append(dict(timing=timing, strata=dict(strata),
                             digest=digest([row["action_digest"] for row in rows])))
        output["engine_batch"] = warm

    if want in ("all", "inf02"):
        positions = uct_positions()
        uct_rows = []
        for label, observation in positions:
            for budget in (2, 4, 8, 16):
                configuration = RootInfoUctConfiguration.build(
                    simulation_budget=budget)

                def search(o=observation, c=configuration):
                    return decide(o, configuration=c,
                                  decision_seed="infra-search-v1")

                search()  # warm the finite exact caches for this position
                timing, decision = timed(search, reps)
                uct_rows.append(dict(position=label, budget=budget,
                                     timing=timing,
                                     digest=digest(decision.to_data())))
        output["uct"] = uct_rows
        agent_timing, _ = timed(void_seeking_agents, reps * 4)
        output["void_seeking_agents"] = agent_timing
        construct_timing, _ = timed(
            lambda: tuple(construct_void_lead_agent(seat) for seat in range(4)),
            reps * 4)
        output["four_construct_calls"] = construct_timing

    if want in ("all", "inf03"):
        app, room, runner, connections, messages = live_broadcast_fixture()
        app._connections[room.code] = {c.token: c for c in connections}
        live_rows = []
        probe = 0
        while not runner.state.completed_deals:
            advance_live(runner)
            if not is_probe_point(runner):
                continue
            tricks = len(runner.state.active_deal.completed_tricks)
            phase = runner.state.active_deal.phase.value
            for count in (4, 1):
                def broadcast(count=count):
                    messages.clear()
                    app._connections[room.code] = {
                        c.token: c for c in connections[:count]}
                    for connection in connections[:count]:
                        connection.last_event_index = runner.event_cursor - 1
                    return asyncio.run(app._broadcast_match(room.code))
                broadcast()
                timing, _ = timed(broadcast, reps)
                live_rows.append(dict(probe=probe, tricks=tricks,
                                      recipients=count, phase=phase,
                                      terminal=runner.terminal, timing=timing,
                                      payload_bytes=sum(len(m["text"])
                                                        for m in messages)))
            probe += 1
            app._connections[room.code] = {c.token: c for c in connections}
            for connection in connections:
                connection.last_event_index = runner.event_cursor
        output["live_update"] = live_rows
    return output


MODES = dict(correctness=run_correctness, counts=run_counts, timing=run_timing)
result = MODES[ARGS.mode]()
payload = canonical_json_bytes(result) if ARGS.mode == "correctness" else (
    json.dumps(result, indent=2, sort_keys=True, default=str).encode())
Path(ARGS.out).write_bytes(payload + b"\n")
print(f"{ARGS.mode} -> {ARGS.out} sha256={hashlib.sha256(payload).hexdigest()}")
