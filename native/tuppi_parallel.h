#ifndef TUPPI_PARALLEL_H
#define TUPPI_PARALLEL_H
#include <stddef.h>

/* Browser builds execute within one dedicated worker. Native builds retain
 * dispatch scheduling and the same independent per-game RNG streams. */
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
