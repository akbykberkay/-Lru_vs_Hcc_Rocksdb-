#!/usr/bin/env python3
"""Figures and tables for experiments E0-E4 from results/csv/summary.csv.

usage: plot_results.py [RESULTS_DIR]

Every point is the mean of the repetitions; whiskers span min..max.
Writes results/figures/*.png (+ .pdf) and results/tables/*.md.
"""
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

# Validated categorical slots 1-3 (dataviz reference palette, light mode,
# checked all-pairs against a white surface) + marker shape as a second channel.
SERIES = {
    "lru_cache": ("LRUCache", "#2a78d6", "o"),
    "auto_hyper_clock_cache": ("HyperClockCache (auto)", "#eb6834", "s"),
    "fixed_hyper_clock_cache": ("HyperClockCache (fixed)", "#1baf7a", "^"),
}
INK, INK2, MUTED, GRID, AXIS = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"

plt.rcParams.update({
    "figure.facecolor": "white", "axes.facecolor": "white", "savefig.facecolor": "white",
    "font.family": "DejaVu Sans", "font.size": 9, "axes.titlesize": 10,
    "axes.labelsize": 9, "axes.labelcolor": INK2, "axes.edgecolor": AXIS,
    "axes.linewidth": 0.8, "axes.grid": True, "axes.axisbelow": True,
    "grid.color": GRID, "grid.linewidth": 0.6, "grid.linestyle": "-",
    "xtick.color": MUTED, "ytick.color": MUTED, "xtick.labelcolor": INK2,
    "ytick.labelcolor": INK2, "legend.frameon": False, "text.color": INK,
    "axes.spines.top": False, "axes.spines.right": False,
})


def pctfmt(v, _pos=None):
    return f"{100 * v:g}%"


def style_axis(ax, metric):
    if metric == "throughput_ops":
        ax.yaxis.set_major_formatter(kfmt)
    elif metric.endswith("_ratio"):
        ax.yaxis.set_major_formatter(pctfmt)


def kfmt(v, _pos=None):
    if v >= 1e6:
        return f"{v / 1e6:g}M"
    if v >= 1e3:
        return f"{v / 1e3:g}K"
    return f"{v:g}"


DODGE = {"lru_cache": -1, "auto_hyper_clock_cache": 0, "fixed_hyper_clock_cache": 1}


def series_line(ax, df, x, y, ct, xvals=None, logx=False, dodge=0.05):
    """One cache type as a line. Series are dodged slightly along x so that
    equal values (e.g. the two HCC variants) do not hide each other:
    multiplicatively on a log axis, by `dodge` x-units otherwise."""
    name, color, marker = SERIES[ct]
    d = df[df.cache_type == ct].sort_values(x)
    if d.empty:
        return
    xs = d[x].tolist() if xvals is None else [xvals.index(v) for v in d[x]]
    if logx:
        xs = [v * 2 ** (0.07 * DODGE[ct]) for v in xs]
    else:
        xs = [v + dodge * DODGE[ct] for v in xs]
    mean, lo, hi = d[f"{y}_mean"], d[f"{y}_min"], d[f"{y}_max"]
    err = [(mean - lo).clip(lower=0), (hi - mean).clip(lower=0)]  # float rounding
    ax.errorbar(xs, mean, yerr=err, color=color, lw=2, marker=marker,
                ms=6, mec="white", mew=1.5, capsize=0, elinewidth=1.2, label=name,
                solid_capstyle="round", solid_joinstyle="round")


def finish(fig, path, legend_ax=None):
    if legend_ax is not None:
        handles, labels = legend_ax.get_legend_handles_labels()
        fig.legend(handles, labels, loc="lower center", ncol=len(labels),
                   bbox_to_anchor=(0.5, -0.02))
        fig.subplots_adjust(bottom=0.2)
    fig.savefig(path + ".png", dpi=200, bbox_inches="tight")
    fig.savefig(path + ".pdf", bbox_inches="tight")
    plt.close(fig)


def skew_label(x):
    return "uniform" if x == 0 else f"skewed (read_random_exp_range={x:g})"


def md_table(df, cols, path, title):
    with open(path, "w") as f:
        f.write(f"### {title}\n\n")
        f.write("| " + " | ".join(h for h, _ in cols) + " |\n")
        f.write("|" + "---|" * len(cols) + "\n")
        for _, r in df.iterrows():
            cells = []
            for _, fn in cols:
                try:
                    cells.append(fn(r))
                except (KeyError, ValueError, TypeError):
                    cells.append("")
            f.write("| " + " | ".join(cells) + " |\n")


