"""Convolve libRadtran spectral output (eup, eglo) with the LTR-390UV-01
spectral response curves (UV and ALS channels) to produce a sensor-band-
integrated prediction in W/m^2 — the only honest comparison axis for
LTR390 measurements vs libRadtran prediction.

Inputs:
  loop/eup_{z}km.dat                                       (z = 0..40)
  ltr-390uv-01-response/spectral_response_digitized.xlsx   (UV + ALS curves)

Output:
  Experiment/sensor_predicted.csv with columns:
    z_km, p_hPa,
    uv_resp_eup_Wm2, uv_resp_eglo_Wm2,
    als_resp_eup_Wm2, als_resp_eglo_Wm2

See Experiment/data_review.md §2.3, §2.4, §4 for rationale.
"""
import numpy as np
import pandas as pd
from pathlib import Path


# ---------------------------------------------------------------------------
# ISA 1976 pressure(z) — copied from plot_profile.py for self-containment
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


def isa_pressure_hPa(z_m):
    z = np.asarray(z_m, dtype=float)
    P = np.full(z.shape, np.nan)
    for i in range(LAPSE.size):
        m = (z >= HB_M[i]) & (z <= HB_M[i + 1])
        if LAPSE[i] == 0.0:
            P[m] = PB_HPA[i] * np.exp(-G0 * (z[m] - HB_M[i]) / (R_SPEC * TB[i]))
        else:
            T_here = TB[i] + LAPSE[i] * (z[m] - HB_M[i])
            P[m] = PB_HPA[i] * (TB[i] / T_here) ** (G0 / (R_SPEC * LAPSE[i]))
    above = z > HB_M[-1]
    if np.any(above):
        i = LAPSE.size - 1
        T_here = TB[i] + LAPSE[i] * (z[above] - HB_M[i])
        P[above] = PB_HPA[i] * (TB[i] / T_here) ** (G0 / (R_SPEC * LAPSE[i]))
    return P


# ---------------------------------------------------------------------------
# LTR-390UV-01 spectral response (digitised from the manufacturer plot)
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
RESP_PATH = ROOT / "ltr-390uv-01-response" / "spectral_response_digitized.xlsx"

resp = pd.read_excel(RESP_PATH)

# Build dense per-nm response arrays. The XLSX has non-overlapping wavelength
# ranges for the two channels; np.interp with NaN-fill outside the support
# would mis-weight, so use 0 outside support.
uv_src = resp.dropna(subset=["UV Response"]).sort_values("Wavelength")
als_src = resp.dropna(subset=["ALS response"]).sort_values("Wavelength")

# Normalise to peak = 1 (the digitised file has peak ~1.09 due to fit slop)
uv_src = uv_src.assign(R=uv_src["UV Response"] / uv_src["UV Response"].max())
als_src = als_src.assign(R=als_src["ALS response"] / als_src["ALS response"].max())

UV_LAM_MIN, UV_LAM_MAX = float(uv_src["Wavelength"].min()), float(uv_src["Wavelength"].max())
ALS_LAM_MIN, ALS_LAM_MAX = float(als_src["Wavelength"].min()), float(als_src["Wavelength"].max())

print(f"LTR390 UV  response support: {UV_LAM_MIN:.0f} – {UV_LAM_MAX:.0f} nm")
print(f"LTR390 ALS response support: {ALS_LAM_MIN:.0f} – {ALS_LAM_MAX:.0f} nm")


def response_at(lam_nm, channel):
    """Interpolate normalised response on the libRadtran wavelength grid."""
    if channel == "UV":
        src_lam, src_R, lo, hi = uv_src["Wavelength"].to_numpy(), uv_src["R"].to_numpy(), UV_LAM_MIN, UV_LAM_MAX
    else:
        src_lam, src_R, lo, hi = als_src["Wavelength"].to_numpy(), als_src["R"].to_numpy(), ALS_LAM_MIN, ALS_LAM_MAX
    R = np.interp(lam_nm, src_lam, src_R, left=0.0, right=0.0)
    R[(lam_nm < lo) | (lam_nm > hi)] = 0.0
    return R


# ---------------------------------------------------------------------------
# Per-altitude band-weighted integration
# ---------------------------------------------------------------------------
MW_TO_W = 1e-3  # Kurucz solar flux is mW/(m^2 nm); convert to W/(m^2 nm)

LOOP_DIR = ROOT / "loop"
OUT_PATH = ROOT / "Experiment" / "sensor_predicted.csv"


def band_weighted(lam, flux, weight):
    return float(np.trapezoid(flux * weight, lam))


rows = []
for z in range(0, 41):
    path = LOOP_DIR / f"eup_{z}km.dat"
    if not path.exists():
        continue
    arr = np.loadtxt(path, comments="#")
    lam = arr[:, 0]
    eup = arr[:, 3]
    eglo = arr[:, 6]
    R_uv = response_at(lam, "UV")
    R_als = response_at(lam, "ALS")
    rows.append({
        "z_km": float(z),
        "p_hPa": float(isa_pressure_hPa(np.array([z * 1000.0]))[0]),
        "uv_resp_eup_Wm2":   band_weighted(lam, eup,  R_uv)  * MW_TO_W,
        "uv_resp_eglo_Wm2":  band_weighted(lam, eglo, R_uv)  * MW_TO_W,
        "als_resp_eup_Wm2":  band_weighted(lam, eup,  R_als) * MW_TO_W,
        "als_resp_eglo_Wm2": band_weighted(lam, eglo, R_als) * MW_TO_W,
    })

df = pd.DataFrame(rows)
df.to_csv(OUT_PATH, index=False, float_format="%g")
print(f"\nWrote {OUT_PATH}")

print("\nSanity check (W/m^2):")
for z in (0, 10, 20, 30, 40):
    if z in df["z_km"].values:
        r = df[df["z_km"] == z].iloc[0]
        print(f"  z={z:2d} km  uv_eup={r['uv_resp_eup_Wm2']:7.3f}  uv_eglo={r['uv_resp_eglo_Wm2']:7.3f}  "
              f"als_eup={r['als_resp_eup_Wm2']:7.3f}  als_eglo={r['als_resp_eglo_Wm2']:7.3f}")
