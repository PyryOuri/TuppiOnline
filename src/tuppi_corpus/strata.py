"""The stratum mixture, the policy population, and per-stream planning.

Diversity is a correctness requirement here, not a nice-to-have, and
``docs/database/phase7_charter.md`` §5.1 says why: ``docs/valuation/handoff.md``
§3.1 established that inference fitted on a deterministic-policy corpus measures
that policy's determinism rather than the game - the signal retained under
policy uncertainty is 1-5% for exactly the high-card observations that looked
most informative - and §3.2 gives the mechanism, that ``partner_aware_v1`` leads
its lowest card 100% of the time.  Four identical deterministic agents plus an
explicit deal also determine the entire match, so an unmixed corpus has only
deal-level diversity and no counterfactuals at all.

Three consequences are built into this module rather than left to a convention:

* the **softened** stratum breaks determinism, so lead rank and duck choice are
  not constants;
* the **forced-branch** strata produce paired arms from an identical state,
  which is where measured action *advantages* come from - the only supervised
  target in the corpus whose optimum is not the generating policy;
* the **held-out split reserves policy sets**, so a model's held-out score is
  cross-policy by construction rather than by remembering to make it so.

Splits are assigned by **stream**, never by row, which is the Phase 6
discipline: a stream's deals are correlated, so splitting rows would leak.
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import CorpusConfigurationError
from .seeds import derive_seed, uniform_below


STRATA_SCHEMA_VERSION = "tuppi.corpus.strata.v1"

SPLIT_TRAIN = 0
SPLIT_VALIDATION = 1
SPLIT_HELDOUT = 2
SPLIT_NAMES = ("train", "validation", "heldout")

TERMINATION_NATURAL = 0
TERMINATION_DEAL_CAP = 1
TERMINATION_FORCED_BRANCH = 2

BRANCH_NONE = 0
BRANCH_EPSILON = 1
BRANCH_FORCED_CONTRACT = 2
BRANCH_FORCED_PLAY = 3

#: The §5.2 mixture.  Weights are relative, not percentages, and are recorded in
#: the manifest so realised counts can be checked against what was asked for.
DEFAULT_MIXTURE: tuple[tuple[str, int], ...] = (
    ("reference_self_play", 30),
    ("population_crossplay", 20),
    ("softened_reference", 15),
    ("epsilon_branch", 15),
    ("forced_contract_pair", 10),
    ("forced_play_pair", 5),
    ("score_stratified", 5),
)

_BRANCH_BY_STRATUM = {
    "reference_self_play": BRANCH_NONE,
    "population_crossplay": BRANCH_NONE,
    "softened_reference": BRANCH_NONE,
    "epsilon_branch": BRANCH_EPSILON,
    "forced_contract_pair": BRANCH_FORCED_CONTRACT,
    "forced_play_pair": BRANCH_FORCED_PLAY,
    "score_stratified": BRANCH_NONE,
}

#: The population.  The first entry is the reference table; the last
#: ``DEFAULT_HELDOUT_POLICY_SETS`` entries are reserved for held-out streams so
#: that held-out evaluation is cross-policy (§5.1 requirement 2).
DEFAULT_POLICY_SETS: tuple[tuple[str, str, str, str], ...] = (
    ("partner_aware_lead_v2",) * 4,
    ("partner_aware_v1",) * 4,
    ("partner_aware_discard_v3",) * 4,
    ("partner_aware_lead_v2", "partner_aware_v1") * 2,
    ("partner_aware_lead_v2", "reactive_contract_v1") * 2,
    ("partner_aware_lead_v2", "public_counting_v1") * 2,
    ("partner_aware_lead_v2", "legacy_heuristic_port_v1") * 2,
    ("match_aware_v1",) * 4,
    # Reserved for held-out streams only.
    ("partner_aware_discard_v3", "partner_aware_v1") * 2,
    ("public_counting_v1",) * 4,
)
DEFAULT_HELDOUT_POLICY_SETS = 2

#: How far into a match an epsilon branch may be targeted. Matches run to a
#: median of 22 deals with a long right tail, so a horizon of 12 is reached by
#: nearly every stream while still spreading the branch over varied match
#: scores. A horizon at the safety cap would miss most streams entirely.
EPSILON_DEAL_HORIZON = 12

#: Ordinary matches start level; the score-stratified stratum starts elsewhere,
#: including the region where ``match_aware_v1`` measured *worse* than the rung
#: below it and which play from 0-0 barely reaches.
DEFAULT_SCORE_SCHEDULE: tuple[tuple[int, int], ...] = ((0, 0),)
#: In this rising-score game at most one team may hold a positive score - the
#: other has been reset - so a schedule entry with both teams above zero is not
#: merely unusual, it is unconstructible.  ``create_match`` rejects it, which is
#: how the first draft of this schedule was caught.
DEFAULT_STRATIFIED_SCORE_SCHEDULE: tuple[tuple[int, int], ...] = (
    (12, 0),
    (0, 12),
    (20, 0),
    (0, 20),
    (36, 0),
    (0, 36),
    (44, 0),
    (0, 44),
    (48, 0),
    (0, 48),
)


@dataclass(frozen=True, slots=True)
class StreamPlan:
    """Everything about one stream that is decided before any card is dealt."""

    stream_index: int
    stratum_index: int
    stratum_name: str
    policy_set_index: int
    split: int
    initial_score: tuple[int, int]
    initial_dealer: int
    deal_cap: int
    branch_kind: int
    branch_deal: int
    branch_target: int
    arms: tuple[int, ...]
    pair_id: int | None

    @property
    def is_paired(self) -> bool:
        return len(self.arms) > 1


def _weighted_choice(mixture: tuple[tuple[str, int], ...], seed: int) -> int:
    total = sum(weight for _, weight in mixture)
    draw = uniform_below(seed, total)
    cumulative = 0
    for index, (_, weight) in enumerate(mixture):
        cumulative += weight
        if draw < cumulative:
            return index
    raise CorpusConfigurationError("weighted choice fell off the mixture")


def assign_split(root_seed: str, stream_index: int, boundaries: tuple[int, int]) -> int:
    """Split membership, by stream.  Never call this per row."""

    low, high = boundaries
    draw = uniform_below(
        derive_seed(root_seed, domain="split", stream=stream_index), 1000
    )
    if draw < low:
        return SPLIT_TRAIN
    if draw < high:
        return SPLIT_VALIDATION
    return SPLIT_HELDOUT


def plan_stream(manifest, stream_index: int) -> StreamPlan:
    """Resolve one stream's stratum, policies, split, score and branch target.

    A pure function of the manifest and the stream index, which is what makes a
    shard regenerable without reference to any other shard.
    """

    if type(stream_index) is not int or stream_index < 0:
        raise CorpusConfigurationError("stream_index must be a nonnegative integer")
    root = manifest.root_seed
    stratum_index = _weighted_choice(
        manifest.mixture, derive_seed(root, domain="stratum", stream=stream_index)
    )
    stratum_name = manifest.mixture[stratum_index][0]
    branch_kind = _BRANCH_BY_STRATUM.get(stratum_name)
    if branch_kind is None:
        raise CorpusConfigurationError(f"unknown stratum {stratum_name!r}")

    split = assign_split(root, stream_index, manifest.split_boundaries)

    reserved = manifest.heldout_policy_sets
    total_sets = len(manifest.policy_sets)
    if reserved >= total_sets:
        raise CorpusConfigurationError("every policy set is reserved for held-out")
    policy_seed = derive_seed(root, domain="policy_set", stream=stream_index)
    if stratum_name in ("reference_self_play", "softened_reference", "score_stratified"):
        policy_set_index = 0
    elif stratum_name == "population_crossplay":
        if split == SPLIT_HELDOUT:
            policy_set_index = total_sets - reserved + uniform_below(policy_seed, reserved)
        else:
            policy_set_index = uniform_below(policy_seed, total_sets - reserved)
    else:
        # Branch strata measure an action against an alternative, so both arms
        # must share one continuation policy; the reference is that policy.
        policy_set_index = 0

    if stratum_name == "score_stratified":
        schedule = manifest.stratified_score_schedule
    else:
        schedule = manifest.score_schedule
    initial_score = schedule[
        uniform_below(derive_seed(root, domain="score", stream=stream_index), len(schedule))
    ]

    branch_deal = 0
    branch_target = 0
    arms: tuple[int, ...] = (0,)
    pair_id: int | None = None
    deal_cap = manifest.match_deal_cap

    if branch_kind == BRANCH_EPSILON:
        branch_seed = derive_seed(root, domain="epsilon", stream=stream_index)
        # Draw the target deal from the range a match actually reaches, not from
        # the safety cap. The T0 pilot drew from range(64) against a median match
        # length of 22 deals, so the branch never fired in 51% of its streams -
        # half the stratum silently produced ordinary on-policy play.
        branch_deal = uniform_below(branch_seed, min(EPSILON_DEAL_HORIZON, deal_cap))
        branch_target = uniform_below(branch_seed, 52, stride=1)
    elif branch_kind in (BRANCH_FORCED_CONTRACT, BRANCH_FORCED_PLAY):
        # One deal, two arms, identical prior state: the design the RAMI/NOLO
        # threshold experiment and the valuation A/B work both used, and the
        # unit their statistics are computed over.
        deal_cap = 1
        arms = (0, 1)
        pair_id = stream_index
        if branch_kind == BRANCH_FORCED_PLAY:
            branch_target = uniform_below(
                derive_seed(root, domain="forced_play", stream=stream_index), 52
            )

    return StreamPlan(
        stream_index=stream_index,
        stratum_index=stratum_index,
        stratum_name=stratum_name,
        policy_set_index=policy_set_index,
        split=split,
        initial_score=tuple(initial_score),
        initial_dealer=stream_index % 4,
        deal_cap=deal_cap,
        branch_kind=branch_kind,
        branch_deal=branch_deal,
        branch_target=branch_target,
        arms=arms,
        pair_id=pair_id,
    )


def construct_table(manifest, policy_set_index: int) -> dict[int, object]:
    """Four fresh, distinct policies - one per seat - for one policy set.

    Distinct objects per seat is an engine requirement, not a style choice: a
    shared instance would break the observation isolation the runner checks.
    """

    from tuppi_agents import phase4_specifications_by_profile_key
    from tuppi_agents.factory import construct_registered_agent
    from tuppi_agents.improved_registry import (
        IMPROVED_PROFILE_KEYS,
        improved_agent_from_specification,
        improved_specifications_by_profile_key,
    )

    if policy_set_index not in range(len(manifest.policy_sets)):
        raise CorpusConfigurationError("policy_set_index is out of range")
    keys = manifest.policy_sets[policy_set_index]
    phase4 = phase4_specifications_by_profile_key()
    improved = improved_specifications_by_profile_key()
    table: dict[int, object] = {}
    for seat, key in enumerate(keys):
        if key in IMPROVED_PROFILE_KEYS:
            table[seat] = improved_agent_from_specification(
                improved[key], profile_key=key, seat=seat
            )
        elif key in phase4:
            table[seat] = construct_registered_agent(phase4[key], seat=seat)
        else:
            raise CorpusConfigurationError(f"unknown policy key {key!r}")
    return table


def policy_identities(manifest) -> dict[str, str]:
    """Every policy key the manifest names, mapped to its content address."""

    from tuppi_agents import phase4_specifications_by_profile_key
    from tuppi_agents.improved_registry import improved_specifications_by_profile_key

    phase4 = phase4_specifications_by_profile_key()
    improved = improved_specifications_by_profile_key()
    identities: dict[str, str] = {}
    for row in manifest.policy_sets:
        for key in row:
            if key in improved:
                identities[key] = improved[key].agent_id
            elif key in phase4:
                identities[key] = phase4[key].agent_id
            else:
                raise CorpusConfigurationError(f"unknown policy key {key!r}")
    return identities


__all__ = [
    "BRANCH_EPSILON",
    "BRANCH_FORCED_CONTRACT",
    "BRANCH_FORCED_PLAY",
    "BRANCH_NONE",
    "DEFAULT_HELDOUT_POLICY_SETS",
    "DEFAULT_MIXTURE",
    "DEFAULT_POLICY_SETS",
    "DEFAULT_SCORE_SCHEDULE",
    "DEFAULT_STRATIFIED_SCORE_SCHEDULE",
    "EPSILON_DEAL_HORIZON",
    "SPLIT_HELDOUT",
    "SPLIT_NAMES",
    "SPLIT_TRAIN",
    "SPLIT_VALIDATION",
    "STRATA_SCHEMA_VERSION",
    "TERMINATION_DEAL_CAP",
    "TERMINATION_FORCED_BRANCH",
    "TERMINATION_NATURAL",
    "StreamPlan",
    "assign_split",
    "construct_table",
    "plan_stream",
    "policy_identities",
]
