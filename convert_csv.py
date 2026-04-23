"""Convert Arduino flight-log variables into the same units used on profile.png.

Reads the raw Arduino CSV (no header, columns per Arduino/Arduino.ino:197),
computes four derived columns matching the four panels of profile.png, and
writes a new CSV with the original 10 columns + 4 derived columns + a header.

Note: temp_c is from the externally-mounted MS5607 (ambient air, bottom of
gondola). It carries a +10 to +35 °C warm bias above the tropopause due to
unshielded radiation/conduction coupling to the gondola — see
Experiment/data_review.md §2.1. The optical sensors (LTR-390UV-01) are also
mounted bottom-of-gondola facing downward, so all measured light is
upwelling — see data_review.md §2.3-2.4.

Derived columns:
  isa_alt_km         ISA 1976 altitude from pressure_mbar  (top x-axis on profile.png)
  o3_ppmv            ozone_ppb / 1000                      (CAMS panel, ppmv)
  uv_erythemal_Wm2   uvi * 0.025  (WHO: 1 UVI = 25 mW/m^2 erythemally-weighted UV)
  vis_Wm2            lux / 120    (D65/solar photopic->radiometric, ~120 lm/W)

temp_c and pressure_mbar are already in profile.png's units, so they are not
duplicated. Derived values are NaN where the per-sensor validity bit in
sensor_flags is not set (flag bits from Arduino/Arduino.ino:45-48).
"""
from pathlib import Path

import numpy as np
import pandas as pd


# ISA 1976 piecewise atmosphere (copied from paper.py:30-102)
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
        p_top = PB_HPA[i + 1]
        p_base = PB_HPA[i]
        m = valid & (p <= p_base) & (p >= p_top)
        if not m.any():
            continue
        if LAPSE[i] == 0.0:
            z[m] = HB_M[i] - (R_SPEC * TB[i] / G0) * np.log(p[m] / p_base)
        else:
            expn = -R_SPEC * LAPSE[i] / G0
            z[m] = HB_M[i] + (TB[i] / LAPSE[i]) * ((p[m] / p_base) ** expn - 1.0)
    # Pressures above the surface base (p > P0) -> below-surface extrapolation
    # using the bottom-layer lapse rate, so readings like 1028 hPa don't lose data.
    below_surface = valid & (p > PB_HPA[0])
    if below_surface.any():
        expn = -R_SPEC * LAPSE[0] / G0
        z[below_surface] = HB_M[0] + (TB[0] / LAPSE[0]) * ((p[below_surface] / PB_HPA[0]) ** expn - 1.0)
    # Pressures below the top boundary (above 47 km): same top-layer extrapolation as paper.py
    above_top = valid & (p < PB_HPA[-1])
    if above_top.any():
        i = LAPSE.size - 1
        expn = -R_SPEC * LAPSE[i] / G0
        z[above_top] = HB_M[i] + (TB[i] / LAPSE[i]) * ((p[above_top] / PB_HPA[i]) ** expn - 1.0)
    return z / 1000.0


# Flag bits (Arduino/Arduino.ino:45-48)
FLAG_UVS_OK    = 0x01
FLAG_ALS_OK    = 0x02
FLAG_MS5607_OK = 0x04
FLAG_O3_OK     = 0x08

UVI_TO_WM2_ERYTHEMAL = 0.025  # WHO: 1 UVI = 25 mW/m^2 erythemal
LUX_PER_WM2_SOLAR = 120.0     # ~120 lm/W for 400-700 nm under solar/D65 spectrum


ROOT = Path(__file__).resolve().parent
IN_PATH = ROOT / "Experiment" / "20260423.CSV"
OUT_PATH = ROOT / "Experiment" / "20260423_converted.CSV"

ORIG_COLS = [
    "timestamp", "als", "lux", "uvs", "uvi",
    "temp_c", "pressure_mbar", "ozone_ppb",
    "rtc_temp_c", "sensor_flags",
]

def _clean_bytes(path):
    """The raw SD log has one corrupted row: an abrupt truncation mid-write
    followed by a run of 0xFF filler bytes, then a resumed record. Strip
    0xFF runs (and any other non-printable bytes) so pandas can parse."""
    raw = Path(path).read_bytes()
    keep = bytearray()
    for b in raw:
        if b == 0x0A or b == 0x0D or 0x20 <= b <= 0x7E:
            keep.append(b)
    return bytes(keep)


from io import BytesIO

df = pd.read_csv(
    BytesIO(_clean_bytes(IN_PATH)),
    header=None,
    names=ORIG_COLS,
    na_values=["nan"],
    dtype={"timestamp": str},
    on_bad_lines="skip",
    engine="python",
)

# sensor_flags column can contain float-looking values on two malformed rows;
# coerce to nullable Int for safe bit-and.
flags = pd.to_numeric(df["sensor_flags"], errors="coerce").astype("Int64")


def mask_bit(bit):
    # True only where flags is non-null and has the bit set
    return (flags.notna()) & ((flags.fillna(0).astype("int64") & bit) != 0)


df["isa_alt_km"] = np.where(
    mask_bit(FLAG_MS5607_OK),
    isa_altitude_km(df["pressure_mbar"].to_numpy()),
    np.nan,
)

df["o3_ppmv"] = np.where(
    mask_bit(FLAG_O3_OK) & (df["ozone_ppb"] >= 0),
    df["ozone_ppb"] / 1000.0,
    np.nan,
)

df["uv_erythemal_Wm2"] = np.where(
    mask_bit(FLAG_UVS_OK),
    df["uvi"] * UVI_TO_WM2_ERYTHEMAL,
    np.nan,
)

df["vis_Wm2"] = np.where(
    mask_bit(FLAG_ALS_OK),
    df["lux"] / LUX_PER_WM2_SOLAR,
    np.nan,
)

df.to_csv(OUT_PATH, index=False, float_format="%g")

print(f"Wrote {len(df)} rows -> {OUT_PATH}")
print(df[["timestamp", "pressure_mbar", "isa_alt_km",
          "temp_c", "o3_ppmv", "uv_erythemal_Wm2", "vis_Wm2"]].head())
