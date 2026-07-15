# SQM: raw-green photometry with self-calibrating black level, color term, and wing correction

The shipped SQM was computed on the 8-bit processed display image with a static
pedestal constant. It wandered 0.7–2.4 mag within a night as auto-exposure moved,
and shifted with focus and sensor swaps. We redesigned it to be self-calibrating:
every correction is either measured from the frame stream itself or is a fixed
property of the sensor — no hand-tuned absolute constant.

The plate-solving path is untouched: solving stays on the processed image
(bare sensors keep their NIR sensitivity for solving); only SQM photometry moves
to the raw frame.

## The decision, in four parts

1. **Photometry on the raw green channel** (`sqm_use_raw_green` in the camera
   profile). The processed image's clipping, 8-bit quantisation and resize break
   the flux linearity photometry needs. For Bayer sensors the green channel is
   the mean of the two green sites; solve centroids are scaled from the 512-px
   processed frame to green-frame pixels. If the raw frame is unavailable the
   SQM cycle is **skipped**, never computed on the processed image with the raw
   profile.

2. **Black level from a per-frame joint fit** (`PedestalEstimator`). Auto-exposure
   sweeps exposure continuously, so fitting `background = P0 + rate·exposure`
   over a rolling window recovers the true black level `P0` (glossary: this is
   the *bias offset*; the fitted slope is the dark-current term and is discarded,
   never subtracted). A static constant that misses the true black level is what
   made SQM exposure-dependent. The fit refuses to run until the exposure range
   spans ≥2×; the profile `bias_offset` is the fallback.

3. **Color term** `V − T·(B−V)` per matched star (B−V from Hipparcos by HIP id).
   The catalog magnitude is Johnson V but the sensor passband is not: bare color
   sensors leak NIR, over-fluxing red stars. `T` is per-sensor
   (`color_coefficient`): 0.8 measured on-sky for bare imx462/imx290, 0.0 for
   HQ (factory IR-cut; measured −0.05 ≈ 0), 0.0 *placeholder* for the imx296
   mono (unmeasured — no working unit available). This is an instrumental
   passband match — the same thing a hardware SQM meter's fixed spectral
   response does — and is distinct from the atmospheric correction that
   ADR-0002 keeps out of the published value.

4. **Wing correction** (`WingEstimator`). Curve-of-growth measurement on the
   sweeps showed the r=5 px aperture misses 25–38% of each star's flux in the
   lens-halo wings, biasing `mzero` low and SQM bright by 0.3–0.5 mag — the
   dominant absolute error. The estimator finds each star's wing boundary by
   growing rings until the profile flattens, measures the aperture's enclosed
   fraction `f`, smooths `f` in a rolling window, and applies `−2.5·log10(f)`
   to `mzero` on every frame. The **measure/smooth/apply split is load-bearing**:
   wings sink below the noise at short exposures, so a per-frame correction
   re-introduces the exposure dependence (measured: exposure slopes up to
   −1.2 mag/dex and 3–6× worse scatter).

5. **Robust mzero.** The zero point is the **median** of the per-star zero
   points, not a flux-weighted mean, and stars peaking above 70% of full scale
   are excluded (CMOS response bends well before hard clip). A flux-weighted
   mean concentrates the vote in the brightest stars — exactly the ones prone
   to nonlinearity and to colour-term extrapolation (B−V lookups are clamped
   to ≤1.2 for the same reason). One near-saturated red giant dragged a
   night's SQM by 0.5 mag under flux weighting; the median is unmoved
   (validated: night-to-night spread 0.63 → 0.06 mag on the imx462 sweeps).

## Considered and rejected

- **IR-cut filter (hardware):** clobbers the NIR sensitivity plate-solving
  depends on, and thousands of devices are already in the field.
- **Per-sensor zero-point constant** (additive mag offset calibrated against a
  reference meter): implemented, then removed. It rested on 3 hand-read meter
  points per sensor, and the residual it papered over turned out to be the wing
  loss (correctable from data) plus night-to-night reference scatter (not a
  sensor property). A constant cannot represent either.
- **Per-frame adaptive apertures** (radius ∝ HFD): wings extend far beyond any
  HFD-scaled radius, and the correction becomes exposure-dependent.
- **Low-percentile / minimum annulus background:** order statistics of a noisy
  sky sit below truth by a noise-dependent amount, and noise varies with
  exposure — measured slopes to −0.6 mag/dex. Median (or a mode estimator on
  large samples) is the only safe annulus statistic.
- **Faint-star cut in the mzero fit:** pooled per-star statistics show the
  faintest flux quartile reading −0.11 mag (identically on imx462 and hq —
  a fixed-ADU annulus error eats a bigger fraction of a small flux). Cutting
  those stars was scanned across the 8-sweep ensemble and made every metric
  worse: the median mzero already absorbs the tail, and shrinking a 10–20
  star sample toward 3–5 costs more in median noise than the bias removal
  gains. Don't re-invent this.

## Consequences

- On the six validation sweeps, SQM is exposure-flat and focus-flat
  (std 0.07–0.22 mag within a sweep) and lands within **±0.07 mag** of the
  hand-held reference meter on 4 of 6 nights with no tuned constant. Two nights
  read ~0.6 mag apart from the reference for reasons the star photometry cannot
  see (reference pointing/haze suspected); settling the absolute anchor needs a
  proper campaign (side-by-side meter on the camera field, or M67 standard
  photometry).
- All published values change scale relative to prior firmware; prior SQM logs
  are not comparable.
- The imx296 mono `color_coefficient=0.0` is an unmeasured placeholder; measure
  it when a working unit exists.
- The estimators condition over the first minutes of operation; until then SQM
  runs on the profile fallback (`bias_offset`, no wing correction).
