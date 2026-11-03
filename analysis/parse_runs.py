#!/usr/bin/env python3
"""Parse every finished run under results/raw into CSV files.

usage: parse_runs.py [RESULTS_DIR]

For each configuration and repetition (results/raw/<config>/rep<k>/) it reads
  w.log   db_bench output of the warm-up-only run  (readrandom,stats)
  wm.log  db_bench output of the warm-up + measure run (readrandom,stats,readrandom,stats)
and computes the measured-phase values:
  * throughput and latency percentiles: from the second readrandom of wm.log;
  * statistics tickers: wm - w, because db_bench prints cumulative tickers
    once, at the end of the process (setup doc: "subtract the warm-up counts");
  * CPU time and context switches per lookup: rusage of wm minus rusage of w.

Writes
  results/csv/runs.csv     one row per repetition
  results/csv/summary.csv  mean / std / min / max over repetitions per configuration
and prints sanity-check warnings.
"""
import glob
import gzip
import json
import math
import os
import re
import statistics
import sys

UNITS = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}

READ_RE = re.compile(
    r"^readrandom\s*:\s*([\d.]+) micros/op (\d+) ops/sec ([\d.]+) seconds (\d+) operations;"
    r"(?:\s+[\d.]+ MB/s)?\s*(?:\((\d+) of (\d+) found\))?", re.M)
HIST_RE = re.compile(
    r"Microseconds per read:\nCount: (\d+) Average: ([\d.]+)\s+StdDev: ([\d.]+)\n"
    r"Min: (\d+)\s+Median: ([\d.]+)\s+Max: (\d+)\n"
    r"Percentiles: P50: ([\d.]+) P75: ([\d.]+) P99: ([\d.]+) P99\.9: ([\d.]+) P99\.99: ([\d.]+)")
TICKER_RE = re.compile(r"^(rocksdb\.[\w.\-]+) COUNT : (\d+)$", re.M)
HISTSTAT_RE = re.compile(
    r"^(rocksdb\.[\w.\-]+) P50 : ([\d.]+) P95 : ([\d.]+) P99 : ([\d.]+) P100 : ([\d.]+) "
    r"COUNT : (\d+) SUM : (\d+)$", re.M)
CACHE_RE = re.compile(
    r"Block cache (\S+) capacity: ([\d.]+ \w+) seed: (\d+) usage: ([\d.]+ \w+) "
    r"table_size: (\d+) occupancy: (\d+) collections: (\d+) .*?secs_since: (\d+)")
ENTRY_RE = re.compile(r"(\w+)\((\d+),([\d.]+ \w+),([\d.eE+\-]+)%\)")


def human_bytes(s):
    num, unit = s.split()
    return float(num) * UNITS[unit]


def parse_log(path):
    text = open(path, errors="replace").read()
    out = {"text_ok": "STATISTICS:" in text}
    out["version"] = (re.search(r"RocksDB:\s+version (\S+)", text) or [None, None])[1]
    out["reads"] = [
        {"micros_per_op": float(m.group(1)), "ops_per_sec": int(m.group(2)),
         "seconds": float(m.group(3)), "ops": int(m.group(4)),
         "found": int(m.group(5)) if m.group(5) else None,
         "found_of": int(m.group(6)) if m.group(6) else None}
        for m in READ_RE.finditer(text)]
    out["hists"] = [
        {"count": int(m.group(1)), "avg": float(m.group(2)), "std": float(m.group(3)),
         "min": int(m.group(4)), "median": float(m.group(5)), "max": int(m.group(6)),
         "p50": float(m.group(7)), "p75": float(m.group(8)), "p99": float(m.group(9)),
         "p999": float(m.group(10)), "p9999": float(m.group(11))}
        for m in HIST_RE.finditer(text)]
    caches = []
    for m in CACHE_RE.finditer(text):
        entry_line = text[m.end():].split("\n", 2)[1] if "\n" in text[m.end():] else ""
        roles = {}
        for e in ENTRY_RE.finditer(entry_line):
            roles[e.group(1)] = {"count": int(e.group(2)), "bytes": human_bytes(e.group(3))}
        caches.append({"id": m.group(1), "capacity": human_bytes(m.group(2)),
                       "seed": int(m.group(3)), "usage": human_bytes(m.group(4)),
                       "table_size": int(m.group(5)), "occupancy": int(m.group(6)),
                       "collections": int(m.group(7)), "secs_since": int(m.group(8)),
                       # "rocksdb.stats" only prints the last scan made by the
                       # periodic stats dump (every 600 s), never a new one, so
                       # the snapshot is used only if it is fresh (secs_since 0).
                       "fresh": int(m.group(8)) == 0, "roles": roles})
    out["cache_stats"] = caches
    stats_part = text.split("STATISTICS:", 1)[1] if "STATISTICS:" in text else ""
    out["tickers"] = {k: int(v) for k, v in TICKER_RE.findall(stats_part)}
    out["histstats"] = {m.group(1): {"count": int(m.group(6)), "sum": int(m.group(7)),
                                     "p50": float(m.group(2)), "p99": float(m.group(4))}
                        for m in HISTSTAT_RE.finditer(stats_part)}
    return out


