"""Sanity check: count Roels samples inside each major Experiment outage."""
from pathlib import Path
import pandas as pd

HERE = Path(__file__).resolve().parent

# Reuse the parsers from analyze_gaps.
import sys
sys.path.insert(0, str(HERE))
from analyze_gaps import load_roels, load_experiment, find_gaps, BIG_GAP_S

roels = load_roels()
exp = load_experiment()
exp_gaps = find_gaps(exp, BIG_GAP_S).sort_values("duration_s", ascending=False)

print(f"{'Experiment outage':<40}  {'dur_s':>7}  {'Roels samples':>14}  {'Roels rate':>11}")
for _, g in exp_gaps.head(10).iterrows():
    inside = roels[(roels["wall"] >= g["start"]) & (roels["wall"] <= g["end"])]
    rate = len(inside) / g["duration_s"] if g["duration_s"] else float("nan")
    label = f"{g['start'].strftime('%H:%M:%S')} → {g['end'].strftime('%H:%M:%S')}"
    print(f"{label:<40}  {g['duration_s']:>7.0f}  {len(inside):>14,}  {rate:>8.1f} Hz")
