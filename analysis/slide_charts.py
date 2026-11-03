#!/usr/bin/env python3
"""Slide-sized charts (1664 px wide panels rendered at 2x) for the results deck.

usage: slide_charts.py RESULTS_DIR OUT_DIR [FONT_DIR]

Charts carry no legend: the slide shows one (same colors and markers).
Every value is the mean of the repetitions; whiskers span min..max.
"""
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib import font_manager  # noqa: E402

RESULTS, OUT = sys.argv[1], sys.argv[2]
FONT_DIR = sys.argv[3] if len(sys.argv) > 3 else None
os.makedirs(OUT, exist_ok=True)

family = "DejaVu Sans"
if FONT_DIR and os.path.isdir(FONT_DIR):
    for f in os.listdir(FONT_DIR):
        if f.endswith(".ttf"):
            font_manager.fontManager.addfont(os.path.join(FONT_DIR, f))
    family = "IBM Plex Sans"

INK, INK2, MUTED, GRID, AXIS = "#13212B", "#3D4A54", "#56626A", "#E1E0D9", "#C3C2B7"
C = {"lru_cache": "#2a78d6", "auto_hyper_clock_cache": "#eb6834", "fixed_hyper_clock_cache": "#1baf7a"}
M = {"lru_cache": "o", "auto_hyper_clock_cache": "s", "fixed_hyper_clock_cache": "D"}
ORDER = ["lru_cache", "auto_hyper_clock_cache", "fixed_hyper_clock_cache"]

plt.rcParams.update({
    "font.family": family, "font.size": 18, "axes.titlesize": 20, "axes.titleweight": "semibold",
    "axes.titlecolor": INK, "axes.titlelocation": "left", "axes.titlepad": 14,
    "axes.labelsize": 18, "axes.labelcolor": INK2, "axes.edgecolor": AXIS, "axes.linewidth": 1.0,
    "axes.grid": True, "axes.axisbelow": True, "grid.color": GRID, "grid.linewidth": 1.0,
    "xtick.color": AXIS, "ytick.color": AXIS, "xtick.labelcolor": INK2, "ytick.labelcolor": INK2,
    "xtick.labelsize": 18, "ytick.labelsize": 18, "axes.spines.top": False, "axes.spines.right": False,
    "figure.facecolor": "white", "axes.facecolor": "white", "savefig.facecolor": "white",
})

S = pd.read_csv(os.path.join(RESULTS, "csv", "summary.csv"))


def in_exp(e):
    return S[S.experiments.fillna("").str.split("+").apply(lambda s: e in s)]


def kfmt(v, _pos=None):
    return f"{v / 1000:g}K" if v >= 1000 else f"{v:g}"


def pct(v, _pos=None):
    return f"{100 * v:g}%"


def save(fig, name):
    fig.savefig(os.path.join(OUT, name), dpi=200, facecolor="white")
    plt.close(fig)
    print("wrote", name)


def figure(ncols, height=4.7):
    fig, axes = plt.subplots(1, ncols, figsize=(16.64, height), squeeze=False)
    fig.subplots_adjust(left=0.06, right=0.99, top=0.86, bottom=0.17, wspace=0.22)
    return fig, axes[0]


def grouped_bars(ax, d, xcol, xvals, metric, width=0.24):
    for i, ct in enumerate(ORDER):
        for j, xv in enumerate(xvals):
            r = d[(d.cache_type == ct) & (d[xcol] == xv)]
            if r.empty:
                continue
            r = r.iloc[0]
            m = r[f"{metric}_mean"]
            x = j + (i - 1) * width
            ax.bar(x, m, width=width * 0.86, color=C[ct], zorder=2)
            ax.errorbar(x, m, yerr=[[max(0, m - r[f"{metric}_min"])], [max(0, r[f"{metric}_max"] - m)]],
                        color=INK2, elinewidth=1.6, capsize=0, zorder=3)
    ax.set_xticks(range(len(xvals)))
    ax.grid(axis="x", visible=False)


