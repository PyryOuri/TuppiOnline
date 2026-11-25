"""Suit symmetry of the game, and a network averaged over it.

By the rules the two red suits are interchangeable and so are the two black
ones: a red card shows RAMI and a black one NOLO (tuppi_core.c: RED = suits 0
and 1, BLACK = suits 2 and 3), tricks compare ranks within the led suit and
there are no trumps. Swapping the red suits, the black suits, or both maps
every position to an equivalent one, so a perfect policy chooses the
corresponding action in all four. The trained networks do not: VRPO4's greedy
action differs in about 40% of unforced decisions when two same-coloured suits
are swapped. That inconsistency is estimation noise, and averaging the
network's logits over the four views removes much of it: measured on CPU, the
averaged VRPO4 beats plain VRPO4 by +0.0026 +/- 0.0003 per deal (8,192 base
deals), VRPO3 by +0.0020 and VRPO1 by +0.0014 over their plain selves.

`Symmetric(net)` is that averaged network as a module with the interface of a
QNet (features in, 156 logits out), so every chooser and evaluation takes it.
The views are computed from the feature row itself: a suit relabelling is a
fixed permutation of the encoder's columns (`feature_perm`) and of the action
ids (`action_perm`); tests/test_symmetry.py checks both against the engine by
re-encoding permuted full states.
"""

from __future__ import annotations

import numpy as np
import torch
from torch import nn

from . import MODELS
from tuppi_ai import model as qmodel
from tuppi_ai import native

#: new suit of each old suit, for the four colour-preserving relabellings (the first is the identity)
SUIT_PERMS = ((0, 1, 2, 3), (1, 0, 2, 3), (0, 1, 3, 2), (1, 0, 3, 2))
A = native.NUM_ACTIONS

# encoder layout (ai/native/tuppi_core.c, the F_* enum and encoder v2)
_CARD_BLOCKS_V1 = ((0, 1), (52, 4), (260, 4), (468, 4), (676, 3))   # hand; played, led, discard x4; trick x3
_F_LED_SUIT, _F_VOID, _F_SHOW, _F_SHOWN_HELD, _F_UNSEEN, _F_DIM = 832, 836, 848, 1072, 1076, 1223
_F2_TRICK_OF, _F2_WON, _F2_DIM = 1223, 1223 + 52 * 13, 1223 + 52 * 13 + 52


