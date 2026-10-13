// Batched self-play environment: N independent matches stepped in lockstep.
// Every live game always has exactly one actor waiting, so one call observes N
// decisions and one call applies N actions.
#include "tuppi_parallel.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>

#include "tuppi_core.h"

typedef uint64_t u64;

typedef struct {
  TcDeal d;
  u64 rng;
  int32_t deals_in_match;
  int32_t live;
} TcGame;

typedef struct {
  int n;
  TcGame *g;
  double eq[25][2];      // team-0 match equity; [state][team 0 deals this deal]
  double p_random_start; // probability a new match starts from a random score
  int single_deal;       // if set, a finished deal is left finished
  int encoder;           // feature encoder version (1 or 2)
  int sooli_belief;      // tc_sample_world_sooli mode for searches in sooli phases
  int sooli_return_pi;   // rollouts: the partner returns the perfect-information best card
  int sooli_play_heur;   // rollouts: sooli trick play by the heuristics instead of the solver
  double sooli_lambda;   // exposure tilt of sooli beliefs (mode bit 2)
  // Value leaf (docs/VALUE_NET_PLAN.md): NULL = off. Rollouts of bid searches
  // stop at the first trick boundary with at least leaf_bid completed tricks,
  // rollouts of card-play searches leaf_play complete tricks after the
  // decision's trick; -1 disables either. value_bot_bit: the net's bot-side
  // input is set for the searching team (VN2) or always clear (VN1).
  const struct TcMlpS *vnet;
  int leaf_bid, leaf_play, value_bot_bit;
  // Incremental first layer for self-play (tc_env_set_incremental; off by
  // default): per game and seat, the first-layer pre-activation and the sorted
  // list of active features it was built from (inc_len -1 = rebuild).
  // Rollout roles (tc_env_set_team_rollout): if set, the searching team's own
  // seats play team_net in rollouts and the other seats the search's network.
  // team_side is the searching team, set by search_core for each search.
  const struct TcMlpS *team_net;
  int team_side;
  int inc_on, inc_width;
  float *inc_acc;
  uint16_t *inc_list;
  int16_t *inc_len;
} TcEnv;
#define INC_MAXA 320

// Parallel loops (every iteration touches only its own game, so the results
// do not depend on the order). A batch job that already runs one process per
// core can switch them off (tc_set_parallel(0)) to avoid oversubscribing the
// machine with each process's worker threads.
static int parallel_loops = 1;
void tc_set_parallel(int on) { parallel_loops = on != 0; }
#ifndef TC_PORTABLE
static void par_apply(size_t n, void (^block)(size_t)) {
  if (!parallel_loops) {
    for (size_t i = 0; i < n; i++) block(i);
    return;
  }
  dispatch_apply(n, dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), block);
}

#endif

static inline u64 splitmix(u64 *x) {
  u64 z = (*x += 0x9E3779B97F4A7C15ULL);
  z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
  z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
  return z ^ (z >> 31);
}

static inline double unit(u64 *x) { return (splitmix(x) >> 11) * (1.0 / 9007199254740992.0); }

static void deal_random(TcGame *g, int dealer, int s0, int s1) {
  int deck[52];
  for (int i = 0; i < 52; i++) deck[i] = i;
  for (int i = 51; i > 0; i--) {
    int j = (int)(splitmix(&g->rng) % (u64)(i + 1));
    int t = deck[i]; deck[i] = deck[j]; deck[j] = t;
  }
  u64 hands[4] = {0, 0, 0, 0};
  for (int i = 0; i < 52; i++) hands[i / 13] |= 1ULL << deck[i];
  tc_deal_init(&g->d, hands, dealer, s0, s1);
}

static void new_match(TcEnv *e, TcGame *g) {
  int dealer = (int)(splitmix(&g->rng) & 3);
  int s0 = 0, s1 = 0;
  if (e->p_random_start > 0 && unit(&g->rng) < e->p_random_start) {
    int level = (int)(splitmix(&g->rng) % 13);  // 0..12
    if (level) { if (splitmix(&g->rng) & 1) s0 = 4 * level; else s1 = 4 * level; }
  }
  g->deals_in_match = 0;
  g->live = 1;
  deal_random(g, dealer, s0, s1);
}

static int eq_index(int s0, int s1) {
  if (s0 == 0 && s1 == 0) return 0;
  if (s0 > 0) return s0 / 4;
  return 12 + s1 / 4;
}

// Team-0 equity of a score about to be played with the given dealer.
static double equity0(const TcEnv *e, int s0, int s1, int dealer) {
  if (s0 >= TC_TARGET) return 1.0;
  if (s1 >= TC_TARGET) return 0.0;
  return e->eq[eq_index(s0, s1)][(dealer & 1) == 0];
}

TcEnv *tc_env_new(int n, uint64_t seed) {
  TcEnv *e = calloc(1, sizeof *e);
  e->n = n;
  e->encoder = 1;
  e->g = calloc((size_t)n, sizeof(TcGame));
  for (int s = 0; s < 25; s++) e->eq[s][0] = e->eq[s][1] = 0.5;
  for (int i = 0; i < n; i++) {
    e->g[i].rng = seed * 0x100000001B3ULL + (u64)i * 0x9E3779B97F4A7C15ULL + 1;
    splitmix(&e->g[i].rng);
    new_match(e, &e->g[i]);
  }
  return e;
}

void tc_env_free(TcEnv *e) { free(e->inc_acc); free(e->inc_list); free(e->inc_len); free(e->g); free(e); }

void tc_env_set_team_rollout(TcEnv *e, const struct TcMlpS *team_net) { e->team_net = team_net; e->team_side = -1; }

// Self-play rollouts only: networks of first-layer width `width` update each
// seat's first layer by the features that changed since its last decision
// instead of summing all active columns. Not bitwise equal to the exact path
// (the search keeps it off). on = 0 frees the buffers.
void tc_env_set_incremental(TcEnv *e, int on, int width) {
  free(e->inc_acc); free(e->inc_list); free(e->inc_len);
  e->inc_acc = NULL; e->inc_list = NULL; e->inc_len = NULL; e->inc_on = 0;
  if (!on) return;
  e->inc_width = width;
  e->inc_acc = malloc(sizeof(float) * (size_t)e->n * 4 * width);
  e->inc_list = malloc(sizeof(uint16_t) * (size_t)e->n * 4 * INC_MAXA);
  e->inc_len = malloc(sizeof(int16_t) * (size_t)e->n * 4);
  for (size_t i = 0; i < (size_t)e->n * 4; i++) e->inc_len[i] = -1;
  e->inc_on = 1;
}
int tc_env_size(const TcEnv *e) { return e->n; }
void tc_env_set_equity(TcEnv *e, const double *eq) { memcpy(e->eq, eq, sizeof e->eq); }
void tc_env_set_options(TcEnv *e, double p_random_start, int single_deal) {
  e->p_random_start = p_random_start;
  e->single_deal = single_deal;
}
void tc_env_set_encoder(TcEnv *e, int version) { e->encoder = version; }
void tc_env_set_sooli(TcEnv *e, int belief, int return_pi, int play_heur, double lambda) {
  e->sooli_lambda = lambda;
  e->sooli_belief = belief;
  e->sooli_return_pi = return_pi;
  e->sooli_play_heur = play_heur;
}
void tc_env_reset_all(TcEnv *e) { for (int i = 0; i < e->n; i++) new_match(e, &e->g[i]); }

// Explicit deal for duplicate evaluation (single-deal mode).
void tc_env_set_deal(TcEnv *e, int i, const uint64_t *hands, int dealer, int s0, int s1) {
  tc_deal_init(&e->g[i].d, hands, dealer, s0, s1);
  e->g[i].live = 1;
}

TcDeal *tc_env_deal(TcEnv *e, int i) { return &e->g[i].d; }

