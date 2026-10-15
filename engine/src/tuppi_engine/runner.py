"""Finite headless runner for explicit ``project_target_v1`` deal sequences."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

from .actions import Action, PlayCardAction, ShowAction
from .agents import Agent, FirstLegalActionAgent, FixedScriptAgent
from .errors import (
    AgentProtocolError,
    DealSequenceError,
    EngineError,
    RunnerConfigurationError,
)
from .match import (
    begin_explicit_deal,
    create_match,
    match_result_from_state,
    play_active_deal,
)
from .results import ResearchRunResult
from .serialization import (
    ExplicitMatchInput,
    agent_script_from_data,
    atomic_write_canonical_json_bundle,
    match_input_from_data,
    public_event_log_to_data,
    research_run_result_to_data,
    strict_json_load_file,
)


def run_match_input(
    match_input: ExplicitMatchInput,
    agents: tuple[Agent, Agent, Agent, Agent],
    *,
    require_complete_match: bool = False,
    expected_actions: tuple[Action, ...] | None = None,
) -> ResearchRunResult:
    if not isinstance(match_input, ExplicitMatchInput):
        raise RunnerConfigurationError("match_input must be an ExplicitMatchInput")
    if type(agents) is not tuple or len(agents) != 4:
        raise RunnerConfigurationError("exactly four agents are required")
    if len({id(agent) for agent in agents}) != 4:
        raise RunnerConfigurationError(
            "each seat requires a distinct agent object to preserve observation isolation"
        )
    identities: list[str] = []
    for agent in agents:
        if not callable(getattr(agent, "choose_action", None)):
            raise AgentProtocolError("every agent must implement choose_action")
        identity = getattr(agent, "identity", None)
        if not isinstance(identity, str) or not identity:
            raise AgentProtocolError("every agent must expose a nonempty identity")
        identities.append(identity)
    if expected_actions is not None and (
        type(expected_actions) is not tuple
        or any(
            not isinstance(action, (ShowAction, PlayCardAction))
            for action in expected_actions
        )
    ):
        raise RunnerConfigurationError("expected_actions must be an engine action tuple")
    action_position = 0

    def audit_action(action: Action) -> None:
        nonlocal action_position
        if expected_actions is None:
            return
        if action_position >= len(expected_actions):
            raise AgentProtocolError("global fixed script is exhausted")
        if action != expected_actions[action_position]:
            raise AgentProtocolError(
                f"fixed script action {action_position} was returned out of global order"
            )
        action_position += 1

    state = create_match(
        initial_score=match_input.initial_score,
        initial_dealer=match_input.initial_dealer,
        match_ref=match_input.match_ref,
    )
    for index, deal in enumerate(match_input.deals):
        if state.terminal:
            raise DealSequenceError(
                f"explicit deal {index} appears after the match already completed"
            )
        state = begin_explicit_deal(state, deal)
        state = play_active_deal(state, agents, action_audit=audit_action)

    for agent in agents:
        if isinstance(agent, FixedScriptAgent):
            agent.assert_consumed()
    if expected_actions is not None and action_position != len(expected_actions):
        raise AgentProtocolError(
            f"global fixed script has {len(expected_actions) - action_position} "
            "unconsumed action(s)"
        )
    if require_complete_match and not state.terminal:
        raise DealSequenceError(
            "supplied explicit deal sequence ended before the match reached 52"
        )
    match_result = match_result_from_state(state) if state.terminal else None
    return ResearchRunResult(
        match_input_id=match_input.match_input_id,
        match_ref=match_input.match_ref,
        initial_score=match_input.initial_score,
        initial_dealer=match_input.initial_dealer,
        agent_ids=(identities[0], identities[1], identities[2], identities[3]),
        deals=state.completed_deals,
        final_score=state.score,
        next_dealer=None if state.terminal else state.dealer,
        terminal=state.terminal,
        match_result=match_result,
        public_events=state.public_events,
    )


def _parse_agents(
    specification: str,
    *,
    script_path: str | None,
    match_input: ExplicitMatchInput,
) -> tuple[tuple[Agent, Agent, Agent, Agent], tuple[Action, ...] | None]:
    names = tuple(part.strip() for part in specification.split(","))
    if len(names) != 4 or any(not name for name in names):
        raise RunnerConfigurationError(
            "--agents must contain exactly four comma-separated names"
        )
    if all(name == "first-legal" for name in names):
        if script_path is not None:
            raise RunnerConfigurationError(
                "--script-file is incompatible with first-legal agents"
            )
        agents = tuple(FirstLegalActionAgent() for _ in range(4))
        return agents, None  # type: ignore[return-value]
    if all(name == "scripted" for name in names):
        if script_path is None:
            raise RunnerConfigurationError(
                "scripted agents require an explicit --script-file"
            )
        actions = agent_script_from_data(
            strict_json_load_file(script_path),
            expected_match_input_id=match_input.match_input_id,
        )
        by_seat = tuple(
            tuple(action for action in actions if action.seat == seat)
            for seat in range(4)
        )
        agents = tuple(FixedScriptAgent(seat_actions) for seat_actions in by_seat)
        return agents, actions  # type: ignore[return-value]
    raise RunnerConfigurationError(
        "supported agent sets are four first-legal agents or four scripted agents"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run finite explicit deals under project_target_v1"
    )
    parser.add_argument(
        "--deal-file",
        required=True,
        help="strict tuppi.engine.match_input.v1 JSON file (never stdin)",
    )
    parser.add_argument(
        "--agents",
        required=True,
        help="four comma-separated values: all first-legal or all scripted",
    )
    parser.add_argument("--script-file", help="strict fixed-action script JSON")
    parser.add_argument("--output", required=True, help="research-private result JSON")
    parser.add_argument("--event-log", help="optional privacy-safe public event log JSON")
    parser.add_argument(
        "--require-complete-match",
        action="store_true",
        help="fail if the supplied sequence does not reach at least 52",
    )
    parser.add_argument(
        "--verbosity",
        choices=("quiet", "normal", "debug"),
        default="normal",
        help="stderr reporting only; excluded from canonical gameplay content",
    )
    return parser


def _paths_alias(left: Path, right: Path) -> bool:
    """Compare existing hard links as well as unresolved future destinations."""

    try:
        return os.path.samefile(left, right)
    except OSError:
        return left.resolve() == right.resolve()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.deal_file == "-" or args.script_file == "-":
            raise RunnerConfigurationError("stdin is not supported")
        if args.output == "-" or args.event_log == "-":
            raise RunnerConfigurationError("stdout is not an authoritative output")
        input_paths = [Path(args.deal_file)]
        if args.script_file is not None:
            input_paths.append(Path(args.script_file))
        output_paths = [Path(args.output)]
        if args.event_log is not None:
            output_paths.append(Path(args.event_log))
        for left_index, left in enumerate(output_paths):
            for right in output_paths[left_index + 1 :]:
                if _paths_alias(left, right):
                    raise RunnerConfigurationError(
                        "--output and --event-log must differ"
                    )
            if any(_paths_alias(left, source) for source in input_paths):
                raise RunnerConfigurationError(
                    "output destinations must not alias deal or script inputs"
                )
        match_input = match_input_from_data(strict_json_load_file(args.deal_file))
        agents, expected_actions = _parse_agents(
            args.agents,
            script_path=args.script_file,
            match_input=match_input,
        )
        result = run_match_input(
            match_input,
            agents,
            require_complete_match=args.require_complete_match,
            expected_actions=expected_actions,
        )
        research_data = research_run_result_to_data(result)
        event_data = (
            None
            if args.event_log is None
            else public_event_log_to_data(
                result.public_events, match_ref=result.match_ref
            )
        )
        # All inputs and both artifacts are materialized before either output is
        # written. Each individual write is atomic and never truncates on error.
        outputs = ((args.output, research_data),)
        if args.event_log is not None:
            outputs += ((args.event_log, event_data),)
        atomic_write_canonical_json_bundle(outputs)
        if args.verbosity != "quiet":
            print(
                f"completed {len(result.deals)} deal(s); terminal={result.terminal}",
                file=sys.stderr,
            )
        return 0
    except EngineError as exc:
        print(f"tuppi-engine: {exc}", file=sys.stderr)
        if getattr(args, "verbosity", None) == "debug":
            import traceback

            traceback.print_exc(file=sys.stderr)
        return 2


def entrypoint() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    entrypoint()