def lines(ax, d, xcol, metric, logx=False):
    for i, ct in enumerate(ORDER):
        r = d[d.cache_type == ct].sort_values(xcol)
        if r.empty:
            continue
        xs = r[xcol].astype(float).tolist()
        dodge = 2 ** (0.05 * (i - 1)) if logx else None
        xs = [x * dodge for x in xs] if logx else [x + 0.15 * (i - 1) for x in xs]
        m = r[f"{metric}_mean"]
        err = [(m - r[f"{metric}_min"]).clip(lower=0), (r[f"{metric}_max"] - m).clip(lower=0)]
        ax.errorbar(xs, m, yerr=err, color=C[ct], marker=M[ct], ms=11, mec="white", mew=2.2,
                    lw=3.2, elinewidth=1.8, capsize=0, zorder=3)
    if logx:
        ax.set_xscale("log", base=2)
        ax.minorticks_off()


# ---------------------------------------------------------------- E0
d = in_exp("E0")
fig, ax = figure(3)
for k, (x, title) in enumerate([(0, "Throughput, uniform (ops/s)"), (10, "Throughput, skewed (ops/s)")]):
    grouped_bars(ax[k], d[d.read_random_exp_range == x], "high_pri_pool_ratio", [0.0, 0.5, 1.0], "throughput_ops")
    ax[k].set_title(title)
    ax[k].yaxis.set_major_formatter(kfmt)
grouped_bars(ax[2], d[d.read_random_exp_range == 0], "high_pri_pool_ratio", [0.0, 0.5, 1.0], "index_miss_ratio")
ax[2].set_title("Index-block miss ratio, uniform")
ax[2].yaxis.set_major_formatter(pct)
lru = d[(d.read_random_exp_range == 0) & (d.cache_type == "lru_cache")].sort_values("high_pri_pool_ratio")
hcc_max = (d[(d.read_random_exp_range == 0) & (d.cache_type != "lru_cache")]
           .groupby("high_pri_pool_ratio").index_miss_ratio_mean.max())
for j, (ratio, v) in enumerate(zip(lru.high_pri_pool_ratio, lru.index_miss_ratio_mean)):
    label = f"{100 * v:.1f}%" if v >= 0.001 else "0.01%"  # label the LRU bars (the last one is ~0)
    if v > hcc_max[ratio]:  # above its neighbours: centred, on a white box so no gridline crosses it
        ax[2].text(j - 0.24, v + 0.003, label, ha="center", va="bottom", fontsize=17, color=INK, zorder=4,
                   bbox=dict(boxstyle="square,pad=0.15", facecolor="white", edgecolor="none"))
    else:  # next to taller bars: end at the bar's right edge so the text stays clear of them
        ax[2].text(j - 0.24 + 0.103, v + 0.003, label, ha="right", va="bottom", fontsize=17, color=INK,
                   zorder=4)
ax[2].set_ylim(0, 0.22)
for a in ax:
    a.set_xlim(-0.62, 2.48)  # room between the y axis and the first bar's label
    a.set_xticklabels(["0", "0.5", "1"])
    a.set_xlabel("cache_high_pri_pool_ratio")
save(fig, "e0.png")

# ---------------------------------------------------------------- E1
d = in_exp("E1")
fig, ax = figure(2)
for k, (x, title) in enumerate([(0, "Throughput, uniform (ops/s)"), (10, "Throughput, skewed (ops/s)")]):
    lines(ax[k], d[d.read_random_exp_range == x], "cache_mb", "throughput_ops", logx=True)
    ax[k].set_title(title)
    ax[k].set_xticks([32, 128, 512, 2048], ["32 MB", "128 MB", "512 MB", "2 GB"])
    ax[k].yaxis.set_major_formatter(kfmt)
    ax[k].set_ylim(0, None)
    ax[k].set_xlabel("block cache size")
save(fig, "e1.png")

# ---------------------------------------------------------------- E2
d = in_exp("E2")
threads = sorted(d.threads.unique())
fig, ax = figure(2)
for k, (x, title) in enumerate([(0, "Throughput, uniform (ops/s)"), (10, "Throughput, skewed (ops/s)")]):
    grouped_bars(ax[k], d[d.read_random_exp_range == x], "threads", threads, "throughput_ops")
    ax[k].set_title(title)
    ax[k].set_xticklabels([f"{t} thread{'s' if t > 1 else ''}" for t in threads])
    ax[k].yaxis.set_major_formatter(kfmt)