def parse_cache_options(log_gz):
    """Block cache settings that RocksDB actually applied (from its LOG)."""
    try:
        text = gzip.open(log_gz, "rt", errors="replace").read()
    except OSError:
        return {}
    res = {}
    for key, pat in [("block_cache_name", r"block_cache_name: (\S+)"),
                     ("applied_capacity", r"capacity : (\d+)"),
                     ("applied_shard_bits", r"num_shard_bits : (\d+)"),
                     ("applied_high_pri_ratio", r"high_pri_pool_ratio: ([\d.]+)"),
                     ("applied_cache_index_and_filter", r"cache_index_and_filter_blocks: (\d)"),
                     ("applied_filter_policy", r"filter_policy: (\S+)"),
                     ("applied_block_size", r"block_size: (\d+)"),
                     ("applied_use_direct_reads", r"Options.use_direct_reads: (\d)")]:
        m = re.search(pat, text)
        if m:
            res[key] = m.group(1)
    return res


T = {  # ticker short names
    "data_hit": "rocksdb.block.cache.data.hit", "data_miss": "rocksdb.block.cache.data.miss",
    "index_hit": "rocksdb.block.cache.index.hit", "index_miss": "rocksdb.block.cache.index.miss",
    "filter_hit": "rocksdb.block.cache.filter.hit", "filter_miss": "rocksdb.block.cache.filter.miss",
    "all_hit": "rocksdb.block.cache.hit", "all_miss": "rocksdb.block.cache.miss",
    "cache_add": "rocksdb.block.cache.add", "cache_add_fail": "rocksdb.block.cache.add.failures",
    "data_add": "rocksdb.block.cache.data.add", "index_add": "rocksdb.block.cache.index.add",
    "filter_add": "rocksdb.block.cache.filter.add",
    "bloom_useful": "rocksdb.bloom.filter.useful",
    "bloom_full_positive": "rocksdb.bloom.filter.full.positive",
    "bloom_full_true_positive": "rocksdb.bloom.filter.full.true.positive",
    "keys_read": "rocksdb.number.keys.read",
    "get_hit_l0": "rocksdb.l0.hit", "get_hit_l1": "rocksdb.l1.hit",
    "get_hit_l2up": "rocksdb.l2andup.hit",
    "bytes_read_cache": "rocksdb.block.cache.bytes.read",
    "bytes_insert_cache": "rocksdb.block.cache.bytes.write",
    "add_redundant": "rocksdb.block.cache.add.redundant",
    "data_add_redundant": "rocksdb.block.cache.data.add.redundant",
}


def ratio(num, den):
    return num / den if den else float("nan")


