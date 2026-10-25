#ifndef TUPPI_PARALLEL_H
#define TUPPI_PARALLEL_H
#include <stddef.h>

/* Index-parallel loops: tc_parallel_for(count, fn, ctx) runs fn(ctx, i) for
 * every i in [0, count) and returns when all have finished. Every use writes
 * disjoint outputs per index (its own games, per-game RNG streams, per-thread
 * solver tables), so no result depends on the schedule or the core count.
 * Mac: dispatch_apply_f on the global queue (off with tc_set_parallel(0)).
 * Portable single-thread builds: a loop. Emscripten pthread build: one
 * persistent pool of up to three workers (tc_parallel_start) with the caller
 * taking part; indices come from an atomic counter, a call nested inside a
 * loop runs inline, and with no workers the caller runs every index. */
typedef void (*TcParallelFn)(void *ctx, size_t index);
void tc_parallel_for(size_t count, TcParallelFn fn, void *ctx);
int tc_parallel_start(int lanes);  /* pthread build: lanes - 1 workers (at most 3); returns how many started */
void tc_parallel_stop(void);
extern int tc_parallel_loops;      /* tc_set_parallel */
/* A per-thread table to free when its thread exits (Mac: the system retires
 * idle worker threads and starts new ones, each allocating fresh tables;
 * without this the old ones stayed allocated). No-op in portable builds. */
void tc_thread_owns(void *table);

/* The older block form, kept for the training and evaluation loops. Browser
 * builds run it as a plain loop. */
#ifdef TC_PORTABLE
#define TC_BLOCK
#define TC_PARALLEL_BEGIN(count, index) \
  for (size_t index = 0, tc_count_##index = (count); index < tc_count_##index; ++index) {
#define TC_PARALLEL_END }
#else
#define TC_BLOCK __block
#include <dispatch/dispatch.h>
#define TC_PARALLEL_BEGIN(count, index) par_apply((count), ^(size_t index) {
#define TC_PARALLEL_END });
#endif
#endif
