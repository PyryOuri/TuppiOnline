#ifndef TUPPI_DAN_H
#define TUPPI_DAN_H
#include "tuppi_core.h"
#include "tuppi_mlp.h"
typedef struct TcEnv TcEnv;
#define TC_DAN_MAX_ACTIONS 13
#define TC_DAN_MAX_WORLDS 64
typedef struct {
  int worlds;
  double lead_loss, second_loss, deal_loss, uncertainty, epsilon;
} TcDanConfig;
typedef struct { uint64_t rng; double remaining; } TcDanContext;
enum {
  TC_DAN_OUTSIDE, TC_DAN_FORCED, TC_DAN_NO_HIGH, TC_DAN_BASE_HIGH,
  TC_DAN_BUDGET, TC_DAN_REJECTED, TC_DAN_ACCEPTED, TC_DAN_SAMPLE_FAILED,
  TC_DAN_INVALID_VALUES
};
typedef struct {
  int action, baseline, best, reason, k, worlds, trick, position;
  double allowance, charge, before, after;
  double means[13], losses[13], gaps_base[13], gaps_best[13], se_base[13], se_best[13];
} TcDanResult;
int tc_dan_config_valid(const TcDanConfig *c);
double tc_dan_allowance(const TcObs *o, const TcDanConfig *c);
/* Pure selector: rows are observer-team returns, shared by every action. */
int tc_dan_select(const int32_t *ids, int k, int baseline, const double *rows, int worlds,
                  double allowance, double remaining, double uncertainty, double epsilon, TcDanResult *out);
/* Mutates only the supplied proposal context, not a live game or base cursor. */
int tc_dan_choose(TcEnv *env, const TcMlp *model, const TcObs *o, const int32_t *ids, int k,
                 int baseline, const TcDanConfig *c, TcDanContext *proposal, TcDanResult *out);
#endif