// Features and legal-action masks for every game's current actor.
void tc_env_observe(TcEnv *e, uint8_t *feat, uint8_t *mask, int32_t *seat, int32_t *phase) {
  int dim = tc_feature_dim_v(e->encoder);
  int acts[TC_NUM_ACTIONS_V2];
  TcObs o;
  memset(mask, 0, (size_t)e->n * TC_NUM_ACTIONS);
  for (int i = 0; i < e->n; i++) {
    TcGame *g = &e->g[i];
    if (!g->live || g->d.phase == TC_PH_DONE) {
      memset(feat + (size_t)i * dim, 0, (size_t)dim);
      seat[i] = -1;
      phase[i] = TC_PH_DONE;
      continue;
    }
    int s = g->d.cur;
    tc_observe(&g->d, s, &o);
    tc_encode_v(&o, feat + (size_t)i * dim, e->encoder);
    int k = tc_legal(&g->d, acts);
    for (int j = 0; j < k; j++) if (acts[j] < TC_NUM_ACTIONS) mask[(size_t)i * TC_NUM_ACTIONS + acts[j]] = 1;
    seat[i] = s;
    phase[i] = g->d.phase;
  }
}

// Applies one action per live game. For every game whose deal ended, sets
// done[i] = 1 and delta0[i] = team 0's match-equity change, and fills
// info[i*8..]: winner, points, contract, declarer, team-0 tricks, match over,
// score before (team 0), score before (team 1).
// Returns the number of illegal actions (which are not applied).
int tc_env_step(TcEnv *e, const int32_t *actions, int32_t *done, float *delta0, int32_t *info) {
  int illegal = 0;
  for (int i = 0; i < e->n; i++) {
    TcGame *g = &e->g[i];
    done[i] = 0;
    delta0[i] = 0.f;
    if (!g->live || g->d.phase == TC_PH_DONE) continue;
    if (tc_apply(&g->d, actions[i]) != 0) { illegal++; continue; }
    if (g->d.phase != TC_PH_DONE) continue;
    TcDeal *d = &g->d;
    uint8_t after[2];
    int over = tc_next_score(d->score, d->winner_team, d->points, after);
    double before_eq = equity0(e, d->score[0], d->score[1], d->dealer);
    double after_eq = equity0(e, after[0], after[1], d->dealer + 1);
    done[i] = 1;
    delta0[i] = (float)(after_eq - before_eq);
    int32_t *f = info + (size_t)i * 8;
    f[0] = d->winner_team; f[1] = d->points; f[2] = d->contract; f[3] = d->declarer;
    f[4] = d->team_tricks[0]; f[5] = over; f[6] = d->score[0]; f[7] = d->score[1];
    if (e->single_deal) continue;
    g->deals_in_match++;
    if (over) new_match(e, g);
    else deal_random(g, (d->dealer + 1) & 3, after[0], after[1]);
  }
  return illegal;
}

// Loads an arbitrary full deal state into game i (used by search rollouts).
void tc_env_set_state(TcEnv *e, int i, const TcDeal *d) {
  e->g[i].d = *d;
  e->g[i].live = 1;
}

// Solver tail: every live game in trick play with at most `dd_left` tricks
// remaining is finished with its perfect-information result. Same outputs as
// tc_env_step for the games it finishes. Returns how many it finished.
int tc_env_dd_finish(TcEnv *e, int dd_left, int32_t *done, float *delta0) {
  int *todo = malloc(sizeof(int) * (size_t)e->n), k = 0;
  for (int i = 0; i < e->n; i++) {
    done[i] = 0;
    delta0[i] = 0.f;
    TcGame *g = &e->g[i];
    if (!g->live || g->d.phase != TC_PH_PLAY) continue;
    if (13 - (g->d.n_played >> 2) > dd_left) continue;
    todo[k++] = i;
  }
  if (k) {
    // Solves are independent and each game is touched by one worker only.
    const size_t chunk = 64, chunks = ((size_t)k + chunk - 1) / chunk;
    TC_PARALLEL_BEGIN(chunks, c)
      size_t lo = c * chunk, hi = lo + chunk < (size_t)k ? lo + chunk : (size_t)k;
      for (size_t j = lo; j < hi; j++) {
        int i = todo[j];
        TcDeal *d = &e->g[i].d;
        tc_finish_with_tricks(d, tc_dd_team0_tricks(d));
        uint8_t after[2];
        tc_next_score(d->score, d->winner_team, d->points, after);
        done[i] = 1;
        delta0[i] = (float)(equity0(e, after[0], after[1], d->dealer + 1) - equity0(e, d->score[0], d->score[1], d->dealer));
      }
    TC_PARALLEL_END
  }
  free(todo);
  return k;
}

// Compact observation of live games only: writes rows for games still in play
// into feat/mask consecutively and their indices into idx. Returns the count.
int tc_env_observe_live(TcEnv *e, uint8_t *feat, uint8_t *mask, int32_t *idx) {
  int dim = tc_feature_dim_v(e->encoder), k = 0;
  int acts[TC_NUM_ACTIONS_V2];
  TcObs o;
  for (int i = 0; i < e->n; i++) {
    TcGame *g = &e->g[i];
    if (!g->live || g->d.phase == TC_PH_DONE) continue;
    tc_observe(&g->d, g->d.cur, &o);
    tc_encode_v(&o, feat + (size_t)k * dim, e->encoder);
    uint8_t *mk = mask + (size_t)k * TC_NUM_ACTIONS;
    memset(mk, 0, TC_NUM_ACTIONS);
    int n = tc_legal(&g->d, acts);
    for (int j = 0; j < n; j++) if (acts[j] < TC_NUM_ACTIONS) mk[acts[j]] = 1;
    idx[k++] = i;
  }
  return k;
}

// Applies actions only to the listed games (idx[0..k)).
void tc_env_step_live(TcEnv *e, const int32_t *idx, const int32_t *actions, int k, int32_t *done, float *delta0) {
  for (int j = 0; j < k; j++) {
    int i = idx[j];
    TcGame *g = &e->g[i];
    done[i] = 0;
    if (!g->live || g->d.phase == TC_PH_DONE) continue;
    if (tc_apply(&g->d, actions[j]) != 0) continue;
    if (g->d.phase != TC_PH_DONE) continue;
    TcDeal *d = &g->d;
    uint8_t after[2];
    tc_next_score(d->score, d->winner_team, d->points, after);
    done[i] = 1;
    delta0[i] = (float)(equity0(e, after[0], after[1], d->dealer + 1) - equity0(e, d->score[0], d->score[1], d->dealer));
  }
}

// Clones one game's state from another environment into slot j.
void tc_env_clone_from(TcEnv *dst, int j, const TcEnv *src, int i) {
  dst->g[j].d = src->g[i].d;
  dst->g[j].live = 1;
}

// Loads a sampled world `count` times into consecutive slots starting at j.
void tc_env_set_state_repeat(TcEnv *e, int j, const TcDeal *d, int count) {
  for (int k = 0; k < count; k++) { e->g[j + k].d = *d; e->g[j + k].live = 1; }
}

void tc_env_park_all(TcEnv *e) { for (int i = 0; i < e->n; i++) e->g[i].d.phase = TC_PH_DONE; }

// All current hands and actors, for labelling (research data only; never
// reachable from a policy).
void tc_env_hands(const TcEnv *e, uint64_t *hands, int32_t *actor) {
  for (int i = 0; i < e->n; i++) {
    for (int s = 0; s < 4; s++) hands[4 * i + s] = e->g[i].d.hand[s];
    actor[i] = e->g[i].d.cur;
  }
}

// ------------------------------------------------------------ native search
#include "tuppi_mlp.h"
int tc_sample_world(const TcObs *o, uint64_t *rng, TcDeal *out);

static void record_if_done(TcEnv *e, int i, double *total) {
  TcDeal *d = &e->g[i].d;
  if (d->phase != TC_PH_DONE) return;
  uint8_t after[2];
  tc_next_score(d->score, d->winner_team, d->points, after);
  float delta = (float)(equity0(e, after[0], after[1], d->dealer + 1) - equity0(e, d->score[0], d->score[1], d->dealer));
  total[i] += (double)delta;
}

