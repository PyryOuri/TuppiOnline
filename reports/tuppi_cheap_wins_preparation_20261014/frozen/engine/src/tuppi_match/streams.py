"""Extensible deterministic match streams with random access by deal index.

A match stream is an *unbounded* sequence of complete deals. It is addressed by
four values and nothing else:

``protocol_version``
    The stream-generator protocol identifier. Changing it changes every deal.
``root_seed``
    The experiment-level seed shared by all streams in one bank.
``stream_index``
    Which independent stream inside that bank.
``deal_index``
    Which deal inside that stream.

The central property is **random access**: ``deal(stream, k)`` is a pure
function of those four values, so recovering deal 500 never requires generating
deals 0 to 499 and never consumes mutable RNG state. Three consequences matter
for the protocol:

* the two complementary legs of a duplicate pair read the *same* stream even
  though they consume different prefix lengths;
* a stream can be extended on demand without changing its prefix;
* execution order, worker count, and chunk size cannot alter any deal.

Stream identity is a digest over canonical semantic content. Output paths,
timestamps, machine names, and run directories are excluded by construction:
they are never inputs.

Dealer handling. A stream supplies *hands only*. The dealer of deal ``k`` comes
from the engine's own ``project_target_v1`` rotation starting at the stream's
``initial_dealer``, so a leg that lasts longer simply keeps rotating. The
convenience helper :func:`expected_dealer` reproduces that rotation for
validation and reporting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator

from tuppi_engine import ExplicitDeal
from tuppi_eval.deals import DealerPolicy, derive_seed, generate_base_deal
from tuppi_eval.serialization import content_digest
from tuppi_rules import Card, MatchScore, card_to_code, rotate_dealer

from .errors import StreamError


STREAM_PROTOCOL_VERSION = "tuppi.match.stream.v1"
STREAM_GENERATOR_ID = "tuppi.match.sha256_counter_stream_v1"
DEFAULT_CHUNK_SIZE = 16
MAXIMUM_DEAL_INDEX = 100_000


@dataclass(frozen=True, slots=True)
class StreamDeal:
    """One materialized deal of a stream, independent of any match state."""

    stream_id: str
    deal_index: int
    hands: tuple[tuple[Card, ...], ...]
    deal_content_id: str

    def explicit_deal(self, dealer: int) -> ExplicitDeal:
        """Bind the hands to the dealer the engine's rotation produced."""

        if type(dealer) is not int or dealer not in range(4):
            raise StreamError("dealer must be an integer in 0..3")
        return ExplicitDeal(dealer=dealer, hands=self.hands)


