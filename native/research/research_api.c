// Research-only native API; see research_api.h.
//
// This file is compiled INSTEAD of tuppi_env.c into libtuppi_research.dylib: it
// includes the overlay-patched copy of tuppi_env.c (so it can reach the
// environment's private layout and the factored search) and adds research
// entrypoints. The build copies the pinned original sources, applies
// overlay.patch to the copy, and never writes native/libtuppi.dylib.
#include "tuppi_env.c"

#include <math.h>
#include <stddef.h>

#include "research_api.h"

#define FULL_DECK_R ((1ULL << 52) - 1)
#define SUIT_MASK_R(s) (0x1FFFULL << ((s) * 13))

int research_api_version(void) { return RESEARCH_API_VERSION; }

int research_get_rollout_chunk(void) { return rollout_chunk; }

#define DEAL_FIELDS(X) X(hand) X(dealer) X(phase) X(cur) X(n_shows) X(show_seat) X(show_card) \
  X(show_contract) X(show_verbal) X(contract) X(declarer) X(first_leader) X(n_played) X(play_card) \
  X(play_seat) X(team_tricks) X(score) X(winner_team) X(points) X(stolen) X(ruleset) X(trick_size) \
  X(n_decisions) X(decision_seat) X(decision_accept) X(soolaaja) X(given) X(returned) X(sooli_won)
#define OBS_FIELDS(X) X(hand) X(seat) X(dealer) X(phase) X(n_shows) X(show_seat) X(show_card) \
  X(show_contract) X(show_verbal) X(contract) X(declarer) X(first_leader) X(n_played) X(play_card) \
  X(play_seat) X(score) X(ruleset) X(trick_size) X(n_decisions) X(decision_seat) X(decision_accept) \
  X(soolaaja) X(known_given) X(known_returned)

// Layout record: api version, first byte of the uint32 0x01020304, sizeof
// TcDeal, its field count, each offset in declaration order, then the same for
// TcObs.
int research_abi_layout(int64_t *out, int cap) {
  int64_t buf[128];
  int n = 0;
  const uint32_t probe = 0x01020304u;
  buf[n++] = RESEARCH_API_VERSION;
  buf[n++] = *(const uint8_t *)&probe;
  buf[n++] = (int64_t)sizeof(TcDeal);
  int count_at = n++;
#define DEAL_OFF(f) buf[n++] = (int64_t)offsetof(TcDeal, f);
  DEAL_FIELDS(DEAL_OFF)
  buf[count_at] = n - count_at - 1;
  buf[n++] = (int64_t)sizeof(TcObs);
  count_at = n++;
#define OBS_OFF(f) buf[n++] = (int64_t)offsetof(TcObs, f);
  OBS_FIELDS(OBS_OFF)
  buf[count_at] = n - count_at - 1;
  if (!out || cap < n) return RESEARCH_BAD_DIMS;
  memcpy(out, buf, sizeof(int64_t) * (size_t)n);
  return n;
}

// Reason codes for research_world_consistent.
enum { WC_OK = 0, WC_ACTOR = 1, WC_PROJECTION = 2, WC_PARTITION = 3, WC_COUNTS = 4, WC_VOID = 5,
       WC_SHOWN = 6, WC_RANGE = 7, WC_TRICKS = 8, WC_BIDS = 9, WC_OBS = 10 };