int tc_sooli_policy(const TcObs *o, uint64_t *rng);
int tc_sample_world_sooli(const TcObs *o, uint64_t *rng, TcDeal *out, int mode, double lambda);

// The returned card that keeps the soolaaja alive under perfect information
// (the first in id order), or the heuristic's if none does.
static int pi_return(const TcDeal *d, uint64_t *rng) {
  int acts[TC_NUM_ACTIONS_V2], k = tc_legal(d, acts);
  for (int j = 0; j < k; j++) {
    TcDeal c = *d;
    if (tc_apply(&c, acts[j]) == 0 && tc_sooli_solve(&c) == 1) return acts[j];
  }
  TcObs ob;
  tc_observe(d, d->cur, &ob);
  return tc_sooli_policy(&ob, rng);
}

// project_target_v2: sooli decisions inside rollouts are taken by the
// observation-only heuristics (tuppi_sooli_policy.c) and sooli trick play is
// finished by the perfect-information solver. One game at a time with its own
// rng; search_core runs the games in parallel (the solvers' tables are
// per-thread).
static void resolve_sooli(TcEnv *e, int i, uint64_t *rng, double *total) {
  TcDeal *d = &e->g[i].d;
  while (d->phase == TC_PH_SOOLI_OFFER || d->phase == TC_PH_SOOLI_GIVE || d->phase == TC_PH_SOOLI_RETURN) {
    TcObs ob;
    tc_observe(d, d->cur, &ob);
    int a = d->phase == TC_PH_SOOLI_RETURN && e->sooli_return_pi ? pi_return(d, rng) : tc_sooli_policy(&ob, rng);
    if (tc_apply(d, a) != 0) { d->phase = TC_PH_DONE; return; }
  }
  if (d->phase == TC_PH_SOOLI_PLAY) {
    if (e->sooli_play_heur) {
      while (d->phase == TC_PH_SOOLI_PLAY) {
        TcObs ob;
        tc_observe(d, d->cur, &ob);
        if (tc_apply(d, tc_sooli_policy(&ob, rng)) != 0) { d->phase = TC_PH_DONE; return; }
      }
    } else {
      tc_sooli_finish(d);
    }
    record_if_done(e, i, total);
  }
}

// Values of `k` candidate actions for the observer of `o`: `w` uniform
// hard-feasible worlds, every candidate played out in each world greedily by
// the network for all four seats (each from its own observation), the last
// `dd_left` tricks solved exactly if dd_left > 0; team-0 equity changes are
// averaged over worlds and signed for the observer's team. The same steps, in
// the same order and with the same rounding, as tuppi_ai.search.Searcher.
// Returns 0, -1 if no world exists, -2 if the environment is too small.
static int search_core(TcEnv *e, const TcMlp *m, const TcObs *o, const int32_t *actions, int k, int w,
                       int dd_left, uint64_t *rng, double *values, double *per_world);

// Rollouts per network batch in the search. 32 spreads one search over the
// most cores (lowest latency, for live play); 128 does about 7% less work in
// total (larger matrix products), for batch jobs that already run several
// processes. The moves are the same either way.
// Extra solver-tail tricks in NOLO contracts for the rollouts (play_out; 0 =
// the same tail as RAMI, the default). NOLO solves fast enough at 7 tricks.
static int dd_extra_nolo = 0;
void tc_set_dd_extra_nolo(int extra) { dd_extra_nolo = extra; }
static int rollout_chunk = 32;
void tc_set_rollout_chunk(int chunk) { rollout_chunk = chunk < 8 ? 8 : chunk > 512 ? 512 : chunk; }

int tc_search_values(TcEnv *e, const TcMlp *m, const TcObs *o, const int32_t *actions, int k, int w,
                     int dd_left, uint64_t *rng, double *values) {
  return search_core(e, m, o, actions, k, w, dd_left, rng, values, NULL);
}

// As tc_search_values, and also every world's value of every action in
// per_world[wi * k + ai] (observer's sign). The worlds are shared by all
// actions, so per-world differences give the paired standard error of a gap.
int tc_search_world_values(TcEnv *e, const TcMlp *m, const TcObs *o, const int32_t *actions, int k, int w,
                           int dd_left, uint64_t *rng, double *values, double *per_world) {
  return search_core(e, m, o, actions, k, w, dd_left, rng, values, per_world);
}

// ------------------------------------------------------------ value leaf
// Full-information features of a trick-play position at a trick boundary, from
// the side of the seat to move (relative seats; team = that seat's team):
// four hands, tricks per team, contract, declarer, score levels, dealer, trick
// index, one bit for "the side to move is the bot pair" (VN2 only) and one for
// "a RAMI was just declared and the sooli offers are still to come" (the end of
// bidding under project_target_v2/v3; the side to move is the first defender).
enum {
  P_HANDS = 0, P_TRICKS = P_HANDS + 208, P_CONTRACT = P_TRICKS + 28, P_DECLARER = P_CONTRACT + 2,
  P_SCORE = P_DECLARER + 5, P_DEALER = P_SCORE + 26, P_TRICK_INDEX = P_DEALER + 4, P_BOT = P_TRICK_INDEX + 13,
  P_PRE_OFFER = P_BOT + 1, P_DIM = P_PRE_OFFER + 1
};
int tc_pi_feature_dim(void) { return P_DIM; }

void tc_encode_pi(const TcDeal *d, int bot_side, uint8_t *out) {
  memset(out, 0, P_DIM);
  const int s = d->cur, own = s & 1;
  for (int q = 0; q < 4; q++)
    for (u64 m = d->hand[q]; m; m &= m - 1) out[P_HANDS + 52 * ((q - s) & 3) + __builtin_ctzll(m)] = 1;
  out[P_TRICKS + d->team_tricks[own]] = 1;
  out[P_TRICKS + 14 + d->team_tricks[own ^ 1]] = 1;
  out[P_CONTRACT + (d->contract == TC_RAMI)] = 1;
  out[P_DECLARER + (d->declarer < 0 ? 4 : ((d->declarer - s) & 3))] = 1;
  int lo = d->score[own] / 4, lt = d->score[own ^ 1] / 4;
  out[P_SCORE + (lo > 12 ? 12 : lo)] = 1;
  out[P_SCORE + 13 + (lt > 12 ? 12 : lt)] = 1;
  out[P_DEALER + ((d->dealer - s) & 3)] = 1;
  int t = d->n_played / 4;
  out[P_TRICK_INDEX + (t > 12 ? 12 : t)] = 1;
  out[P_BOT] = (uint8_t)(bot_side != 0);
  out[P_PRE_OFFER] = (uint8_t)(d->phase == TC_PH_SOOLI_OFFER);
}

void tc_env_set_value(TcEnv *e, const TcMlp *v, int leaf_bid, int leaf_play, int bot_bit) {
  e->vnet = v;
  e->leaf_bid = leaf_bid;
  e->leaf_play = leaf_play;
  e->value_bot_bit = bot_bit;
}

typedef struct {
  const TcMlp *v;
  int min_completed;  // leaf at a trick boundary with at least this many completed tricks
  int bot_team;       // team whose side-to-move gets the bot bit, or -1
} Leaf;

// Training capture: full-information rows of trick-boundary positions.
typedef struct {
  int max_rows, rows;
  uint8_t *feat;
  int32_t *game;
  int8_t *team;
  int8_t *last;  // per game: completed tricks of its last captured row
} Capture;

// A leaf point: an ordinary trick-play trick boundary with at least
// min_completed tricks done and more than dd_left left, or, for bid searches
// (min_completed == 0), the end of bidding before any sooli offer.
static inline int at_leaf_point(const TcDeal *d, int dd_left, int min_completed) {
  if (d->phase == TC_PH_SOOLI_OFFER) return min_completed == 0 && d->n_decisions == 0;
  if (d->phase != TC_PH_PLAY || (d->n_played & 3)) return 0;
  int done = d->n_played >> 2;
  return done >= min_completed && 13 - done > dd_left;
}

