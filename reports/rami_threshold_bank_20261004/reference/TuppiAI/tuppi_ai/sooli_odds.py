"""Live sooli odds for the server's training tool, from the bot's own sampler.

The server's exact odds model covers four hands in play. In a sooli deal the
sooli partner's hand is dead and the card exchange is private, so the tool
asks this sampler instead (``tuppi_server.sooli_training_analysis`` builds and
checks the envelope). Two samples of the hidden cards, for one seat's own
observation (its hand, the play, what it knows of the exchange):

* **facts only**: uniform over the layouts consistent with that observation;
* **the bot's sooli inference** (the search's own sooli belief,
  ``SOOLI_DEFAULTS``: mode 17, tilt 0.3): the soolaaja accepted sooli, so its
  hand passes the offer prefilter, and low hands are more likely (exposure
  tilt). It is used where the bot uses it: by the sooli partner choosing the
  return, and by the RAMI pair during sooli play. Measured (docs/STATUS.md,
  "Sooli"): the uniform sampler gives the banked soolaajas a median exposure
  of 33 where their real hands have 15, and the tilt lowers the soolaaja's
  survival against the bot's RAMI pair from 0.42 to 0.33.

Draws are seeded from the position, so reopening the tool on the same
position shows the same numbers.
"""

from __future__ import annotations

import ctypes as C
import zlib

from tuppi_rules.cards import card_from_index

from . import native
from .bridge import obs_from_player_observation
from .search import SOOLI_DEFAULTS

#: Worlds per sample; about 1 s for both samples together.
DEFAULT_WORLDS = 2000


class SooliOdds:
    estimator_id = "tuppi_ai_sooli_belief_v1"

    def __init__(self, worlds: int = DEFAULT_WORLDS):
        self.worlds = worlds
        self.mode = SOOLI_DEFAULTS["belief"]
        self.lam = SOOLI_DEFAULTS["lam"]

    def informed_applies(self, observation) -> bool:
        """Whether the bot's inference differs from the facts for this seat now."""

        obs = obs_from_player_observation(observation)
        soolaaja = obs.soolaaja
        if soolaaja < 0 or obs.seat == soolaaja:
            return False
        partner = (soolaaja + 2) & 3
        if obs.phase == native.PH_SOOLI_RETURN:
            return obs.seat == partner
        return obs.phase == native.PH_SOOLI_PLAY and obs.seat != partner

    def sample_layouts(self, observation, *, informed: bool) -> list[tuple[tuple, ...]]:
        """``self.worlds`` layouts: each the four seats' current holdings (Card tuples)."""

        obs = obs_from_player_observation(observation)
        rng = C.c_uint64(self._seed(observation, informed))
        mode = self.mode if informed else 0
        layouts = []
        world = native.TcDeal()
        for _ in range(self.worlds):
            if native.lib.tc_sample_world_sooli(C.byref(obs), C.byref(rng), C.byref(world), mode, self.lam) != 0:
                raise ValueError("no layout is consistent with the observation")
            layouts.append(tuple(_cards(world.hand[seat]) for seat in range(4)))
        return layouts

    def prior_probability(self, observation) -> float:
        """Share of facts-only layouts in which the soolaaja's hand passes the offer
        prefilter: how much of a leap the inference is (1.0 when nothing is ruled out)."""

        obs = obs_from_player_observation(observation)
        soolaaja = obs.soolaaja
        if soolaaja < 0:
            return 1.0
        played = 0
        for i in range(obs.n_played):
            if obs.play_seat[i] == soolaaja:
                played |= 1 << obs.play_card[i]
        rng = C.c_uint64(self._seed(observation, False))
        world = native.TcDeal()
        passed = 0
        for _ in range(self.worlds):
            if native.lib.tc_sample_world_sooli(C.byref(obs), C.byref(rng), C.byref(world), 0, 0.0) != 0:
                raise ValueError("no layout is consistent with the observation")
            hand = world.hand[soolaaja] | played
            if obs.phase == native.PH_SOOLI_RETURN and obs.known_given >= 0:
                hand |= 1 << obs.known_given
            passed += native.lib.tc_sooli_offer_prefilter(C.c_uint64(hand)) != 0
        return max(passed, 1) / self.worlds

    @staticmethod
    def _seed(observation, informed: bool) -> int:
        plays = len(getattr(observation, "sooli_tricks", ())) * 3 + len(getattr(observation, "sooli_current_trick", ()))
        key = f"{observation.deal_ref}:{observation.observing_seat}:{observation.phase.value}:{plays}:{int(informed)}"
        return zlib.crc32(key.encode()) * 2654435761 + 1


def _cards(mask: int) -> tuple:
    return tuple(card_from_index(i) for i in range(52) if mask >> i & 1)
