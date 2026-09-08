"""A scoped mode that elides *implicit revalidation* of engine-internal state.

This exists for one reason, and it is a measured one.  Self-play generation
spends about **81%** of its time in ``match._validate_match_state``, which runs
roughly three times per action - once on the way into ``apply_match_action``,
once when the successor ``MatchState`` constructs itself, and once on the way
into ``match_observation_for`` - and each run revalidates the whole match
history, including every completed deal's event log.  Eliding those three
measured **12.4x** with byte-identical play over 11 615 checkpoints.  See
``docs/database/phase7_charter.md`` §1.1-1.3 and ``work/phase7_planning/``.

Phase 5D-C established the precedent one layer out:
``tuppi_search.fast_trick.FastTrickState`` omits event-log construction and
repeated whole-state validation inside hypothetical simulations, with the
authoritative engine kept as the differential reference.  This module does the
same thing without a second implementation of the state machine.

What it elides
--------------

Exactly four implicit revalidations of state this engine itself just produced:

* ``DealState.__post_init__``
* ``MatchState.__post_init__``
* the entry revalidation in ``apply_match_action``
* the entry revalidation in ``match_observation_for``

What it does not elide, ever
----------------------------

* **``begin_explicit_deal``** - so every deal is fully validated at its start,
  including the incoming explicit deal, which is external data.
* **``research_deal_result_from_state``** - so every deal is fully validated at
  its end.  Together with the previous point, a trusted run still validates the
  complete state at both boundaries of every deal; only the ~55 intra-deal
  revalidations are skipped.
* **``create_match``**, result construction, and serialization, all of which
  accept or emit external data.
* **the public ``validate_match_state`` and ``validate_deal_state``**.  An
  explicit request for a check is always honoured, including inside a trusted
  block.  That is what lets a generation run revalidate a sample of its own
  deals through the authoritative path while the rest of the run is trusted -
  and ``docs/database/phase7_charter.md`` treats that sampling as load-bearing
  rather than optional.

The danger, stated plainly
--------------------------

Inside this block the engine stops proving that its own successor states are
well-formed.  If a transition is wrong, a trusted run produces a plausible,
silently-wrong deal instead of raising.  Two consequences follow, and neither is
advisory:

1. A trusted generator must be gated by a **differential** test - the same
   streams played through both paths, comparing every action, score and deal
   count.  ``tests/engine/test_trusted_transitions.py`` is that gate.
2. A trusted run must revalidate a sample of its output explicitly, so a defect
   that the gate's fixed streams miss still surfaces.

This is a generation and research device.  **No policy may enter it**, and
``tests/agents/test_architecture.py`` fails if any agent module imports this
module.  It is not a performance switch for the product runtime: the private
alpha serves a human at a few actions per second, where the validation cost is
irrelevant and the guarantee is not.

Determinism is unaffected.  Validation cannot change a selected action - it
either passes or raises - which is why the elision is provably behaviour
preserving rather than merely believed to be.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator


TRUSTED_MODE_SCHEMA_VERSION = "tuppi.engine.trusted_transitions.v1"

#: A ``ContextVar`` rather than a module global so that the mode cannot leak
#: across threads or asynchronous tasks, and a nesting depth rather than a
#: boolean so that nested blocks restore correctly.
_DEPTH: ContextVar[int] = ContextVar("tuppi_engine_trusted_depth", default=0)


def is_trusted() -> bool:
    """True inside :func:`trusted_transitions`."""

    return _DEPTH.get() > 0


@contextmanager
def trusted_transitions() -> Iterator[None]:
    """Elide implicit revalidation of engine-internal state within this block.

    Re-entrant, and restored on exception.  Read this module's docstring before
    using it: inside the block the engine no longer proves its own successors
    are well-formed, and the caller takes on the differential gate and the
    revalidation sample that responsibility implies.
    """

    token = _DEPTH.set(_DEPTH.get() + 1)
    try:
        yield
    finally:
        _DEPTH.reset(token)


__all__ = [
    "TRUSTED_MODE_SCHEMA_VERSION",
    "is_trusted",
    "trusted_transitions",
]
