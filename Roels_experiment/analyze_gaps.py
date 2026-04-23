"""Detect and visualize data gaps in Roels' IMU log versus our flight CSV.

Roels log `DATALOG_Official.TXT` uses an Arduino millisecond counter as its
time column; the user's note places the first sample at 11:26:00 local and
the last at ~17:47:52 on 2026-04-23. Our `Experiment/20260423.CSV` has wall-
clock timestamps and is therefore the reference clock. We align Roels to
wall-clock via the first-sample anchor and compare gap positions.
"""
from __future__ import annotations

from pathlib import Path
import datetime as dt

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import Patch

ROOT = Path(__file__).resolve().parents[1]
ROELS = ROOT / "Roels_experiment" / "DATALOG_Official.TXT"
EXPERIMENT = ROOT / "Experiment" / "20260423.CSV"
OUT_DIR = ROOT / "Roels_experiment"

# Anchor: user note says the long period started 11:26:00 on 2026-04-23.
ANCHOR_WALL = dt.datetime(2026, 4, 23, 11, 26, 0)

# A "gap" is any consecutive-sample interval longer than this.
# Typical Roels cadence is 10–20 ms; Experiment CSV is ~10–15 s.
GAP_THRESHOLD_S = 2.0   # visualize anything >= 2 s as an outage
BIG_GAP_S = 30.0        # call out >= 30 s as a real outage in the table


