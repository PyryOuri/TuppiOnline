"""Typed validation errors for the authoritative executable rules."""


class RulesError(ValueError):
    """Base class for rejected rules states and actions."""


class InvalidSeatError(RulesError):
    """A seat is not one of the four integer seats 0..3."""


class InvalidTeamError(RulesError):
    """A team value is not a :class:`tuppi_rules.Team`."""


class InvalidCardError(RulesError):
    """A card, rank, suit, or serialized card is invalid."""


class InvalidHandError(RulesError):
    """A hand is empty, contains invalid cards, or contains duplicates."""


class InvalidShowActionError(RulesError):
    """A proposed show action violates the show-card hierarchy."""


class InvalidShowingSequenceError(RulesError):
    """Showing actions are duplicated, out of order, or continue after RAMI."""


class IncompleteShowingError(InvalidShowingSequenceError):
    """A showing sequence has not yet resolved a contract."""


class IllegalPlayError(RulesError):
    """A card play is not held or violates follow-suit."""


class InvalidTrickError(RulesError):
    """A completed trick is structurally invalid."""


class InvalidDealStateError(RulesError):
    """A deal or trick-total state is incomplete or inconsistent."""


class InvalidDealScoreError(RulesError):
    """A deal score is not a result produced by the authoritative formulas."""


class InvalidMatchScoreError(RulesError):
    """A rising-score match state violates its one-sided invariant."""


class TerminalMatchError(InvalidMatchScoreError):
    """A score transition was requested after the match had already ended."""