save(fig, "e2.png")

# ---------------------------------------------------------------- E3
d = in_exp("E3")
order = [("lru_cache", 0), ("lru_cache", 2), ("lru_cache", 4), ("lru_cache", 6),
         ("auto_hyper_clock_cache", 0), ("auto_hyper_clock_cache", 2),
         ("fixed_hyper_clock_cache", 0), ("fixed_hyper_clock_cache", 2)]
pos = [0, 1, 2, 3, 4.6, 5.6, 7.2, 8.2]
fig, ax = figure(2)  # same 4.7 in height as the other charts, so it fills the same slide box
fig.subplots_adjust(bottom=0.21)
for k, (x, title) in enumerate([(0, "Throughput, uniform (ops/s)"), (10, "Throughput, skewed (ops/s)")]):
    dd = d[d.read_random_exp_range == x]
    for p, (ct, bits) in zip(pos, order):
        r = dd[(dd.cache_type == ct) & (dd.shard_bits == bits)].iloc[0]
        m = r.throughput_ops_mean
        ax[k].bar(p, m, width=0.78, color=C[ct], zorder=2)
        ax[k].errorbar(p, m, yerr=[[max(0, m - r.throughput_ops_min)], [max(0, r.throughput_ops_max - m)]],
                       color=INK2, elinewidth=1.6, capsize=0, zorder=3)
    ax[k].set_xticks(pos, ["1", "4", "16", "64", "1", "4", "1", "4"])
    for gx, label in [(1.5, "LRU"), (5.1, "HCC auto"), (7.7, "HCC fixed")]:
        ax[k].text(gx, -0.2, label, transform=ax[k].get_xaxis_transform(), ha="center", va="top",
                   fontsize=18, color=INK2)
    ax[k].set_title(title)
    ax[k].yaxis.set_major_formatter(kfmt)
    ax[k].grid(axis="x", visible=False)
    ax[k].set_xlabel("")
save(fig, "e3.png")

# ---------------------------------------------------------------- E4
d = in_exp("E4")
fig, ax = figure(2)
for k, t in enumerate(sorted(d.threads.unique())):
    lines(ax[k], d[d.threads == t], "read_random_exp_range", "throughput_ops")
    ax[k].set_title(f"Throughput, {t} thread{'s' if t > 1 else ''} (ops/s)")
    ax[k].set_xticks([0, 5, 10, 20], ["0 (uniform)", "5", "10", "20"])
    ax[k].yaxis.set_major_formatter(kfmt)
    ax[k].set_ylim(0, None)
    ax[k].set_xlabel("read_random_exp_range")
save(fig, "e4.png")

# ---------------------------------------------------------------- lock wait (LOCKSTAT pass)
L = pd.read_csv(os.path.join(os.path.dirname(os.path.abspath(RESULTS)), "results_lockstat", "csv", "summary.csv"))
L = L[(L.cache_mb == 1024) & (L.cache_type == "lru_cache")]
fig, ax = figure(2)
for k, (x, title) in enumerate([(0, "Share of LRU reader time spent waiting, uniform"),
                                (10, "Share of LRU reader time spent waiting, skewed")]):
    dd = L[L.read_random_exp_range == x].sort_values("shard_bits")
    vals = dd.lock_wait_share_mean.tolist()
    ax[k].bar(range(len(vals)), vals, width=0.6, color=C["lru_cache"], zorder=2)
    for i, v in enumerate(vals):
        ax[k].text(i, v, f"{100 * v:.1f}%", ha="center", va="bottom", fontsize=18, color=INK)
    ax[k].set_xticks(range(len(vals)), [f"{2 ** int(b)} shard{'s' if b else ''}" for b in dd.shard_bits])
    ax[k].set_title(title)
    ax[k].yaxis.set_major_formatter(pct)
    ax[k].set_ylim(0, max(vals) * 1.25)
    ax[k].grid(axis="x", visible=False)
save(fig, "lock.png")
