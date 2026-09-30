"""Self-play approximate policy iteration (docs/SELFPLAY_PLAN.md, docs/SCALING_PLAN.md).

Each iteration:
  1. self-play with the current policy pi_k records full states at random
     unforced decisions (native; project_target_v3, fast sooli offers, no
     solver tail), more often in position classes whose decisions are rarely
     inert (importance sampling; every row carries its weight);
  2. every legal action of every state is played out with pi_k on all seats
     (native branch labels: the same hidden cards for every action; one
     rollout per run of rank-equivalent cards);
  3. a Q network learns the labels (level plus centred advantages) on the GPU,
     early-stopped on held-out advantage R^2;
  4. the composite policy argmax_a [Q(obs, a) + margin * 1(a = pi_k(obs))] is
     distilled into the next policy net;
  5. a native duplicate check of pi_{k+1} against the clone and against pi_k.

The Q net may be larger than the policy net: it is only trained and queried
on the GPU, while the policy net plays every rollout. Data is kept compact
(legal actions only, fp16 labels: about 325 bytes per state), written to one
shard per iteration, and a run can be resumed.

SP1 (2026-09-29; commit f6463ce): 43 iterations, 86.6M labelled states in
3.7 h; the final policy scores +0.0131 [+0.0119, +0.0143] against the
incumbent without search (clone -0.0001).

    python -m tuppi_ai.selfplay --name sp2 --hours 6
    python -m tuppi_ai.selfplay --name sp2 --hours 6 --resume
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
PAD = native.NUM_ACTIONS  # padding action id in compact label rows


@dataclass
class Config:
    init: str = str(ROOT.parent / "TuppiAI" / "runs" / "bc_small.pt")
    baseline: str = str(ROOT.parent / "TuppiAI" / "runs" / "bc_small.pt")  # the fixed opponent of the "vs_clone" check
    reference: str = ""            # optional second fixed opponent ("vs_ref"), e.g. the previous run's final policy
    holdout_every: int = 10        # every n-th self-play batch (whole deals) is held out from the Q net
    offer_model: str = str(ROOT / "models" / "offer_model_selfplay.pt")
    ruleset: int = 3
    states_per_iter: int = 2_000_000
    p_record: float = 0.04
    p_random: float = 0.03
    margin: float = 0.006          # equity: how much better than pi_k's action a new one must look
    min_adv_r2: float = 0.01       # the policy only changes once Q explains this much held-out advantage variance
    replay_iters: int = 3
    q_width: int = 0               # 0: the policy net's shape, warm-started from it
    q_blocks: int = 0
    q_steps: int = 2000
    pi_steps: int = 1000
    batch: int = 16384
    lr_q: float = 1e-3
    lr_pi: float = 3e-4
    adv_weight: float = 4.0
    eval_base: int = 8192
    selfplay_games: int = 16384
    label_games: int = 32768
    incremental: bool = True       # incremental first layer (labels identical in tests)
    share_labels: bool = True      # one rollout per run of rank-equivalent cards (95.7% identical labels)
    importance: bool = True        # record per position class by its measured non-inert rate
    mult_lo: float = 0.25
    mult_hi: float = 2.0
    save_data: bool = True         # one compact shard per iteration in <run>/data
    seed: int = 1
    compile: bool = True


def compact_labels(acts: np.ndarray, k: np.ndarray, q: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(ids uint8 [n, MAX_K] padded with PAD, labels float16 [n, MAX_K]) from branch_values output."""
    valid = np.arange(native.MAX_K)[None, :] < k[:, None]
    return np.where(valid, acts, PAD).astype(np.uint8), np.where(valid, q, 0).astype(np.float16)


