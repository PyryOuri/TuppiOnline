# Source index

Generated from the ending inventory completed **2026-10-02T07:50:30.502331+00:00**. Navigation covers selected source trees; it does not imply every file was manually reviewed. Line numbers belong to that inventory and may drift with later work.

[Main report](REPORT.md) · [Architecture](ARCHITECTURE.md) · [Methods](METHODS_AND_EVIDENCE.md) · [Validation](VALIDATION.md)

The JSON inventories hold every scoped file hash, Python top-level definition, import list, line count and Git identity. Python methods inside classes are not separately enumerated. Docstring flags are a navigation aid, not a documentation-quality score. Generated data, models, archives, caches and symlink targets are excluded; native research source copies and duplicated worktrees remain included.

## Checkout inventory

| Root | Files | Python | C / headers | Swift | Markdown |
|---|---:|---:|---:|---:|---:|
| `AGENTS.md` | 1 | 0 | 0 / 0 | 0 | 1 |
| `README.md` | 1 | 0 | 0 / 0 | 0 | 1 |
| `TuppiAI` | 177 | 123 | 23 / 9 | 0 | 16 |
| `TuppiAI-perf` | 81 | 56 | 7 / 2 | 0 | 11 |
| `TuppiAI-prior` | 125 | 93 | 7 / 3 | 0 | 17 |
| `TuppiAI-sp` | 96 | 67 | 7 / 3 | 0 | 14 |
| `TuppiAI-vn` | 88 | 62 | 7 / 2 | 0 | 12 |
| `TuppiClient` | 46 | 0 | 0 / 0 | 41 | 4 |
| `TuppiClient-current` | 54 | 0 | 0 / 0 | 49 | 4 |
| `TuppiProject` | 585 | 435 | 0 / 0 | 0 | 148 |
| `TuppiProject-current` | 548 | 404 | 0 / 0 | 0 | 142 |
| `audit_deliverables` | 5 | 4 | 0 / 0 | 0 | 1 |
| `start_tuppi_server.sh` | 1 | 0 | 0 / 0 | 0 | 0 |
| `tuppi_execution_12h` | 29 | 23 | 0 / 0 | 0 | 4 |
| `tuppi_execution_sampler_v1` | 35 | 19 | 8 / 4 | 0 | 2 |
| `tuppi_execution_v2` | 22 | 9 | 0 / 0 | 0 | 12 |
| `tuppi_execution_v2_output` | 14 | 12 | 0 / 0 | 0 | 2 |

1,908 scoped files; 1,021 distinct content hashes; 622 repeated-content groups. These are file-level counts, not independently maintained implementations or semantic duplication measurements.

## Current AI modules

Paths identify implementation locations. The architecture guide supplies their roles.

