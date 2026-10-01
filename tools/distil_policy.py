"""Distil a policy net into a differently shaped one (for VRPO with a larger actor).

States come from the teacher's own sampled self-play (`native.ppo_rollouts`,
every network decision of all four seats). The student is trained on the
GPU to match the teacher's softmax over the legal actions (KL divergence),
then checked natively: greedy agreement on fresh states and a duplicate
evaluation against the teacher.

    python tools/distil_policy.py --teacher models/vrpo1_actor_0504.pt --width 512 --blocks 4 \\
        --out models/vrpo1_512x4.pt
"""

from __future__ import annotations

import argparse
import ctypes as C
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tuppi_ai import model as qmodel  # noqa: E402
from tuppi_ai import native  # noqa: E402
from tuppi_ai.value import _unpack  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--teacher", required=True)
    p.add_argument("--width", type=int, default=512)
    p.add_argument("--blocks", type=int, default=4)
    p.add_argument("--rounds", type=int, default=24, help="data rounds of --games deals each")
    p.add_argument("--games", type=int, default=16384)
    p.add_argument("--epochs", type=int, default=2, help="passes over each round's data")
    p.add_argument("--batch", type=int, default=8192)
    p.add_argument("--lr", type=float, default=5e-4)
    p.add_argument("--eval-base", type=int, default=8192)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    torch.set_num_threads(1)
    dev = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    teacher_cpu = qmodel.load(a.teacher, "cpu")
    enc, dim = teacher_cpu.encoder, native.feature_dim(teacher_cpu.encoder)
    teacher = qmodel.load(a.teacher, dev).eval()
    student = qmodel.QNet(a.width, a.blocks, enc).to(dev).train()
    opt = torch.optim.AdamW(student.parameters(), lr=a.lr, weight_decay=1e-5, fused=dev.type == "mps")
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=a.rounds)
    from tuppi_ai.best import EQUITY
    from tuppi_ai.equity import Equity
    from tuppi_ai.offer_screen import load as load_offer
    om, _ = load_offer(ROOT / "models" / "offer_model_selfplay.pt")
    offer = native.Mlp(om, in_dim=om.config["in_dim"], out_dim=1)
    native.set_offer_model(offer)
    table = Equity.load(EQUITY).table
    env = native.Env(a.games, a.seed, table, single_deal=True, encoder=enc)
    env.set_sooli(0, False, False, 0.0)
    rng = C.c_uint64(a.seed * 7919 + 3)
    t_mlp = native.Mlp(teacher_cpu)
    log = []
    for rnd in range(a.rounds):
        t0 = time.perf_counter()
        d = native.ppo_rollouts(env, t_mlp, a.games, 3, rng, 1.0)
        feat = torch.from_numpy(d["feat"]).to(dev)
        mask = torch.from_numpy(d["mask"]).to(dev)
        n = len(feat)
        losses = []
        for _ in range(a.epochs):
            perm = torch.randperm(n, device=dev)
            for i in range(0, n, a.batch):
                idx = perm[i:i + a.batch]
                x = _unpack(feat[idx], dim)
                m = _unpack(mask[idx], native.NUM_ACTIONS).bool()
                with torch.no_grad():
                    pt = torch.softmax(teacher(x).masked_fill(~m, -1e9), 1)
                ls = torch.log_softmax(student(x).masked_fill(~m, -1e9), 1)
                loss = -(pt * ls.masked_fill(~m, 0.0)).sum(1).mean()  # cross-entropy = KL + teacher entropy
                opt.zero_grad(set_to_none=True)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(student.parameters(), 1.0)
                opt.step()
                losses.append(float(loss.detach()))
        sched.step()
        # greedy agreement on this round's last batch
        with torch.no_grad():
            x = _unpack(feat[-65536:], dim)
            m = _unpack(mask[-65536:], native.NUM_ACTIONS).bool()
            choice = m.sum(1) > 1
            agree = float(((teacher(x).masked_fill(~m, -1e9).argmax(1) == student(x).masked_fill(~m, -1e9).argmax(1))
                           [choice]).float().mean())
        row = {"round": rnd + 1, "rows": n, "ce": float(np.mean(losses[-20:])), "greedy_agreement": agree,
               "seconds": round(time.perf_counter() - t0, 1)}
        log.append(row)
        print(json.dumps(row), flush=True)
    student_cpu = qmodel.QNet(a.width, a.blocks, enc)
    student_cpu.load_state_dict({k: v.detach().cpu() for k, v in student.state_dict().items()})
    qmodel.save(student_cpu.eval(), a.out, distilled_from=str(a.teacher))
    env_eval = native.Env(8 * a.eval_base, a.seed + 5, table, single_deal=True, encoder=enc)
    env_eval.set_sooli(0, False, False, 0.0)
    vals = native.duplicate_eval(env_eval, native.Mlp(student_cpu.eval()), t_mlp, a.eval_base, 3, rng)
    res = {"student_vs_teacher": [float(vals.mean()), float(1.96 * vals.std(ddof=1) / np.sqrt(len(vals)))]}
    print(json.dumps(res), flush=True)
    a.out.with_suffix(".json").write_text(json.dumps({"log": log, **res, **vars(a)}, default=str, indent=1))


if __name__ == "__main__":
    main()
