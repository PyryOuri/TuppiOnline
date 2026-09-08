"""The Phase 7 decision corpus: generation, storage, and derived decisions.

A corpus of games played by the strongest available policy is not, by itself, a
new resource - imitation cannot exceed its target, and Phase 6 already measured
what a clone of the reference is worth.  What this package produces instead is a
corpus of *decisions with outcomes and counterfactuals*: paired forced branches
that measure what an action was worth, deal-level returns dense enough to learn
from, and a deliberately mixed and partly randomised generating population,
because a corpus from a deterministic policy teaches a model to invert that
policy rather than to read the game.

The charter, its measurements and its decisions are in
``docs/database/phase7_charter.md``.

Storage follows one rule: **store only what replay cannot recompute.**  A deal
is 13 bytes of packed hands plus its ordered actions and outcome - about 74
bytes on disk - and every observation, feature vector and legal action set is
derived from it through the engine's formal projection.  Serialising
observations instead would cost roughly three orders of magnitude more and
would pin the corpus to one encoder version.

Bulk output belongs on a plain local filesystem outside the repository and
outside any synced folder.  Deals carry complete hidden hands and are research
private; :mod:`tuppi_corpus.replay` is the only supported path from one to
anything a model may read.
"""

from .errors import (
    CorpusConfigurationError,
    CorpusError,
    CorpusFormatError,
    CorpusIntegrityError,
    CorpusProvenanceError,
)
from .generation import GeneratedUnit, assign_rows, generate_stream
from .manifest import RunManifest, load_manifest, pin_sources
from .packing import CARD_ENCODING, HAND_ORDER_ID, canonical_hands
from .records import DealRecord, MatchRecord
from .replay import Decision, replay_deal, verify_deal
from .shards import read_shard, shard_name, write_shard
from .strata import (
    DEFAULT_MIXTURE,
    DEFAULT_POLICY_SETS,
    SPLIT_NAMES,
    StreamPlan,
    plan_stream,
)

__all__ = [
    "CARD_ENCODING",
    "DEFAULT_MIXTURE",
    "DEFAULT_POLICY_SETS",
    "HAND_ORDER_ID",
    "SPLIT_NAMES",
    "CorpusConfigurationError",
    "CorpusError",
    "CorpusFormatError",
    "CorpusIntegrityError",
    "CorpusProvenanceError",
    "DealRecord",
    "Decision",
    "GeneratedUnit",
    "MatchRecord",
    "RunManifest",
    "StreamPlan",
    "assign_rows",
    "canonical_hands",
    "generate_stream",
    "load_manifest",
    "pin_sources",
    "plan_stream",
    "read_shard",
    "replay_deal",
    "shard_name",
    "verify_deal",
    "write_shard",
]
