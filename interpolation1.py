import xarray as xr
import numpy as np
import pandas as pd
from pathlib import Path

lat = 50.798056
lon = 4.357500

ds = xr.open_dataset("cams_o3_profile_20260115_0000.nc", decode_timedelta=False)

o3 = ds["go3"]  # ozone mass mixing ratio (kg/kg)

# Interpolate to your exact point
o3_point = o3.interp(latitude=lat, longitude=lon)

# Keep only ONE instant:
# leadtime=0 and single forecast_reference_time -> take index 0 for both dims
o3_profile = o3_point.isel(forecast_reference_time=0, forecast_period=0)

# Now it should be 1D over pressure_level only
# Convert kg/kg -> ppmv (approx)
o3_ppmv = o3_profile * 0.603 * 1e6

# Pressure levels are in hPa
p_hpa = o3_profile["pressure_level"].values.astype(float)

def pressure_hpa_to_alt_km_isa(p_hpa_values: np.ndarray) -> np.ndarray:
    """
    Convert pressure (hPa) to geometric altitude (km) using the ISA (1976) piecewise
    temperature profile up to 47 km:
      - 0–11 km:   L = -6.5 K/km
      - 11–20 km:  isothermal
      - 20–32 km:  L = +1.0 K/km
      - 32–47 km:  L = +2.8 K/km

    This is a *much* better pressure->height mapping for stratospheric work than the
    common single-formula troposphere approximation.
    """
    # Constants
    g0 = 9.80665  # m/s^2
    R = 287.05287  # J/(kg·K) specific gas constant for dry air

    p0_hpa = 1013.25
    T0 = 288.15  # K

    # Layer bases (meters) and lapse rates (K/m)
    hb = np.array([0.0, 11000.0, 20000.0, 32000.0, 47000.0], dtype=float)
    L = np.array([-0.0065, 0.0, 0.0010, 0.0028], dtype=float)

    # Precompute base temperature/pressure at each layer boundary
    Tb = np.zeros(hb.shape, dtype=float)
    Pb_hpa = np.zeros(hb.shape, dtype=float)
    Tb[0] = T0
    Pb_hpa[0] = p0_hpa

    for i in range(L.shape[0]):
        dz = hb[i + 1] - hb[i]
        if L[i] == 0.0:
            Tb[i + 1] = Tb[i]
            Pb_hpa[i + 1] = Pb_hpa[i] * np.exp(-g0 * dz / (R * Tb[i]))
        else:
            Tb[i + 1] = Tb[i] + L[i] * dz
            Pb_hpa[i + 1] = Pb_hpa[i] * (Tb[i] / Tb[i + 1]) ** (g0 / (R * L[i]))

    p = np.asarray(p_hpa_values, dtype=float)
    if np.any(p <= 0.0):
        raise ValueError("All pressures must be > 0 hPa.")

    z_m = np.full(p.shape, np.nan, dtype=float)

    # Invert p->z, layer by layer (valid for p between boundary pressures)
    for i in range(L.shape[0]):
        p_top = Pb_hpa[i + 1]
        p_base = Pb_hpa[i]
        in_layer = (p <= p_base) & (p >= p_top)
        if not np.any(in_layer):
            continue

        if L[i] == 0.0:
            z_m[in_layer] = hb[i] - (R * Tb[i] / g0) * np.log(p[in_layer] / p_base)
        else:
            exponent = -R * L[i] / g0
            z_m[in_layer] = hb[i] + (Tb[i] / L[i]) * ((p[in_layer] / p_base) ** (exponent) - 1.0)

    # For pressures lower than the top boundary (above 47 km), do a simple extrapolation
    # using the top-layer lapse rate (keeps the function usable if CAMS provides <0.3 hPa).
    above_top = p < Pb_hpa[-1]
    if np.any(above_top):
        i = L.shape[0] - 1
        p_base = Pb_hpa[i]
        exponent = -R * L[i] / g0
        z_m[above_top] = hb[i] + (Tb[i] / L[i]) * ((p[above_top] / p_base) ** (exponent) - 1.0)

    return z_m / 1000.0


z_km = pressure_hpa_to_alt_km_isa(p_hpa)

df = pd.DataFrame({
    "alt_km_approx": z_km,
    "pressure_hPa": p_hpa,
    "ozone_kgkg": o3_profile.values,
    "ozone_ppmv": o3_ppmv.values
}).sort_values("alt_km_approx")

print(df.to_string(index=False))


def write_o3_mmr_dat_pressure(
    p_hpa_values: np.ndarray,
    o3_mmr_kg_per_kg_values: np.ndarray,
    output_path: Path,
) -> None:
    """
    Write a libRadtran mol_file for ozone using PRESSURE as vertical coordinate.

    Format:
      p_hPa   O3_mmr_kg_per_kg

    Pressure must be monotonically decreasing (top → bottom or bottom → top
    is fine; libRadtran detects ordering).
    """
    p = np.asarray(p_hpa_values, dtype=float)
    o3 = np.asarray(o3_mmr_kg_per_kg_values, dtype=float)

    if p.shape != o3.shape:
        raise ValueError("Pressure and O3 arrays must have the same shape.")

    # libRadtran is happiest if pressure is monotonic
    sort_idx = np.argsort(p)[::-1]  # descending pressure (surface → top)
    p = p[sort_idx]
    o3 = o3[sort_idx]

    output_path.parent.mkdir(parents=True, exist_ok=True)

    header = "# p_hPa   O3_mmr_kg_per_kg\n"
    with output_path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(header)
        for p_hpa, o3_mmr in zip(p, o3, strict=False):
            f.write(f"{p_hpa:10.3f} {o3_mmr:.10e}\n")


o3_mmr_output_path = Path("o3_mmr.dat")

write_o3_mmr_dat_pressure(df["pressure_hPa"].to_numpy(), df["ozone_kgkg"].to_numpy(), o3_mmr_output_path)