static void inc_reset(TcEnv *e, int n) {
  if (e->inc_on) for (size_t i = 0; i < (size_t)n * 4; i++) e->inc_len[i] = -1;
}

// Network outputs for `rows` games (their current actors), from dense
// features: exact (tc_mlp_forward), or incremental when the environment has
// it on for this network's width. Each game appears at most once per call.
static void forward_games(TcEnv *e, const TcMlp *m, const int *games, int rows, const uint8_t *feat, int dim,
                          float *q) {
  if (!e->inc_on || tc_mlp_width(m) != e->inc_width) { tc_mlp_forward(m, feat, rows, q); return; }
  const int W = e->inc_width;
  float *h0 = malloc(sizeof(float) * (size_t)rows * W);
  uint16_t fresh[INC_MAXA];
  for (int r = 0; r < rows; r++) {
    const int i = games[r], slot = i * 4 + e->g[i].d.cur;
    const uint8_t *fr = feat + (size_t)r * dim;
    int nf = 0, overflow = 0;
    for (int j = 0; j < dim; j++) {
      if (!fr[j]) continue;
      if (nf == INC_MAXA) { overflow = 1; break; }
      fresh[nf++] = (uint16_t)j;
    }
    float *acc = e->inc_acc + (size_t)slot * W;
    uint16_t *old = e->inc_list + (size_t)slot * INC_MAXA;
    const int no = e->inc_len[slot];
    if (overflow) {  // too many active features to track: exact sum, no reuse
      tc_mlp_h0_init(m, acc);
      for (int j = 0; j < dim; j++) if (fr[j]) tc_mlp_h0_add(m, acc, j, 1.0f);
      e->inc_len[slot] = -1;
    } else {
      if (no < 0) {
        tc_mlp_h0_init(m, acc);
        for (int a = 0; a < nf; a++) tc_mlp_h0_add(m, acc, fresh[a], 1.0f);
      } else {  // merge the two sorted lists: subtract what left, add what came
        int a = 0, b = 0;
        while (a < no || b < nf) {
          if (b == nf || (a < no && old[a] < fresh[b])) tc_mlp_h0_add(m, acc, old[a++], -1.0f);
          else if (a == no || fresh[b] < old[a]) tc_mlp_h0_add(m, acc, fresh[b++], 1.0f);
          else { a++; b++; }
        }
      }
      memcpy(old, fresh, sizeof(uint16_t) * (size_t)nf);
      e->inc_len[slot] = (int16_t)nf;
    }
    memcpy(h0 + (size_t)r * W, acc, sizeof(float) * (size_t)W);
  }
  tc_mlp_forward_h0(m, h0, rows, q);
  free(h0);
}

// Plays every live game of e->g[0..n) to its end (or its value leaf) exactly as
// the search's rollouts do: sooli phases by the heuristics (resolved in
// parallel from one draw of rng), the solver tail for the last dd_left tricks,
// everything else greedily by the network. Deal results go to total[] (team 0).
static void play_out(TcEnv *e, const TcMlp *m, int n, int dd_left, uint64_t *rng, double *total, int *idx,
                     const Leaf *leaf, Capture *cap) {
  const int enc = tc_mlp_encoder(m), dim = tc_feature_dim_v(enc);
  inc_reset(e, n);
  for (;;) {
    if (cap) {
      for (int i = 0; i < n; i++) {
        const TcDeal *d = &e->g[i].d;
        if (!at_leaf_point(d, dd_left, 0) || cap->last[i] == (int8_t)(d->n_played >> 2) || cap->rows >= cap->max_rows) continue;
        cap->last[i] = (int8_t)(d->n_played >> 2);
        tc_encode_pi(d, 0, cap->feat + (size_t)cap->rows * P_DIM);
        cap->game[cap->rows] = i;
        cap->team[cap->rows] = (int8_t)(d->cur & 1);
        cap->rows++;
      }
    }
    if (leaf) {
      int todo = 0;
      for (int i = 0; i < n; i++)
        if (at_leaf_point(&e->g[i].d, dd_left, leaf->min_completed)) idx[todo++] = i;
      if (todo) {
        const int chunk = 256;
        TC_PARALLEL_BEGIN((size_t)(todo + chunk - 1) / chunk, c)
          int lo = (int)c * chunk, hi = lo + chunk < todo ? lo + chunk : todo, rows = hi - lo;
          uint8_t *feat = malloc((size_t)rows * P_DIM);
          float *v = malloc(sizeof(float) * (size_t)rows);
          for (int r = 0; r < rows; r++) {
            const TcDeal *d = &e->g[idx[lo + r]].d;
            tc_encode_pi(d, leaf->bot_team >= 0 && (d->cur & 1) == leaf->bot_team, feat + (size_t)r * P_DIM);
          }
          tc_mlp_forward(leaf->v, feat, rows, v);
          for (int r = 0; r < rows; r++) {
            int i = idx[lo + r];
            TcDeal *d = &e->g[i].d;
            total[i] += (d->cur & 1) == 0 ? (double)v[r] : -(double)v[r];  // v: side to move
            d->phase = TC_PH_DONE;  // valued; no deal result is recorded
          }
          free(feat);
          free(v);
        TC_PARALLEL_END
      }
    }
    // Rollouts that reached a sooli (most RAMI rollouts of a bid search pass
    // an offer, which the heuristic answers with the exact solver on sampled
    // worlds): resolved in parallel, each game with its own stream seeded from
    // one draw of the shared rng, so a search stays reproducible.
    int ns = 0;
    for (int i = 0; i < n; i++)
      if (e->g[i].d.phase >= TC_PH_SOOLI_OFFER) idx[ns++] = i;
    if (ns) {
      const u64 base = splitmix(rng);
      TC_PARALLEL_BEGIN((size_t)ns, j)
        u64 local = base ^ (0x9E3779B97F4A7C15ULL * (u64)(idx[j] + 1));
        splitmix(&local);
        resolve_sooli(e, idx[j], &local, total);
      TC_PARALLEL_END
    }
    if (dd_left > 0) {
      int todo = 0;
      for (int i = 0; i < n; i++) {
        TcDeal *d = &e->g[i].d;
        if (d->phase == TC_PH_PLAY && 13 - (d->n_played >> 2) <= dd_left + (d->contract == TC_NOLO ? dd_extra_nolo : 0))
          idx[todo++] = i;
      }
      if (todo) {
        TC_PARALLEL_BEGIN((size_t)(todo + 31) / 32, c)
          int lo = (int)c * 32, hi = lo + 32 < todo ? lo + 32 : todo;
          for (int j = lo; j < hi; j++) {
            TcDeal *d = &e->g[idx[j]].d;
            tc_finish_with_tricks(d, tc_dd_team0_tricks(d));
            record_if_done(e, idx[j], total);
          }
        TC_PARALLEL_END
      }
    }
    int live = 0;
    for (int i = 0; i < n; i++) if (e->g[i].d.phase != TC_PH_DONE) idx[live++] = i;
    if (!live) break;
    const int chunk = rollout_chunk;
    TC_PARALLEL_BEGIN((size_t)(live + chunk - 1) / chunk, c)
      int lo = (int)c * chunk, hi = lo + chunk < live ? lo + chunk : live, rows = hi - lo;
      uint8_t *feat = malloc((size_t)rows * dim);
      float *q = malloc(sizeof(float) * (size_t)rows * TC_NUM_ACTIONS);
      int legal[TC_NUM_ACTIONS];
      TcObs ob;
      for (int r = 0; r < rows; r++) {
        TcDeal *d = &e->g[idx[lo + r]].d;
        tc_observe(d, d->cur, &ob);
        tc_encode_v(&ob, feat + (size_t)r * dim, enc);
      }
      if (e->team_net && e->team_side >= 0) {
        // Rows of the searching team's seats go to team_net, the rest to m.
        uint8_t *ft = malloc((size_t)rows * dim), *fo = malloc((size_t)rows * dim);
        float *qt = malloc(sizeof(float) * (size_t)rows * TC_NUM_ACTIONS);
        float *qo = malloc(sizeof(float) * (size_t)rows * TC_NUM_ACTIONS);
        int *which = malloc(sizeof(int) * (size_t)rows), nt = 0, no = 0;
        for (int r = 0; r < rows; r++) {
          int own = (e->g[idx[lo + r]].d.cur & 1) == e->team_side;
          memcpy((own ? ft + (size_t)nt * dim : fo + (size_t)no * dim), feat + (size_t)r * dim, (size_t)dim);
          which[r] = own ? nt++ : -1 - no++;
        }
        if (nt) tc_mlp_forward(e->team_net, ft, nt, qt);
        if (no) tc_mlp_forward(m, fo, no, qo);
        for (int r = 0; r < rows; r++) {
          const float *src = which[r] >= 0 ? qt + (size_t)which[r] * TC_NUM_ACTIONS
                                           : qo + (size_t)(-1 - which[r]) * TC_NUM_ACTIONS;
          memcpy(q + (size_t)r * TC_NUM_ACTIONS, src, sizeof(float) * TC_NUM_ACTIONS);
        }
        free(ft); free(fo); free(qt); free(qo); free(which);
      } else {
        forward_games(e, m, idx + lo, rows, feat, dim, q);
      }
      for (int r = 0; r < rows; r++) {
        int i = idx[lo + r];
        TcDeal *d = &e->g[i].d;
        // tc_legal lists actions in increasing id order, so scanning it keeps
        // numpy's "first maximum" tie-break over the masked row.
        int nl = tc_legal(d, legal), best = legal[0];
        const float *qr = q + (size_t)r * TC_NUM_ACTIONS;
        for (int t = 1; t < nl; t++) if (qr[legal[t]] > qr[best]) best = legal[t];
        tc_apply(d, best);
        record_if_done(e, i, total);
      }
      free(feat);
      free(q);
    TC_PARALLEL_END
  }
}

