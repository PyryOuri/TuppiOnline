/* Versioned browser adapter. The canonical Python engine remains the oracle.
 * One worker owns this module. Public methods validate actions before the
 * fast core; private hands never need to cross the worker's UI boundary. */
#include <math.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include "tuppi_core.h"
#include "tuppi_mlp.h"

typedef struct TcEnv TcEnv;
TcEnv *tc_env_new(int n, uint64_t seed);
void tc_env_free(TcEnv *e);
void tc_env_set_encoder(TcEnv *e, int encoder);
void tc_env_set_equity(TcEnv *e, const double *equity);
void tc_env_set_options(TcEnv *e, double random_start, int single_deal);
void tc_env_set_team_rollout(TcEnv *e, const TcMlp *m);
void tc_env_set_sooli(TcEnv *e, int belief, int return_pi, int play_heur, double lambda);
int tc_search_values(TcEnv *e, const TcMlp *m, const TcObs *o, const int32_t *actions,
                     int k, int w, int dd_left, uint64_t *rng, double *out);
int tc_search_world_values(TcEnv *e, const TcMlp *m, const TcObs *o, const int32_t *actions,
                           int k, int w, int dd_left, uint64_t *rng, double *mean, double *out);
void tc_set_showing_fix(int on);
void tc_set_rollout_chunk(int n);

static TcDeal game;
static int hand_order[4][14], hand_count[4];
static TcMlp *models[2];
static TcEnv *envs[4];
static uint64_t rngs[4];
static int sooli_modes[4], worlds = 128;
static double last_values[TC_NUM_ACTIONS_V2];
static int last_ids[TC_NUM_ACTIONS_V2], last_count;

int tb_api_version(void) { return 1; }

int tb_load_model(int role, int in_dim, int width, int blocks, int encoder,
                  int count, const float *params) {
  if (role < 0 || role > 1 || width < 1 || width > 1024 || blocks < 0 || blocks > 8 ||
      encoder < 1 || encoder > 2 || in_dim != tc_feature_dim_v(encoder) || !params) return -1;
  int expected = width * in_dim + width + blocks * (2 * width * width + 4 * width)
                 + 2 * width + TC_NUM_ACTIONS * width + TC_NUM_ACTIONS;
  if (count != expected) return -2;
  /* Reloading models would invalidate existing environment pointers. */
  if (envs[0]) return -3;
  TcMlp *model = tc_mlp_new(in_dim, width, blocks, TC_NUM_ACTIONS, encoder, params);
  if (!model) return -4;
  tc_mlp_free(models[role]); models[role] = model;
  return 0;
}

int tb_configure(int n_worlds, const double *equity) {
  if (!models[0] || !models[1] || !equity || n_worlds < 1 || n_worlds > 1024 ||
      (n_worlds > 128 && n_worlds % 128)) return -1;
  worlds = n_worlds;
  tc_set_showing_fix(1); tc_set_rollout_chunk(32);
  for (int s = 0; s < 4; ++s) {
    tc_env_free(envs[s]);
    envs[s] = tc_env_new(worlds * 26, (uint64_t)(2 * s));
    if (!envs[s]) return -2;
    tc_env_set_encoder(envs[s], tc_mlp_encoder(models[0]));
    tc_env_set_equity(envs[s], equity);
    tc_env_set_options(envs[s], 0, 1);
    tc_env_set_team_rollout(envs[s], models[0]);
    rngs[s] = (uint64_t)(2 * s) * 2654435761ULL + 1;
    sooli_modes[s] = 0;
  }
  last_count = 0;
  return 0;
}

int tb_init(const int32_t *cards, int dealer, int score0, int score1) {
  if (!cards || dealer < 0 || dealer > 3 || score0 < 0 || score1 < 0 ||
      score0 >= 52 || score1 >= 52 || score0 % 4 || score1 % 4 || (score0 && score1)) return -1;
  uint64_t hands[4] = {0}, seen = 0;
  for (int i = 0; i < 52; ++i) {
    int c = cards[i];
    if (c < 0 || c >= 52 || (seen & (1ULL << c))) return -2;
    seen |= 1ULL << c; hands[i / 13] |= 1ULL << c;
  }
  tc_deal_init_v(&game, hands, dealer, score0, score1, 3);
  for (int s = 0; s < 4; ++s) {
    hand_count[s] = 13;
    for (int i = 0; i < 13; ++i) hand_order[s][i] = cards[s * 13 + i];
  }
  last_count = 0;
  return 0;
}

int tb_legal(int seat, int32_t *out) {
  if (seat < 0 || seat > 3 || !out || game.phase == TC_PH_DONE) return 0;
  if (game.phase != TC_PH_SHOW && game.cur != seat) return 0;
  TcObs obs; tc_observe(&game, seat, &obs);
  int legal[TC_NUM_ACTIONS_V2], k = tc_legal_obs(&obs, legal), n = 0;
  if (game.phase == TC_PH_SOOLI_OFFER) { memcpy(out, legal, sizeof(int) * k); return k; }
  /* Canonical PlayerObservation retains the explicit deal's hand order.
   * It affects tie-breaking and per-action rollout RNG assignment. */
  for (int contract = 0; contract < (game.phase == TC_PH_SHOW ? 2 : 1); ++contract)
    for (int i = 0; i < hand_count[seat]; ++i) {
      int id = hand_order[seat][i];
      if (game.phase == TC_PH_SHOW) id += 52 + 52 * contract;
      else if (game.phase == TC_PH_SOOLI_GIVE || game.phase == TC_PH_SOOLI_RETURN) id += TC_ACT_EXCHANGE;
      for (int j = 0; j < k; ++j) if (legal[j] == id) out[n++] = id;
    }
  return n;
}

