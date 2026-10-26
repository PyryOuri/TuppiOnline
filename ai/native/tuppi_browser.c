/* Versioned browser adapter. The canonical Python engine remains the oracle.
 * One worker owns this module. Public methods validate actions before the
 * fast core; private hands never need to cross the worker's UI boundary. */
#include <math.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include "tuppi_core.h"
#include "tuppi_mlp.h"
#include "tuppi_parallel.h"
#include "tuppi_dan.h"

typedef struct TcEnv TcEnv;
TcEnv *tc_env_new(int n, uint64_t seed);
void tc_env_free(TcEnv *e);
void tc_env_set_encoder(TcEnv *e, int encoder);
void tc_env_set_equity(TcEnv *e, const double *equity);
void tc_env_set_options(TcEnv *e, double random_start, int single_deal);
void tc_env_set_team_rollout(TcEnv *e, const TcMlp *m);
void tc_env_set_exact_speed(TcEnv *e, int enabled);
void tc_env_set_belief(TcEnv *e, const TcMlp *m, int mult, double temperature, double eps, int all_seats);
void tc_env_set_belief_humans(TcEnv *e, int mask, double temperature, double eps);
int tc_lite_net_applies(const TcObs *o, int tricks, int rami_tricks);
int tc_lite_net_h(const TcMlp *m, const double *equity, const TcObs *o, int action,
                 int layouts, int mult, int human_mask, double temperature, double eps,
                 uint64_t *gate_rng, uint64_t *belief_rng);
void tc_env_set_sooli(TcEnv *e, int belief, int return_pi, int play_heur, double lambda);
int tc_search_values(TcEnv *e, const TcMlp *m, const TcObs *o, const int32_t *actions,
                     int k, int w, int dd_left, uint64_t *rng, double *out);
int tc_search_world_values(TcEnv *e, const TcMlp *m, const TcObs *o, const int32_t *actions,
                           int k, int w, int dd_left, uint64_t *rng, double *mean, double *out);
void tc_set_showing_fix(int on);
void tc_set_rollout_chunk(int n);
void tc_set_belief_lanes(int lanes);
void tc_belief_profile(double *seconds, long *counts, int reset);
int tc_belief_counters(double *out, int reset);
void tc_set_dedup_worlds(int on);

static TcDeal game;
static int hand_order[4][14], hand_count[4];
/* Roles: 0 rollouts (VRPO1), 1 anchor (VRPO3), 2 the Heidi 1.2 network. */
static TcMlp *models[3];
static TcEnv *envs[4];
static uint64_t rngs[4];
static int sooli_modes[4], worlds = 128;
static double last_values[TC_NUM_ACTIONS_V2];
static int last_ids[TC_NUM_ACTIONS_V2], last_count;
/* Additive API: old callers keep the original controller and 3-word context. */
static int bot_mode, human_mask;
/* Mode 3 is mode 1 on role 2 (Nelli 1.1); mode 4 is mode 2 with role 2 as
 * the anchor only (Heidi 1.2). */
static int lite_mode(int mode) { return mode == 1 || mode == 3; }
static int pib_mode(int mode) { return mode == 2 || mode == 4; }
/* The anchor: the keep rule's network for bids and play, the anchor-only bid
 * and the lite policy. Role 2 in modes 3 and 4, role 1 otherwise. */
static TcMlp *anchor_for(int mode) { return models[mode >= 3 ? 2 : 1]; }
/* The likelihood model: play inference (modes 2 and 4) and the safety net's
 * belief (modes 1 and 3, the lite policy's own network). Role 2 in mode 3
 * only; Heidi 1.2 keeps role 1 here. Rollouts always use models[0]. */
static TcMlp *likelihood_for(int mode) { return models[mode == 3 ? 2 : 1]; }
static TcMlp *anchor_model(void) { return anchor_for(bot_mode); }
static TcMlp *likelihood_model(void) { return likelihood_for(bot_mode); }
/* Every network a mode reads is loaded (role 0 is required by tb_configure). */
static int mode_ready(int mode) { return models[0] && anchor_for(mode) && likelihood_for(mode); }
/* 0: searched bids (the default); 1: the anchor's bid in the show phase. */
static int bid_mode;
static uint64_t gate_rngs[4], belief_rngs[4];
static double match_equity[50];
/* Dan is an additive explicit entry point; modes 0-4 and their context
 * formats remain unchanged. The caller owns proposal/commit of Dan state. */
static TcEnv *dan_envs[4];
static int dan_env_worlds[4];

int tb_api_version(void) { return 1; }

