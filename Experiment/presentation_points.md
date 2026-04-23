# Data Analysis — From Raw Arduino CSV to `compare_*.png`

**Flight:** ASGARD-XV Exp 14 · Brussels 50.80 °N, 4.36 °E · 2026-04-23 · SZA ≈ 38.4°
**Inputs:** `Experiment/20260423.CSV` (raw SD log, no header) + libRadtran pre-flight simulation
**Outputs:** `compare_temperature.png`, `compare_ozone.png`, `compare_uv.png`, `compare_visible.png`

---

## 1. Updates in assumptions (pre-flight → post-flight model)

- **Surface albedo: 0.05 → 0.15** (`uvspec_template.inp:32`). The 0.05 placeholder (open-ocean / dark asphalt) was physically wrong for a Belgian land overflight. Open-Meteo reanalysis for 2026-04-23 over Brussels confirmed **0 % cloud cover all day** (peak 821 W/m² shortwave at 14:00 CEST), so the downward-facing sensor footprint sees only mixed spring land (vegetation budding + cropland + low-density urban) → realistic composite albedo ≈ 0.13–0.18.
- **Falsified earlier hypothesis** that ~50 % cloud cover was boosting *effective* albedo to 0.40. The real weather record ruled that out.
- **Sensor viewing geometry re-stated**: LTR-390UV-01 is mounted bottom-of-gondola **facing down** → every optical measurement is **upwelling**, not downwelling. All comparisons now use libRadtran's `eup` column, not `edn`/`eglo`.
- **MS5607 thermal boundary condition clarified**: sensor is **shaded by the gondola** (no direct solar absorption). The observed warm bias is therefore purely **Earth-IR back-warming + gondola-underside IR + conductive coupling through the mount** — not absorbed sunlight. Corrects a revision-2 misattribution.
- **Spectral presentation assumption changed**: predicted UV / visible must be **convolved with the LTR-390UV-01 spectral response** (UV: peak 317 nm, FWHM 296–355 nm; ALS: peak 538 nm, FWHM 511–607 nm) before comparison — flat band-integrated W/m² is not the quantity the sensor actually reports.

---

## 2. Updates in theoretical results (libRadtran outputs)

- **Regenerated all 41 altitude steps** via `./run_loop.sh` → `loop/eup_{0..40}km.dat` with the new albedo = 0.15 and the clear-sky midlatitude-summer atmosphere.
- **Upwelling UV (LTR390 UV band, `predict_sensor_response.py`)**: grows from **2.3 W/m² at ground → 7.5 W/m² asymptote above ~20 km** (previously underestimated by the 0.05 albedo placeholder).
- **Upwelling visible (LTR390 ALS band)**: **12.6 W/m² at ground → ~11.1 W/m² plateau above 10 km** (roughly flat with altitude, as expected for upwelling from a diffuse land surface).
- **Deprecated the old "flat 400–700 nm" prediction (47 W/m²)** — it was ~4× too high because it ignored the sensor's narrow ALS passband. Kept in the memo for reference only.
- **Ozone profile unchanged**: CAMS forecast remains the dominant input (stratospheric peak ~6500 ppb near 30 km); the SEN0321 measurement is unusable (see §3) so there is no reason to re-fit.
- **ISA 1976 temperature profile unchanged**: used as the theoretical baseline against measured MS5607; extends to 47 km via the piecewise lapse-rate model (`plot_measured_vs_predicted.py:49-58`).

---

## 3. Postprocessing of the data (raw CSV → `compare_*.png`)

### Stage A — `convert_csv.py`: byte-clean & unit conversion
- Stripped 0xFF filler bytes from one corrupted SD row (abrupt mid-write truncation).
- Parsed the 10-column Arduino log with per-sensor validity bits (`FLAG_UVS_OK`, `FLAG_ALS_OK`, `FLAG_MS5607_OK`, `FLAG_O3_OK`).
- Derived 4 physical columns: `isa_alt_km` (pressure → altitude via ISA 1976), `o3_ppmv`, `uv_erythemal_Wm2` (legacy), `vis_Wm2` (legacy). Invalid-flag rows → NaN.
- Output: `Experiment/20260423_converted.CSV` (~54 kB, 14 columns).

