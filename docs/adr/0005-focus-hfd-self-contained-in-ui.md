# Focus-quality indicator: self-contained HFD measured in the UI

The focus screen (`UIPreview`) measures focus quality with **Half-Flux Diameter (HFD)** — the diameter enclosing half a star's background-subtracted flux — computed by its **own lightweight star detector** running in the main process on the raw 512×512 frame, deliberately tuned to accept broad, defocused blobs (up to a ~50 px size cap). It does **not** reuse the solver's tetra3/Cedar centroids or SQM's photometry. The driving reason: a badly defocused frame **does not plate-solve**, so solver-derived stars (and SQM, which only runs on successful solves) vanish at exactly the moment focus help is needed most. A self-contained detector is the only source of focus feedback that works across the entire defocus range, including the donut phase at the start of a focus sweep. The math lives in a pure `focus.py` module (no UI/PIL deps) so it is unit-testable against synthetic blobs of known width; `UIPreview` owns only rolling-window state and rendering.

## Considered Options

- **Reuse the solver's matched centroids via `shared_state`.** Rejected: matched-centroid count goes to zero when defocused. Focus guidance would go blind precisely when the image is most out of focus — the worst possible failure mode for the feature.
- **Open a second Cedar gRPC client from the UI.** Rejected: Cedar is tuned to *reject* fuzzy/large blobs (`max_size=10`, `sigma=8`) to find tight stars for solving, so it returns little or nothing on a defocused donut. Wrong tool for the defocused regime, and it adds cross-process coupling to the UI.
- **Share/refactor SQM's `_measure_star_flux_with_local_background` patch geometry.** Rejected: SQM is a different bounded context, runs in the solver process, is gated to once per 5 s on successful solves, and is photometry-tuned. The genuine overlap is ~15 lines of generic numpy patch math carrying no domain meaning; duplicating it keeps the two contexts decoupled and lets each evolve independently. SQM does not detect stars at all, so there is no "two competing star-finders" concern.
- **FWHM instead of HFD.** Rejected: FWHM assumes a Gaussian-ish PSF and breaks on saturated cores and broad/donut defocus — the exact shapes seen across a focus sweep. HFD stays stable and monotonic over the full range, which is what makes the "stop at the minimum" workflow legible.
- **Report HFD in arcseconds.** Rejected: the PiFinder's ~10.2° / 512 px optics give ~72 arcsec/px, so an in-focus star would read as ~70–215 arcsec — ~30× worse than the 2–4 arcsec users expect from imaging-rig FWHM, inviting false alarm and false comparison. Pixels are the honest native unit, and only the *relative* trend matters for finding best focus.

## Consequences

- A second, intentional star-finder exists in the codebase, tuned opposite to Cedar (accept blobs rather than reject them). This is deliberate, not an oversight or a missed reuse opportunity.
- HFD is always computed on the **raw** frame, independent of the display contrast stretch — the reported number never depends on how the image looks. (This also lets the focus screen replace blind per-frame `autocontrast` with a background-anchored, EMA-smoothed stretch driven by the detector's background/peak estimates.)
- The indicator works without any plate solve, so the focus screen is useful before the system has ever solved.
- Companion glossary: [`docs/ax/ui/CONTEXT.md`](../ax/ui/CONTEXT.md) (Focus indicator section).