def parse_run(rep_dir):
    meta = json.load(open(os.path.join(rep_dir, "meta.json")))
    w = parse_log(os.path.join(rep_dir, "w.log"))
    wm = parse_log(os.path.join(rep_dir, "wm.log"))
    ru_w = json.load(open(os.path.join(rep_dir, "w.rusage.json")))
    ru_wm = json.load(open(os.path.join(rep_dir, "wm.rusage.json")))
    warnings = []

    row = dict(meta)
    row["rep_dir"] = rep_dir
    row["version"] = wm["version"]
    if len(wm["reads"]) != 2 or len(wm["hists"]) != 2 or len(w["reads"]) != 1:
        warnings.append(f"unexpected number of readrandom results "
                        f"(wm {len(wm['reads'])}, w {len(w['reads'])})")
        return row, warnings
    meas, warm_in_wm, warm_w = wm["reads"][1], wm["reads"][0], w["reads"][0]
    hist = wm["hists"][1]
    expected_ops = meta["threads"] * meta["reads_per_thread"]
    row.update({
        "ops": meas["ops"], "seconds": meas["seconds"],
        "throughput_ops": meas["ops_per_sec"], "micros_per_op_thread": meas["micros_per_op"],
        "lat_avg_us": hist["avg"], "lat_p50_us": hist["p50"], "lat_p75_us": hist["p75"],
        "lat_p99_us": hist["p99"], "lat_p999_us": hist["p999"], "lat_p9999_us": hist["p9999"],
        "lat_max_us": hist["max"],
        "warmup_throughput_ops": warm_in_wm["ops_per_sec"],
        "warmup_throughput_w_run": warm_w["ops_per_sec"],
    })
    if meas["ops"] != expected_ops:
        warnings.append(f"measured ops {meas['ops']} != threads*reads {expected_ops}")
    if hist["count"] != meas["ops"]:
        warnings.append(f"histogram count {hist['count']} != ops {meas['ops']}")
    for r in (meas, warm_in_wm, warm_w):
        if r["found"] is not None and r["found"] != r["found_of"]:
            warnings.append(f"not all keys found: {r['found']} of {r['found_of']}")

    # Measured-phase tickers = WM - W
    tw, twm = w["tickers"], wm["tickers"]
    if not tw or not twm:
        warnings.append("missing STATISTICS")
        return row, warnings
    delta = {}
    for short, name in T.items():
        if name in twm:
            delta[short] = twm[name] - tw.get(name, 0)
            # "redundant add" counts depend on thread races, so with several
            # threads the W and WM warm-ups differ by a few: not an error.
            if delta[short] < 0 and not (meta["threads"] > 1 and "redundant" in name):
                warnings.append(f"negative delta for {name}: {delta[short]}")
    for k, v in delta.items():
        row[k] = v
    for kind in ("data", "index", "filter", "all"):
        h, m = delta.get(f"{kind}_hit", 0), delta.get(f"{kind}_miss", 0)
        row[f"{kind}_accesses"] = h + m
        row[f"{kind}_miss_ratio"] = ratio(m, h + m)
        row[f"{kind}_misses_per_lookup"] = ratio(m, meas["ops"])
        row[f"{kind}_accesses_per_lookup"] = ratio(h + m, meas["ops"])
    # Warm-up phase alone (W run): its miss ratio, and the raw counts that were
    # subtracted (their spread across repetitions bounds the subtraction error
    # for multi-threaded runs, whose warm-up is not exactly repeatable).
    for kind in ("data", "index", "filter", "all"):
        h = tw.get(T[f"{kind}_hit"], 0)
        m = tw.get(T[f"{kind}_miss"], 0)
        row[f"warmup_{kind}_miss_ratio"] = ratio(m, h + m)
        row[f"w_{kind}_hit"], row[f"w_{kind}_miss"] = h, m
    # I/O latency of block reads in the measured phase (mean only; histograms
    # cannot be subtracted percentile-wise).
    for name, short in (("rocksdb.sst.read.micros", "sst_read"),
                        ("rocksdb.db.get.micros", "db_get")):
        a, b = w["histstats"].get(name), wm["histstats"].get(name)
        if a and b:
            cnt = b["count"] - a["count"]
            row[f"{short}_count"] = cnt
            row[f"{short}_mean_us"] = ratio(b["sum"] - a["sum"], cnt)
    # CPU and context switches of the measured phase
    cpu = (ru_wm["utime_s"] + ru_wm["stime_s"]) - (ru_w["utime_s"] + ru_w["stime_s"])
    row["cpu_s"] = cpu
    row["cpu_us_per_op"] = ratio(cpu * 1e6, meas["ops"])
    row["user_us_per_op"] = ratio((ru_wm["utime_s"] - ru_w["utime_s"]) * 1e6, meas["ops"])
    row["sys_us_per_op"] = ratio((ru_wm["stime_s"] - ru_w["stime_s"]) * 1e6, meas["ops"])
    row["vol_ctx_switches_per_op"] = ratio(ru_wm["nvcsw"] - ru_w["nvcsw"], meas["ops"])
    row["invol_ctx_switches_per_op"] = ratio(ru_wm["nivcsw"] - ru_w["nivcsw"], meas["ops"])
    row["read_kb_per_op"] = ratio((ru_wm["inblock"] - ru_w["inblock"]) * 512 / 1024, meas["ops"])
    row["maxrss_mb"] = ru_wm["maxrss_kb"] / 1024
    # Optional mutex wait time (LOCKSTAT=1 runs). The shim reports counters per
    # thread in order of thread start; db_bench starts new reader threads for
    # each benchmark, so the last `threads` slots of the WM run are the readers
    # of the measured phase. (A WM - W difference would be dominated by the
    # noisy lock waits of the 16 file-opening threads at DB open.)
    lw, lwm = (os.path.join(rep_dir, f"{t}.lockstat.json") for t in ("w", "wm"))
    if os.path.exists(lw) and os.path.exists(lwm):
        a, b = json.load(open(lw)), json.load(open(lwm))
        t = meta["threads"]
        if "slots" in b and b["threads_seen"] - a["threads_seen"] == t and len(b["slots"]) >= t:
            readers = b["slots"][-t:]
            acq = sum(x[0] for x in readers)
            cont = sum(x[1] for x in readers)
            wait_s = sum(x[2] for x in readers) / 1e9
            row["lock_method"] = "measured-phase reader threads"
        else:
            warnings.append("lockstat: cannot isolate reader threads; using WM - W totals")
            acq = b["acquisitions"] - a["acquisitions"]
            cont = b["contended"] - a["contended"]
            wait_s = (b["wait_ns"] - a["wait_ns"]) / 1e9
            row["lock_method"] = "WM - W totals"
        row["lock_acquisitions_per_op"] = ratio(acq, meas["ops"])
        row["lock_contended_per_op"] = ratio(cont, meas["ops"])
        row["lock_contended_frac"] = ratio(cont, acq)
        row["lock_wait_us_per_op"] = ratio(wait_s * 1e6, meas["ops"])
        # share of the threads' time spent waiting for a mutex
        row["lock_wait_share"] = ratio(wait_s, meta["threads"] * meas["seconds"])
    row["wall_w_s"], row["wall_wm_s"] = ru_w["wall_s"], ru_wm["wall_s"]
    # The W run and the warm-up of the WM run must leave the cache in the same
    # state (exactly, with one thread): compare entry counts after the warm-up.
    if (w["cache_stats"] and wm["cache_stats"] and w["cache_stats"][0]["fresh"]
            and wm["cache_stats"][0]["fresh"]):
        a, b = w["cache_stats"][0], wm["cache_stats"][0]
        same = (a["occupancy"] == b["occupancy"] and
                {k: v["count"] for k, v in a["roles"].items()} ==
                {k: v["count"] for k, v in b["roles"].items()})
        row["warmup_state_match"] = int(same)
        row["warmup_occupancy_diff"] = b["occupancy"] - a["occupancy"]
        if meta["threads"] == 1 and not same:
            warnings.append("1-thread warm-ups of W and WM left different cache states")
    # Cache contents after warm-up and after the measured phase
    # Cache contents (only when the scan is fresh, see CACHE_RE).
    cs = wm["cache_stats"]
    for i, tag in ((0, "after_warmup"), (1, "after_measure")):
        if len(cs) > i and cs[i]["fresh"]:
            c = cs[i]
            row[f"cache_usage_mb_{tag}"] = c["usage"] / 2**20
            row[f"cache_fill_{tag}"] = ratio(c["usage"], c["capacity"])
            row[f"cache_entries_{tag}"] = c["occupancy"]
            for role in ("DataBlock", "IndexBlock", "FilterBlock"):
                r = c["roles"].get(role, {"count": 0, "bytes": 0})
                row[f"cache_{role}_mb_{tag}"] = r["bytes"] / 2**20
                row[f"cache_{role}_count_{tag}"] = r["count"]
    # What RocksDB really applied
    row.update(parse_cache_options(os.path.join(rep_dir, "wm.LOG.gz")))
    exp_name = {"lru_cache": "LRUCache", "auto_hyper_clock_cache": "AutoHyperClockCache",
                "fixed_hyper_clock_cache": "FixedHyperClockCache"}[meta["cache_type"]]
    if row.get("block_cache_name") and row["block_cache_name"] != exp_name:
        warnings.append(f"block cache is {row['block_cache_name']}, expected {exp_name}")
    if row.get("applied_shard_bits") and int(row["applied_shard_bits"]) != meta["shard_bits"]:
        warnings.append(f"applied shard bits {row['applied_shard_bits']} != {meta['shard_bits']}")
    if row.get("applied_capacity") and int(row["applied_capacity"]) != meta["cache_mb"] * 2**20:
        warnings.append(f"applied capacity {row['applied_capacity']}")
    return row, warnings