// Range and self-consistency checks on an observation before any native use
// (the sampler copies n_played bytes and indexes by play seats unchecked).
int research_obs_valid(const TcObs *o) {
  if (!o) return 0;
  if (o->seat > 3 || o->dealer > 3 || o->phase > TC_PH_SOOLI_PLAY || o->phase == TC_PH_DONE) return 0;
  if (o->n_shows > 4 || o->n_played > 52 || o->n_decisions > 2) return 0;
  if (!(o->trick_size == 3 || o->trick_size == 4) || o->ruleset < 1 || o->ruleset > 3) return 0;
  if (o->contract < -1 || o->contract > 1 || o->declarer < -1 || o->declarer > 3 || o->first_leader > 3) return 0;
  if (o->soolaaja < -1 || o->soolaaja > 3 || o->known_given < -1 || o->known_given > 51 ||
      o->known_returned < -1 || o->known_returned > 51) return 0;
  if (o->hand & ~FULL_DECK_R) return 0;
  u64 played = 0;
  for (int i = 0; i < o->n_played; i++) {
    if (o->play_card[i] > 51 || o->play_seat[i] > 3) return 0;
    u64 b = 1ULL << o->play_card[i];
    if (played & b) return 0;
    played |= b;
  }
  if (o->hand & played) return 0;
  for (int i = 0; i < 4; i++)
    if (o->show_seat[i] > 3 || o->show_card[i] > 51 || o->show_contract[i] > 1 || o->show_verbal[i] > 1) return 0;
  for (int i = 0; i < 2; i++) if (o->decision_seat[i] > 3 || o->decision_accept[i] > 1) return 0;
  return 1;
}

// Trick totals and the current actor implied by a deal's public history.
static void implied_state(const TcDeal *w, int tricks[2], int *cur) {
  const int ts = w->trick_size == 3 ? 3 : 4, n = w->n_played;
  int leader = ts == 3 ? w->declarer : w->first_leader;
  tricks[0] = tricks[1] = 0;
  for (int t = 0; t + ts <= n; t += ts) {
    int led = w->play_card[t] / 13, best = t;
    for (int i = t + 1; i < t + ts; i++) {
      int c = w->play_card[i], b = w->play_card[best];
      int higher = ts == 3 ? tc_sooli_rank(c) > tc_sooli_rank(b) : c % 13 > b % 13;
      if (c / 13 == led && higher) best = i;
    }
    int winner = w->play_seat[best];
    tricks[winner & 1]++;
    leader = winner;
  }
  switch (w->phase) {
    case TC_PH_SHOW: *cur = (w->dealer + 1 + w->n_shows) & 3; break;
    case TC_PH_PLAY: { int pos = n & 3; *cur = pos ? ((w->play_seat[n - pos] + pos) & 3) : leader; break; }
    case TC_PH_SOOLI_OFFER: *cur = (w->declarer + (w->n_decisions ? 3 : 1)) & 3; break;
    case TC_PH_SOOLI_GIVE: *cur = w->soolaaja; break;
    case TC_PH_SOOLI_RETURN: *cur = (w->soolaaja + 2) & 3; break;
    case TC_PH_SOOLI_PLAY: {
      int pos = n % 3, lead = pos ? w->play_seat[n - pos] : leader;
      *cur = pos == 0 ? lead : pos == 1 ? ((lead + 2) & 3) : w->soolaaja;
      break;
    }
    default: *cur = -1;
  }
}

static int obs_equal(const TcObs *a, const TcObs *b) {
  if (a->hand != b->hand || a->seat != b->seat || a->dealer != b->dealer || a->phase != b->phase) return 0;
  if (a->n_shows != b->n_shows) return 0;
  if (memcmp(a->show_seat, b->show_seat, 4) || memcmp(a->show_card, b->show_card, 4) ||
      memcmp(a->show_contract, b->show_contract, 4) || memcmp(a->show_verbal, b->show_verbal, 4)) return 0;
  if (a->contract != b->contract || a->declarer != b->declarer || a->first_leader != b->first_leader) return 0;
  if (a->n_played != b->n_played) return 0;
  if (memcmp(a->play_card, b->play_card, a->n_played) || memcmp(a->play_seat, b->play_seat, a->n_played)) return 0;
  if (a->score[0] != b->score[0] || a->score[1] != b->score[1]) return 0;
  if (a->ruleset != b->ruleset || a->trick_size != b->trick_size || a->n_decisions != b->n_decisions) return 0;
  for (int i = 0; i < a->n_decisions && i < 2; i++)
    if (a->decision_seat[i] != b->decision_seat[i] || a->decision_accept[i] != b->decision_accept[i]) return 0;
  return a->soolaaja == b->soolaaja && a->known_given == b->known_given && a->known_returned == b->known_returned;
}

