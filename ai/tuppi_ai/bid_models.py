"""Readable models of the bot's RAMI/NOLO decision (numpy only).

Each model maps a table of `tuppi_ai.bid_features` to "bid RAMI or not", can
say in words what it does, and serialises to JSON so the rule can be replayed
(`tuppi_ai.rule_bidder`) and shown to a player:

* `Threshold`: one countable score (e.g. HCP) against a threshold per seat;
* `PointCount`: a weighted sum of a few features, fitted to the bot's own
  value of bidding RAMI over NOLO, expressed in HCP-equivalent points and
  rounded to half points, with a threshold per seat;
* `Tree`: a small decision tree (a few yes/no questions).

Fidelity (agreement with the bot) and the equity cost of bidding by the rule
are measured elsewhere; this module only fits and describes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import numpy as np

NAMES_FI = {
    "hcp": "arvopisteet (A4 K3 Q2 J1)", "aces": "ässät", "kings": "kuninkaat", "queens": "rouvat",
    "jacks": "jätkät", "controls": "kontrollit (A=2, K=1)", "honours": "kuvakortit", "top_five": "10-A-kortit",
    "quick_tricks": "pikatikit", "longest": "pisin maa", "second_longest": "toiseksi pisin maa",
    "shortest": "lyhin maa", "voids": "renonssit", "singletons": "singletonit", "doubletons": "dubletonit",
    "balanced": "tasainen jako", "long_suit_points": "pitkän maan pisteet (yli 4 korttia)",
    "low_cards": "pienet kortit (2-4)", "very_low_cards": "hyvin pienet (2-3)", "mid_cards": "keskikortit (5-9)",
    "stoppers": "pysäyttimet", "nolo_safe_suits": "NOLO-turvalliset maat (korkein enintään 7)",
    "high_short_honours": "kuvakortti lyhyessä maassa", "low_short_suits": "lyhyt maa pienillä",
    "red_silent": "punainen 3-9 (RAMI ilman puhetta)", "black_silent": "musta 3-9 (NOLO ilman puhetta)",
    "position": "paikka (0 = etukäsi)", "own_score": "omat pisteet", "opp_score": "vastustajien pisteet",
    "score_diff": "piste-ero", "own_to_target": "omaa matkaa maaliin", "opp_to_target": "vastustajien matkaa maaliin",
    "old_rami_score": "vanhan botin RAMI-pisteet", "old_nolo_score": "vanhan botin NOLO-pisteet",
}


def matrix(rows: list[dict], names: list[str]) -> np.ndarray:
    return np.array([[float(r[n]) for n in names] for r in rows], dtype=np.float64)


def _best_threshold(score: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """The threshold t maximising agreement of (score >= t) with y."""
    order = np.argsort(score)
    s, yy = score[order], y[order]
    # predicting RAMI for everything from index i on
    rami_after = np.concatenate([np.cumsum(yy[::-1])[::-1], [0]])
    nolo_before = np.concatenate([[0], np.cumsum(1 - yy)])
    agree = nolo_before + rami_after
    candidates = np.unique(np.concatenate([[s[0] - 1], s, [s[-1] + 1]]))
    best_t, best_a = candidates[0], -1
    for t in candidates:
        i = int(np.searchsorted(s, t, side="left"))
        if agree[i] > best_a:
            best_a, best_t = agree[i], t
    return float(best_t), float(best_a / len(y))


@dataclass
class Threshold:
    feature: str
    thresholds: dict[int, float] = field(default_factory=dict)  # per position

    kind = "threshold"

    def fit(self, rows, y):
        pos = np.array([r["position"] for r in rows])
        x = matrix(rows, [self.feature])[:, 0]
        for p in range(4):
            m = pos == p
            if m.any():
                self.thresholds[p] = _best_threshold(x[m], y[m])[0]
        return self

    def predict(self, rows) -> np.ndarray:
        return np.array([float(r[self.feature]) >= self.thresholds.get(int(r["position"]), np.inf) for r in rows])

    def describe(self) -> str:
        seats = ", ".join(f"paikka {p + 1}: vähintään {t:g}" for p, t in sorted(self.thresholds.items()))
        return f"RAMI, kun {NAMES_FI.get(self.feature, self.feature)} riittää ({seats})."

    def to_json(self):
        return {"kind": self.kind, "feature": self.feature, "thresholds": self.thresholds}


@dataclass
class PointCount:
    features: list[str]
    weights: dict[str, float] = field(default_factory=dict)  # HCP-equivalent, rounded to 0.5
    thresholds: dict[int, float] = field(default_factory=dict)
    unit: str = "hcp"

    kind = "point_count"

    def fit(self, rows, gap, y, ridge: float = 1e-3):
        """Least squares of the bot's RAMI-minus-NOLO value on the features (with a
        separate intercept per seat), rescaled so one point is one HCP, rounded to
        half points; then the seat thresholds that best match the bot's choices."""
        pos = np.array([int(r["position"]) for r in rows], dtype=int)
        x = matrix(rows, self.features)
        seats = np.eye(4)[pos]
        a = np.hstack([x, seats])
        w = np.linalg.solve(a.T @ a + ridge * np.eye(a.shape[1]), a.T @ gap)
        scale = w[self.features.index(self.unit)] if self.unit in self.features else np.abs(w[:len(self.features)]).max()
        if scale == 0:
            scale = 1.0
        self.weights = {f: float(np.round(2 * w[i] / scale) / 2) for i, f in enumerate(self.features)}
        pts = self.points(rows)
        for p in range(4):
            m = pos == p
            if m.any():
                self.thresholds[p] = _best_threshold(pts[m], y[m])[0]
        return self

    def points(self, rows) -> np.ndarray:
        return matrix(rows, self.features) @ np.array([self.weights[f] for f in self.features])

    def predict(self, rows) -> np.ndarray:
        pts = self.points(rows)
        return np.array([p >= self.thresholds.get(int(r["position"]), np.inf) for p, r in zip(pts, rows)])

    def contributions(self, row: dict) -> list[tuple[str, float]]:
        """Each feature's points for one hand, largest effect first."""
        items = [(f, self.weights[f] * float(row[f])) for f in self.features if self.weights[f]]
        return sorted(items, key=lambda kv: -abs(kv[1]))

    def describe(self) -> str:
        terms = " ".join(f"{'+' if w >= 0 else '−'} {abs(w):g} × {NAMES_FI.get(f, f)}"
                         for f, w in self.weights.items() if w)
        seats = ", ".join(f"paikka {p + 1}: {t:g}" for p, t in sorted(self.thresholds.items()))
        return f"Pisteet = {terms.lstrip('+ ')}. RAMI, kun pisteet ovat vähintään raja ({seats})."

    def explain(self, row: dict) -> str:
        """One hand, in words: the total against its seat's threshold and the main terms."""
        total = float(self.points([row])[0])
        limit = self.thresholds.get(int(row["position"]), float("nan"))
        parts = ", ".join(f"{'+' if v >= 0 else '−'}{abs(v):g} {NAMES_FI.get(f, f)}"
                          for f, v in self.contributions(row)[:4])
        verdict = "RAMI" if total >= limit else "NOLO"
        margin = total - limit
        close = " (tiukka)" if abs(margin) < 1.0 else ""
        return f"{verdict}{close}: {total:g} pistettä, raja {limit:g}; {parts}."

    def to_json(self):
        return {"kind": self.kind, "features": self.features, "weights": self.weights,
                "thresholds": self.thresholds, "unit": self.unit}


