// Native Tuppi core for project_target_v1.
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
#ifndef TUPPI_CORE_H
#define TUPPI_CORE_H

#include <stdint.h>

#define TC_NOLO 0
#define TC_RAMI 1
#define TC_PH_SHOW 0
#define TC_PH_PLAY 1
#define TC_PH_DONE 2
#define TC_NUM_ACTIONS 156
#define TC_TARGET 52

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
} TcObs;

void tc_deal_init(TcDeal *d, const uint64_t hands[4], int dealer, int score0, int score1);
// Legal action ids for the current actor; returns the count.
int tc_legal(const TcDeal *d, int *actions);
// Applies an action for the current actor. Returns 0, or -1 if illegal.
int tc_apply(TcDeal *d, int action);
// Rising-score transition. Returns 1 if the match is over.
int tc_next_score(const uint8_t score[2], int winner_team, int points, uint8_t out[2]);

// Ends a deal with the given final team-0 trick count (for solver tails).
void tc_finish_with_tricks(TcDeal *d, int team0_tricks);
int tc_dd_team0_tricks(const TcDeal *d);

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
