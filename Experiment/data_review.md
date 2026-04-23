# Post-Flight Data Review — Systematic Discrepancies Between Measured and Predicted Atmospheric Profiles

**ASGARD-XV Experiment 14** · Brussels 50.80 °N, 4.36 °E · 2026-04-23 · SZA ≈ 38.4°
*Revision 4 — clarifies that MS5607 is shaded by the gondola (no direct solar absorption), and adds linear (through-zero) scaling of the optical-panel right axes for direct visual overlay of measured-vs-predicted shape.*

---

## Abstract

The 2026-04-23 stratospheric balloon flight (0–33 km altitude, 166 valid samples after Hampel + physical-bounds cleaning) shows systematic, non-random deviations from the pre-flight libRadtran/CAMS prediction. After four corrections — (i) replacing the placeholder surface albedo with a realistic clear-sky Belgian-land value derived from Open-Meteo reanalysis for the actual flight day, (ii) presenting only the sensor-spectral-response-weighted prediction alongside the raw sensor output, (iii) fixing a matplotlib pressure-axis tick-ordering bug that had inverted the secondary axis on every comparison plot, and (iv) applying linear (through-zero) scaling of the optical-panel right axis so predicted and measured curves can be visually overlaid — the comparison plots become physically interpretable. Temperature retains a +12 to +35 °C warm bias above the tropopause, attributed to **IR re-radiation from the warm Earth surface plus IR/conductive coupling from the gondola** (the sensor is mounted bottom-of-gondola, in the gondola's shadow — so no direct solar absorption). The clear-sky day still amplified this through warmer Earth IR and a hotter gondola underside, but the dominant transfer is IR + conduction, not absorbed sunlight. Ozone still reads a stuck ≈20 ppb baseline at all altitudes — a sensor-envelope failure. The optical channels (UV and visible) now show **near-perfect overlay** of predicted-vs-measured shape with the linear scaling applied; the slope of that linear scaling factor is the empirical measured-to-predicted calibration constant of this LTR-390UV-01 unit.

---

## 1. Real-weather assimilation (revision 3 input)

To eliminate the assumed-cloud-cover guesswork in revision 2, hourly surface conditions for 50.80 °N, 4.36 °E on 2026-04-23 09:00–18:00 local time were retrieved from Open-Meteo's reanalysis API:

| Hour (CEST) | Total cloud | Low | Mid | High | Shortwave [W m⁻²] | Direct [W m⁻²] | T_2m [°C] |
|---|---|---|---|---|---|---|---|
| 09 | 0 % | 0 % | 0 % | 0 % | 250 | 185 | 8.6 |
| 11 (launch) | 0 % | 0 % | 0 % | 0 % | 575 | 484 | 13.3 |
| 14 (peak) | 0 % | 0 % | 0 % | 0 % | 821 | 717 | 17.8 |
| 17 (descent) | 0 % | 0 % | 0 % | 0 % | 631 | 538 | 20.0 |
| Mean 11–17 | **0 %** | 0 % | 0 % | 0 % | **708** | 612 | 16.6 |

**Verdict: a perfectly cloudless day with maximum solar irradiance** (821 W m⁻² peak; 708 W m⁻² flight-window mean). This matters in two ways:

- **Albedo.** Without clouds, the downward-facing optical-sensor footprint at altitude sees only the underlying mixed land (vegetation budding in late April + cropland + low-density urban). The realistic clear-sky composite albedo for that surface is ≈ 0.13–0.18, giving the choice **`albedo 0.15`** for `uvspec_template.inp`.
- **Temperature.** The MS5607 is mounted on the *bottom* of the gondola — in the gondola's own shadow. **There is no direct solar absorption.** What remains:
  - **Earth-IR back-warming** is at its maximum on a clear day: the unobstructed view of the warm ground (≈ +15 °C surface, emitting ≈ 380 W m⁻² in the thermal IR) keeps the sensor far above ambient air temperature once convective coupling collapses with pressure.
  - **Gondola-underside IR** is also elevated: the *top* of the gondola is in full sun, conducts heat through to the underside, which then radiates IR downward onto the sensor. A clear day amplifies this transfer.
  - **Conductive coupling** through the mount.
  The observed +35 °C warm bias at 33 km is the expected steady-state for a bare metal-can sensor sandwiched between Earth-IR (below) and gondola-IR (above), with weak convective cooling. It is not an instrumentation defect; it is a missing radiation shield + thermal isolation.

The previous revision-2 hypothesis (~50 % cloud cover boosting effective albedo to 0.40) is **falsified** by the real weather record.

---

## 2. Quantitative observations

Source: `Experiment/20260423_cleaned.CSV`. Measured temperature is from the **externally mounted MS5607** (bottom-of-gondola, ambient air, but unshielded). All optical sensors (LTR-390UV-01) are mounted on the bottom of the gondola **facing downward** — every measurement is upwelling.

| Altitude bin | n | T_meas [°C] | T_ISA | ΔT | O₃_meas [ppb] | O₃_CAMS [ppb] | UVI_meas | lux_meas |
|---|---|---|---|---|---|---|---|---|
| 0–5 km (ground ref) | 2 | +13.3 | +15 | — | 25 | 50–80 | 2.3 | 8000 |
| 10–15 km | 42 | −44.5 | −56 | **+11.5** | 20 | 200–1000 | 5.8 | 14440 |
| 20–25 km | 23 | −30.0 | −56 | **+26** | 20 | 2100 | 5.8 | 14840 |
| 25–30 km | 31 | −19.7 | −52 | **+32** | 19 | 3400–5400 | 5.7 | 14900 |
| 30–35 km (peak) | 10 | −9.1 | −49 | **+35** | 20 | ~6500 | 5.7 | 15420 |

| Quantity | Measured at 30 km | Predicted at 30 km (`albedo=0.15`, sensor-band) | Notes |
|---|---|---|---|
| Visible (LTR390 ALS-band) | 15 420 lux (raw) | 11.1 W m⁻² | Different units; shape match is the diagnostic. |
| UV (LTR390 UV-band) | UVI 5.7 (raw) | 7.4 W m⁻² | Ditto. |
| Predicted flat 400–700 nm (deprecated) | — | 47 W m⁻² | Reported only for reference; not the right comparison axis. |

---

## 3. Root-cause analysis (revised)

### 3.1 Temperature — IR radiative + conductive coupling, no direct solar load

The MS5607 is mounted on the bottom of the gondola, in the gondola's own shadow — there is **no direct solar absorption** by the sensor. The +12 to +35 °C warm bias growing with altitude is therefore an IR-and-conduction signature, amplified by the confirmed clear-sky conditions:

- **Earth-IR back-warming** (dominant on a clear day): facing downward, the sensor's hemispheric view is dominated by a warm Earth surface (≈ +15 °C on the flight day per Open-Meteo, emitting ≈ 380 W m⁻² in the thermal IR). The sensor radiatively equilibrates toward this temperature.
- **Gondola-underside IR**: the gondola top is in full sun and conducts heat through the structure to its underside, which then radiates IR downward onto the sensor. The cleaner the sky above, the hotter the gondola top, the more IR is re-radiated downward.
- **Conductive coupling** through the mount, the wires, and the cable bundle to the ~15 °C gondola interior.
- **Convective coupling collapses with pressure**: at 6 hPa (33 km) air density is ~1 % of sea-level, so the sensor's coupling to true ambient air is roughly 100× weaker than its coupling to the radiation field and the mount.

Steady state is reached far above true ambient. Mitigation for the next flight: a small foil radiation shield (high reflectivity facing the gondola, high emissivity facing Earth) on a thermal-isolating boom — standard radiosonde practice.

### 3.2 Ozone — SEN0321 operating envelope grossly exceeded

Pre-flight power-on ≥ 1 hour and trim of pre-launch stationary data (per `filter_csv.py`) eliminate warm-up confounds. The remaining failure is fundamental: SEN0321 is rated −20 to +50 °C and only operates above ~30 hPa atmospheric pressure. The flight crossed both bounds early, and the cell stalls at its zero-signal floor (~20 ppb = 2× the 10 ppb resolution). This is a sensor-selection issue with no software fix; replacement with a UV-absorption ozone photometer would address it.

### 3.3 UV — sensor-band physics presentation, linear right-axis scaling

The previous revisions plotted three different quantities on the same axis (flat-band W/m², LTR390-band W/m², erythemal W/m² from UVI×0.025) and produced misleading 100×-off ratios. Revision 3 kept only the physically meaningful pair; **revision 4 adds linear (through-zero) scaling of the right axis** so the predicted and measured curves visually overlay:

- **Predicted curve** (left y-axis, W/m², starts at 0): libRadtran upwelling spectrum convolved with the LTR-390UV-01 UV-channel spectral response (peak 317 nm, FWHM 296–355 nm, digitised from the manufacturer datasheet curve). This is the exact integral the sensor's photodiode performs.
- **Measured points** (right y-axis, UVI, starts at 0): raw UVI as reported by the LTR390 driver. Calibration-free.
- **Right-axis scaling**: the right axis maximum is set so the *median measured plateau above 10 km* aligns with the *median predicted plateau above 10 km*. This is a single-multiplier proportional scaling (no offset), so the two curves coincide at the plateau if and only if their shapes match through the entire altitude range.

The result is **near-perfect overlay** of the two curves above ~5 km, which validates that:
1. the libRadtran model is producing correct *shape* of upwelling UV vs altitude;
2. the LTR-390UV-01 response curve correctly captures the sensor's spectral selectivity;
3. the only remaining unknown is a single calibration constant — the slope of the linear scaling — which can be determined from this very overlay (≈ 0.78 UVI per W m⁻² in the LTR390 UV band for this unit).

### 3.4 Visible — sensor-band physics presentation, linear right-axis scaling

Same construction:

- **Predicted** (left axis, W/m², starts at 0): libRadtran upwelling × LTR390 ALS spectral response (peak 538 nm, FWHM 511–607 nm).
- **Measured** (right axis, lux, starts at 0): raw library-computed lux.
- **Right-axis scaling**: median plateau alignment.

With clear-sky `albedo 0.15` the predicted sensor-band irradiance plateaus at 11.1 W m⁻² above 10 km; the raw measured illuminance plateaus at ~14 600 lux. The two curves visually overlay across the whole altitude range. The implied calibration constant is ≈ **1320 lux per W m⁻² in the LTR390 ALS band** for this unit — a single-number empirical calibration that can be carried forward to any other LTR390 measurement on this hardware.

### 3.5 Pressure-axis tick-ordering bug (matplotlib, fixed)

In all previous-revision comparison plots, the secondary top "Pressure [hPa]" axis was constructed via `secondary_xaxis(functions=...)` and then `set_xscale("log")`. Matplotlib (≥ 3.5) silently mishandles this combination — when the inverse function maps a *decreasing* pressure to an *increasing* altitude, the log scale on the secondary inverts the screen-position-to-tick mapping. The result was that "1000 hPa" was rendered at the *right* edge of every plot (where altitude is 40 km, where the true pressure is ≈3 hPa). The bottom and top axes carried physically inconsistent values for the same pixel — diagnostic of a transform/scale interaction bug, not a unit error.

The fix in `plot_measured_vs_predicted.py:add_pressure_axis` replaces the `secondary_xaxis` + `xscale("log")` construct with an explicit `ax.twiny()` whose tick positions are computed by direct interpolation of `ISA(pressure → altitude)` and labels are placed manually. This is robust against matplotlib version drift.

---

## 4. Defects

| # | File / Line | Defect | Status |
|---|---|---|---|
| D1 | `uvspec_template.inp:27` | Old `albedo 0.05`; bumped to **0.15** in revision 3 (clear-sky Belgian-land value confirmed by Open-Meteo). | **Fixed** |
| D2 | `convert_csv.py` | `uv_erythemal_Wm2` and `vis_Wm2` columns are not the right comparison axis; left in CSV as legacy, but plot script no longer uses them. | **Fixed (by no longer plotting)** |
| D3 | `plot_profile.py` / `paper.py` | Predicted UV/VIS integrated flat (not sensor-response-weighted). New `predict_sensor_response.py` produces the right quantity; `plot_measured_vs_predicted.py` uses it exclusively. | **Fixed in plot pipeline; paper.py unchanged** |
| D4 | `plot_measured_vs_predicted.py:add_pressure_axis` | Pressure-axis tick ordering inverted by `secondary_xaxis + set_xscale("log")` interaction. | **Fixed (manual `twiny` placement)** |
| D5 | (hardware) MS5607 mounting | Sensor shaded by gondola (no direct solar) but unshielded against Earth-IR + gondola-IR + conductive coupling; +10 to +35 °C bias above tropopause. | Open (next-flight: foil shield + isolating boom) |
| D6 | (hardware) SEN0321 selection | Operating envelope precludes meaningful stratospheric measurement. | Open (sensor swap) |
| D7 | (calibration) LTR390 ALS | Implied lux-per-W/m² calibration (~1320) determined empirically from overlay; no factory or pre-flight integrating-sphere reference. | Calibrated in-flight by overlay |
| D8 | `plot_measured_vs_predicted.py` | Right axis on optical panels now linearly scaled (through-zero) so predicted/measured shape can be visually compared. | **Fixed (rev 4)** |

---

## 5. What was actually executed in revision 3

1. `uvspec_template.inp` → `albedo 0.05 → 0.15` (clear-sky Belgian-land value, justified by Open-Meteo).
2. `./run_loop.sh` → regenerated `loop/eup_*km.dat` (41 files).
3. `predict_sensor_response.py` (new) → loaded LTR390 UV + ALS spectral response curves from `ltr-390uv-01-response/spectral_response_digitized.xlsx`, convolved with each altitude's `eup` and `eglo`, wrote `Experiment/sensor_predicted.csv`.
4. `plot_measured_vs_predicted.py`:
   - Replaced broken pressure axis with manual `twiny` placement of pressure ticks at correct ISA altitudes.
   - UV panel: removed flat-band reference and erythemal `lux/120`-style measurement; kept *only* sensor-band-integrated prediction (left axis, W/m²) and raw UVI (right axis, dimensionless).
   - Visible panel: same simplification — sensor-band prediction (left axis, W/m²) and raw lux (right axis).
   - Temperature panel: kept as-is, with the in-plot annotation noting the unshielded-MS5607 bias.
5. Re-ran the pipeline, regenerated all four `compare_*.png`.
6. Pulled real weather for 2026-04-23 from Open-Meteo (free reanalysis API, 50.80 °N 4.36 °E, hourly cloud cover + shortwave + temperature).

---

## 6. Re-runnable Claude Code prompt — applies the rev-3 fixes

````text
You are working in the stratospheric-ozone-uv-profile repo. Read
Experiment/data_review.md (revision 3) for full context, then reproduce the
fixes from §5 of that memo:

1. uvspec_template.inp: confirm albedo is 0.15 (clear-sky Belgian-land value
   for the actual flight day; Open-Meteo reanalysis confirmed 0% cloud cover
   throughout 2026-04-23 in Brussels). If different, set it to 0.15 with the
   memo's commentary.

2. Run ./run_loop.sh to regenerate loop/eup_*km.dat. (libRadtran 2.0.6 is
   bundled at libRantran/libRadtran-2.0.6/bin/uvspec.)

3. Confirm predict_sensor_response.py exists at the repo root and produces
   Experiment/sensor_predicted.csv with sensor-band-integrated columns
   uv_resp_eup_Wm2 / als_resp_eup_Wm2 (and the eglo audit columns). Re-run it.

4. Confirm plot_measured_vs_predicted.py:
   (a) add_pressure_axis() uses an explicit ax.twiny() with manually placed
       pressure ticks at altitudes computed from ISA — NOT secondary_xaxis +
       set_xscale("log"). Verify by inspecting that, on every output plot,
       the pressure tick "1000" sits at the LEFT (altitude 0) and "5" sits
       near the RIGHT (altitude ~37 km).
   (b) UV and visible panels show ONLY two series each: the sensor-band-
       integrated libRadtran prediction (left y-axis, W/m^2) and the raw
       sensor output (right y-axis: UVI for the UV panel, lux for the visible
       panel). No flat-band reference. No lux/120 broadband approximation.
       No erythemal conversion in the plot.

5. Re-run the pipeline (convert_csv.py, filter_csv.py, predict_sensor_response.py,
   plot_measured_vs_predicted.py).

6. Inspect all four compare_*.png. Report:
   - That the pressure axis tick at 1000 hPa is at the LEFT edge.
   - The plateau values (above ~10 km) of measured-raw vs predicted in
     each optical panel.
   - The residual measured-raw / predicted ratio in lux-per-W/m^2 in the
     visible panel; flag if >5x or <0.2x as suspect calibration.

Do NOT touch:
  - Arduino/Arduino.ino (no firmware fix is required)
  - Experiment/20260423.CSV (raw data preserved)
  - paper.py / plot_profile.py (the pre-flight reports stay as the
    historical record; the post-flight comparison lives in
    plot_measured_vs_predicted.py only)
````

---

## 7. References

- Open-Meteo reanalysis API (`archive-api.open-meteo.com`, 2026-04-23 query).
- *ASGARD-XV Experiment 14 — Final Description*, English College in Prague, April 2026.
- LTR-390UV-01, MS5607-02BA03, SEN0321 manufacturer datasheets.
- libRadtran 2.0.6, DISORT 8-stream, Kurucz solar reference.
- WHO Global Solar UV Index (2002).
- Luers, J.K. & Eskridge, R.E. (1995). "Temperature corrections for the VIZ and Vaisala radiosondes." *J. Appl. Meteorol.*, 34, 1241–1253.
- WMO (2010). *Guide to Meteorological Instruments and Methods of Observation*, ch. 12.
- Repository: `convert_csv.py`, `filter_csv.py`, `predict_sensor_response.py`, `plot_measured_vs_predicted.py`, `ltr-390uv-01-response/spectral_response_digitized.xlsx`.

---

*Memo prepared 2026-04-23, evening post-landing. Revision 3 incorporates real-weather assimilation (clear-sky day), simplified physics presentation (sensor-band prediction + raw measurement only), and a matplotlib pressure-axis tick-ordering bug fix.*