@dataclass
class Tree:
    depth: int = 3
    min_leaf: int = 100
    node: dict | None = None

    kind = "tree"

    def fit(self, rows, y, names: list[str]):
        x = matrix(rows, names)
        self.node = self._grow(x, y, names, self.depth)
        return self

    def _grow(self, x, y, names, depth):
        rami = float(y.mean()) if len(y) else 0.0
        leaf = {"leaf": True, "rami": rami >= 0.5, "share": round(rami, 3), "n": int(len(y))}
        if depth == 0 or len(y) < 2 * self.min_leaf or rami in (0.0, 1.0):
            return leaf
        best = None
        base = min(rami, 1 - rami) * len(y)
        for j, name in enumerate(names):
            values = np.unique(np.quantile(x[:, j], np.linspace(0.05, 0.95, 19)))
            for t in values:
                left = x[:, j] < t
                nl, nr = int(left.sum()), int((~left).sum())
                if nl < self.min_leaf or nr < self.min_leaf:
                    continue
                err = min(y[left].mean(), 1 - y[left].mean()) * nl + min(y[~left].mean(), 1 - y[~left].mean()) * nr
                if best is None or err < best[0]:
                    best = (err, name, float(t), left)
        if best is None or best[0] >= base:
            return leaf
        _, name, t, left = best
        return {"leaf": False, "feature": name, "threshold": t,
                "below": self._grow(x[left], y[left], names, depth - 1),
                "above": self._grow(x[~left], y[~left], names, depth - 1)}

    def _decide(self, node, row):
        while not node["leaf"]:
            node = node["below"] if float(row[node["feature"]]) < node["threshold"] else node["above"]
        return node["rami"]

    def predict(self, rows) -> np.ndarray:
        return np.array([self._decide(self.node, r) for r in rows])

    def describe(self, node=None, indent="") -> str:
        node = self.node if node is None else node
        if node["leaf"]:
            return f"{indent}→ {'RAMI' if node['rami'] else 'NOLO'} (botti RAMI {100 * node['share']:.0f} %, n={node['n']})"
        name = NAMES_FI.get(node["feature"], node["feature"])
        return (f"{indent}jos {name} < {node['threshold']:g}:\n{self.describe(node['below'], indent + '  ')}\n"
                f"{indent}muuten:\n{self.describe(node['above'], indent + '  ')}")

    def to_json(self):
        return {"kind": self.kind, "depth": self.depth, "min_leaf": self.min_leaf, "node": self.node}


def from_json(data: dict):
    kind = data["kind"]
    if kind == "threshold":
        return Threshold(data["feature"], {int(k): v for k, v in data["thresholds"].items()})
    if kind == "point_count":
        return PointCount(data["features"], data["weights"], {int(k): v for k, v in data["thresholds"].items()},
                          data.get("unit", "hcp"))
    if kind == "tree":
        return Tree(data["depth"], data["min_leaf"], data["node"])
    raise ValueError(f"unknown model kind {kind}")


def save(model, path) -> None:
    with open(path, "w") as fh:
        json.dump(model.to_json(), fh, indent=1)


def load(path):
    with open(path) as fh:
        return from_json(json.load(fh))