static int search_core(TcEnv *e, const TcMlp *m, const TcObs *o, const int32_t *actions, int k, int w,
                       int dd_left, uint64_t *rng, double *values, double *per_world) {
  const int n = w * k;
  if (n > e->n) return -2;
  TcDeal world;
  for (int wi = 0; wi < w; wi++) {
    if (tc_sample_world_sooli(o, rng, &world, e->sooli_belief, e->sooli_lambda) != 0) return -1;
    for (int ai = 0; ai < k; ai++) { e->g[wi * k + ai].d = world; e->g[wi * k + ai].live = 1; }
  }
  double *total = calloc((size_t)n, sizeof(double));
  int *idx = malloc(sizeof(int) * (size_t)n);
  for (int i = 0; i < n; i++) {
    if (tc_apply(&e->g[i].d, actions[i % k]) != 0) { free(total); free(idx); return -3; }
    record_if_done(e, i, total);
  }
  e->team_side = e->team_net ? (o->seat & 1) : -1;
  Leaf leaf = {e->vnet, 0, e->value_bot_bit ? (o->seat & 1) : -1};
  int use_leaf = 0;
  if (e->vnet && o->phase == TC_PH_SHOW && e->leaf_bid >= 0) { use_leaf = 1; leaf.min_completed = e->leaf_bid; }
  if (e->vnet && o->phase == TC_PH_PLAY && e->leaf_play >= 0) {
    use_leaf = 1;
    leaf.min_completed = o->n_played / 4 + 1 + e->leaf_play;
  }
  play_out(e, m, n, dd_left, rng, total, idx, use_leaf ? &leaf : NULL, NULL);
  const double sign = (o->seat & 1) == 0 ? 1.0 : -1.0;
  for (int a = 0; a < k; a++) {
    double s = 0.0;
    for (int wi = 0; wi < w; wi++) s += total[wi * k + a];
    values[a] = sign * (s / w);
  }
  if (per_world)
    for (int i = 0; i < n; i++) per_world[i] = sign * total[i];
  free(total);
  free(idx);
  return 0;
}

// Value training data (VN1): n games from random deals under `ruleset` (score
// 0-0 half the time, else a random reachable score; random dealer), played to
// the end exactly as the search's rollouts are. Every trick-boundary position
// with more than dd_left tricks left is written as a full-information row
// (tc_encode_pi, bot bit clear); target[row] is the deal's match-equity change
// for the side to move at that row. Returns the number of rows (<= max_rows).
int tc_value_rollouts(TcEnv *e, const TcMlp *m, int n, int ruleset, int dd_left, uint64_t *rng, int max_rows,
                      uint8_t *feat, float *target) {
  if (n > e->n) return -2;
  for (int i = 0; i < n; i++) {
    uint64_t hands[4] = {0, 0, 0, 0};
    int deck[52];
    for (int c = 0; c < 52; c++) deck[c] = c;
    for (int c = 51; c > 0; c--) { int j = (int)(splitmix(rng) % (u64)(c + 1)); int t = deck[c]; deck[c] = deck[j]; deck[j] = t; }
    for (int c = 0; c < 52; c++) hands[c / 13] |= 1ULL << deck[c];
    int dealer = (int)(splitmix(rng) & 3), s0 = 0, s1 = 0;
    if (splitmix(rng) & 1) {
      int level = 1 + (int)(splitmix(rng) % 12);
      if (splitmix(rng) & 1) s0 = 4 * level; else s1 = 4 * level;
    }
    tc_deal_init_v(&e->g[i].d, hands, dealer, s0, s1, ruleset);
    e->g[i].live = 1;
  }
  double *total = calloc((size_t)n, sizeof(double));
  int *idx = malloc(sizeof(int) * (size_t)n);
  int32_t *game = malloc(sizeof(int32_t) * (size_t)max_rows);
  int8_t *team = malloc((size_t)max_rows), *last = malloc((size_t)n);
  memset(last, -1, (size_t)n);
  Capture cap = {max_rows, 0, feat, game, team, last};
  play_out(e, m, n, dd_left, rng, total, idx, NULL, &cap);
  for (int r = 0; r < cap.rows; r++) {
    double t0 = total[game[r]];
    target[r] = (float)(team[r] == 0 ? t0 : -t0);
  }
  int rows = cap.rows;
  free(total); free(idx); free(game); free(team); free(last);
  return rows;
}

// ------------------------------------------------------ self-play learning
// docs/SELFPLAY_PLAN.md. Random v3-style deals (random dealer; score 0-0 half
// the time, else a random reachable score), every game with its own rng stream.
static void random_deals(TcEnv *e, int n, int ruleset, uint64_t *rng) {
  for (int i = 0; i < n; i++) {
    uint64_t hands[4] = {0, 0, 0, 0};
    int deck[52];
    for (int c = 0; c < 52; c++) deck[c] = c;
    for (int c = 51; c > 0; c--) { int j = (int)(splitmix(rng) % (u64)(c + 1)); int t = deck[c]; deck[c] = deck[j]; deck[j] = t; }
    for (int c = 0; c < 52; c++) hands[c / 13] |= 1ULL << deck[c];
    int dealer = (int)(splitmix(rng) & 3), s0 = 0, s1 = 0;
    if (splitmix(rng) & 1) {
      int level = 1 + (int)(splitmix(rng) % 12);
      if (splitmix(rng) & 1) s0 = 4 * level; else s1 = 4 * level;
    }
    tc_deal_init_v(&e->g[i].d, hands, dealer, s0, s1, ruleset);
    e->g[i].live = 1;
    e->g[i].rng = splitmix(rng) | 1;
  }
}

// Self-play with the policy network on all seats and no solver tail. At each
// unforced decision the full state is recorded with probability p_record
// (before the action); a decision is played uniformly at random with
// probability p_random, else greedily. Sooli phases by the heuristics (and the
// fast offer model if one is set). Returns the number of states recorded.
// Position classes for importance-weighted recording: 0 showing, 1 + trick
// for NOLO trick play, 14 + trick for RAMI trick play (27 classes).
static inline int record_class(const TcDeal *d) {
  if (d->phase == TC_PH_SHOW) return 0;
  int t = d->n_played / 4;
  return (d->contract == TC_RAMI ? 14 : 1) + (t > 12 ? 12 : t);
}
int tc_record_class(const TcDeal *d) { return record_class(d); }

