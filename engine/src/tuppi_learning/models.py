"""Small observation-only actor and centralized training critic."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Mapping

from tuppi_engine import PlayerObservation

from .encoding import (
    ACTION_ENCODER_VERSION,
    CONTEXT_DIM,
    ENCODER_VERSION,
    PREPROCESSING_VERSION,
    batch_from_observations,
)
from .errors import LearningConfigurationError, LearningDependencyError, ObservationBoundaryError


MODEL_ARCHITECTURE_VERSION = "seat_relative_actor_gru_deepsets_v2"
CRITIC_ARCHITECTURE_VERSION = "centralized_match_critic_mlp_v1"


def _torch_nn() -> tuple[Any, Any]:
    try:
        import torch
        from torch import nn
    except ImportError as exc:  # pragma: no cover - optional dependency path
        raise LearningDependencyError(
            "Phase 6 models require optional 'learning' dependencies"
        ) from exc
    return torch, nn


@dataclass(frozen=True, slots=True)
class ActorConfiguration:
    architecture_version: str = MODEL_ARCHITECTURE_VERSION
    encoder_version: str = ENCODER_VERSION
    action_encoder_version: str = ACTION_ENCODER_VERSION
    preprocessing_version: str = PREPROCESSING_VERSION
    card_embedding_dim: int = 16
    history_hidden_dim: int = 32
    state_dim: int = 128
    context_hidden_dim: int = 32
    inference_rule: str = "greedy_logit_then_engine_action_order_v1"

    def __post_init__(self) -> None:
        expected_versions = {
            "architecture_version": MODEL_ARCHITECTURE_VERSION,
            "encoder_version": ENCODER_VERSION,
            "action_encoder_version": ACTION_ENCODER_VERSION,
            "preprocessing_version": PREPROCESSING_VERSION,
            "inference_rule": "greedy_logit_then_engine_action_order_v1",
        }
        for label, expected in expected_versions.items():
            if getattr(self, label) != expected:
                raise LearningConfigurationError(
                    f"unsupported {label}: expected {expected}"
                )
        for label in ("card_embedding_dim", "history_hidden_dim", "state_dim", "context_hidden_dim"):
            value = getattr(self, label)
            if type(value) is not int or value <= 0:
                raise LearningConfigurationError(f"{label} must be a positive integer")

    def to_data(self) -> dict[str, object]:
        return {
            "action_encoder_version": self.action_encoder_version,
            "architecture_version": self.architecture_version,
            "card_embedding_dim": self.card_embedding_dim,
            "context_hidden_dim": self.context_hidden_dim,
            "encoder_version": self.encoder_version,
            "history_hidden_dim": self.history_hidden_dim,
            "inference_rule": self.inference_rule,
            "preprocessing_version": self.preprocessing_version,
            "state_dim": self.state_dim,
        }

    @property
    def configuration_id(self) -> str:
        payload = json.dumps(self.to_data(), sort_keys=True, separators=(",", ":")).encode()
        return "learncfg:sha256:" + hashlib.sha256(payload).hexdigest()


def _make_actor_class():
    try:
        torch, nn = _torch_nn()
    except LearningDependencyError:
        return None

    class SeatRelativeActor(nn.Module):
        """One shared legal-action policy for all physical seats."""

        def __init__(self, configuration: ActorConfiguration | None = None) -> None:
            super().__init__()
            self.configuration = configuration or ActorConfiguration()
            cfg = self.configuration
            card_dim = cfg.card_embedding_dim
            self.card_embedding = nn.Embedding(53, card_dim, padding_idx=52)
            self.role_embedding = nn.Embedding(4, 4)
            self.kind_embedding = nn.Embedding(3, 4)
            self.contract_history_embedding = nn.Embedding(3, 4)
            self.position_embedding = nn.Embedding(5, 4)
            self.winner_history_embedding = nn.Embedding(4, 4)
            self.history_gru = nn.GRU(card_dim + 4 + 4 + 4 + 4 + 4, cfg.history_hidden_dim, batch_first=True)
            self.context_encoder = nn.Sequential(
                nn.Linear(CONTEXT_DIM, cfg.context_hidden_dim),
                nn.Tanh(),
            )
            self.state_projection = nn.Sequential(
                nn.Linear(card_dim + cfg.history_hidden_dim + card_dim + cfg.context_hidden_dim, cfg.state_dim),
                nn.ReLU(),
                nn.Linear(cfg.state_dim, cfg.state_dim),
            )
            self.action_kind_embedding = nn.Embedding(3, 8)
            self.action_contract_embedding = nn.Embedding(3, 8)
            self.action_projection = nn.Sequential(
                nn.Linear(card_dim + 8 + 8, cfg.state_dim),
                nn.Tanh(),
            )
            self.scale = float(cfg.state_dim) ** -0.5

        def _pool_cards(self, cards):
            mask = (cards != 52).unsqueeze(-1)
            values = self.card_embedding(cards) * mask
            return values.sum(dim=1) / mask.sum(dim=1).clamp_min(1).to(values.dtype)

        def _state(self, batch: Mapping[str, Any]):
            own = self._pool_cards(batch["hand"])
            history = self.card_embedding(batch["history_cards"])
            history = torch.cat(
                (
                    history,
                    self.role_embedding(batch["history_roles"]),
                    self.kind_embedding(batch["history_kinds"]),
                    self.contract_history_embedding(batch["history_contracts"]),
                    self.position_embedding(batch["history_positions"]),
                    self.winner_history_embedding(batch["history_winners"]),
                ),
                dim=-1,
            )
            lengths = batch["history_lengths"]
            # Padding is zeroed and excluded from the recurrent state.  A
            # length of one is used for the all-padding showing-prefix case,
            # then its state is explicitly cleared below.
            packed_lengths = lengths.clamp_min(1).cpu()
            packed = torch.nn.utils.rnn.pack_padded_sequence(
                history,
                packed_lengths,
                batch_first=True,
                enforce_sorted=False,
            )
            _, hidden = self.history_gru(packed)
            history_state = hidden[-1]
            history_state = history_state * (lengths > 0).unsqueeze(-1).to(history_state.dtype)
            current = self._pool_cards(batch["current_cards"])
            context = self.context_encoder(batch["context"])
            return self.state_projection(torch.cat((own, history_state, current, context), dim=-1))

        def forward(self, batch: Mapping[str, Any]):
            state = self._state(batch)
            action_cards = self.card_embedding(batch["legal_cards"])
            actions = torch.cat(
                (
                    action_cards,
                    self.action_kind_embedding(batch["legal_kinds"]),
                    self.action_contract_embedding(batch["legal_contracts"]),
                ),
                dim=-1,
            )
            actions = self.action_projection(actions)
            logits = (actions * state.unsqueeze(1)).sum(dim=-1) * self.scale
            return logits.masked_fill(~batch["legal_mask"], torch.finfo(logits.dtype).min)

        def log_probs(self, batch: Mapping[str, Any]):
            return torch.log_softmax(self.forward(batch), dim=-1)

        def greedy_indices(self, batch: Mapping[str, Any]):
            return self.forward(batch).argmax(dim=-1)

        @property
        def parameter_count(self) -> int:
            return sum(parameter.numel() for parameter in self.parameters())

    return SeatRelativeActor


_ACTOR_CLASS = _make_actor_class()


def SeatRelativeActor(configuration: ActorConfiguration | None = None):
    """Construct the optional torch actor without importing torch eagerly."""

    if _ACTOR_CLASS is None:
        raise LearningDependencyError("PyTorch is required to construct the actor")
    return _ACTOR_CLASS(configuration)


class ObservationOnlyActor:
    """Strict deployment adapter around a trained actor module."""

    def __init__(self, module: Any, *, device: str = "cpu") -> None:
        if _ACTOR_CLASS is None or not isinstance(module, _ACTOR_CLASS):
            raise ObservationBoundaryError("deployment actor must be a SeatRelativeActor")
        self.module = module
        self.device = device
        self.module.to(device)
        self.module.eval()

    @property
    def identity(self) -> str:
        return self.module.configuration.configuration_id

    def logits(self, observation):
        if not isinstance(observation, PlayerObservation):
            raise ObservationBoundaryError("deployment actor accepts only PlayerObservation")
        import torch
        batch = batch_from_observations((observation,), device=self.device)
        with torch.no_grad():
            return self.module(batch)[0]

    def choose_action(self, observation):
        logits = self.logits(observation)
        index = int(logits.argmax().item())
        return observation.legal_actions[index]


def _make_critic_class():
    try:
        _torch, nn = _torch_nn()
    except LearningDependencyError:
        return None

    class CentralizedCritic(nn.Module):
        """Training-only value model; never accepted by ``ObservationOnlyActor``."""

        def __init__(self, input_dim: int = 128) -> None:
            super().__init__()
            self.input_dim = input_dim
            self.network = nn.Sequential(
                nn.Linear(input_dim, 128),
                nn.Tanh(),
                nn.Linear(128, 64),
                nn.Tanh(),
                nn.Linear(64, 1),
                nn.Tanh(),
            )

        def forward(self, private_features):
            return self.network(private_features).squeeze(-1)

    return CentralizedCritic


_CRITIC_CLASS = _make_critic_class()


def CentralizedCritic(input_dim: int = 128):
    if _CRITIC_CLASS is None:
        raise LearningDependencyError("PyTorch is required to construct the critic")
    return _CRITIC_CLASS(input_dim)


def actor_parameter_count(configuration: ActorConfiguration | None = None) -> int:
    return int(SeatRelativeActor(configuration).parameter_count)