def card_perm(suits) -> np.ndarray:
    """card id -> card id under the suit relabelling `suits` (new suit of each old suit)."""
    return np.array([suits[c // 13] * 13 + c % 13 for c in range(52)], np.int64)


def action_perm(suits) -> np.ndarray:
    """action id -> action id: card plays 0..51, shows 52 + 52 * contract + card."""
    cp, a = card_perm(suits), np.arange(A)
    return np.where(a < 52, cp[a % 52], 52 + 52 * ((a - 52) // 52) + cp[(a - 52) % 52])


def feature_image(suits, encoder: int = 2) -> np.ndarray:
    """Column j of a position's features is column image[j] of the relabelled position's."""
    if encoder not in (1, 2):
        raise ValueError("encoder 1 or 2")
    cp = card_perm(suits)
    image = np.arange(_F2_DIM if encoder == 2 else _F_DIM)
    for start, blocks in _CARD_BLOCKS_V1:
        for b in range(blocks):
            image[start + 52 * b + np.arange(52)] = start + 52 * b + cp
    image[_F_LED_SUIT + np.arange(4)] = _F_LED_SUIT + np.asarray(suits)
    for r in range(3):
        image[_F_VOID + 4 * r + np.arange(4)] = _F_VOID + 4 * r + np.asarray(suits)
    for r in range(4):                                    # shows: 52 card columns, then 4 that do not move
        image[_F_SHOW + 56 * r + np.arange(52)] = _F_SHOW + 56 * r + cp
    image[_F_UNSEEN + np.arange(52)] = _F_UNSEEN + cp
    if encoder == 2:
        cards, tricks = np.divmod(np.arange(52 * 13), 13)
        image[_F2_TRICK_OF + np.arange(52 * 13)] = _F2_TRICK_OF + 13 * cp[cards] + tricks
        image[_F2_WON + np.arange(52)] = _F2_WON + cp
    return image


def feature_perm(suits, encoder: int = 2) -> np.ndarray:
    """src with relabelled_features = features[:, src]."""
    image = feature_image(suits, encoder)
    src = np.empty_like(image)
    src[image] = np.arange(len(image))
    return src


def permute_states(states: np.ndarray, suits) -> np.ndarray:
    """Full states (labels.STATE records) with the suits relabelled: hands, shown cards, played
    cards and the sooli exchange. Entries of the card arrays beyond their counts are unused."""
    cp, out = card_perm(suits), states.copy()
    for seat in range(4):
        hand = states["hand"][:, seat]
        new = np.zeros_like(hand)
        for s in range(4):
            new |= ((hand >> np.uint64(13 * s)) & np.uint64(0x1FFF)) << np.uint64(13 * suits[s])
        out["hand"][:, seat] = new
    for name in ("show_card", "play_card"):
        out[name] = cp[states[name].astype(np.int64) % 52].astype(states[name].dtype)
    for name in ("given", "returned"):
        v = states[name].astype(np.int64)
        out[name] = np.where(v >= 0, cp[np.clip(v, 0, 51)], v).astype(states[name].dtype)
    return out


class Symmetric(nn.Module):
    """A network averaged over the four suit views: mean over views of net(view of x), each
    mapped back to the original action ids. Logits in, logits out, so greedy play, sampling and
    every evaluation work unchanged. (For a greedy choice, averaging logits and averaging
    log-probabilities over the legal actions are the same thing: each view's log-probabilities
    are its logits minus a constant.)"""

    def __init__(self, net, views=(0, 1, 2, 3)):
        super().__init__()
        self.net = net
        self.encoder = net.encoder
        self.config = {**net.config, "symmetric": list(views)}
        self.views = tuple(views)
        self.register_buffer("src", torch.from_numpy(np.stack([feature_perm(SUIT_PERMS[v], net.encoder) for v in views])),
                             persistent=False)
        self.register_buffer("back", torch.from_numpy(np.stack([action_perm(SUIT_PERMS[v]) for v in views])),
                             persistent=False)

    def view_logits(self, x: torch.Tensor) -> torch.Tensor:
        """[views, rows, 156]: each view's logits, indexed by the original action ids."""
        n, v = len(x), len(self.views)
        stacked = torch.cat([x[:, self.src[i]] for i in range(v)])
        out = self.net(stacked).float().reshape(v, n, A)
        return torch.stack([out[i][:, self.back[i]] for i in range(v)])

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.view_logits(x).mean(0)


def view_of(x: torch.Tensor, legal: torch.Tensor, target: torch.Tensor, view: int, encoder: int = 2,
            cache: dict | None = None):
    """A training row seen through suit view `view`: features, legal mask and per-action target
    (all [rows, ...]) of the relabelled position. For augmentation: the relabelled position's
    correct target is the relabelled target."""
    if view == 0:
        return x, legal, target
    key = (view, encoder, x.device)
    if cache is None or key not in cache:
        src = torch.from_numpy(feature_perm(SUIT_PERMS[view], encoder)).to(x.device)
        ap = action_perm(SUIT_PERMS[view])
        inv = np.empty_like(ap)
        inv[ap] = np.arange(A)
        entry = (src, torch.from_numpy(inv).to(x.device))
        if cache is not None:
            cache[key] = entry
    else:
        entry = cache[key]
    src, inv = entry
    return x[:, src], legal[:, inv], target[:, inv]


def load_net(name: str, dev):
    """A network by file name or path; the prefix "sym:" wraps it in `Symmetric`
    (e.g. "sym:vrpo4_final.pt")."""
    from pathlib import Path
    symmetric = name.startswith("sym:")
    name = name[4:] if symmetric else name
    path = Path(name)
    net = qmodel.load(path if path.exists() else MODELS / name, dev)
    return Symmetric(net).to(dev).eval() if symmetric else net