int research_world_consistent(const TcObs *o, const TcDeal *w) {
  if (!o || !w) return WC_RANGE;
  if (!research_obs_valid(o)) return WC_OBS;
  if (w->n_played > 52 || w->n_shows > 4 || w->cur > 3 || w->dealer > 3 || w->n_decisions > 2) return WC_RANGE;
  if (w->phase > TC_PH_SOOLI_PLAY || w->phase == TC_PH_DONE) return WC_RANGE;
  if (w->cur != o->seat) return WC_ACTOR;
  TcObs ob;
  tc_observe(w, o->seat, &ob);
  if (!obs_equal(&ob, o)) return WC_PROJECTION;
  u64 played = 0, seen = 0;
  int played_by[4] = {0, 0, 0, 0};
  for (int i = 0; i < w->n_played; i++) {
    if (w->play_card[i] > 51 || w->play_seat[i] > 3) return WC_RANGE;
    u64 b = 1ULL << w->play_card[i];
    if (played & b) return WC_PARTITION;
    played |= b;
    played_by[w->play_seat[i]]++;
  }
  for (int s = 0; s < 4; s++) {
    if ((w->hand[s] & ~FULL_DECK_R) || (w->hand[s] & (seen | played))) return WC_PARTITION;
    seen |= w->hand[s];
  }
  if ((seen | played) != FULL_DECK_R) return WC_PARTITION;
  if (w->soolaaja > 3 || w->declarer > 3 || w->n_shows > 4) return WC_RANGE;
  for (int s = 0; s < 4; s++) {
    int want = 13 - played_by[s];
    if (w->phase == TC_PH_SOOLI_RETURN && s == w->soolaaja) want -= 1;          // gave one, not yet returned
    if (w->phase == TC_PH_SOOLI_RETURN && s == ((w->soolaaja + 2) & 3)) want += 1;
    if (__builtin_popcountll(w->hand[s]) != want) return WC_COUNTS;
  }
  int tricks[2], cur;
  implied_state(w, tricks, &cur);
  if (tricks[0] != w->team_tricks[0] || tricks[1] != w->team_tricks[1]) return WC_TRICKS;
  if (cur != w->cur) return WC_ACTOR;
  if (w->phase == TC_PH_SHOW)  // every bid, hidden or not, legal from its bidder's (original) hand in order
    for (int i = 0; i < w->n_shows; i++) {
      int s = w->show_seat[i], c = w->show_card[i], k = w->show_contract[i];
      if (s != ((w->dealer + 1 + i) & 3) || k > 1 || c > 51) return WC_BIDS;
      if (k != TC_NOLO) return WC_BIDS;  // during showing every bid so far was NOLO (a RAMI ends it)
      if (!(tc_valid_show_cards(w->hand[s], k) >> c & 1ULL)) return WC_BIDS;
      if (w->show_verbal[i] != tc_verbal_required(c, k)) return WC_BIDS;
    }
  const int ts = w->trick_size == 3 ? 3 : 4;
  for (int t = 0; t < w->n_played; t += ts) {
    int led = w->play_card[t] / 13;
    for (int i = t + 1; i < w->n_played && i < t + ts; i++)
      if (w->play_card[i] / 13 != led && (w->hand[w->play_seat[i]] & SUIT_MASK_R(led))) return WC_VOID;
  }
  if (w->soolaaja < 0 && !(w->ruleset == 3 && w->phase == TC_PH_SHOW))
    for (int i = 0; i < w->n_shows; i++) {
      int c = w->show_card[i];
      if (!(played >> c & 1ULL) && !(w->hand[w->show_seat[i]] >> c & 1ULL)) return WC_SHOWN;
    }
  return WC_OK;
}

static u64 slot_digest(const TcEnv *e) {
  u64 h = 0xcbf29ce484222325ULL;
  for (int i = 0; i < e->n; i++) {
    u64 parts[3] = {e->g[i].rng, (u64)(uint32_t)e->g[i].live, (u64)(uint32_t)e->g[i].deals_in_match};
    for (int p = 0; p < 3; p++)
      for (int b = 0; b < 8; b++) { h ^= (parts[p] >> (8 * b)) & 0xFF; h *= 0x100000001b3ULL; }
  }
  return h;
}

