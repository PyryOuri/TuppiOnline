"""Card-location belief network.

Input: one seat's observation (encoder v2). Output: for each of the 52 cards,
logits over which of the other three seats (relative 1, 2, 3) holds it. Only
cards unseen by the observer are trained or used. Trained on native self-play
positions from tools/gen_belief.py, so the belief encodes how the policies in
that data behave (a distilled search policy for one team, the incumbent clone
for the other).

    python -m tuppi_ai.belief --data runs/belief/v1 --out runs/belief_v1.pt
"""

from __future__ import annotations

import argparse
import math
import time
from pathlib import Path

import numpy as np
import torch
from torch import nn

from .model import ResBlock
from .native import feature_dim


class BeliefNet(nn.Module):
    def __init__(self, width: int = 512, blocks: int = 3, encoder: int = 2):
        super().__init__()
        self.config = {"width": width, "blocks": blocks, "encoder": encoder}
        self.encoder = encoder
        self.inp = nn.Linear(feature_dim(encoder), width)
        self.blocks = nn.Sequential(*[ResBlock(width) for _ in range(blocks)])
        self.norm = nn.LayerNorm(width)
        self.out = nn.Linear(width, 52 * 3)

    def forward(self, x):
        h = self.blocks(torch.relu(self.inp(x.float())))
        return self.out(torch.relu(self.norm(h))).view(-1, 52, 3)


def load(path, device="cpu") -> BeliefNet:
    blob = torch.load(path, map_location=device, weights_only=False)
    net = BeliefNet(**blob["config"])
    net.load_state_dict(blob["state"])
    return net.to(device).eval()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--data", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--epochs", type=float, default=2.0)
    p.add_argument("--batch", type=int, default=8192)
    p.add_argument("--lr", type=float, default=1e-3)
    args = p.parse_args()
    device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    F, L = [], []
    for path in sorted(args.data.glob("shard_*.npz")):
        z = np.load(path)
        F.append(z["feat"]); L.append(z["loc"])
    F, L = np.concatenate(F), np.concatenate(L)
    n = len(L)
    rng = np.random.default_rng(0)
    perm = rng.permutation(n)
    hold, train = perm[:100_000], perm[100_000:]
    net = BeliefNet().to(device)
    dim = feature_dim(net.encoder)
    opt = torch.optim.AdamW(net.parameters(), lr=args.lr, weight_decay=1e-5, fused=device.type == "mps")
    steps = int(args.epochs * len(train) / args.batch)
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: 0.5 * (1 + math.cos(math.pi * min(s / steps, 1.0))))

    def nll(idx):
        x = torch.from_numpy(np.unpackbits(F[idx], axis=1)[:, :dim]).to(device)
        y = torch.from_numpy(L[idx].astype(np.int64)).to(device)
        logits = net(x)
        valid = y != 255
        return torch.nn.functional.cross_entropy(logits[valid], y[valid])

    t0 = time.time()
    for step in range(steps + 1):
        loss = nll(train[rng.integers(0, len(train), args.batch)])
        opt.zero_grad(set_to_none=True)
        loss.backward()
        opt.step()
        sched.step()
        if step % 500 == 0:
            with torch.no_grad():
                net.eval()
                h = float(np.mean([nll(hold[i:i + 20000]).item() for i in range(0, len(hold), 20000)]))
                net.train()
            print(f"step {step}/{steps} train {loss.item():.4f} held-out NLL/card {h:.4f} "
                  f"(uniform-over-3 {math.log(3):.4f}) ({time.time() - t0:.0f}s)", flush=True)
    state = {k: v.detach().cpu() for k, v in net.state_dict().items()}
    torch.save({"config": net.config, "state": state}, args.out)
    print("saved", args.out)


if __name__ == "__main__":
    main()
