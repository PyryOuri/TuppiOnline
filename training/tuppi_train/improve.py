"""Policy improvement from counterfactual labels: teacher, composite, gain.

The maths is that of ai/tuppi_ai/selfplay.py (its `dense`, `_adv_terms`, the
level + advantage loss, the held-out one-step gain and the composite
argmax_a [Q(obs, a) + margin * 1(a = pi(obs))]); tests/test_improve.py checks
the functions here against that module on the same data. What is added:

- any device, optional half precision and compilation;
- separate margins for showing (bidding) and card play, and a composite that
  may be restricted to decisions with more than `min_tricks_left` tricks to go;
- gains on clean states only (no exploration move before them), and scored on
  another label kind than the teacher was trained on;
- `Composite`, a chooser that plays the composite directly in lockstep games,
  so a teacher can be judged by play without distilling it first;
- every greedy choice is made on float32 values with ties to the lowest action
  id, as the C code breaks them, whatever the forward precision was.

This module is the shared core. The verdict run (verdict.py) uses it for one
round from a fixed network; the improvement loop builds on the same functions.
"""

from __future__ import annotations

import time

import numpy as np
import torch

from . import device, labels, lockstep, tn
from tuppi_ai import model as qmodel
from tuppi_ai import native
from tuppi_ai.selfplay import SCALE, Learner as _SP, dense
from tuppi_ai.value import _unpack

A = native.NUM_ACTIONS
lib = tn.lib
_adv_terms = _SP._adv_terms


greedy = lockstep.greedy


def forward(net, x, amp=None) -> torch.Tensor:
    """net(x) in float32, computed under autocast if `amp` is a dtype."""
    if amp is None:
        return net(x)
    with torch.autocast(x.device.type, dtype=amp):
        return net(x).float()


def margins_for(show: torch.Tensor, margin_show: float, margin_play: float) -> torch.Tensor:
    """Per-row margin in label units (equity x SCALE): `show` marks showing decisions."""
    return torch.where(show, margin_show * SCALE, margin_play * SCALE)


def composite_choice(q: torch.Tensor, pi: torch.Tensor, legal: torch.Tensor, margin: torch.Tensor,
                     keep: torch.Tensor | None = None) -> tuple[torch.Tensor, torch.Tensor]:
    """(new, old): old = the policy's greedy action, new = argmax_a [q + margin * 1(a = old)] over the
    legal actions; rows where `keep` is set stay with old."""
    old = greedy(pi.float().masked_fill(~legal, float("-inf")))
    boosted = q.float().masked_fill(~legal, float("-inf")) + margin[:, None] * torch.nn.functional.one_hot(old, A)
    new = greedy(boosted)
    if keep is not None:
        new = torch.where(keep, old, new)
    return new, old


def tail_rows(cls: torch.Tensor, min_tricks_left: int) -> torch.Tensor:
    """Card-play rows with at most `min_tricks_left` tricks to go (cls: tc_record_class)."""
    trick = (cls.long() - 1) % 13
    return (cls > 0) & (13 - trick <= min_tricks_left)


# --------------------------------------------------------------------- data
LABELS = ("q", "q0", "q6")   # label columns: selfplay.py's own, own-play, solver tail


def to_device(data: dict, dev) -> dict:
    """Label rows on the device: packed `feat`, `ids`, every label column present (LABELS),
    weights `w`, position class `cls` and `clean` (no exploration move before the state)."""
    t = lambda a: torch.from_numpy(np.ascontiguousarray(a)).to(dev)  # noqa: E731
    out = {"feat": t(data["feat"]), "ids": t(data["ids"]), "w": t(data["w"]), "cls": t(data["cls"]),
           "clean": t(np.asarray(data["explored"]) == 0)}
    for key in LABELS:
        if key in data:
            out[key] = t(data[key])
    return out


def take(D: dict, rows) -> dict:
    return {k: v[rows] for k, v in D.items()}


def _batch(D: dict, idx: torch.Tensor, dim: int, label: str = "q"):
    mask, tgt = dense(D["ids"][idx], D[label][idx])
    return _unpack(D["feat"][idx], dim), mask, tgt, D["w"][idx].float()


def importance_weights(cls: np.ndarray, mult: np.ndarray) -> np.ndarray:
    """1 / recording multiplier of each state's class, normalised to mean 1 (selfplay.py)."""
    w = 1.0 / mult[cls]
    return (w / w.mean()).astype(np.float16)


