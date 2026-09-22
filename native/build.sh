#!/bin/sh
# Builds libtuppi.dylib with the Xcode toolchain. The CommandLineTools SDK on
# this machine has a linker/tbd mismatch ("tapi error: malformed file").
set -e
cd "$(dirname "$0")"
export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
CLANG="$DEVELOPER_DIR/Toolchains/XcodeDefault.xctoolchain/usr/bin/clang"
SDK="$(xcrun --sdk macosx --show-sdk-path)"
"$CLANG" -O3 -Wall -Wextra -Wno-unused-parameter -isysroot "$SDK" -dynamiclib \
  -o libtuppi.dylib.tmp tuppi_core.c tuppi_env.c tuppi_search.c tuppi_dd.c
# Rename, never overwrite in place: a running process keeps its mapped inode.
mv -f libtuppi.dylib.tmp libtuppi.dylib
echo "built $(pwd)/libtuppi.dylib"
