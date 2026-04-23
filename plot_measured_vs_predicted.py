"""Overlay measured Arduino CSV data (converted to profile.png units) on top of
the four predicted profile.png panels. One figure per panel.

Predicted curves mirror plot_profile.py exactly. Measured scatter comes from
Experiment/20260423_converted.CSV (produced by convert_csv.py).

Outputs:
  compare_temperature.png
  compare_ozone.png
  compare_uv.png
  compare_visible.png
"""
import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
from pathlib import Path


# ---------------------------------------------------------------------------
# ISA 1976 piecewise atmosphere (mirrors plot_profile.py)
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


def isa_temp_K(z_m):
    z = np.asarray(z_m, dtype=float)
    T = np.full(z.shape, np.nan)
    for i in range(LAPSE.size):
        mask = (z >= HB_M[i]) & (z <= HB_M[i + 1])
        T[mask] = TB[i] + LAPSE[i] * (z[mask] - HB_M[i])
    above = z > HB_M[-1]
    if np.any(above):
        T[above] = TB[-1] + LAPSE[-1] * (z[above] - HB_M[-1])
    return T


def isa_pressure_hPa(z_m):
    z = np.asarray(z_m, dtype=float)
    P = np.full(z.shape, np.nan)
    for i in range(LAPSE.size):
        mask = (z >= HB_M[i]) & (z <= HB_M[i + 1])
        if LAPSE[i] == 0.0:
            P[mask] = PB_HPA[i] * np.exp(-G0 * (z[mask] - HB_M[i]) / (R_SPEC * TB[i]))
        else:
            T_here = TB[i] + LAPSE[i] * (z[mask] - HB_M[i])
            P[mask] = PB_HPA[i] * (TB[i] / T_here) ** (G0 / (R_SPEC * LAPSE[i]))
    above = z > HB_M[-1]
    if np.any(above):
        i = LAPSE.size - 1
        T_here = TB[i] + LAPSE[i] * (z[above] - HB_M[i])
        P[above] = PB_HPA[i] * (TB[i] / T_here) ** (G0 / (R_SPEC * LAPSE[i]))
    return P


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
    above_top = valid & (p < PB_HPA[-1])
    if above_top.any():
        i = LAPSE.size - 1
        expn = -R_SPEC * LAPSE[i] / G0
        z[above_top] = HB_M[i] + (TB[i] / LAPSE[i]) * ((p[above_top] / PB_HPA[i]) ** expn - 1.0)
    return z / 1000.0


# ---------------------------------------------------------------------------
# Load predicted data (same as plot_profile.py)
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent

o3 = pd.read_csv(
    ROOT / "o3_mmr.dat",
    sep=r"\s+",
    comment="#",
    names=["p_hPa", "o3_mmr_kgkg"],
)
o3["o3_ppmv"] = o3["o3_mmr_kgkg"] * 0.603 * 1e6
o3["z_km"] = isa_altitude_km(o3["p_hPa"].to_numpy())
o3 = o3.sort_values("z_km").reset_index(drop=True)

UV_BAND = (280.0, 400.0)
VIS_BAND = (400.0, 700.0)
MW_TO_W = 1e-3


def band_integrate(lam, flux, band):
    m = (lam >= band[0]) & (lam <= band[1])
    if m.sum() < 2:
        return 0.0
    return float(np.trapezoid(flux[m], lam[m]))


loop_dir = ROOT / "loop"
rows = []
for z in range(0, 41):
    path = loop_dir / f"eup_{z}km.dat"
    if not path.exists():
        continue
    arr = np.loadtxt(path, comments="#")
    lam = arr[:, 0]
    eup = arr[:, 3]
    rows.append({
        "z_km": float(z),
        "uv_Wm2":  band_integrate(lam, eup, UV_BAND)  * MW_TO_W,
        "vis_Wm2": band_integrate(lam, eup, VIS_BAND) * MW_TO_W,
    })
irr = pd.DataFrame(rows)
irr["p_hPa"] = isa_pressure_hPa(irr["z_km"].to_numpy() * 1000.0)

z_dense_m = np.linspace(0.0, 45000.0, 451)
temp = pd.DataFrame({
    "z_km": z_dense_m / 1000.0,
    "T_C": isa_temp_K(z_dense_m) - 273.15,
    "p_hPa": isa_pressure_hPa(z_dense_m),
})


