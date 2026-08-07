"""Phase 5C development evaluation: deal-level ablations and complete matches.

Two instruments, at very different costs.

**Deal-level duplicate ablation.** Each base deal is played twice from the same
starting score: once with the candidate partnership at seats 0 and 2, once at seats
1 and 3. The paired value is the candidate's signed utility in the even leg minus
the odd leg, halved - the same complementary-leg construction the complete-match
protocol uses, applied to a single deal. One deal instead of roughly thirty makes
this the affordable instrument for the many pairwise ablations.

It is a **screening** instrument. Phase 5A established that signed deal points are
blind to match safety, so a deal-level result can say "these two agents differ" and
must never be read as "this agent is stronger over matches".

**Complete-match comparison.** The frozen Phase 5A protocol, unmodified:
:func:`tuppi_match.protocol.run_pair`, complementary legs on the same extensible
stream, natural termination, orientation-averaged match-win probability as the
primary endpoint, and :func:`tuppi_match.statistics.pair_inference` for the
statistics. Phase 5C supplies its own agent builders - the one thing the Phase 5A
executor cannot do for a profile outside the Phase 4 registry - and changes nothing
else.

Banks
-----

Phase 5C uses new root seeds. Reusing a Phase 5A or 5B bank would reuse fixtures
that were already inspected, and the sealed promotion bank is not touched at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math

from tuppi_agents import construct_agent, phase4_specifications_by_profile_key
from tuppi_engine import (
    ExplicitDeal,
    apply_action,
    begin_explicit_deal,
    create_match,
    observation_for,
)
from tuppi_match.banks import BankRole, StreamBank
from tuppi_match.manifest import MatchComparison
from tuppi_match.protocol import run_pair
from tuppi_match.executor import _pair_from_data
from tuppi_match.records import PairRecord
from tuppi_match.statistics import pair_inference, secondary_metrics
from tuppi_rules import MatchScore, Team

from .config import DEVELOPMENT_REFERENCE_POLICY
from .errors import SearchError
from .registry import build_agent, specification_for
from .utilities import (
    OutcomeSource,
    UtilityId,
    summary_from_completed_deal,
    utility_value,
)


EVALUATION_SCHEMA_VERSION = "tuppi.search.phase5c_evaluation.v1"

DEAL_ABLATION_ROOT_SEED = "tuppi-phase5c-deal-ablation-v1"
MATCH_COMPARISON_ROOT_SEED = "tuppi-phase5c-match-comparison-v1"

CONFIDENCE_LEVEL = 0.95
BOOTSTRAP_REPLICATES = 2000
SIGN_FLIP_REPLICATES = 10000
DEFAULT_SAFETY_CAP = 704


def deal_ablation_bank(*, stream_count: int) -> StreamBank:
    return StreamBank.build(
        name="phase5c_deal_ablation_v1",
        role=BankRole.DEVELOPMENT,
        root_seed=DEAL_ABLATION_ROOT_SEED,
        initial_dealer=0,
        stream_count=stream_count,
        purpose=(
            "Phase 5C deal-level duplicate screening for PIMC ablations. A "
            "development bank; deal-level results screen for behavioural "
            "differences and support no match-strength claim."
        ),
    )


def match_comparison_bank(*, stream_count: int) -> StreamBank:
    return StreamBank.build(
        name="phase5c_match_comparison_v1",
        role=BankRole.DEVELOPMENT,
        root_seed=MATCH_COMPARISON_ROOT_SEED,
        initial_dealer=0,
        stream_count=stream_count,
        purpose=(
            "Phase 5C complete-match development comparison for the PIMC baseline. "
            "A development bank; the promotion-sealed bank stays unopened."
        ),
    )


# ------------------------------------------------------------- agent builders


def _phase4_builder(profile_key: str):
    specification = phase4_specifications_by_profile_key()[profile_key]
    return lambda seat: construct_agent(specification, seat=seat)


def _pimc_builder(profile_key: str):
    return lambda seat: build_agent(profile_key, seat=seat)


def agent_builder(profile_key: str):
    """Resolve a builder for a Phase 4 profile key or a Phase 5C profile key."""

    if profile_key in phase4_specifications_by_profile_key():
        return _phase4_builder(profile_key)
    return _pimc_builder(profile_key)


def agent_identity(profile_key: str) -> str:
    phase4 = phase4_specifications_by_profile_key()
    if profile_key in phase4:
        return phase4[profile_key].agent_id
    return specification_for(profile_key).agent_id


# ------------------------------------------------------- deal-level ablation


@dataclass(frozen=True, slots=True)
class DealPairResult:
    """One complementary deal pair."""

    ordinal: int
    even_utility: float
    odd_utility: float
    even_candidate_wins: bool
    odd_candidate_wins: bool
    even_actions: int
    odd_actions: int

    @property
    def paired_value(self) -> float:
        return (self.even_utility - self.odd_utility) / 2.0

    @property
    def paired_deal_wins(self) -> float:
        return (
            int(self.even_candidate_wins) - int(self.odd_candidate_wins)
        ) / 2.0


def _play_one_deal(
    *,
    hands: tuple,
    dealer: int,
    starting_score: MatchScore,
    candidate_seats: tuple[int, ...],
    build_candidate,
    build_opponent,
    match_ref: str,
    utility_id: UtilityId,
) -> tuple[float, bool, int]:
    """Play one complete deal and return the candidate team's utility."""

    state = create_match(
        initial_score=starting_score, initial_dealer=dealer, match_ref=match_ref
    )
    state = begin_explicit_deal(state, ExplicitDeal(dealer=dealer, hands=hands))
    deal = state.active_deal
    if deal is None:  # pragma: no cover - begin_explicit_deal always sets it
        raise SearchError("the deal did not begin")
    agents = tuple(
        (build_candidate if seat in candidate_seats else build_opponent)(seat)
        for seat in range(4)
    )
    if len({id(agent) for agent in agents}) != 4:
        raise SearchError("deal ablation constructed a shared runtime agent object")
    actions = 0
    while not deal.complete:
        actor = deal.current_actor
        observation = observation_for(deal, actor)
        deal = apply_action(deal, agents[actor].choose_action(observation))
        actions += 1
    root_seat = candidate_seats[0]
    summary = summary_from_completed_deal(
        deal, root_seat=root_seat, source=OutcomeSource.ROLLOUT, tricks_simulated=13
    )
    return (
        utility_value(utility_id, summary),
        summary.root_team_wins_deal,
        actions,
    )


