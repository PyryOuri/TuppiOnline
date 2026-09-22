"""Q-network: observation features -> one value per action id (156).

Outputs 0..51 are card plays and 52..155 are (contract, card) shows. The value
is the acting team's expected match-equity change over the current deal, in
units of `RETURN_SCALE` x equity.
"""

from __future__ import annotations

import torch
from torch import nn

from .native import FEATURE_DIM, NUM_ACTIONS

RETURN_SCALE = 10.0


class ResBlock(nn.Module):
    def __init__(self, width: int):
        super().__init__()
        self.norm = nn.LayerNorm(width)
        self.fc1 = nn.Linear(width, width)
        self.fc2 = nn.Linear(width, width)

    def forward(self, x):
        return x + self.fc2(torch.relu(self.fc1(self.norm(x))))


class QNet(nn.Module):
    def __init__(self, width: int = 768, blocks: int = 4):
        super().__init__()
        self.config = {"width": width, "blocks": blocks}
        self.inp = nn.Linear(FEATURE_DIM, width)
        self.blocks = nn.Sequential(*[ResBlock(width) for _ in range(blocks)])
        self.norm = nn.LayerNorm(width)
        self.out = nn.Linear(width, NUM_ACTIONS)

    def forward(self, x):
        h = torch.relu(self.inp(x.float()))
        h = self.blocks(h)
        return self.out(torch.relu(self.norm(h)))


def masked_argmax(q: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    return q.masked_fill(mask == 0, float("-inf")).argmax(dim=1)


def save(net: QNet, path, **extra) -> None:
    state = {k: v.detach().cpu() for k, v in net.state_dict().items()}
    torch.save({"config": net.config, "state": state, **extra}, path)


def load(path, device="cpu") -> QNet:
    blob = torch.load(path, map_location=device, weights_only=False)
    net = QNet(**blob["config"])
    net.load_state_dict(blob["state"])
    net.to(device).eval()
    return net
