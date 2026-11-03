#!/usr/bin/env python3
"""Verify the bulk-loaded DB and summarize its shape.

usage: verify_db.py DB_DIR SST_DUMP LOAD_LOG OUT_DIR NUM_KEYS

Checks
  * every key is present exactly once (sum of "# entries" == NUM_KEYS),
  * the SST files on disk are the ones sst_dump read,
  * L0 has fewer files than level0_file_num_compaction_trigger (4),
  * every level is at or below its target size after waitforcompaction
    (compaction score <= 1).
Reports
  * files and size per level, total data / index / filter block sizes,
  * which cache sizes can hold all index + filter blocks.
Writes OUT_DIR/db_summary.json and OUT_DIR/sst_properties.txt.
"""
import glob
import json
import os
import re
import subprocess
import sys

MB = 1024 * 1024
L0_TRIGGER = 4
LEVEL_BASE = 32 * MB
MULTIPLIER = 2


def run_sst_dump(sst_dump, db_dir, out_path):
    cmd = [sst_dump, f"--file={db_dir}", "--command=none",
           "--show_properties", "--show_summary"]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    with open(out_path, "w") as f:
        f.write(res.stdout)
        if res.stderr:
            f.write("\n# stderr\n" + res.stderr)
    if res.returncode != 0:
        sys.exit(f"sst_dump failed ({res.returncode}): {res.stderr[:500]}")
    return res.stdout


def parse_sst_props(text):
    files = []
    cur = None
    for line in text.splitlines():
        if line.startswith("Table Properties:"):
            cur = {}
            files.append(cur)
            continue
        if cur is None:
            continue
        m = re.match(r"\s+(# data blocks|# entries|data block size|filter block size"
                     r"|raw key size|raw value size|original file number)"
                     r": (\d+)$", line)
        if m:
            cur[m.group(1)] = int(m.group(2))
            continue
        m = re.match(r"\s+index block size \(user-key\? (\d), delta-value\? (\d)\): (\d+)$", line)
        if m:
            cur["index block size"] = int(m.group(3))
            cur["index_key_is_user_key"] = int(m.group(1))
            cur["index_value_is_delta_encoded"] = int(m.group(2))
    summary = {}
    for key in ("total number of files", "total number of data blocks",
                "total data block size", "total index block size",
                "total filter block size"):
        m = re.search(re.escape(key) + r": (\d+)", text)
        if m:
            summary[key] = int(m.group(1))
    return files, summary


def to_bytes(value, unit):
    scale = {"B": 1, "KB": 1024, "MB": MB, "GB": 1024 * MB, "TB": 1024 * 1024 * MB}
    return float(value) * scale[unit]


def parse_load_log(path):
    """Level shape from the db_bench 'stats' output printed after the load."""
    text = open(path, errors="replace").read()
    levels = {}
    # Compaction stats table, e.g. "  L3     98/0   97.71 MB   0.8 ..."
    for m in re.finditer(r"^\s+L(\d+)\s+(\d+)/(\d+)\s+([\d.]+) (B|KB|MB|GB|TB)\s+([\d.]+)",
                         text, re.M):
        lvl = int(m.group(1))
        levels[lvl] = {"files": int(m.group(2)),
                       "files_being_compacted": int(m.group(3)),
                       "bytes": to_bytes(m.group(4), m.group(5)),
                       "score": float(m.group(6))}
    wamp = None
    m = re.search(r"^\s+Sum\s+\d+/\d+\s+[\d.]+ \w+\s+[\d.]+\s+[\d.]+\s+[\d.]+\s+[\d.]+"
                  r"\s+[\d.]+\s+[\d.]+\s+[\d.]+\s+([\d.]+)", text, re.M)
    if m:
        wamp = float(m.group(1))
    fill = re.search(r"^filluniquerandom\s*:\s*([\d.]+) micros/op\s+(\d+) ops/sec\s+([\d.]+) seconds",
                     text, re.M)
    wfc = re.search(r"waitforcompaction\(.*\): finished with status \((.*)\)", text)
    return {
        "levels": levels,
        "write_amplification": wamp,
        "fill_ops_per_sec": int(fill.group(2)) if fill else None,
        "fill_seconds": float(fill.group(3)) if fill else None,
        "waitforcompaction_status": wfc.group(1) if wfc else None,
        "version": (re.search(r"RocksDB:\s+version (\S+)", text) or [None, None])[1],
    }