@dataclass(frozen=True, slots=True)
class MatchStream:
    """An unbounded, randomly addressable, content-identified deal stream."""

    root_seed: int | str
    stream_index: int
    initial_dealer: int
    stream_id: str
    protocol_version: str = field(default=STREAM_PROTOCOL_VERSION, init=False)
    generator_id: str = field(default=STREAM_GENERATOR_ID, init=False)

    def __post_init__(self) -> None:
        if type(self.root_seed) not in (int, str) or isinstance(self.root_seed, bool):
            raise StreamError("root_seed must be an integer or a string")
        if isinstance(self.root_seed, str) and not self.root_seed:
            raise StreamError("a string root_seed must not be empty")
        if type(self.stream_index) is not int or self.stream_index < 0:
            raise StreamError("stream_index must be a nonnegative integer")
        if type(self.initial_dealer) is not int or self.initial_dealer not in range(4):
            raise StreamError("initial_dealer must be an integer in 0..3")
        if self.stream_id != f"stream:{content_digest(self.identity_data())}":
            raise StreamError("stream_id disagrees with its canonical identity")

    @classmethod
    def build(
        cls, *, root_seed: int | str, stream_index: int, initial_dealer: int
    ) -> "MatchStream":
        identity = {
            "generator_id": STREAM_GENERATOR_ID,
            "initial_dealer": initial_dealer,
            "protocol_version": STREAM_PROTOCOL_VERSION,
            "root_seed": root_seed,
            "stream_index": stream_index,
        }
        return cls(
            root_seed=root_seed,
            stream_index=stream_index,
            initial_dealer=initial_dealer,
            stream_id=f"stream:{content_digest(identity)}",
        )

    def identity_data(self) -> dict[str, object]:
        return {
            "generator_id": self.generator_id,
            "initial_dealer": self.initial_dealer,
            "protocol_version": self.protocol_version,
            "root_seed": self.root_seed,
            "stream_index": self.stream_index,
        }

    # ------------------------------------------------------------ random access

    @property
    def deal_seed(self) -> str:
        """The per-stream seed handed to the shared shuffle implementation."""

        return derive_seed(
            self.root_seed, self.protocol_version, "stream", self.stream_index
        )

    def deal(self, deal_index: int) -> StreamDeal:
        """Return deal ``deal_index`` without generating any earlier deal."""

        if type(deal_index) is not int or deal_index < 0:
            raise StreamError("deal_index must be a nonnegative integer")
        if deal_index > MAXIMUM_DEAL_INDEX:
            raise StreamError(
                f"deal_index {deal_index} exceeds the protocol maximum "
                f"{MAXIMUM_DEAL_INDEX}"
            )
        base = generate_base_deal(
            root_seed=self.deal_seed,
            index=deal_index,
            dealer_policy=DealerPolicy.ROUND_ROBIN,
            initial_dealer=self.initial_dealer,
            starting_score=MatchScore(),
        )
        return StreamDeal(
            stream_id=self.stream_id,
            deal_index=deal_index,
            hands=base.hands,
            deal_content_id=_deal_content_id(self.stream_id, deal_index, base.hands),
        )

    def chunk(self, start: int, size: int) -> tuple[StreamDeal, ...]:
        """Materialize ``size`` consecutive deals beginning at ``start``.

        Chunking exists only to bound working memory. Because every deal is an
        independent pure function of its index, the chunk size can never change
        a semantic result, which :mod:`tests.match` asserts directly.
        """

        if type(size) is not int or size <= 0:
            raise StreamError("chunk size must be a positive integer")
        return tuple(self.deal(index) for index in range(start, start + size))

    def iter_deals(
        self, *, start: int = 0, chunk_size: int = DEFAULT_CHUNK_SIZE
    ) -> Iterator[StreamDeal]:
        """Yield deals lazily and indefinitely in deterministic chunks."""

        if type(chunk_size) is not int or chunk_size <= 0:
            raise StreamError("chunk size must be a positive integer")
        index = start
        while index <= MAXIMUM_DEAL_INDEX:
            for item in self.chunk(index, chunk_size):
                yield item
            index += chunk_size

    def expected_dealer(self, deal_index: int) -> int:
        """Reproduce the engine's dealer rotation for reporting and checks."""

        if type(deal_index) is not int or deal_index < 0:
            raise StreamError("deal_index must be a nonnegative integer")
        dealer = self.initial_dealer
        for _ in range(deal_index):
            dealer = rotate_dealer(dealer)
        return dealer

    def prefix_commitment(self, length: int) -> str:
        """Return a digest over the first ``length`` deal content identifiers.

        This is the cheap, checkable commitment stored with a bank: it proves a
        later run reads the same stream prefix without storing the deals.
        """

        if type(length) is not int or length <= 0:
            raise StreamError("commitment length must be a positive integer")
        return content_digest(
            {
                "deal_content_ids": [
                    self.deal(index).deal_content_id for index in range(length)
                ],
                "length": length,
                "schema_version": "tuppi.match.stream_commitment.v1",
                "stream_id": self.stream_id,
            }
        )


def _deal_content_id(stream_id: str, deal_index: int, hands) -> str:
    return f"streamdeal:{content_digest({
        'deal_index': deal_index,
        'hands': [[card_to_code(card) for card in hand] for hand in hands],
        'schema_version': 'tuppi.match.stream_deal.v1',
        'stream_id': stream_id,
    })}"


def stream_family(
    *, root_seed: int | str, initial_dealer: int, count: int, first_index: int = 0
) -> tuple[MatchStream, ...]:
    """Return ``count`` independent streams sharing one root seed."""

    if type(count) is not int or count <= 0:
        raise StreamError("stream count must be a positive integer")
    if type(first_index) is not int or first_index < 0:
        raise StreamError("first_index must be a nonnegative integer")
    return tuple(
        MatchStream.build(
            root_seed=root_seed,
            stream_index=index,
            initial_dealer=initial_dealer,
        )
        for index in range(first_index, first_index + count)
    )