def run_deal_ablation(
    *,
    candidate_profile_key: str,
    opponent_profile_key: str,
    deals: int,
    starting_score: tuple[int, int] = (0, 0),
    utility_id: UtilityId = UtilityId.MATCH_TRANSITION_V1,
    progress=None,
) -> dict[str, object]:
    """Screen two agents over complementary deal pairs on a fresh bank."""

    if type(deals) is not int or deals <= 0:
        raise SearchError("deal count must be a positive integer")
    bank = deal_ablation_bank(stream_count=max(deals, 1))
    build_candidate = agent_builder(candidate_profile_key)
    build_opponent = agent_builder(opponent_profile_key)
    score = MatchScore(*starting_score)

    results: list[DealPairResult] = []
    for ordinal in range(deals):
        stream = bank.stream(ordinal)
        stream_deal = stream.deal(0)
        even_utility, even_win, even_actions = _play_one_deal(
            hands=stream_deal.hands,
            dealer=stream.initial_dealer,
            starting_score=score,
            candidate_seats=(0, 2),
            build_candidate=build_candidate,
            build_opponent=build_opponent,
            match_ref=f"dp-e-{ordinal:06d}",
            utility_id=utility_id,
        )
        odd_utility, odd_win, odd_actions = _play_one_deal(
            hands=stream_deal.hands,
            dealer=stream.initial_dealer,
            starting_score=score,
            candidate_seats=(1, 3),
            build_candidate=build_candidate,
            build_opponent=build_opponent,
            match_ref=f"dp-o-{ordinal:06d}",
            utility_id=utility_id,
        )
        results.append(
            DealPairResult(
                ordinal=ordinal,
                even_utility=even_utility,
                odd_utility=odd_utility,
                even_candidate_wins=even_win,
                odd_candidate_wins=odd_win,
                even_actions=even_actions,
                odd_actions=odd_actions,
            )
        )
        if progress is not None:
            progress(ordinal + 1, deals)

    values = [item.paired_value for item in results]
    wins = [item.paired_deal_wins for item in results]
    mean = math.fsum(values) / len(values)
    deviation = (
        math.sqrt(math.fsum((value - mean) ** 2 for value in values) / len(values))
        if len(values) > 1
        else 0.0
    )
    return {
        "bank": bank.to_data(),
        "candidate_agent_id": agent_identity(candidate_profile_key),
        "candidate_profile_key": candidate_profile_key,
        "deal_pairs": len(results),
        "interpretation": (
            "A deal-level screening result. Phase 5A established that signed deal "
            "value is blind to match safety, so this may show that two agents "
            "differ and may never be read as a match-strength claim."
        ),
        "mean_paired_deal_win_advantage": round(
            math.fsum(wins) / len(wins), 6
        ),
        "mean_paired_utility": round(mean, 6),
        "opponent_agent_id": agent_identity(opponent_profile_key),
        "opponent_profile_key": opponent_profile_key,
        "pairs_candidate_ahead": sum(1 for value in values if value > 0),
        "pairs_candidate_behind": sum(1 for value in values if value < 0),
        "pairs_tied": sum(1 for value in values if value == 0),
        "schema_version": "tuppi.search.deal_ablation.v1",
        "standard_error_paired_utility": round(
            deviation / math.sqrt(len(values)) if len(values) > 1 else 0.0, 6
        ),
        "starting_score": list(starting_score),
        "total_actions": sum(
            item.even_actions + item.odd_actions for item in results
        ),
        "utility_id": utility_id.value,
    }