| Module | Top-level definitions and source lines |
|---|---|
| [__init__.py](../../TuppiAI/tuppi_ai/__init__.py) | package/constants/imports |
| [agent.py](../../TuppiAI/tuppi_ai/agent.py) | `LearnedAgent`:18 |
| [bc.py](../../TuppiAI/tuppi_ai/bc.py) | `load`:24, `batch`:32, `main`:38 |
| [belief.py](../../TuppiAI/tuppi_ai/belief.py) | `BeliefNet`:28, `load`:43, `main`:50 |
| [best.py](../../TuppiAI/tuppi_ai/best.py) | `best_agents`:76 |
| [bid_features.py](../../TuppiAI/tuppi_ai/bid_features.py) | `_rank`:21, `_quick_tricks`:26, `_stopper`:42, `bid_features`:58 |
| [bid_models.py](../../TuppiAI/tuppi_ai/bid_models.py) | `matrix`:40, `_best_threshold`:44, `Threshold`:62, `PointCount`:89, `Tree`:152, `from_json`:208, `save`:220; +1 more |
| [branch_eval.py](../../TuppiAI/tuppi_ai/branch_eval.py) | `_init`:52, `_reset_sooli`:68, `_value`:74, `_finish`:80, `_game`:92, `measure`:125, `evaluate`:149; +1 more |
| [bridge.py](../../TuppiAI/tuppi_ai/bridge.py) | `mask_of`:31, `action_id`:38, `engine_action`:50, `obs_from_player_observation`:62 |
| [bsearch.py](../../TuppiAI/tuppi_ai/bsearch.py) | `BatchedSearch`:35, `main`:121 |
| [distill.py](../../TuppiAI/tuppi_ai/distill.py) | `load_search`:25, `main`:35 |
| [equity.py](../../TuppiAI/tuppi_ai/equity.py) | `DealModel`:23, `_outcomes`:53, `solve`:60, `native_table`:95, `Equity`:105 |
| [equivalence.py](../../TuppiAI/tuppi_ai/equivalence.py) | `groups`:18, `equivalent`:51 |
| [evaluate.py](../../TuppiAI/tuppi_ai/evaluate.py) | `_with_sooli`:34, `_init`:42, `_make_candidate`:60, `_score_for`:124, `_play`:134, `measure`:177, `summarise`:203; +2 more |
| [heuristic_rules.py](../../TuppiAI/tuppi_ai/heuristic_rules.py) | `suit`:14, `suit_cards`:18, `certain_winner`:22, `underlead_unsupported_honour`:27, `cash_singleton_winner`:39, `cash_singleton_winner_late`:51, `_trick`:55; +7 more |
| [heuristic_variants.py](../../TuppiAI/tuppi_ai/heuristic_variants.py) | `variant_profile`:24, `variant_agents`:36, `_show_id`:52, `_best_show`:58, `LayeredAgent`:64, `parse_spec`:107, `spec_agents`:122 |
| [incumbent.py](../../TuppiAI/tuppi_ai/incumbent.py) | `incumbent_agents`:17 |
| [match_eval.py](../../TuppiAI/tuppi_ai/match_eval.py) | `_leg`:31, `measure_pair`:66, `evaluate_matches`:76, `main`:98 |
| [model.py](../../TuppiAI/tuppi_ai/model.py) | `ResBlock`:18, `QNet`:29, `masked_argmax`:45, `save`:49, `load`:54 |
| [native.py](../../TuppiAI/tuppi_ai/native.py) | `TcDeal`:25, `TcObs`:45, `_Absent`:63, `_sym`:78, `feature_dim`:167, `dd_team0_tricks`:171, `history_rows`:176; +29 more |
| [native_eval.py](../../TuppiAI/tuppi_ai/native_eval.py) | `_hands`:26, `_features`:35, `duplicate`:45, `main`:98 |
| [offer_screen.py](../../TuppiAI/tuppi_ai/offer_screen.py) | `train`:33, `_auc`:88, `calibrate`:96, `load`:126, `main`:134 |
| [policies.py](../../TuppiAI/tuppi_ai/policies.py) | `_q`:23, `Greedy`:28, `Conservative`:38, `from_spec`:57, `PolicyAgent`:66 |
| [research/__init__.py](../../TuppiAI/tuppi_ai/research/__init__.py) | package/constants/imports |
| [research/c1_control_variate.py](../../TuppiAI/tuppi_ai/research/c1_control_variate.py) | `suit_ranks`:35, `contested_liability`:41, `liabilities`:56, `proxy_matrix`:68, `GapEstimate`:79, `estimate_gaps`:91, `plain_gaps`:119; +6 more |
| [research/c1_dispatch.py](../../TuppiAI/tuppi_ai/research/c1_dispatch.py) | `C1Config`:50, `eligible`:71, `C1Decision`:85, `C1Candidate`:95 |
| [research/c2_blind_bids.py](../../TuppiAI/tuppi_ai/research/c2_blind_bids.py) | `C2Batch`:42, `ClonePredecessor`:70, `always`:86, `predecessor_seats`:90, `precommit_observation`:94, `with_chosen_shows`:106, `evaluate`:119; +3 more |
| [research/c2_screen.py](../../TuppiAI/tuppi_ai/research/c2_screen.py) | `_argmax`:26, `run`:34, `analyse`:163, `main`:205 |
| [research/c2_stage2.py](../../TuppiAI/tuppi_ai/research/c2_stage2.py) | `_pick`:21, `accepted_worlds`:29, `run`:50, `analyse`:143, `main`:180 |
| [research/c3_kernel.py](../../TuppiAI/tuppi_ai/research/c3_kernel.py) | `Unresolved`:33, `Kernel`:38, `paired_difference`:156, `next_score`:170, `match_kernel`:180, `augmented_states`:210, `reduce_mode`:215; +3 more |
| [research/c3_utility_stop.py](../../TuppiAI/tuppi_ai/research/c3_utility_stop.py) | `UtilityCertificate`:29, `feasible_totals`:35, `deal_score`:42, `deal_utility`:58, `certificate`:68, `certificate_of_deal`:76, `reachable_utilities`:84 |
| [research/c4_exchange.py](../../TuppiAI/tuppi_ai/research/c4_exchange.py) | `IllegalExchangeInput`:36, `_card_index`:40, `ace_low_index`:46, `_context`:52, `_hand_block`:82, `give_features`:91, `receiver_original_hand`:109; +11 more |
| [research/c4_training.py](../../TuppiAI/tuppi_ai/research/c4_training.py) | `ExchangeProblem`:27, `_argmax`:47, `point`:51, `receiver_values`:55, `receiver_best_response`:67, `giver_values`:74, `giver_best_response`:84; +8 more |
| [research/c5_option.py](../../TuppiAI/tuppi_ai/research/c5_option.py) | `KeyCollision`:35, `NodeCapExceeded`:39, `optimise_groups`:46, `Support`:77, `eligible`:85, `_constraints`:93, `_assignments`:116; +11 more |
| [research/c5_screen.py](../../TuppiAI/tuppi_ai/research/c5_screen.py) | `_finish`:25, `_root_utility`:40, `run`:46, `analyse`:158, `main`:201 |
| [research/cli.py](../../TuppiAI/tuppi_ai/research/cli.py) | `protect_check`:34, `validate_manifest`:50, `set_state`:67, `main`:94 |
| [research/clone_policy.py](../../TuppiAI/tuppi_ai/research/clone_policy.py) | `rollout_network`:25, `clone_scores`:33, `preferred`:41, `CloneGreedyAgent`:53 |
| [research/fixtures.py](../../TuppiAI/tuppi_ai/research/fixtures.py) | `card`:45, `codes`:51, `deck_digest`:57, `hands_of`:61, `first_where`:65, `is_show`:69, `RuleAgent`:73; +27 more |
| [research/identity.py](../../TuppiAI/tuppi_ai/research/identity.py) | `accepted_asset`:68, `head_descends_from_audit`:73, `is_research_addition`:91, `sha256_bytes`:95, `sha256_file`:99, `canonical`:107, `digest`:111; +18 more |
| [research/ledger.py](../../TuppiAI/tuppi_ai/research/ledger.py) | `count`:41, `append`:58, `run`:64, `summary`:91, `main`:110 |
| [research/lifecycle.py](../../TuppiAI/tuppi_ai/research/lifecycle.py) | `factory`:40, `_best`:48, `_clone`:56, `_incumbent`:63, `_first_legal`:73, `RandomLegalAgent`:79, `_random_legal`:98; +12 more |
| [research/manifests.py](../../TuppiAI/tuppi_ai/research/manifests.py) | `_template`:23, `source_hashes`:28, `build_ids`:39, `c1_manifest`:47, `write`:128, `mechanism_manifest`:141 |
| [research/measure_branch_fraction.py](../../TuppiAI/tuppi_ai/research/measure_branch_fraction.py) | `classify`:23, `Timed`:47, `ForcedNolo`:65, `run`:79, `analyse`:117, `main`:174 |
| [research/native_api.py](../../TuppiAI/tuppi_ai/research/native_api.py) | `NativeOwnershipError`:60, `NativeCallError`:64, `bind_native`:70, `native_module`:108, `OwnedEnv`:115, `OwnedMlp`:131, `WorldEvaluation`:144; +6 more |
| [research/observation.py](../../TuppiAI/tuppi_ai/research/observation.py) | `ObservationCodecError`:39, `_card`:43, `_int`:54, `_opt_int`:60, `_restore_show`:64, `_plays`:86, `_tricks`:97; +10 more |
| [research/parity.py](../../TuppiAI/tuppi_ai/research/parity.py) | `_probe`:26, `build_cases`:37, `compare`:107, `main`:170, `chunk_check`:193 |
| [research/probe.py](../../TuppiAI/tuppi_ai/research/probe.py) | `_hex`:29, `run`:35, `main`:122 |
| [research/records.py](../../TuppiAI/tuppi_ai/research/records.py) | `SplitLeakError`:25, `TruthLeakError`:29, `parent_deal_id`:33, `DecisionCase`:39, `OfflineTruth`:76, `TruthStore`:99, `visible_card_codes`:118; +6 more |
| [research/runner_v3.py](../../TuppiAI/tuppi_ai/research/runner_v3.py) | `score_weights`:52, `draw_score`:63, `PolicyFamily`:81, `DealOutcome`:101, `new_match`:111, `play_deal`:119, `_equity`:160; +6 more |
| [research/statistics.py](../../TuppiAI/tuppi_ai/research/statistics.py) | `mean_ci`:28, `cluster_bootstrap`:40, `bundle_summary`:56, `match_summary`:88, `mse_endpoints`:131, `total_saving_bound`:200, `power_n`:210; +2 more |
| [research/streams.py](../../TuppiAI/tuppi_ai/research/streams.py) | `_check`:26, `stream_seed`:37, `scalar_stream`:44, `numpy_stream`:49, `python_stream`:53, `shuffled_deck`:57, `legacy_deck`:66; +1 more |
| [research/testing.py](../../TuppiAI/tuppi_ai/research/testing.py) | `fixture_case`:6, `tobs_of`:15 |
| [review.py](../../TuppiAI/tuppi_ai/review.py) | `ReviewedDecision`:45, `decision_kind`:56, `DealReviewer`:78, `ServerReviewer`:163 |
| [rule_bidder.py](../../TuppiAI/tuppi_ai/rule_bidder.py) | `features_of`:17, `RuleBidder`:28 |
| [search.py](../../TuppiAI/tuppi_ai/search.py) | `Searcher`:28, `SearchAgent`:263 |
| [selfplay.py](../../TuppiAI/tuppi_ai/selfplay.py) | `Config`:52, `compact_labels`:93, `dense`:99, `inert_rows`:108, `Learner`:117, `main`:465 |
| [sooli_odds.py](../../TuppiAI/tuppi_ai/sooli_odds.py) | `SooliOdds`:38, `_cards`:103 |
| [train.py](../../TuppiAI/tuppi_ai/train.py) | `Replay`:29, `random_legal`:48, `main`:53 |
| [train2.py](../../TuppiAI/tuppi_ai/train2.py) | `AllActionReplay`:43, `main`:61 |
| [value.py](../../TuppiAI/tuppi_ai/value.py) | `VNet`:33, `save`:47, `load`:52, `to_native`:60, `suit_permutations`:66, `generate`:82, `_unpack`:105; +2 more |
| [vrpo.py](../../TuppiAI/tuppi_ai/vrpo.py) | `Config`:53, `Critic`:80, `pack_hidden`:96, `trace`:102, `VRPO`:133, `main`:292 |

