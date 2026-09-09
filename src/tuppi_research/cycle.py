"""One bounded control cycle over the existing evaluator.

    hypothesis -> candidate -> legality -> paired execution -> admission
    -> analysis -> review -> recorded finding

Every heavy step is delegated. The engine plays the deals, :mod:`tuppi_eval`
builds the schedule, runs the arena, forms the blocks and computes the estimator,
and :func:`tuppi_eval.qualification.admitted_blocks` decides whether the evidence
covers the plan. This module owns only the order of the steps, the restart state,
and the fact that a finished run is not yet a finding.

The cycle shipped here is a *null control*: candidate and incumbent are the same
production incumbent, so the correct outcome is "no effect" and accepting it is a
bug. It exists to show the loop closes and to calibrate the instrument, not to
measure strength.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

from tuppi_agents.improved_registry import improved_specifications_by_profile_key
from tuppi_agents.research_candidates import (
    candidate_specifications_by_key,
    research_candidates,
)
from tuppi_engine import (
    EnginePhase,
    ExplicitDeal,
    apply_match_action,
    begin_explicit_deal,
    create_match,
    match_observation_for,
)
from tuppi_eval.agents import construct_agent
from tuppi_eval.arena import run_evaluation
from tuppi_eval.config import (
    EvaluationConfiguration,
    FailurePolicy,
    OutputMode,
    PrimaryMetric,
    SeedHierarchy,
    SequentialMode,
    SequentialProtocol,
    TimeoutLimits,
)
from tuppi_eval.deals import DealBank, DealerPolicy, generate_deal_bank
from tuppi_eval.errors import InterruptedEvaluation
from tuppi_eval.identities import AgentSpecification, TeamSpecification
from tuppi_eval.qualification import admitted_blocks, expected_blocks_for
from tuppi_eval.records import ExecutionStatus
from tuppi_eval.registry import AgentRegistry, baseline_agent_specifications
from tuppi_eval.schedules import (
    CANONICAL_BLOCK_SIZE,
    CANONICAL_SCHEDULE_DESIGN,
    EvaluationMode,
    Schedule,
    build_canonical_schedule,
)
from tuppi_eval.statistics import paired_statistical_summary
from tuppi_rules import FULL_DECK, MatchScore

from .decisions import DEAL_POINTS_SCREENING_RULE, DecisionRule, decide
from .errors import CycleError, LegalityError
from .ledger import ExecutionState, Ledger, Verdict, digest_file

#: The user-designated production incumbent. Imported, never promoted here.
REFERENCE_PROFILE = "partner_aware_lead_v2"

#: The development surrogate endpoint, in the units the evaluator actually
#: produces. Named so a recorded finding cannot be silently reread as equity.
ENDPOINT = "mean_signed_deal_points_per_eight_game_block"

#: Deliberately small. The control validates the loop, not a hypothesis.
DEFAULT_BASE_DEALS = 4
MAX_BASE_DEALS = 64


def reference_specification() -> AgentSpecification:
    return improved_specifications_by_profile_key()[REFERENCE_PROFILE]


def reference_registry() -> AgentRegistry:
    """Controls plus the incumbent, so fault fixtures share one registry."""

    return AgentRegistry.build(
        baseline_agent_specifications() + (reference_specification(),)
    )


def reference_team(description: str) -> TeamSpecification:
    specification = reference_specification()
    return TeamSpecification.build(
        component_agent_ids=(specification.agent_id, specification.agent_id),
        partner_convention_id=None,
        shared_instances=False,
        description=description,
    )


def candidate_specification(candidate_key: str) -> AgentSpecification:
    specifications = candidate_specifications_by_key()
    if candidate_key not in specifications:
        raise CycleError(f"undeclared research candidate {candidate_key!r}")
    return specifications[candidate_key]


def candidate_team(candidate_key: str) -> TeamSpecification:
    specification = candidate_specification(candidate_key)
    return TeamSpecification.build(
        component_agent_ids=(specification.agent_id, specification.agent_id),
        partner_convention_id=None,
        shared_instances=False,
        description=f"Research candidate {candidate_key}, both partner seats.",
    )


@dataclass(frozen=True, slots=True)
class ExperimentDeclaration:
    """What is being compared, and whether it is a control that cannot win."""

    hypothesis: str
    candidate_id: str
    incumbent_id: str
    is_null_control: bool


def null_control_declaration() -> ExperimentDeclaration:
    specification = reference_specification()
    return ExperimentDeclaration(
        hypothesis=(
            "A candidate identical to the production incumbent produces no "
            "measurable difference on the paired development endpoint."
        ),
        candidate_id=specification.agent_id,
        incumbent_id=specification.agent_id,
        is_null_control=True,
    )


def candidate_declaration(candidate_key: str) -> ExperimentDeclaration:
    """A declared candidate against the incumbent.

    ``is_null_control`` stays True only when the candidate is behaviourally a
    pass-through, which the registry marks explicitly. Everything else is a real
    comparison, and :func:`review` will return INCONCLUSIVE for it until a
    useful-effect threshold exists.
    """

    declared = research_candidates()[candidate_key]
    return ExperimentDeclaration(
        hypothesis=(
            f"Research candidate {candidate_key} (base "
            f"{declared.base_profile_key}, override "
            f"{declared.override.override_id}) differs from the production "
            "incumbent on the paired development endpoint."
        ),
        candidate_id=candidate_specification(candidate_key).agent_id,
        incumbent_id=reference_specification().agent_id,
        is_null_control=declared.override.override_id == "tuppi.research.noop.v1",
    )


@dataclass(frozen=True, slots=True)
class CycleInputs:
    registry: AgentRegistry
    team_a: TeamSpecification
    team_b: TeamSpecification
    bank: DealBank
    schedule: Schedule
    config: EvaluationConfiguration


@dataclass
class CycleReport:
    run_id: str
    experiment_id: str
    execution_state: ExecutionState
    verdict: Verdict | None = None
    finding_id: str | None = None
    units: int = 0
    summary: dict[str, Any] = field(default_factory=dict)
    control_checks: list[dict[str, Any]] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)

    def to_data(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "experiment_id": self.experiment_id,
            "execution_state": self.execution_state.value,
            "verdict": None if self.verdict is None else self.verdict.value,
            "finding_id": self.finding_id,
            "units": self.units,
            "endpoint": ENDPOINT,
            "promotion": "not_performed",
            "summary": self.summary,
            "control_checks": self.control_checks,
            "blocked": self.blocked,
        }


def build_inputs(
    *,
    base_deals: int = DEFAULT_BASE_DEALS,
    root_seed: str = "tuppi-research-null-control-v1",
    analysis_seed: str = "tuppi-research-analysis-v1",
    per_action_seconds: float | None = None,
) -> CycleInputs:
    """Native inputs for the null control: the incumbent against itself."""

    incumbent = reference_team("Imported production incumbent, both partner seats.")
    return build_inputs_for_teams(
        registry=reference_registry(),
        team_a=incumbent,
        team_b=incumbent,
        base_deals=base_deals,
        root_seed=root_seed,
        analysis_seed=analysis_seed,
        per_action_seconds=per_action_seconds,
        description="Null control: the production incumbent against itself.",
    )


def build_candidate_inputs(
    candidate_key: str,
    *,
    base_deals: int = DEFAULT_BASE_DEALS,
    root_seed: str | None = None,
    analysis_seed: str | None = None,
) -> CycleInputs:
    """Candidate (team A) against the imported production incumbent (team B)."""

    candidate = candidate_specification(candidate_key)
    incumbent = reference_specification()
    registry = AgentRegistry.build(
        baseline_agent_specifications() + (incumbent, candidate)
    )
    return build_inputs_for_teams(
        registry=registry,
        team_a=candidate_team(candidate_key),
        team_b=reference_team("Imported production incumbent, both partner seats."),
        base_deals=base_deals,
        root_seed=root_seed or f"tuppi-research-{candidate_key}-v1",
        analysis_seed=analysis_seed or f"tuppi-research-{candidate_key}-analysis-v1",
        description=f"Research candidate {candidate_key} versus the incumbent.",
    )


def build_inputs_for_teams(
    *,
    registry: AgentRegistry,
    team_a: TeamSpecification,
    team_b: TeamSpecification,
    base_deals: int = DEFAULT_BASE_DEALS,
    root_seed: str = "tuppi-research-null-control-v1",
    analysis_seed: str = "tuppi-research-analysis-v1",
    per_action_seconds: float | None = None,
    description: str = "Research control cycle.",
) -> CycleInputs:
    """Assemble native inputs. Configures no estimator and no threshold.

    Separate from :func:`build_inputs` so that fault fixtures can substitute the
    non-strategic Phase 3 teams without hand-editing an immutable configuration -
    ``EvaluationConfiguration`` is content addressed, so ``dataclasses.replace``
    on one produces an object that refuses to validate.
    """

    if type(base_deals) is not int or not 1 <= base_deals <= MAX_BASE_DEALS:
        raise CycleError(f"base_deals must be an integer in 1..{MAX_BASE_DEALS}")
    bank = generate_deal_bank(
        count=base_deals,
        root_seed=root_seed,
        dealer_policy=DealerPolicy.ROUND_ROBIN,
        initial_dealer=0,
        starting_score=MatchScore(),
        creation_metadata={"purpose": "research_control_cycle", "seed": root_seed},
    )
    schedule = build_canonical_schedule(
        deal_bank=bank, team_a=team_a, team_b=team_b, mode=EvaluationMode.DEAL
    )
    config = EvaluationConfiguration.build(
        ruleset_id="project_target_v1",
        engine_identity="tuppi_engine:phase2",
        deal_bank_id=bank.deal_bank_id,
        agent_specifications=registry.specifications,
        agent_registry_digest=registry.registry_digest,
        team_a=team_a,
        team_b=team_b,
        schedule_id=schedule.schedule_id,
        schedule_design_id=CANONICAL_SCHEDULE_DESIGN,
        evaluation_mode=EvaluationMode.DEAL,
        match_sequence_length=None,
        starting_score=MatchScore(),
        dealer_policy=DealerPolicy.ROUND_ROBIN,
        number_base_deals=base_deals,
        transformations_applied=tuple(
            item.transformation_id for item in schedule.transformations
        ),
        failure_policy=FailurePolicy.CONTINUE,
        output_mode=OutputMode.RAW_AND_SUMMARY,
        confidence_level=0.95,
        bootstrap_replicates=2000,
        permutation_replicates=2000,
        primary_metric=PrimaryMetric.PAIRED_DUPLICATE_UTILITY,
        seed_hierarchy=SeedHierarchy(
            deal_root_seed=root_seed,
            agent_root_seed=root_seed,
            analysis_seed=analysis_seed,
        ),
        timeouts=TimeoutLimits(
            per_action_seconds=per_action_seconds,
            per_deal_seconds=None,
            per_match_seconds=None,
        ),
        sequential_protocol=SequentialProtocol(
            mode=SequentialMode.FIXED_SAMPLE,
            maximum_base_deals=base_deals,
            interim_checkpoints=(),
            stopping_boundaries=(),
        ),
        software_environment={"layer": "tuppi_research", "cycle": "control"},
        description=description,
    )
    return CycleInputs(registry, team_a, team_b, bank, schedule, config)


# --------------------------------------------------------------- legality
def preflight_legality(inputs: CycleInputs) -> dict[str, Any]:
    """Correctness before measurement: construct, isolate, and play legally.

    Cheap and bounded on purpose - one scripted deal. It is a precondition, not a
    substitute for the engine's own property suite.
    """

    specification = reference_specification()
    agents = [
        construct_agent(specification, seed=None, seat=seat) for seat in range(4)
    ]
    if len({id(agent) for agent in agents}) != 4:
        raise LegalityError("candidate construction shared a runtime instance")
    if len({agent.identity for agent in agents}) != 1:
        raise LegalityError("one policy produced several identities")
    hands = tuple(tuple(FULL_DECK[seat * 13 : (seat + 1) * 13]) for seat in range(4))
    state = create_match(
        initial_score=MatchScore(), initial_dealer=0, match_ref="research-preflight"
    )
    state = begin_explicit_deal(state, ExplicitDeal(dealer=0, hands=hands))
    decisions = 0
    while state.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
        actor = state.current_actor
        observation = match_observation_for(state, actor)
        if set(observation.own_hand) - set(hands[actor]):
            raise LegalityError(f"seat {actor} observed a card it does not hold")
        action = agents[actor].choose_action(observation)
        if action not in observation.legal_actions:
            raise LegalityError(
                f"seat {actor} chose an action outside the engine's legal tuple"
            )
        state = apply_match_action(state, action)
        decisions += 1
    if decisions != 56:
        raise LegalityError(f"scripted deal produced {decisions} decisions, not 56")
    return {
        "agent_id": specification.agent_id,
        "distinct_instances_per_seat": True,
        "decisions": decisions,
        "every_action_within_legal_tuple": True,
        "observation_confined_to_own_hand": True,
    }


# --------------------------------------------------------------- execution
def _plan(schedule: Schedule) -> tuple[tuple[int, str], ...]:
    seen: dict[int, str] = {}
    for entry in schedule.entries:
        seen.setdefault(entry.block_index, entry.base_deal_id)
    return tuple(sorted(seen.items()))


def execute_cycle(
    ledger: Ledger,
    inputs: CycleInputs,
    *,
    output_directory: Path,
    max_new_games: int | None = None,
    notes: str = "",
    experiment: "ExperimentDeclaration | None" = None,
) -> tuple[str, str, ExecutionState]:
    """Register, then run or resume. Returns (experiment_id, run_id, state).

    ``experiment`` defaults to the null control so the R2 entry point is
    unchanged; a declared candidate supplies its own.
    """

    declaration = experiment or null_control_declaration()
    experiment_id = ledger.record_experiment(
        hypothesis=declaration.hypothesis,
        endpoint=ENDPOINT,
        incumbent_id=declaration.incumbent_id,
        candidate_id=declaration.candidate_id,
        is_null_control=declaration.is_null_control,
        notes=notes,
    )
    output = Path(output_directory)
    run_id = ledger.open_run(
        experiment_id=experiment_id,
        evaluation_id=inputs.config.evaluation_id,
        schedule_id=inputs.schedule.schedule_id,
        config_digest=inputs.config.configuration_digest,
        deal_bank_id=inputs.config.deal_bank_id,
        output_directory=str(output),
        planned_units=_plan(inputs.schedule),
        games_per_unit=CANONICAL_BLOCK_SIZE,
    )
    try:
        run = run_evaluation(
            inputs.config,
            inputs.bank,
            inputs.schedule,
            output_directory=output,
            max_new_games=max_new_games,
        )
    except InterruptedEvaluation as exc:
        # A partially executed unit stays PLANNED. It is never half-counted.
        ledger.set_run_state(
            run_id=run_id, state=ExecutionState.INTERRUPTED, failure=str(exc)
        )
        return experiment_id, run_id, ExecutionState.INTERRUPTED

    failed = tuple(
        record
        for record in run.result.game_records
        if record.execution_status is not ExecutionStatus.SUCCESS
    )
    for block in run.result.duplicate_blocks:
        if block.complete and block.paired_utility is not None:
            ledger.complete_unit(
                run_id=run_id,
                block_index=block.block_index,
                observed_games=block.valid_game_count,
                block_record_id=block.block_record_id,
                paired_utility=block.paired_utility,
            )
        else:
            ledger.fail_unit(
                run_id=run_id,
                block_index=block.block_index,
                detail=(
                    f"{block.invalid_game_count} of {CANONICAL_BLOCK_SIZE} games "
                    "did not succeed"
                ),
            )
    for name in ("evaluation_result.json", "summary.json", "reproducibility_manifest.json"):
        path = output / name
        if path.is_file():
            ledger.record_artifact(
                run_id=run_id, kind=name.removesuffix(".json"), path=path, root=output
            )
    ledger.record_control_check(
        run_id=run_id,
        name="arena_execution",
        passed=not failed,
        detail=(
            f"{len(run.result.game_records)} games, {len(failed)} failed, "
            f"{run.resumed_game_count} resumed, {run.executed_game_count} executed"
        ),
    )
    incomplete = ledger.incomplete_units(run_id)
    state = ExecutionState.COMPLETE if not incomplete else ExecutionState.FAILED
    ledger.set_run_state(
        run_id=run_id,
        state=state,
        failure=None if not incomplete else f"incomplete units {list(incomplete)}",
    )
    return experiment_id, run_id, state


# ---------------------------------------------------------------- analysis
def analyse(inputs: CycleInputs, output_directory: Path) -> dict[str, Any]:
    """Admit the planned manifest, then delegate to the unchanged estimator."""

    result_path = Path(output_directory) / "evaluation_result.json"
    if not result_path.is_file():
        raise CycleError("no evaluation result to analyse; run the cycle first")
    from tuppi_eval.serialization import strict_json_load_file
    from tuppi_eval.records import evaluation_result_from_data

    result = evaluation_result_from_data(strict_json_load_file(result_path))
    expected = expected_blocks_for(inputs.config, inputs.schedule)
    admitted = admitted_blocks(result.duplicate_blocks, expected)
    summary = paired_statistical_summary(
        admitted,
        confidence_level=inputs.config.confidence_level,
        analysis_seed=inputs.config.seed_hierarchy.analysis_seed,
        bootstrap_replicates=inputs.config.bootstrap_replicates,
        permutation_replicates=inputs.config.permutation_replicates,
    )
    return {
        "admitted_units": len(admitted),
        "block_utilities": [block.paired_utility for block in admitted],
        "statistics": summary,
    }


# ------------------------------------------------------------------ review
def review(
    analysis: dict[str, Any],
    *,
    is_null_control: bool,
    rule: DecisionRule = DEAL_POINTS_SCREENING_RULE,
) -> tuple[Verdict, str]:
    """Turn analysis into a verdict under a declared rule. Separate from execution.

    The rule is what makes this a review rather than a shrug. Before one existed
    every real candidate was recorded INCONCLUSIVE, including one that lost by
    20.33 points per block - a label that described the project's own missing
    threshold rather than the evidence.

    A null control must come out practically equivalent. If it does not, that is an
    instrument fault, not a finding, and it is raised rather than recorded.
    """

    statistics = analysis["statistics"]
    verdict, statement = decide(
        rule,
        endpoint=ENDPOINT,
        confidence_interval=statistics["confidence_interval"],
        confidence_level=statistics["confidence_level"],
    )
    if is_null_control:
        if verdict is not Verdict.NO_EFFECT:
            raise CycleError(
                f"null control was judged {verdict.value!r}; the candidate is not "
                "identical or the instrument is wrong - this is not a finding"
            )
        statement = (
            "Null control: candidate and incumbent are the identical imported "
            f"production incumbent over {analysis['admitted_units']} independent "
            f"base deals. {statement} The exact zero is the design's own algebraic "
            "identity and is the expected outcome, so it confirms the instrument "
            "and establishes nothing about strength. No policy is promoted."
        )
    return verdict, statement


def record_cycle_finding(
    ledger: Ledger,
    *,
    experiment_id: str,
    run_id: str,
    analysis: dict[str, Any],
    output_directory: Path,
    reviewed_by: str,
    is_null_control: bool = True,
    rule: DecisionRule = DEAL_POINTS_SCREENING_RULE,
) -> tuple[Verdict, str]:
    verdict, statement = review(analysis, is_null_control=is_null_control, rule=rule)
    summary_path = Path(output_directory) / "summary.json"
    summary_sha256, _ = digest_file(summary_path)
    finding_id = ledger.record_finding(
        experiment_id=experiment_id,
        run_id=run_id,
        verdict=verdict,
        endpoint=ENDPOINT,
        decision_rule_id=rule.rule_id,
        summary_sha256=summary_sha256,
        statement=statement,
        reviewed_by=reviewed_by,
    )
    return verdict, finding_id


# --------------------------------------------------------- instrument checks
# Both checks below are exact, so neither needs a threshold. An earlier draft
# also tried an orientation check by swapping team_a and team_b and requiring
# each unit's utility to negate. That is not a valid identity: `_seat_assignments`
# gives engine team 0 to whichever team is labelled A for a row, so swapping the
# arguments moves a team between seat groups (0, 2) and (1, 3) on unchanged cards
# rather than merely relabelling it. The play changes, so no exact negation is
# predicted and the check was dropped instead of weakened into a tolerance.


def null_control_zero_check(analysis: dict[str, Any]) -> dict[str, Any]:
    """For an identical candidate every unit must be **exactly** zero.

    This is an algebraic identity of the canonical design, not a tolerance. The
    eight rows of a block are relabellings of one base deal; a policy that does
    not condition on labels therefore reaches the same deal outcome on all eight,
    and the balanced assignment gives external team A the winning engine team on
    exactly four of them. The signed values cancel to the last bit.

    It is the strongest single check in the cycle because one number validates
    four separate things at once: that the design really is balanced, that the
    sign convention is consistent, that ``paired_utility`` is the mean of the
    eight rather than some other combination, and that the candidate genuinely is
    behaviourally identical. Any nonzero value here is an instrument fault or a
    candidate that is not what it claims to be - never a result.
    """

    utilities = analysis["block_utilities"]
    offenders = [
        (index, value) for index, value in enumerate(utilities) if value != 0.0
    ]
    if offenders:
        raise CycleError(
            "null control did not cancel exactly; the instrument or the "
            f"candidate is wrong, not the world: {offenders}"
        )
    mean = analysis["statistics"]["mean_paired_utility"]
    if mean != 0.0:
        raise CycleError(f"null control mean is {mean!r}, not exactly 0.0")
    return {
        "units": len(utilities),
        "every_unit_exactly_zero": True,
        "mean_exactly_zero": True,
    }


def determinism_check(inputs: CycleInputs, first: Path, second: Path) -> dict[str, Any]:
    """The same inputs must produce the same content-addressed game records."""

    digests = []
    for output in (first, second):
        run = run_evaluation(
            inputs.config, inputs.bank, inputs.schedule, output_directory=output
        )
        digests.append(
            tuple(record.record_id for record in run.result.game_records)
        )
    identical = digests[0] == digests[1]
    if not identical:
        raise CycleError("repeated identical evaluation produced different records")
    return {
        "games": len(digests[0]),
        "record_identities_identical": True,
    }


class _NoOpDelegate:
    """Pass-through wrapper: same identity, same observation, same action."""

    __slots__ = ("_inner",)

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    @property
    def identity(self) -> str:
        return self._inner.identity

    def choose_action(self, observation: Any) -> Any:
        return self._inner.choose_action(observation)


def noop_parity_check() -> dict[str, Any]:
    """A behaviourally transparent wrapper must not change one action.

    This is what makes the null control meaningful: if wrapping a policy could
    perturb it, "identical candidate" would not be identical.
    """

    specification = reference_specification()

    def trace(wrap: bool) -> tuple[str, ...]:
        agents = {
            seat: construct_agent(specification, seed=None, seat=seat)
            for seat in range(4)
        }
        if wrap:
            agents = {seat: _NoOpDelegate(agent) for seat, agent in agents.items()}
        hands = tuple(
            tuple(FULL_DECK[seat * 13 : (seat + 1) * 13]) for seat in range(4)
        )
        state = create_match(
            initial_score=MatchScore(), initial_dealer=0, match_ref="research-noop"
        )
        state = begin_explicit_deal(state, ExplicitDeal(dealer=0, hands=hands))
        actions: list[str] = []
        while state.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
            actor = state.current_actor
            action = agents[actor].choose_action(match_observation_for(state, actor))
            actions.append(repr(action))
            state = apply_match_action(state, action)
        return tuple(actions)

    plain, wrapped = trace(False), trace(True)
    if plain != wrapped:
        raise CycleError("a no-op wrapper changed the action trace")
    return {"actions": len(plain), "trace_identical": True}


__all__ = [
    "CycleInputs",
    "CycleReport",
    "DEFAULT_BASE_DEALS",
    "ENDPOINT",
    "REFERENCE_PROFILE",
    "analyse",
    "DEAL_POINTS_SCREENING_RULE",
    "ExperimentDeclaration",
    "build_candidate_inputs",
    "build_inputs",
    "build_inputs_for_teams",
    "candidate_declaration",
    "candidate_specification",
    "candidate_team",
    "execute_cycle",
    "preflight_legality",
    "determinism_check",
    "noop_parity_check",
    "null_control_declaration",
    "null_control_zero_check",
    "record_cycle_finding",
    "reference_registry",
    "reference_specification",
    "reference_team",
    "review",
]
