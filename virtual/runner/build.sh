#!/bin/sh
# build.sh - fetch mGBA 0.10.5, add the cart-bus hook and the link correction, build it as a library, and build vduo.
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
python3 "$TOP/mgba/apply_lockstep.py" "$MGBA"        # (does nothing once applied)
if [ ! -f "$LIB/libmgba.a" ] || [ "$MGBA/src/gba/memory.c" -nt "$LIB/libmgba.a" ] \
        || [ "$MGBA/src/gba/sio/lockstep.c" -nt "$LIB/libmgba.a" ]; then
    mkdir -p "$LIB"
    (cd "$LIB" && cmake "$MGBA" -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
        -DBUILD_QT=OFF -DBUILD_SDL=OFF -DBUILD_GL=OFF -DBUILD_GLES2=OFF -DBUILD_GLES3=OFF \
        -DBUILD_LIBRETRO=OFF -DBUILD_PERF=OFF -DBUILD_TEST=OFF -DBUILD_SUITE=OFF -DBUILD_CINEMA=OFF \
        -DBUILD_EXAMPLE=OFF -DBUILD_PYTHON=OFF -DBUILD_STATIC=ON -DBUILD_SHARED=OFF -DM_CORE_GB=OFF \
        -DUSE_FFMPEG=OFF -DUSE_MINIZIP=OFF -DUSE_LIBZIP=OFF -DUSE_LZMA=OFF -DUSE_EDITLINE=OFF \
        -DUSE_SQLITE3=OFF -DUSE_ELF=OFF -DUSE_LUA=OFF -DUSE_DISCORD_RPC=OFF -DUSE_DEBUGGERS=OFF \
        -DUSE_GDB_STUB=OFF -DENABLE_SCRIPTING=OFF -DUSE_PNG=ON -DUSE_ZLIB=ON > cmake.log && \
        cmake --build . --target mgba > build.log)
fi
mkdir -p "$HERE/build"
# Compile exactly as mGBA itself was compiled: its structs change shape with NDEBUG and its
# feature definitions, and a mismatch corrupts memory silently (the link-cable state, first).
# (Read from memory.c's block in build.ninja, which runs to the next blank line: its layout differs
# between CMake versions, so look for the DEFINES and FLAGS lines rather than counting.)
BLOCK=$(awk '/src\/gba\/memory\.c\.o: C_COMPILER/ {on = 1; next} on && /^$/ {exit} on' "$LIB/build.ninja")
DEFS=$(printf '%s\n' "$BLOCK" | sed -n 's/^ *DEFINES = //p' | head -1)
NDEBUG=""
if printf '%s\n' "$BLOCK" | grep -q -- "-DNDEBUG"; then NDEBUG=-DNDEBUG; fi
[ -n "$DEFS" ] || { echo "can't read mGBA's compile definitions from $LIB/build.ninja"; exit 1; }
${CC:-cc} -std=gnu99 -O2 -Wall -Wextra -Wno-unused-parameter $DEFS $NDEBUG \
    -include "$LIB/include/mgba/flags.h" -I"$MGBA/include" -I"$LIB/include" -I"$TOP/core" \
    "$HERE/vduo.c" "$TOP/core/duocore.c" \
    "$LIB/libmgba.a" -lpng -lz -lpthread -lm -o "$HERE/build/vduo"
echo "built $HERE/build/vduo"
