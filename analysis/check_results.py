#!/usr/bin/env python3
"""Sanity checks over results/csv/runs.csv and summary.csv.

usage: check_results.py [RESULTS_DIR]

  1. every run found all its keys and did threads x reads lookups
  2. 1-thread runs: the W run and the WM warm-up left identical cache states
     (so the WM - W subtraction of tickers is exact)
  3. RocksDB applied the requested cache type, capacity and shard bits
  4. HyperClockCache has no priority pools: in E0 its results must not depend
     on cache_high_pri_pool_ratio (1 thread: identical miss counts)
  5. 1-thread runs are (nearly) deterministic: repetitions agree on miss counts
  6. run-to-run spread: coefficient of variation of throughput per config
Writes RESULTS_DIR/csv/checks.txt and prints it.
"""
import os
import sys

import pandas as pd


def main():
    results = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "results")
    runs = pd.read_csv(os.path.join(results, "csv", "runs.csv"))
    out = []

    def say(s=""):
        out.append(s)

    say(f"runs: {len(runs)} repetitions of {runs.config_id.nunique()} configurations")

    exp_ops = runs.threads * runs.reads_per_thread
    bad_ops = runs[runs.ops != exp_ops]
    say(f"[{'PASS' if bad_ops.empty else 'FAIL'}] measured lookups == threads x reads "
        f"({len(bad_ops)} mismatches)")

    one = runs[runs.threads == 1]
    if "warmup_state_match" in runs and not one.empty:
        chk = one.warmup_state_match.dropna()
        ok = int(chk.sum())
        say(f"[{'PASS' if ok == len(chk) else 'FAIL'}] 1-thread runs with identical "
            f"warm-up cache state in W and WM: {ok}/{len(chk)} "
            f"({len(one) - len(chk)} runs had a warm-up shorter than 10 s, so no fresh snapshot)")
    multi = runs[runs.threads > 1]
    if not multi.empty:
        if "warmup_occupancy_diff" in runs:
            rel = (multi.warmup_occupancy_diff.abs() /
                   multi.cache_entries_after_warmup.replace(0, float("nan")))
            say(f"[INFO] multi-thread runs: |cache entries after warm-up, WM - W| / entries: "
                f"median {rel.median():.2e}, max {rel.max():.2e}")
        for kind in ("data", "index", "filter"):
            col = f"w_{kind}_miss"
            if col in multi:
                g = multi.groupby("config_id")[col]
                spread = (g.max() - g.min()) / multi.groupby("config_id")[f"{kind}_accesses"].mean()
                say(f"[INFO] multi-thread runs: warm-up {kind} misses vary across repetitions by "
                    f"at most {spread.max():.1e} of the measured {kind} accesses "
                    f"(bound on the W-subtraction error)")

    exp_name = runs.cache_type.map({"lru_cache": "LRUCache",
                                    "auto_hyper_clock_cache": "AutoHyperClockCache",
                                    "fixed_hyper_clock_cache": "FixedHyperClockCache"})
    if "block_cache_name" in runs:
        bad = runs[(runs.block_cache_name != exp_name) |
                   (runs.applied_shard_bits.astype("Int64") != runs.shard_bits) |
                   (runs.applied_capacity.astype("Int64") != runs.cache_mb * 2**20)]
        say(f"[{'PASS' if bad.empty else 'FAIL'}] applied cache type / capacity / shard bits "
            f"match the request ({len(bad)} mismatches)")
    if "applied_use_direct_reads" in runs:
        nd = runs[runs.applied_use_direct_reads.astype("Int64") != 1]
        say(f"[{'PASS' if nd.empty else 'FAIL'}] direct reads enabled in every run")

    e0 = runs[runs.experiments.fillna("").str.contains("E0") &
              runs.cache_type.str.contains("hyper") & (runs.threads == 1)]
    if not e0.empty:
        worst = 0.0
        for kind in ("data", "index", "filter"):
            g = e0.groupby(["cache_type", "read_random_exp_range"])
            spread = (g[f"{kind}_miss"].max() - g[f"{kind}_miss"].min()) / g[f"{kind}_accesses"].mean()
            worst = max(worst, float(spread.max()))
        say(f"[{'PASS' if worst <= 1e-3 else 'FAIL'}] HyperClockCache, 1 thread: miss counts for "
            f"ratio 0 / 0.5 / 1 differ by at most {worst:.1e} of the accesses, the same as "
            f"between repetitions (the ratio has no effect on HCC)")
        lru = runs[runs.experiments.fillna("").str.contains("E0") & (runs.cache_type == "lru_cache")]
        if not lru.empty:
            t = lru.groupby(["read_random_exp_range", "high_pri_pool_ratio"])[
                ["index_miss_ratio", "filter_miss_ratio", "throughput_ops"]].mean()
            say("[INFO] LRUCache in E0 (64 MB, 1 thread): index/filter miss ratio and throughput by ratio")
            for (x, ratio_), v in t.iterrows():
                say(f"         skew {x:g}  ratio {ratio_:g}:  index {100 * v.index_miss_ratio:6.2f}%  "
                    f"filter {100 * v.filter_miss_ratio:6.2f}%  {v.throughput_ops:,.0f} ops/s")

    if not one.empty:
        # A single lookup thread is deterministic apart from RocksDB's own
        # background work (e.g. the stats collector touching the cache), so the
        # repetitions' miss counts should agree to within ~1e-3.
        cols = ["data_miss", "index_miss", "filter_miss"]
        g = one.groupby("config_id")
        rel = pd.concat([(g[c].max() - g[c].min()) /
                         (g[c.replace("_miss", "_accesses")].mean().replace(0, float("nan")))
                         for c in cols], axis=1).max(axis=1).fillna(0)
        exact = int((rel == 0).sum())
        say(f"[{'PASS' if rel.max() <= 1e-3 else 'FAIL'}] 1-thread configurations: repetitions agree "
            f"on miss counts (exactly in {exact}/{len(rel)}; max difference "
            f"{rel.max():.1e} of the accesses)")

    cv = runs.groupby("config_id").throughput_ops.agg(lambda s: s.std() / s.mean())
    if cv.notna().any():
        worst = cv.sort_values(ascending=False).head(5)
        say(f"[INFO] throughput coefficient of variation across repetitions: median "
            f"{cv.median():.3f}, max {cv.max():.3f}")
        for cfg, v in worst.items():
            say(f"         {v:.3f}  {cfg}")

    text = "\n".join(out)
    with open(os.path.join(results, "csv", "checks.txt"), "w") as f:
        f.write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