int research_env_config(const void *env, double *out, int cap) {
  const TcEnv *e = env;
  if (!e || !out) return RESEARCH_NULL;
  if (cap < RESEARCH_CFG_LEN) return RESEARCH_BAD_DIMS;
  u64 dg = slot_digest(e);
  out[0] = RESEARCH_CFG_VERSION;
  out[1] = e->n;
  out[2] = e->encoder;
  out[3] = e->single_deal;
  out[4] = e->p_random_start;
  out[5] = e->sooli_belief;
  out[6] = e->sooli_return_pi;
  out[7] = e->sooli_play_heur;
  out[8] = e->sooli_lambda;
  out[9] = rollout_chunk;
  out[10] = (double)(dg >> 32);
  out[11] = (double)(dg & 0xFFFFFFFFULL);
  memcpy(out + 12, e->eq, sizeof e->eq);
  return RESEARCH_CFG_LEN;
}

int research_env_import_config(void *env, const double *cfg, int len) {
  TcEnv *e = env;
  if (!e || !cfg) return RESEARCH_NULL;
  if (len != RESEARCH_CFG_LEN || cfg[0] != RESEARCH_CFG_VERSION || cfg[1] != e->n) return RESEARCH_BAD_DIMS;
  if (!(cfg[2] == 1 || cfg[2] == 2)) return RESEARCH_BAD_DIMS;
  for (int i = 4; i < RESEARCH_CFG_LEN; i++) if (!isfinite(cfg[i])) return RESEARCH_NONFINITE;
  e->encoder = (int)cfg[2];
  e->single_deal = (int)cfg[3];
  e->p_random_start = cfg[4];
  e->sooli_belief = (int)cfg[5];
  e->sooli_return_pi = (int)cfg[6];
  e->sooli_play_heur = (int)cfg[7];
  e->sooli_lambda = cfg[8];
  memcpy(e->eq, cfg + 12, sizeof e->eq);
  return RESEARCH_OK;
}

static int check_options(int options) { return (options & ~RESEARCH_OPT_UTILITY_STOP) == 0; }

static int check_dims(int k, int w, int dd_left) {
  if (w < 1 || w > RESEARCH_MAX_WORLDS || k < 1 || k > TC_NUM_ACTIONS_V2) return 0;
  if (dd_left < 0 || dd_left > 13) return 0;
  // w <= 4096 and k <= 210 already bound w * k; the explicit check guards future cap changes.
  if ((long long)w * (long long)k > (long long)INT32_MAX) return 0;
  return 1;
}

int research_sample_worlds(const void *env, const TcObs *o, int w, uint64_t *rng, TcDeal *out, int out_cap,
                           int *drawn) {
  const TcEnv *e = env;
  if (drawn) *drawn = 0;
  if (!e || !o || !rng || !out) return RESEARCH_NULL;
  if (w < 1 || w > RESEARCH_MAX_WORLDS || out_cap < w) return RESEARCH_BAD_DIMS;
  if (!research_obs_valid(o)) return RESEARCH_BAD_OBS;
  for (int wi = 0; wi < w; wi++) {
    if (tc_sample_world_sooli(o, rng, &out[wi], e->sooli_belief, e->sooli_lambda) != 0) return RESEARCH_NO_WORLD;
    if (drawn) *drawn = wi + 1;
  }
  return RESEARCH_OK;
}

static int finite_outputs(const double *values, int k, const double *per_world, int n) {
  for (int a = 0; a < k; a++) if (!isfinite(values[a])) return 0;
  if (per_world) for (int i = 0; i < n; i++) if (!isfinite(per_world[i])) return 0;
  return 1;
}

