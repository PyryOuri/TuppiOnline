// Batched self-play environment: N independent matches stepped in lockstep.
// Every live game always has exactly one actor waiting, so one call observes N
// decisions and one call applies N actions.
#include <dispatch/dispatch.h>
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
} TcEnv;

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

void tc_env_free(TcEnv *e) { free(e->g); free(e); }
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
    dispatch_apply(chunks, dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^(size_t c) {
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
    });
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
// finished by the perfect-information solver. Serial: it is rare and uses rng.
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
  const int enc = tc_mlp_encoder(m), dim = tc_feature_dim_v(enc);
  for (;;) {
    for (int i = 0; i < n; i++)
      if (e->g[i].d.phase >= TC_PH_SOOLI_OFFER) resolve_sooli(e, i, rng, total);
    if (dd_left > 0) {
      int todo = 0;
      for (int i = 0; i < n; i++) {
        TcDeal *d = &e->g[i].d;
        if (d->phase == TC_PH_PLAY && 13 - (d->n_played >> 2) <= dd_left) idx[todo++] = i;
      }
      if (todo) {
        dispatch_apply((size_t)(todo + 31) / 32, dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^(size_t c) {
          int lo = (int)c * 32, hi = lo + 32 < todo ? lo + 32 : todo;
          for (int j = lo; j < hi; j++) {
            TcDeal *d = &e->g[idx[j]].d;
            tc_finish_with_tricks(d, tc_dd_team0_tricks(d));
            record_if_done(e, idx[j], total);
          }
        });
      }
    }
    int live = 0;
    for (int i = 0; i < n; i++) if (e->g[i].d.phase != TC_PH_DONE) idx[live++] = i;
    if (!live) break;
    const int chunk = 32;
    dispatch_apply((size_t)(live + chunk - 1) / chunk, dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^(size_t c) {
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
      tc_mlp_forward(m, feat, rows, q);
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
    });
  }
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