int tb_apply(int action) {
  int ids[TC_NUM_ACTIONS_V2], k = tc_legal(&game, ids), legal = 0;
  for (int i = 0; i < k; ++i) if (ids[i] == action) legal = 1;
  if (!legal) return -1;
  int phase = game.phase, actor = game.cur;
  int result = tc_apply(&game, action);
  if (result == 0 && phase != TC_PH_SHOW && phase != TC_PH_SOOLI_OFFER) {
    int card = action >= TC_ACT_EXCHANGE ? action - TC_ACT_EXCHANGE : action;
    int position = -1;
    for (int i = 0; i < hand_count[actor]; ++i) if (hand_order[actor][i] == card) position = i;
    if (position < 0) return -2;
    for (int i = position; i + 1 < hand_count[actor]; ++i) hand_order[actor][i] = hand_order[actor][i + 1];
    --hand_count[actor];
    if (phase == TC_PH_SOOLI_GIVE || phase == TC_PH_SOOLI_RETURN) {
      int receiver = (actor + 2) % 4;
      hand_order[receiver][hand_count[receiver]++] = card;
    }
  }
  return result;
}

int tb_state(int field) {
  uint8_t after[2] = {game.score[0], game.score[1]};
  int terminal = 0;
  if (game.phase == TC_PH_DONE)
    terminal = tc_next_score(game.score, game.winner_team, game.points, after);
  const int fields[] = {game.phase, game.cur, game.dealer, game.contract, game.declarer,
    game.n_shows, game.n_played, game.team_tricks[0], game.team_tricks[1],
    after[0], after[1], game.points, game.winner_team, game.soolaaja, game.trick_size,
    terminal, game.given, game.returned};
  return field >= 0 && field < (int)(sizeof fields / sizeof *fields) ? fields[field] : -999;
}

int tb_hand(int seat, int32_t *out) {
  if (seat < 0 || seat > 3 || !out) return -1;
  memcpy(out, hand_order[seat], sizeof(int) * hand_count[seat]);
  return hand_count[seat];
}

int tb_history(int32_t *cards, int32_t *seats) {
  for (int i = 0; i < game.n_played; ++i) { cards[i] = game.play_card[i]; seats[i] = game.play_seat[i]; }
  return game.n_played;
}

int tb_bids(int32_t *cards, int32_t *seats, int32_t *contracts) {
  if (game.phase == TC_PH_SHOW) return 0;
  for (int i = 0; i < game.n_shows; ++i) {
    cards[i] = game.show_card[i]; seats[i] = game.show_seat[i]; contracts[i] = game.show_contract[i];
  }
  return game.n_shows;
}

static void set_sooli(int seat, int mode) {
  tc_env_set_sooli(envs[seat], mode ? 17 : 0, 0, mode == 1, mode ? 0.3 : 0);
  sooli_modes[seat] = mode;
}

uint32_t tb_context(int seat, int field) {
  if (seat < 0 || seat > 3) return 0;
  return field == 0 ? (uint32_t)rngs[seat] : field == 1 ? (uint32_t)(rngs[seat] >> 32) : (uint32_t)sooli_modes[seat];
}
int tb_restore_context(int seat, uint32_t lo, uint32_t hi, int mode) {
  if (seat < 0 || seat > 3 || !envs[seat] || mode < 0 || mode > 2) return -1;
  rngs[seat] = (uint64_t)lo | ((uint64_t)hi << 32); set_sooli(seat, mode); return 0;
}

static int argmax(const double *values, int k) {
  int best = 0;
  for (int i = 1; i < k; ++i) if (values[i] > values[best]) best = i;
  return best;
}

