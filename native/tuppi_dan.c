#include <math.h>
#include <stddef.h>
#include <string.h>
#include "tuppi_dan.h"

void tc_env_set_encoder(TcEnv *, int);
void tc_env_set_team_rollout(TcEnv *, const TcMlp *);
void tc_env_set_value(TcEnv *, const TcMlp *, int, int, int);
void tc_env_set_belief(TcEnv *, const TcMlp *, int, double, double, int);
void tc_env_set_exact_speed(TcEnv *, int);
int tc_search_world_values(TcEnv *, const TcMlp *, const TcObs *, const int32_t *, int, int,
                           int, uint64_t *, double *, double *);

static int high(int id) { return id >= 0 && id < 52 && id % 13 >= 11; }
void tc_dan_default_config(TcDanConfig *out) {
  if (out) *out = (TcDanConfig){64, .03, .02, .05, 2.0, 1e-12, 14.0};
}
int tc_dan_config_valid(const TcDanConfig *c) {
  return c && c->worlds >= 2 && c->worlds <= TC_DAN_MAX_WORLDS &&
    isfinite(c->lead_loss) && c->lead_loss >= 0 && c->lead_loss <= 1 &&
    isfinite(c->second_loss) && c->second_loss >= 0 && c->second_loss <= c->lead_loss &&
    isfinite(c->deal_loss) && c->deal_loss >= 0 && c->deal_loss <= 1 &&
    isfinite(c->uncertainty) && c->uncertainty >= 0 && c->uncertainty <= 10 &&
    isfinite(c->epsilon) && c->epsilon >= 0 && c->epsilon <= 1e-6 &&
    isfinite(c->rami_margin) && c->rami_margin >= 0 && c->rami_margin <= 20;
}

int tc_dan_bid_select(const int32_t *ids, int k, const float *scores, double margin, TcDanBidResult *r) {
  if (!r) return -1;
  memset(r, 0, sizeof *r);
  r->action = r->nelli_action = r->nolo_action = r->rami_action = -1;
  r->margin = margin;
  if (!ids || !scores || k < 1 || k > 26 || !isfinite(margin) || margin < 0 || margin > 20) return -1;
  int best = -1;
  for (int i = 0; i < k; i++) {
    int a = ids[i];
    if (a < 52 || a >= 156 || !isfinite(scores[a])) return -1;
    for (int j = 0; j < i; j++) if (ids[j] == a) return -1;
    if (best < 0 || scores[a] > scores[best] || (scores[a] == scores[best] && a < best)) best = a;
    int *slot = a < 104 ? &r->nolo_action : &r->rami_action;
    if (*slot < 0 || scores[a] > scores[*slot] || (scores[a] == scores[*slot] && a < *slot)) *slot = a;
  }
  r->action = r->nelli_action = best;
  if (r->nolo_action >= 0) r->nolo_score = scores[r->nolo_action];
  if (r->rami_action >= 0) r->rami_score = scores[r->rami_action];
  if (r->nolo_action < 0 || r->rami_action < 0) { r->reason = TC_DAN_BID_FORCED; return 0; }
  r->gap = r->rami_score - r->nolo_score;
  if (best < 104) r->reason = TC_DAN_BID_NELLI_NOLO;
  else if (r->gap < margin) { r->action = r->nolo_action; r->reason = TC_DAN_BID_VETO; }
  else r->reason = TC_DAN_BID_RAMI_KEPT;
  return 0;
}