# ----------------------------------------------------- complete-match design


def build_match_comparison(
    *, candidate_profile_key: str, opponent_profile_key: str, hypothesis: str
) -> MatchComparison:
    return MatchComparison.build(
        name=f"phase5c_{candidate_profile_key}_vs_{opponent_profile_key}",
        candidate_profile_key=candidate_profile_key,
        opponent_profile_key=opponent_profile_key,
        candidate_agent_id=agent_identity(candidate_profile_key),
        opponent_agent_id=agent_identity(opponent_profile_key),
        result_class="development",
        hypothesis=hypothesis,
    )


def _match_unit(payload: tuple) -> tuple[int, dict]:
    """Process-pool entry point. Rebuilds agents inside the worker."""

    (
        candidate_key,
        opponent_key,
        comparison_data,
        stream_count,
        safety_cap,
        ordinal,
    ) = payload
    comparison = MatchComparison.build(
        name=comparison_data["name"],
        candidate_profile_key=comparison_data["candidate_profile_key"],
        opponent_profile_key=comparison_data["opponent_profile_key"],
        candidate_agent_id=comparison_data["candidate_agent_id"],
        opponent_agent_id=comparison_data["opponent_agent_id"],
        result_class=comparison_data["result_class"],
        hypothesis=comparison_data["hypothesis"],
        starting_score=tuple(comparison_data["starting_score"]),
    )
    bank = match_comparison_bank(stream_count=stream_count)
    record = run_pair(
        stream=bank.stream(ordinal),
        comparison=comparison,
        safety_cap=safety_cap,
        ordinal=ordinal,
        build_candidate=agent_builder(candidate_key),
        build_opponent=agent_builder(opponent_key),
    )
    return (ordinal, record.to_data())


def run_match_comparison(
    *,
    candidate_profile_key: str,
    opponent_profile_key: str = DEVELOPMENT_REFERENCE_POLICY,
    pairs: int,
    safety_cap: int = DEFAULT_SAFETY_CAP,
    hypothesis: str | None = None,
    workers: int | None = None,
    progress=None,
) -> dict[str, object]:
    """Run the frozen complete-match protocol with a PIMC candidate."""

    if type(pairs) is not int or pairs <= 0:
        raise SearchError("pair count must be a positive integer")
    comparison = build_match_comparison(
        candidate_profile_key=candidate_profile_key,
        opponent_profile_key=opponent_profile_key,
        hypothesis=hypothesis
        or (
            f"Does {candidate_profile_key} beat {opponent_profile_key} over "
            "complete matches from 0-0?"
        ),
    )
    bank = match_comparison_bank(stream_count=pairs)
    units = [
        (
            candidate_profile_key,
            opponent_profile_key,
            comparison.to_data(),
            pairs,
            safety_cap,
            ordinal,
        )
        for ordinal in range(pairs)
    ]
    collected: dict[int, PairRecord] = {}
    done = 0
    if workers is None or workers <= 1:
        for unit in units:
            ordinal, data = _match_unit(unit)
            collected[ordinal] = _pair_from_data(data)
            done += 1
            if progress is not None:
                progress(done, len(units))
    else:
        from concurrent.futures import ProcessPoolExecutor

        with ProcessPoolExecutor(max_workers=workers) as pool:
            for ordinal, data in pool.map(_match_unit, units, chunksize=1):
                collected[ordinal] = _pair_from_data(data)
                done += 1
                if progress is not None:
                    progress(done, len(units))

    records = tuple(collected[ordinal] for ordinal in range(pairs))
    return {
        "bank": bank.to_data(),
        "candidate_profile_key": candidate_profile_key,
        "comparison_id": comparison.comparison_id,
        "hypothesis": comparison.hypothesis,
        "name": comparison.name,
        "opponent_profile_key": opponent_profile_key,
        "pair_count": pairs,
        "primary_match_inference": pair_inference(
            records,
            confidence_level=CONFIDENCE_LEVEL,
            analysis_seed=MATCH_COMPARISON_ROOT_SEED,
            bootstrap_replicates=BOOTSTRAP_REPLICATES,
            sign_flip_replicates=SIGN_FLIP_REPLICATES,
        ),
        "safety_cap": safety_cap,
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "secondary_metrics": secondary_metrics(records),
        "sign_convention": (
            "The candidate is the PIMC agent, so p_win above 0.5 means PIMC beats "
            "the opponent over complete matches."
        ),
        "worker_independence": (
            "Every pair is a pure function of the bank, comparison, safety cap, "
            "and ordinal, so the worker count changes wall-clock time only."
        ),
    }