# ------------------------------------------------------------------ teacher
def adv_r2(net, H: dict, dim: int, amp=None, label: str = "q") -> float:
    """Share of the held-out centred-advantage variance the net explains (importance-weighted)."""
    was = net.training
    net.eval()
    num = den = 0.0
    with torch.no_grad():
        for i in range(0, len(H["feat"]), 65536):
            sl = torch.arange(i, min(i + 65536, len(H["feat"])), device=H["feat"].device)
            x, mask, tgt, w = _batch(H, sl, dim, label)
            mf, pc, tc = _adv_terms(forward(net, x, amp), mask, tgt, w)
            num += float((((pc - tc) ** 2) * mf).sum())
            den += float(((tc ** 2) * mf).sum())
    net.train(was)
    return 1.0 - num / max(den, 1e-12)


def fit_teacher(net, D: dict, H: dict, steps: int = 2000, batch: int = 16384, lr: float = 1e-3, wd: float = 1e-5,
                adv_weight: float = 4.0, amp=None, compile_net: bool = False, check_every: int = 200,
                patience: int = 0, opt=None, label: str = "q") -> dict:
    """Trains `net` on D (level MSE + adv_weight x centred-advantage MSE, importance-weighted) and
    leaves it at the weights with the best held-out advantage R^2, checked every `check_every`
    steps (selfplay.py `train_q`). patience > 0 stops after that many checks without a new best."""
    dev = D["feat"].device
    dim = native.feature_dim(net.encoder)
    n = len(D["feat"])
    net.train()
    opt = opt or torch.optim.AdamW(net.parameters(), lr=lr, weight_decay=wd, fused=dev.type in ("cuda", "mps"))
    scaler = torch.amp.GradScaler(dev.type, enabled=amp is torch.float16)
    fwd = torch.compile(net) if compile_net else net
    best = (adv_r2(net, H, dim, amp, label), 0, {k: v.detach().clone() for k, v in net.state_dict().items()})
    history, losses, stale, t0 = [[0, best[0]]], [], 0, time.perf_counter()
    for step in range(steps):
        idx = torch.randint(0, n, (batch,), device=dev)
        x, mask, tgt, w = _batch(D, idx, dim, label)
        pred = forward(fwd, x, amp)
        mf, pc, tc = _adv_terms(pred, mask, tgt, w)
        level = (((pred - tgt) ** 2) * mf).sum() / mf.sum()
        adv = (((pc - tc) ** 2) * mf).sum() / mf.sum()
        loss = level + adv_weight * adv
        opt.zero_grad(set_to_none=True)
        if scaler.is_enabled():
            scaler.scale(loss).backward()
            scaler.step(opt)
            scaler.update()
        else:
            loss.backward()
            opt.step()
        if step % 200 == 0:
            losses.append(float(adv.detach()))
        if (step + 1) % check_every == 0:
            r2 = adv_r2(net, H, dim, amp, label)
            history.append([step + 1, r2])
            if r2 > best[0]:
                best, stale = (r2, step + 1, {k: v.detach().clone() for k, v in net.state_dict().items()}), 0
            else:
                stale += 1
                if patience and stale >= patience:
                    break
    net.load_state_dict(best[2])
    return {"adv_r2": best[0], "best_step": best[1], "steps": history[-1][0], "history": history,
            "adv_mse": float(np.mean(losses[-3:])) / SCALE ** 2 if losses else None,
            "seconds": round(time.perf_counter() - t0, 1)}