int research_trace_search(void *env, const void *mlp, const TcObs *o, const int32_t *actions, int k, int w,
                          int dd_left, int options, uint64_t *rng, double *values, double *per_world,
                          uint8_t *row_status, int cell_cap, TcDeal *worlds_out, int worlds_cap, int64_t *work) {
  TcEnv *e = env;
  if (!e || !mlp || !o || !actions || !rng || !values) return RESEARCH_NULL;
  if (!check_dims(k, w, dd_left) || !check_options(options)) return RESEARCH_BAD_DIMS;
  if (!research_obs_valid(o)) return RESEARCH_BAD_OBS;
  const int n = w * k;
  if ((per_world || row_status) && cell_cap < n) return RESEARCH_BAD_DIMS;
  if (worlds_out && worlds_cap < w) return RESEARCH_BAD_DIMS;
  if (n > e->n) return RESEARCH_ENV_TOO_SMALL;
  TcResearchCtx ctx;
  memset(&ctx, 0, sizeof ctx);
  ctx.row_status = row_status;
  ctx.options = options;
  if (row_status) memset(row_status, 0, (size_t)n);
  if (sample_root_worlds(e, o, k, w, rng, worlds_out) != 0) return RESEARCH_NO_WORLD;
  int rc = continue_rollouts(e, mlp, o, actions, k, w, dd_left, rng, values, per_world, &ctx);
  if (work) memcpy(work, ctx.work, sizeof ctx.work);
  if (rc == 0 && !finite_outputs(values, k, per_world, n)) return RESEARCH_NONFINITE;
  return rc;
}

int research_evaluate_worlds(void *env, const void *mlp, const TcObs *o, const TcDeal *worlds, int w,
                             const int32_t *actions, int k, int dd_left, int options, uint64_t *cont_rng,
                             double *values, double *per_world, uint8_t *row_status, int cell_cap, int64_t *work,
                             int *bad_world) {
  TcEnv *e = env;
  if (bad_world) *bad_world = -1;
  if (!e || !mlp || !o || !worlds || !actions || !cont_rng || !values) return RESEARCH_NULL;
  if (!check_dims(k, w, dd_left) || !check_options(options)) return RESEARCH_BAD_DIMS;
  if (!research_obs_valid(o)) return RESEARCH_BAD_OBS;
  const int n = w * k;
  if ((per_world || row_status) && cell_cap < n) return RESEARCH_BAD_DIMS;
  if (n > e->n) return RESEARCH_ENV_TOO_SMALL;
  for (int wi = 0; wi < w; wi++)
    if (research_world_consistent(o, &worlds[wi]) != WC_OK) {
      if (bad_world) *bad_world = wi;
      return RESEARCH_WORLD_MISMATCH;
    }
  TcResearchCtx ctx;
  memset(&ctx, 0, sizeof ctx);
  ctx.row_status = row_status;
  ctx.options = options;
  if (row_status) memset(row_status, 0, (size_t)n);
  for (int wi = 0; wi < w; wi++)
    for (int ai = 0; ai < k; ai++) { e->g[wi * k + ai].d = worlds[wi]; e->g[wi * k + ai].live = 1; }
  int rc = continue_rollouts(e, mlp, o, actions, k, w, dd_left, cont_rng, values, per_world, &ctx);
  if (work) memcpy(work, ctx.work, sizeof ctx.work);
  if (rc == 0 && !finite_outputs(values, k, per_world, n)) return RESEARCH_NONFINITE;
  return rc;
}

int research_row_utility(const void *env, const TcDeal *d, int team0_tricks, float *out) {
  const TcEnv *e = env;
  if (!e || !d || !out) return RESEARCH_NULL;
  if (team0_tricks < 0 || team0_tricks > 13 || d->contract < 0 || d->contract > 1) return RESEARCH_BAD_DIMS;
  TcDeal c = *d;
  tc_finish_with_tricks(&c, team0_tricks);
  uint8_t after[2];
  tc_next_score(c.score, c.winner_team, c.points, after);
  *out = (float)(equity0(e, after[0], after[1], c.dealer + 1) - equity0(e, c.score[0], c.score[1], c.dealer));
  return RESEARCH_OK;
}

int research_utility_certificate(const void *env, const TcDeal *d, float *out) {
  if (!env || !d || !out) return RESEARCH_NULL;
  return utility_certificate(env, d, out);
}