def fmt_pm(r, col, scale=1.0, digits=0):
    m, s = r[f"{col}_mean"] * scale, r[f"{col}_std"] * scale
    return f"{m:,.{digits}f} ± {s:,.{digits}f}"


def pct(r, col):
    return f"{100 * r[f'{col}_mean']:.2f}%"


COMMON_COLS = [
    ("cache", lambda r: SERIES[r.cache_type][0]),
    ("throughput (ops/s)", lambda r: fmt_pm(r, "throughput_ops")),
    ("p50 (µs)", lambda r: f"{r.lat_p50_us_mean:.1f}"),
    ("p99 (µs)", lambda r: f"{r.lat_p99_us_mean:.1f}"),
    ("p99.9 (µs)", lambda r: f"{r.lat_p999_us_mean:.1f}"),
    ("data miss", lambda r: pct(r, "data_miss_ratio")),
    ("index miss", lambda r: pct(r, "index_miss_ratio")),
    ("filter miss", lambda r: pct(r, "filter_miss_ratio")),
    ("CPU µs/op", lambda r: f"{r.cpu_us_per_op_mean:.2f}"),
    ("reps", lambda r: f"{int(r.n_reps)}"),
]


def in_exp(df, e):
    return df[df.experiments.fillna("").str.split("+").apply(lambda s: e in s)]


def plot_e0(df, out, tabs):
    d = in_exp(df, "E0")
    if d.empty:
        return
    skews = sorted(d.read_random_exp_range.unique())
    ratios = sorted(d.high_pri_pool_ratio.unique())
    metrics = [("throughput_ops", "Throughput (ops/s)"), ("lat_p99_us", "p99 latency (µs)"),
               ("data_miss_ratio", "Data-block miss ratio"),
               ("index_miss_ratio", "Index-block miss ratio"),
               ("filter_miss_ratio", "Filter-block miss ratio")]
    fig, axes = plt.subplots(len(skews), len(metrics), figsize=(3.0 * len(metrics), 2.6 * len(skews)),
                             squeeze=False)
    for i, x in enumerate(skews):
        for j, (m, lab) in enumerate(metrics):
            ax = axes[i][j]
            for ct in SERIES:
                series_line(ax, d[d.read_random_exp_range == x], "high_pri_pool_ratio", m, ct,
                            xvals=ratios)
            ax.set_xticks(range(len(ratios)), [f"{r:g}" for r in ratios])
            ax.set_xlabel("cache_high_pri_pool_ratio")
            ax.set_title(f"{lab}\n{skew_label(x)}", loc="left", color=INK)
            ax.set_ylim(bottom=0)
            style_axis(ax, m)
    fig.suptitle("E0  64 MB cache, 1 thread: effect of the high-priority pool ratio "
                 "(only LRUCache has pools)", x=0.01, ha="left", color=INK)
    fig.tight_layout()
    finish(fig, os.path.join(out, "E0_ratio"), axes[0][0])
    t = d.sort_values(["read_random_exp_range", "cache_type", "high_pri_pool_ratio"])
    md_table(t, [("skew", lambda r: f"{r.read_random_exp_range:g}"),
                 ("ratio", lambda r: f"{r.high_pri_pool_ratio:g}")] + COMMON_COLS,
             os.path.join(tabs, "E0_ratio.md"), "E0: 64 MB cache, 1 thread, high-priority pool ratio")