int tc_dan_bid(const TcMlp *model, const TcObs *o, const int32_t *ids, int k,
                double margin, TcDanBidResult *out) {
  if (!model || !o || !ids || !out || o->ruleset != 3 || o->phase != TC_PH_SHOW ||
      o->seat > 3 || o->n_shows > 3 || (o->hand >> 52) || k < 1 || k > 26) return -1;
  int canonical[TC_NUM_ACTIONS_V2], n = tc_legal_obs(o, canonical);
  if (n != k) return -1;
  for (int i = 0; i < k; i++) {
    int found = 0;
    for (int j = 0; j < n; j++) found += canonical[j] == ids[i];
    for (int j = 0; j < i; j++) if (ids[i] == ids[j]) return -1;
    if (found != 1) return -1;
  }
  uint8_t features[2048]; float scores[TC_NUM_ACTIONS];
  tc_encode_v(o, features, tc_mlp_encoder(model));
  tc_mlp_forward(model, features, 1, scores);
  return tc_dan_bid_select(ids, k, scores, margin, out);
}
double tc_dan_allowance(const TcObs *o, const TcDanConfig *c) {
  if (!o || !tc_dan_config_valid(c) || o->ruleset != 3 || o->phase != TC_PH_PLAY ||
      o->contract != TC_NOLO || o->trick_size != 4 || o->soolaaja >= 0 || o->n_played >= 12) return 0;
  int trick = o->n_played / 4 + 1, pos = o->n_played % 4 + 1;
  if (pos == 1 && trick <= 3) return c->lead_loss;
  if (pos == 2 && trick <= 2) return c->second_loss;
  return 0;
}
static void init(TcDanResult *r, int baseline, double remaining) {
  memset(r, 0, sizeof *r);
  r->action = r->baseline = baseline; r->best = -1;
  r->before = r->after = remaining;
}
static double paired(const double *rows, int w, int k, int a, int b, double *se) {
  double mean = 0, m2 = 0;
  for (int i = 0; i < w; i++) {
    double d = rows[(size_t)i*k+a] - rows[(size_t)i*k+b], delta = d - mean;
    mean += delta / (i+1); m2 += delta * (d-mean);
  }
  *se = sqrt(fmax(0, m2) / (w-1) / w);
  return mean;
}
int tc_dan_select(const int32_t *ids, int k, int baseline, const double *rows, int w,
                  double allowance, double remaining, double z, double epsilon, TcDanResult *r) {
  if (!r) return -1;
  init(r, baseline, remaining); r->reason = TC_DAN_INVALID_VALUES;
  if (!ids || !rows || k < 1 || k > 13 || w < 2 || w > 512 ||
      !isfinite(allowance) || allowance < 0 || !isfinite(remaining) || remaining < 0 ||
      !isfinite(z) || z < 0 || !isfinite(epsilon) || epsilon < 0) return -1;
  int bi = -1, best = 0;
  for (int a = 0; a < k; a++) {
    if (ids[a] < 0 || ids[a] >= 52) return -1;
    for (int b = 0; b < a; b++) if (ids[b] == ids[a]) return -1;
    if (ids[a] == baseline) bi = a;
    for (int i = 0; i < w; i++) {
      double x = rows[(size_t)i*k+a];
      if (!isfinite(x) || fabs(x) > 1) return -1;
      r->means[a] += x / w;
    }
    if (r->means[a] > r->means[best] ||
        (r->means[a] == r->means[best] && ids[a] < ids[best])) best = a;
  }
  if (bi < 0) return -1;
  r->k = k; r->worlds = w; r->best = ids[best];
  r->allowance = fmin(allowance, remaining); r->reason = TC_DAN_REJECTED;
  int chosen = -1;
  for (int a = 0; a < k; a++) {
    r->gaps_base[a] = paired(rows, w, k, bi, a, &r->se_base[a]);
    r->gaps_best[a] = paired(rows, w, k, best, a, &r->se_best[a]);
    r->losses[a] = fmax(0, fmax(r->gaps_base[a] + z*r->se_base[a],
                               r->gaps_best[a] + z*r->se_best[a]));
    if (!high(ids[a]) || r->losses[a] + epsilon > r->allowance) continue;
    if (chosen < 0 || r->means[a] > r->means[chosen] ||
        (r->means[a] == r->means[chosen] && ids[a] < ids[chosen])) chosen = a;
  }
  if (chosen >= 0) {
    r->action = ids[chosen]; r->reason = TC_DAN_ACCEPTED;
    r->charge = r->losses[chosen]; r->after = fmax(0, remaining-r->charge);
  }
  return 0;
}
int tc_dan_choose(TcEnv *env, const TcMlp *model, const TcObs *o, const int32_t *ids, int k,
                 int baseline, const TcDanConfig *c, TcDanContext *ctx, TcDanResult *r) {
  if (!r || !ctx || !o || !ids || !tc_dan_config_valid(c) || k < 1 || k > TC_NUM_ACTIONS_V2 ||
      !isfinite(ctx->remaining) || ctx->remaining < 0 || ctx->remaining > c->deal_loss ||
      o->seat > 3 || o->dealer > 3 || o->n_played > 52 || o->n_shows > 4 ||
      o->n_decisions > 2 || o->phase > TC_PH_SOOLI_PLAY || o->phase == TC_PH_DONE ||
      o->soolaaja < -1 || o->soolaaja > 3 || o->contract < -1 || o->contract > 1 ||
      (o->hand >> 52)) return -1;
  init(r, baseline, ctx->remaining);
  int canonical[TC_NUM_ACTIONS_V2], n = tc_legal_obs(o, canonical), has_base = 0;
  if (n != k) return -1;
  for (int a = 0; a < k; a++) {
    int found = 0;
    for (int j = 0; j < n; j++) found += canonical[j] == ids[a];
    for (int j = 0; j < a; j++) if (ids[j] == ids[a]) return -1;
    if (found != 1) return -1;
    has_base |= ids[a] == baseline;
  }
  if (!has_base) return -1;
  r->trick = o->n_played / 4 + 1; r->position = o->n_played % 4 + 1;
  double allowance = tc_dan_allowance(o, c);
  if (!allowance) return 0;
  if (k == 1) { r->reason = TC_DAN_FORCED; return 0; }
  int any_high = 0;
  for (int a = 0; a < k; a++) any_high |= high(ids[a]);
  if (!any_high) { r->reason = TC_DAN_NO_HIGH; return 0; }
  if (high(baseline)) { r->reason = TC_DAN_BASE_HIGH; return 0; }
  if (ctx->remaining <= c->epsilon) { r->reason = TC_DAN_BUDGET; return 0; }
  if (!env || !model || k > 13) return -1;
  /* Dedicated guard env; no belief resampling, value leaves, team-policy
   * replacement, solver tail, or recursion into the personality. */
  tc_env_set_encoder(env, tc_mlp_encoder(model));
  tc_env_set_team_rollout(env, NULL); tc_env_set_value(env, NULL, -1, -1, 0);
  tc_env_set_belief(env, NULL, 0, 2, .5, 0); tc_env_set_exact_speed(env, 1);
  double means[13], rows[TC_DAN_MAX_WORLDS*13];
  uint64_t rng = ctx->rng;
  if (tc_search_world_values(env, model, o, ids, k, c->worlds, 0, &rng, means, rows)) {
    r->reason = TC_DAN_SAMPLE_FAILED; return 0;
  }
  TcDanResult selected;
  if (tc_dan_select(ids, k, baseline, rows, c->worlds, allowance, ctx->remaining,
                     c->uncertainty, c->epsilon, &selected)) {
    r->reason = TC_DAN_INVALID_VALUES; return 0;
  }
  selected.trick = r->trick; selected.position = r->position; *r = selected;
  ctx->rng = rng; ctx->remaining = r->after;
  return 0;
}