def dense(ids: torch.Tensor, q: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
    """(legal mask [B, 156], scaled targets [B, 156]) from compact rows, on the device."""
    idx = ids.long()
    n = len(idx)
    mask = torch.zeros(n, PAD + 1, dtype=torch.bool, device=idx.device).scatter_(1, idx, True)[:, :PAD]
    tgt = torch.zeros(n, PAD + 1, device=idx.device).scatter_(1, idx, q.float() * SCALE)[:, :PAD]
    return mask, tgt


def inert_rows(ids: np.ndarray, q: np.ndarray) -> np.ndarray:
    """True where every legal action has the same label."""
    valid = ids != PAD
    qf = q.astype(np.float32)
    hi = np.where(valid, qf, -np.inf).max(1)
    lo = np.where(valid, qf, np.inf).min(1)
    return hi == lo


class Learner:
    def __init__(self, cfg: Config, out: Path):
        self.cfg, self.out = cfg, out
        self.dev = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
        base = qmodel.load(cfg.init, "cpu")
        self.encoder, self.dim = base.encoder, native.feature_dim(base.encoder)
        self.clone = native.Mlp(qmodel.load(cfg.baseline, "cpu"))
        self.ref = native.Mlp(qmodel.load(cfg.reference, "cpu")) if cfg.reference else None
        self.policy = qmodel.load(cfg.init, "cpu")            # pi_k (CPU copy for export)
        if cfg.q_width:  # a larger Q net, trained from scratch
            self.qnet = qmodel.QNet(cfg.q_width, cfg.q_blocks or 4, self.encoder).to(self.dev).train()
        else:            # the policy's shape: warm start from its trunk
            self.qnet = qmodel.load(cfg.init, self.dev).train()
        with torch.no_grad():  # a fresh, zero value head either way
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
        native.set_branch_share(cfg.share_labels)
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
        self.class_mult = np.ones(native.N_RECORD_CLASSES)
        self.replay: list[dict] = []
        self.iteration = 0

    # ---------------------------------------------------------------- data
    def collect(self, mlp: native.Mlp) -> dict:
        cfg = self.cfg
        t0 = time.perf_counter()
        feats, ids_all, qs, ws, classes, holds, n_total, t_label = [], [], [], [], [], [], 0, 0.0
        batch = 0
        mult = self.class_mult if cfg.importance else None
        while n_total < cfg.states_per_iter:
            states, n = native.selfplay_states(self.env_play, mlp, cfg.selfplay_games, cfg.ruleset, self.rng,
                                               cfg.p_record, cfg.p_random, cfg.selfplay_games * 8, mult)
            feat, mask = native.encode_states(states, n, self.encoder)
            cls = native.record_classes(states, n)
            k = mask.sum(axis=1)
            tl = time.perf_counter()
            start = 0
            while start < n:  # label in chunks that fit the labelling environment
                stop = start + int(np.searchsorted(np.cumsum(k[start:]), cfg.label_games, side="right"))
                acts, kk, qv = native.branch_values(self.env_label, mlp, states, stop - start, 0, self.rng,
                                                    offset=start)
                ids, q16 = compact_labels(acts, kk, qv)
                ids_all.append(ids)
                qs.append(q16)
                start = stop
            t_label += time.perf_counter() - tl
            feats.append(np.packbits(feat, axis=1))
            ws.append((1.0 / (mult[cls] if mult is not None else np.ones(n))).astype(np.float16))
            classes.append(cls)
            holds.append(np.full(n, batch % cfg.holdout_every == 0, dtype=np.uint8))  # whole deals held out
            batch += 1
            n_total += n
        data = {"feat": np.concatenate(feats), "ids": np.concatenate(ids_all), "q": np.concatenate(qs),
                "w": np.concatenate(ws), "hold": np.concatenate(holds)}
        inert = inert_rows(data["ids"], data["q"])
        self._update_class_mult(np.concatenate(classes), inert)
        data["w"] = (data["w"] / data["w"].astype(np.float32).mean()).astype(np.float16)
        if cfg.save_data:
            (self.out / "data").mkdir(exist_ok=True)
            np.savez(self.out / "data" / f"iter_{self.iteration + 1:03d}.npz", **data)
        return {**data, "seconds": time.perf_counter() - t0, "label_seconds": t_label, "inert": float(inert.mean())}

    def _update_class_mult(self, cls: np.ndarray, inert: np.ndarray) -> None:
        """Recording multiplier per class for the next iteration: proportional to its measured
        rate of non-inert decisions (smoothed), within [mult_lo, mult_hi]."""
        rate = np.full(native.N_RECORD_CLASSES, np.nan)
        for c in range(native.N_RECORD_CLASSES):
            m = cls == c
            if m.sum() >= 200:
                rate[c] = 1.0 - inert[m].mean()
        overall = 1.0 - inert.mean()
        target = np.where(np.isnan(rate), 1.0, rate / max(overall, 1e-6))
        self.class_mult = np.clip(0.5 * self.class_mult + 0.5 * target, self.cfg.mult_lo, self.cfg.mult_hi)

    def _to_dev(self, data) -> dict:
        return {key: torch.from_numpy(np.ascontiguousarray(data[key])).to(self.dev)
                for key in ("feat", "ids", "q", "w")}

    @staticmethod
    def _split(dev: dict, hold: np.ndarray) -> tuple[dict, dict]:
        """(held-out, training) rows; `hold` marks rows of held-out self-play batches."""
        h = torch.from_numpy(np.flatnonzero(hold)).to(next(iter(dev.values())).device)
        t = torch.from_numpy(np.flatnonzero(hold == 0)).to(h.device)
        return {k: v[h] for k, v in dev.items()}, {k: v[t] for k, v in dev.items()}

    # ------------------------------------------------------------ training
    def _batch(self, D: dict, idx: torch.Tensor):
        mask, tgt = dense(D["ids"][idx], D["q"][idx])
        return _unpack(D["feat"][idx], self.dim), mask, tgt, D["w"][idx].float()

    @staticmethod
    def _adv_terms(pred, mask, tgt, w):
        mf = mask.float() * w[:, None]
        k = mask.float().sum(1, keepdim=True)
        pc = pred - (pred * mask).sum(1, keepdim=True) / k
        tc = tgt - (tgt * mask).sum(1, keepdim=True) / k
        return mf, pc, tc

    def adv_r2(self, H: dict) -> float:
        """Share of the held-out centred-advantage variance the Q net explains (importance-weighted)."""
        self.qnet.eval()
        num = den = 0.0
        with torch.no_grad():
            for i in range(0, len(H["feat"]), 65536):
                sl = torch.arange(i, min(i + 65536, len(H["feat"])), device=self.dev)
                x, mask, tgt, w = self._batch(H, sl)
                mf, pc, tc = self._adv_terms(self.qnet(x), mask, tgt, w)
                num += float((((pc - tc) ** 2) * mf).sum())
                den += float(((tc ** 2) * mf).sum())
        self.qnet.train()
        return 1.0 - num / max(den, 1e-12)

    def train_q(self, D: dict, H: dict) -> tuple[float, float, int]:
        """Trains the Q net, keeping the weights with the best held-out advantage R^2 (every 200 steps)."""
        cfg, n = self.cfg, len(D["feat"])
        losses = []
        best = (self.adv_r2(H), 0, {k: v.detach().clone() for k, v in self.qnet.state_dict().items()})
        for step in range(cfg.q_steps):
            idx = torch.randint(0, n, (cfg.batch,), device=self.dev)
            x, mask, tgt, w = self._batch(D, idx)
            pred = self.q_fwd(x)
            mf, pc, tc = self._adv_terms(pred, mask, tgt, w)
            level = (((pred - tgt) ** 2) * mf).sum() / mf.sum()
            adv = (((pc - tc) ** 2) * mf).sum() / mf.sum()
            loss = level + cfg.adv_weight * adv
            self.opt_q.zero_grad(set_to_none=True)
            loss.backward()
            self.opt_q.step()
            if step % 200 == 0:
                losses.append(float(adv.detach()))
            if (step + 1) % 200 == 0:
                r2 = self.adv_r2(H)
                if r2 > best[0]:
                    best = (r2, step + 1, {k: v.detach().clone() for k, v in self.qnet.state_dict().items()})
        self.qnet.load_state_dict(best[2])
        return float(np.mean(losses[-3:])) / SCALE ** 2, best[0], best[1]

    def composite_labels(self, D: dict) -> tuple[torch.Tensor, dict]:
        """argmax_a Q + margin * 1(a = pi_k) for every state of D, and diagnostics."""
        cfg, n = self.cfg, len(D["feat"])
        self.qnet.eval()
        pk = self.policy.to(self.dev).eval()
        labels, changed, show_rows, show_rami_old, show_rami_new = [], 0, 0, 0, 0
        with torch.no_grad():
            for i in range(0, n, 65536):
                sl = torch.arange(i, min(i + 65536, n), device=self.dev)
                x, m, _, _ = self._batch(D, sl)
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
            x, m, _, w = self._batch(D, idx)
            logits = self.p_fwd(x).masked_fill(~m, -1e9)
            ce = torch.nn.functional.cross_entropy(logits, labels[idx], reduction="none")
            loss = (ce * w).sum() / w.sum()
            self.opt_p.zero_grad(set_to_none=True)
            loss.backward()
            self.opt_p.step()
            if step % 200 == 0:
                losses.append(float(loss.detach()))
        return float(np.mean(losses[-3:]))

    # ------------------------------------------------------------ run state
    def save_state(self) -> None:
        qmodel.save(self.policy, self.out / f"policy_{self.iteration:03d}.pt")
        qmodel.save(self.qnet, self.out / "q_latest.pt")
        torch.save({"q": self.opt_q.state_dict(), "p": self.opt_p.state_dict()}, self.out / "optim_latest.pt")
        state = {"iteration": self.iteration, "class_mult": self.class_mult.tolist(), "rng": self.rng.value}
        (self.out / "state.json").write_text(json.dumps(state))

    def resume(self) -> None:
        """Continue a run: the latest policy, Q net, optimisers, recording weights, rng and replay shards."""
        state = json.loads((self.out / "state.json").read_text())
        self.iteration = state["iteration"]
        self.class_mult = np.array(state["class_mult"])
        self.rng = C.c_uint64(state["rng"])
        p = qmodel.load(self.out / f"policy_{self.iteration:03d}.pt", "cpu")
        self.policy.load_state_dict(p.state_dict())
        self.pnet.load_state_dict(p.state_dict())
        self.qnet.load_state_dict(qmodel.load(self.out / "q_latest.pt", "cpu").state_dict())
        opt = torch.load(self.out / "optim_latest.pt", map_location=self.dev, weights_only=False)
        self.opt_q.load_state_dict(opt["q"])
        self.opt_p.load_state_dict(opt["p"])
        for it in range(max(1, self.iteration - self.cfg.replay_iters + 1), self.iteration + 1):
            shard = self.out / "data" / f"iter_{it:03d}.npz"
            if shard.exists():
                raw = np.load(shard)
                d = self._to_dev(raw)
                hold = raw["hold"] if "hold" in raw.files else (np.arange(len(raw["feat"])) < len(raw["feat"]) // 10)
                self.replay.append(self._split(d, hold.astype(np.uint8))[1])

    # ----------------------------------------------------------------- loop
    def evaluate(self, a: native.Mlp, b: native.Mlp) -> tuple[float, float]:
        v = native.duplicate_eval(self.env_eval, a, b, self.cfg.eval_base, self.cfg.ruleset, self.rng)
        return float(v.mean()), float(1.96 * v.std(ddof=1) / np.sqrt(len(v)))

    def iterate(self) -> dict:
        cfg = self.cfg
        t0 = time.perf_counter()
        mlp_k = native.Mlp(self.policy)
        data = self.collect(mlp_k)
        H, train = self._split(self._to_dev(data), data["hold"])  # held out by whole self-play batches
        self.replay.append(train)
        self.replay = self.replay[-cfg.replay_iters:]
        D = {key: torch.cat([r[key] for r in self.replay]) for key in ("feat", "ids", "q", "w")}
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
        vs_ref = self.evaluate(mlp_next, self.ref) if self.ref is not None else None
        self.iteration += 1
        self.save_state()
        row = {"iteration": self.iteration, "states": int(len(data["feat"])), "replay_states": int(len(D["feat"])),
               "vs_clone": vs_clone, "vs_prev": vs_prev, "vs_ref": vs_ref, "adv_mse": adv_mse, "adv_r2": r2,
               "held_out_states": int(len(H["feat"])),
               "q_best_step": q_best_step, "policy_ce": ce, **diag, "inert": data["inert"],
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
    p.add_argument("--resume", action="store_true")
    for field, default in asdict(Config()).items():
        kind = type(default)
        p.add_argument("--" + field.replace("_", "-"), type=(lambda s: s.lower() in ("1", "true")) if kind is bool
                       else kind, default=default)
    a = p.parse_args()
    out = ROOT / "runs" / "selfplay" / a.name
    if a.resume:
        cfg = Config(**json.loads((out / "config.json").read_text()))
    else:
        cfg = Config(**{f: getattr(a, f) for f in asdict(Config())})
        out.mkdir(parents=True, exist_ok=True)
        (out / "config.json").write_text(json.dumps(asdict(cfg), indent=1))
    native.set_rollout_chunk(128)
    torch.set_num_threads(1)
    learner = Learner(cfg, out)
    if a.resume:
        learner.resume()
    t_end = time.time() + 3600 * a.hours
    while time.time() < t_end and learner.iteration < a.iterations:
        print(json.dumps(learner.iterate()), flush=True)


if __name__ == "__main__":
    main()
