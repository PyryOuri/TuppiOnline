"""Stable identifiers used by the archival harness."""

ARTIFACT_ID = "legacy_v9_unverified"
ADAPTER_VERSION = "0.1.0"
EMULATOR_RELATIVE_PATH = "Archive/tuppi_emulator_v9.py"
GUI_RELATIVE_PATH = "Archive/tuppi_gui_client_multi_v8.py"
MANIFEST_RELATIVE_PATH = "manifests/legacy_v9.json"

EMULATOR_SHA256 = "f5d52f2a41d0c1fc2db18fa54f1171355d432d581c6eb6cb18c1298218aa87c9"
GUI_SHA256 = "a926f5a2a7714b82eb7eaa3d4f640ef1676011874cb090712b862c27d63a2558"

CARD_ENCODING = "legacy_v9_integer_0_51_suit_major_rank_2_to_ace"
DEAL_SCHEMA_VERSION = "tuppi.legacy.deal.v1"
DEAL_SET_SCHEMA_VERSION = "tuppi.legacy.deal_set.v1"
RESULT_SCHEMA_VERSION = "tuppi.legacy.result.v1"

DEFAULT_SHOW_BANNED_RANKS = (2, 11, 12, 13)
DEAL_GENERATOR_ID = "sha256_counter_fisher_yates_v1"
AGENT_ID = "legacy_v9.MonteCarloAI"

COMMON_FIDELITY_WARNINGS = (
    "legacy_v9_unverified is an archival behavior identifier, not a validated ruleset.",
    "Legacy gameplay and all PIMC decisions share one adapter-seeded RNG stream.",
    "The materialized deal is injected at the unchanged legacy deck-shuffle boundary.",
    "Legacy presentation output is suppressed; structured data is captured from method boundaries and live state.",
    "The fixed-count adapter calls legacy play_one_hand directly and does not apply the legacy run loop's game-over stop.",
    "The adapter is single-threaded while the frozen module's random binding and stdout are temporarily redirected.",
)
