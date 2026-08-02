"""Typed failures for the Phase 4 observation-only baseline agents."""


class AgentsError(Exception):
    """Base class for baseline-agent failures."""


class AgentsValidationError(AgentsError, ValueError):
    """A strict immutable agent input or configuration is invalid."""


class ObservationBoundaryError(AgentsValidationError):
    """A policy received something other than a formal player observation."""


class ProfileError(AgentsValidationError):
    """A heuristic profile is unknown, malformed, or self-contradictory."""


class RuleCatalogueError(AgentsValidationError):
    """A strategy-rule catalogue entry or reference is invalid."""


class DiagnosticsError(AgentsValidationError):
    """A decision-diagnostics value is invalid or privacy-unsafe."""


class PolicyError(AgentsError):
    """A deterministic policy could not produce a legal action."""


class AgentConstructionError(AgentsValidationError):
    """A registered Phase 4 agent could not be constructed."""
