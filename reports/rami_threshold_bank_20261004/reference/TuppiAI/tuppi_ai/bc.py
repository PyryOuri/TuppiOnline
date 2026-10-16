"""Behaviour cloning of the incumbent from tools/gen_bc.py shards.

The network is the same QNet; its outputs are trained as logits over legal
actions. The result is a native-speed copy of the incumbent that later serves
as a stable rollout policy for policy improvement.

    python -m tuppi_ai.bc --data runs/bc/v1 --out runs/bc_v1.pt --epochs 3
"""

from __future__ import annotations

import argparse
import math
import time
from pathlib import Path

import numpy as np
import torch

from . import model as qmodel
from .native import NUM_ACTIONS, feature_dim


def load(data: Path):
    feats, acts, masks = [], [], []
    for path in sorted(data.glob("shard_*.npz")):
        z = np.load(path)
        feats.append(z["feat"]); acts.append(z["act"]); masks.append(z["mask"])
    return np.concatenate(feats), np.concatenate(acts).astype(np.int64), np.concatenate(masks)


def batch(feat, mask, idx, dim):
    x = np.unpackbits(feat[idx], axis=1)[:, :dim]
    m = np.unpackbits(mask[idx], axis=1)[:, :NUM_ACTIONS]
    return x, m


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--data", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--epochs", type=float, default=3.0)
    p.add_argument("--batch", type=int, default=8192)
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument("--width", type=int, default=768)
    p.add_argument("--blocks", type=int, default=4)
    p.add_argument("--encoder", type=int, default=2)
    args = p.parse_args()
    device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    dim = feature_dim(args.encoder)
    feat, act, mask = load(args.data)
    n = len(act)
    rng = np.random.default_rng(0)
    perm = rng.permutation(n)
    hold = perm[: n // 50]
    train = perm[n // 50:]
    print(f"{n} decisions, {len(train)} train, {len(hold)} held out", flush=True)
    net = qmodel.QNet(args.width, args.blocks, args.encoder).to(device)
    opt = torch.optim.AdamW(net.parameters(), lr=args.lr, weight_decay=1e-5, fused=device.type == "mps")
    steps = int(args.epochs * len(train) / args.batch)
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: 0.5 * (1 + math.cos(math.pi * min(s / steps, 1.0))))
    t0 = time.time()

    def held_out():
        net.eval()
        correct = total = 0
        with torch.no_grad():
            for start in range(0, len(hold), 16384):
                idx = hold[start:start + 16384]
                x, m = batch(feat, mask, idx, dim)
                q = net(torch.from_numpy(x).to(device)).cpu().numpy()
                pick = np.where(m == 1, q, -np.inf).argmax(1)
                correct += int((pick == act[idx]).sum())
                total += len(idx)
        net.train()
        return correct / total

    for step in range(steps + 1):
        idx = train[rng.integers(0, len(train), args.batch)]
        x, m = batch(feat, mask, idx, dim)
        logits = net(torch.from_numpy(x).to(device))
        logits = logits.masked_fill(torch.from_numpy(m).to(device) == 0, -1e9)
        loss = torch.nn.functional.cross_entropy(logits, torch.from_numpy(act[idx]).to(device))
        opt.zero_grad(set_to_none=True)
        loss.backward()
        opt.step()
        sched.step()
        if step % 500 == 0:
            print(f"step {step}/{steps} loss {loss.item():.4f} held-out agreement {held_out():.4f} "
                  f"({time.time() - t0:.0f}s)", flush=True)
    qmodel.save(net, args.out, bc={"data": str(args.data), "held_out_agreement": held_out()})
    print("saved", args.out)


if __name__ == "__main__":
    main()