def showing_contract_sensitivity(
    *,
    world_counts: tuple[int, ...] = (2, 4, 8, 16),
    deals: int = 24,
    rollout_policy_key: str = DEVELOPMENT_REFERENCE_POLICY,
    utility_id: UtilityId = UtilityId.MATCH_TRANSITION_V1,
    progress=None,
) -> dict[str, object]:
    """How often does PIMC declare RAMI, as a function of the world budget?

    This instrument exists because of a specific measured finding: the first
    complete-match comparison showed the PIMC baseline declaring RAMI far more often
    than any Phase 4 agent, and losing a much larger share of those contracts to
    ramin ryöstö. The natural explanation is **selection optimism**: the selected
    action is the argmax of a handful of noisy per-world means, and taking a maximum
    over noisy estimates is biased upward. RAMI's value distribution is far wider
    than NOLO's - it wins big or is stolen for double - so the noisier option is
    systematically flattered, and the bias shrinks as the world count grows.

    Showing decisions only, so it is cheap: a showing root is replayed once per
    world budget with no trick play at all beyond the rollouts the search itself
    performs. Comparing against the frozen reference agent's own declaration rate on
    the *same* deals gives the contrast a baseline.
    """

    from .config import PimcConfiguration
    from .pimc import decide

    if not world_counts:
        raise SearchError("showing sensitivity needs at least one world count")
    bank = deal_ablation_bank(stream_count=max(deals, 1))
    reference = phase4_specifications_by_profile_key()[rollout_policy_key]

    rami_counts = {count: 0 for count in world_counts}
    decisions = {count: 0 for count in world_counts}
    reference_rami = 0
    reference_decisions = 0
    for ordinal in range(deals):
        stream = bank.stream(ordinal)
        stream_deal = stream.deal(2)
        state = create_match(
            initial_score=MatchScore(),
            initial_dealer=stream.initial_dealer,
            match_ref=f"showsens-{ordinal:06d}",
        )
        state = begin_explicit_deal(
            state,
            ExplicitDeal(dealer=stream.initial_dealer, hands=stream_deal.hands),
        )
        deal = state.active_deal
        # Only the forehand's first showing decision is compared, so every deal
        # contributes exactly one observation and the counts stay balanced.
        actor = deal.current_actor
        observation = observation_for(deal, actor)
        reference_action = construct_agent(reference, seat=actor).choose_action(
            observation
        )
        reference_decisions += 1
        if reference_action.declared_contract.value == "RAMI":
            reference_rami += 1
        for count in world_counts:
            configuration = PimcConfiguration.build(
                world_count=count,
                rollout_policy_key=rollout_policy_key,
                utility_id=utility_id,
            )
            decision = decide(
                observation,
                configuration=configuration,
                decision_seed=f"showsens-{ordinal}",
            )
            decisions[count] += 1
            if decision.selected_action.declared_contract.value == "RAMI":
                rami_counts[count] += 1
        if progress is not None:
            progress(ordinal + 1, deals)

    return {
        "deals": deals,
        "hypothesis": (
            "Selection optimism: the chosen action is the argmax of a few noisy "
            "per-world means, which flatters the higher-variance contract. If that "
            "is the mechanism, the RAMI declaration rate falls as the world count "
            "rises and approaches the reference agent's rate."
        ),
        "pimc_rami_declaration_rate": {
            str(count): round(rami_counts[count] / decisions[count], 6)
            for count in sorted(world_counts)
        },
        "reference_policy_key": rollout_policy_key,
        "reference_rami_declaration_rate": round(
            reference_rami / reference_decisions, 6
        ),
        "schema_version": "tuppi.search.showing_contract_sensitivity.v1",
        "utility_id": utility_id.value,
        "world_counts": list(sorted(world_counts)),
    }


def heterogeneous_partnership_diagnostic(
    *, pimc_profile_key: str, deals: int, progress=None
) -> dict[str, object]:
    """Deal-level diagnostic for mixed partnerships.

    Diagnostic only. A mixed partnership shares no convention, so a difference here
    describes how the two policies interact, not which is stronger.
    """

    designs = (
        (
            "pimc_with_reference_vs_reference_pair",
            (pimc_profile_key, DEVELOPMENT_REFERENCE_POLICY),
            (DEVELOPMENT_REFERENCE_POLICY, DEVELOPMENT_REFERENCE_POLICY),
        ),
        (
            "pimc_pair_vs_pimc_with_reference",
            (pimc_profile_key, pimc_profile_key),
            (pimc_profile_key, DEVELOPMENT_REFERENCE_POLICY),
        ),
    )
    results = []
    for name, candidate_pair, opponent_pair in designs:
        results.append(
            {
                "candidate_partnership": list(candidate_pair),
                "name": name,
                "opponent_partnership": list(opponent_pair),
                "result": _mixed_deal_screen(
                    candidate_pair=candidate_pair,
                    opponent_pair=opponent_pair,
                    deals=deals,
                    progress=progress,
                ),
            }
        )
    return {
        "designs": results,
        "interpretation": (
            "Heterogeneous partnership diagnostics only. A mixed partnership shares "
            "no partner convention, so these numbers describe interaction, not "
            "strength."
        ),
        "schema_version": "tuppi.search.heterogeneous_diagnostic.v1",
    }


