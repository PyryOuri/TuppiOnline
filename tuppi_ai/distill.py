"""Distil a search policy into a network (expert iteration).

Trains the policy logits by cross-entropy on the actions chosen by
`bsearch` (search over the current blueprint). Rows where no data exists stay
covered by starting from the blueprint's own weights. Optionally mixes in the
original behaviour-cloning shards so rarely searched positions do not drift.

    python -m tuppi_ai.distill --data runs/xi/v1 --init runs/bc_v1.pt --out runs/xi_v1.pt
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


def load_search(data: Path):
    F, M, A, B, P, V = [], [], [], [], [], []
    for path in sorted(data.glob("shard_*.npz")):
        z = np.load(path)
        F.append(z["feat"]); M.append(z["mask"]); A.append(z["act"]); B.append(z["bp"]); P.append(z["phase"])
        V.append(z["val"].astype(np.float16))
    return (np.concatenate(F), np.concatenate(M), np.concatenate(A).astype(np.int64),
            np.concatenate(B).astype(np.int64), np.concatenate(P), np.concatenate(V))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--data", type=Path, required=True, nargs="+")
    p.add_argument("--init", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--bc-data", type=Path, help="behaviour-cloning shards to mix in")
    p.add_argument("--bc-share", type=float, default=0.25)
    p.add_argument("--epochs", type=float, default=4.0)
    p.add_argument("--batch", type=int, default=4096)
    p.add_argument("--lr", type=float, default=3e-4)
    p.add_argument("--soft", type=float, default=0.0,
                   help="if > 0, train toward softmax(search values / soft) instead of the searched action")
    args = p.parse_args()
    device = torch.device("cuda" if torch.cuda.is_available() else
                          "mps" if torch.backends.mps.is_available() else "cpu")
    net = qmodel.load(args.init, "cpu")
    net.train().to(device)
    dim = feature_dim(net.encoder)
    parts = [load_search(d) for d in args.data]
    F = np.concatenate([x[0] for x in parts]); M = np.concatenate([x[1] for x in parts])
    A = np.concatenate([x[2] for x in parts]); B = np.concatenate([x[3] for x in parts])
    V = np.concatenate([x[5] for x in parts]) if args.soft > 0 else None
    n = len(A)
    rng = np.random.default_rng(0)
    perm = rng.permutation(n)
    hold, train = perm[: n // 20], perm[n // 20:]
    print(f"{n} search rows; search differs from blueprint on {np.mean(A != B):.3f}", flush=True)
    bc = None
    if args.bc_data:
        from .bc import load as load_bc
        bc = load_bc(args.bc_data)
        print(f"mixing {len(bc[1])} behaviour-cloning rows at share {args.bc_share}", flush=True)
    opt = torch.optim.AdamW(net.parameters(), lr=args.lr, weight_decay=1e-5, fused=device.type in ("mps", "cuda"))
    steps = int(args.epochs * len(train) / (args.batch * (1 - (args.bc_share if bc else 0))))
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: 0.5 * (1 + math.cos(math.pi * min(s / max(steps, 1), 1.0))))

    def unpack(f, m):
        return np.unpackbits(f, axis=1)[:, :dim], np.unpackbits(m, axis=1)[:, :NUM_ACTIONS]

    def held_out():
        net.eval()
        agree_s = agree_b = 0
        with torch.no_grad():
            for s in range(0, len(hold), 16384):
                idx = hold[s:s + 16384]
                x, m = unpack(F[idx], M[idx])
                q = net(torch.from_numpy(x).to(device)).cpu().numpy()
                pick = np.where(m == 1, q, -np.inf).argmax(1)
                agree_s += int((pick == A[idx]).sum())
                agree_b += int((pick == B[idx]).sum())
        net.train()
        return agree_s / len(hold), agree_b / len(hold)

    t0 = time.time()
    print("before: agreement with search %.4f, with blueprint %.4f" % held_out(), flush=True)
    nb = int(args.batch * args.bc_share) if bc else 0
    for step in range(steps + 1):
        idx = train[rng.integers(0, len(train), args.batch - nb)]
        x, m = unpack(F[idx], M[idx])
        y = A[idx]
        if nb:
            j = rng.integers(0, len(bc[1]), nb)
            xb, mb = unpack(bc[0][j], bc[2][j])
            x, m, y = np.concatenate([x, xb]), np.concatenate([m, mb]), np.concatenate([y, bc[1][j]])
        logits = net(torch.from_numpy(x).to(device))
        mt = torch.from_numpy(m).to(device) == 0
        logits = logits.masked_fill(mt, -1e9)
        if V is None:
            loss = torch.nn.functional.cross_entropy(logits, torch.from_numpy(y).to(device))
        else:
            ns = args.batch - nb
            tv = torch.from_numpy(V[idx].astype(np.float32)).to(device) / args.soft
            target = torch.softmax(tv.masked_fill(mt[:ns], -1e9), dim=1)
            logp = torch.log_softmax(logits, dim=1)
            loss = -(target * logp[:ns]).sum(1).mean()
            if nb:
                loss = loss * (ns / args.batch) + torch.nn.functional.cross_entropy(
                    logits[ns:], torch.from_numpy(y[ns:]).to(device)) * (nb / args.batch)
        opt.zero_grad(set_to_none=True)
        loss.backward()
        opt.step()
        sched.step()
        if step % 500 == 0:
            s_, b_ = held_out()
            print(f"step {step}/{steps} loss {loss.item():.4f} held-out agreement: search {s_:.4f} "
                  f"blueprint {b_:.4f} ({time.time() - t0:.0f}s)", flush=True)
    s_, b_ = held_out()
    print(f"final held-out agreement: search {s_:.4f} blueprint {b_:.4f}", flush=True)
    qmodel.save(net, args.out, distill={"data": [str(d) for d in args.data], "init": str(args.init),
                                        "agreement_search": s_, "agreement_blueprint": b_})
    print("saved", args.out, flush=True)


if __name__ == "__main__":
    main()
