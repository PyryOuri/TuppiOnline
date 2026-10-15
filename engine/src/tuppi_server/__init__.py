"""Minimal in-memory online server boundary for the native Tuppi client."""

from .deal_generation import generate_live_deal
from .analysis import (
    AGENT_DIAGNOSTICS_SCHEMA_VERSION,
    AnalysisProjectionError,
    COMPLETED_DEAL_BOT_REPLAY_SCHEMA_VERSION,
    COMPLETED_DEAL_DIAGNOSTICS_SCHEMA_VERSION,
    COMPLETED_DEAL_REVIEW_SCHEMA_VERSION,
    POST_MATCH_ANALYSIS_SCHEMA_VERSION,
    POST_MATCH_DIAGNOSTICS_SCHEMA_VERSION,
    POST_MATCH_REVIEW_SCHEMA_VERSION,
    VERDICT_NOTES,
    RecordedDecisionAnalysis,
    project_post_match_analysis,
    project_post_match_analysis_response,
    validate_post_match_analysis_response,
    validate_completed_deal_analysis_response,
)
from .match_runner import LiveMatchRunner
from .post_match_diagnostics import (
    HistoricalDecision,
    generate_completed_deal_diagnostics,
    generate_post_match_diagnostics,
    reconstruct_historical_decisions,
)
from .persistence import (
    POST_MATCH_ANALYSIS_RECORD_SCHEMA_VERSION,
    FileRoomStore,
    PersistenceError,
)
from .projection import (
    project_event_batch,
    project_completed_deals,
    project_match_result,
    project_observation,
)
from .rooms import RoomManager

__all__ = (
    "LiveMatchRunner",
    "AGENT_DIAGNOSTICS_SCHEMA_VERSION",
    "AnalysisProjectionError",
    "COMPLETED_DEAL_BOT_REPLAY_SCHEMA_VERSION",
    "COMPLETED_DEAL_DIAGNOSTICS_SCHEMA_VERSION",
    "COMPLETED_DEAL_REVIEW_SCHEMA_VERSION",
    "FileRoomStore",
    "POST_MATCH_ANALYSIS_RECORD_SCHEMA_VERSION",
    "POST_MATCH_ANALYSIS_SCHEMA_VERSION",
    "POST_MATCH_DIAGNOSTICS_SCHEMA_VERSION",
    "POST_MATCH_REVIEW_SCHEMA_VERSION",
    "VERDICT_NOTES",
    "PersistenceError",
    "RecordedDecisionAnalysis",
    "RoomManager",
    "HistoricalDecision",
    "generate_live_deal",
    "generate_completed_deal_diagnostics",
    "generate_post_match_diagnostics",
    "project_post_match_analysis",
    "project_post_match_analysis_response",
    "validate_post_match_analysis_response",
    "validate_completed_deal_analysis_response",
    "reconstruct_historical_decisions",
    "project_event_batch",
    "project_completed_deals",
    "project_match_result",
    "project_observation",
)
