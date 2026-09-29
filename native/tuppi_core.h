// Native Tuppi core for project_target_v1 and project_target_v2 (v1 + sooli).
//
// The Python package tuppi_rules in TuppiProject is the authoritative
// reference; this core is a fast re-implementation that is differential-tested
// against it (tests/test_differential.py). Nothing here is a second source of
// truth: a disagreement is a bug in this file.
//
// Card index: suit * 13 + (rank - 2), suits hearts, diamonds, clubs, spades
// (the project's project_target_v1_suit_major_hdcs_rank_2_to_ace encoding).
//
// Action ids: 0..51 play that card; 52 + 52 * contract + card shows that card
// with that contract (contract 0 = NOLO, 1 = RAMI). NUM_ACTIONS = 156.
// project_target_v2 adds 156 decline sooli, 157 accept sooli and 158 + card
// exchange that card (give or return); these never reach a network head.
#ifndef TUPPI_CORE_H
#define TUPPI_CORE_H

#include <stdint.h>

#define TC_NOLO 0
#define TC_RAMI 1
#define TC_PH_SHOW 0
#define TC_PH_PLAY 1
#define TC_PH_DONE 2
// Rulesets: 1 = project_target_v1, 2 = v1 + sooli, 3 = v2 + locked bids
// (during showing no seat sees another's bid; only how many were taken).
#define TC_LOCKED(o) ((o)->ruleset == 3 && (o)->phase == TC_PH_SHOW)
// project_target_v2 (sooli)
#define TC_PH_SOOLI_OFFER 3
#define TC_PH_SOOLI_GIVE 4
#define TC_PH_SOOLI_RETURN 5
#define TC_PH_SOOLI_PLAY 6
// Network heads and legal masks cover action ids 0..155 (plays and shows).
#define TC_NUM_ACTIONS 156
// v2 action ids outside the network head: sooli answers and exchanged cards.
#define TC_ACT_SOOLI_DECLINE 156
#define TC_ACT_SOOLI_ACCEPT 157
#define TC_ACT_EXCHANGE 158   // + card
#define TC_NUM_ACTIONS_V2 210
#define TC_TARGET 52
#define TC_SOOLI_POINTS 24

typedef struct {
  uint64_t hand[4];
  uint8_t dealer, phase, cur;
  uint8_t n_shows;
  uint8_t show_seat[4], show_card[4], show_contract[4], show_verbal[4];
  int8_t contract, declarer;
  uint8_t first_leader;
  uint8_t n_played;
  uint8_t play_card[52], play_seat[52];
  uint8_t team_tricks[2];
  uint8_t score[2];  // match score when this deal started
  // Filled when phase becomes DONE.
  int8_t winner_team;
  uint8_t points;
  uint8_t stolen;
  // project_target_v2 (sooli). v1 deals keep the defaults set by tc_deal_init.
  uint8_t ruleset;          // 1 or 2
  uint8_t trick_size;       // 4, or 3 once sooli play starts
  uint8_t n_decisions;
  uint8_t decision_seat[2], decision_accept[2];
  int8_t soolaaja;          // -1 when no sooli
  int8_t given, returned;   // exchanged cards, -1 until exchanged
  uint8_t sooli_won;        // DONE sooli deals: 1 if the soolaaja took no trick
} TcDeal;

// A player's legal view: own hand plus public history. Built either by
// projecting a TcDeal (tc_observe) or from an engine PlayerObservation on the
// Python side. The encoder reads nothing else, so it cannot see hidden cards.
typedef struct {
  uint64_t hand;
  uint8_t seat, dealer, phase;
  uint8_t n_shows;
  uint8_t show_seat[4], show_card[4], show_contract[4], show_verbal[4];
  int8_t contract, declarer;
  uint8_t first_leader;
  uint8_t n_played;
  uint8_t play_card[52], play_seat[52];
  uint8_t score[2];
  // project_target_v2 (sooli). The exchanged cards are known only to the
  // soolaaja and the partner; everyone else sees -1.
  uint8_t ruleset, trick_size, n_decisions;
  uint8_t decision_seat[2], decision_accept[2];
  int8_t soolaaja, known_given, known_returned;
} TcObs;

void tc_deal_init(TcDeal *d, const uint64_t hands[4], int dealer, int score0, int score1);
void tc_deal_init_v(TcDeal *d, const uint64_t hands[4], int dealer, int score0, int score1, int ruleset);
// Ace-low rank used in sooli trick play (A=0, 2=1, ..., K=12).
int tc_sooli_rank(int card);
void tc_struct_sizes(int *out);
// Legal action ids for the current actor; returns the count.
int tc_legal(const TcDeal *d, int *actions);
// Applies an action for the current actor. Returns 0, or -1 if illegal.
int tc_apply(TcDeal *d, int action);
// Rising-score transition. Returns 1 if the match is over.
int tc_next_score(const uint8_t score[2], int winner_team, int points, uint8_t out[2]);

// Sooli perfect-information solver (tuppi_sooli.c). tc_sooli_solve returns 1
// if the soolaaja survives the rest of the deal, 0 if the RAMI pair can force
// a trick on them, -1 outside sooli play.
int tc_sooli_solve(const TcDeal *d);
int tc_sooli_solve_budget(const TcDeal *d, long budget);  // -2 if the budget ran out
int tc_sooli_move_values(const TcDeal *d, const int *actions, int k, int *out);
void tc_sooli_finish(TcDeal *d);
long tc_sooli_nodes(void);
// Observation-only sooli heuristics (tuppi_sooli_policy.c): an action for the
// observer in a sooli phase, -1 otherwise.
int tc_sooli_policy(const TcObs *o, uint64_t *rng);
int tc_sooli_offer_prefilter(uint64_t hand);
int tc_sample_world_sooli(const TcObs *o, uint64_t *rng, TcDeal *out, int mode, double lambda);
void tc_set_rollout_chunk(int chunk);
int tc_sample_world_tilted(const TcObs *o, uint64_t *rng, TcDeal *out, double lambda);

// Ends a deal with the given final team-0 trick count (for solver tails).
void tc_finish_with_tricks(TcDeal *d, int team0_tricks);
int tc_dd_team0_tricks(const TcDeal *d);

// Full-information features of a trick-boundary position for the value net
// (tuppi_env.c; docs/VALUE_NET_PLAN.md), from the side of the seat to move.
int tc_pi_feature_dim(void);
void tc_encode_pi(const TcDeal *d, int bot_side, uint8_t *out);

void tc_observe(const TcDeal *d, int seat, TcObs *o);
int tc_legal_obs(const TcObs *o, int *actions);
int tc_feature_dim(void);
// Every feature is 0 or 1. Version 1 is tc_encode; version 2 appends play order.
void tc_encode(const TcObs *o, uint8_t *out);
int tc_feature_dim_v(int version);
void tc_encode_v(const TcObs *o, uint8_t *out, int version);

// Derived public facts, exposed for tests.
uint64_t tc_valid_show_cards(uint64_t hand, int contract);
int tc_verbal_required(int card, int contract);

#endif