def _mixed_deal_screen(
    *,
    candidate_pair: tuple[str, str],
    opponent_pair: tuple[str, str],
    deals: int,
    progress=None,
) -> dict[str, object]:
    bank = deal_ablation_bank(stream_count=max(deals, 1))
    builders = {
        0: agent_builder(candidate_pair[0]),
        2: agent_builder(candidate_pair[1]),
        1: agent_builder(opponent_pair[0]),
        3: agent_builder(opponent_pair[1]),
    }
    values: list[float] = []
    for ordinal in range(deals):
        stream = bank.stream(ordinal)
        stream_deal = stream.deal(1)
        state = create_match(
            initial_score=MatchScore(),
            initial_dealer=stream.initial_dealer,
            match_ref=f"het-{ordinal:06d}",
        )
        state = begin_explicit_deal(
            state, ExplicitDeal(dealer=stream.initial_dealer, hands=stream_deal.hands)
        )
        deal = state.active_deal
        agents = tuple(builders[seat](seat) for seat in range(4))
        while not deal.complete:
            actor = deal.current_actor
            deal = apply_action(
                deal, agents[actor].choose_action(observation_for(deal, actor))
            )
        summary = summary_from_completed_deal(
            deal, root_seat=0, source=OutcomeSource.ROLLOUT, tricks_simulated=13
        )
        values.append(utility_value(UtilityId.MATCH_TRANSITION_V1, summary))
        if progress is not None:
            progress(ordinal + 1, deals)
    return {
        "candidate_team": Team.TEAM_0.value,
        "deals": len(values),
        "mean_candidate_utility": round(math.fsum(values) / len(values), 6),
        "note": (
            "Single-orientation deal screen; not complementary and not paired, so "
            "it carries seat and dealer effects the duplicate design removes."
        ),
        "utility_id": UtilityId.MATCH_TRANSITION_V1.value,
    }


# ------------------------------------------------------------- Phase 5D-A


PHASE5D_A_MATCH_ROOT_SEED = "tuppi-phase5d-a-match-v1"
PHASE5D_A_DEAL_ROOT_SEED = "tuppi-phase5d-a-deal-v1"
PHASE5D_A_CORPUS_ROOT_SEED = "tuppi-phase5d-a-corpus-v1"
PHASE5D_A_HETERO_ROOT_SEED = "tuppi-phase5d-a-heterogeneous-v1"


def phase5d_a_match_bank(*, stream_count: int) -> StreamBank:
    """Fresh complete-match streams for the Phase 5D-A homogeneous comparisons.

    A new root seed. The Phase 5C primary used 32 streams from
    ``phase5c_match_comparison_v1``; re-running variants on those same streams would
    be tuning against the fixture that produced the result being explained.
    """

    return StreamBank.build(
        name="phase5d_a_match_v1",
        role=BankRole.DEVELOPMENT,
        root_seed=PHASE5D_A_MATCH_ROOT_SEED,
        initial_dealer=0,
        stream_count=stream_count,
        purpose=(
            "Phase 5D-A complete-match streams for the play-only and show-only "
            "decompositions. A development bank, distinct from every Phase 5C "
            "fixture; the promotion-sealed bank stays unopened."
        ),
    )


def phase5d_a_hetero_bank(*, stream_count: int) -> StreamBank:
    """Fresh streams for the seat-balanced heterogeneous partnership designs."""

    return StreamBank.build(
        name="phase5d_a_heterogeneous_v1",
        role=BankRole.DEVELOPMENT,
        root_seed=PHASE5D_A_HETERO_ROOT_SEED,
        initial_dealer=0,
        stream_count=stream_count,
        purpose=(
            "Phase 5D-A heterogeneous-partnership complete-match streams. Separate "
            "from the homogeneous bank so a mixed-team result never shares a "
            "fixture with a homogeneous one."
        ),
    )


def phase5d_a_deal_bank(*, stream_count: int) -> StreamBank:
    """Fresh deals for the Phase 5D-A deal-level screens."""

    return StreamBank.build(
        name="phase5d_a_deal_v1",
        role=BankRole.DEVELOPMENT,
        root_seed=PHASE5D_A_DEAL_ROOT_SEED,
        initial_dealer=0,
        stream_count=stream_count,
        purpose=(
            "Phase 5D-A deal-level duplicate screens. Screening only: Phase 5A "
            "established that signed deal value is blind to match safety."
        ),
    )