// class_mult (27 entries, or NULL for 1): the recording probability of an
// unforced decision is p_record * class_mult[class] (capped at 1).
int tc_selfplay_states_w(TcEnv *e, const TcMlp *m, int n, int ruleset, uint64_t *rng, double p_record,
                         double p_random, const double *class_mult, int max_states, TcDeal *out);
int tc_selfplay_states(TcEnv *e, const TcMlp *m, int n, int ruleset, uint64_t *rng, double p_record,
                       double p_random, int max_states, TcDeal *out) {
  return tc_selfplay_states_w(e, m, n, ruleset, rng, p_record, p_random, NULL, max_states, out);
}

int tc_selfplay_states_w(TcEnv *e, const TcMlp *m, int n, int ruleset, uint64_t *rng, double p_record,
                         double p_random, const double *class_mult, int max_states, TcDeal *out) {
  if (n > e->n) return -2;
  random_deals(e, n, ruleset, rng);
  inc_reset(e, n);
  double *total = calloc((size_t)n, sizeof(double));
  int *idx = malloc(sizeof(int) * (size_t)n);
  const int enc = tc_mlp_encoder(m), dim = tc_feature_dim_v(enc);
  TC_BLOCK int recorded = 0;
  int *counter = &recorded;
  for (;;) {
    int ns = 0;
    for (int i = 0; i < n; i++)
      if (e->g[i].d.phase >= TC_PH_SOOLI_OFFER) idx[ns++] = i;
    if (ns) TC_PARALLEL_BEGIN((size_t)ns, j) resolve_sooli(e, idx[j], &e->g[idx[j]].rng, total); TC_PARALLEL_END
    int live = 0;
    for (int i = 0; i < n; i++) if (e->g[i].d.phase != TC_PH_DONE) idx[live++] = i;
    if (!live) break;
    const int chunk = rollout_chunk;
    TC_PARALLEL_BEGIN((size_t)(live + chunk - 1) / chunk, c)
      int lo = (int)c * chunk, hi = lo + chunk < live ? lo + chunk : live, rows = hi - lo;
      uint8_t *feat = malloc((size_t)rows * dim);
      float *q = malloc(sizeof(float) * (size_t)rows * TC_NUM_ACTIONS);
      int legal[TC_NUM_ACTIONS_V2];
      TcObs ob;
      for (int r = 0; r < rows; r++) {
        TcDeal *d = &e->g[idx[lo + r]].d;
        tc_observe(d, d->cur, &ob);
        tc_encode_v(&ob, feat + (size_t)r * dim, enc);
      }
      forward_games(e, m, idx + lo, rows, feat, dim, q);
      for (int r = 0; r < rows; r++) {
        TcGame *g = &e->g[idx[lo + r]];
        TcDeal *d = &g->d;
        int nl = tc_legal(d, legal), best = legal[0];
        if (nl > 1) {
          const double pr = class_mult ? p_record * class_mult[record_class(d)] : p_record;
          if (unit(&g->rng) < pr) {
            int slot = __atomic_fetch_add(counter, 1, __ATOMIC_RELAXED);
            if (slot < max_states) out[slot] = *d;
          }
          if (unit(&g->rng) < p_random) {
            best = legal[splitmix(&g->rng) % (u64)nl];
          } else {
            const float *qr = q + (size_t)r * TC_NUM_ACTIONS;
            for (int t = 1; t < nl; t++) if (qr[legal[t]] > qr[best]) best = legal[t];
          }
        }
        tc_apply(d, best);
      }
      free(feat);
      free(q);
    TC_PARALLEL_END
  }
  free(total);
  free(idx);
  return recorded < max_states ? recorded : max_states;
}

// Branch labels: for each state, every legal action (network ids, at most
// max_k) is applied to a copy and played out to the end with the policy on all
// seats (solver tail of dd_left tricks if > 0). q[s * max_k + j] is the acting
// team's match-equity change after actions[s * max_k + j]; k[s] actions are
// valid. e must hold at least the total number of actions. Returns 0, or -2
// if e is too small.
// Label sharing (tc_set_branch_share): in trick play, a legal card whose next
// lower live card of its suit (any hand, or the current trick) is also legal
// for the mover takes the same tricks under every continuation; only the
// lowest card of each such run is played out and the others copy its value
// (measured: identical labels for 95.7% of such pairs under the clone, which
// reads the exact card; they are 24% of card-play rollouts).
static int branch_share = 0;
void tc_set_branch_share(int on) { branch_share = on != 0; }

static int share_rep(const TcDeal *d, int card) {
  if (!branch_share || d->phase != TC_PH_PLAY || card >= 52) return card;
  u64 live = d->hand[0] | d->hand[1] | d->hand[2] | d->hand[3];
  int pos = d->n_played & 3;
  for (int i = d->n_played - pos; i < d->n_played; i++) live |= 1ULL << d->play_card[i];
  const u64 own = d->hand[d->cur], sm = 0x1FFFULL << (13 * (card / 13));
  int c = card;
  for (;;) {  // walk down while the next lower live card is also the mover's
    u64 below = live & sm & ((1ULL << c) - 1);
    if (!below) return c;
    int nb = 63 - __builtin_clzll(below);
    if (!(own >> nb & 1ULL)) return c;
    c = nb;
  }
}

int tc_branch_values(TcEnv *e, const TcMlp *m, const TcDeal *states, int n_states, int max_k, int dd_left,
                     uint64_t *rng, int32_t *actions, int32_t *k, float *q) {
  int total_games = 0, legal[TC_NUM_ACTIONS_V2];
  for (int s = 0; s < n_states; s++) {
    int nl = tc_legal(&states[s], legal), kk = 0;
    for (int j = 0; j < nl && kk < max_k; j++) if (legal[j] < TC_NUM_ACTIONS) actions[s * max_k + kk++] = legal[j];
    k[s] = kk;
    for (int j = 0; j < kk; j++) total_games += share_rep(&states[s], actions[s * max_k + j]) == actions[s * max_k + j];
  }
  if (total_games > e->n) return -2;
  double *total = calloc((size_t)total_games, sizeof(double));
  int *idx = malloc(sizeof(int) * (size_t)total_games);
  int *slot = malloc(sizeof(int) * (size_t)n_states * max_k);  // game index of each (state, action)'s rollout
  int g = 0;
  for (int s = 0; s < n_states; s++)
    for (int j = 0; j < k[s]; j++) {
      int a = actions[s * max_k + j];
      if (share_rep(&states[s], a) != a) continue;
      slot[s * max_k + j] = g;
      e->g[g].d = states[s];
      e->g[g].live = 1;
      tc_apply(&e->g[g].d, a);
      record_if_done(e, g, total);
      g++;
    }
  for (int s = 0; s < n_states; s++)  // copies point at their representative's rollout
    for (int j = 0; j < k[s]; j++) {
      int a = actions[s * max_k + j], rep = share_rep(&states[s], a);
      if (rep == a) continue;
      for (int r = 0; r < k[s]; r++) if (actions[s * max_k + r] == rep) { slot[s * max_k + j] = slot[s * max_k + r]; break; }
    }
  play_out(e, m, total_games, dd_left, rng, total, idx, NULL, NULL);
  for (int s = 0; s < n_states; s++) {
    const double sign = (states[s].cur & 1) == 0 ? 1.0 : -1.0;
    for (int j = 0; j < k[s]; j++) q[s * max_k + j] = (float)(sign * total[slot[s * max_k + j]]);
  }
  free(total);
  free(idx);
  free(slot);
  return 0;
}