# ---------------------------------------------------------------------------
# Load measured data
# ---------------------------------------------------------------------------
# Note: temp_c is the externally-mounted MS5607 (ambient air, bottom of
# gondola). It carries a +10 to +35 °C warm bias above the tropopause from
# unshielded radiative/conductive coupling to the gondola — see
# Experiment/data_review.md §2.1.
meas = pd.read_csv(ROOT / "Experiment" / "20260423_cleaned.CSV")

# Sensor-band-integrated prediction (LTR390 UV/ALS spectral response convolved
# with libRadtran upwelling spectrum). See predict_sensor_response.py.
SENSOR_PRED_PATH = ROOT / "Experiment" / "sensor_predicted.csv"
sensor_pred = pd.read_csv(SENSOR_PRED_PATH) if SENSOR_PRED_PATH.exists() else None


# ---------------------------------------------------------------------------
# Shared plot setup
# ---------------------------------------------------------------------------
Z_MIN, Z_MAX = 0.0, 40.0
PRESSURE_TICKS_HPA = [1000, 500, 200, 100, 50, 20, 10, 5, 2]
SUPTITLE = (
    "ASGARD-XV Exp 14  |  Brussels 50.80 N, 4.36 E  |  "
    "2026-04-23 14:00 CEST  (SZA 38.4°)"
)


def add_pressure_axis(ax):
    """Twin top axis labelled in pressure (hPa). Uses explicit altitude
    placement of pressure ticks rather than secondary_xaxis(xscale='log'),
    which silently inverts the tick order when combined with custom
    transform functions in matplotlib >= 3.5."""
    ax2 = ax.twiny()
    ax2.set_xlim(ax.get_xlim())
    # Each pressure tick is placed at the altitude (km) where ISA p == that value
    z_for_p = [float(np.interp(p, temp["p_hPa"][::-1], temp["z_km"][::-1]))
               for p in PRESSURE_TICKS_HPA]
    ax2.set_xticks(z_for_p)
    ax2.set_xticklabels([f"{p:g}" for p in PRESSURE_TICKS_HPA])
    ax2.set_xlabel("Pressure [hPa] (ISA)")
    ax2.tick_params(axis="x", which="minor", bottom=False, top=False)


def new_fig(title):
    fig, ax = plt.subplots(figsize=(9, 5.5))
    ax.set_xlim(Z_MIN, Z_MAX)
    ax.grid(True, which="both", alpha=0.3)
    ax.set_xlabel("Altitude [km] (ISA)")
    ax.set_title(title)
    add_pressure_axis(ax)
    fig.suptitle(SUPTITLE, fontsize=10)
    return fig, ax


MEAS_KW = dict(marker=".", s=10, alpha=0.5, zorder=3, label="Measured (Arduino)")
PRED_KW = dict(lw=2.0, zorder=2, label="Predicted")


# ---------------------------------------------------------------------------
# 1. Temperature
# ---------------------------------------------------------------------------
fig, ax = new_fig("ISA 1976 temperature vs measured MS5607")
ax.plot(temp["z_km"], temp["T_C"], color="tab:red", **PRED_KW)
m = meas.dropna(subset=["isa_alt_km", "temp_c"])
ax.scatter(m["isa_alt_km"], m["temp_c"], color="black", **MEAS_KW)
ax.axhline(0, color="gray", lw=0.5, ls="--")
ax.set_ylabel("Temperature [°C]")
ax.text(0.02, 0.02,
        "MS5607 mounted bottom-of-gondola (shaded from direct sun): warm bias above\n"
        "tropopause is from Earth-IR + gondola-IR + conductive coupling (data_review §3.1)",
        transform=ax.transAxes, fontsize=8, color="dimgray",
        verticalalignment="bottom")
ax.legend(loc="best")
fig.tight_layout(rect=(0, 0, 1, 0.95))
fig.savefig(ROOT / "compare_temperature.png", dpi=140)
plt.close(fig)

# ---------------------------------------------------------------------------
# 2. Ozone
# ---------------------------------------------------------------------------
fig, ax = new_fig("CAMS ozone forecast vs measured SEN0321")
ax.plot(o3["z_km"], o3["o3_ppmv"], color="tab:blue", marker="o", ms=3, **PRED_KW)
m = meas.dropna(subset=["isa_alt_km", "o3_ppmv"])
ax.scatter(m["isa_alt_km"], m["o3_ppmv"], color="black", **MEAS_KW)
ax.set_ylabel("Ozone [ppmv]")
ax.legend(loc="best")
fig.tight_layout(rect=(0, 0, 1, 0.95))
fig.savefig(ROOT / "compare_ozone.png", dpi=140)
plt.close(fig)

