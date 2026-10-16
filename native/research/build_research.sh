#!/bin/sh
# Builds the two research comparator libraries without touching the installed
# native/libtuppi.dylib (IMPLEMENTATION_SPEC.md section 1.2):
#
#   <out>/source/libtuppi.dylib            B0-source: unmodified copies of the
#                                          pinned sources, native/build.sh's exact
#                                          compiler command and output name
#   <out>/research/libtuppi_research.dylib R0-parity: the same copies with
#                                          overlay.patch applied to tuppi_env.c,
#                                          plus research_api.c (which includes it)
#
# Usage: native/research/build_research.sh [out_dir]   (default native/research/build)
# Writes <out>/build_manifest.txt (commands, compiler, SDK, input/output hashes).
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
NATIVE=$(cd "$HERE/.." && pwd)
OUT=${1:-$HERE/build}
export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
CLANG="$DEVELOPER_DIR/Toolchains/XcodeDefault.xctoolchain/usr/bin/clang"
SDK="$(xcrun --sdk macosx --show-sdk-path)"
FLAGS="-O3 -Wall -Wextra -Wno-unused-parameter -isysroot $SDK -dynamiclib -framework Accelerate"
SOURCES="tuppi_core.c tuppi_env.c tuppi_search.c tuppi_dd.c tuppi_mlp.c tuppi_sooli.c tuppi_sooli_policy.c"
RESEARCH_SOURCES="tuppi_core.c research_api.c tuppi_search.c tuppi_dd.c tuppi_mlp.c tuppi_sooli.c tuppi_sooli_policy.c"
HEADERS="tuppi_core.h tuppi_mlp.h"

# Audit-pinned sources (evidence E004-E010); tuppi_mlp.[ch] are not in the
# audit and are pinned by the git HEAD check below instead.
cd "$NATIVE"
if ! git diff --quiet HEAD -- $SOURCES $HEADERS build.sh; then
  echo "native sources differ from the checked-out HEAD; refusing to build a comparator" >&2
  exit 2
fi
shasum -a 256 -c "$HERE/pinned_sources.sha256" >/dev/null || {
  echo "a pinned native source differs from its audit hash (see pinned_sources.sha256)" >&2
  exit 2
}

rm -rf "$OUT"
mkdir -p "$OUT/source" "$OUT/research"
for f in $SOURCES $HEADERS; do
  cp "$NATIVE/$f" "$OUT/source/$f"
  cp "$NATIVE/$f" "$OUT/research/$f"
done

# B0-source: the original build command, unchanged, in a private directory.
( cd "$OUT/source" && "$CLANG" $FLAGS -o libtuppi.dylib.tmp $SOURCES && mv -f libtuppi.dylib.tmp libtuppi.dylib )

# R0-parity: patch the copy (never the original), add the research API.
( cd "$OUT/research" && patch -p1 --quiet < "$HERE/overlay.patch" \
  && cp "$HERE/research_api.c" "$HERE/research_api.h" . \
  && "$CLANG" $FLAGS -o libtuppi_research.dylib.tmp $RESEARCH_SOURCES \
  && mv -f libtuppi_research.dylib.tmp libtuppi_research.dylib )

{
  echo "build_research.sh manifest"
  echo "date: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "clang: $("$CLANG" --version | head -1)"
  echo "sdk: $SDK"
  echo "flags: $FLAGS"
  echo "source_command: cd source && clang \$FLAGS -o libtuppi.dylib.tmp $SOURCES && mv -f libtuppi.dylib.tmp libtuppi.dylib"
  echo "research_command: cd research && patch -p1 < overlay.patch && clang \$FLAGS -o libtuppi_research.dylib.tmp $RESEARCH_SOURCES && mv"
  echo "native_git_head: $(git -C "$NATIVE" rev-parse HEAD)"
  echo "inputs:"
  ( cd "$NATIVE" && shasum -a 256 $SOURCES $HEADERS build.sh )
  ( cd "$HERE" && shasum -a 256 overlay.patch research_api.c research_api.h build_research.sh pinned_sources.sha256 )
  echo "patched_copy:"
  ( cd "$OUT/research" && shasum -a 256 tuppi_env.c )
  echo "outputs:"
  shasum -a 256 "$OUT/source/libtuppi.dylib" "$OUT/research/libtuppi_research.dylib" "$NATIVE/libtuppi.dylib"
} > "$OUT/build_manifest.txt"
echo "built $OUT/source/libtuppi.dylib and $OUT/research/libtuppi_research.dylib"