// Observation features (encoder) and legal-action masks of the acting seat for
// a batch of states, in parallel.
void tc_encode_states(const TcDeal *states, int n, int encoder, uint8_t *feat, uint8_t *mask) {
  const int dim = tc_feature_dim_v(encoder);
  TC_PARALLEL_BEGIN((size_t)(n + 255) / 256, c)
    int lo = (int)c * 256, hi = lo + 256 < n ? lo + 256 : n, legal[TC_NUM_ACTIONS_V2];
    TcObs ob;
    for (int s = lo; s < hi; s++) {
      tc_observe(&states[s], states[s].cur, &ob);
      tc_encode_v(&ob, feat + (size_t)s * dim, encoder);
      uint8_t *mk = mask + (size_t)s * TC_NUM_ACTIONS;
      memset(mk, 0, TC_NUM_ACTIONS);
      int nl = tc_legal(&states[s], legal);
      for (int j = 0; j < nl; j++) if (legal[j] < TC_NUM_ACTIONS) mk[legal[j]] = 1;
    }
  TC_PARALLEL_END
}

// Duplicate evaluation of two policy networks under `ruleset`, all in native
// code (the design of tuppi_ai/evaluate.py: every base deal is played 4
// rotations x 2 team assignments, dealer 0, from the given score). Seats of
// team A play mA, the others mB; sooli phases by the heuristics; the solver
// tail for the last dd_left tricks if > 0. value[b] is team A's mean
// match-equity change over base deal b's 8 games. e must hold 8 * n_base games.
static double dup_temperature = 0.0;  // > 0: both sides sample from softmax(logits / T) (tc_set_eval_temperature)
void tc_set_eval_temperature(double t) { dup_temperature = t; }

int tc_duplicate_eval(TcEnv *e, const TcMlp *mA, const TcMlp *mB, int n_base, int ruleset, int score0,
                      int score1, int dd_left, uint64_t *rng, double *value) {
  const int n = 8 * n_base;
  if (n > e->n) return -2;
  if (tc_mlp_encoder(mA) != tc_mlp_encoder(mB)) return -3;
  int *a_team = malloc(sizeof(int) * (size_t)n);
  for (int b = 0; b < n_base; b++) {
    int deck[52];
    for (int c = 0; c < 52; c++) deck[c] = c;
    for (int c = 51; c > 0; c--) { int j = (int)(splitmix(rng) % (u64)(c + 1)); int t = deck[c]; deck[c] = deck[j]; deck[j] = t; }
    uint64_t base[4] = {0, 0, 0, 0};
    for (int c = 0; c < 52; c++) base[c / 13] |= 1ULL << deck[c];
    for (int r = 0; r < 4; r++)
      for (int t = 0; t < 2; t++) {
        int g = 8 * b + 2 * r + t;
        uint64_t hands[4];
        for (int s = 0; s < 4; s++) hands[s] = base[(s + r) & 3];
        tc_deal_init_v(&e->g[g].d, hands, 0, score0, score1, ruleset);
        e->g[g].live = 1;
        e->g[g].rng = splitmix(rng) | 1;
        a_team[g] = t;
      }
  }
  double *total = calloc((size_t)n, sizeof(double));
  int *idx = malloc(sizeof(int) * (size_t)n);
  const int dim = tc_feature_dim_v(tc_mlp_encoder(mA));
  for (;;) {
    int ns = 0;
    for (int i = 0; i < n; i++)
      if (e->g[i].d.phase >= TC_PH_SOOLI_OFFER) idx[ns++] = i;
    if (ns) TC_PARALLEL_BEGIN((size_t)ns, j) resolve_sooli(e, idx[j], &e->g[idx[j]].rng, total); TC_PARALLEL_END
    if (dd_left > 0) {
      int todo = 0;
      for (int i = 0; i < n; i++) {
        TcDeal *d = &e->g[i].d;
        if (d->phase == TC_PH_PLAY && 13 - (d->n_played >> 2) <= dd_left) idx[todo++] = i;
      }
      if (todo)
        TC_PARALLEL_BEGIN((size_t)(todo + 31) / 32, c)
          int lo = (int)c * 32, hi = lo + 32 < todo ? lo + 32 : todo;
          for (int j = lo; j < hi; j++) {
            TcDeal *d = &e->g[idx[j]].d;
            tc_finish_with_tricks(d, tc_dd_team0_tricks(d));
            record_if_done(e, idx[j], total);
          }
        TC_PARALLEL_END
    }
    int live = 0;
    for (int i = 0; i < n; i++) if (e->g[i].d.phase != TC_PH_DONE) idx[live++] = i;
    if (!live) break;
    const int chunk = rollout_chunk;
    TC_PARALLEL_BEGIN((size_t)(live + chunk - 1) / chunk, c)
      int lo = (int)c * chunk, hi = lo + chunk < live ? lo + chunk : live, rows = hi - lo;
      uint8_t *feat = malloc((size_t)rows * dim);
      float *qa = malloc(sizeof(float) * (size_t)rows * TC_NUM_ACTIONS);
      float *qb = malloc(sizeof(float) * (size_t)rows * TC_NUM_ACTIONS);
      int legal[TC_NUM_ACTIONS_V2];
      TcObs ob;
      for (int r = 0; r < rows; r++) {
        TcDeal *d = &e->g[idx[lo + r]].d;
        tc_observe(d, d->cur, &ob);
        tc_encode_v(&ob, feat + (size_t)r * dim, tc_mlp_encoder(mA));
      }
      tc_mlp_forward(mA, feat, rows, qa);
      tc_mlp_forward(mB, feat, rows, qb);
      for (int r = 0; r < rows; r++) {
        int i = idx[lo + r];
        TcDeal *d = &e->g[i].d;
        const float *qr = ((d->cur & 1) == a_team[i] ? qa : qb) + (size_t)r * TC_NUM_ACTIONS;
        int nl = tc_legal(d, legal), best = legal[0];
        if (dup_temperature > 0.0 && nl > 1) {
          double mx = -1e300, z = 0.0, p[TC_NUM_ACTIONS];
          for (int t = 0; t < nl; t++) if (qr[legal[t]] > mx) mx = qr[legal[t]];
          for (int t = 0; t < nl; t++) { p[t] = exp((qr[legal[t]] - mx) / dup_temperature); z += p[t]; }
          double u = unit(&e->g[i].rng) * z, acc = 0.0;
          best = legal[nl - 1];
          for (int t = 0; t < nl; t++) { acc += p[t]; if (u < acc) { best = legal[t]; break; } }
        } else {
          for (int t = 1; t < nl; t++) if (qr[legal[t]] > qr[best]) best = legal[t];
        }
        tc_apply(d, best);
        record_if_done(e, i, total);
      }
      free(feat); free(qa); free(qb);
    TC_PARALLEL_END
  }
  for (int b = 0; b < n_base; b++) {
    double s = 0.0;
    for (int j = 0; j < 8; j++) { int g = 8 * b + j; s += a_team[g] == 0 ? total[g] : -total[g]; }
    value[b] = s / 8.0;
  }
  free(total); free(idx); free(a_team);
  return 0;
}

