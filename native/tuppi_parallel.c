/* tc_parallel_for (see tuppi_parallel.h). */
#include "tuppi_parallel.h"

int tc_parallel_loops = 1;
// A batch job that already runs one process per core can switch the parallel
// loops off to avoid oversubscribing the machine with each process's threads.
void tc_set_parallel(int on) { tc_parallel_loops = on != 0; }

void tc_dd_release_thread(void);
void tc_sooli_release_thread(void);
void tc_search_release_thread(void);

#if defined(__EMSCRIPTEN_PTHREADS__)
#include <pthread.h>
#include <stdatomic.h>
// Pool workers free their tables explicitly before they exit (worker()).
void tc_thread_owns(void *table) { (void)table; }

static pthread_mutex_t mu = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t wake = PTHREAD_COND_INITIALIZER, idle = PTHREAD_COND_INITIALIZER;
static pthread_t workers[3];
static int nworkers, stopping, busy;  // busy: workers not yet done with the current loop
static unsigned generation;           // one per loop
static TcParallelFn job_fn;
static void *job_ctx;
static size_t job_count;
static atomic_size_t job_next;
static _Thread_local int inside;      // a loop nested inside a loop's body runs inline

static void drain(TcParallelFn fn, void *ctx, size_t count) {
  for (size_t i; (i = atomic_fetch_add(&job_next, 1)) < count;) fn(ctx, i);
}

static void *worker(void *unused) {
  (void)unused;
  inside = 1;
  unsigned seen = 0;
  pthread_mutex_lock(&mu);
  for (;;) {
    while (!stopping && generation == seen) pthread_cond_wait(&wake, &mu);
    if (stopping) break;
    seen = generation;
    const TcParallelFn fn = job_fn;
    void *ctx = job_ctx;
    const size_t count = job_count;
    pthread_mutex_unlock(&mu);
    drain(fn, ctx, count);
    pthread_mutex_lock(&mu);
    if (--busy == 0) pthread_cond_signal(&idle);
  }
  pthread_mutex_unlock(&mu);
  // The solver and sampler tables this thread allocated go with it.
  tc_dd_release_thread(); tc_sooli_release_thread(); tc_search_release_thread();
  return NULL;
}

int tc_parallel_start(int lanes) {
  tc_parallel_stop();
  const int want = lanes - 1 > 3 ? 3 : lanes - 1;
  pthread_mutex_lock(&mu);
  stopping = 0;
  pthread_mutex_unlock(&mu);
  // An unavailable worker leaves its share to the others and the caller.
  while (nworkers < want && pthread_create(&workers[nworkers], NULL, worker, NULL) == 0) nworkers++;
  return nworkers;
}

void tc_parallel_stop(void) {
  pthread_mutex_lock(&mu);
  stopping = 1;
  pthread_cond_broadcast(&wake);
  pthread_mutex_unlock(&mu);
  for (int i = 0; i < nworkers; i++) pthread_join(workers[i], NULL);
  nworkers = 0;
}

void tc_parallel_for(size_t count, TcParallelFn fn, void *ctx) {
  if (!nworkers || inside || count < 2) {
    for (size_t i = 0; i < count; i++) fn(ctx, i);
    return;
  }
  pthread_mutex_lock(&mu);
  job_fn = fn; job_ctx = ctx; job_count = count;
  atomic_store(&job_next, 0);
  busy = nworkers;
  generation++;
  pthread_cond_broadcast(&wake);
  pthread_mutex_unlock(&mu);
  inside = 1;
  drain(fn, ctx, count);
  inside = 0;
  pthread_mutex_lock(&mu);
  while (busy) pthread_cond_wait(&idle, &mu);  // ctx lives on the caller's stack
  pthread_mutex_unlock(&mu);
}

#elif defined(TC_PORTABLE)
void tc_thread_owns(void *table) { (void)table; }
int tc_parallel_start(int lanes) { (void)lanes; return 0; }
void tc_parallel_stop(void) {}
void tc_parallel_for(size_t count, TcParallelFn fn, void *ctx) {
  for (size_t i = 0; i < count; i++) fn(ctx, i);
}

#else
#include <dispatch/dispatch.h>
#include <pthread.h>
#include <stdlib.h>
typedef struct { void *table[8]; int n; } Owned;
static pthread_key_t owned_key;
static pthread_once_t owned_once = PTHREAD_ONCE_INIT;
static void owned_free(void *value) {
  Owned *owned = value;
  for (int i = 0; i < owned->n; i++) free(owned->table[i]);
  free(owned);
}
static void owned_init(void) { pthread_key_create(&owned_key, owned_free); }
void tc_thread_owns(void *table) {
  if (!table) return;
  pthread_once(&owned_once, owned_init);
  Owned *owned = pthread_getspecific(owned_key);
  if (!owned && (owned = calloc(1, sizeof *owned))) pthread_setspecific(owned_key, owned);
  if (owned && owned->n < 8) owned->table[owned->n++] = table;
}
int tc_parallel_start(int lanes) { (void)lanes; return 0; }
void tc_parallel_stop(void) {}
void tc_parallel_for(size_t count, TcParallelFn fn, void *ctx) {
  if (!tc_parallel_loops) {
    for (size_t i = 0; i < count; i++) fn(ctx, i);
    return;
  }
  dispatch_apply_f(count, dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ctx, fn);
}
#endif
