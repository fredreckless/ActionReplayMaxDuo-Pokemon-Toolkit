#!/bin/sh
# build.sh - fetch mGBA 0.10.5, add the cart-bus hook, build it as a library, and build vduo.
#   runner/build.sh            (from anywhere; needs git, cmake, a C compiler, zlib and libpng)
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
TOP=$(dirname "$HERE")
MGBA="$TOP/third_party/mgba-0.10.5"
LIB="$TOP/mgba/build"

if [ ! -d "$MGBA" ]; then
    mkdir -p "$TOP/third_party"
    git clone -q --depth 1 --branch 0.10.5 https://github.com/mgba-emu/mgba "$MGBA"
fi
if ! grep -q "struct GBACartBus" "$MGBA/include/mgba/internal/gba/memory.h"; then
    python3 "$TOP/mgba/apply_cart_bus.py" "$MGBA"
fi
if [ ! -f "$LIB/libmgba.a" ] || [ "$MGBA/src/gba/memory.c" -nt "$LIB/libmgba.a" ]; then
    mkdir -p "$LIB"
    (cd "$LIB" && cmake "$MGBA" -G Ninja -DCMAKE_BUILD_TYPE=Release \
        -DBUILD_QT=OFF -DBUILD_SDL=OFF -DBUILD_GL=OFF -DBUILD_GLES2=OFF -DBUILD_GLES3=OFF \
        -DBUILD_LIBRETRO=OFF -DBUILD_PERF=OFF -DBUILD_TEST=OFF -DBUILD_SUITE=OFF -DBUILD_CINEMA=OFF \
        -DBUILD_EXAMPLE=OFF -DBUILD_PYTHON=OFF -DBUILD_STATIC=ON -DBUILD_SHARED=OFF -DM_CORE_GB=OFF \
        -DUSE_FFMPEG=OFF -DUSE_MINIZIP=OFF -DUSE_LIBZIP=OFF -DUSE_LZMA=OFF -DUSE_EDITLINE=OFF \
        -DUSE_SQLITE3=OFF -DUSE_ELF=OFF -DUSE_LUA=OFF -DUSE_DISCORD_RPC=OFF -DUSE_DEBUGGERS=OFF \
        -DUSE_GDB_STUB=OFF -DENABLE_SCRIPTING=OFF -DUSE_PNG=ON -DUSE_ZLIB=ON > cmake.log && \
        cmake --build . --target mgba-static > build.log)
fi
mkdir -p "$HERE/build"
# Compile exactly as mGBA itself was compiled: its structs change shape with NDEBUG and its
# feature definitions, and a mismatch corrupts memory silently (the link-cable state, first).
DEFS=$(grep -A1 "src/gba/memory.c.o: C_COMPILER" "$LIB/build.ninja" | sed -n 's/.*DEFINES = //p' | head -1)
NDEBUG=$(grep -A3 "src/gba/memory.c.o: C_COMPILER" "$LIB/build.ninja" | grep -q -- "-DNDEBUG" && echo -DNDEBUG)
[ -n "$DEFS" ] || { echo "can't read mGBA's compile definitions from $LIB/build.ninja"; exit 1; }
${CC:-cc} -std=gnu99 -O2 -Wall -Wextra -Wno-unused-parameter $DEFS $NDEBUG \
    -include "$LIB/include/mgba/flags.h" -I"$MGBA/include" -I"$LIB/include" -I"$TOP/core" \
    "$HERE/vduo.c" "$TOP/core/duocore.c" \
    "$LIB/libmgba.a" -lpng -lz -lpthread -lm -o "$HERE/build/vduo"
echo "built $HERE/build/vduo"