// Search-value labels (SP3): for each state, every legal action (network ids,
// at most max_k) is played out with the policy on all seats in W worlds: the
// true state (if include_true) and worlds sampled from the acting seat's
// observation (tc_sample_world, with the showing-fallback restrictions),
// finishing the last dd_left tricks exactly. q[s * max_k + j] is the acting
// team's mean match-equity change over the worlds; q_true the value in the
// true world alone (0 if include_true is off). e must hold the sum over states
// of W * k[s] games (with label sharing, fewer). Returns 0, -1 if some state
// admits no world, -2 if e is too small.
int tc_world_values(TcEnv *e, const TcMlp *m, const TcDeal *states, int n_states, int max_k, int W, int include_true,
                    int dd_left, uint64_t *rng, int32_t *actions, int32_t *k, float *q, float *q_true) {
  int legal[TC_NUM_ACTIONS_V2];
  for (int s = 0; s < n_states; s++) {
    int nl = tc_legal(&states[s], legal), kk = 0;
    for (int j = 0; j < nl && kk < max_k; j++) if (legal[j] < TC_NUM_ACTIONS) actions[s * max_k + kk++] = legal[j];
    k[s] = kk;
  }
  // Worlds first (sampling draws from rng, sequentially, so labels are reproducible).
  TcDeal *worlds = malloc(sizeof(TcDeal) * (size_t)n_states * W);
  for (int s = 0; s < n_states; s++) {
    TcObs ob;
    tc_observe(&states[s], states[s].cur, &ob);
    for (int w = 0; w < W; w++) {
      TcDeal *dst = &worlds[(size_t)s * W + w];
      if (include_true && w == 0) { *dst = states[s]; continue; }
      if (tc_sample_world(&ob, rng, dst) != 0) { free(worlds); return -1; }
    }
  }
  int total_games = 0;
  for (int s = 0; s < n_states; s++)
    for (int w = 0; w < W; w++)
      for (int j = 0; j < k[s]; j++) {
        const TcDeal *d = &worlds[(size_t)s * W + w];
        total_games += share_rep(d, actions[s * max_k + j]) == actions[s * max_k + j];
      }
  if (total_games > e->n) { free(worlds); return -2; }
  double *total = calloc((size_t)total_games, sizeof(double));
  int *idx = malloc(sizeof(int) * (size_t)total_games);
  int *slot = malloc(sizeof(int) * (size_t)n_states * W * max_k);
  int g = 0;
  for (int s = 0; s < n_states; s++)
    for (int w = 0; w < W; w++) {
      const TcDeal *d = &worlds[(size_t)s * W + w];
      int *sl = slot + ((size_t)s * W + w) * max_k;
      for (int j = 0; j < k[s]; j++) {
        int a = actions[s * max_k + j];
        if (share_rep(d, a) != a) continue;
        sl[j] = g;
        e->g[g].d = *d;
        e->g[g].live = 1;
        tc_apply(&e->g[g].d, a);
        record_if_done(e, g, total);
        g++;
      }
      for (int j = 0; j < k[s]; j++) {
        int a = actions[s * max_k + j], rep = share_rep(d, a);
        if (rep == a) continue;
        for (int r = 0; r < k[s]; r++) if (actions[s * max_k + r] == rep) { sl[j] = sl[r]; break; }
      }
    }
  play_out(e, m, total_games, dd_left, rng, total, idx, NULL, NULL);
  for (int s = 0; s < n_states; s++) {
    const double sign = (states[s].cur & 1) == 0 ? 1.0 : -1.0;
    for (int j = 0; j < k[s]; j++) {
      double sum = 0.0;
      for (int w = 0; w < W; w++) sum += total[slot[((size_t)s * W + w) * max_k + j]];
      q[s * max_k + j] = (float)(sign * sum / W);
      q_true[s * max_k + j] = include_true ? (float)(sign * total[slot[(size_t)s * W * max_k + j]]) : 0.0f;
    }
  }
  free(worlds); free(total); free(idx); free(slot);
  return 0;
}

// ------------------------------------------------------------- VRPO data
// On-policy trajectories for policy-gradient self-play (tuppi_ai/vrpo.py): n
// random deals, every network decision (showing and trick play) of all four
// seats sampled from softmax(logits / temperature) over the legal actions;
// sooli phases by the heuristics; no solver tail. Per recorded decision:
// packed actor features (big-endian bits, as numpy.packbits), the other three
// hands (relative seats 1..3, for the training-only critic), the packed legal
// mask, the action, its log-probability under the behaviour policy, the acting
// team, the deal index and the decision's step within its deal. reward[i] is
// deal i's team-0 match-equity change. Returns the number of rows.
int tc_ppo_rollouts(TcEnv *e, const TcMlp *m, int n, int ruleset, uint64_t *rng, double temperature, int max_rows,
                    uint8_t *feat_packed, uint64_t *hidden, uint8_t *mask_packed, uint8_t *action, float *logp,
                    int8_t *team, int32_t *deal, int16_t *step, float *reward) {
  if (n > e->n) return -2;
  random_deals(e, n, ruleset, rng);
  inc_reset(e, n);
  double *total = calloc((size_t)n, sizeof(double));
  int *idx = malloc(sizeof(int) * (size_t)n);
  int16_t *steps = calloc((size_t)n, sizeof(int16_t));
  const int enc = tc_mlp_encoder(m), dim = tc_feature_dim_v(enc), fb = (dim + 7) / 8, mb = (TC_NUM_ACTIONS + 7) / 8;
  TC_BLOCK int rows = 0;
  int *counter = &rows;
  for (;;) {
    int ns = 0;
    for (int i = 0; i < n; i++)
      if (e->g[i].d.phase >= TC_PH_SOOLI_OFFER) idx[ns++] = i;
    if (ns) TC_PARALLEL_BEGIN((size_t)ns, j) resolve_sooli(e, idx[j], &e->g[idx[j]].rng, total); TC_PARALLEL_END
    int live = 0;
    for (int i = 0; i < n; i++) if (e->g[i].d.phase != TC_PH_DONE) idx[live++] = i;
    if (!live) break;
    const int chunk = rollout_chunk;
    TC_PARALLEL_BEGIN((size_t)(live + chunk - 1) / chunk, c)
      int lo = (int)c * chunk, hi = lo + chunk < live ? lo + chunk : live, nrow = hi - lo;
      uint8_t *feat = malloc((size_t)nrow * dim);
      float *q = malloc(sizeof(float) * (size_t)nrow * TC_NUM_ACTIONS);
      int legal[TC_NUM_ACTIONS_V2];
      double p[TC_NUM_ACTIONS];
      TcObs ob;
      for (int r = 0; r < nrow; r++) {
        TcDeal *d = &e->g[idx[lo + r]].d;
        tc_observe(d, d->cur, &ob);
        tc_encode_v(&ob, feat + (size_t)r * dim, enc);
      }
      forward_games(e, m, idx + lo, nrow, feat, dim, q);
      for (int r = 0; r < nrow; r++) {
        const int i = idx[lo + r];
        TcGame *g = &e->g[i];
        TcDeal *d = &g->d;
        const float *qr = q + (size_t)r * TC_NUM_ACTIONS;
        int nl = tc_legal(d, legal);
        double mx = -1e300, z = 0.0;
        for (int t = 0; t < nl; t++) if (qr[legal[t]] > mx) mx = qr[legal[t]];
        for (int t = 0; t < nl; t++) { p[t] = exp((qr[legal[t]] - mx) / temperature); z += p[t]; }
        double u = unit(&g->rng) * z, acc = 0.0;
        int pick = nl - 1;
        for (int t = 0; t < nl; t++) { acc += p[t]; if (u < acc) { pick = t; break; } }
        const int slot = __atomic_fetch_add(counter, 1, __ATOMIC_RELAXED);
        if (slot < max_rows) {
          uint8_t *fp = feat_packed + (size_t)slot * fb, *mp = mask_packed + (size_t)slot * mb;
          memset(fp, 0, (size_t)fb);
          memset(mp, 0, (size_t)mb);
          const uint8_t *fr = feat + (size_t)r * dim;
          for (int j = 0; j < dim; j++) if (fr[j]) fp[j >> 3] |= (uint8_t)(0x80 >> (j & 7));
          for (int t = 0; t < nl; t++) mp[legal[t] >> 3] |= (uint8_t)(0x80 >> (legal[t] & 7));
          for (int k = 1; k < 4; k++) hidden[(size_t)slot * 3 + k - 1] = d->hand[(d->cur + k) & 3];
          action[slot] = (uint8_t)legal[pick];
          logp[slot] = (float)log(p[pick] / z);
          team[slot] = (int8_t)(d->cur & 1);
          deal[slot] = i;
          step[slot] = steps[i];
        }
        steps[i]++;
        tc_apply(d, legal[pick]);
        record_if_done(e, i, total);
      }
      free(feat);
      free(q);
    TC_PARALLEL_END
  }
  for (int i = 0; i < n; i++) reward[i] = (float)total[i];
  free(total); free(idx); free(steps);
  return rows < max_rows ? rows : max_rows;
}
