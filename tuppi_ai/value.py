"""Value network for the search's rollout leaves (docs/VALUE_NET_PLAN.md).

V maps a full-information trick-boundary position (`native.encode_pi`: four
hands, tricks, contract, declarer, score, dealer, trick index, bot-side bit)
to the deal's match-equity change for the side to move. The layout mirrors
`model.QNet` with one output, so `native.Mlp` runs it inside the search.

    python -m tuppi_ai.value gen --rows 4000000 --out runs/value/vn1_train.npz
    python -m tuppi_ai.value train --data runs/value/vn1_train.npz --val runs/value/vn1_val.npz \\
        --out runs/value/vn1.pt
"""

from __future__ import annotations

import argparse
import ctypes as C
import itertools
import json
import time
from pathlib import Path

import numpy as np
import torch
from torch import nn

from . import native
from .model import ResBlock

ROOT = Path(__file__).resolve().parents[1]
VALUE_SCALE = 10.0  # trained on 10 x equity (as model.RETURN_SCALE); folded out on export


class VNet(nn.Module):
    def __init__(self, width: int = 256, blocks: int = 2, in_dim: int = native.PI_DIM):
        super().__init__()
        self.config = {"width": width, "blocks": blocks, "in_dim": in_dim, "encoder": 1, "kind": "value"}
        self.inp = nn.Linear(in_dim, width)
        self.blocks = nn.Sequential(*[ResBlock(width) for _ in range(blocks)])
        self.norm = nn.LayerNorm(width)
        self.out = nn.Linear(width, 1)

    def forward(self, x):
        h = self.blocks(torch.relu(self.inp(x.float())))
        return self.out(torch.relu(self.norm(h)))[:, 0]


def save(net: VNet, path, **extra) -> None:
    state = {k: v.detach().cpu() for k, v in net.state_dict().items()}
    torch.save({"config": net.config, "state": state, **extra}, path)


def load(path, device="cpu") -> VNet:
    blob = torch.load(path, map_location=device, weights_only=False)
    cfg = {k: blob["config"][k] for k in ("width", "blocks", "in_dim")}
    net = VNet(**cfg)
    net.load_state_dict(blob["state"])
    return net.to(device).eval()


def to_native(net: VNet) -> native.Mlp:
    """The net in native memory, returning equity (the training scale folded out)."""
    return native.Mlp(net, in_dim=net.config["in_dim"], out_dim=1, out_scale=1.0 / VALUE_SCALE)


# ------------------------------------------------------------------ symmetry
def suit_permutations() -> np.ndarray:
    """Column index maps [24, PI_DIM]: every relabelling of the suits applied to
    the four 52-card hand blocks (there are no trumps, so each is an exact
    symmetry of the position's value); other columns are fixed."""
    perms = []
    for p in itertools.permutations(range(4)):
        cols = np.arange(native.PI_DIM)
        for block in range(4):
            for s in range(4):
                for r in range(13):
                    cols[52 * block + 13 * p[s] + r] = 52 * block + 13 * s + r
        perms.append(cols)
    return np.stack(perms)


# ---------------------------------------------------------------------- data
def generate(rows: int, seed: int, games_per_call: int = 4096, ruleset: int = 3, dd_left: int = 6,
             rollout=ROOT / "models" / "rollout_clone_small.pt") -> tuple[np.ndarray, np.ndarray]:
    """VN1 rows: positions of clone self-play (the search's rollout policy, sooli
    by its heuristics, exact tail) and each deal's outcome from there."""
    from . import model as qmodel
    from .best import EQUITY
    from .equity import Equity

    net = qmodel.load(rollout, "cpu")
    mlp = native.Mlp(net)
    env = native.Env(games_per_call, seed, Equity.load(EQUITY).table, single_deal=True, encoder=net.encoder)
    env.set_sooli(0, False, False, 0.0)
    rng = C.c_uint64(seed * 0x9E3779B97F4A7C15 % 2**64 + 1)
    feats, targets, have = [], [], 0
    while have < rows:
        f, t = native.value_rollouts(env, mlp, games_per_call, ruleset, dd_left, rng, games_per_call * 14)
        feats.append(np.packbits(f, axis=1))
        targets.append(t)
        have += len(t)
    return np.concatenate(feats)[:rows], np.concatenate(targets)[:rows]