# --------------------------------------------------------------------- gain
def heldout_gain(policy, teacher, H: dict, margin_show: float, margin_play: float, score: str = "q",
                 clean_only: bool = False, min_tricks_left: int = 0, amp=None) -> dict:
    """One-step gain of the composite on held-out states: the importance-weighted mean over states
    of label[composite action] - label[policy action], in equity (selfplay.py `heldout_gain`).
    The labels are continuations by the policy, so this estimates the effect of changing only this
    decision. score: the label column of H to judge on (the teacher's own kind, or another)."""
    dev = H["feat"].device
    dim = native.feature_dim(policy.encoder)
    was = (policy.training, teacher.training)
    policy.eval(), teacher.eval()
    gains, ws, changed, show_n, rami_old, rami_new, rows = [], [], 0, 0, 0, 0, 0
    with torch.no_grad():
        for i in range(0, len(H["feat"]), 65536):
            sl = torch.arange(i, min(i + 65536, len(H["feat"])), device=dev)
            if clean_only:
                sl = sl[H["clean"][sl]]
                if not len(sl):
                    continue
            x, m, tgt, w = _batch(H, sl, dim, score)
            cls = H["cls"][sl]
            show = cls == 0
            keep = tail_rows(cls, min_tricks_left) if min_tricks_left > 0 else None
            new, old = composite_choice(forward(teacher, x, amp), forward(policy, x, amp), m,
                                        margins_for(show, margin_show, margin_play), keep)
            r = torch.arange(len(sl), device=dev)
            gains.append(((tgt[r, new] - tgt[r, old]) / SCALE).cpu().numpy())
            ws.append(w.cpu().numpy())
            changed += int((new != old).sum())
            show_n += int(show.sum())
            rami_old += int((show & (old >= 104)).sum())
            rami_new += int((show & (new >= 104)).sum())
            rows += len(sl)
    policy.train(was[0]), teacher.train(was[1])
    g, w = np.concatenate(gains).astype(np.float64), np.concatenate(ws).astype(np.float64)
    mean = float((g * w).sum() / w.sum())
    se = float(np.sqrt(((w * (g - mean)) ** 2).sum()) / w.sum())
    return {"gain": mean, "se": se, "z": mean / se if se > 0 else 0.0, "changed": changed / max(rows, 1),
            "states": rows, "rami_old": rami_old / max(show_n, 1), "rami_new": rami_new / max(show_n, 1)}


# ------------------------------------------------------------------ chooser
class Composite:
    """Plays argmax_a [Q_teacher + margin * 1(a = policy's action)] in lockstep games.

    `env` is the environment the chooser is used on (for the position class of each row: showing
    or card play, and the trick). min_tricks_left > 0: in card play with at most that many tricks
    to go the policy's own action is played."""

    def __init__(self, policy, teacher, dev, env: "native.Env", margin_show: float, margin_play: float,
                 min_tricks_left: int = 0, amp=None, chunk: int = 65536):
        self.policy, self.teacher, self.dev, self.env = policy, teacher, torch.device(dev), env
        self.margin_show, self.margin_play, self.min_left = margin_show, margin_play, min_tricks_left
        self.amp, self.chunk = amp, chunk
        self.dim = native.feature_dim(policy.encoder)
        self.changed = self.rows = 0

    def __call__(self, feat, mask, idx, team):
        k = len(idx)
        cls_np = np.zeros(k, np.int8)
        idx32 = np.ascontiguousarray(idx, np.int32)
        lib.tc_ls_classes(self.env._h, idx32.ctypes.data, k, cls_np.ctypes.data, None)
        out = np.zeros(k, np.uint8)
        with torch.no_grad():
            for i in range(0, k, self.chunk):
                sl = slice(i, i + self.chunk)
                x = _unpack(torch.from_numpy(np.ascontiguousarray(feat[sl])).to(self.dev), self.dim)
                legal = _unpack(torch.from_numpy(np.ascontiguousarray(mask[sl])).to(self.dev), A).bool()
                cls = torch.from_numpy(cls_np[sl]).to(self.dev)
                keep = tail_rows(cls, self.min_left) if self.min_left > 0 else None
                new, old = composite_choice(forward(self.teacher, x, self.amp), forward(self.policy, x, self.amp),
                                            legal, margins_for(cls == 0, self.margin_show, self.margin_play), keep)
                self.changed += int((new != old).sum())
                out[sl] = new.to(torch.uint8).cpu().numpy()
        self.rows += k
        return out, None


def new_teacher(width: int, blocks: int, encoder: int, dev, warm_from=None) -> qmodel.QNet:
    """A teacher Q net: a copy of `warm_from` (same shape) or a new net, with a zero value head
    either way (selfplay.py)."""
    if warm_from is not None:
        net = qmodel.QNet(**warm_from.config)
        net.load_state_dict({k: v.detach().cpu().clone() for k, v in warm_from.state_dict().items()})
    else:
        net = qmodel.QNet(width, blocks, encoder)
    with torch.no_grad():
        net.out.weight.zero_()
        net.out.bias.zero_()
    return net.to(dev).train()
