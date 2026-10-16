// Research-only native API (tuppi_ai.research.native_api).
//
// Built only into libtuppi_research.dylib by native/research/build_research.sh,
// in the same translation unit as the overlay-patched copy of tuppi_env.c. The
// installed native/libtuppi.dylib and every original tc_* entrypoint are
// unchanged. Buffers belong to the caller; every buffer is passed with its
// capacity and nothing is written past it.
#ifndef TUPPI_RESEARCH_API_H
#define TUPPI_RESEARCH_API_H

#include <stdint.h>

#include "tuppi_core.h"

#define RESEARCH_API_VERSION 3  // 2: options + C3b exports; 3: observation validation, stricter worlds
#define RESEARCH_MAX_WORLDS 4096

// Return codes. -1..-3 keep the original search_core meanings.
#define RESEARCH_OK 0
#define RESEARCH_NO_WORLD (-1)        // the sampler found no world
#define RESEARCH_ENV_TOO_SMALL (-2)   // w * k exceeds the environment's slots
#define RESEARCH_BAD_ACTION (-3)      // a candidate action is illegal in some world
#define RESEARCH_BAD_DIMS (-4)        // w, k, dd_left or a capacity out of range / overflow
#define RESEARCH_WORLD_MISMATCH (-5)  // a supplied world disagrees with the observation
#define RESEARCH_NONFINITE (-6)       // a value is not finite
#define RESEARCH_NULL (-7)            // a required pointer is NULL
#define RESEARCH_BAD_OBS (-8)         // the observation fails its range/consistency checks

// Row status bits (per rollout slot wi * k + ai), as in overlay.patch.
#define RESEARCH_RS_RECORDED 1
#define RESEARCH_RS_SOOLI_ILLEGAL 2
#define RESEARCH_RS_DOUBLE 4
#define RESEARCH_RS_CERTIFIED 8

// Research switches (options). 0 is the original computation.
#define RESEARCH_OPT_UTILITY_STOP 1  // C3b

// Work counters (int64_t work[8]).
#define RESEARCH_RW_FIRST 0
#define RESEARCH_RW_SOOLI 1
#define RESEARCH_RW_DD 2
#define RESEARCH_RW_MLP_ROWS 3
#define RESEARCH_RW_MLP_BATCHES 4
#define RESEARCH_RW_PLIES 5
#define RESEARCH_RW_ROUNDS 6
#define RESEARCH_RW_CERTIFIED 7
#define RESEARCH_WORK_SLOTS 8

// Controller configuration record (research_env_config / _import_config).
#define RESEARCH_CFG_VERSION 1
#define RESEARCH_CFG_LEN 62  // version, n, encoder, single_deal, p_random_start, belief, return_pi,
                             // play_heur, lambda, rollout_chunk, slot digest hi32, lo32, eq[25][2]

int research_api_version(void);

// Sizes and field offsets of TcDeal and TcObs, and an endianness probe, for
// the Python side to compare with its ctypes layout. Returns the count
// written, or RESEARCH_BAD_DIMS if cap is too small.
int research_abi_layout(int64_t *out, int cap);

// 0 if `world` is a complete deal state consistent with observation `o` for
// its actor: a valid observation, same projection, the observer to act (and
// `cur` equal to the actor implied by the history), trick totals recomputed
// from the history, a card partition, per-phase hand sizes, voids, unplayed
// shown cards with their shower (outside sooli), and during showing every bid
// (hidden or not) legal from its bidder's hand in bidding order. Otherwise a
// positive reason code (see research_api.c).
int research_obs_valid(const TcObs *o);
int research_world_consistent(const TcObs *o, const TcDeal *world);

// The environment's search configuration. research_env_import_config writes
// the mutable fields (encoder, options, sooli settings, equity) and refuses a
// record from an environment of a different size.
int research_env_config(const void *env, double *out, int cap);
int research_env_import_config(void *env, const double *cfg, int len);
int research_get_rollout_chunk(void);

// The first `w` root worlds exactly as tc_search_values would draw them with
// this environment's sooli settings, advancing *rng identically, but without
// any rollout. Returns 0 or RESEARCH_NO_WORLD (*drawn tells how many).
int research_sample_worlds(const void *env, const TcObs *o, int w, uint64_t *rng, TcDeal *out, int out_cap,
                           int *drawn);

// tc_search_world_values, plus the root worlds it drew, per-rollout status
// and work counters. Same values, same rng advancement.
// per_world and row_status (each optional) hold cell_cap entries, at least w * k.
int research_trace_search(void *env, const void *mlp, const TcObs *o, const int32_t *actions, int k, int w,
                          int dd_left, int options, uint64_t *rng, double *values, double *per_world,
                          uint8_t *row_status, int cell_cap, TcDeal *worlds_out, int worlds_cap, int64_t *work);

// The continuation of tc_search_world_values on caller-supplied root worlds:
// never samples a root world. *cont_rng is the continuation stream (only a
// rollout that reaches a sooli draws from it). On a world/observation
// mismatch *bad_world is its index.
int research_evaluate_worlds(void *env, const void *mlp, const TcObs *o, const TcDeal *worlds, int w,
                             const int32_t *actions, int k, int dd_left, int options, uint64_t *cont_rng,
                             double *values, double *per_world, uint8_t *row_status, int cell_cap, int64_t *work,
                             int *bad_world);

// C3b pieces, exposed for exact tests: the row utility record_if_done would add
// for a deal finished with `team0_tricks`, and the certificate itself.
int research_row_utility(const void *env, const TcDeal *d, int team0_tricks, float *out);
int research_utility_certificate(const void *env, const TcDeal *d, float *out);

#endif
