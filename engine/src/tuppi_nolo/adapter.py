"""N08: an offline research policy that plays the certified NOLO choices.

This is the first thing in the programme that *acts*. Everything before it
measured; this executes, and the discipline that matters is that it must never
claim a guarantee it is not actually delivering.

## What it is

A subclass of the v2 policy, living in the research layer. Showing, RAMI,
out-of-range NOLO and every unresolved decision delegate to v2 unchanged, so the
adapter can only differ where an exact, verified answer exists. Its preference is
expressed the way every Phase 4 policy expresses one: a named score component on
**every** legal action, with the inherited v2 ranking surviving underneath as the
tie-break. The chosen action is the lexicographic maximum, so ``choose_action``,
``decide`` and ``explain`` cannot disagree — they all read the same ranking.

The component's value is N05's worst-case score-state proxy for that action, not
its trick count. That matters: two actions differing by a trick that prices to
the same score state get the same value, the tie falls through to v2, and the
baseline survives. The score-tie cases from N05 are therefore preserved without a
special case anywhere in this file.

## Why it has memory, and what is in it

A security value is only attained if the whole certified continuation is played.
Winning a trick differently and then reverting to the baseline's next card is not
a weaker version of the guarantee; it is no guarantee at all. So when a search
resolves and its certificate verifies, the **complete** plan is retained, indexed
by information key, and later own decisions replay it without another search.
Completeness is not assumed: N03 rejects a plan that fails to name an action at
any reachable own node, so a verified certificate is exactly the reservation this
needs before the first card is committed.

This makes the adapter a **finite-memory research strategy**, not a stateless
Phase 4 policy, and it is described as one. Its memory holds only its own earlier
observations and the plans it verified from them. No hidden hand, no real deal,
no partner's private state ever enters it. Plans are cleared at a new deal, and a
history that does not match a retained plan drops the plan and the guarantee with
it, loudly, rather than substituting an unverified continuation.

Each seat runs its own instance and reads only its own observation. The control
model quantifies over arbitrary partner actions, which is precisely what makes
that legal: no seat needs to know what its partner intends, so there is no shared
team controller here and must never be one.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from tuppi_agents.action_scoring import CandidateEvaluation, ScoredActions
from tuppi_agents.features import PublicFeatures
from tuppi_agents.void_lead import VoidSeekingPartnerAwarePolicy
from tuppi_engine import EnginePhase, PlayCardAction, PlayerObservation
from tuppi_rules import Contract, card_to_code

from .certificates import CheckStatus, all_action_bounds
from .outcomes import ClaimLabel, classify_claim, outcome_for_total
from .security import SecurityStatus, solve_security
from .support import SupportBudget, semantic_observation_key

ADAPTER_SCHEMA_VERSION = "tuppi.nolo.adapter.v1"

#: Distinct from any registered profile: a consumer must be able to tell that
#: this research policy, and not v2 itself, produced a decision.
ADAPTER_PROFILE_KEY = "nolo_security_certified_v1"

#: Prepended when a completed, verified search ranked every legal action.
SECURITY_COMPONENT = "nolo_security_proxy"

#: Prepended when a retained certified plan names the action for this key.
PLAN_COMPONENT = "nolo_certified_plan"

REASON_UNIVERSAL = "nolo_certified_universal"
REASON_SECURITY_ONLY = "nolo_certified_security_only"
REASON_UNCLASSIFIED = "nolo_certified_unclassified"
REASON_BASELINE_KEPT = "nolo_certified_baseline_kept"
REASON_PLAN_CONTINUATION = "nolo_certified_plan_continuation"

#: Why a decision was left to v2. Every one of these means the adapter is making
#: no claim at all about that decision.
FALLBACK_OUT_OF_CONTRACT = "nolo_fallback_not_nolo_play"
FALLBACK_OUT_OF_RANGE = "nolo_fallback_out_of_range"
FALLBACK_UNRESOLVED = "nolo_fallback_search_unresolved"
FALLBACK_UNVERIFIED = "nolo_fallback_certificate_unverified"
FALLBACK_PLAN_MISMATCH = "nolo_fallback_plan_history_mismatch"

_CLAIM_REASONS = {
    ClaimLabel.UNIVERSAL: REASON_UNIVERSAL,
    ClaimLabel.SECURITY_ONLY: REASON_SECURITY_ONLY,
    ClaimLabel.TIE: REASON_BASELINE_KEPT,
    ClaimLabel.UNCLASSIFIED: REASON_UNCLASSIFIED,
}


class AdapterInvariantError(RuntimeError):
    """FAILED_CHECK: the played action and the certified plan disagree."""


@dataclass(frozen=True, slots=True)
class CertifiedPlan:
    """A verified continuation, held only for the deal and seat that made it."""

    deal_ref: str
    seat: int
    root_key: str
    root_action: PlayCardAction
    table: dict
    certificate: object
    claimed_bound: int
    world_count: int

    def action_for(self, information_key: str):
        """The action this plan commits to at *information_key*, if it has one.

        The root is answered from ``root_action``: N03 keeps the root out of the
        plan table, and without this a repeated call at the root would look like
        a foreign history and drop the plan.
        """

        if information_key == self.root_key:
            return self.root_action
        return self.table.get(information_key)


class SecurityCertifiedNoloPolicy(VoidSeekingPartnerAwarePolicy):
    """v2, corrected only where an exact verified answer says to correct it.

    Construct one per seat. The instance is stateful by design — see the module
    docstring — and its state is a function of the observations it has been
    shown, so two instances given the same observed history decide identically.
    """

    def __init__(self, *, agent_id: str, profile, budget: SupportBudget | None = None) -> None:
        super().__init__(agent_id=agent_id, profile=profile)
        self._budget = budget or SupportBudget()
        self._deal_ref: str | None = None
        self._plan: CertifiedPlan | None = None
        # Memoised by information key so repeated decide/explain calls neither
        # repeat a costly search nor consume anything.
        self._searches: dict = {}
        # One information key is one decision, so a repeated decide/explain must
        # return the ranking already produced rather than re-derive it.
        self._decisions: dict = {}
        self._reports: dict = {}

    # ------------------------------------------------------------- inspection

    @property
    def budget(self) -> SupportBudget:
        return self._budget

    @property
    def plan(self) -> CertifiedPlan | None:
        return self._plan

    def security_report(self, observation: PlayerObservation) -> dict:
        """Policy-safe account of what the adapter did at this observation.

        Contains no hand, world or private path — only the public key, the
        status, the claim and the counters.
        """

        return dict(self._reports.get(semantic_observation_key(observation), {}))

    def reset(self) -> None:
        """Forget every plan and search. Called automatically at a new deal."""

        self._deal_ref = None
        self._plan = None
        self._searches.clear()
        self._decisions.clear()
        self._reports.clear()

    # ------------------------------------------------------------- the policy

    def score_play_actions(
        self, observation: PlayerObservation, features: PublicFeatures
    ) -> ScoredActions:
        if observation.deal_ref != self._deal_ref:
            self.reset()
            self._deal_ref = observation.deal_ref
        key = semantic_observation_key(observation)
        settled = self._decisions.get(key)
        if settled is not None:
            return settled

        baseline = super().score_play_actions(observation, features)
        if (
            observation.phase is not EnginePhase.TRICK_PLAY
            or observation.contract is not Contract.NOLO
        ):
            return self._record(key, baseline, FALLBACK_OUT_OF_CONTRACT)

        replay = self._replay(observation, key, baseline)
        if replay is not None:
            return replay

        remaining = 13 - len(observation.completed_tricks)
        if not 1 <= remaining <= self._budget.max_remaining_tricks:
            return self._record(key, baseline, FALLBACK_OUT_OF_RANGE)
        if len(observation.legal_actions) < 2:
            # A forced play needs no ranking and no guarantee to justify it.
            return self._record(key, baseline, FALLBACK_OUT_OF_RANGE)

        result = self._search(observation, key)
        if result.status is not SecurityStatus.EXACT_COMPLETE:
            return self._record(key, baseline, FALLBACK_UNRESOLVED,
                                status=result.status.value, reason=result.reason)
        if result.verification is None or result.verification.status is not CheckStatus.EXACT_COMPLETE:
            # An unverified certificate is not a certificate. Nothing is claimed.
            return self._record(key, baseline, FALLBACK_UNVERIFIED,
                                status=result.status.value,
                                verifier=None if result.verification is None
                                else result.verification.status.value)
        return self._ranked_by_security(observation, key, baseline, result)

    # ------------------------------------------------------------- internals

    def _search(self, observation: PlayerObservation, key: str):
        """Solve once per information key; a repeated call must be free.

        The observation is the only input. ``solve_security`` refuses anything
        that is not a ``PlayerObservation``, so no private state can reach it
        even by mistake.
        """

        if key not in self._searches:
            self._searches[key] = solve_security(
                observation, self._budget, verification_budget=self._budget
            )
        return self._searches[key]

    def _replay(self, observation: PlayerObservation, key: str, baseline: ScoredActions):
        """Execute the retained plan, or drop it if this history is not its own."""

        plan = self._plan
        if plan is None:
            return None
        if plan.deal_ref != observation.deal_ref or plan.seat != observation.observing_seat:
            self._plan = None
            return self._record(key, baseline, FALLBACK_PLAN_MISMATCH)
        action = plan.action_for(key)
        if action is None:
            # The plan covers every own node its root can reach, so a key it does
            # not name means this is not that continuation. Drop the plan rather
            # than quietly play an uncertified card under its guarantee.
            self._plan = None
            return self._record(key, baseline, FALLBACK_PLAN_MISMATCH)
        if action not in observation.legal_actions:
            raise AdapterInvariantError(
                "the retained plan names an action that is not legal here"
            )
        weights = {
            candidate.action_order_index: 1.0 if candidate.action == action else 0.0
            for candidate in baseline.candidates
        }
        scored = self._prepend(baseline, PLAN_COMPONENT, weights, REASON_PLAN_CONTINUATION)
        if scored.action != action:  # pragma: no cover - the weights force it
            raise AdapterInvariantError("plan replay did not select the planned action")
        return self._record(key, scored, REASON_PLAN_CONTINUATION,
                            planned=card_to_code(action.card),
                            plan_root=plan.root_key, claimed_bound=plan.claimed_bound)

    def _ranked_by_security(self, observation, key, baseline, result) -> ScoredActions:
        """Rank every legal action by its verified worst-case score proxy."""

        seat = observation.observing_seat
        proxies = {
            value.action: float(
                outcome_for_total(
                    value.security_value, seat=seat, score_before=observation.match_score
                ).proxy
            )
            for value in result.root_values
        }
        missing = [c for c in baseline.candidates if c.action not in proxies]
        if missing:  # pragma: no cover - the search ranks every legal play
            raise AdapterInvariantError("the search did not value every legal action")
        weights = {
            candidate.action_order_index: proxies[candidate.action]
            for candidate in baseline.candidates
        }
        scored = self._prepend(baseline, SECURITY_COMPONENT, weights, REASON_BASELINE_KEPT)
        chosen = scored.action

        label, comparison = self._classify(observation, result, baseline.action, chosen)
        # Re-score with the settled reason so the explanation names the claim.
        scored = self._prepend(baseline, SECURITY_COMPONENT, weights, _CLAIM_REASONS[label])
        if scored.action != chosen:  # pragma: no cover - one rule decides both
            raise AdapterInvariantError("the security ranking is not deterministic")

        corrected = chosen != baseline.action
        certified = chosen == result.selected_action
        # The plan is retained exactly where a correction has to be honoured. An
        # unchanged action corrects nothing, so it needs no future restriction
        # and v2 keeps driving; a score-tied action outside the certified plan is
        # played on the baseline's authority and claims nothing.
        if corrected and certified:
            self._plan = CertifiedPlan(
                deal_ref=observation.deal_ref,
                seat=seat,
                root_key=key,
                root_action=chosen,
                table={entry.information_key: entry.action for entry in result.plan},
                certificate=result.certificate,
                claimed_bound=result.certificate.claimed_terminal_bound,
                world_count=result.world_count,
            )
        return self._record(
            key, scored, _CLAIM_REASONS[label],
            status=result.status.value,
            verifier=result.verification.status.value,
            baseline_action=card_to_code(baseline.action.card),
            chosen_action=card_to_code(chosen.card),
            corrected=corrected,
            certified=certified,
            claim=label.value,
            claim_reason=comparison,
            claimed_bound=result.certificate.claimed_terminal_bound,
            plan_size=len(result.plan) if (corrected and certified) else 0,
            world_count=result.world_count,
            search_engine_transitions=result.search_engine_transitions,
            verification_engine_transitions=result.verification_engine_transitions,
            proxies={card_to_code(a.card): v for a, v in proxies.items()},
        )

    def _classify(self, observation, result, baseline_action, chosen):
        """Label a correction against the baseline it replaces.

        Only a correction is compared: an unchanged action replaces nothing, so
        there is nothing to label and no reason to pay for an extra walk.
        """

        if chosen == baseline_action:
            return ClaimLabel.TIE, "the baseline is already a security maximum"
        if chosen != result.selected_action:
            # Same worst-case score state, different trick count, and no plan was
            # certified for this action. It is played on the baseline's ranking
            # and carries no guarantee, which is what the label has to say.
            return (
                ClaimLabel.UNCLASSIFIED,
                "a score-tied action outside the certified plan; nothing is claimed",
            )
        candidate_totals = sorted(result.verification.terminal_totals)
        bounds = all_action_bounds(observation, baseline_action, self._budget)
        if bounds.status is not CheckStatus.EXACT_COMPLETE:
            return ClaimLabel.UNCLASSIFIED, f"baseline comparator unresolved: {bounds.reason}"
        baseline_totals = sorted(bounds.terminal_totals)
        assessment = classify_claim(
            seat=observation.observing_seat,
            score_before=observation.match_score,
            candidate_totals=candidate_totals,
            baseline_totals=baseline_totals,
            candidate_upper_bound=result.certificate.claimed_terminal_bound,
            baseline_lower_bound=min(baseline_totals),
        )
        return assessment.label, assessment.reason

    @staticmethod
    def _prepend(scored: ScoredActions, component: str, weights: dict, reason: str):
        """Add one named component above every inherited one, and re-select.

        No catalogue rule and no validation provenance is introduced: the rule
        ids are the inherited ones, exactly as ``void_lead`` does it, because a
        Phase 4 catalogue entry carries provenance tied to the frozen profiles.
        """

        ordered = sorted(
            scored.candidates,
            key=lambda c: ((weights[c.action_order_index],)
                           + tuple(float(v) for v in c.score_vector), -c.action_order_index),
            reverse=True,
        )
        chosen = ordered[0].action_order_index
        candidates = tuple(
            CandidateEvaluation(
                action=candidate.action,
                action_order_index=candidate.action_order_index,
                component_names=(component,) + candidate.component_names,
                score_vector=(weights[candidate.action_order_index],)
                + candidate.score_vector,
                rule_ids=candidate.rule_ids,
                reason_codes=(
                    (reason,) if candidate.action_order_index == chosen else ()
                )
                + candidate.reason_codes,
            )
            for candidate in scored.candidates
        )
        return ScoredActions(candidates=candidates, selected_index=chosen)

    def _record(self, key: str, scored: ScoredActions, outcome: str, **detail):
        self._decisions[key] = scored
        self._reports[key] = {
            "schema_version": ADAPTER_SCHEMA_VERSION,
            "information_key": key,
            "outcome": outcome,
            "selected_action": card_to_code(scored.action.card)
            if isinstance(scored.action, PlayCardAction) else None,
            **detail,
        }
        return scored


def construct_security_certified_agent(
    seat: int, *, budget: SupportBudget | None = None
) -> SecurityCertifiedNoloPolicy:
    """One research policy for *seat*, scored through the same v2 profile.

    Nothing here registers a profile, renames a bot or touches a frozen digest.
    This constructs an offline research object and nothing else.
    """

    from tuppi_agents.factory import profile_of
    from tuppi_agents.registry import phase4_specifications_by_profile_key
    from tuppi_agents.void_lead import BASE_PROFILE_KEY

    if type(seat) is not int or seat not in range(4):
        raise ValueError("seat must be an integer in 0..3")
    specification = phase4_specifications_by_profile_key()[BASE_PROFILE_KEY]
    return SecurityCertifiedNoloPolicy(
        agent_id=f"{ADAPTER_PROFILE_KEY}:{specification.agent_id}",
        profile=profile_of(specification),
        budget=budget,
    )


def security_certified_agents(budget: SupportBudget | None = None) -> tuple:
    """Four independent seats. Each reads only its own observation and plan."""

    return tuple(construct_security_certified_agent(seat, budget=budget) for seat in range(4))