def phase5d_a_corpus_bank(*, stream_count: int) -> StreamBank:
    """Fresh deals from which the frozen decision corpus is sampled."""

    return StreamBank.build(
        name="phase5d_a_corpus_v1",
        role=BankRole.DEVELOPMENT,
        root_seed=PHASE5D_A_CORPUS_ROOT_SEED,
        initial_dealer=0,
        stream_count=stream_count,
        purpose=(
            "Phase 5D-A frozen decision corpus. Positions are sampled from "
            "reference-agent play on a development bank and stored as formal "
            "observations; the true state lives in a separate restricted channel."
        ),
    )


def phase5d_a_agent_builder(profile_key: str):
    """Resolve a builder for a Phase 4, Phase 5C, or Phase 5D-A profile key."""

    from .registry import build_phase5d_a_agent, is_phase5d_a_profile

    if is_phase5d_a_profile(profile_key):
        return lambda seat: build_phase5d_a_agent(profile_key, seat=seat)
    return agent_builder(profile_key)


def phase5d_a_agent_identity(profile_key: str) -> str:
    from .registry import is_phase5d_a_profile, phase5d_a_specification

    if is_phase5d_a_profile(profile_key):
        return phase5d_a_specification(profile_key).agent_id
    return agent_identity(profile_key)


def _phase5d_a_unit(payload: tuple) -> tuple[int, dict]:
    """Process-pool entry point for a homogeneous Phase 5D-A pair."""

    (
        candidate_key,
        opponent_key,
        comparison_data,
        stream_count,
        safety_cap,
        ordinal,
    ) = payload
    comparison = MatchComparison.build(
        name=comparison_data["name"],
        candidate_profile_key=comparison_data["candidate_profile_key"],
        opponent_profile_key=comparison_data["opponent_profile_key"],
        candidate_agent_id=comparison_data["candidate_agent_id"],
        opponent_agent_id=comparison_data["opponent_agent_id"],
        result_class=comparison_data["result_class"],
        hypothesis=comparison_data["hypothesis"],
        starting_score=tuple(comparison_data["starting_score"]),
    )
    bank = phase5d_a_match_bank(stream_count=stream_count)
    record = run_pair(
        stream=bank.stream(ordinal),
        comparison=comparison,
        safety_cap=safety_cap,
        ordinal=ordinal,
        build_candidate=phase5d_a_agent_builder(candidate_key),
        build_opponent=phase5d_a_agent_builder(opponent_key),
    )
    return (ordinal, record.to_data())


def run_phase5d_a_match_comparison(
    *,
    candidate_profile_key: str,
    opponent_profile_key: str = DEVELOPMENT_REFERENCE_POLICY,
    pairs: int,
    safety_cap: int = DEFAULT_SAFETY_CAP,
    hypothesis: str | None = None,
    workers: int | None = None,
    progress=None,
) -> dict[str, object]:
    """Homogeneous complete-match comparison on the fresh Phase 5D-A bank."""

    if type(pairs) is not int or pairs <= 0:
        raise SearchError("pair count must be a positive integer")
    comparison = MatchComparison.build(
        name=f"phase5d_a_{candidate_profile_key}_vs_{opponent_profile_key}",
        candidate_profile_key=candidate_profile_key,
        opponent_profile_key=opponent_profile_key,
        candidate_agent_id=phase5d_a_agent_identity(candidate_profile_key),
        opponent_agent_id=phase5d_a_agent_identity(opponent_profile_key),
        result_class="development",
        hypothesis=hypothesis
        or (
            f"Does {candidate_profile_key} beat {opponent_profile_key} over "
            "complete matches from 0-0?"
        ),
    )
    bank = phase5d_a_match_bank(stream_count=pairs)
    units = [
        (
            candidate_profile_key,
            opponent_profile_key,
            comparison.to_data(),
            pairs,
            safety_cap,
            ordinal,
        )
        for ordinal in range(pairs)
    ]
    collected: dict[int, PairRecord] = {}
    done = 0
    if workers is None or workers <= 1:
        for unit in units:
            ordinal, data = _phase5d_a_unit(unit)
            collected[ordinal] = _pair_from_data(data)
            done += 1
            if progress is not None:
                progress(done, len(units))
    else:
        from concurrent.futures import ProcessPoolExecutor

        with ProcessPoolExecutor(max_workers=workers) as pool:
            for ordinal, data in pool.map(_phase5d_a_unit, units, chunksize=1):
                collected[ordinal] = _pair_from_data(data)
                done += 1
                if progress is not None:
                    progress(done, len(units))

    records = tuple(collected[ordinal] for ordinal in range(pairs))
    return {
        "bank": bank.to_data(),
        "candidate_profile_key": candidate_profile_key,
        "comparison_id": comparison.comparison_id,
        "design": "homogeneous_partnership",
        "hypothesis": comparison.hypothesis,
        "name": comparison.name,
        "opponent_profile_key": opponent_profile_key,
        "pair_count": pairs,
        "primary_match_inference": pair_inference(
            records,
            confidence_level=CONFIDENCE_LEVEL,
            analysis_seed=PHASE5D_A_MATCH_ROOT_SEED,
            bootstrap_replicates=BOOTSTRAP_REPLICATES,
            sign_flip_replicates=SIGN_FLIP_REPLICATES,
        ),
        "safety_cap": safety_cap,
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "secondary_metrics": secondary_metrics(records),
        "sign_convention": (
            "The candidate is the search variant, so p_win above 0.5 means the "
            "variant beats the opponent over complete matches."
        ),
        "worker_independence": (
            "Every pair is a pure function of the bank, comparison, safety cap, "
            "and ordinal, so the worker count changes wall-clock time only."
        ),
    }