def experiments_of(row, max_threads, skew=10):
    e = []
    mb, t, x = row["cache_mb"], row["threads"], row["read_random_exp_range"]
    ct, bits, r = row["cache_type"], row["shard_bits"], row["high_pri_pool_ratio"]
    default_bits = default_shard_bits(ct, mb)
    if mb == 64 and t == 1 and x in (0, skew) and bits == default_bits:
        e.append("E0")
    if mb in (32, 128, 512, 2048) and t == 1 and x in (0, skew) and r == 0.5 and bits == default_bits:
        e.append("E1")
    if mb == 2048 and x in (0, skew) and r == 0.5 and bits == default_bits:
        e.append("E2")
    if mb == 1024 and t == max_threads and r == 0.5:
        e.append("E3")
    if mb == 64 and x in (0, 5, 10, 20) and t in (1, max_threads) and r == 0.5 and bits == default_bits:
        e.append("E4")
    return "+".join(e)


def default_shard_bits(cache_type, mb):
    min_shard = 512 * 1024 if cache_type == "lru_cache" else 32 * 2**20
    n, bits = mb * 2**20 // min_shard, 0
    while bits < 6 and n >= 2:
        n >>= 1
        bits += 1
    return bits


def write_csv(path, rows, cols):
    import csv
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in cols})


