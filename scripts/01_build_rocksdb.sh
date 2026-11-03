#!/usr/bin/env bash
# Build db_bench, sst_dump and ldb from RocksDB v11.8.1 in release mode.
#
#  * DEBUG_LEVEL=0  -> -O2 -DNDEBUG (the Makefile default is DEBUG_LEVEL=1,
#                      which keeps assertions on and makes benchmarks slow).
#  * DISABLE_JEMALLOC=1 -> glibc malloc on every machine, so results do not
#                      depend on whether libjemalloc-dev happens to be installed.
#  * PORTABLE unset  -> -march=native: build on the machine that runs the
#                      experiments.
#
# Needs: git, g++ (C++20), make, libgflags-dev, and the compression headers
# RocksDB normally builds with (libsnappy-dev liblz4-dev libzstd-dev zlib1g-dev
# libbz2-dev). The experiments use compression_type=none, but RocksDB 11.8.1 does
# not compile in release mode without Snappy (unused parameter in
# util/compression.cc + -Werror); if Snappy is missing we build with
# DISABLE_WARNING_AS_ERROR=1 instead, which only affects compiler warnings.
# Usage: scripts/01_build_rocksdb.sh            (JOBS=<n> to override)
set -euo pipefail
source "$(dirname "$0")/../config/common.sh"

JOBS="${JOBS:-$(nproc)}"
mkdir -p "$RESULTS"

if [ ! -d "$ROCKSDB_SRC" ]; then
  git clone --depth 1 --branch "$ROCKSDB_TAG" https://github.com/facebook/rocksdb.git "$ROCKSDB_SRC"
fi

cd "$ROCKSDB_SRC"
ver=$(awk '/define ROCKSDB_(MAJOR|MINOR|PATCH)/{printf "%s%s", sep, $3; sep="."}' include/rocksdb/version.h)
echo "RocksDB source version: $ver  commit: $(git rev-parse HEAD 2>/dev/null || echo unknown)"
if [ "v$ver" != "$ROCKSDB_TAG" ]; then
  echo "ERROR: source is $ver but ROCKSDB_TAG is $ROCKSDB_TAG" >&2
  exit 1
fi

if ! echo '#include <gflags/gflags.h>' | g++ -x c++ -fsyntax-only - 2>/dev/null; then
  echo "ERROR: gflags headers not found (Ubuntu/Debian: sudo apt-get install libgflags-dev)" >&2
  exit 1
fi

MAKE_VARS=(DEBUG_LEVEL=0 DISABLE_JEMALLOC=1)
if ! echo '#include <snappy.h>' | g++ -x c++ -fsyntax-only - 2>/dev/null; then
  echo "NOTE: snappy headers not found (sudo apt-get install libsnappy-dev); building with DISABLE_WARNING_AS_ERROR=1"
  MAKE_VARS+=(DISABLE_WARNING_AS_ERROR=1)
fi

{
  echo "# build started $(date -Is) on $(hostname)"
  echo "# g++: $(g++ --version | head -1)"
  echo "# AUTO_CLEAN=1 make -j$JOBS ${MAKE_VARS[*]} db_bench sst_dump ldb"
} > "$RESULTS/build.log"

AUTO_CLEAN=1 make -j"$JOBS" "${MAKE_VARS[@]}" db_bench sst_dump ldb 2>&1 | tee -a "$RESULTS/build.log"

# Mutex wait-time shim (optional LOCKSTAT=1 runs).
gcc -O2 -Wall -shared -fPIC -ftls-model=initial-exec -o "$PROJ/tools/lockstat/liblockstat.so" \
    "$PROJ/tools/lockstat/lockstat.c" -ldl -lpthread

# Record exactly how the binary was built.
{
  echo "rocksdb_version=$ver"
  echo "rocksdb_commit=$(git rev-parse HEAD 2>/dev/null || echo unknown)"
  echo "build_date=$(date -Is)"
  echo "host=$(hostname)"
  echo "compiler=$(g++ --version | head -1)"
  echo "make_vars=${MAKE_VARS[*]}"
  echo "opt_flags=-O2 -fno-omit-frame-pointer -momit-leaf-frame-pointer -DNDEBUG (Makefile, DEBUG_LEVEL=0)"
  echo "platform_cxxflags=$(grep '^PLATFORM_CXXFLAGS=' make_config.mk | cut -d= -f2- | tr -s ' ' | cut -c1-400)"
  echo "db_bench_sha256=$(sha256sum db_bench | cut -d' ' -f1)"
} > "$RESULTS/build_info.txt"

# Sanity: the release binary must not print the assertion/optimization warnings.
tmpdb=$(mktemp -d)
out=$(./db_bench --db="$tmpdb" --benchmarks=crc32c --num=1000 2>&1 || true)
rm -rf "$tmpdb"
if echo "$out" | grep -qE "WARNING: (Assertions|Optimization)"; then
  echo "ERROR: db_bench was built without optimizations or with assertions" >&2
  exit 1
fi
echo "OK: $(echo "$out" | grep -m1 'RocksDB:')"
cat "$RESULTS/build_info.txt"
