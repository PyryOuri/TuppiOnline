"""Persistent experiment metadata and one bounded control cycle.

This layer owns scheduling state, restart state and the recorded verdict. It owns
no rules, no engine, no policy, no estimator and no result bytes: the evaluation
artifacts stay exactly where :mod:`tuppi_eval` wrote them and are referenced here
by path and digest.

The distinction the ledger exists to keep is between *execution status* - did the
run finish - and *scientific verdict* - did it establish anything. A completed
cycle is not an accepted finding.
"""

from .decisions import (
    DEAL_POINTS_SCREENING_RULE,
    DecisionRule,
    decide,
)
from .errors import CycleError, LedgerError, LegalityError, ResearchError

# `findings`, `assumptions`, `proposals` and `coverage` are deliberately NOT
# imported here.
# Each is meant to be run as `python -m tuppi_research.<module>`, and an eager
# package-level import puts it in sys.modules before runpy executes it, which
# makes every invocation print a RuntimeWarning. Import them directly:
# `from tuppi_research.assumptions import register`.
from .ledger import (
    LEDGER_SCHEMA_VERSION,
    Ledger,
    ExecutionState,
    Verdict,
)

__all__ = [
    "DEAL_POINTS_SCREENING_RULE",
    "DecisionRule",
    "LEDGER_SCHEMA_VERSION",
    "CycleError",
    "decide",
    "ExecutionState",
    "Ledger",
    "LedgerError",
    "LegalityError",
    "ResearchError",
    "Verdict",
]
