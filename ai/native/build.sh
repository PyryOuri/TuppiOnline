#!/bin/sh
# Linux uses the portable backend; macOS keeps Accelerate unless --portable.
# Build by rename so an existing process keeps its mapped library inode.
set -eu
cd "$(dirname "$0")"
portable=0
blas=0
case "${1:-}" in --portable) portable=1 ;; --blas) portable=1; blas=1 ;; "") ;; *) echo "usage: build.sh [--portable|--blas]" >&2; exit 2 ;; esac
sources="tuppi_core.c tuppi_env.c tuppi_search.c tuppi_dd.c tuppi_mlp.c tuppi_sooli.c tuppi_sooli_policy.c tuppi_dd_wr.c tuppi_lite_net.c tuppi_browser.c tuppi_parallel.c"
case "$(uname -s)" in
  Linux)
    target=libtuppi.so
    blas_flags=""
    if [ "$blas" = 1 ]; then blas_flags="-DTC_HOSTED_BLAS -lopenblas"; fi
    "${CC:-cc}" -O3 -Wall -Wextra -Wno-unused-parameter -ffp-contract=off \
      -DTC_PORTABLE -fPIC -shared -o "$target.tmp" $sources -lm $blas_flags
    ;;
  Darwin)
    target=libtuppi.dylib
    export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
    clang="${CC:-$DEVELOPER_DIR/Toolchains/XcodeDefault.xctoolchain/usr/bin/clang}"
    sdk="$(xcrun --sdk macosx --show-sdk-path)"
    if [ "$portable" = 1 ]; then
      blas_flags=""
      if [ "$blas" = 1 ]; then blas_flags="-DTC_HOSTED_BLAS -framework Accelerate"; fi
      "$clang" -O3 -Wall -Wextra -Wno-unused-parameter -isysroot "$sdk" \
        -ffp-contract=off -DTC_PORTABLE -dynamiclib -o "$target.tmp" $sources -lm $blas_flags
    else
      "$clang" -O3 -Wall -Wextra -Wno-unused-parameter -isysroot "$sdk" \
        -dynamiclib -framework Accelerate -o "$target.tmp" $sources
    fi
    ;;
  *) echo "unsupported native platform" >&2; exit 2 ;;
esac
mv -f "$target.tmp" "$target"
echo "built $(pwd)/$target"
