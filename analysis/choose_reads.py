#!/usr/bin/env python3
"""Choose --reads (lookups per thread) for every experimental point.

usage:
  choose_reads.py fill DB_SUMMARY_JSON CACHE_MB
      total lookups a uniform warm-up needs to fill a cache of CACHE_MB
  choose_reads.py choose DB_SUMMARY_JSON CAL_DIR OUT_TSV TARGET_SECONDS
      read the calibration runs in CAL_DIR and write OUT_TSV

Rule (the same --reads for every cache type at a point, so all caches see
exactly the same key sequence):

  reads_per_thread = max( fill(cache) / threads,
                          fastest calibrated throughput per thread * TARGET_SECONDS )

rounded up to a multiple of 10,000. The first term makes the warm-up fill the
cache: with uniform keys over B data blocks and room for C of them, the cache is
full after  n = -B * ln(1 - C/B)  lookups; we use 1.6 n, at least 100,000.
The second term makes every phase last at least TARGET_SECONDS on this
machine, so throughput is measured over a meaningful interval and the tail
percentiles have enough samples.
"""
import glob
import json
import math
import os
import re
import sys

MB = 1024 * 1024
BLOCK_OVERHEAD = 160      # Block object + cache handle, bytes per cached block (approx.)
MIN_TOTAL = 100_000
ROUND = 10_000


def fill_total(summary, cache_mb):
    blocks = summary["data_blocks"]
    charge = summary["avg_data_block_bytes"] + BLOCK_OVERHEAD
    meta = summary["index_plus_filter_bytes"] + summary["sst_files"] * 2 * BLOCK_OVERHEAD
    room = max(0.0, cache_mb * MB - meta) / charge
    if room >= blocks:
        n = blocks * (math.log(blocks) + 0.5772)   # coupon collector: every block once
    else:
        n = -blocks * math.log(1.0 - room / blocks)
    return max(MIN_TOTAL, int(math.ceil(1.6 * n / ROUND)) * ROUND)


def roundup(v):
    return int(math.ceil(v / ROUND)) * ROUND


READ_RE = re.compile(r"^readrandom\s*:\s*[\d.]+ micros/op (\d+) ops/sec", re.M)


def choose(summary, cal_dir, out_tsv, target):
    points = {}
    for path in sorted(glob.glob(os.path.join(cal_dir, "*.log"))):
        m = re.match(r"(\d+)_(\d+)_(\d+)__(\w+)\.log$", os.path.basename(path))
        if not m:
            continue
        mb, t, x, ct = int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4)
        found = READ_RE.findall(open(path, errors="replace").read())
        if len(found) != 2:
            sys.exit(f"{path}: expected two readrandom results, found {len(found)}")
        points.setdefault((mb, t, x), {})[ct] = int(found[1])
    rows = []
    for (mb, t, x), tp in sorted(points.items()):
        fill = fill_total(summary, mb)
        fastest = max(tp.values())
        reads = roundup(max(fill / t, fastest / t * target))
        rows.append((mb, t, x, reads, fill, fastest, tp))
    with open(out_tsv, "w") as f:
        f.write("cache_mb\tthreads\texp_range\treads_per_thread\tfill_total\tfastest_ops_per_sec\tcalibration\n")
        for mb, t, x, reads, fill, fastest, tp in rows:
            cal = ",".join(f"{k}={v}" for k, v in sorted(tp.items()))
            f.write(f"{mb}\t{t}\t{x}\t{reads}\t{fill}\t{fastest}\t{cal}\n")
    for mb, t, x, reads, fill, fastest, tp in rows:
        est = max(reads * t / v for v in tp.values())
        print(f"{mb:5d} MB  threads={t:<3d} exp_range={x:<3d} reads/thread={reads:>9,d}  "
              f"(fill {fill:>9,d}, fastest {fastest:>8,d} ops/s, slowest phase ~{est:.0f} s)")


def main():
    if len(sys.argv) >= 4 and sys.argv[1] == "fill":
        summary = json.load(open(sys.argv[2]))
        print(fill_total(summary, int(sys.argv[3])))
    elif len(sys.argv) == 6 and sys.argv[1] == "choose":
        summary = json.load(open(sys.argv[2]))
        choose(summary, sys.argv[3], sys.argv[4], float(sys.argv[5]))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