def plot_vs(df, exp, xcol, xlabel, title, fname, logx=False, panel_col="read_random_exp_range",
            panel_label=skew_label, metrics=None):
    d = in_exp(df, exp)
    if d.empty:
        return None
    panels = sorted(d[panel_col].unique())
    metrics = metrics or [("throughput_ops", "Throughput (ops/s)"),
                          ("lat_p99_us", "p99 latency (µs)"),
                          ("data_miss_ratio", "Data-block miss ratio")]
    fig, axes = plt.subplots(len(panels), len(metrics),
                             figsize=(3.3 * len(metrics), 2.7 * len(panels)), squeeze=False)
    for i, p in enumerate(panels):
        for j, (m, lab) in enumerate(metrics):
            ax = axes[i][j]
            xs_all = sorted(d[xcol].unique())
            span = (max(xs_all) - min(xs_all)) or 1
            for ct in SERIES:
                series_line(ax, d[d[panel_col] == p], xcol, m, ct, logx=logx, dodge=0.012 * span)
            if logx:
                ax.set_xscale("log", base=2)
            xs = sorted(d[xcol].unique())
            ax.set_xticks(xs, [f"{v:g}" for v in xs])
            ax.minorticks_off()
            ax.set_xlabel(xlabel)
            ax.set_title(f"{lab}\n{panel_label(p)}", loc="left", color=INK)
            ax.set_ylim(bottom=0)
            style_axis(ax, m)
    fig.suptitle(title, x=0.01, ha="left", color=INK)
    fig.tight_layout()
    finish(fig, fname, axes[0][0])
    return d


def plot_e3(df, out, tabs):
    d = in_exp(df, "E3")
    if d.empty:
        return
    order = [("lru_cache", 0), ("lru_cache", 2), ("lru_cache", 4), ("lru_cache", 6),
             ("auto_hyper_clock_cache", 0), ("auto_hyper_clock_cache", 2),
             ("fixed_hyper_clock_cache", 0), ("fixed_hyper_clock_cache", 2)]
    skews = sorted(d.read_random_exp_range.unique())
    fig, axes = plt.subplots(1, len(skews), figsize=(6.4 * len(skews), 3.4), squeeze=False)
    for i, x in enumerate(skews):
        ax = axes[0][i]
        dd = d[d.read_random_exp_range == x]
        labels, k = [], 0
        for ct, bits in order:
            r = dd[(dd.cache_type == ct) & (dd.shard_bits == bits)]
            if r.empty:
                continue
            r = r.iloc[0]
            name, color, _ = SERIES[ct]
            m = r.throughput_ops_mean
            ax.bar(k, m, width=0.6, color=color,
                   label=name if name not in [lb for lb in labels] else None)
            ax.errorbar(k, m, yerr=[[max(0, m - r.throughput_ops_min)],
                                    [max(0, r.throughput_ops_max - m)]],
                        color=INK2, capsize=0, elinewidth=1.2)
            labels.append(name)
            k += 1
        ax.set_xticks(range(k), [f"{'LRU' if ct == 'lru_cache' else ('auto' if 'auto' in ct else 'fixed')}"
                                 f"\n{2 ** b}" for ct, b in order][:k])
        ax.set_xlabel("cache type and number of shards")
        ax.yaxis.set_major_formatter(kfmt)
        ax.set_ylabel("Throughput (ops/s)")
        threads = int(dd.threads.iloc[0]) if not dd.empty else 0
        ax.set_title(f"{skew_label(x)}, {threads} threads", loc="left", color=INK)
        ax.grid(axis="x", visible=False)
    handles = [plt.Rectangle((0, 0), 1, 1, color=SERIES[c][1]) for c in SERIES]
    fig.legend(handles, [SERIES[c][0] for c in SERIES], loc="lower center", ncol=3,
               bbox_to_anchor=(0.5, -0.06))
    fig.suptitle("E3  1 GB cache, max threads: number of shards", x=0.01, ha="left", color=INK)
    fig.tight_layout()
    fig.subplots_adjust(bottom=0.25)
    fig.savefig(os.path.join(out, "E3_shards.png"), dpi=200, bbox_inches="tight")
    fig.savefig(os.path.join(out, "E3_shards.pdf"), bbox_inches="tight")
    plt.close(fig)
    t = d.sort_values(["read_random_exp_range", "cache_type", "shard_bits"])
    md_table(t, [("skew", lambda r: f"{r.read_random_exp_range:g}"),
                 ("shards", lambda r: f"{2 ** int(r.shard_bits)}"),
                 ("threads", lambda r: f"{int(r.threads)}")] + COMMON_COLS,
             os.path.join(tabs, "E3_shards.md"), "E3: 1 GB cache, max threads, shards")