## Native source

| File | Lines |
|---|---:|
| [showing_constraints.h](../../TuppiAI/native/showing_constraints.h) | 67 |
| [tuppi_core.c](../../TuppiAI/native/tuppi_core.c) | 450 |
| [tuppi_core.h](../../TuppiAI/native/tuppi_core.h) | 137 |
| [tuppi_dd.c](../../TuppiAI/native/tuppi_dd.c) | 190 |
| [tuppi_env.c](../../TuppiAI/native/tuppi_env.c) | 1,191 |
| [tuppi_mlp.c](../../TuppiAI/native/tuppi_mlp.c) | 214 |
| [tuppi_mlp.h](../../TuppiAI/native/tuppi_mlp.h) | 15 |
| [tuppi_search.c](../../TuppiAI/native/tuppi_search.c) | 625 |
| [tuppi_sooli.c](../../TuppiAI/native/tuppi_sooli.c) | 258 |
| [tuppi_sooli_policy.c](../../TuppiAI/native/tuppi_sooli_policy.c) | 355 |

## Authoritative engine and research packages

Current packages are summarized by their package directory. Legacy-only packages are listed separately to expose approaches absent from the product checkout.

| Package | Python modules | Entry point / definitions |
|---|---:|---|
| `TuppiProject-current/src/tuppi_agents` | 31 | [__init__.py](../../TuppiProject-current/src/tuppi_agents/__init__.py): package/constants/imports |
| `TuppiProject-current/src/tuppi_belief` | 9 | [__init__.py](../../TuppiProject-current/src/tuppi_belief/__init__.py): package/constants/imports |
| `TuppiProject-current/src/tuppi_corpus` | 12 | [__init__.py](../../TuppiProject-current/src/tuppi_corpus/__init__.py): package/constants/imports |
| `TuppiProject-current/src/tuppi_engine` | 17 | [__init__.py](../../TuppiProject-current/src/tuppi_engine/__init__.py): package/constants/imports |
| `TuppiProject-current/src/tuppi_eval` | 17 | [__init__.py](../../TuppiProject-current/src/tuppi_eval/__init__.py): package/constants/imports |
| `TuppiProject-current/src/tuppi_exact` | 11 | [__init__.py](../../TuppiProject-current/src/tuppi_exact/__init__.py): package/constants/imports |
| `TuppiProject-current/src/tuppi_learning` | 8 | [__init__.py](../../TuppiProject-current/src/tuppi_learning/__init__.py): package/constants/imports |
| `TuppiProject-current/src/tuppi_legacy` | 9 | [__init__.py](../../TuppiProject-current/src/tuppi_legacy/__init__.py): package/constants/imports |
| `TuppiProject-current/src/tuppi_match` | 14 | [__init__.py](../../TuppiProject-current/src/tuppi_match/__init__.py): package/constants/imports |
| `TuppiProject-current/src/tuppi_nolo` | 10 | [__init__.py](../../TuppiProject-current/src/tuppi_nolo/__init__.py): package/constants/imports |
| `TuppiProject-current/src/tuppi_research` | 11 | [__init__.py](../../TuppiProject-current/src/tuppi_research/__init__.py): package/constants/imports |
| `TuppiProject-current/src/tuppi_rules` | 10 | [__init__.py](../../TuppiProject-current/src/tuppi_rules/__init__.py): package/constants/imports |
| `TuppiProject-current/src/tuppi_search` | 34 | [__init__.py](../../TuppiProject-current/src/tuppi_search/__init__.py): package/constants/imports |
| `TuppiProject-current/src/tuppi_server` | 16 | [__init__.py](../../TuppiProject-current/src/tuppi_server/__init__.py): package/constants/imports |
| `TuppiProject-current/src/tuppi_ui_fixtures` | 3 | [__init__.py](../../TuppiProject-current/src/tuppi_ui_fixtures/__init__.py): package/constants/imports |
| `TuppiProject/src/tuppi_llm` | 11 | [__init__.py](../../TuppiProject/src/tuppi_llm/__init__.py): package/constants/imports |
| `TuppiProject/src/tuppi_valuation` | 12 | [__init__.py](../../TuppiProject/src/tuppi_valuation/__init__.py): package/constants/imports |

