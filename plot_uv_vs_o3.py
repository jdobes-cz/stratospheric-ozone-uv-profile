"""Plot dE_up/dz vs local O3 concentration for UV (280-400 nm) and visible (400-700 nm).

At altitudes with high ozone mixing ratio, the upward flux changes rapidly with
altitude for UV (Hartley/Huggins bands) but only weakly for visible (only the
Chappuis band absorbs there). Both altitude-gradients are plotted on the same
axes against local O3 ppmv so their different sensitivities are directly
comparable.
"""
import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from pathlib import Path


# ---------------------------------------------------------------------------
# ISA 1976 atmosphere (mirrors plot_profile.py / interpolation1.py)
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


def isa_temp_K(z_m: np.ndarray) -> np.ndarray:
    z = np.asarray(z_m, dtype=float)
    T = np.full(z.shape, np.nan)
    for i in range(LAPSE.size):
        mask = (z >= HB_M[i]) & (z <= HB_M[i + 1])
        T[mask] = TB[i] + LAPSE[i] * (z[mask] - HB_M[i])
    above = z > HB_M[-1]
    if np.any(above):
        T[above] = TB[-1] + LAPSE[-1] * (z[above] - HB_M[-1])
    return T


# ---------------------------------------------------------------------------
# O3 profile → ppmv at each km
# ---------------------------------------------------------------------------
o3 = pd.read_csv(
    "o3_mmr.dat",
    sep=r"\s+",
    comment="#",
    names=["p_hPa", "mmr"],
).sort_values("p_hPa").reset_index(drop=True)

K_B = 1.380649e-23  # Boltzmann [J/K]

altitudes_km = np.arange(0, 41)
p_at_alt_hPa = isa_pressure_hPa(altitudes_km * 1000.0)
T_at_alt_K = isa_temp_K(altitudes_km * 1000.0)

# Interpolate mmr in log-pressure
mmr_at_alt = np.interp(
    np.log(p_at_alt_hPa),
    np.log(o3["p_hPa"].to_numpy()),
    o3["mmr"].to_numpy(),
)
ppmv_at_alt = mmr_at_alt * 0.603 * 1e6                   # ppmv (volume mixing ratio)
n_air_cm3 = (p_at_alt_hPa * 100.0) / (K_B * T_at_alt_K) / 1e6  # molec/cm³
n_o3_cm3 = ppmv_at_alt * 1e-6 * n_air_cm3               # O3 number density [molec/cm³]


# ---------------------------------------------------------------------------
# Upward irradiance per altitude (column 3 = eup from output_user)
# ---------------------------------------------------------------------------
UV_BAND = (280.0, 400.0)
VIS_BAND = (400.0, 700.0)


def band_integrate(lam, flux, band):
    m = (lam >= band[0]) & (lam <= band[1])
    if m.sum() < 2:
        return 0.0
    return float(np.trapezoid(flux[m], lam[m]))


loop_dir = Path("loop")
rows = []
for z_km in altitudes_km:
    path = loop_dir / f"eup_{z_km}km.dat"
    if not path.exists():
        continue
    arr = np.loadtxt(path, comments="#")
    lam = arr[:, 0]
    eup = arr[:, 3]  # upward irradiance [mW m-2 nm-1]
    rows.append({
        "z_km": float(z_km),
        "uv_up": band_integrate(lam, eup, UV_BAND),
        "vis_up": band_integrate(lam, eup, VIS_BAND),
    })

irr = pd.DataFrame(rows).sort_values("z_km").reset_index(drop=True)
z = irr["z_km"].to_numpy()
irr["ppmv"] = np.interp(z, altitudes_km, ppmv_at_alt)
irr["n_o3"] = np.interp(z, altitudes_km, n_o3_cm3)  # molec/cm³

# dE/dz via central differences (np.gradient handles uneven spacing and edges)
irr["duv_dz"] = np.gradient(irr["uv_up"].to_numpy(), z)
irr["dvis_dz"] = np.gradient(irr["vis_up"].to_numpy(), z)
# Fractional gradient d(lnE)/dz = (1/E) dE/dz  — local extinction-coefficient proxy
irr["dln_uv_dz"] = irr["duv_dz"] / irr["uv_up"]
irr["dln_vis_dz"] = irr["dvis_dz"] / irr["vis_up"]


# ---------------------------------------------------------------------------
# Plot — two panels vs local O3 number density:
#   left:  dE_up/dz  on log-y   (absolute gradient, mW m^-2 km^-1)
#   right: d(lnE)/dz on log-y   (fractional gradient, km^-1, ~ extinction coef)
# ---------------------------------------------------------------------------
fig, (ax_abs, ax_rel) = plt.subplots(1, 2, figsize=(13, 6.5))

for ax in (ax_abs, ax_rel):
    ax.set_yscale("log")
    ax.set_xlabel(r"Local O$_3$ number density  [molec cm$^{-3}$]")
    ax.grid(True, which="both", alpha=0.3)

ax_abs.plot(irr["n_o3"], irr["duv_dz"], color="tab:purple",
            marker="o", ms=6, lw=2, label="UV 280–400 nm")
ax_abs.plot(irr["n_o3"], irr["dvis_dz"], color="tab:orange",
            marker="s", ms=6, lw=2, label="Visible (ambient) 400–700 nm")
ax_abs.set_ylabel(r"$dE_\mathrm{up}/dz$   [mW m$^{-2}$ km$^{-1}$]  (log)")
ax_abs.set_title("Absolute altitude-gradient")
ax_abs.legend(loc="best", fontsize=10)

ax_rel.plot(irr["n_o3"], irr["dln_uv_dz"], color="tab:purple",
            marker="o", ms=6, lw=2, label="UV 280–400 nm")
ax_rel.plot(irr["n_o3"], irr["dln_vis_dz"], color="tab:orange",
            marker="s", ms=6, lw=2, label="Visible (ambient) 400–700 nm")
ax_rel.set_ylabel(r"$d(\ln E_\mathrm{up})/dz$   [km$^{-1}$]  (log)")
ax_rel.set_title("Fractional gradient  (≈ local extinction coef.)")
ax_rel.legend(loc="best", fontsize=10)

for _, r in irr.iterrows():
    zi = int(round(r["z_km"]))
    if zi in (0, 5, 10, 15, 20, 25, 30, 35, 40):
        ax_abs.annotate(f"{zi} km",
                        xy=(r["n_o3"], r["duv_dz"]),
                        xytext=(5, 5), textcoords="offset points",
                        fontsize=7, color="tab:purple")
        ax_rel.annotate(f"{zi} km",
                        xy=(r["n_o3"], r["dln_uv_dz"]),
                        xytext=(5, 5), textcoords="offset points",
                        fontsize=7, color="tab:purple")

fig.suptitle(
    "Upward-irradiance altitude-gradient vs local O$_3$ number density  |  "
    "Brussels 50.80°N, 4.36°E  |  2026-04-23 14:00 CEST  (SZA 38.4°)",
    fontsize=11,
)
fig.tight_layout(rect=(0, 0, 1, 0.95))
out = Path("uv_vs_o3.png")
fig.savefig(out, dpi=140)
print(f"Saved: {out.resolve()}")
print()
print(irr[["z_km", "ppmv", "n_o3", "uv_up", "vis_up", "duv_dz", "dvis_dz"]]
      .assign(n_o3=lambda d: d["n_o3"].map(lambda v: f"{v:.2e}"))
      .round(3).to_string(index=False))
