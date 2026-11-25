// Training-only build of the batched environment (training/README.md).
//
// This file is compiled INSTEAD of ai/native/tuppi_env.c, which it includes
// unchanged. It does two things the hosted build must not do:
//
//  1. The index-parallel loops of tuppi_env.c (TC_PARALLEL_BEGIN: self-play,
//     PPO rollouts, duplicate evaluation, solver tails) run on OpenMP threads.
//     The hosted Linux build runs them as plain loops. Every loop writes
//     disjoint outputs per index (tuppi_parallel.h), so the results are the
//     same; tc_set_parallel(0) still turns the threads off.
//  2. It adds the tc_ls_* "lockstep" functions: the engine steps the games,
//     the caller evaluates the network (on a GPU) and chooses the actions.
//     They need the file-local helpers of tuppi_env.c, hence the inclusion.
//
// Nothing here is part of the qualified hosted library.
#include "tuppi_parallel.h"
#undef TC_PARALLEL_BEGIN
#undef TC_PARALLEL_END
#define TC_PARALLEL_BEGIN(count, index) \
  _Pragma("omp parallel for schedule(dynamic, 1) if(tc_parallel_loops)") \
  for (size_t index = 0; index < (size_t)(count); ++index) {
#define TC_PARALLEL_END }

#include "tuppi_env.c"

#include <omp.h>

#ifdef TC_HOSTED_BLAS
void openblas_set_num_threads(int n);
#endif

// Call once, on the main thread, before anything else. Fills the once-only
// table of tuppi_search.c (its portable build assumes one thread; the sooli
// offer heuristic reaches it from the parallel loops) and keeps OpenBLAS to
// one thread per caller, whatever the environment variables say.
void tc_train_init(void) {
  uint64_t hands[4] = {0, 0, 0, 0};
  for (int c = 0; c < 52; c++) hands[c & 3] |= 1ULL << c;
  TcDeal d, w;
  TcObs o;
  uint64_t r = 0x9E3779B97F4A7C15ULL;
  tc_deal_init_v(&d, hands, 0, 0, 0, 3);
  tc_observe(&d, d.cur, &o);
  tc_sample_world(&o, &r, &w);
#ifdef TC_HOSTED_BLAS
  openblas_set_num_threads(1);
#endif
}

int tc_train_threads(void) { return tc_parallel_loops ? omp_get_max_threads() : 1; }
void tc_train_set_threads(int n) { if (n > 0) omp_set_num_threads(n); }

// ------------------------------------------------------------------ lockstep
// n random deals, exactly as tc_ppo_rollouts draws them (same hands, dealers,
// scores and per-game seeds from the same rng state).
int tc_ls_begin(TcEnv *e, int n, int ruleset, uint64_t *rng) {
  if (n > e->n) return -2;
  random_deals(e, n, ruleset, rng);
  return 0;
}

// The deals of tc_duplicate_eval: every base deal 4 rotations x 2 team
// assignments, dealer 0, from the given score; a_team[g] is the team that
// plays network A in game g. The rng advances exactly as in tc_duplicate_eval.
// paired != 0: the two team assignments of a rotation share one seed, so the
// heuristics' random draws (sooli offers) are common to both and a policy
// against itself scores exactly zero. paired == 0 reproduces the native seeds.
int tc_ls_begin_duplicate(TcEnv *e, int n_base, int ruleset, int score0, int score1, int paired, uint64_t *rng,
                          int8_t *a_team) {
  const int n = 8 * n_base;
  if (n > e->n) return -2;
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
        if (paired && t == 1) e->g[g].rng = e->g[g - 1].rng;
        a_team[g] = (int8_t)t;
      }
  }
  return 0;
}

// Offer recording for the fast offer model's training data (tc_ls_observe).
typedef struct {
  uint8_t *feat;   // packed encoder-1 observations, (tc_feature_dim() + 7) / 8 bytes per row
  uint8_t *label;  // 1 = the heuristic accepted
  int max_rows;
  int rows;        // written with atomics
} OfferRec;