int tb_load_model(int role, int in_dim, int width, int blocks, int encoder,
                  int count, const float *params) {
  if (role < 0 || role > 2 || width < 1 || width > 1024 || blocks < 0 || blocks > 8 ||
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
  if (!models[0] || (!models[1] && !models[2]) || !equity || n_worlds < 1 || n_worlds > 1024 ||
      (n_worlds > 128 && n_worlds % 128)) return -1;
  worlds = n_worlds;
  bot_mode = 0; human_mask = 0; bid_mode = 0;
  memcpy(match_equity, equity, sizeof match_equity);
  tc_set_showing_fix(1);
#ifdef __EMSCRIPTEN__
  /* Exact in WASM (row-independent kernel): each repeated world is played once
   * and its value added once per copy, in order. The hosted library keeps it off. */
  tc_set_dedup_worlds(1);
#endif
  for (int s = 0; s < 4; ++s) {
    if (dan_envs[s]) tc_env_free(dan_envs[s]);
    dan_envs[s] = NULL; dan_env_worlds[s] = 0;
    if (envs[s]) tc_env_free(envs[s]);
    envs[s] = tc_env_new(worlds * 26, (uint64_t)(2 * s));
    if (!envs[s]) return -2;
    tc_env_set_encoder(envs[s], tc_mlp_encoder(models[0]));
    tc_env_set_equity(envs[s], equity);
    tc_env_set_options(envs[s], 0, 1);
    tc_env_set_team_rollout(envs[s], NULL);
    tc_env_set_exact_speed(envs[s], 1);
    rngs[s] = (uint64_t)(2 * s) * 2654435761ULL + 1;
    sooli_modes[s] = 0;
  }
  last_count = 0;
  return 0;
}

/* 0: unchanged search; 1: Heidi 0.5 / Nelli 1.0 (C1H); 2: Heidi 1.0 / 1.1
 * (PIB4 humans); 3: Nelli 1.1 (mode 1 on role 2); 4: Heidi 1.2 (mode 2 with
 * role 2 as the anchor only; likelihood role 1). Modes 0-2 need role 1,
 * mode 3 role 2, mode 4 roles 1 and 2. */
int tb_configure_bot(int mode, int people) {
  if (mode < 0 || mode > 4 || people < 0 || people > 15 || !envs[0] || !mode_ready(mode)) return -1;
  bot_mode = mode; human_mask = people; bid_mode = 0;
  const int pib = pib_mode(mode);
  for (int s = 0; s < 4; ++s) {
    tc_env_set_belief(envs[s], pib ? likelihood_model() : NULL, pib ? 4 : 0, 2.0, 0.5, 1);
    tc_env_set_belief_humans(envs[s], pib ? people & ~(1 << s) : 0, 4.0, 0.8);
    if (lite_mode(mode)) rngs[s] = UINT64_C(0x9E3779B97F4A7C15) * (s + 1);
    gate_rngs[s] = UINT64_C(0x5AFE0000) + s;
    belief_rngs[s] = UINT64_C(0xBE11EF00) + s;
  }
  return 0;
}

/* Search profile is explicit; execution backend never changes it. The old
 * configure_bot API retains PIB4 for existing callers and fixtures. The
 * threaded build keeps lanes - 1 workers for scoring and rollouts until
 * tb_dispose; the single build has none. */
int tb_configure_inference(int mult, int lanes) {
  if (!pib_mode(bot_mode) || (mult != 4 && mult != 8) || lanes < 1 || lanes > 4) return -1;
  tc_set_belief_lanes(lanes);
  tc_parallel_start(lanes);
  for (int s = 0; s < 4; ++s)
    tc_env_set_belief(envs[s], likelihood_model(), mult, 2.0, 0.5, 1);
  return 0;
}

/* Seat ownership may change online. This must not reset a controller cursor
 * or its persistent sooli setting. */
int tb_set_human_seats(int people) {
  if (people < 0 || people > 15 || !envs[0]) return -1;
  human_mask = people;
  for (int s = 0; s < 4; ++s)
    tc_env_set_belief_humans(envs[s], pib_mode(bot_mode) ? people & ~(1 << s) : 0, 4.0, 0.8);
  return 0;
}

/* Bid profile of Heidi 1.0 (Heidi fast plan, Stage 3). Mode 0 searches the
 * show phase as before. Mode 1 takes the anchor's bid there: the argmax of
 * its logits over the legal bids with tb_choose's tie rule, no search, no RNG
 * draw and no values recorded; every other phase is unchanged. Off unless a
 * caller sets it; saves record it so a game never changes mode. */
int tb_configure_bids(int mode) {
  if (mode < 0 || mode > 1 || (mode == 1 && !pib_mode(bot_mode))) return -1;
  bid_mode = mode;
  return 0;
}

static int anchor_index(const TcObs *obs, const int *ids, int k) {
  const TcMlp *model = anchor_model();
  uint8_t features[2048]; float logits[TC_NUM_ACTIONS];
  tc_encode_v(obs, features, tc_mlp_encoder(model));
  tc_mlp_forward(model, features, 1, logits);
  int anchor = 0;
  for (int i = 1; i < k; ++i) if (logits[ids[i]] > logits[ids[anchor]]) anchor = i;
  return anchor;
}

int tb_belief_profile(double *out, int reset) {
  if (!out) return -1;
  long counts[2];
  tc_belief_profile(out, counts, reset);
  out[5] = (double)counts[0]; out[6] = (double)counts[1];
  return 0;
}

/* Exact work counters; returns how many were written. */
int tb_belief_counters(double *out, int reset) { return out ? tc_belief_counters(out, reset) : -1; }

void tb_dispose(void) {
  for (int s = 0; s < 4; s++) {
    if (dan_envs[s]) tc_env_free(dan_envs[s]);
    dan_envs[s] = NULL; dan_env_worlds[s] = 0;
  }
  tc_parallel_stop();
  for (int s = 0; s < 4; s++) { if (envs[s]) tc_env_free(envs[s]); envs[s] = NULL; }
  for (int role = 0; role < 3; role++) { tc_mlp_free(models[role]); models[role] = NULL; }
  last_count = 0;
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
  switch (field) {
    case 0: return (uint32_t)rngs[seat];
    case 1: return (uint32_t)(rngs[seat] >> 32);
    case 2: return (uint32_t)sooli_modes[seat];
    case 3: return (uint32_t)gate_rngs[seat];
    case 4: return (uint32_t)(gate_rngs[seat] >> 32);
    case 5: return (uint32_t)belief_rngs[seat];
    case 6: return (uint32_t)(belief_rngs[seat] >> 32);
    default: return 0;
  }
}
int tb_restore_context(int seat, uint32_t lo, uint32_t hi, int mode) {
  if (seat < 0 || seat > 3 || !envs[seat] || mode < 0 || mode > 2) return -1;
  rngs[seat] = (uint64_t)lo | ((uint64_t)hi << 32); set_sooli(seat, mode); return 0;
}
int tb_restore_net_context(int seat, uint32_t glo, uint32_t ghi, uint32_t blo, uint32_t bhi) {
  if (seat < 0 || seat > 3 || !lite_mode(bot_mode)) return -1;
  gate_rngs[seat] = (uint64_t)glo | ((uint64_t)ghi << 32);
  belief_rngs[seat] = (uint64_t)blo | ((uint64_t)bhi << 32);
  return 0;
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

static int choose_observation(int seat, const TcObs *observation, const int *legal, int k) {
  last_count = 0;
  TcObs obs = *observation;
  int ids[TC_NUM_ACTIONS_V2];
  memcpy(ids, legal, sizeof(int) * k);
  if (k == 0) return -2;
  if (k == 1) return ids[0];
  if (lite_mode(bot_mode)) {
    if (obs.phase >= TC_PH_SOOLI_OFFER) return tc_sooli_policy(&obs, &rngs[seat]);
    TcMlp *model = anchor_model();
    uint8_t features[2048]; float q[TC_NUM_ACTIONS];
    tc_encode_v(&obs, features, tc_mlp_encoder(model));
    tc_mlp_forward(model, features, 1, q);
    int best = 0;
    for (int i = 1; i < k; ++i)
      if (q[ids[i]] > q[ids[best]] || (q[ids[i]] == q[ids[best]] && ids[i] < ids[best])) best = i;
    int action = ids[best];
    if (tc_lite_net_applies(&obs, 9, 0))
      action = tc_lite_net_h(likelihood_model(), match_equity, &obs, action, 16, 4,
                            human_mask & ~(1 << seat), 4.0, 0.8, &gate_rngs[seat], &belief_rngs[seat]);
    return action;
  }
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
    if (obs.phase == TC_PH_SHOW && bid_mode == 1) return ids[anchor_index(&obs, ids, k)];
    /* Preserve the current v3 controller's persistent sooli setting. */
    if (obs.phase == TC_PH_SHOW && worlds > 128) best = adaptive(seat, &obs, ids, k, values);
    else {
      if (tc_search_values(envs[seat], models[0], &obs, ids, k, worlds, 6, &rngs[seat], values)) return -3;
      best = argmax(values, k);
    }
    if (best < 0) return -3;
    int anchor = anchor_index(&obs, ids, k);
    double margin = obs.phase == TC_PH_SHOW ? 0.03 : 0.003;
    if (values[anchor] >= values[best] - margin) best = anchor;
  }
  last_count = k;
  memcpy(last_ids, ids, sizeof(int) * k); memcpy(last_values, values, sizeof(double) * k);
  return ids[best];
}

int tb_choose(int seat) {
  last_count = 0;
  if (seat != game.cur || seat < 0 || seat > 3 || !envs[seat] || !mode_ready(bot_mode) || game.phase == TC_PH_DONE) return -1;
  TcObs obs; tc_observe(&game, seat, &obs);
  int ids[TC_NUM_ACTIONS_V2], k = tb_legal(seat, ids);
  return choose_observation(seat, &obs, ids, k);
}

/* Trusted server adapter: only the acting seat's observation, never a full
 * deal. Preserve the authoritative engine's legal-action order for ties and
 * per-action RNG assignment. Validate its complete legal set before search. */
int tb_choose_observation(const TcObs *obs, const int32_t *ids, int k) {
  last_count = 0;
  if (!obs || !ids || obs->seat > 3 || !envs[obs->seat] || !mode_ready(bot_mode) || k < 1 || k > TC_NUM_ACTIONS_V2 ||
      obs->phase == TC_PH_DONE || obs->phase > TC_PH_SOOLI_PLAY || obs->dealer > 3 ||
      obs->n_shows > 4 || obs->n_played > 52 || obs->n_decisions > 2 ||
      (obs->hand >> 52) || obs->ruleset != 3) return -1;
  int canonical[TC_NUM_ACTIONS_V2], count = tc_legal_obs(obs, canonical);
  if (count != k) return -2;
  for (int i = 0; i < k; ++i) {
    int found = 0;
    for (int j = 0; j < count; ++j) if (ids[i] == canonical[j]) ++found;
    for (int j = 0; j < i; ++j) if (ids[i] == ids[j]) return -2;
    if (found != 1) return -2;
  }
  return choose_observation(obs->seat, obs, ids, k);
}

int tb_values(int32_t *ids, double *values) {
  memcpy(ids, last_ids, sizeof(int) * last_count); memcpy(values, last_values, sizeof(double) * last_count);
  return last_count;
}

/* Uses only the acting seat's legal observation. Context pointers must be
 * copies until the chosen action is accepted; no live cursors are mutated. */
int tb_dan_choose_observation(const TcObs *obs, const int32_t *ids, int k,
    const TcDanConfig *config, uint64_t *base_rng, TcDanContext *proposal, TcDanResult *result) {
  if (!obs || !ids || !base_rng || !proposal || !result || !tc_dan_config_valid(config) ||
      !models[1] || !envs[0] || obs->seat > 3 || obs->dealer > 3 || k < 1 || k > TC_NUM_ACTIONS_V2 ||
      obs->phase == TC_PH_DONE || obs->phase > TC_PH_SOOLI_PLAY || obs->n_played > 52 ||
      obs->n_shows > 4 || obs->n_decisions > 2 || obs->ruleset != 3 || (obs->hand >> 52)) return -1;
  int canonical[TC_NUM_ACTIONS_V2], n = tc_legal_obs(obs, canonical);
  if (n != k) return -2;
  for (int i = 0; i < k; i++) {
    int found = 0;
    for (int j = 0; j < n; j++) found += ids[i] == canonical[j];
    for (int j = 0; j < i; j++) if (ids[i] == ids[j]) return -2;
    if (found != 1) return -2;
  }
  uint64_t next_base = *base_rng;
  int base = ids[0];
  if (obs->phase == TC_PH_SHOW) {
    /* Dan 1.1 uses the actual Nelli 1.1 bidding network, with a one-way RAMI
     * veto; card play and rollouts continue on plain VRPO3. */
    TcDanBidResult bid;
    if (!models[2] || tc_dan_bid(models[2], obs, ids, k, config->rami_margin, &bid)) return -5;
    base = bid.action;
  }
  else if (k > 1 && obs->phase >= TC_PH_SOOLI_OFFER) base = tc_sooli_policy(obs, &next_base);
  else if (k > 1) {
    uint8_t features[2048]; float q[TC_NUM_ACTIONS];
    tc_encode_v(obs, features, tc_mlp_encoder(models[1]));
    tc_mlp_forward(models[1], features, 1, q);
    for (int i = 1; i < k; i++)
      if (q[ids[i]] > q[base] || (q[ids[i]] == q[base] && ids[i] < base)) base = ids[i];
  }
  int seat = obs->seat;
  int need = tc_dan_allowance(obs, config) > 0 && k > 1 && base < 52 && base % 13 < 11 &&
             proposal->remaining > config->epsilon;
  if (need && (!dan_envs[seat] || dan_env_worlds[seat] != config->worlds)) {
    if (dan_envs[seat]) tc_env_free(dan_envs[seat]);
    dan_envs[seat] = tc_env_new(config->worlds * 13, 0);
    dan_env_worlds[seat] = config->worlds;
    if (!dan_envs[seat]) return -3;
    tc_env_set_equity(dan_envs[seat], match_equity);
    tc_env_set_options(dan_envs[seat], 0, 1);
  }
  if (tc_dan_choose(dan_envs[seat], models[1], obs, ids, k, base, config, proposal, result)) return -4;
  *base_rng = next_base;
  return result->action;
}

int tb_dan_choose(int seat, const TcDanConfig *config, uint64_t *base_rng,
                  TcDanContext *proposal, TcDanResult *result) {
  if (seat < 0 || seat > 3 || game.cur != seat || game.phase == TC_PH_DONE) return -1;
  TcObs obs; tc_observe(&game, seat, &obs);
  int32_t ids[TC_NUM_ACTIONS_V2]; int k = tb_legal(seat, ids);
  return tb_dan_choose_observation(&obs, ids, k, config, base_rng, proposal, result);
}

/* Browser save ABI for Dan 1.1. All values are uint32 words, including the
 * exact double bits of the ledger. A proposal never mutates the before row. */
#define DAN_WORDS 8
#define DAN_MAGIC UINT32_C(0xDA110001)
static uint64_t dan_u64(const uint32_t *p) { return (uint64_t)p[0] | ((uint64_t)p[1] << 32); }
static void dan_put_u64(uint32_t *p, uint64_t v) { p[0] = (uint32_t)v; p[1] = (uint32_t)(v >> 32); }
int tb_dan_context_words(void) { return DAN_WORDS; }
int tb_dan_validate_context(const uint32_t *row) {
  if (!row || row[6] != DAN_MAGIC || row[7] != 0) return -1;
  uint64_t bits = dan_u64(row+4); double remaining; memcpy(&remaining, &bits, sizeof remaining);
  TcDanConfig cfg; tc_dan_default_config(&cfg);
  return isfinite(remaining) && remaining >= 0 && remaining <= cfg.deal_loss ? 0 : -1;
}
int tb_dan_reset_deal(uint32_t *row) {
  if (tb_dan_validate_context(row)) return -1;
  TcDanConfig cfg; tc_dan_default_config(&cfg);
  uint64_t bits; memcpy(&bits, &cfg.deal_loss, sizeof bits); dan_put_u64(row+4, bits);
  return 0;
}
int tb_dan_initial_context(int seat, uint32_t *out) {
  if (!out || seat < 0 || seat > 3) return -1;
  memset(out, 0, sizeof(uint32_t)*DAN_WORDS);
  dan_put_u64(out, UINT64_C(0x9E3779B97F4A7C15)*(seat+1));
  dan_put_u64(out+2, UINT64_C(0xDAA00000)+seat);
  out[6] = DAN_MAGIC;
  return tb_dan_reset_deal(out);
}
int tb_dan_choose_context(int seat, const uint32_t *before, uint32_t *after) {
  last_count = 0;
  if (!after || tb_dan_validate_context(before)) return -1;
  TcDanConfig cfg; tc_dan_default_config(&cfg);
  uint64_t base = dan_u64(before), bits = dan_u64(before+4);
  TcDanContext proposal = {.rng=dan_u64(before+2)};
  memcpy(&proposal.remaining, &bits, sizeof proposal.remaining);
  TcDanResult result;
  int action = tb_dan_choose(seat, &cfg, &base, &proposal, &result);
  if (action < 0) return action;
  memcpy(after, before, sizeof(uint32_t)*DAN_WORDS);
  dan_put_u64(after, base); dan_put_u64(after+2, proposal.rng);
  memcpy(&bits, &proposal.remaining, sizeof bits); dan_put_u64(after+4, bits);
  if (result.k) {
    int32_t ids[TC_NUM_ACTIONS_V2]; int k = tb_legal(seat, ids);
    if (k != result.k) return -6;
    last_count = k;
    memcpy(last_ids, ids, sizeof(int)*k); memcpy(last_values, result.means, sizeof(double)*k);
  }
  return action;
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
  if (role < 0 || role > 2 || !models[role] || rows < 1 || rows > 64) return -1;
  tc_mlp_forward(models[role], features, rows, out); return 0;
}