# ---------------------------------------------------------------------------
# 3. UV (upwelling)
# ---------------------------------------------------------------------------
fig, ax = new_fig("Upwelling UV — libRadtran ⊗ LTR390 spectral response  vs  LTR390 UVS")
if sensor_pred is None:
    raise SystemExit("Run predict_sensor_response.py first to generate Experiment/sensor_predicted.csv")
ax.plot(sensor_pred["z_km"], sensor_pred["uv_resp_eup_Wm2"],
        color="tab:purple", marker="o", ms=3, lw=2.0,
        label="Predicted (libRadtran ⊗ LTR390 UV response)")
ax.set_ylabel(r"Predicted irradiance in LTR390 UV band $[W/m^2]$",
              color="tab:purple")
ax.tick_params(axis="y", labelcolor="tab:purple")

m = meas.dropna(subset=["isa_alt_km", "uvi"])
ax_r = ax.twinx()
ax_r.scatter(m["isa_alt_km"], m["uvi"], color="black",
             marker=".", s=12, alpha=0.6, zorder=3, label="Measured UVI (raw)")
ax_r.set_ylabel("Measured UVI", color="black")

# Linear (through-zero) scaling of the right axis so the predicted and
# measured curves visually overlay. Both axes start at 0; ymax_right /
# ymax_left = (median measured plateau) / (median predicted plateau)
# above 10 km — see data_review.md §3.3.
pred_plateau = float(sensor_pred.loc[sensor_pred["z_km"] >= 10, "uv_resp_eup_Wm2"].median())
meas_plateau = float(m.loc[m["isa_alt_km"] >= 10, "uvi"].median())
ymax_left = max(sensor_pred["uv_resp_eup_Wm2"].max(), 1.0) * 1.15
scale = meas_plateau / pred_plateau
ax.set_ylim(0, ymax_left)
ax_r.set_ylim(0, ymax_left * scale)

lines1, labels1 = ax.get_legend_handles_labels()
lines2, labels2 = ax_r.get_legend_handles_labels()
ax.legend(lines1 + lines2, labels1 + labels2, loc="lower right", fontsize=9)
fig.tight_layout(rect=(0, 0, 1, 0.95))
fig.savefig(ROOT / "compare_uv.png", dpi=140)
plt.close(fig)

# ---------------------------------------------------------------------------
# 4. Visible (upwelling)
# ---------------------------------------------------------------------------
fig, ax = new_fig("Upwelling visible — libRadtran ⊗ LTR390 spectral response  vs  LTR390 ALS")
ax.plot(sensor_pred["z_km"], sensor_pred["als_resp_eup_Wm2"],
        color="tab:orange", marker="o", ms=3, lw=2.0,
        label="Predicted (libRadtran ⊗ LTR390 ALS response)")
ax.set_ylabel(r"Predicted irradiance in LTR390 ALS band $[W/m^2]$",
              color="tab:orange")
ax.tick_params(axis="y", labelcolor="tab:orange")

m = meas.dropna(subset=["isa_alt_km", "lux"])
ax_r = ax.twinx()
ax_r.scatter(m["isa_alt_km"], m["lux"], color="black",
             marker=".", s=12, alpha=0.6, zorder=3, label="Measured illuminance (raw)")
ax_r.set_ylabel("Measured illuminance [lux]", color="black")

# Linear (through-zero) scaling: same construction as the UV panel.
pred_plateau = float(sensor_pred.loc[sensor_pred["z_km"] >= 10, "als_resp_eup_Wm2"].median())
meas_plateau = float(m.loc[m["isa_alt_km"] >= 10, "lux"].median())
ymax_left = max(sensor_pred["als_resp_eup_Wm2"].max(), 1.0) * 1.15
scale = meas_plateau / pred_plateau
ax.set_ylim(0, ymax_left)
ax_r.set_ylim(0, ymax_left * scale)

lines1, labels1 = ax.get_legend_handles_labels()
lines2, labels2 = ax_r.get_legend_handles_labels()
ax.legend(lines1 + lines2, labels1 + labels2, loc="lower right", fontsize=9)
fig.tight_layout(rect=(0, 0, 1, 0.95))
fig.savefig(ROOT / "compare_visible.png", dpi=140)
plt.close(fig)

print("Saved:")
for name in ("compare_temperature.png", "compare_ozone.png", "compare_uv.png", "compare_visible.png"):
    print(f"  {(ROOT / name).resolve()}")
