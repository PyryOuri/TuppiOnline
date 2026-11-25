"""Bake the suit-averaged network into one plain network (distillation).

`symmetry.Symmetric(net)` plays better than `net` but needs four forward passes
per decision and code that the hosted bots do not have. This trains a plain
network, the student, to give the averaged network's policy from a single
pass, so the gain can ship as an ordinary network file.

It is supervised learning with a clean target and unlimited data:

1. deals are played in lockstep, alternately by the teacher and by the student
   (so the student is also corrected where its own play leads), with at most
   one random move per deal;
2. for every unforced decision the teacher's policy is computed (softmax of
   its averaged logits over the legal actions);
3. the student is trained to match it (KL divergence), each minibatch seen
   through one of the four suit views chosen at random, the target relabelled
   with it: the student is taught to be symmetric as well.

Every `eval_every` iterations the student plays the base network (panel[0],
normally the network the teacher was built from), the other panel networks and
the teacher, on fixed deals; the best student against the base is kept as
best_student.pt. A run resumes from its last checkpoint.

    python -m tuppi_train.bake --name sym4 --hours 1 --offer-model <offer_model.pt>
    python -m tuppi_train.bake --name sym4x --hours 2 --init "" --width 1024 --blocks 5   # a larger student
"""

from __future__ import annotations

import argparse
import ctypes as C
import json
import math
import signal
import time
from dataclasses import asdict, dataclass, fields
from pathlib import Path

import numpy as np
import torch

from . import REPO, checkpoint, device, labels, lockstep, offer, symmetry, tn
from tuppi_ai import model as qmodel
from tuppi_ai import native
from tuppi_ai.value import _unpack

A = native.NUM_ACTIONS


@dataclass
class Config:
    teacher: str = "sym:vrpo4_final.pt"
    init: str = "vrpo4_final.pt"     # the student's starting weights; "" = a new network of width x blocks
    width: int = 0                   # with init: 0 = its shape
    blocks: int = 0
    panel: str = "vrpo4_final.pt,vrpo3_final.pt,vrpo1_actor_0504.pt"   # the first is the base
    offer_model: str = ""
    ruleset: int = 3
    games_per_iter: int = 16384
    p_explore: float = 0.01          # per unforced decision, at most one random move per deal
    student_share: float = 0.5       # share of iterations whose deals the student plays
    epochs: int = 1
    minibatch: int = 16384
    lr: float = 1e-4
    lr_final: float = 1e-5           # cosine from lr to lr_final over lr_decay_iters iterations, then constant
    lr_decay_iters: int = 300
    augment: bool = True             # train through a random suit view per minibatch
    eval_every: int = 20
    eval_base: int = 2048
    eval_seed: int = 20261126
    save_minutes: float = 5.0
    milestone_every: int = 100
    seed: int = 1
    amp: str = "off"
    compile: bool = False
    tf32: bool = True


