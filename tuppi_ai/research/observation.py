"""Legal observation transport, information keys and native record codecs (C0.02; A04, A05).

`observation_from_data` is the typed inverse of the engine's wire form
`tuppi_engine.observation_to_data` (evidence E017): every field of
`PlayerObservation` is restored, and the result re-serialises to exactly the
input. It reads nothing but the wire record, so it cannot introduce hidden
information. Two reconstructions need care, both handled explicitly:

- A shown card's `tuppi_rules.ShowAction` normally re-derives its verbal flag
  from the shower's (hidden) hand. The flag is a function of the card and the
  contract alone for any legal show (`verbal_declaration_required`), so it is
  checked against that and the frozen object is restored without a hand.
- In a sooli deal the wire's trick lists carry the three-card sooli tricks.

`information_key` identifies an actor's complete legal information plus its
permitted own memory. Protocol identifiers (match/deal refs) are excluded
because they can encode world identity; the key is never an encoder vector,
which is not injective (the encoder does not see the ruleset, for one).

The TcObs/TcDeal codecs are the supplementary native record (JSON is the
portable one); decoding validates every integer range.
"""

from __future__ import annotations

import hashlib
import json

_ENGINE_KEYS = {
    "completed_tricks", "contract", "current_actor", "current_trick", "deal_ref", "deal_terminal", "dealer",
    "declarer", "first_leader", "forehand", "legal_actions", "match_ref", "match_score", "match_terminal",
    "observing_seat", "own_hand", "partner_seat", "phase", "publicly_shown_cards", "ruleset_id",
    "schema_version", "show_actions", "team", "team_tricks", "visibility",
}
_SOOLI_KEYS = {"decisions", "exchanged", "given_card", "partner", "returned_card", "soolaaja"}
PROTOCOL_KEYS = ("match_ref", "deal_ref")


class ObservationCodecError(ValueError):
    pass


def _card(code):
    from tuppi_rules.cards import card_from_code, card_to_code

    if not isinstance(code, str):
        raise ObservationCodecError("card must be a canonical code string")
    card = card_from_code(code)
    if card_to_code(card) != code:
        raise ObservationCodecError(f"non-canonical card code {code!r}")
    return card


def _int(value, lo, hi, label):
    if type(value) is not int or not lo <= value <= hi:
        raise ObservationCodecError(f"{label} must be an integer in {lo}..{hi}")
    return value


def _opt_int(value, lo, hi, label):
    return None if value is None else _int(value, lo, hi, label)


def _restore_show(data: dict):
    """A frozen tuppi_rules.ShowAction from public fields only (no hand)."""
    from tuppi_rules import Contract, ShowAction as RulesShowAction
    from tuppi_rules.showing import card_color, contract_color, is_show_rank_eligible

    if set(data) != {"declared_contract", "seat", "shown_card", "verbal_required"}:
        raise ObservationCodecError(f"show record keys {sorted(data)}")
    card = _card(data["shown_card"])
    contract = Contract(data["declared_contract"])
    verbal = data["verbal_required"]
    if type(verbal) is not bool:
        raise ObservationCodecError("verbal_required must be a boolean")
    if verbal != (not (is_show_rank_eligible(card) and card_color(card) is contract_color(contract))):
        raise ObservationCodecError("verbal_required disagrees with the shown card and contract")
    show = object.__new__(RulesShowAction)
    object.__setattr__(show, "seat", _int(data["seat"], 0, 3, "show seat"))
    object.__setattr__(show, "shown_card", card)
    object.__setattr__(show, "declared_contract", contract)
    object.__setattr__(show, "verbal_required", verbal)
    return show


def _plays(items):
    from tuppi_rules import PlayedCard

    out = []
    for item in items:
        if set(item) != {"card", "seat"}:
            raise ObservationCodecError("played-card record keys")
        out.append(PlayedCard(seat=_int(item["seat"], 0, 3, "play seat"), card=_card(item["card"])))
    return tuple(out)


def _tricks(items, sooli: bool):
    from tuppi_engine.state import CompletedTrick, SooliTrick

    cls = SooliTrick if sooli else CompletedTrick
    out = []
    for item in items:
        if set(item) != {"leader", "plays", "trick_index", "winner"}:
            raise ObservationCodecError("trick record keys")
        out.append(cls(trick_index=item["trick_index"], leader=item["leader"], plays=_plays(item["plays"]),
                       winner=item["winner"]))
    return tuple(out)


