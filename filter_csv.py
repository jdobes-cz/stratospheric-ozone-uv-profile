"""Clean the converted CSV: physical-bounds clipping + Hampel spike rejection
per sensor, then trim the stationary ground tails to 2 rows on each side.

Reads  Experiment/20260423_converted.CSV   (14 columns)
Writes Experiment/20260423_cleaned.CSV     (same 14 columns, bad samples -> NaN,
                                           pre/post-flight ground tails trimmed)

Note: temp_c (MS5607) is externally-mounted ambient air but unshielded;
expect a +10 to +35 °C warm bias above the tropopause vs ISA — see
Experiment/data_review.md §2.1.

Filter design:
  Step 1: Physical plausibility bounds (clip to NaN)
  Step 2: Hampel rolling filter (rolling median +/- k * 1.4826 * rolling MAD)
  Step 3: Trim to flight window (isa_alt_km > 1 km) +/- 2 ground points
  Step 4: Recompute derived columns (isa_alt_km, o3_ppmv, uv_erythemal_Wm2, vis_Wm2)
"""
from pathlib import Path

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# ISA 1976 pressure -> altitude (same as convert_csv.py)
# ---------------------------------------------------------------------------
G0 = 9.80665
R_SPEC = 287.05287
P0_HPA = 1013.25
T0 = 288.15

HB_M = np.array([0.0, 11000.0, 20000.0, 32000.0, 47000.0])
LAPSE = np.array([-0.0065, 0.0, 0.0010, 0.0028])

TB = np.zeros_like(HB_M)
PB_HPA = np.zeros_like(HB_M)
TB[0] = T0
PB_HPA[0] = P0_HPA
for i in range(LAPSE.size):
    dz = HB_M[i + 1] - HB_M[i]
    if LAPSE[i] == 0.0:
        TB[i + 1] = TB[i]
        PB_HPA[i + 1] = PB_HPA[i] * np.exp(-G0 * dz / (R_SPEC * TB[i]))
    else:
        TB[i + 1] = TB[i] + LAPSE[i] * dz
        PB_HPA[i + 1] = PB_HPA[i] * (TB[i] / TB[i + 1]) ** (G0 / (R_SPEC * LAPSE[i]))


def isa_altitude_km(p_hpa):
    p = np.asarray(p_hpa, dtype=float)
    z = np.full(p.shape, np.nan)
    valid = p > 0
    for i in range(LAPSE.size):
        m = valid & (p <= PB_HPA[i]) & (p >= PB_HPA[i + 1])
        if not m.any():
            continue
        if LAPSE[i] == 0.0:
            z[m] = HB_M[i] - (R_SPEC * TB[i] / G0) * np.log(p[m] / PB_HPA[i])
        else:
            expn = -R_SPEC * LAPSE[i] / G0
            z[m] = HB_M[i] + (TB[i] / LAPSE[i]) * ((p[m] / PB_HPA[i]) ** expn - 1.0)
    below_surface = valid & (p > PB_HPA[0])
    if below_surface.any():
        expn = -R_SPEC * LAPSE[0] / G0
        z[below_surface] = HB_M[0] + (TB[0] / LAPSE[0]) * ((p[below_surface] / PB_HPA[0]) ** expn - 1.0)
    above_top = valid & (p < PB_HPA[-1])
    if above_top.any():
        i = LAPSE.size - 1
        expn = -R_SPEC * LAPSE[i] / G0
        z[above_top] = HB_M[i] + (TB[i] / LAPSE[i]) * ((p[above_top] / PB_HPA[i]) ** expn - 1.0)
    return z / 1000.0


# ---------------------------------------------------------------------------
# Filter configuration
# ---------------------------------------------------------------------------
PHYSICAL_BOUNDS = {
    # column -> (low, high), both inclusive; None means unbounded on that side
    "pressure_mbar": (0.0, 1100.0),     # strict > 0, <= 1100
    "temp_c":        (-70.0, 50.0),
    "ozone_ppb":     (0.0, 500.0),      # also drops the -1 sensor error code
    "uvi":           (0.0, None),
    "lux":           (0.0, None),
    "als":           (0.0, 262142.0),   # 262143 = 2^18-1 saturation
    "uvs":           (0.0, None),
    "rtc_temp_c":    (-40.0, 85.0),
}

