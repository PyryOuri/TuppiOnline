"""SP1: self-play approximate policy iteration (docs/SELFPLAY_PLAN.md).

Each iteration:
  1. self-play with the current policy pi_k records full states at random
     unforced decisions (native; project_target_v3, fast sooli offers, no
     solver tail);
  2. every legal action of every state is played out with pi_k on all seats
     (native branch labels: the same hidden cards for every action);
  3. a Q network learns the labels (level plus centred advantages) on the GPU;
  4. the composite policy argmax_a [Q(obs, a) + margin * 1(a = pi_k(obs))] is
     distilled into the next policy net;
  5. a native duplicate check of pi_{k+1} against the clone and against pi_k.

    python -m tuppi_ai.selfplay --name sp1 --hours 6
"""

from __future__ import annotations

import argparse
import ctypes as C
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import torch

from . import model as qmodel
from . import native
from .value import _unpack

ROOT = Path(__file__).resolve().parents[1]
SCALE = qmodel.RETURN_SCALE


@dataclass
class Config:
    init: str = str(ROOT.parent / "TuppiAI" / "runs" / "bc_small.pt")
    offer_model: str = str(ROOT / "models" / "offer_model_selfplay.pt")
    ruleset: int = 3
    states_per_iter: int = 400_000
    p_record: float = 0.04
    p_random: float = 0.03
    margin: float = 0.003          # equity: how much better than pi_k's action a new one must look
    min_adv_r2: float = 0.2        # the policy only changes once Q explains this much held-out advantage variance
    replay_iters: int = 3
    q_steps: int = 2000
    pi_steps: int = 1500
    batch: int = 16384
    lr_q: float = 1e-3
    lr_pi: float = 3e-4
    adv_weight: float = 4.0
    eval_base: int = 8192
    selfplay_games: int = 16384
    label_games: int = 32768
    incremental: bool = True       # incremental first layer in self-play and labelling (labels identical in tests)
    seed: int = 1
    compile: bool = True


def _masked_argmax(q: np.ndarray, mask: np.ndarray) -> np.ndarray:
    return np.where(mask == 1, q, -np.inf).argmax(axis=1)