// 8 feature bytes (each 0 or 1) -> one byte, first feature in the top bit, as
// numpy.packbits and tc_ppo_rollouts pack them.
static inline void pack_bits(const uint8_t *src, int dim, uint8_t *dst) {
  int j = 0, b = 0;
  for (; j + 8 <= dim; j += 8, b++) {
    uint64_t x;
    memcpy(&x, src + j, 8);
    if (x & 0xFEFEFEFEFEFEFEFEULL) {  // not 0/1 bytes: the plain definition
      uint8_t v = 0;
      for (int k = 0; k < 8; k++) if (src[j + k]) v |= (uint8_t)(0x80 >> k);
      dst[b] = v;
    } else {
      dst[b] = (uint8_t)((x * 0x8040201008040201ULL) >> 56);
    }
  }
  if (j < dim) {
    uint8_t v = 0;
    for (int k = 0; j + k < dim; k++) if (src[j + k]) v |= (uint8_t)(0x80 >> k);
    dst[b] = v;
  }
}

// resolve_sooli (tuppi_env.c) with the offers recorded: the same decisions
// from the same draws; for every offer whose hand passes the prefilter, the
// defender's encoder-1 observation and the answer.
static void resolve_sooli_rec(TcEnv *e, int i, uint64_t *rng, double *total, OfferRec *rec) {
  TcDeal *d = &e->g[i].d;
  while (d->phase == TC_PH_SOOLI_OFFER || d->phase == TC_PH_SOOLI_GIVE || d->phase == TC_PH_SOOLI_RETURN) {
    TcObs ob;
    tc_observe(d, d->cur, &ob);
    const int offer = d->phase == TC_PH_SOOLI_OFFER;
    int a = d->phase == TC_PH_SOOLI_RETURN && e->sooli_return_pi ? pi_return(d, rng) : tc_sooli_policy(&ob, rng);
    if (offer && tc_sooli_offer_prefilter(ob.hand)) {
      const int slot = __atomic_fetch_add(&rec->rows, 1, __ATOMIC_RELAXED);
      if (slot < rec->max_rows) {
        uint8_t f[2048];
        const int dim = tc_feature_dim();
        tc_encode(&ob, f);
        pack_bits(f, dim, rec->feat + (size_t)slot * ((dim + 7) / 8));
        rec->label[slot] = a == TC_ACT_SOOLI_ACCEPT;
      }
    }
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

// One lockstep observation of games 0..n-1. First the games in a sooli phase
// are resolved by the heuristics, as tc_ppo_rollouts and tc_duplicate_eval do
// (each game with its own rng; a deal that ends there adds its team-0 equity
// change to total[i]). Then, for every game that is not finished, in game
// order: idx[r] = the game, and row r of
//   feat_packed  the actor's observation, encoder `encoder`, packed bits
//   mask_packed  its legal network actions, packed bits
//   hidden       the other three hands, relative seats 1..3 (may be NULL)
//   team         the acting team (may be NULL)
// Forced decisions (one legal action) are rows like any other. Returns the
// number of rows. offer_* (may be NULL / 0): the prefiltered offers answered
// in this call are appended, *offer_rows counts them (it may exceed
// offer_max; only offer_max are stored). seconds (may be NULL): [0] += time in
// the sooli part, [1] += time in the encoding part.
int tc_ls_observe(TcEnv *e, int n, int encoder, double *total, int32_t *idx, uint8_t *feat_packed,
                  uint8_t *mask_packed, uint64_t *hidden, int8_t *team, uint8_t *offer_feat, uint8_t *offer_label,
                  int offer_max, int *offer_rows, double *seconds) {
  if (n > e->n) return -2;
  const double t0 = omp_get_wtime();
  int ns = 0;
  for (int i = 0; i < n; i++)
    if (e->g[i].d.phase >= TC_PH_SOOLI_OFFER) idx[ns++] = i;
  if (ns) {
    if (offer_feat) {
      OfferRec rec = {offer_feat, offer_label, offer_max, offer_rows ? *offer_rows : 0};
      OfferRec *rp = &rec;
      TC_PARALLEL_BEGIN((size_t)ns, j) resolve_sooli_rec(e, idx[j], &e->g[idx[j]].rng, total, rp); TC_PARALLEL_END
      if (offer_rows) *offer_rows = rec.rows;
    } else {
      TC_PARALLEL_BEGIN((size_t)ns, j) resolve_sooli(e, idx[j], &e->g[idx[j]].rng, total); TC_PARALLEL_END
    }
  }
  const double t1 = omp_get_wtime();
  int live = 0;
  for (int i = 0; i < n; i++) if (e->g[i].d.phase != TC_PH_DONE) idx[live++] = i;
  const int dim = tc_feature_dim_v(encoder), fb = (dim + 7) / 8, mb = (TC_NUM_ACTIONS + 7) / 8;
  const int chunk = 256;
  TC_PARALLEL_BEGIN((size_t)(live + chunk - 1) / chunk, c)
    const int lo = (int)c * chunk, hi = lo + chunk < live ? lo + chunk : live;
    uint8_t feat[4096];
    int legal[TC_NUM_ACTIONS_V2];
    TcObs ob;
    for (int r = lo; r < hi; r++) {
      const TcDeal *d = &e->g[idx[r]].d;
      tc_observe(d, d->cur, &ob);
      tc_encode_v(&ob, feat, encoder);
      pack_bits(feat, dim, feat_packed + (size_t)r * fb);
      uint8_t *mp = mask_packed + (size_t)r * mb;
      memset(mp, 0, (size_t)mb);
      const int nl = tc_legal(d, legal);
      for (int t = 0; t < nl; t++) mp[legal[t] >> 3] |= (uint8_t)(0x80 >> (legal[t] & 7));
      if (hidden) for (int k = 1; k < 4; k++) hidden[(size_t)r * 3 + k - 1] = d->hand[(d->cur + k) & 3];
      if (team) team[r] = (int8_t)(d->cur & 1);
    }
  TC_PARALLEL_END
  if (seconds) { seconds[0] += t1 - t0; seconds[1] += omp_get_wtime() - t1; }
  return live;
}

// Applies actions[r] to game idx[r] for r < k; a deal that ends adds its
// team-0 equity change to total. burn_rng != 0 draws one number from each
// game's stream first, as tc_ppo_rollouts does for its own sampling, so that
// a replay of its actions leaves every stream where it left it. Returns the
// number of illegal actions (those games are left as they were).
int tc_ls_step(TcEnv *e, const int32_t *idx, const uint8_t *actions, int k, double *total, int burn_rng) {
  int illegal = 0;
  for (int r = 0; r < k; r++) {
    const int i = idx[r];
    TcGame *g = &e->g[i];
    if (burn_rng) unit(&g->rng);
    if (g->d.phase == TC_PH_DONE || tc_apply(&g->d, actions[r]) != 0) { illegal++; continue; }
    record_if_done(e, i, total);
  }
  return illegal;
}

// Counts for the statistical tests: for games 0..n-1, out[0] finished deals,
// out[1] RAMI contracts, out[2] deals in which a sooli was played, out[3]
// deals won by team 0.
void tc_ls_summary(const TcEnv *e, int n, int32_t *out) {
  out[0] = out[1] = out[2] = out[3] = 0;
  for (int i = 0; i < n; i++) {
    const TcDeal *d = &e->g[i].d;
    if (d->phase != TC_PH_DONE) continue;
    out[0]++;
    out[1] += d->contract == TC_RAMI;
    out[2] += d->soolaaja >= 0;
    out[3] += d->winner_team == 0;
  }
}

// ------------------------------------------------------------ branch labels
// Counterfactual labels (ai/tuppi_ai/selfplay.py; tc_branch_values) with the
// network outside the engine: record full states during lockstep self-play,
// load every (state, legal action) into play-out slots, play them out with the
// lockstep calls, read each action's result from total[].

// The full states of games idx[0..k), before their next action.
void tc_ls_copy_states(const TcEnv *e, const int32_t *idx, int k, TcDeal *out) {
  for (int r = 0; r < k; r++) out[r] = e->g[idx[r]].d;
}

// Position class (tc_record_class) and cards played so far, per game.
void tc_ls_classes(const TcEnv *e, const int32_t *idx, int k, int8_t *cls, uint8_t *n_played) {
  for (int r = 0; r < k; r++) {
    const TcDeal *d = &e->g[idx[r]].d;
    if (cls) cls[r] = (int8_t)record_class(d);
    if (n_played) n_played[r] = d->n_played;
  }
}

// As the first half of tc_branch_values: for each state its legal network
// actions (at most max_k) in actions/k, and one play-out game per action (one
// per run of rank-equivalent cards while tc_set_branch_share is on) with the
// action applied; slot[s * max_k + j] is the game of state s's j-th action. A
// deal the action ends is added to total[] at once; total[0..games) must be
// zero on entry. Every game of state s gets the stream seeds[s], so the
// heuristics' draws are common to its actions and nothing depends on what the
// slots held before. Returns the number of games, or -2 if e is too small.
int tc_ls_branch_begin(TcEnv *e, const TcDeal *states, int n_states, int max_k, const uint64_t *seeds,
                       int32_t *actions, int32_t *k, int32_t *slot, double *total) {
  int total_games = 0, legal[TC_NUM_ACTIONS_V2];
  for (int s = 0; s < n_states; s++) {
    int nl = tc_legal(&states[s], legal), kk = 0;
    for (int j = 0; j < nl && kk < max_k; j++) if (legal[j] < TC_NUM_ACTIONS) actions[s * max_k + kk++] = legal[j];
    k[s] = kk;
    for (int j = 0; j < kk; j++) total_games += share_rep(&states[s], actions[s * max_k + j]) == actions[s * max_k + j];
  }
  if (total_games > e->n) return -2;
  int g = 0;
  for (int s = 0; s < n_states; s++)
    for (int j = 0; j < k[s]; j++) {
      int a = actions[s * max_k + j];
      if (share_rep(&states[s], a) != a) continue;
      slot[s * max_k + j] = g;
      e->g[g].d = states[s];
      e->g[g].live = 1;
      e->g[g].rng = seeds[s] | 1;
      tc_apply(&e->g[g].d, a);
      record_if_done(e, g, total);
      g++;
    }
  for (int s = 0; s < n_states; s++)  // copies point at their representative's play-out
    for (int j = 0; j < k[s]; j++) {
      int a = actions[s * max_k + j], rep = share_rep(&states[s], a);
      if (rep == a) continue;
      for (int r = 0; r < k[s]; r++) if (actions[s * max_k + r] == rep) { slot[s * max_k + j] = slot[s * max_k + r]; break; }
    }
  return total_games;
}

// What play_out does before each network step, for games 0..n-1: sooli phases
// by the heuristics (each game's own stream), then, if dd_left > 0, every game
// in trick play with at most dd_left tricks left (plus tc_set_dd_extra_nolo in
// NOLO) is finished with its perfect-information result. Finished deals are
// added to total[]. Call it before tc_ls_observe in a play-out with a solver
// tail. seconds (may be NULL): [0] += sooli time, [1] += solver time.
void tc_ls_resolve(TcEnv *e, int n, int dd_left, double *total, int32_t *scratch, double *seconds) {
  const double t0 = omp_get_wtime();
  int ns = 0;
  for (int i = 0; i < n; i++)
    if (e->g[i].d.phase >= TC_PH_SOOLI_OFFER) scratch[ns++] = i;
  if (ns) TC_PARALLEL_BEGIN((size_t)ns, j) resolve_sooli(e, scratch[j], &e->g[scratch[j]].rng, total); TC_PARALLEL_END
  const double t1 = omp_get_wtime();
  if (dd_left > 0) {
    int todo = 0;
    for (int i = 0; i < n; i++) {
      const TcDeal *d = &e->g[i].d;
      if (d->phase == TC_PH_PLAY && 13 - (d->n_played >> 2) <= dd_left + (d->contract == TC_NOLO ? dd_extra_nolo : 0))
        scratch[todo++] = i;
    }
    if (todo)
      TC_PARALLEL_BEGIN((size_t)(todo + 31) / 32, c)
        const int lo = (int)c * 32, hi = lo + 32 < todo ? lo + 32 : todo;
        for (int j = lo; j < hi; j++) {
          TcDeal *d = &e->g[scratch[j]].d;
          tc_finish_with_tricks(d, tc_dd_team0_tricks(d));
          record_if_done(e, scratch[j], total);
        }
      TC_PARALLEL_END
  }
  if (seconds) { seconds[0] += t1 - t0; seconds[1] += omp_get_wtime() - t1; }
}