def main():
    if len(sys.argv) != 6:
        sys.exit(__doc__)
    db_dir, sst_dump, load_log, out_dir, num_keys = sys.argv[1:]
    num_keys = int(num_keys)
    os.makedirs(out_dir, exist_ok=True)

    ssts = sorted(glob.glob(os.path.join(db_dir, "*.sst")))
    sst_bytes = sum(os.path.getsize(f) for f in ssts)
    text = run_sst_dump(sst_dump, db_dir, os.path.join(out_dir, "sst_properties.txt"))
    files, summary = parse_sst_props(text)
    load = parse_load_log(load_log)

    def total(key):
        return sum(f.get(key, 0) for f in files)

    entries = total("# entries")
    index_bytes = total("index block size")
    filter_bytes = total("filter block size")
    data_bytes = total("data block size")
    data_blocks = total("# data blocks")
    meta = index_bytes + filter_bytes

    checks = []

    def check(name, ok, detail):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    check("sst files read by sst_dump == files on disk",
          len(files) == len(ssts) == summary.get("total number of files", -1),
          f"{len(files)} parsed, {len(ssts)} on disk, summary {summary.get('total number of files')}")
    check("every key stored exactly once", entries == num_keys,
          f"{entries} entries, expected {num_keys}")
    check("sst_dump totals match per-file sums",
          summary.get("total index block size") == index_bytes
          and summary.get("total filter block size") == filter_bytes,
          f"index {index_bytes}, filter {filter_bytes}")
    lv = load["levels"]
    check("waitforcompaction finished OK", load["waitforcompaction_status"] == "OK",
          str(load["waitforcompaction_status"]))
    if lv:
        l0 = lv.get(0, {}).get("files", 0)
        check("L0 below compaction trigger", l0 < L0_TRIGGER, f"L0 files = {l0}")
        over = {k: v["score"] for k, v in lv.items() if v["score"] > 1.0}
        check("all levels within target size (score <= 1)", not over, f"over target: {over}")
        files_in_levels = sum(v["files"] for v in lv.values())
        check("level table accounts for all files", files_in_levels == len(ssts),
              f"{files_in_levels} in level table, {len(ssts)} on disk")
    else:
        check("level table found in load log", False, "no compaction stats table")

    per_level = []
    for lvl in sorted(lv):
        target = None if lvl == 0 else LEVEL_BASE * MULTIPLIER ** (lvl - 1)
        per_level.append({"level": lvl, **lv[lvl],
                          "target_bytes": target})

    caches_mb = [32, 64, 128, 512, 1024, 2048]
    fits = {str(c): meta <= c * MB for c in caches_mb}

    result = {
        "version": load["version"],
        "num_keys": num_keys,
        "sst_files": len(ssts),
        "sst_bytes_on_disk": sst_bytes,
        "entries": entries,
        "data_blocks": data_blocks,
        "data_block_bytes": data_bytes,
        "avg_data_block_bytes": data_bytes / data_blocks if data_blocks else None,
        "entries_per_data_block": entries / data_blocks if data_blocks else None,
        "index_block_bytes": index_bytes,
        "filter_block_bytes": filter_bytes,
        "index_plus_filter_bytes": meta,
        "avg_index_block_bytes": index_bytes / len(files) if files else None,
        "avg_filter_block_bytes": filter_bytes / len(files) if files else None,
        "index_key_is_user_key": sorted({f.get("index_key_is_user_key") for f in files}),
        "index_plus_filter_fit_in_cache_mb": fits,
        "levels": per_level,
        "load_write_amplification": load["write_amplification"],
        "fill_ops_per_sec": load["fill_ops_per_sec"],
        "fill_seconds": load["fill_seconds"],
        "checks": checks,
    }
    with open(os.path.join(out_dir, "db_summary.json"), "w") as f:
        json.dump(result, f, indent=1)

    print(f"RocksDB {result['version']}: {len(ssts)} SST files, "
          f"{sst_bytes / 1e9:.2f} GB on disk ({sst_bytes / (1024 * MB):.2f} GiB)")
    print(f"entries {entries:,}; data blocks {data_blocks:,} "
          f"(avg {result['avg_data_block_bytes']:.0f} B, {result['entries_per_data_block']:.2f} keys/block)")
    print(f"index blocks  {index_bytes / MB:8.1f} MB   (avg {result['avg_index_block_bytes']:.0f} B per file)")
    print(f"filter blocks {filter_bytes / MB:8.1f} MB   (avg {result['avg_filter_block_bytes']:.0f} B per file)")
    print(f"index+filter  {meta / MB:8.1f} MB   fits in: "
          + ", ".join(f"{c} MB={'yes' if ok else 'no'}" for c, ok in fits.items()))
    print("level  files      size(MB)   target(MB)  score")
    for p in per_level:
        tgt = "-" if p["target_bytes"] is None else f"{p['target_bytes'] / MB:.0f}"
        print(f"  L{p['level']}  {p['files']:6d}  {p['bytes'] / MB:11.1f}  {tgt:>11}  {p['score']:.2f}")
    if load["write_amplification"] is not None:
        print(f"load write amplification: {load['write_amplification']}")
    bad = [c for c in checks if not c["ok"]]
    for c in checks:
        print(("PASS " if c["ok"] else "FAIL ") + c["check"] + " -- " + c["detail"])
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