static int adaptive(int seat, const TcObs *obs, const int *ids, int k, double *values) {
  double *rows = malloc(sizeof(double) * (size_t)worlds * k);
  double *batch_rows = malloc(sizeof(double) * (size_t)128 * k);
  int active[52], counts[52] = {0}, n_active = k, drawn = 0, lead = 0;
  for (int i = 0; i < k; ++i) active[i] = i;
  for (;;) {
    int actions[52]; double means[52];
    for (int i = 0; i < n_active; ++i) actions[i] = ids[active[i]];
    if (tc_search_world_values(envs[seat], models[0], obs, actions, n_active, 128, 6,
                               &rngs[seat], means, batch_rows)) { free(rows); free(batch_rows); return -1; }
    for (int a = 0; a < n_active; ++a) {
      int index = active[a];
      for (int r = 0; r < 128; ++r) rows[(size_t)index * worlds + counts[index] + r] = batch_rows[(size_t)r * n_active + a];
      counts[index] += 128;
      double sum = 0;
      for (int r = 0; r < counts[index]; ++r) sum += rows[(size_t)index * worlds + r];
      values[index] = sum / counts[index];
    }
    drawn += 128; lead = active[0];
    for (int a = 1; a < n_active; ++a) if (values[active[a]] > values[lead]) lead = active[a];
    if (n_active == 1 || drawn >= worlds) break;
    int kept[52], n_kept = 0, settled = 1;
    for (int a = 0; a < n_active; ++a) {
      int index = active[a];
      if (index == lead) { kept[n_kept++] = index; continue; }
      double gap = 0, variance = 0;
      for (int r = 0; r < drawn; ++r) gap += rows[(size_t)lead * worlds + r] - rows[(size_t)index * worlds + r];
      gap /= drawn;
      for (int r = 0; r < drawn; ++r) {
        double d = rows[(size_t)lead * worlds + r] - rows[(size_t)index * worlds + r] - gap;
        variance += d * d;
      }
      double se = sqrt(variance / (drawn - 1) / drawn);
      if (gap - 2.5 * se > 0) continue;
      kept[n_kept++] = index;
      if (-gap + 2.5 * se >= 0.005) settled = 0;
    }
    memcpy(active, kept, sizeof(int) * n_kept); n_active = n_kept;
    if (settled) break;
  }
  free(rows); free(batch_rows); return lead;
}

int tb_choose(int seat) {
  last_count = 0;
  if (seat != game.cur || seat < 0 || seat > 3 || !envs[seat] || game.phase == TC_PH_DONE) return -1;
  TcObs obs; tc_observe(&game, seat, &obs);
  int ids[TC_NUM_ACTIONS_V2], k = tb_legal(seat, ids);
  if (k == 0) return -2;
  if (k == 1) return ids[0];
  double values[TC_NUM_ACTIONS_V2]; int best;
  if (obs.phase >= TC_PH_SOOLI_OFFER) {
    if (obs.phase == TC_PH_SOOLI_OFFER) {
      set_sooli(seat, 1);
      if (tc_search_values(envs[seat], models[0], &obs, ids, k, worlds, 6, &rngs[seat], values)) return -3;
      best = values[1] - values[0] > 0.02 ? 1 : 0;
    } else {
      int heuristic = tc_sooli_policy(&obs, &rngs[seat]);
      if (obs.phase == TC_PH_SOOLI_RETURN) return heuristic;
      int ordered[TC_NUM_ACTIONS_V2], n = 0; ordered[n++] = heuristic;
      for (int i = 0; i < k; ++i) if (ids[i] != heuristic) ordered[n++] = ids[i];
      if (n != k) return -4;
      memcpy(ids, ordered, sizeof(int) * k); set_sooli(seat, 2);
      if (tc_search_values(envs[seat], models[0], &obs, ids, k, worlds, 6, &rngs[seat], values)) return -3;
      best = argmax(values, k);
    }
  } else {
    /* Preserve the current v3 controller's persistent sooli setting. */
    if (obs.phase == TC_PH_SHOW && worlds > 128) best = adaptive(seat, &obs, ids, k, values);
    else {
      if (tc_search_values(envs[seat], models[0], &obs, ids, k, worlds, 6, &rngs[seat], values)) return -3;
      best = argmax(values, k);
    }
    if (best < 0) return -3;
    uint8_t features[2048]; float logits[TC_NUM_ACTIONS];
    tc_encode_v(&obs, features, tc_mlp_encoder(models[1]));
    tc_mlp_forward(models[1], features, 1, logits);
    int anchor = 0;
    for (int i = 1; i < k; ++i) if (logits[ids[i]] > logits[ids[anchor]]) anchor = i;
    double margin = obs.phase == TC_PH_SHOW ? 0.03 : 0.003;
    if (values[anchor] >= values[best] - margin) best = anchor;
  }
  last_count = k;
  memcpy(last_ids, ids, sizeof(int) * k); memcpy(last_values, values, sizeof(double) * k);
  return ids[best];
}

int tb_values(int32_t *ids, double *values) {
  memcpy(ids, last_ids, sizeof(int) * last_count); memcpy(values, last_values, sizeof(double) * last_count);
  return last_count;
}

int tb_observation_size(void) { return sizeof(TcObs); }
int tb_observation(int seat, uint8_t *out) {
  if (seat < 0 || seat > 3 || !out) return -1;
  TcObs obs; tc_observe(&game, seat, &obs); memcpy(out, &obs, sizeof obs); return 0;
}
int tb_features(int seat, int encoder, uint8_t *out) {
  if (seat < 0 || seat > 3 || !out || encoder < 1 || encoder > 2) return -1;
  TcObs obs; tc_observe(&game, seat, &obs); tc_encode_v(&obs, out, encoder); return tc_feature_dim_v(encoder);
}
int tb_inference(int role, const uint8_t *features, int rows, float *out) {
  if (role < 0 || role > 1 || !models[role] || rows < 1 || rows > 64) return -1;
  tc_mlp_forward(models[role], features, rows, out); return 0;
}
