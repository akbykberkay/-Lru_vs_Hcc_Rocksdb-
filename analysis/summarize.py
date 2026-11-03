#!/usr/bin/env python3
"""Key comparisons HCC vs LRU per experimental point (from summary.csv).

usage: summarize.py [RESULTS_DIR]

For every point (cache size, threads, skew) that has the default LRU
configuration (ratio 0.5, default shards), prints throughput, p99 and the
index/filter/data miss ratios of LRU, auto HCC and fixed HCC, and the
throughput of each HCC relative to LRU. Writes results/tables/summary.md.
"""
import os
import sys

import pandas as pd

NAMES = {"lru_cache": "LRU", "auto_hyper_clock_cache": "HCC-auto",
         "fixed_hyper_clock_cache": "HCC-fixed"}


def default_bits(ct, mb):
    min_shard = 512 * 1024 if ct == "lru_cache" else 32 * 2**20
    n, b = mb * 2**20 // min_shard, 0
    while b < 6 and n >= 2:
        n >>= 1
        b += 1
    return b


def main():
    results = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "results")
    d = pd.read_csv(os.path.join(results, "csv", "summary.csv"))
    d = d[(d.high_pri_pool_ratio == 0.5) &
          (d.shard_bits == d.apply(lambda r: default_bits(r.cache_type, r.cache_mb), axis=1))]
    lines = ["| cache MB | threads | skew | cache | ops/s | vs LRU | p99 µs | data miss | index miss | filter miss |",
             "|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|"]
    for (mb, t, x), g in d.groupby(["cache_mb", "threads", "read_random_exp_range"]):
        lru = g[g.cache_type == "lru_cache"]
        base = lru.throughput_ops_mean.iloc[0] if not lru.empty else float("nan")
        for ct in NAMES:
            r = g[g.cache_type == ct]
            if r.empty:
                continue
            r = r.iloc[0]
            rel = r.throughput_ops_mean / base - 1
            lines.append(
                f"| {mb} | {t} | {x:g} | {NAMES[ct]} | {r.throughput_ops_mean:,.0f} ± "
                f"{r.throughput_ops_std:,.0f} | {'' if ct == 'lru_cache' else f'{100 * rel:+.1f}%'} | "
                f"{r.lat_p99_us_mean:.0f} | {100 * r.data_miss_ratio_mean:.1f}% | "
                f"{100 * r.index_miss_ratio_mean:.2f}% | {100 * r.filter_miss_ratio_mean:.2f}% |")
    text = "\n".join(lines)
    os.makedirs(os.path.join(results, "tables"), exist_ok=True)
    with open(os.path.join(results, "tables", "summary.md"), "w") as f:
        f.write("### LRU (ratio 0.5) vs HyperClockCache, default shards\n\n" + text + "\n")
    print(text)


if __name__ == "__main__":
    main()