def _hetero_unit(payload: tuple) -> tuple[int, dict]:
    """Process-pool entry point for one seat-balanced heterogeneous pair."""

    (
        search_key,
        partner_key,
        opponent_key,
        arrangement,
        comparison_data,
        stream_count,
        safety_cap,
        ordinal,
    ) = payload
    comparison = MatchComparison.build(
        name=comparison_data["name"],
        candidate_profile_key=comparison_data["candidate_profile_key"],
        opponent_profile_key=comparison_data["opponent_profile_key"],
        candidate_agent_id=comparison_data["candidate_agent_id"],
        opponent_agent_id=comparison_data["opponent_agent_id"],
        result_class=comparison_data["result_class"],
        hypothesis=comparison_data["hypothesis"],
        starting_score=tuple(comparison_data["starting_score"]),
    )
    bank = phase5d_a_hetero_bank(stream_count=stream_count)
    search_builder = phase5d_a_agent_builder(search_key)
    partner_builder = phase5d_a_agent_builder(partner_key)
    opponent_builder = phase5d_a_agent_builder(opponent_key)

    def build_candidate(seat: int):
        # The complete-match protocol hands the candidate builder its two seats.
        # ``arrangement`` decides which of them holds the search agent, so running
        # both arrangements rotates the search agent through both partnership
        # positions instead of fixing it to one.
        lower = seat in (0, 1)
        searches = lower if arrangement == 0 else not lower
        return search_builder(seat) if searches else partner_builder(seat)

    record = run_pair(
        stream=bank.stream(ordinal),
        comparison=comparison,
        safety_cap=safety_cap,
        ordinal=ordinal,
        build_candidate=build_candidate,
        build_opponent=opponent_builder,
    )
    return (ordinal, record.to_data())


def run_heterogeneous_match_comparison(
    *,
    search_profile_key: str,
    partner_profile_key: str = DEVELOPMENT_REFERENCE_POLICY,
    opponent_profile_key: str = DEVELOPMENT_REFERENCE_POLICY,
    pairs: int,
    safety_cap: int = DEFAULT_SAFETY_CAP,
    workers: int | None = None,
    progress=None,
) -> dict[str, object]:
    """Seat-balanced heterogeneous partnership comparison.

    The search agent is rotated through **both** partnership positions. Each
    arrangement is reported as its own comparison over the same streams, because a
    single fixed seat assignment cannot distinguish partner compatibility from a
    seat or dealer effect - and pooling the two would understate the dependence
    between them.
    """

    if type(pairs) is not int or pairs <= 0:
        raise SearchError("pair count must be a positive integer")
    bank = phase5d_a_hetero_bank(stream_count=pairs)
    results = []
    total = 2 * pairs
    done = 0
    for arrangement in (0, 1):
        comparison = MatchComparison.build(
            name=(
                f"phase5d_a_hetero_{search_profile_key}_with_"
                f"{partner_profile_key}_arrangement{arrangement}"
            ),
            candidate_profile_key=f"{search_profile_key}+{partner_profile_key}",
            opponent_profile_key=f"{opponent_profile_key}+{opponent_profile_key}",
            candidate_agent_id=phase5d_a_agent_identity(search_profile_key),
            opponent_agent_id=phase5d_a_agent_identity(opponent_profile_key),
            result_class="development",
            hypothesis=(
                f"Is a {search_profile_key} seat partnered with "
                f"{partner_profile_key} competitive against a pure "
                f"{opponent_profile_key} partnership?"
            ),
        )
        units = [
            (
                search_profile_key,
                partner_profile_key,
                opponent_profile_key,
                arrangement,
                comparison.to_data(),
                pairs,
                safety_cap,
                ordinal,
            )
            for ordinal in range(pairs)
        ]
        collected: dict[int, PairRecord] = {}
        if workers is None or workers <= 1:
            for unit in units:
                ordinal, data = _hetero_unit(unit)
                collected[ordinal] = _pair_from_data(data)
                done += 1
                if progress is not None:
                    progress(done, total)
        else:
            from concurrent.futures import ProcessPoolExecutor

            with ProcessPoolExecutor(max_workers=workers) as pool:
                for ordinal, data in pool.map(_hetero_unit, units, chunksize=1):
                    collected[ordinal] = _pair_from_data(data)
                    done += 1
                    if progress is not None:
                        progress(done, total)
        records = tuple(collected[ordinal] for ordinal in range(pairs))
        results.append(
            {
                "arrangement": arrangement,
                "arrangement_meaning": (
                    "search agent at the numerically lower candidate seat"
                    if arrangement == 0
                    else "search agent at the numerically higher candidate seat"
                ),
                "comparison_id": comparison.comparison_id,
                "name": comparison.name,
                "primary_match_inference": pair_inference(
                    records,
                    confidence_level=CONFIDENCE_LEVEL,
                    analysis_seed=PHASE5D_A_HETERO_ROOT_SEED,
                    bootstrap_replicates=BOOTSTRAP_REPLICATES,
                    sign_flip_replicates=SIGN_FLIP_REPLICATES,
                ),
                "secondary_metrics": secondary_metrics(records),
            }
        )
    return {
        "arrangements": results,
        "bank": bank.to_data(),
        "design": "heterogeneous_partnership_seat_balanced",
        "opponent_profile_key": opponent_profile_key,
        "pair_count_per_arrangement": pairs,
        "partner_profile_key": partner_profile_key,
        "safety_cap": safety_cap,
        "schema_version": "tuppi.search.phase5d_a_heterogeneous.v1",
        "search_profile_key": search_profile_key,
        "seat_balance_note": (
            "Both arrangements use the same streams, so they are not independent of "
            "each other. Each is reported separately rather than pooled."
        ),
        "sign_convention": (
            "The candidate partnership contains the search agent, so p_win above "
            "0.5 means the mixed partnership beats the pure reference partnership."
        ),
    }


