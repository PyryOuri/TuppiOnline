// Batched self-play environment: N independent matches stepped in lockstep.
// Every live game always has exactly one actor waiting, so one call observes N
// decisions and one call applies N actions.
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
  int acts[TC_NUM_ACTIONS];
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
    for (int j = 0; j < k; j++) mask[(size_t)i * TC_NUM_ACTIONS + acts[j]] = 1;
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
  int finished = 0;
  for (int i = 0; i < e->n; i++) {
    TcGame *g = &e->g[i];
    done[i] = 0;
    delta0[i] = 0.f;
    TcDeal *d = &g->d;
    if (!g->live || d->phase != TC_PH_PLAY) continue;
    if (13 - (d->n_played >> 2) > dd_left) continue;
    tc_finish_with_tricks(d, tc_dd_team0_tricks(d));
    uint8_t after[2];
    tc_next_score(d->score, d->winner_team, d->points, after);
    done[i] = 1;
    delta0[i] = (float)(equity0(e, after[0], after[1], d->dealer + 1) - equity0(e, d->score[0], d->score[1], d->dealer));
    finished++;
  }
  return finished;
}
