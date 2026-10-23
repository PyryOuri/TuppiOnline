/* Repeated native Heidi 1.0 decisions for the repeated-world reuse leak check
 * (Heidi fast plan, Stage 4). Builds the browser adapter natively, loads the
 * exported browser assets, sets one position and repeats the same decision
 * from the same cursors, printing the action and the process footprint.
 * Values must repeat exactly (dedup on or off). Bytes in use come from the
 * malloc zones (malloc_zone_statistics): a leak shows as steady growth after
 * warmup. `leaks --atExit` cannot attach in the sandbox this was run in.
 *
 *   repeat_driver ASSETS WORLDS MULT REPEATS DEDUP W0 B0 E0 W1 B1 E1 PEOPLE DEALER S0 S1 CARDS PREFIX
 * (Wn Bn En: width, blocks, encoder of model n; CARDS/PREFIX: comma lists)
 */
#include <mach/mach.h>
#include <malloc/malloc.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int tb_load_model(int role, int in_dim, int width, int blocks, int encoder, int count, const float *params);
int tb_configure(int n_worlds, const double *equity);
int tb_configure_bot(int mode, int people);
int tb_configure_inference(int mult, int lanes);
int tb_init(const int32_t *cards, int dealer, int score0, int score1);
int tb_apply(int action);
int tb_state(int field);
int tb_choose(int seat);
int tb_values(int32_t *ids, double *values);
uint32_t tb_context(int seat, int field);
int tb_restore_context(int seat, uint32_t lo, uint32_t hi, int mode);
void tb_dispose(void);
int tc_feature_dim_v(int version);
void tc_set_dedup_worlds(int on);

static void *slurp(const char *dir, const char *name, size_t *size) {
  char path[4096];
  snprintf(path, sizeof path, "%s/%s", dir, name);
  FILE *f = fopen(path, "rb");
  if (!f) { perror(path); exit(2); }
  fseek(f, 0, SEEK_END); *size = (size_t)ftell(f); fseek(f, 0, SEEK_SET);
  void *p = malloc(*size);
  if (fread(p, 1, *size, f) != *size) exit(2);
  fclose(f);
  return p;
}

static int list(const char *s, int32_t *out) {
  int n = 0;
  for (const char *p = s; *p; ) { out[n++] = (int32_t)strtol(p, (char **)&p, 10); if (*p == ',') p++; }
  return n;
}

static double in_use_mb(void) {
  malloc_statistics_t stats;
  malloc_zone_statistics(NULL, &stats);
  return stats.size_in_use / 1048576.0;
}

static double footprint_mb(void) {
  task_vm_info_data_t info; mach_msg_type_number_t count = TASK_VM_INFO_COUNT;
  if (task_info(mach_task_self(), TASK_VM_INFO, (task_info_t)&info, &count) != KERN_SUCCESS) return -1;
  return info.phys_footprint / 1048576.0;
}

int main(int argc, char **argv) {
  if (argc != 18) { fprintf(stderr, "usage: see source\n"); return 2; }
  const char *assets = argv[1];
  const int worlds = atoi(argv[2]), mult = atoi(argv[3]), repeats = atoi(argv[4]), dedup = atoi(argv[5]);
  const char *files[2] = {"vrpo1_actor_0504.f32", "vrpo3_final.f32"};
  for (int role = 0; role < 2; role++) {
    size_t size;
    float *params = slurp(assets, files[role], &size);
    int width = atoi(argv[6 + 3 * role]), blocks = atoi(argv[7 + 3 * role]), encoder = atoi(argv[8 + 3 * role]);
    if (tb_load_model(role, tc_feature_dim_v(encoder), width, blocks, encoder, (int)(size / 4), params)) return 3;
    free(params);
  }
  size_t esize;
  double *equity = slurp(assets, "equity.f64", &esize);
  if (tb_configure(worlds, equity) || tb_configure_bot(2, atoi(argv[12])) || tb_configure_inference(mult, 1)) return 4;
  free(equity);
  tc_set_dedup_worlds(dedup);
  int32_t cards[52], prefix[64];
  if (list(argv[16], cards) != 52) return 5;
  const int np = argv[17][0] ? list(argv[17], prefix) : 0;
  if (tb_init(cards, atoi(argv[13]), atoi(argv[14]), atoi(argv[15]))) return 6;
  for (int i = 0; i < np; i++) if (tb_apply(prefix[i])) return 7;
  const int actor = tb_state(1);
  uint32_t ctx[4][3];
  for (int s = 0; s < 4; s++) for (int f = 0; f < 3; f++) ctx[s][f] = tb_context(s, f);
  int first = -1; int32_t ids[210]; double values[210], first_values[210]; int nv = 0;
  // REPEAT_PAUSE_MS: idle time between repeats, so the system can retire idle worker threads.
  const int pause_ms = getenv("REPEAT_PAUSE_MS") ? atoi(getenv("REPEAT_PAUSE_MS")) : 0;
  for (int r = 0; r < repeats; r++) {
    if (pause_ms && r) usleep((useconds_t)pause_ms * 1000);
    for (int s = 0; s < 4; s++) tb_restore_context(s, ctx[s][0], ctx[s][1], (int)ctx[s][2]);
    int a = tb_choose(actor), n = tb_values(ids, values);
    if (r == 0) { first = a; nv = n; memcpy(first_values, values, sizeof(double) * n); }
    else if (a != first || n != nv || memcmp(values, first_values, sizeof(double) * n)) { printf("MISMATCH at %d\n", r); return 8; }
    if (r % (pause_ms ? 2 : 20) == 0 || r == repeats - 1)
      printf("repeat %d action %d in_use_mb %.2f footprint_mb %.1f\n", r, a, in_use_mb(), footprint_mb());
    fflush(stdout);
  }
  tb_dispose();
  printf("done repeats %d action %d values %d identical 1 in_use_after_dispose_mb %.2f\n", repeats, first, nv, in_use_mb());
  return 0;
}