def run_phase5d_a_deal_screen(
    *,
    candidate_profile_key: str,
    opponent_profile_key: str,
    deals: int,
    utility_id: UtilityId = UtilityId.MATCH_TRANSITION_V1,
    progress=None,
) -> dict[str, object]:
    """Deal-level duplicate screen on the fresh Phase 5D-A deal bank."""

    if type(deals) is not int or deals <= 0:
        raise SearchError("deal count must be a positive integer")
    bank = phase5d_a_deal_bank(stream_count=max(deals, 1))
    build_candidate = phase5d_a_agent_builder(candidate_profile_key)
    build_opponent = phase5d_a_agent_builder(opponent_profile_key)
    score = MatchScore()
    results: list[DealPairResult] = []
    for ordinal in range(deals):
        stream = bank.stream(ordinal)
        stream_deal = stream.deal(0)
        even_utility, even_win, even_actions = _play_one_deal(
            hands=stream_deal.hands,
            dealer=stream.initial_dealer,
            starting_score=score,
            candidate_seats=(0, 2),
            build_candidate=build_candidate,
            build_opponent=build_opponent,
            match_ref=f"dda-e-{ordinal:06d}",
            utility_id=utility_id,
        )
        odd_utility, odd_win, odd_actions = _play_one_deal(
            hands=stream_deal.hands,
            dealer=stream.initial_dealer,
            starting_score=score,
            candidate_seats=(1, 3),
            build_candidate=build_candidate,
            build_opponent=build_opponent,
            match_ref=f"dda-o-{ordinal:06d}",
            utility_id=utility_id,
        )
        results.append(
            DealPairResult(
                ordinal=ordinal,
                even_utility=even_utility,
                odd_utility=odd_utility,
                even_candidate_wins=even_win,
                odd_candidate_wins=odd_win,
                even_actions=even_actions,
                odd_actions=odd_actions,
            )
        )
        if progress is not None:
            progress(ordinal + 1, deals)
    values = [item.paired_value for item in results]
    mean = math.fsum(values) / len(values)
    deviation = (
        math.sqrt(math.fsum((value - mean) ** 2 for value in values) / len(values))
        if len(values) > 1
        else 0.0
    )
    return {
        "bank": bank.to_data(),
        "candidate_profile_key": candidate_profile_key,
        "deal_pairs": len(results),
        "interpretation": (
            "Deal-level screening. Phase 5A established that signed deal value is "
            "blind to match safety, so this may show that two agents differ and may "
            "never be read as a match-strength claim."
        ),
        "mean_paired_utility": round(mean, 6),
        "opponent_profile_key": opponent_profile_key,
        "pairs_candidate_ahead": sum(1 for value in values if value > 0),
        "pairs_candidate_behind": sum(1 for value in values if value < 0),
        "pairs_tied": sum(1 for value in values if value == 0),
        "schema_version": "tuppi.search.phase5d_a_deal_screen.v1",
        "standard_error_paired_utility": round(
            deviation / math.sqrt(len(values)) if len(values) > 1 else 0.0, 6
        ),
        "utility_id": utility_id.value,
    }