def main():
    results = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "results")
    rep_dirs = sorted(glob.glob(os.path.join(results, "raw", "*", "rep*")))
    rows, n_warn = [], 0
    for d in rep_dirs:
        if not os.path.exists(os.path.join(d, "done")):
            continue
        row, warns = parse_run(d)
        for wmsg in warns:
            n_warn += 1
            print(f"WARNING {os.path.relpath(d, results)}: {wmsg}")
        rows.append(row)
    if not rows:
        print("no finished runs")
        return 0
    max_threads = max(r.get("max_threads", 1) for r in rows)
    for r in rows:
        r["experiments"] = experiments_of(r, max_threads)
    os.makedirs(os.path.join(results, "csv"), exist_ok=True)

    key_cols = ["config_id", "experiments", "cache_type", "cache_mb", "shard_bits",
                "high_pri_pool_ratio", "threads", "read_random_exp_range", "reads_per_thread"]
    first = key_cols + ["rep"]
    metric_cols = []
    for r in rows:
        for k, v in r.items():
            if k not in first and k not in metric_cols and isinstance(v, (int, float)) \
                    and not isinstance(v, bool) and k not in ("max_threads",):
                metric_cols.append(k)
    other = [k for k in rows[0] if k not in first and k not in metric_cols]
    write_csv(os.path.join(results, "csv", "runs.csv"), rows, first + metric_cols + other)

    groups = {}
    for r in rows:
        groups.setdefault(r["config_id"], []).append(r)
    summary = []
    for cfg, rs in sorted(groups.items()):
        s = {k: rs[0][k] for k in key_cols}
        s["n_reps"] = len(rs)
        for k in metric_cols:
            vals = [r[k] for r in rs if isinstance(r.get(k), (int, float))
                    and not (isinstance(r.get(k), float) and math.isnan(r[k]))]
            if not vals:
                continue
            s[f"{k}_mean"] = statistics.fmean(vals)
            s[f"{k}_std"] = statistics.stdev(vals) if len(vals) > 1 else 0.0
            s[f"{k}_min"] = min(vals)
            s[f"{k}_max"] = max(vals)
        summary.append(s)
    scols = key_cols + ["n_reps"] + [f"{k}_{a}" for k in metric_cols
                                     for a in ("mean", "std", "min", "max")]
    write_csv(os.path.join(results, "csv", "summary.csv"), summary, scols)
    print(f"parsed {len(rows)} repetitions of {len(groups)} configurations "
          f"({n_warn} warnings) -> {os.path.join(results, 'csv')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