# ------------------------------------------------------------------ training
def _unpack(packed: torch.Tensor, dim: int) -> torch.Tensor:
    """uint8 [n, ceil(dim/8)] packed big-endian bits -> float [n, dim], on the device."""
    shifts = torch.arange(7, -1, -1, device=packed.device, dtype=torch.uint8)
    bits = (packed.unsqueeze(2) >> shifts) & 1
    return bits.reshape(len(packed), -1)[:, :dim].float()


def train(data: Path, val: Path, out: Path, width: int, blocks: int, steps: int, batch: int, lr: float,
          device: str, augment: bool = True, log_every: int = 1000, init: Path | None = None) -> dict:
    dev = torch.device(device)
    d, v = np.load(data), np.load(val)
    x = torch.from_numpy(d["feat"]).to(dev)
    y = torch.from_numpy(d["target"]).to(dev) * VALUE_SCALE
    xv = _unpack(torch.from_numpy(v["feat"]).to(dev), native.PI_DIM)
    yv = torch.from_numpy(v["target"]).to(dev) * VALUE_SCALE
    perms = torch.from_numpy(suit_permutations()).to(dev)
    net = load(init, dev).train() if init else VNet(width, blocks).to(dev)  # warm start (VN2 from VN1)
    opt = torch.optim.AdamW(net.parameters(), lr=lr, weight_decay=1e-5, fused=dev.type == "mps")
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=lr, total_steps=steps, pct_start=0.05)
    gen = torch.Generator(device="cpu").manual_seed(0)
    history, t0 = [], time.time()

    def val_mse():
        net.eval()
        with torch.no_grad():
            pred = torch.cat([net(xv[i:i + 65536]) for i in range(0, len(xv), 65536)])
        net.train()
        mse = float(((pred - yv) ** 2).mean()) / VALUE_SCALE ** 2
        base = float(((yv - yv.mean()) ** 2).mean()) / VALUE_SCALE ** 2
        return mse, base

    for step in range(1, steps + 1):
        idx = torch.randint(0, len(x), (batch,), generator=gen).to(dev)
        xb = _unpack(x[idx], native.PI_DIM)
        if augment:
            p = perms[torch.randint(0, 24, (1,), generator=gen).item()]
            xb = xb[:, p]
        loss = torch.nn.functional.mse_loss(net(xb), y[idx])
        opt.zero_grad(set_to_none=True)
        loss.backward()
        opt.step()
        sched.step()
        if step % log_every == 0 or step == steps:
            mse, base = val_mse()
            row = {"step": step, "train_mse": float(loss) / VALUE_SCALE ** 2, "val_mse": mse,
                   "val_r2": 1 - mse / base, "seconds": round(time.time() - t0, 1)}
            history.append(row)
            print(json.dumps(row), flush=True)
    save(net.cpu(), out, history=history, data=str(data))
    return history[-1]


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gen")
    g.add_argument("--rows", type=int, required=True)
    g.add_argument("--seed", type=int, required=True)
    g.add_argument("--out", type=Path, required=True)
    t = sub.add_parser("train")
    t.add_argument("--data", type=Path, required=True)
    t.add_argument("--val", type=Path, required=True)
    t.add_argument("--out", type=Path, required=True)
    t.add_argument("--width", type=int, default=256)
    t.add_argument("--blocks", type=int, default=2)
    t.add_argument("--steps", type=int, default=20000)
    t.add_argument("--batch", type=int, default=8192)
    t.add_argument("--lr", type=float, default=2e-3)
    t.add_argument("--device", default="mps" if torch.backends.mps.is_available() else "cpu")
    t.add_argument("--no-augment", action="store_true")
    t.add_argument("--init", type=Path, help="start from this value net (its width/blocks)")
    args = p.parse_args()
    if args.cmd == "gen":
        torch.set_num_threads(1)
        native.set_rollout_chunk(128)
        t0 = time.time()
        feat, target = generate(args.rows, args.seed)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        np.savez(args.out, feat=feat, target=target)
        print(json.dumps({"rows": len(target), "seconds": round(time.time() - t0, 1),
                          "target_mean": float(target.mean()), "target_sd": float(target.std())}))
    else:
        train(args.data, args.val, args.out, args.width, args.blocks, args.steps, args.batch, args.lr,
              args.device, not args.no_augment, init=args.init)


if __name__ == "__main__":
    main()
