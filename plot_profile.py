"""Plot predicted atmospheric profile for the 2026-04-23 14:00 CEST balloon flight.

Four panels share a pressure (log) x-axis, with altitude as a twin top axis:
  - Temperature (ISA 1976)
  - Ozone (from CAMS, interpolated to Brussels)
  - UV upwelling irradiance 280-400 nm (libRadtran eup, band-integrated)
  - Ambient/visible upwelling irradiance 400-700 nm (libRadtran eup, band-integrated)

libRadtran output columns (from uvspec_template.inp `output_user lambda sza zout eup edir edn eglo`):
  0: lambda [nm]
  1: sza [deg]
  2: zout [km]
  3: eup  - upwelling irradiance
  4: edir - direct downwelling
  5: edn  - diffuse downwelling
  6: eglo - global downwelling
Irradiance values are in mW m^-2 nm^-1 (Kurucz solar flux units); we divide by 1000 to report in W m^-2.
"""
import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
from pathlib import Path


# ---------------------------------------------------------------------------
# ISA 1976 piecewise atmosphere (mirrors interpolation1.py)
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


def isa_temp_K(z_m: np.ndarray) -> np.ndarray:
    z = np.asarray(z_m, dtype=float)
    T = np.full(z.shape, np.nan)
    for i in range(LAPSE.size):
        mask = (z >= HB_M[i]) & (z <= HB_M[i + 1])
        T[mask] = TB[i] + LAPSE[i] * (z[mask] - HB_M[i])
    # Extrapolate above 47 km with top-layer lapse (keeps plot usable if needed)
    above = z > HB_M[-1]
    if np.any(above):
        T[above] = TB[-1] + LAPSE[-1] * (z[above] - HB_M[-1])
    return T


def isa_pressure_hPa(z_m: np.ndarray) -> np.ndarray:
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


# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------
o3 = pd.read_csv(
    "o3_mmr.dat",
    sep=r"\s+",
    comment="#",
    names=["p_hPa", "o3_mmr_kgkg"],
)
o3["o3_ppmv"] = o3["o3_mmr_kgkg"] * 0.603 * 1e6

UV_BAND = (280.0, 400.0)
VIS_BAND = (400.0, 700.0)


def band_integrate(lam: np.ndarray, flux: np.ndarray, band: tuple[float, float]) -> float:
    m = (lam >= band[0]) & (lam <= band[1])
    if m.sum() < 2:
        return 0.0
    return float(np.trapezoid(flux[m], lam[m]))


rows = []
loop_dir = Path("loop")
MW_TO_W = 1e-3  # Kurucz solar flux is in mW/(m^2 nm); convert integrated band to W/m^2
for z in range(0, 41):
    path = loop_dir / f"eup_{z}km.dat"
    if not path.exists():
        continue
    arr = np.loadtxt(path, comments="#")
    lam = arr[:, 0]
    eup = arr[:, 3]  # upwelling irradiance
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
# Plot
# ---------------------------------------------------------------------------
fig, axes = plt.subplots(2, 2, figsize=(12, 8), sharex=True)
ax_t, ax_o = axes[0]
ax_uv, ax_vis = axes[1]

P_MIN, P_MAX = 1.0, 1013.25
ALT_TICKS_KM = [0, 5, 10, 15, 20, 25, 30, 35, 40]

for ax in axes.flat:
    ax.set_xscale("log")
    ax.set_xlim(P_MAX, P_MIN)  # surface on the left, TOA on the right
    ax.grid(True, which="both", alpha=0.3)

# Temperature
ax_t.plot(temp["p_hPa"], temp["T_C"], color="tab:red")
ax_t.set_ylabel("Temperature [°C]")
ax_t.set_title("ISA 1976 temperature")
ax_t.axhline(0, color="gray", lw=0.5, ls="--")

# Ozone
ax_o.plot(o3["p_hPa"], o3["o3_ppmv"], color="tab:blue", marker="o", ms=3)
ax_o.set_ylabel("Ozone [ppmv]")
ax_o.set_title("CAMS ozone forecast (interp. to 50.8 N, 4.36 E)")

# UV (upwelling)
ax_uv.plot(irr["p_hPa"], irr["uv_Wm2"], color="tab:purple", marker="o", ms=3)
ax_uv.set_ylabel(r"UV 280–400 nm  $[W/m^2]$")
ax_uv.set_title("Upwelling UV irradiance (libRadtran eup)")

# Ambient / visible (upwelling)
ax_vis.plot(irr["p_hPa"], irr["vis_Wm2"], color="tab:orange", marker="o", ms=3)
ax_vis.set_ylabel(r"Visible 400–700 nm  $[W/m^2]$")
ax_vis.set_title("Upwelling visible irradiance (libRadtran eup)")

# X labels (bottom row only)
for ax in (ax_uv, ax_vis):
    ax.set_xlabel("Pressure [hPa]")

# Altitude twin on top row
def add_alt_axis(ax):
    secax = ax.secondary_xaxis(
        "top",
        functions=(
            lambda p: np.interp(np.clip(p, P_MIN, P_MAX), temp["p_hPa"][::-1], temp["z_km"][::-1]),
            lambda z: isa_pressure_hPa(np.asarray(z) * 1000.0),
        ),
    )
    secax.set_xlabel("Altitude [km] (ISA)")
    secax.set_xticks(ALT_TICKS_KM)
    secax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:g}"))
    secax.xaxis.set_minor_locator(mticker.NullLocator())

for ax in (ax_t, ax_o):
    add_alt_axis(ax)

fig.suptitle(
    "Predicted atmospheric profile  |  Brussels 50.80 N, 4.36 E  |  2026-04-23 14:00 CEST  (SZA 38.4°)",
    fontsize=12,
)
fig.tight_layout(rect=(0, 0, 1, 0.96))

out = Path("profile.png")
fig.savefig(out, dpi=140)
print(f"Saved: {out.resolve()}")