## Prepared infrastructure checkout

Only modules whose content differs from the main AI counterpart are listed here; a difference is not a validated improvement. Use its implementation reports and deferred runtime gates before integration.

| Module | Top-level definitions and source lines |
|---|---|
| [branch_eval.py](../../TuppiAI-prior/tuppi_ai/branch_eval.py) | `_init`:50, `_reset_sooli`:66, `_value`:72, `_finish`:78, `_game`:90, `measure`:123, `evaluate`:147; +1 more |
| [evaluate.py](../../TuppiAI-prior/tuppi_ai/evaluate.py) | `_with_sooli`:35, `_init`:43, `_search_global_settings`:67, `_make_candidate`:77, `_score_for`:147, `_play`:157, `measure`:200; +3 more |
| [experiment_io.py](../../TuppiAI-prior/tuppi_ai/experiment_io.py) | `canonical`:12, `digest`:16, `file_digest`:20, `read_json`:28, `write_json`:43 |
| [experiment_queue.py](../../TuppiAI-prior/tuppi_ai/experiment_queue.py) | `_search_options`:28, `_positive`:71, `_path`:79, `_input`:86, `_spec`:94, `normalize`:151, `_source_inputs`:247; +14 more |
| [experiment_worker.py](../../TuppiAI-prior/tuppi_ai/experiment_worker.py) | `main`:13 |
| [heuristic_rules.py](../../TuppiAI-prior/tuppi_ai/heuristic_rules.py) | `suit`:14, `suit_cards`:18, `certain_winner`:22, `underlead_unsupported_honour`:27, `cash_singleton_winner`:39, `cash_singleton_winner_late`:51, `_trick`:55; +5 more |
| [heuristic_variants.py](../../TuppiAI-prior/tuppi_ai/heuristic_variants.py) | `variant_profile`:18, `variant_agents`:30, `LayeredAgent`:42, `parse_spec`:71, `spec_agents`:84 |
| [incumbent.py](../../TuppiAI-prior/tuppi_ai/incumbent.py) | `incumbent_agents`:8 |
| [match_eval.py](../../TuppiAI-prior/tuppi_ai/match_eval.py) | `_leg`:30, `measure_pair`:65, `evaluate_matches`:74, `main`:90 |
| [match_statistics.py](../../TuppiAI-prior/tuppi_ai/match_statistics.py) | `pair_result`:9, `summarize_pairs`:20 |
| [paired_results.py](../../TuppiAI-prior/tuppi_ai/paired_results.py) | `_number`:18, `validate_result`:24, `compare`:86, `main`:134 |
| [policy_prior.py](../../TuppiAI-prior/tuppi_ai/policy_prior.py) | `_finite_vector`:14, `soft_offsets`:21, `hard_offsets`:32, `action_scores`:43, `select_action`:55 |
| [review.py](../../TuppiAI-prior/tuppi_ai/review.py) | `ReviewedDecision`:38, `decision_kind`:49, `DealReviewer`:71, `ServerReviewer`:147 |
| [search.py](../../TuppiAI-prior/tuppi_ai/search.py) | `Searcher`:29, `SearchAgent`:277 |
| [vrpo.py](../../TuppiAI-prior/tuppi_ai/vrpo.py) | `Config`:54, `_host_stats`:92, `Critic`:97, `pack_hidden`:113, `trace`:119, `VRPO`:150, `main`:359 |

