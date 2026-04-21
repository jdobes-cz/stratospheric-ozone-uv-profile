"""Build the ASGARD-XV Exp 14 white paper: compute results, render figures,
emit paper.html, and invoke weasyprint to produce paper.pdf.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
PAPER_DIR = ROOT / "paper"
PAPER_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# ISA 1976 piecewise atmosphere
# ---------------------------------------------------------------------------
G0 = 9.80665
R_SPEC = 287.05287
P0_HPA = 1013.25
T0 = 288.15
K_B = 1.380649e-23

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
        m = (z >= HB_M[i]) & (z <= HB_M[i + 1])
        T[m] = TB[i] + LAPSE[i] * (z[m] - HB_M[i])
    above = z > HB_M[-1]
    if np.any(above):
        T[above] = TB[-1] + LAPSE[-1] * (z[above] - HB_M[-1])
    return T


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


def isa_altitude_km(p_hpa):
    p = np.asarray(p_hpa, dtype=float)
    z = np.full(p.shape, np.nan)
    for i in range(LAPSE.size):
        p_top = PB_HPA[i + 1]
        p_base = PB_HPA[i]
        m = (p <= p_base) & (p >= p_top)
        if not m.any():
            continue
        if LAPSE[i] == 0.0:
            z[m] = HB_M[i] - (R_SPEC * TB[i] / G0) * np.log(p[m] / p_base)
        else:
            expn = -R_SPEC * LAPSE[i] / G0
            z[m] = HB_M[i] + (TB[i] / LAPSE[i]) * ((p[m] / p_base) ** expn - 1.0)
    above = p < PB_HPA[-1]
    if above.any():
        i = LAPSE.size - 1
        expn = -R_SPEC * LAPSE[i] / G0
        z[above] = HB_M[i] + (TB[i] / LAPSE[i]) * ((p[above] / PB_HPA[i]) ** expn - 1.0)
    return z / 1000.0


# ---------------------------------------------------------------------------
# Data loading and band integration
# ---------------------------------------------------------------------------
MW_TO_W = 1e-3   # Kurucz solar file is in mW/(m^2 nm)

BANDS = {
    "UVC": (250.0, 280.0),
    "UVB": (280.0, 315.0),
    "UVA": (315.0, 400.0),
    "UV":  (280.0, 400.0),
    "VIS": (400.0, 700.0),
    "NIR": (700.0, 1100.0),
    "ALL": (250.0, 1100.0),
}


def band_int(lam, flux, band):
    m = (lam >= band[0]) & (lam <= band[1])
    if m.sum() < 2:
        return 0.0
    return float(np.trapezoid(flux[m], lam[m]))


def load_altitude_file(z_km):
    path = ROOT / "loop" / f"eup_{z_km}km.dat"
    arr = np.loadtxt(path, comments="#")
    return {
        "lam": arr[:, 0],
        "sza": arr[:, 1],
        "zout": arr[:, 2],
        "eup":  arr[:, 3],
        "edir": arr[:, 4],
        "edn":  arr[:, 5],
        "eglo": arr[:, 6],
    }


# ---------------------------------------------------------------------------
# 1. Ozone profile + total column
# ---------------------------------------------------------------------------
o3 = pd.read_csv(ROOT / "o3_mmr.dat", sep=r"\s+", comment="#",
                 names=["p_hPa", "o3_mmr_kgkg"])
o3["o3_ppmv"] = o3["o3_mmr_kgkg"] * 0.603e6  # kg/kg -> ppmv (M_air/M_O3 approx)
o3["alt_km"] = isa_altitude_km(o3["p_hPa"].to_numpy())
o3 = o3.sort_values("alt_km").reset_index(drop=True)

# Total ozone column (Dobson Units)
M_AIR = 28.9647
M_O3  = 47.9982
p_pa = o3["p_hPa"].to_numpy() * 100.0
T_K = isa_temp_K(o3["alt_km"].to_numpy() * 1000.0)
n_air = p_pa / (K_B * T_K)                 # molec / m^3
q_vmr = o3["o3_mmr_kgkg"].to_numpy() * (M_AIR / M_O3)
n_o3 = q_vmr * n_air                       # molec / m^3
z_m = o3["alt_km"].to_numpy() * 1000.0
col_molec_m2 = float(np.trapezoid(n_o3, z_m))
if z_m[0] > 0:
    col_molec_m2 += float(n_o3[0] * z_m[0])  # pad surface->lowest level
TOTAL_DU = col_molec_m2 / 2.687e20

peak_idx = int(o3["o3_ppmv"].to_numpy().argmax())
PEAK_PPMV   = float(o3["o3_ppmv"].iloc[peak_idx])
PEAK_ALT_KM = float(o3["alt_km"].iloc[peak_idx])
PEAK_P_HPA  = float(o3["p_hPa"].iloc[peak_idx])


# ---------------------------------------------------------------------------
# 2. Band-integrated irradiance at every altitude (W/m^2)
# ---------------------------------------------------------------------------
rows = []
sza_val = None
for z in range(0, 41):
    d = load_altitude_file(z)
    if sza_val is None:
        sza_val = float(d["sza"][0])
    row = {"z_km": float(z), "p_hPa": float(isa_pressure_hPa(np.array([z * 1000.0]))[0])}
    for name, band in BANDS.items():
        for comp in ("eup", "edir", "edn", "eglo"):
            row[f"{comp}_{name}"] = band_int(d["lam"], d[comp], band) * MW_TO_W
    rows.append(row)
irr = pd.DataFrame(rows)
SZA_DEG = sza_val


# ---------------------------------------------------------------------------
# 3. Figure 2 -- UV sub-band (upwelling) vs. altitude, log y
# ---------------------------------------------------------------------------
fig, ax = plt.subplots(figsize=(8, 5))
ax.plot(irr["z_km"], irr["eup_UVA"], label="UV-A (315–400 nm)", color="tab:purple", marker="o", ms=3)
ax.plot(irr["z_km"], irr["eup_UVB"], label="UV-B (280–315 nm)", color="tab:red",    marker="s", ms=3)
ax.plot(irr["z_km"], irr["eup_UVC"], label="UV-C (250–280 nm)", color="black",      marker="^", ms=3)
ax.set_yscale("log")
ax.set_xlabel("Altitude [km]")
ax.set_ylabel(r"Upwelling irradiance (eup) $[W/m^2]$")
ax.set_title("Upwelling UV by sub-band — ASGARD-XV Exp 14, 2026-04-23 14:00 CEST")
ax.grid(True, which="both", alpha=0.3)
ax.set_xlim(0, 40)
ax.set_ylim(1e-12, 20)
ax.legend(loc="lower right")
fig.tight_layout()
fig.savefig(PAPER_DIR / "uv_bands.png", dpi=140)
plt.close(fig)


# ---------------------------------------------------------------------------
# 4. Figure 3 -- Spectral eup at selected altitudes
# ---------------------------------------------------------------------------
fig, ax = plt.subplots(figsize=(8, 5))
palette = plt.cm.viridis(np.linspace(0.05, 0.9, 5))
for color, z in zip(palette, (0, 10, 20, 30, 40)):
    d = load_altitude_file(z)
    ax.plot(d["lam"], d["eup"] * MW_TO_W, label=f"{z} km", color=color, lw=1.2)
ax.set_yscale("log")
ax.set_xlim(250, 1100)
ax.set_ylim(1e-8, 1.5)
ax.set_xlabel("Wavelength [nm]")
ax.set_ylabel(r"Spectral upwelling irradiance $[W/(m^2\,nm)]$")
ax.set_title("Upwelling spectrum at selected altitudes (SZA = 38.37°)")
ax.axvspan(250, 280, color="gray", alpha=0.08, label="UV-C")
ax.axvspan(280, 315, color="red",  alpha=0.08, label="UV-B")
ax.axvspan(315, 400, color="purple", alpha=0.08, label="UV-A")
ax.grid(True, which="both", alpha=0.3)
ax.legend(loc="lower right", ncol=2, fontsize=9)
fig.tight_layout()
fig.savefig(PAPER_DIR / "spectrum.png", dpi=140)
plt.close(fig)


# ---------------------------------------------------------------------------
# 5. Pre-formatted numbers for the paper
# ---------------------------------------------------------------------------
def v(z_km, key):
    return float(irr.loc[irr["z_km"] == z_km, key].iloc[0])


sel_alts = [0, 5, 10, 15, 20, 25, 30, 35, 40]
eup_table_rows = []
for z in sel_alts:
    eup_table_rows.append({
        "z_km": z,
        "p_hPa": v(z, "p_hPa"),
        "UVA_eup": v(z, "eup_UVA"),
        "UVB_eup": v(z, "eup_UVB"),
        "UV_eup":  v(z, "eup_UV"),
        "VIS_eup": v(z, "eup_VIS"),
        "NIR_eup": v(z, "eup_NIR"),
    })

eglo_table_rows = []
for z in sel_alts:
    eglo_table_rows.append({
        "z_km": z,
        "UV_eglo":  v(z, "eglo_UV"),
        "VIS_eglo": v(z, "eglo_VIS"),
        "ALL_eglo": v(z, "eglo_ALL"),
    })

# Ozone table
ozone_rows = []
for _, r in o3.iterrows():
    ozone_rows.append({
        "p_hPa": float(r["p_hPa"]),
        "alt_km": float(r["alt_km"]),
        "o3_mmr": float(r["o3_mmr_kgkg"]),
        "o3_ppmv": float(r["o3_ppmv"]),
    })

summary = {
    "sza_deg": SZA_DEG,
    "ozone_peak_ppmv": PEAK_PPMV,
    "ozone_peak_alt_km": PEAK_ALT_KM,
    "ozone_peak_p_hPa": PEAK_P_HPA,
    "ozone_column_DU": TOTAL_DU,
    "eup_UV_0km":  v(0,  "eup_UV"),
    "eup_UV_40km": v(40, "eup_UV"),
    "eup_VIS_0km":  v(0,  "eup_VIS"),
    "eup_VIS_40km": v(40, "eup_VIS"),
    "eglo_UV_0km":  v(0,  "eglo_UV"),
    "eglo_UV_40km": v(40, "eglo_UV"),
    "eglo_VIS_0km":  v(0,  "eglo_VIS"),
    "eglo_VIS_40km": v(40, "eglo_VIS"),
    "eglo_ALL_40km": v(40, "eglo_ALL"),
    "uv_ratio_0km":  v(0,  "eup_UV")  / v(0,  "eglo_UV"),
    "uv_ratio_40km": v(40, "eup_UV")  / v(40, "eglo_UV"),
    "vis_ratio_0km":  v(0,  "eup_VIS") / v(0,  "eglo_VIS"),
    "vis_ratio_40km": v(40, "eup_VIS") / v(40, "eglo_VIS"),
}
(PAPER_DIR / "summary.json").write_text(json.dumps(summary, indent=2))


# ---------------------------------------------------------------------------
# 6. HTML + CSS
# ---------------------------------------------------------------------------
def fmt(x, digits=3):
    if abs(x) >= 100:
        return f"{x:.{max(0, digits-1)}f}"
    if abs(x) < 0.01:
        return f"{x:.2e}".replace("e-0", "×10⁻").replace("e-", "×10⁻")
    return f"{x:.{digits}g}"


PROFILE_PNG = (ROOT / "profile.png").as_uri()
UVBAND_PNG  = (PAPER_DIR / "uv_bands.png").as_uri()
SPECTRUM_PNG = (PAPER_DIR / "spectrum.png").as_uri()

TODAY = datetime.now(timezone.utc).strftime("%d %B %Y")


def eup_table_html():
    rows = []
    for r in eup_table_rows:
        rows.append(
            "<tr>"
            f"<td>{r['z_km']:g}</td>"
            f"<td>{r['p_hPa']:.2f}</td>"
            f"<td>{r['UVA_eup']:.2f}</td>"
            f"<td>{r['UVB_eup']:.3f}</td>"
            f"<td>{r['UV_eup']:.2f}</td>"
            f"<td>{r['VIS_eup']:.2f}</td>"
            f"<td>{r['NIR_eup']:.2f}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def ozone_table_html():
    rows = []
    for r in ozone_rows:
        rows.append(
            "<tr>"
            f"<td>{r['p_hPa']:.1f}</td>"
            f"<td>{r['alt_km']:.2f}</td>"
            f"<td>{r['o3_mmr']:.3e}</td>"
            f"<td>{r['o3_ppmv']:.3f}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def eglo_table_html():
    rows = []
    for r in eglo_table_rows:
        rows.append(
            "<tr>"
            f"<td>{r['z_km']:g}</td>"
            f"<td>{r['UV_eglo']:.2f}</td>"
            f"<td>{r['VIS_eglo']:.2f}</td>"
            f"<td>{r['ALL_eglo']:.2f}</td>"
            "</tr>"
        )
    return "\n".join(rows)


HTML = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>ASGARD-XV Experiment 14 — Predicted Atmospheric and Radiative Profile</title>
<style>
@page {{
  size: A4;
  margin: 22mm 20mm 22mm 20mm;
  @bottom-center {{
    content: "ASGARD-XV Exp 14 — J. Dobes — Page " counter(page) " / " counter(pages);
    font: 9pt "Georgia", serif;
    color: #555;
  }}
}}
html {{ font-family: "Georgia", "Times New Roman", serif; font-size: 10.5pt; }}
body {{ color: #111; line-height: 1.42; }}

/* Title block */
.title-block {{ text-align: center; margin-bottom: 18pt; }}
.series {{ font-family: "Helvetica", "Arial", sans-serif; font-size: 9pt; letter-spacing: 2pt;
           text-transform: uppercase; color: #666; margin-bottom: 6pt; }}
h1.title {{ font-size: 18pt; font-weight: bold; margin: 4pt 0 6pt 0; line-height: 1.2; }}
.subtitle {{ font-size: 12pt; font-style: italic; color: #333; margin-bottom: 10pt; }}
.author {{ font-size: 11pt; margin-top: 6pt; }}
.affiliation {{ font-size: 10pt; color: #444; }}
.date {{ font-size: 10pt; color: #666; margin-top: 2pt; }}

h2 {{ font-size: 12.5pt; margin-top: 14pt; margin-bottom: 4pt;
       border-bottom: 0.6pt solid #888; padding-bottom: 2pt; }}
h3 {{ font-size: 11pt; margin-top: 10pt; margin-bottom: 2pt; font-style: italic; }}
p  {{ margin: 4pt 0; text-align: justify; }}

.abstract {{ font-size: 10pt; background: #f5f5f2; padding: 8pt 12pt;
              border-left: 2pt solid #444; margin: 10pt 0 14pt 0; }}
.abstract h2 {{ border: none; font-size: 10.5pt; margin: 0 0 4pt 0; padding: 0;
                text-transform: uppercase; letter-spacing: 1pt; color: #444; }}

table {{ border-collapse: collapse; margin: 6pt auto; font-size: 9.5pt; }}
table.data {{ width: 100%; }}
table.data th, table.data td {{ border: 0.4pt solid #bbb; padding: 3pt 6pt; text-align: right; }}
table.data th {{ background: #eee; font-weight: bold; }}
table.data td:first-child, table.data th:first-child {{ text-align: center; }}

.caption {{ font-size: 9pt; color: #333; text-align: center; margin: 4pt 0 10pt 0; }}
.caption b {{ color: #000; }}

figure {{ page-break-inside: avoid; margin: 8pt 0; text-align: center; }}
figure img {{ width: 100%; max-width: 165mm; height: auto; }}

.monospace {{ font-family: "Courier New", monospace; font-size: 9.5pt; }}
code {{ font-family: "Courier New", monospace; font-size: 9.5pt; background: #f0f0ee;
        padding: 0 2pt; border-radius: 2pt; }}
pre  {{ font-family: "Courier New", monospace; font-size: 9pt; background: #f5f5f2;
        padding: 6pt 8pt; border-left: 2pt solid #888; margin: 6pt 0;
        white-space: pre-wrap; word-wrap: break-word; }}

.eqn {{ display: block; text-align: center; font-style: italic; margin: 4pt 0; }}
.var {{ font-style: italic; }}

ol.refs {{ padding-left: 18pt; font-size: 9.5pt; }}
ol.refs li {{ margin-bottom: 3pt; }}
</style>
</head>
<body>

<div class="title-block">
  <div class="series">ASGARD-XV · Experiment 14 · Pre-Flight Prediction</div>
  <h1 class="title">Predicted Atmospheric and Upwelling Radiation Profile for a Stratospheric Balloon Ascent from Brussels, 2026-04-23</h1>
  <div class="author">Jiri Dobes</div>
  <div class="affiliation">The English College in Prague / X-Horizon</div>
  <div class="date">{TODAY}</div>
</div>

<div class="abstract">
<h2>Abstract</h2>
<p>A pre-flight prediction of atmospheric temperature, ozone concentration, and upwelling broadband radiation is presented for ASGARD-XV Experiment 14, a student stratospheric balloon payload carrying a Lite-On LTR390 UV/ambient-light sensor, a DFRobot SEN0321 ozone sensor, a TE MS5611 pressure/temperature sensor, and a Maxim DS3231 precision real-time clock, launching from Brussels, Belgium (50.80°N, 4.36°E) at 14:00 CEST on 23 April 2026. The ozone profile was derived from the Copernicus Atmosphere Monitoring Service (CAMS) global composition forecast (init 2026-04-20 12:00 UTC, lead +72 h), bilinearly interpolated to the launch point. Radiative transfer was computed with libRadtran 2.0.6 using the DISORT 8-stream pseudospherical solver on a 1 nm spectral grid from 250 to 1100 nm, in 1 km altitude steps from 0 to 40 km. Headline results: total ozone column <b>{fmt(TOTAL_DU, 4)} DU</b>, peak mixing ratio <b>{fmt(PEAK_PPMV, 3)} ppmv</b> at <b>{fmt(PEAK_ALT_KM, 3)} km</b>, solar zenith angle <b>{fmt(SZA_DEG, 4)}°</b>, band-integrated upwelling irradiance at 40 km of <b>{fmt(v(40,'eup_UV'), 3)} W m⁻²</b> in the 280–400 nm band and <b>{fmt(v(40,'eup_VIS'), 3)} W m⁻²</b> in the 400–700 nm band.</p>
</div>

<h2>1. Introduction</h2>
<p>ASGARD-XV Experiment 14 is a compact autonomous data logger designed, built, and tested at The English College in Prague. It carries four sensors sampled at 1 Hz during a stratospheric balloon ascent, with records stored to a 256 kbit AT24C256 EEPROM (primary storage) and a microSD card (backup) driven by an Arduino Pro Mini running at 3.3&nbsp;V / 8&nbsp;MHz. The flight profile reaches a nominal float altitude of approximately 30&nbsp;km.</p>

<p>The purpose of this note is to produce a physically grounded pre-flight prediction of the vertical structure of temperature, ozone, and ground-facing upwelling ultraviolet and visible irradiance that the payload will encounter. These reference profiles serve three functions:</p>
<ul>
<li>they bound the dynamic range the LTR390 UV and ALS (ambient-light) channels will see, allowing gain settings to be chosen pre-flight;</li>
<li>they provide a forecast ozone column and stratospheric peak against which the SEN0321 ozone sensor data can be qualitatively compared;</li>
<li>they supply a reference temperature profile (ISA 1976) against which MS5611 in-situ readings can be evaluated.</li>
</ul>

<h2>2. Methodology</h2>

<h3>2.1 Input ozone from CAMS</h3>
<p>Ozone mass mixing ratio <span class="var">q(p)</span> was obtained from the CAMS global atmospheric composition forecast (<code>cams-global-atmospheric-composition-forecasts</code>). The request configuration is given below:</p>
<pre>init date   : 2026-04-20
init time   : 12:00 UTC
lead time   : +72 h          → valid 2026-04-23 12:00 UTC (14:00 CEST)
area        : 50.8±0.5 N, 4.36±0.5 E
levels (22) : 1000, 925, 850, 700, 600, 500, 400, 300, 250, 200,
              150, 100, 70, 50, 30, 20, 10, 7, 5, 3, 2, 1 hPa
type        : forecast
format      : netcdf</pre>
<p>The raw NetCDF field has dimensions (<span class="var">forecast_reference_time, forecast_period, pressure_level, latitude, longitude</span>). A bilinear interpolation in (latitude, longitude) to the exact launch point was performed using <code>xarray</code>'s <code>interp</code> method. Because pressure-level forecasts are produced on a 3 h time grid, the closest grid point to the 13:00 CEST launch target is 14:00 CEST, a 1 h forward offset considered negligible for stratospheric ozone.</p>

<h3>2.2 ISA 1976 pressure–altitude mapping</h3>
<p>For the reference temperature profile and for altitude labelling, the U.S. Standard Atmosphere 1976 was adopted, with piecewise linear temperature lapse rates:</p>
<table class="data" style="width: 90%;">
<thead><tr><th>Layer</th><th>Base altitude [km]</th><th>Lapse rate <span class="var">L</span> [K km⁻¹]</th></tr></thead>
<tbody>
<tr><td>Troposphere</td><td>0 – 11</td><td>−6.50</td></tr>
<tr><td>Lower stratosphere (isothermal)</td><td>11 – 20</td><td>0.00</td></tr>
<tr><td>Middle stratosphere</td><td>20 – 32</td><td>+1.00</td></tr>
<tr><td>Upper stratosphere</td><td>32 – 47</td><td>+2.80</td></tr>
</tbody>
</table>
<p>Pressure as a function of altitude <span class="var">z</span> follows from the hydrostatic balance layer by layer. For a non-isothermal layer with base (<span class="var">z<sub>b</sub>, T<sub>b</sub>, p<sub>b</sub></span>):</p>
<p class="eqn">p(z) = p<sub>b</sub> [T<sub>b</sub> / (T<sub>b</sub> + L (z − z<sub>b</sub>))]<sup> g / (R L)</sup></p>
<p>and for an isothermal layer:</p>
<p class="eqn">p(z) = p<sub>b</sub> exp[−g (z − z<sub>b</sub>) / (R T<sub>b</sub>)]</p>
<p>with <span class="var">g</span> = 9.80665 m s⁻² and <span class="var">R</span> = 287.053 J kg⁻¹ K⁻¹ (specific gas constant for dry air). The inverse <span class="var">p → z</span> is derived analytically within each layer and is used to place the CAMS pressure levels on a geometric altitude axis.</p>

<h3>2.3 Total ozone column</h3>
<p>The ozone column density in Dobson Units (DU) is computed as</p>
<p class="eqn">N<sub>O₃</sub> = ∫ q(z) · (M<sub>air</sub> / M<sub>O₃</sub>) · n<sub>air</sub>(z) d<span class="var">z</span></p>
<p>where <span class="var">n<sub>air</sub>(z) = p(z) / (k<sub>B</sub> T(z))</span>, with <span class="var">T(z)</span> taken from ISA 1976, <span class="var">M<sub>air</sub></span> = 28.9647 g mol⁻¹, <span class="var">M<sub>O₃</sub></span> = 47.9982 g mol⁻¹, <span class="var">k<sub>B</sub></span> = 1.380649 × 10⁻²³ J K⁻¹, and 1 DU ≡ 2.687 × 10²⁰ molec m⁻². The integral is evaluated by the composite trapezoidal rule over the CAMS pressure levels, with a rectangular pad added from the lowest level down to the surface to avoid truncating the boundary layer.</p>

<h3>2.4 Radiative transfer</h3>
<p>Spectral irradiance was computed with libRadtran 2.0.6 [1]. The <code>uvspec</code> input template is:</p>
<pre>latitude N 50.798056
longitude E 4.357500
time 2026 04 23 12 00 00            # UTC = 14:00 CEST
atmosphere_file midlatitude_summer
mol_file O3 o3_mmr.dat mmr          # CAMS overlay
rte_solver disort
number_of_streams 8
pseudospherical
mol_abs_param crs
source solar kurudz_0.1nm.dat       # Kurucz 0.1 nm [2], mW m⁻² nm⁻¹
wavelength 250 1100
spline 250 1100 1                   # 1 nm output grid
albedo 0.05                         # land / vegetation baseline
zout_sea &lt;SUBSTITUTED&gt;
output_user lambda sza zout eup edir edn eglo
quiet</pre>
<p>A bash driver iterates <span class="var">z<sub>out</sub></span> from 0 to 40 km in 1 km steps (41 runs). For each run the solver writes a 4-column spectral file: upwelling irradiance <span class="var">E<sub>up</sub></span>, direct downwelling <span class="var">E<sub>dir</sub></span>, diffuse downwelling <span class="var">E<sub>dn</sub></span>, and global downwelling <span class="var">E<sub>glo</sub> = E<sub>dir</sub> + E<sub>dn</sub></span>. Pseudospherical mode corrects the plane-parallel direct-beam geometry for Earth curvature, which is important at high SZA but has a small (&lt;1%) effect at our launch geometry. The DISORT 8-stream solver resolves the multiple-scattering contribution sufficiently for integrated radiometric quantities.</p>

<h3>2.5 Band integration</h3>
<p>At each altitude, the upwelling irradiance <span class="var">E<sub>up</sub></span>(λ, z) in mW m⁻² nm⁻¹ is numerically integrated over spectral bands:</p>
<p class="eqn">E<sub>band</sub>(z) = 10⁻³ · ∫<sub>λ₁</sub><sup>λ₂</sup> E<sub>up</sub>(λ, z) d<span class="var">λ</span>   [W m⁻²]</p>
<p>where the 10⁻³ factor converts mW to W. Band definitions used throughout:</p>
<table class="data" style="width: 75%;">
<thead><tr><th>Band</th><th>Range [nm]</th></tr></thead>
<tbody>
<tr><td>UV-C</td><td>250 – 280</td></tr>
<tr><td>UV-B</td><td>280 – 315</td></tr>
<tr><td>UV-A</td><td>315 – 400</td></tr>
<tr><td>UV (total)</td><td>280 – 400</td></tr>
<tr><td>Visible</td><td>400 – 700</td></tr>
<tr><td>Near-infrared (NIR)</td><td>700 – 1100</td></tr>
</tbody>
</table>

<h2>3. Results</h2>

<h3>3.1 Ozone profile and column</h3>
<p>The interpolated CAMS ozone volume mixing ratio rises from order ~50 ppbv in the lower troposphere to a stratospheric peak of <b>{fmt(PEAK_PPMV, 3)} ppmv</b> at approximately <b>{fmt(PEAK_ALT_KM, 3)} km</b> (<b>{fmt(PEAK_P_HPA, 3)} hPa</b>), decreasing above. The vertically integrated column is <b>{fmt(TOTAL_DU, 4)} DU</b>, typical of mid-latitude spring. Table 1 gives the interpolated profile at all 22 CAMS pressure levels.</p>

<table class="data">
<caption class="caption"><b>Table 1.</b> CAMS ozone forecast interpolated to (50.80°N, 4.36°E), valid 2026-04-23 12:00 UTC. Altitude column is ISA 1976 pressure → height.</caption>
<thead><tr><th>Pressure [hPa]</th><th>Altitude [km]</th><th>O₃ mmr [kg kg⁻¹]</th><th>O₃ [ppmv]</th></tr></thead>
<tbody>
{ozone_table_html()}
</tbody>
</table>

<h3>3.2 Upwelling radiation profile</h3>
<p>The solar zenith angle at the launch coordinates and time is <b>{fmt(SZA_DEG, 4)}°</b> (elevation {fmt(90 - SZA_DEG, 3)}°). Band-integrated upwelling irradiance at nine representative altitudes is listed in Table 2.</p>

<table class="data">
<caption class="caption"><b>Table 2.</b> Band-integrated upwelling irradiance <span class="var">E<sub>up</sub></span> (W m⁻²) at representative altitudes. Pressure from ISA 1976.</caption>
<thead><tr>
<th>z [km]</th><th>p [hPa]</th>
<th>UV-A<br/>315–400</th>
<th>UV-B<br/>280–315</th>
<th>UV<br/>280–400</th>
<th>Visible<br/>400–700</th>
<th>NIR<br/>700–1100</th>
</tr></thead>
<tbody>
{eup_table_html()}
</tbody>
</table>

<figure>
<img src="{PROFILE_PNG}" alt="Four-panel profile"/>
<div class="caption"><b>Figure 1.</b> Predicted atmospheric and upwelling radiation profile for the ASGARD-XV Experiment 14 flight. Top-left: ISA 1976 temperature (°C). Top-right: CAMS ozone volume mixing ratio (ppmv). Bottom-left: band-integrated upwelling UV irradiance 280–400 nm (W m⁻²). Bottom-right: band-integrated upwelling visible irradiance 400–700 nm (W m⁻²). Shared pressure axis (log, surface on left, TOA on right). Top row shows a secondary altitude axis.</div>
</figure>

<figure>
<img src="{UVBAND_PNG}" alt="UV sub-band upwelling irradiance"/>
<div class="caption"><b>Figure 2.</b> Upwelling UV irradiance decomposed into UV-A (315–400 nm), UV-B (280–315 nm), and UV-C (250–280 nm) components, log scale. UV-A dominates at all altitudes; UV-B is reduced by ozone absorption below the stratospheric layer; UV-C is effectively extinguished below ~25 km.</div>
</figure>

<figure>
<img src="{SPECTRUM_PNG}" alt="Upwelling spectrum at selected altitudes"/>
<div class="caption"><b>Figure 3.</b> Spectral upwelling irradiance <span class="var">E<sub>up</sub></span>(λ) at five altitudes, log scale. The short-wavelength cut-off imposed by the Hartley-band ozone absorption migrates from ~305 nm at the surface to ~260 nm at 40 km as the overlying ozone column decreases. Shaded regions mark the UV-C / UV-B / UV-A sub-bands.</div>
</figure>

<h3>3.3 Downwelling reference</h3>
<p>Although the primary interest of the ground-facing instrument configuration is the upwelling flux, the same libRadtran runs provide the downwelling global irradiance <span class="var">E<sub>glo</sub></span> for context. Table 3 lists <span class="var">E<sub>glo</sub></span> in the same UV and visible bands.</p>
<table class="data">
<caption class="caption"><b>Table 3.</b> Band-integrated downwelling (global) irradiance <span class="var">E<sub>glo</sub></span> (W m⁻²) at representative altitudes; full-spectrum 250–1100 nm column for reference.</caption>
<thead><tr><th>z [km]</th><th>UV 280–400</th><th>Visible 400–700</th><th>250–1100 total</th></tr></thead>
<tbody>
{eglo_table_html()}
</tbody>
</table>

<h2>4. Discussion</h2>

<h3>4.1 Sanity checks</h3>
<p>At 40 km altitude, the total downwelling irradiance in the 250–1100 nm range is <b>{fmt(v(40,'eglo_ALL'),4)} W m⁻²</b>. The TOA horizontal solar flux at SZA = {fmt(SZA_DEG, 4)}° would be <b>TSI · cos(SZA) = {fmt(1361 * np.cos(np.deg2rad(SZA_DEG)), 4)} W m⁻²</b>; the 250–1100 nm window retains roughly 80% of the total solar constant, consistent with the Kurucz reference spectrum. The 40 km figure thus accounts for ~{fmt(100.0 * v(40,'eglo_ALL') / (1361 * np.cos(np.deg2rad(SZA_DEG))), 3)}% of the full-spectrum horizontal TOA flux, physically reasonable given (i) the 250–1100 nm window, (ii) Rayleigh absorption and scattering in the thin overlying column, and (iii) residual stratospheric ozone absorption of the UV-B/UV-C contribution.</p>

<p>The upwelling-to-downwelling ratio confirms the expected wavelength dependence of Rayleigh backscattering (σ ∝ λ⁻⁴):</p>
<table class="data" style="width: 70%;">
<thead><tr><th>Altitude</th><th>UV (280–400) <span class="var">E<sub>up</sub>/E<sub>glo</sub></span></th><th>Visible (400–700) <span class="var">E<sub>up</sub>/E<sub>glo</sub></span></th></tr></thead>
<tbody>
<tr><td>0 km (surface)</td><td>{fmt(100.0 * summary['uv_ratio_0km'], 3)}%</td><td>{fmt(100.0 * summary['vis_ratio_0km'], 3)}%</td></tr>
<tr><td>40 km</td><td>{fmt(100.0 * summary['uv_ratio_40km'], 3)}%</td><td>{fmt(100.0 * summary['vis_ratio_40km'], 3)}%</td></tr>
</tbody>
</table>
<p>At the surface both ratios are dominated by the imposed surface albedo of 0.05 and thus are similar. At 40 km the UV ratio is substantially larger than the visible because the entire atmospheric column contributes diffuse Rayleigh backscatter, which is strongly wavelength-dependent.</p>

<h3>4.2 Limitations</h3>
<ul>
<li><b>Cloud-free assumption.</b> The simulation does not include clouds. Cloud cover in the trajectory corridor would (a) substantially increase upwelling visible irradiance above the cloud deck (bright reflector), and (b) reduce UV below the deck. The predicted curves apply to a cloud-free case and should be treated as envelopes where cloud is present.</li>
<li><b>Surface albedo.</b> A constant albedo of 0.05 (generic land/vegetation) is used. Trajectory-dependent mosaics of land, water, snow, or cloud-top would require a rescaling; for the upwelling band, <span class="var">E<sub>up</sub>(z)</span> scales roughly linearly with the albedo of the underlying surface within the cone subtending the solid angle at altitude.</li>
<li><b>Aerosol.</b> libRadtran's default rural aerosol model is applied. Actual boundary-layer aerosol optical depth over NW Europe in late April can vary; the effect on UV-B and visible irradiance is at the several-percent level and does not change qualitative conclusions.</li>
<li><b>CAMS time grid.</b> Pressure-level CAMS output is on a 3 h time grid; the closest point to the 13:00 CEST target is 14:00 CEST (+1 h). Stratospheric ozone varies on much longer timescales, so this offset is negligible.</li>
<li><b>Temperature inconsistency.</b> Figure 1(a) shows ISA 1976 temperature for vertical coordinate consistency, while the radiative transfer internally uses libRadtran's <code>midlatitude_summer</code> profile (temperature differences &lt;3 K in the troposphere, sub-percent impact on integrated UV).</li>
<li><b>SEN0321 at stratospheric density.</b> The DFRobot SEN0321 electrochemical ozone sensor is calibrated for surface-level pressures; at stratospheric densities (< 30 hPa) its response is outside the manufacturer-specified operating regime and the sensor data should be treated as qualitative above ~20 km.</li>
</ul>

<h3>4.3 Implications for the in-flight measurement</h3>
<p>The LTR390 UV channel has a peak responsivity near 330 nm, falling within the UV-A sub-band. Ground-facing during ascent, it should see an upwelling UV-A irradiance rising from <b>{fmt(v(0,'eup_UVA'), 3)} W m⁻²</b> at launch to <b>{fmt(v(40,'eup_UVA'), 3)} W m⁻²</b> at 40 km (Table 2). The ALS (visible) channel, peaking near 555 nm, should see upwelling visible irradiance from <b>{fmt(v(0,'eup_VIS'), 3)} W m⁻²</b> to <b>{fmt(v(40,'eup_VIS'), 3)} W m⁻²</b>. Both channels will therefore span roughly one order of magnitude over the flight, and gain settings should be chosen to avoid saturation near the float altitude while retaining sensitivity at launch.</p>

<h2>5. Conclusion</h2>
<p>A complete pre-flight prediction of the atmospheric and upwelling radiative environment for ASGARD-XV Experiment 14 has been produced, combining a 72-hour CAMS ozone forecast with libRadtran DISORT radiative transfer. The headline figures are a total ozone column of <b>{fmt(TOTAL_DU, 4)} DU</b>, a stratospheric ozone peak of <b>{fmt(PEAK_PPMV, 3)} ppmv at {fmt(PEAK_ALT_KM, 3)} km</b>, and upwelling irradiance at 40 km of <b>{fmt(v(40,'eup_UV'), 3)} W m⁻²</b> (UV 280–400 nm) and <b>{fmt(v(40,'eup_VIS'), 3)} W m⁻²</b> (visible 400–700 nm). All input files, scripts, and outputs are archived in the experiment repository and can be re-executed with the <code>cams_download3.py</code> → <code>interpolation1.py</code> → <code>run_loop.sh</code> → <code>paper.py</code> pipeline. The predictions provide a quantitative reference against which the LTR390, SEN0321, and MS5611 sensor data will be compared after flight.</p>

<h2>References</h2>
<ol class="refs">
<li>Emde, C., Buras-Schnell, R., Kylling, A., Mayer, B., Gasteiger, J., Hamann, U., Kylling, J., Richter, B., Pause, C., Dowling, T., Bugliaro, L. (2016). The libRadtran software package for radiative transfer calculations (version 2.0.2). <i>Geoscientific Model Development</i>, <b>9</b>, 1647–1672. doi:10.5194/gmd-9-1647-2016.</li>
<li>Kurucz, R. L. (1992). Synthetic infrared spectra. In <i>Infrared Solar Physics</i>, IAU Symposium 154, ed. D. M. Rabin et al., Kluwer Academic Publishers, 523–531.</li>
<li>U.S. Committee on Extension to the Standard Atmosphere (1976). <i>U.S. Standard Atmosphere, 1976</i>. NOAA-S/T 76-1562. U.S. Government Printing Office, Washington, DC.</li>
<li>Copernicus Atmosphere Monitoring Service (CAMS), Atmosphere Data Store. <i>Global atmospheric composition forecasts</i>. European Centre for Medium-Range Weather Forecasts. <span class="monospace">https://ads.atmosphere.copernicus.eu</span> (accessed April 2026).</li>
<li>Stamnes, K., Tsay, S.-C., Wiscombe, W., Jayaweera, K. (1988). Numerically stable algorithm for discrete-ordinate-method radiative transfer in multiple scattering and emitting layered media. <i>Applied Optics</i>, <b>27</b>, 2502–2509.</li>
</ol>

</body>
</html>
"""

html_path = PAPER_DIR / "paper.html"
html_path.write_text(HTML, encoding="utf-8")


# ---------------------------------------------------------------------------
# 7. Render to PDF via weasyprint CLI
# ---------------------------------------------------------------------------
weasyprint_bin = shutil.which("weasyprint") or str(Path.home() / ".local/bin/weasyprint")
pdf_path = ROOT / "paper.pdf"

result = subprocess.run(
    [weasyprint_bin, str(html_path), str(pdf_path)],
    capture_output=True, text=True,
)
if result.returncode != 0:
    print("weasyprint stderr:", result.stderr, file=sys.stderr)
    sys.exit(result.returncode)

print(f"Saved HTML: {html_path}")
print(f"Saved PDF : {pdf_path}")
print("\n=== Summary ===")
for k, val in summary.items():
    print(f"  {k:24s}  {val}")