HAMPEL_CFG = {
    # column -> (window, k)
    "pressure_mbar": (7, 3.0),
    "temp_c":        (7, 3.0),
    "rtc_temp_c":    (7, 3.0),
    "uvi":           (7, 3.0),
    "uvs":           (7, 3.0),
    "lux":           (7, 3.0),
    "als":           (7, 3.0),
    "ozone_ppb":     (15, 4.0),
}


def clip_to_nan(s, bounds):
    low, high = bounds
    out = s.copy()
    if low is not None:
        out[out < low] = np.nan
    if high is not None:
        out[out > high] = np.nan
    return out


def hampel_filter(s, window, k):
    """Replace outliers with NaN. Outlier if |x - rolling_median| > k * 1.4826 * rolling_MAD."""
    s = s.astype(float)
    med = s.rolling(window, center=True, min_periods=3).median()
    mad = 1.4826 * (s - med).abs().rolling(window, center=True, min_periods=3).median()
    # Where MAD is 0 (constant stretch), we don't flag anything (everything equals the median).
    threshold = k * mad.where(mad > 0, np.inf)
    outlier = (s - med).abs() > threshold
    return s.mask(outlier, np.nan)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
IN_PATH = ROOT / "Experiment" / "20260423_converted.CSV"
OUT_PATH = ROOT / "Experiment" / "20260423_cleaned.CSV"

df = pd.read_csv(IN_PATH)
# Chronological order — the converted CSV preserves raw order but be safe
df["_ts"] = pd.to_datetime(df["timestamp"], format="%Y/%m/%d %H:%M:%S")
df = df.sort_values("_ts").reset_index(drop=True)

print(f"Loaded {len(df)} rows")

# Step 1: physical bounds
pre_nan = df.isna().sum()
for col, bounds in PHYSICAL_BOUNDS.items():
    df[col] = clip_to_nan(df[col], bounds)
clipped_nan = df.isna().sum() - pre_nan
print("\nStep 1 — physical-bounds clipping (NaN added per column):")
for col in PHYSICAL_BOUNDS:
    print(f"  {col:16s} {clipped_nan[col]:4d}")

# Step 2: Hampel filter
pre_nan = df.isna().sum()
for col, (w, k) in HAMPEL_CFG.items():
    df[col] = hampel_filter(df[col], w, k)
hampel_nan = df.isna().sum() - pre_nan
print("\nStep 2 — Hampel filter (additional NaN added per column):")
for col in HAMPEL_CFG:
    print(f"  {col:16s} {hampel_nan[col]:4d}")

# Step 3: trim to flight window +/- 2 ground points
#    Use a freshly-computed altitude from the cleaned pressure so the flight
#    window isn't corrupted by the (already-stale) isa_alt_km column.
alt_now = isa_altitude_km(df["pressure_mbar"].to_numpy())
in_flight = np.where(np.nan_to_num(alt_now, nan=-1.0) > 1.0)[0]
if in_flight.size == 0:
    raise RuntimeError("No in-flight rows found (alt > 1 km). Check pressure_mbar.")
start = max(0, int(in_flight.min()) - 2)
end = min(len(df) - 1, int(in_flight.max()) + 2)
print(f"\nStep 3 — trim to flight window: rows [{start} .. {end}] "
      f"(flight_start={in_flight.min()}, flight_end={in_flight.max()})")
df = df.iloc[start:end + 1].reset_index(drop=True)

# Step 4: recompute derived columns from cleaned sources
df["isa_alt_km"]       = isa_altitude_km(df["pressure_mbar"].to_numpy())
df["o3_ppmv"]          = df["ozone_ppb"] / 1000.0
df["uv_erythemal_Wm2"] = df["uvi"] * 0.025
df["vis_Wm2"]          = df["lux"] / 120.0

# Drop helper column
df = df.drop(columns="_ts")

df.to_csv(OUT_PATH, index=False, float_format="%g")

print(f"\nWrote {len(df)} rows -> {OUT_PATH}")
print("\nNaN counts per column in cleaned file:")
for col in df.columns:
    n = df[col].isna().sum()
    pct = 100.0 * n / len(df)
    print(f"  {col:20s} {n:4d}  ({pct:5.1f}%)")