## Current client source

| File | Lines |
|---|---:|
| [TuppiClient/AnalysisModels.swift](../../TuppiClient-current/Sources/TuppiClient/AnalysisModels.swift) | 902 |
| [TuppiClient/AnalysisRepository.swift](../../TuppiClient-current/Sources/TuppiClient/AnalysisRepository.swift) | 38 |
| [TuppiClient/AppSessionModel.swift](../../TuppiClient-current/Sources/TuppiClient/AppSessionModel.swift) | 122 |
| [TuppiClient/CardView.swift](../../TuppiClient-current/Sources/TuppiClient/CardView.swift) | 250 |
| [TuppiClient/ContentView.swift](../../TuppiClient-current/Sources/TuppiClient/ContentView.swift) | 282 |
| [TuppiClient/DealAnalysisWindow.swift](../../TuppiClient-current/Sources/TuppiClient/DealAnalysisWindow.swift) | 1,299 |
| [TuppiClient/DealReplay.swift](../../TuppiClient-current/Sources/TuppiClient/DealReplay.swift) | 252 |
| [TuppiClient/DealReview.swift](../../TuppiClient-current/Sources/TuppiClient/DealReview.swift) | 207 |
| [TuppiClient/DesignSystem.swift](../../TuppiClient-current/Sources/TuppiClient/DesignSystem.swift) | 55 |
| [TuppiClient/FixtureInteractionStore.swift](../../TuppiClient-current/Sources/TuppiClient/FixtureInteractionStore.swift) | 195 |
| [TuppiClient/FixtureRepository.swift](../../TuppiClient-current/Sources/TuppiClient/FixtureRepository.swift) | 106 |
| [TuppiClient/LiveSessionStore.swift](../../TuppiClient-current/Sources/TuppiClient/LiveSessionStore.swift) | 1,104 |
| [TuppiClient/MatchHistoryStore.swift](../../TuppiClient-current/Sources/TuppiClient/MatchHistoryStore.swift) | 432 |
| [TuppiClient/Networking.swift](../../TuppiClient-current/Sources/TuppiClient/Networking.swift) | 348 |
| [TuppiClient/NetworkingModels.swift](../../TuppiClient-current/Sources/TuppiClient/NetworkingModels.swift) | 546 |
| [TuppiClient/OnlineViews.swift](../../TuppiClient-current/Sources/TuppiClient/OnlineViews.swift) | 1,227 |
| [TuppiClient/ProtocolBundleModels.swift](../../TuppiClient-current/Sources/TuppiClient/ProtocolBundleModels.swift) | 294 |
| [TuppiClient/ProtocolModels.swift](../../TuppiClient-current/Sources/TuppiClient/ProtocolModels.swift) | 595 |
| [TuppiClient/ReferencePolicy.swift](../../TuppiClient-current/Sources/TuppiClient/ReferencePolicy.swift) | 43 |
| [TuppiClient/ReplayViews.swift](../../TuppiClient-current/Sources/TuppiClient/ReplayViews.swift) | 1,207 |
| [TuppiClient/RoomCredentials.swift](../../TuppiClient-current/Sources/TuppiClient/RoomCredentials.swift) | 60 |
| [TuppiClient/StartingHandSummary.swift](../../TuppiClient-current/Sources/TuppiClient/StartingHandSummary.swift) | 59 |
| [TuppiClient/TableKeyboardSelection.swift](../../TuppiClient-current/Sources/TuppiClient/TableKeyboardSelection.swift) | 137 |
| [TuppiClient/TableViews.swift](../../TuppiClient-current/Sources/TuppiClient/TableViews.swift) | 1,228 |
| [TuppiClient/TrainingAnalysisModels.swift](../../TuppiClient-current/Sources/TuppiClient/TrainingAnalysisModels.swift) | 360 |
| [TuppiClient/TrainingOverlayView.swift](../../TuppiClient-current/Sources/TuppiClient/TrainingOverlayView.swift) | 381 |
| [TuppiClient/TuppiClientApp.swift](../../TuppiClient-current/Sources/TuppiClient/TuppiClientApp.swift) | 111 |
| [TuppiClient/UISettings.swift](../../TuppiClient-current/Sources/TuppiClient/UISettings.swift) | 214 |

## Research entry points

- [C0–C5 implementation handoff](../TUPPI_IMPLEMENTATION_HANDOFF.md)
- [C0–C5 implementation output](../tuppi_implementation_output/IMPLEMENTATION_REPORT.md)
- [Self-play research packet](../tuppi_selfplay_research_20260929/TUPPI_SELFPLAY_STRENGTH_MAXIMISATION_PACKET.md)
- [Policy-prior infrastructure](../tuppi_policy_prior_infrastructure_20261002/IMPLEMENTATION_REPORT.md)
- [Checked comparisons and queues](../tuppi_experiment_tools_20261002/IMPLEMENTATION_REPORT.md)
- [CVR/JRPL trial entry](../../tuppi_execution_12h/README.md)
- [Corrected-sampler trial](../../tuppi_execution_sampler_v1/README.md)

Regenerate with `python3 -B tools/validate_review.py` from this directory. It reads saved inventories; a later source inventory needs a new filename and an explicit change to this script's snapshot selection.
