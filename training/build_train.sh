#!/bin/sh
# Builds the training library (OpenMP loops + the tc_ls_* lockstep functions).
#
#   sh training/build_train.sh            -> training/build/libtuppi_train.so
#   sh training/build_train.sh --stock    -> training/build/libtuppi_stock.so
#
# --stock compiles the twelve hosted sources exactly as ai/native/build.sh
# --blas does (serial loops), into the same out-of-tree directory, as the
# reference for the equivalence tests. Neither build writes into ai/native.
#
# BLAS: the system OpenBLAS (apt-get install libopenblas-dev) if present,
# otherwise the scipy-openblas32 wheel (pip install scipy-openblas32).
# Use the library with TUPPI_NATIVE_LIBRARY=<path> (ai/tuppi_ai/native.py).
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
src="$(dirname "$here")/ai/native"
out="${TUPPI_BUILD_DIR:-$here/build}"
mkdir -p "$out"
stock=0
case "${1:-}" in --stock) stock=1 ;; "") ;; *) echo "usage: build_train.sh [--stock]" >&2; exit 2 ;; esac

cc="${CC:-cc}"
blas=""
if printf '#include <cblas.h>\nint main(void){openblas_set_num_threads(1);return 0;}\n' \
     | "$cc" -x c - -o /dev/null -lopenblas 2>/dev/null; then
  blas="-lopenblas"
else
  py="${PYTHON:-python3}"
  inc="$("$py" -c 'import scipy_openblas32 as s; print(s.get_include_dir())' 2>/dev/null || true)"
  lib="$("$py" -c 'import scipy_openblas32 as s; print(s.get_lib_dir())' 2>/dev/null || true)"
  if [ -z "$inc" ]; then
    echo "no OpenBLAS: apt-get install libopenblas-dev, or pip install scipy-openblas32" >&2; exit 1
  fi
  blas="-I$inc -L$lib -lscipy_openblas -Wl,-rpath,$lib -Dcblas_sgemm=scipy_cblas_sgemm -Dopenblas_set_num_threads=scipy_openblas_set_num_threads"
fi

common="tuppi_core.c tuppi_search.c tuppi_dd.c tuppi_mlp.c tuppi_sooli.c tuppi_sooli_policy.c tuppi_dd_wr.c tuppi_lite_net.c tuppi_browser.c tuppi_parallel.c tuppi_dan.c"
flags="-O3 -Wall -Wextra -Wno-unused-parameter -ffp-contract=off -DTC_PORTABLE -DTC_HOSTED_BLAS -fPIC -shared"
cd "$src"
if [ "$stock" = 1 ]; then
  target="$out/libtuppi_stock.so"
  # shellcheck disable=SC2086
  "$cc" $flags -o "$target.tmp" tuppi_env.c $common -lm $blas
else
  target="$out/libtuppi_train.so"
  # shellcheck disable=SC2086
  "$cc" $flags -fopenmp -I"$src" -o "$target.tmp" "$here/native/tuppi_train.c" $common -lm $blas
fi
mv -f "$target.tmp" "$target"
echo "built $target"