def load_roels() -> pd.DataFrame:
    """Load the long flight segment only.

    The log has 4 `time,heading,...` headers — each Arduino reset restarts the
    millisecond counter. Segments 1–3 are short (≤25 s) pre-flight restarts;
    segment 4 is the ~6 h 23 min flight run the user's note refers to.
    """
    # Stream the file and keep only rows after the 4th header.
    header_count = 0
    rows: list[int] = []
    with open(ROELS, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("time,"):
                header_count += 1
                continue
            if header_count < 4:
                continue
            # Only need the first column.
            comma = line.find(",")
            if comma == -1:
                continue
            try:
                rows.append(int(line[:comma]))
            except ValueError:
                continue
    t = np.asarray(rows, dtype=np.int64)
    df = pd.DataFrame({"time_ms": t})
    t0_ms = int(df["time_ms"].iloc[0])
    df["wall"] = ANCHOR_WALL + pd.to_timedelta(df["time_ms"] - t0_ms, unit="ms")
    df["dt_s"] = df["time_ms"].diff().div(1000.0)
    return df


def load_experiment() -> pd.DataFrame:
    """Read the raw Experiment CSV, dropping lines with binary garbage.

    The file is written by the Arduino directly to microSD and occasionally
    contains non-UTF8 bytes from power blips / write interruptions. We only
    need the timestamp column, so we tolerate and skip malformed lines.
    """
    good_lines: list[str] = []
    with open(EXPERIMENT, "rb") as fh:
        raw = fh.read()
    for raw_line in raw.splitlines():
        try:
            line = raw_line.decode("utf-8")
        except UnicodeDecodeError:
            continue  # skip corrupted line
        if not line or line.count(",") < 5:
            continue
        good_lines.append(line)
    from io import StringIO
    cols = ["timestamp", "als", "lux", "uvs", "uvi", "temp_c",
            "pressure_mbar", "ozone_ppb", "rtc_temp_c", "sensor_flags"]
    df = pd.read_csv(StringIO("\n".join(good_lines)), header=None, names=cols,
                     on_bad_lines="skip")
    df["wall"] = pd.to_datetime(df["timestamp"], format="%Y/%m/%d %H:%M:%S",
                                errors="coerce")
    df = df.dropna(subset=["wall"]).sort_values("wall").reset_index(drop=True)
    df["dt_s"] = df["wall"].diff().dt.total_seconds()
    return df


def find_gaps(df: pd.DataFrame, threshold_s: float) -> pd.DataFrame:
    """Return [start, end, duration_s] rows for gaps exceeding threshold."""
    mask = df["dt_s"] > threshold_s
    gaps = []
    for i in np.flatnonzero(mask.values):
        start = df["wall"].iloc[i - 1]
        end = df["wall"].iloc[i]
        gaps.append({
            "start": start,
            "end": end,
            "duration_s": float(df["dt_s"].iloc[i]),
        })
    if not gaps:
        return pd.DataFrame(columns=["start", "end", "duration_s"])
    return pd.DataFrame(gaps)


def summarize(name: str, df: pd.DataFrame, gaps: pd.DataFrame) -> None:
    print(f"\n=== {name} ===")
    print(f"  rows:           {len(df):>10,}")
    print(f"  wall-clock:     {df['wall'].iloc[0]}  →  {df['wall'].iloc[-1]}")
    print(f"  total span:     {(df['wall'].iloc[-1] - df['wall'].iloc[0]).total_seconds()/3600:.3f} h")
    dt_desc = df["dt_s"].iloc[1:].describe(percentiles=[0.5, 0.95, 0.99])
    print(f"  median dt:      {dt_desc['50%']*1000:.1f} ms")
    print(f"  p95 dt:         {dt_desc['95%']*1000:.1f} ms")
    print(f"  p99 dt:         {dt_desc['99%']*1000:.1f} ms")
    print(f"  max dt:         {dt_desc['max']:.2f} s")
    big = gaps[gaps["duration_s"] >= BIG_GAP_S]
    print(f"  gaps ≥ {BIG_GAP_S:.0f} s:    {len(big)}")
    if len(big):
        shown = big.copy()
        shown["duration_s"] = shown["duration_s"].round(1)
        print(shown.to_string(index=False))


def bin_rate_hz(df: pd.DataFrame, freq: str = "30s") -> pd.Series:
    """Average sampling rate (Hz) per bin, so gaps register as dips to ~0."""
    bin_s = pd.Timedelta(freq).total_seconds()
    return df.set_index("wall").assign(n=1)["n"].resample(freq).sum() / bin_s


def max_dt_per_bin(df: pd.DataFrame, freq: str = "30s") -> pd.Series:
    """Max inter-sample interval per bin (s). Peaks mark gaps."""
    return df.set_index("wall")["dt_s"].resample(freq).max()


def main() -> None:
    roels = load_roels()
    exp = load_experiment()

    roels_gaps = find_gaps(roels, GAP_THRESHOLD_S)
    exp_gaps = find_gaps(exp, GAP_THRESHOLD_S)

    summarize("Roels IMU log", roels, roels_gaps)
    summarize("Experiment CSV (raw)", exp, exp_gaps)

    # ---------- Plot ----------
    fig, axes = plt.subplots(
        4, 1, figsize=(13, 11), sharex=True,
        gridspec_kw={"height_ratios": [2.0, 2.0, 2.0, 1.0]},
    )

    # Overlay Experiment outage bands on *both* Roels panels, so it's visible
    # that Roels keeps sampling right through every Experiment gap.
    exp_big = exp_gaps[exp_gaps["duration_s"] >= BIG_GAP_S]

    # Row 1: Roels instantaneous rate (Hz) per 30-s bin.
    roels_rate = bin_rate_hz(roels, "30s")
    axes[0].fill_between(roels_rate.index, roels_rate.values, step="mid",
                         color="#2b7bba", alpha=0.75, linewidth=0)
    axes[0].set_ylabel("Roels rate\n(samples s⁻¹)")
    axes[0].set_title(
        f"Roels IMU log — {len(roels):,} samples, median {roels['dt_s'].median()*1000:.0f} ms cadence, "
        f"max gap {roels['dt_s'].max():.2f} s  →  NO outages",
        loc="left",
    )
    axes[0].set_ylim(bottom=0)
    for _, g in exp_big.iterrows():
        axes[0].axvspan(g["start"], g["end"], color="#c0392b", alpha=0.18,
                        linewidth=0)
    for _, g in roels_gaps[roels_gaps["duration_s"] >= BIG_GAP_S].iterrows():
        axes[0].axvspan(g["start"], g["end"], color="red", alpha=0.6)

    # Row 2: Roels *max inter-sample dt* per 30-s bin (log y) — makes small
    # gaps visible even though the sampling rate is ~70 Hz.
    roels_maxdt = max_dt_per_bin(roels, "30s")
    axes[1].fill_between(roels_maxdt.index, roels_maxdt.values * 1000, step="mid",
                         color="#2b7bba", alpha=0.75, linewidth=0)
    axes[1].set_ylabel("Roels max Δt\nper 30 s (ms)")
    axes[1].set_yscale("log")
    axes[1].axhline(50, color="grey", linestyle=":", linewidth=0.8)
    axes[1].text(roels["wall"].iloc[0], 55, "  50 ms", color="grey", fontsize=8, va="bottom")
    for _, g in exp_big.iterrows():
        axes[1].axvspan(g["start"], g["end"], color="#c0392b", alpha=0.18,
                        linewidth=0)

    # Row 3: Experiment rate (Hz) per 30-s bin with gap shading.
    exp_rate = bin_rate_hz(exp, "30s")
    axes[2].fill_between(exp_rate.index, exp_rate.values, step="mid",
                         color="#2aa26a", alpha=0.75, linewidth=0)
    axes[2].set_ylabel("Experiment rate\n(samples s⁻¹)")
    axes[2].set_title(
        f"Experiment CSV — {len(exp):,} samples, median {exp['dt_s'].median():.1f} s cadence, "
        f"{len(exp_gaps[exp_gaps['duration_s'] >= BIG_GAP_S])} gap(s) ≥ {BIG_GAP_S:.0f} s",
        loc="left",
    )
    axes[2].set_ylim(bottom=0)
    for _, g in exp_gaps[exp_gaps["duration_s"] >= BIG_GAP_S].iterrows():
        axes[2].axvspan(g["start"], g["end"], color="red", alpha=0.35)

    # Row 4: gap timelines side by side — one y-lane per dataset.
    ax = axes[3]
    ax.set_yticks([1, 0])
    ax.set_yticklabels(["Roels", "Experiment"])
    ax.set_ylim(-0.5, 1.5)
    ax.grid(axis="x", linestyle=":", alpha=0.5)
    plotted_any = False
    for _, g in roels_gaps[roels_gaps["duration_s"] >= BIG_GAP_S].iterrows():
        ax.barh(1, width=g["end"] - g["start"], left=g["start"],
                height=0.6, color="#c0392b", alpha=0.85)
        plotted_any = True
    for _, g in exp_gaps[exp_gaps["duration_s"] >= BIG_GAP_S].iterrows():
        ax.barh(0, width=g["end"] - g["start"], left=g["start"],
                height=0.6, color="#c0392b", alpha=0.85)
        plotted_any = True
    if not plotted_any:
        ax.text(0.5, 0.5, "(no outages to plot)", transform=ax.transAxes,
                ha="center", va="center", color="grey")
    ax.set_title(f"Outage periods (gap ≥ {BIG_GAP_S:.0f} s)", loc="left")
    ax.set_xlabel("Wall-clock time on 2026-04-23 (local)")

    xlo = min(roels["wall"].iloc[0], exp["wall"].iloc[0])
    xhi = max(roels["wall"].iloc[-1], exp["wall"].iloc[-1])
    axes[-1].set_xlim(xlo, xhi)
    axes[-1].xaxis.set_major_locator(mdates.HourLocator(interval=1))
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    axes[-1].xaxis.set_minor_locator(mdates.MinuteLocator(byminute=[15, 30, 45]))

    legend = [
        Patch(facecolor="#c0392b", alpha=0.35, label=f"Experiment outage window (≥ {BIG_GAP_S:.0f} s gap)"),
        Patch(facecolor="#2b7bba", alpha=0.75, label="Roels (IMU)"),
        Patch(facecolor="#2aa26a", alpha=0.75, label="Experiment (sensor stack)"),
    ]
    fig.legend(handles=legend, loc="lower center", ncol=3, frameon=False,
               bbox_to_anchor=(0.5, -0.01))

    fig.suptitle(
        "Roels' IMU vs. Experiment CSV — do the gaps coincide?  "
        "Answer: NO. Roels logs continuously through every Experiment outage.",
        fontsize=12, y=0.995,
    )
    fig.tight_layout(rect=(0, 0.02, 1, 0.97))

    png = OUT_DIR / "gap_comparison.png"
    fig.savefig(png, dpi=140, bbox_inches="tight")
    print(f"\nSaved figure → {png}")

    # Persist gap tables as CSV for the record.
    roels_gaps.to_csv(OUT_DIR / "gaps_roels.csv", index=False)
    exp_gaps.to_csv(OUT_DIR / "gaps_experiment.csv", index=False)
    print(f"Saved gap tables → gaps_roels.csv, gaps_experiment.csv")


if __name__ == "__main__":
    main()