def observation_from_data(data: dict):
    """Inverse of `tuppi_engine.observation_to_data`; strict about keys and types."""
    from tuppi_engine import PlayerObservation, action_from_data, observation_to_data
    from tuppi_engine.state import EnginePhase
    from tuppi_rules import LOCKED_BID_RULESETS, SOOLI_RULESETS, Contract, MatchScore, RulesetId, Team

    if not isinstance(data, dict):
        raise ObservationCodecError("observation record must be an object")
    ruleset = RulesetId(data.get("ruleset_id"))
    expected = set(_ENGINE_KEYS)
    if ruleset in SOOLI_RULESETS:
        expected.add("sooli")
    if ruleset in LOCKED_BID_RULESETS:
        expected.add("bids_locked")
    if set(data) != expected:
        raise ObservationCodecError(f"unexpected keys: {sorted(set(data) ^ expected)}")
    sooli = data.get("sooli") or {"decisions": [], "exchanged": False, "given_card": None, "partner": None,
                                   "returned_card": None, "soolaaja": None}
    if set(sooli) != _SOOLI_KEYS:
        raise ObservationCodecError("sooli block keys")
    exchanged = sooli["exchanged"]
    if type(exchanged) is not bool:
        raise ObservationCodecError("sooli.exchanged must be a boolean")
    tricks = _tricks(data["completed_tricks"], sooli=exchanged)
    current = _plays(data["current_trick"])
    shows = tuple(_restore_show(s) for s in data["show_actions"])
    decisions = []
    for d in sooli["decisions"]:
        if set(d) != {"play_sooli", "seat"} or type(d["play_sooli"]) is not bool:
            raise ObservationCodecError("sooli decision record")
        decisions.append((_int(d["seat"], 0, 3, "decision seat"), d["play_sooli"]))
    soolaaja = _opt_int(sooli["soolaaja"], 0, 3, "soolaaja")
    if sooli["partner"] != (None if soolaaja is None else (soolaaja + 2) % 4):
        raise ObservationCodecError("sooli partner disagrees with soolaaja")
    score = data["match_score"]
    obs = PlayerObservation(
        match_ref=data["match_ref"], deal_ref=data["deal_ref"],
        observing_seat=_int(data["observing_seat"], 0, 3, "observing_seat"),
        team=Team(data["team"]), partner_seat=_int(data["partner_seat"], 0, 3, "partner_seat"),
        dealer=_int(data["dealer"], 0, 3, "dealer"), forehand=_int(data["forehand"], 0, 3, "forehand"),
        phase=EnginePhase(data["phase"]), current_actor=_opt_int(data["current_actor"], 0, 3, "current_actor"),
        own_hand=tuple(_card(c) for c in data["own_hand"]),
        show_actions=shows, publicly_shown_cards=tuple((s.seat, s.shown_card) for s in shows),
        contract=None if data["contract"] is None else Contract(data["contract"]),
        declarer=_opt_int(data["declarer"], 0, 3, "declarer"),
        first_leader=_opt_int(data["first_leader"], 0, 3, "first_leader"),
        completed_tricks=() if exchanged else tricks, current_trick=() if exchanged else current,
        team_tricks=tuple(_int(t, 0, 13, "team_tricks") for t in data["team_tricks"]),
        match_score=MatchScore(score[0], score[1]),
        legal_actions=tuple(action_from_data(a) for a in data["legal_actions"]),
        deal_terminal=data["deal_terminal"], match_terminal=data["match_terminal"], ruleset_id=ruleset,
        sooli_decisions=tuple(decisions), soolaaja=soolaaja, sooli_exchanged=exchanged,
        sooli_given_card=None if sooli["given_card"] is None else _card(sooli["given_card"]),
        sooli_returned_card=None if sooli["returned_card"] is None else _card(sooli["returned_card"]),
        sooli_tricks=tricks if exchanged else (), sooli_current_trick=current if exchanged else (),
        bids_locked=data.get("bids_locked", 0),
    )
    if obs.schema_version != data["schema_version"] or obs.visibility != data["visibility"]:
        raise ObservationCodecError("schema_version/visibility mismatch")
    if [[s, c] for s, c in obs.publicly_shown_cards] != [[p["seat"], _card(p["card"])]
                                                           for p in data["publicly_shown_cards"]]:
        raise ObservationCodecError("publicly_shown_cards disagrees with show_actions")
    if observation_to_data(obs) != data:
        raise ObservationCodecError("reconstruction does not re-serialise to the input")
    return obs


def canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def information_key(observation, own_memory=None) -> str:
    """Key of an actor's complete legal information and permitted own memory.

    Includes the ordered own hand and legal actions, all public history,
    ruleset, phase, score and sooli/private-exchange knowledge; excludes the
    protocol refs. `own_memory` must be the actor's own permitted state (for
    example a C5 option's history), never another seat's data.
    """
    from tuppi_engine import observation_to_data

    data = observation_to_data(observation)
    for key in PROTOCOL_KEYS:
        data.pop(key)
    record = {"observation": data, "own_memory": own_memory}
    return hashlib.sha256(canonical_json(record).encode()).hexdigest()


def public_key(observation) -> str:
    """Public-only key (no own hand, no legal actions, no private exchange); separately named."""
    from tuppi_engine import observation_to_data

    data = observation_to_data(observation)
    for key in (*PROTOCOL_KEYS, "own_hand", "legal_actions", "observing_seat", "team", "partner_seat",
                "current_actor"):
        data.pop(key, None)
    if "sooli" in data:
        data["sooli"] = {k: v for k, v in data["sooli"].items() if k not in ("given_card", "returned_card")}
    return hashlib.sha256(canonical_json(data).encode()).hexdigest()


# ---------------------------------------------------------------- native codecs

_U8_ARRAYS_OBS = ("show_seat", "show_card", "show_contract", "show_verbal", "play_card", "play_seat", "score",
                  "decision_seat", "decision_accept")
_RANGES = {"seat": (0, 3), "dealer": (0, 3), "phase": (0, 6), "n_shows": (0, 4), "contract": (-1, 1),
           "declarer": (-1, 3), "first_leader": (0, 3), "n_played": (0, 52), "ruleset": (1, 3),
           "trick_size": (3, 4), "n_decisions": (0, 2), "soolaaja": (-1, 3), "known_given": (-1, 51),
           "known_returned": (-1, 51), "cur": (0, 3), "winner_team": (-1, 1), "points": (0, 255),
           "stolen": (0, 1), "given": (-1, 51), "returned": (-1, 51), "sooli_won": (0, 1)}
_ARRAY_RANGES = {"show_seat": (0, 3), "show_card": (0, 51), "show_contract": (0, 1), "show_verbal": (0, 1),
                 "play_card": (0, 51), "play_seat": (0, 3), "score": (0, 255), "decision_seat": (0, 3),
                 "decision_accept": (0, 1), "team_tricks": (0, 13)}
FULL_DECK_MASK = (1 << 52) - 1


def _struct_to_data(obj) -> dict:
    out = {}
    for name, ctype in obj._fields_:
        v = getattr(obj, name)
        out[name] = list(v) if hasattr(ctype, "_length_") else int(v)
    return out


def _struct_from_data(cls, data: dict):
    names = [n for n, _t in cls._fields_]
    if set(data) != set(names):
        raise ObservationCodecError(f"{cls.__name__} keys differ: {sorted(set(data) ^ set(names))}")
    obj = cls()
    for name, ctype in cls._fields_:
        v = data[name]
        if hasattr(ctype, "_length_"):
            if not isinstance(v, list) or len(v) != ctype._length_:
                raise ObservationCodecError(f"{name} must be a list of {ctype._length_}")
            lo, hi = _ARRAY_RANGES.get(name, (0, (1 << 64) - 1))
            for x in v:
                _int(x, lo, hi, name)
            getattr(obj, name)[:] = v
        else:
            if name == "hand":
                _int(v, 0, FULL_DECK_MASK, name)
            else:
                lo, hi = _RANGES.get(name, (-128, 255))
                _int(v, lo, hi, name)
            setattr(obj, name, v)
    return obj


def tcobs_to_data(obs) -> dict:
    return _struct_to_data(obs)


def tcobs_from_data(data: dict):
    from .. import native

    obs = _struct_from_data(native.TcObs, data)
    if obs.hand & ~FULL_DECK_MASK:
        raise ObservationCodecError("hand has bits above 52")
    return obs


def tcdeal_to_data(deal) -> dict:
    d = _struct_to_data(deal)
    d["hand"] = list(d["hand"])
    return d


def tcdeal_from_data(data: dict):
    from .. import native

    deal = _struct_from_data(native.TcDeal, data)
    if any(h & ~FULL_DECK_MASK for h in deal.hand):
        raise ObservationCodecError("hand has bits above 52")
    return deal