### Stage B — `filter_csv.py`: clean & trim to flight window
- **Step 1** physical-bounds clipping (e.g. `pressure 0–1100 hPa`, `temp −70…+50 °C`, `ozone 0–500 ppb`, `als ≤ 262 142` to drop 2¹⁸−1 saturation).
- **Step 2** per-sensor Hampel rolling filter (median ± k · 1.4826 · MAD; windows 7–15, k = 3–4) → spike rejection without smoothing the signal.
- **Step 3** trim stationary ground tails: keep only rows with altitude > 1 km, plus 2 padding rows each side.
- **Step 4** recompute derived columns from the cleaned sources.
- Output: `Experiment/20260423_cleaned.CSV` (**166 valid samples, 0–33 km**).

### Stage C — `predict_sensor_response.py`: spectral convolution
- Loaded digitised LTR-390UV-01 response curves from `ltr-390uv-01-response/spectral_response_digitized.xlsx`, normalised each channel to peak = 1.
- For each `loop/eup_{z}km.dat` (z = 0…40 km): interpolated response onto libRadtran's 1-nm grid, band-weighted the upwelling spectrum (`np.trapezoid(flux · R, λ)`), converted mW/m²/nm → W/m².
- Output: `Experiment/sensor_predicted.csv` (41 rows × 6 cols — the only honest comparison axis for LTR390).

### Stage D — `plot_measured_vs_predicted.py`: overlay & scaling
- **Four figures, shared pressure-axis helper** with manual `ax.twiny()` placement at ISA altitudes (fixes a matplotlib ≥ 3.5 bug where `secondary_xaxis + set_xscale("log")` silently inverted the top axis — previously "1000 hPa" rendered at 40 km).
- **compare_temperature.png** — ISA line vs MS5607 scatter; in-plot caveat about the unshielded-sensor warm bias (+12 … +35 °C above the tropopause).
- **compare_ozone.png** — CAMS profile vs SEN0321 scatter; SEN0321 stalls at ~20 ppb floor (operating envelope exceeded — sensor-selection failure, no software fix).
- **compare_uv.png / compare_visible.png** — **dual-axis** with **linear through-zero scaling**: left axis = predicted W/m² in the sensor band; right axis = raw UVI / raw lux, with ymax chosen so the *median plateau above 10 km* matches the predicted plateau. Since the scaling is a single multiplier (no offset), the curves overlay everywhere if and only if shapes match.
- **Empirical calibration constants falling out of the overlay**:
    - LTR390 UV channel: **≈ 0.78 UVI per W/m²** in the LTR390 UV band.
    - LTR390 ALS channel: **≈ 1320 lux per W/m²** in the LTR390 ALS band.

---

## 4. Key take-aways for the presentation

- **Optical channels (UV + visible): near-perfect shape overlay above 5 km** → libRadtran model is correct, LTR390 spectral response is correctly captured; the only unknown is a single multiplicative calibration constant, **which this flight itself produced**.
- **Temperature: systematic +12 … +35 °C warm bias** above the tropopause, explained by Earth-IR + gondola-IR + conductive coupling at low convective density. Mitigation = foil radiation shield on a thermally isolating boom (standard radiosonde practice).
- **Ozone: SEN0321 unusable above ~30 hPa / below −20 °C** — operating envelope grossly exceeded; next flight needs a UV-absorption ozone photometer.
- **One matplotlib transform bug** (pressure-axis inversion) was silently corrupting every previous comparison plot — now fixed with explicit tick placement.

---

*Compiled 2026-04-23 from `Experiment/data_review.md` (rev. 4). For the full root-cause discussion see §3 of that memo.*