class Learner:
    def __init__(self, cfg: Config, out: Path):
        self.cfg, self.out = cfg, out
        self.dev = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
        base = qmodel.load(cfg.init, "cpu")
        self.encoder, self.dim = base.encoder, native.feature_dim(base.encoder)
        self.clone = native.Mlp(base)
        self.policy = qmodel.load(cfg.init, "cpu")            # pi_k (CPU copy for export)
        self.qnet = qmodel.load(cfg.init, self.dev).train()   # warm start: the clone's trunk ...
        with torch.no_grad():                                   # ... but a fresh, zero value head
            self.qnet.out.weight.zero_()
            self.qnet.out.bias.zero_()
        self.pnet = qmodel.load(cfg.init, self.dev).train()
        self.opt_q = torch.optim.AdamW(self.qnet.parameters(), lr=cfg.lr_q, weight_decay=1e-5,
                                       fused=self.dev.type == "mps")
        self.opt_p = torch.optim.AdamW(self.pnet.parameters(), lr=cfg.lr_pi, weight_decay=1e-5,
                                       fused=self.dev.type == "mps")
        self.q_fwd = torch.compile(self.qnet) if cfg.compile else self.qnet
        self.p_fwd = torch.compile(self.pnet) if cfg.compile else self.pnet
        if cfg.offer_model:
            from .offer_screen import load as load_offer
            om, _ = load_offer(cfg.offer_model)
            self._offer = native.Mlp(om, in_dim=om.config["in_dim"], out_dim=1)
            native.set_offer_model(self._offer)
        from .best import EQUITY
        from .equity import Equity
        table = Equity.load(EQUITY).table
        self.env_play = native.Env(cfg.selfplay_games, cfg.seed, table, single_deal=True, encoder=self.encoder)
        self.env_label = native.Env(cfg.label_games, cfg.seed + 1, table, single_deal=True, encoder=self.encoder)
        self.env_eval = native.Env(8 * cfg.eval_base, cfg.seed + 2, table, single_deal=True, encoder=self.encoder)
        for env in (self.env_play, self.env_label, self.env_eval):
            env.set_sooli(0, False, False, 0.0)
        if cfg.incremental:
            for env in (self.env_play, self.env_label):
                env.set_incremental(True, base.config["width"])
        self.rng = C.c_uint64(cfg.seed * 0x9E3779B97F4A7C15 % 2**64 + 7)
        self.replay: list[dict] = []
        self.iteration = 0

    # ---------------------------------------------------------------- data
    def collect(self, mlp: native.Mlp) -> dict:
        cfg = self.cfg
        t0 = time.perf_counter()
        feats, masks, qs, n_total = [], [], [], 0
        t_label = 0.0
        while n_total < cfg.states_per_iter:
            states, n = native.selfplay_states(self.env_play, mlp, cfg.selfplay_games, cfg.ruleset, self.rng,
                                               cfg.p_record, cfg.p_random, cfg.selfplay_games * 8)
            feat, mask = native.encode_states(states, n, self.encoder)
            k = mask.sum(axis=1)
            tl = time.perf_counter()
            start = 0
            while start < n:  # label in chunks that fit the labelling environment
                cum = np.cumsum(k[start:])
                stop = start + int(np.searchsorted(cum, cfg.label_games, side="right"))
                acts, kk, qv = native.branch_values(self.env_label, mlp, states, stop - start, 0, self.rng,
                                                    offset=start)
                q = np.zeros((stop - start, native.NUM_ACTIONS), dtype=np.float32)
                rows = np.repeat(np.arange(stop - start), native.MAX_K).reshape(-1, native.MAX_K)
                valid = np.arange(native.MAX_K)[None, :] < kk[:, None]
                q[rows[valid], acts[valid]] = qv[valid]
                qs.append(q)
                start = stop
            t_label += time.perf_counter() - tl
            feats.append(np.packbits(feat, axis=1))
            masks.append(mask)
            n_total += n
        data = {"feat": np.concatenate(feats), "mask": np.concatenate(masks), "q": np.concatenate(qs)}
        data["seconds"] = time.perf_counter() - t0
        data["label_seconds"] = t_label
        return data

    def _to_dev(self, data: dict) -> dict:
        return {"feat": torch.from_numpy(data["feat"]).to(self.dev),
                "mask": torch.from_numpy(data["mask"]).to(self.dev).bool(),
                "q": torch.from_numpy(data["q"]).to(self.dev) * SCALE}

    # ------------------------------------------------------------ training
    def adv_r2(self, H: dict) -> float:
        """Share of the held-out centred-advantage variance the Q net explains."""
        self.qnet.eval()
        num = den = 0.0
        with torch.no_grad():
            for i in range(0, len(H["feat"]), 65536):
                x, m, t = _unpack(H["feat"][i:i + 65536], self.dim), H["mask"][i:i + 65536], H["q"][i:i + 65536]
                mf = m.float()
                k = mf.sum(1, keepdim=True)
                pc = (p := self.qnet(x)) - (p * mf).sum(1, keepdim=True) / k
                tc = t - (t * mf).sum(1, keepdim=True) / k
                num += float((((pc - tc) ** 2) * mf).sum())
                den += float(((tc ** 2) * mf).sum())
        self.qnet.train()
        return 1.0 - num / max(den, 1e-12)

    def train_q(self, D: dict, H: dict | None = None) -> tuple[float, float, int]:
        """Trains the Q net; with held-out states H, keeps the weights with the best
        held-out advantage R^2 (checked every 200 steps). Returns (adv mse, R^2, step)."""
        cfg, n = self.cfg, len(D["feat"])
        losses = []
        best = (self.adv_r2(H), 0, {k: v.detach().clone() for k, v in self.qnet.state_dict().items()}) if H else None
        for step in range(cfg.q_steps):
            idx = torch.randint(0, n, (cfg.batch,), device=self.dev)
            x, m, t = _unpack(D["feat"][idx], self.dim), D["mask"][idx], D["q"][idx]
            pred = self.q_fwd(x)
            mf = m.float()
            k = mf.sum(1, keepdim=True)
            level = (((pred - t) ** 2) * mf).sum() / mf.sum()
            pc = pred - (pred * mf).sum(1, keepdim=True) / k
            tc = t - (t * mf).sum(1, keepdim=True) / k
            adv = (((pc - tc) ** 2) * mf).sum() / mf.sum()
            loss = level + cfg.adv_weight * adv
            self.opt_q.zero_grad(set_to_none=True)
            loss.backward()
            self.opt_q.step()
            if step % 200 == 0:
                losses.append(float(adv.detach()))
            if H is not None and (step + 1) % 200 == 0:
                r2 = self.adv_r2(H)
                if r2 > best[0]:
                    best = (r2, step + 1, {k: v.detach().clone() for k, v in self.qnet.state_dict().items()})
        if H is None:
            return float(np.mean(losses[-3:])) / SCALE ** 2, float("nan"), cfg.q_steps
        self.qnet.load_state_dict(best[2])
        return float(np.mean(losses[-3:])) / SCALE ** 2, best[0], best[1]

    def composite_labels(self, D: dict) -> tuple[torch.Tensor, dict]:
        """argmax_a Q + margin * 1(a = pi_k) for every state of D, and diagnostics."""
        cfg, n = self.cfg, len(D["feat"])
        self.qnet.eval()
        labels, changed, show_rows, show_rami_old, show_rami_new = [], 0, 0, 0, 0
        pk = self.policy.to(self.dev).eval()
        with torch.no_grad():
            for i in range(0, n, 65536):
                x, m = _unpack(D["feat"][i:i + 65536], self.dim), D["mask"][i:i + 65536]
                q = self.qnet(x).masked_fill(~m, float("-inf"))
                old = pk(x).masked_fill(~m, float("-inf")).argmax(1)
                q = q + (cfg.margin * SCALE) * torch.nn.functional.one_hot(old, native.NUM_ACTIONS)
                new = q.argmax(1)
                labels.append(new)
                changed += int((new != old).sum())
                show = m[:, 52:].any(1)
                show_rows += int(show.sum())
                show_rami_old += int((show & (old >= 104)).sum())
                show_rami_new += int((show & (new >= 104)).sum())
        self.policy.cpu()
        self.qnet.train()
        return torch.cat(labels), {"changed": changed / n, "show_states": show_rows,
                                   "rami_old": show_rami_old / max(show_rows, 1),
                                   "rami_new": show_rami_new / max(show_rows, 1)}

    def train_policy(self, D: dict, labels: torch.Tensor) -> float:
        cfg, n = self.cfg, len(D["feat"])
        losses = []
        for step in range(cfg.pi_steps):
            idx = torch.randint(0, n, (cfg.batch,), device=self.dev)
            x, m = _unpack(D["feat"][idx], self.dim), D["mask"][idx]
            logits = self.p_fwd(x).masked_fill(~m, -1e9)
            loss = torch.nn.functional.cross_entropy(logits, labels[idx])
            self.opt_p.zero_grad(set_to_none=True)
            loss.backward()
            self.opt_p.step()
            if step % 200 == 0:
                losses.append(float(loss.detach()))
        return float(np.mean(losses[-3:]))

    # ----------------------------------------------------------------- loop
    def evaluate(self, a: native.Mlp, b: native.Mlp) -> tuple[float, float]:
        v = native.duplicate_eval(self.env_eval, a, b, self.cfg.eval_base, self.cfg.ruleset, self.rng)
        return float(v.mean()), float(1.96 * v.std(ddof=1) / np.sqrt(len(v)))

    def iterate(self) -> dict:
        cfg = self.cfg
        t0 = time.perf_counter()
        mlp_k = native.Mlp(self.policy)
        data = self.collect(mlp_k)
        dev_data = self._to_dev(data)
        n_hold = len(dev_data["feat"]) // 10  # this iteration's first 10%: held out from the Q net
        H = {key: v[:n_hold] for key, v in dev_data.items()}
        self.replay.append({key: v[n_hold:] for key, v in dev_data.items()})
        self.replay = self.replay[-cfg.replay_iters:]
        D = {key: torch.cat([r[key] for r in self.replay]) for key in ("feat", "mask", "q")}
        t1 = time.perf_counter()
        adv_mse, r2, q_best_step = self.train_q(D, H)
        if r2 >= cfg.min_adv_r2:
            labels, diag = self.composite_labels(D)
            ce = self.train_policy(D, labels)
        else:  # Q has not learned enough yet: keep the policy
            diag, ce = {"changed": 0.0, "show_states": 0, "rami_old": None, "rami_new": None}, None
        t2 = time.perf_counter()
        self.policy.load_state_dict({k: v.detach().cpu() for k, v in self.pnet.state_dict().items()})
        mlp_next = native.Mlp(self.policy)
        vs_clone = self.evaluate(mlp_next, self.clone)
        vs_prev = self.evaluate(mlp_next, mlp_k)
        self.iteration += 1
        qmodel.save(self.policy, self.out / f"policy_{self.iteration:03d}.pt")
        qmodel.save(self.qnet, self.out / "q_latest.pt")
        row = {"iteration": self.iteration, "states": int(len(data["feat"])), "replay_states": int(len(D["feat"])),
               "vs_clone": vs_clone, "vs_prev": vs_prev, "adv_mse": adv_mse, "adv_r2": r2, "q_best_step": q_best_step, "policy_ce": ce, **diag,
               "collect_s": round(data["seconds"], 1), "label_s": round(data["label_seconds"], 1),
               "train_s": round(t2 - t1, 1), "eval_s": round(time.perf_counter() - t2, 1),
               "total_s": round(time.perf_counter() - t0, 1)}
        with open(self.out / "log.jsonl", "a") as f:
            f.write(json.dumps(row) + "\n")
        return row


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--name", required=True)
    p.add_argument("--hours", type=float, default=1.0)
    p.add_argument("--iterations", type=int, default=10_000)
    for field, default in asdict(Config()).items():
        kind = type(default)
        p.add_argument("--" + field.replace("_", "-"), type=(lambda s: s.lower() in ("1", "true")) if kind is bool
                       else kind, default=default)
    a = p.parse_args()
    cfg = Config(**{f: getattr(a, f) for f in asdict(Config())})
    out = ROOT / "runs" / "selfplay" / a.name
    out.mkdir(parents=True, exist_ok=True)
    (out / "config.json").write_text(json.dumps(asdict(cfg), indent=1))
    native.set_rollout_chunk(128)
    torch.set_num_threads(1)
    learner = Learner(cfg, out)
    t_end = time.time() + 3600 * a.hours
    while time.time() < t_end and learner.iteration < a.iterations:
        print(json.dumps(learner.iterate()), flush=True)


if __name__ == "__main__":
    main()