def main():
    results = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "results")
    df = pd.read_csv(os.path.join(results, "csv", "summary.csv"))
    out = os.path.join(results, "figures")
    tabs = os.path.join(results, "tables")
    os.makedirs(out, exist_ok=True)
    os.makedirs(tabs, exist_ok=True)

    plot_e0(df, out, tabs)

    d = plot_vs(df, "E1", "cache_mb", "block cache size (MB)",
                "E1  cache size, 1 thread", os.path.join(out, "E1_cache_size"), logx=True,
                metrics=[("throughput_ops", "Throughput (ops/s)"), ("lat_p99_us", "p99 latency (µs)"),
                         ("data_miss_ratio", "Data-block miss ratio"),
                         ("index_miss_ratio", "Index-block miss ratio"),
                         ("filter_miss_ratio", "Filter-block miss ratio")])
    if d is not None:
        md_table(d.sort_values(["read_random_exp_range", "cache_mb", "cache_type"]),
                 [("skew", lambda r: f"{r.read_random_exp_range:g}"),
                  ("cache MB", lambda r: f"{int(r.cache_mb)}")] + COMMON_COLS,
                 os.path.join(tabs, "E1_cache_size.md"), "E1: cache size, 1 thread")

    d = plot_vs(df, "E2", "threads", "threads", "E2  thread scaling, 2 GB cache",
                os.path.join(out, "E2_threads"), logx=True)
    if d is not None:
        md_table(d.sort_values(["read_random_exp_range", "threads", "cache_type"]),
                 [("skew", lambda r: f"{r.read_random_exp_range:g}"),
                  ("threads", lambda r: f"{int(r.threads)}")] + COMMON_COLS,
                 os.path.join(tabs, "E2_threads.md"), "E2: threads, 2 GB cache")

    plot_e3(df, out, tabs)

    d = plot_vs(df, "E4", "read_random_exp_range", "read_random_exp_range (0 = uniform)",
                "E4  skew, 64 MB cache", os.path.join(out, "E4_skew"), panel_col="threads",
                panel_label=lambda t: f"{int(t)} thread{'s' if t > 1 else ''}",
                metrics=[("throughput_ops", "Throughput (ops/s)"), ("lat_p99_us", "p99 latency (µs)"),
                         ("data_miss_ratio", "Data-block miss ratio"),
                         ("index_miss_ratio", "Index-block miss ratio")])
    if d is not None:
        md_table(d.sort_values(["threads", "read_random_exp_range", "cache_type"]),
                 [("threads", lambda r: f"{int(r.threads)}"),
                  ("skew", lambda r: f"{r.read_random_exp_range:g}")] + COMMON_COLS,
                 os.path.join(tabs, "E4_skew.md"), "E4: skew, 64 MB cache")
    plot_lockstat(results, out, tabs)
    print(f"figures -> {out}\ntables  -> {tabs}")


def plot_lockstat(results, out, tabs):
    """Lock-wait pass (LOCKSTAT=1, separate results dir): share of thread time
    spent waiting for a mutex, for the multi-threaded configurations."""
    path = os.path.join(os.path.dirname(os.path.abspath(results)), "results_lockstat",
                        "csv", "summary.csv")
    if not os.path.exists(path):
        return
    d = pd.read_csv(path)
    if "lock_wait_share_mean" not in d:
        return
    d = d[d.threads > 1]
    if d.empty:
        return
    d = d.sort_values(["cache_mb", "read_random_exp_range", "cache_type", "shard_bits"])
    md_table(d, [("cache MB", lambda r: f"{int(r.cache_mb)}"),
                 ("skew", lambda r: f"{r.read_random_exp_range:g}"),
                 ("threads", lambda r: f"{int(r.threads)}"),
                 ("cache", lambda r: SERIES[r.cache_type][0]),
                 ("shards", lambda r: f"{2 ** int(r.shard_bits)}"),
                 ("mutex acquisitions / lookup", lambda r: f"{r.lock_acquisitions_per_op_mean:.1f}"),
                 ("contended", lambda r: "–" if r.lock_acquisitions_per_op_mean < 0.01
                  else f"{100 * r.lock_contended_frac_mean:.2f}%"),
                 ("wait µs / lookup", lambda r: f"{r.lock_wait_us_per_op_mean:.3f}"),
                 ("share of thread time waiting", lambda r: f"{100 * r.lock_wait_share_mean:.2f}%"),
                 ("throughput (ops/s)", lambda r: f"{r.throughput_ops_mean:,.0f}")],
             os.path.join(tabs, "lock_wait.md"), "Mutex wait time (LOCKSTAT pass)")


if __name__ == "__main__":
    main()