class Baker:
    def __init__(self, cfg: Config, out: Path, dev: torch.device | None = None, resume: bool = True):
        self.cfg, self.out = cfg, Path(out)
        self.out.mkdir(parents=True, exist_ok=True)
        self.dev = dev or device.pick()
        device.setup(self.dev, cfg.tf32)
        if cfg.amp not in device.AMP:
            raise ValueError(f"amp must be one of {sorted(device.AMP)}")
        self.amp = device.AMP[cfg.amp]
        torch.manual_seed(cfg.seed)
        self.teacher = symmetry.load_net(cfg.teacher, self.dev).eval()
        for p in self.teacher.parameters():
            p.requires_grad_(False)
        self.encoder, self.dim = self.teacher.encoder, native.feature_dim(self.teacher.encoder)
        if cfg.init:
            start = symmetry.load_net(cfg.init, "cpu")
            self.student = qmodel.QNet(**start.config)
            self.student.load_state_dict(start.state_dict())
        else:
            if not (cfg.width and cfg.blocks):
                raise ValueError("a new student needs --width and --blocks")
            self.student = qmodel.QNet(cfg.width, cfg.blocks, self.encoder)
        self.student = self.student.to(self.dev).train()
        self.opt = device.adamw(self.student.parameters(), cfg.lr, 0.0, self.dev)
        self.scaler = torch.amp.GradScaler(self.dev.type, enabled=cfg.amp == "fp16")
        self.fwd = torch.compile(self.student) if cfg.compile else self.student
        native.set_offer_model(offer.load_native(cfg.offer_model) if cfg.offer_model else None)
        native.set_branch_share(False)
        from tuppi_ai.best import EQUITY
        from tuppi_ai.equity import Equity
        self.table = Equity.load(EQUITY).table
        self.env = self._env(cfg.games_per_iter)
        self.env_eval = self._env(8 * cfg.eval_base)
        self.panel = [(Path(n.strip()).stem.replace(":", "_"), symmetry.load_net(n.strip(), self.dev))
                      for n in cfg.panel.split(",") if n.strip()]
        self.rng = C.c_uint64(cfg.seed * 0x9E3779B97F4A7C15 % 2**64 + 17)
        self.iteration = 0
        self.best = {"mean": None, "iteration": None}
        self.seconds = 0.0
        self.views: dict = {}
        self.store = checkpoint.Rotating(self.out / "ckpt")
        self._last_save = time.time()
        if resume:
            self._restore()

    def _env(self, n: int) -> "native.Env":
        env = native.Env(n, self.cfg.seed, self.table, single_deal=True, encoder=self.encoder)
        env.set_sooli(0, False, False, 0.0)
        return env

    def _run(self, module, x):
        if self.amp is None:
            return module(x)
        with torch.autocast(self.dev.type, dtype=self.amp):
            return module(x).float()

    def student_cpu(self) -> qmodel.QNet:
        net = qmodel.QNet(**self.student.config)
        net.load_state_dict({k: v.detach().cpu() for k, v in self.student.state_dict().items()})
        return net.eval()

    # ----------------------------------------------------------------- data
    def collect(self) -> tuple[torch.Tensor, torch.Tensor, str]:
        """One batch of deals; the packed features and legal masks of their unforced decisions."""
        cfg = self.cfg
        by_student = (self.iteration * cfg.student_share) % 1.0 + cfg.student_share >= 1.0
        player = self.student if by_student else self.teacher
        choose = labels.Recorder(self.env, lockstep.TorchGreedy(player, self.dev, self.encoder, amp=self.amp),
                                 cfg.games_per_iter, 0.0, cfg.p_explore, None,
                                 seed=cfg.seed * 1_000_003 + self.iteration, capacity=1)
        d = lockstep.rollouts(self.env, choose, cfg.games_per_iter, cfg.ruleset, self.rng, self.encoder)
        unforced = np.unpackbits(d["mask"], axis=1).sum(1) > 1
        feat = torch.from_numpy(d["feat"][unforced]).to(self.dev)
        mask = torch.from_numpy(d["mask"][unforced]).to(self.dev)
        return feat, mask, "student" if by_student else "teacher"

    def targets(self, feat: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
        """The teacher's log-policy over the legal actions of every row (illegal: very negative)."""
        out = torch.empty((len(feat), A), device=self.dev)
        with torch.no_grad():
            for i in range(0, len(feat), 32768):
                x = _unpack(feat[i:i + 32768], self.dim)
                legal = _unpack(mask[i:i + 32768], A).bool()
                out[i:i + 32768] = torch.log_softmax(self._run(self.teacher, x).float().masked_fill(~legal, -1e9), 1)
        return out

    # ------------------------------------------------------------- training
    def lr_now(self) -> float:
        cfg = self.cfg
        if cfg.lr_decay_iters <= 0 or self.iteration >= cfg.lr_decay_iters:
            return cfg.lr_final if cfg.lr_decay_iters > 0 else cfg.lr
        return cfg.lr_final + 0.5 * (cfg.lr - cfg.lr_final) * (1 + math.cos(math.pi * self.iteration / cfg.lr_decay_iters))

    def iterate(self) -> dict:
        cfg, dev = self.cfg, self.dev
        t0 = time.perf_counter()
        feat, mask, played_by = self.collect()
        t_play = time.perf_counter() - t0
        target = self.targets(feat, mask)
        n = len(feat)
        lr = self.lr_now()
        for group in self.opt.param_groups:
            group["lr"] = lr
        losses, agree = [], None
        for _ in range(cfg.epochs):
            perm = torch.randperm(n, device=dev)
            for i in range(0, n, cfg.minibatch):
                idx = perm[i:i + cfg.minibatch]
                x, legal, t = _unpack(feat[idx], self.dim), _unpack(mask[idx], A).bool(), target[idx]
                view = int(torch.randint(0, 4, (1,)).item()) if cfg.augment else 0
                x, legal, t = symmetry.view_of(x, legal, t, view, self.encoder, self.views)
                logits = self._run(self.fwd, x).float().masked_fill(~legal, -1e9)
                logp = torch.log_softmax(logits, 1)
                p_t = torch.exp(t)
                loss = (p_t * (t - logp)).masked_fill(~legal, 0.0).sum(1).mean()
                if agree is None:   # before this iteration's first step: how the student stands on fresh rows
                    agree = float((lockstep.greedy(logits) == lockstep.greedy(t)).float().mean())
                self.opt.zero_grad(set_to_none=True)
                if self.scaler.is_enabled():
                    self.scaler.scale(loss).backward()
                    self.scaler.unscale_(self.opt)
                    torch.nn.utils.clip_grad_norm_(self.student.parameters(), 1.0)
                    self.scaler.step(self.opt)
                    self.scaler.update()
                else:
                    loss.backward()
                    torch.nn.utils.clip_grad_norm_(self.student.parameters(), 1.0)
                    self.opt.step()
                losses.append(float(loss.detach()))
        self.iteration += 1
        row = {"iteration": self.iteration, "rows": n, "played_by": played_by, "kl_first": losses[0],
               "kl": float(np.mean(losses)), "agree": agree, "lr": lr, "play_s": round(t_play, 2)}
        if self.iteration % cfg.eval_every == 0:
            self._judge(row)
        if cfg.milestone_every and self.iteration % cfg.milestone_every == 0:
            folder = self.out / "students"
            folder.mkdir(exist_ok=True)
            qmodel.save(self.student_cpu(), folder / f"student_{self.iteration:06d}.pt", iteration=self.iteration)
        row["total_s"] = round(time.perf_counter() - t0, 2)
        self.seconds += time.perf_counter() - t0
        row["hours"] = round(self.seconds / 3600, 3)
        with open(self.out / "log.jsonl", "a") as f:
            f.write(json.dumps(row) + "\n")
        if time.time() - self._last_save >= cfg.save_minutes * 60:
            self.save()
        return row

    # ----------------------------------------------------------- evaluation
    def evaluate(self, base: int | None = None, seed: int | None = None, symmetric: bool = False) -> dict:
        """Paired duplicate of the student (or its suit-averaged self) against every panel network
        and the teacher: name -> [mean, 95% half-width] per deal."""
        cfg = self.cfg
        base = base or cfg.eval_base
        env = self.env_eval if 8 * base <= self.env_eval.n else self._env(8 * base)
        side = symmetry.Symmetric(self.student).to(self.dev).eval() if symmetric else self.student
        a = lockstep.TorchGreedy(side, self.dev, self.encoder, amp=self.amp)
        out = {}
        for name, net in self.panel + [("teacher", self.teacher)]:
            b = lockstep.TorchGreedy(net, self.dev, self.encoder, amp=self.amp)
            v = lockstep.duplicate_eval(env, a, b, base, cfg.ruleset, C.c_uint64(seed if seed is not None else cfg.eval_seed),
                                        self.encoder)
            out[name] = lockstep.interval(v)
        return out

    def _judge(self, row: dict) -> None:
        result = self.evaluate()
        row["eval"] = result
        mean = result[self.panel[0][0]][0] if self.panel else result["teacher"][0]
        if self.best["mean"] is None or mean > self.best["mean"]:
            self.best = {"mean": mean, "iteration": self.iteration}
            qmodel.save(self.student_cpu(), self.out / "best_student.pt", iteration=self.iteration, eval=result,
                        teacher=self.cfg.teacher)

    # --------------------------------------------------------------- resume
    def state(self) -> dict:
        return {"config": asdict(self.cfg), "iteration": self.iteration, "student_config": self.student.config,
                "student": {k: v.detach().cpu() for k, v in self.student.state_dict().items()},
                "opt": self.opt.state_dict(), "scaler": self.scaler.state_dict(), "rng": int(self.rng.value),
                "torch_rng": torch.get_rng_state(),
                "cuda_rng": torch.cuda.get_rng_state_all() if self.dev.type == "cuda" else None,
                "best": dict(self.best), "seconds": self.seconds}

    def save(self) -> Path:
        path = self.store.save(self.state())
        self._last_save = time.time()
        return path

    def _restore(self) -> bool:
        s = self.store.load()
        if s is None:
            return False
        if s["student_config"] != self.student.config:
            raise ValueError("the checkpoint's student has another shape than this configuration")
        self.student.load_state_dict(s["student"])
        self.opt.load_state_dict(s["opt"])
        if s.get("scaler") and self.scaler.is_enabled():
            self.scaler.load_state_dict(s["scaler"])
        self.rng = C.c_uint64(s["rng"])
        torch.set_rng_state(s["torch_rng"])
        if self.dev.type == "cuda" and s.get("cuda_rng") is not None:
            torch.cuda.set_rng_state_all(s["cuda_rng"])
        self.iteration, self.best, self.seconds = s["iteration"], dict(s["best"]), s["seconds"]
        log = self.out / "log.jsonl"
        if log.exists():
            rows = [line for line in log.read_text().splitlines()
                    if line.strip() and json.loads(line)["iteration"] <= self.iteration]
            log.write_text("".join(r + "\n" for r in rows))
        return True


def brief(row: dict) -> str:
    parts = [f"{row['iteration']:6d}", f"{row['total_s']:6.1f}s (play {row['play_s']:.1f}, by {row['played_by']})",
             f"KL {row['kl']:.5f}", f"same choice as teacher {row['agree']:.2%}"]
    if "eval" in row:
        parts.append("EVAL " + ", ".join(f"{k} {v[0]:+.5f}+/-{v[1]:.5f}" for k, v in row["eval"].items()))
    return " | ".join(parts)


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--name", required=True)
    p.add_argument("--out", type=Path, default=None, help="run directory (default training/runs/<name>)")
    p.add_argument("--hours", type=float, default=1.0)
    p.add_argument("--iterations", type=int, default=10**9)
    p.add_argument("--device", default=None)
    p.add_argument("--print-every", type=int, default=1)
    for f in fields(Config):
        kind = type(f.default)
        p.add_argument("--" + f.name.replace("_", "-"), default=None,
                       type=(lambda s: s.lower() in ("1", "true")) if kind is bool else kind)
    a = p.parse_args(argv)
    out = a.out or REPO / "training" / "runs" / a.name
    given = {f.name: getattr(a, f.name) for f in fields(Config) if getattr(a, f.name) is not None}
    saved = checkpoint.Rotating(out / "ckpt").load()
    base = saved["config"] if saved else {}
    names = {f.name for f in fields(Config)}
    cfg = Config(**{**{k: v for k, v in base.items() if k in names}, **given})
    out.mkdir(parents=True, exist_ok=True)
    (out / "config.json").write_text(json.dumps(asdict(cfg), indent=1))
    dev = device.pick(a.device)
    print(json.dumps({"run": a.name, "out": str(out), "resumed_from": saved["iteration"] if saved else None,
                      "threads": tn.threads(), **device.describe(dev)}), flush=True)
    baker = Baker(cfg, out, dev)
    stop = {"asked": False}

    def ask_stop(signum, frame):
        if stop["asked"]:
            raise KeyboardInterrupt
        stop["asked"] = True
        print(f"signal {signum}: stopping after this iteration and saving", flush=True)

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, ask_stop)
    t_end = time.time() + 3600 * a.hours
    while time.time() < t_end and baker.iteration < a.iterations and not stop["asked"]:
        row = baker.iterate()
        if "eval" in row or row["iteration"] % a.print_every == 0:
            print(brief(row), flush=True)
    baker.save()
    print(json.dumps({"finished": "stopped by a signal" if stop["asked"] else "time or iteration limit",
                      "iteration": baker.iteration, "hours": round(baker.seconds / 3600, 3), "best": baker.best}),
          flush=True)


if __name__ == "__main__":
    main()
