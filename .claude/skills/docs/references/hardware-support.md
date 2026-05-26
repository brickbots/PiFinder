# Hardware & Technical Facts

> **Using this in the `docs` skill:** This file is a curated set of PiFinder
> hardware and technical facts for documentation — diagnosis order, focus/exposure
> procedure, alignment steps, power behavior, and common failure causes. These are
> excellent raw material for troubleshooting and setup docs once rewritten in the
> manual's voice. If a fact here conflicts with the code or existing docs, trust
> the code/docs and flag the discrepancy.

Read this for technical facts about diagnosis, troubleshooting, plate solving, alignment, PiSugar/power, mount/config (Flat/Left/Right), conversion, and replacement parts.

## Diagnosis

- **Escalation order**: simplest user-side fix → replacement parts → repair.
- **"Lost connection" is ambiguous** — it could mean immediate failure or worked-then-stopped. The two cases point to different causes.
- **Post-update "X won't work" is ambiguous** — the menu involved, what happens on screen, and the previous version all matter. Don't pattern-match to a plausible-sounding story (e.g., GPS lock) without grounding in the actual symptom.
- **For alignment issues**, understand the symptom before diagnosing hardware. The full procedure includes the non-obvious SQUARE button to enter star-selection mode. For "way out" issues, check whether the star is outside the darker FOV box on the alignment screen (visible when zoomed out). A missed procedural step is more common than a bent stalk.
- **For "Alignment Failed"**: (1) software version — alignment has been improved, updating may resolve it. (2) Focus and exposure. (3) **Quick re-align alternative**: with any object centered in the eyepiece, hold SQUARE and select "Align" to zero out offsets without using the full alignment screen.
- **For "can't reach pifinder.local" / web interface connection issues**, first **verify the device is connected to the PiFinderAP WiFi network** (PiFinder in AP mode, device joined to "PiFinderAP"). Then the URL/browser fixes: http:// not https://, http://10.10.10.1 fallback (include the trailing-slash variant `http://10.10.10.1/` — some browsers need it), try a different browser (Edge/Safari). The right-network prerequisite is foundational and easy to overlook.
- **DIY kit builds with multiple symptoms** (stuck switches, screen glitches, boot failures): think solder joints first. Bridged joints at the GPIO header or switch legs are most common. Try a cable/power swap before SD re-imaging or Pi replacement.
- **Technical DIY hardware probe points** (pin numbers, signal paths, voltage tests): the **DIY v2.5 schematic** (`https://github.com/brickbots/PiFinder/blob/release/PiFinder_schematic.pdf`) is the authoritative source — don't fabricate specific pin numbers, header locations, or wiring details. For SSH-based GPS diagnosis, prefer **`gpsmon`** (decoded NMEA + satellite info) over raw `cat /dev/serial0`.
- **Issues after a software update**: check the previous version, and whether the relevant subsystem actually changed. Reverting is "not especially easy to do."
- **Order troubleshooting by actionability**: lead with the actual fix; "this isn't causing your problem" reassurance comes after. When something isn't the cause, a brief note of what it actually does is helpful.
- **The power switch affects charging** — the switch direction ("off is to the left if facing the screen") belongs inline with charging instructions.
- Indicator lights are diagnostic evidence — LEDs on when they shouldn't be is a clue, not "normal."
- Before replacing parts, verify the correct part isn't already present (e.g., the 16mm lens is a separate kit item).

## Service path

- **SD card replacement**: a fresh card can be pre-loaded with the latest software ("programmed up"). After re-imaging, configuration (camera type, WiFi) may need restoring.
- **Rebooting on both battery and USB** → likely SD card issue (re-image). **Rebooting on battery only** → battery/power control board issue.

## Product knowledge

- **Plate solving issues**: always address **both focus and exposure**. UI tips — +/- keys zoom the Focus screen, AUTO in exposure menu. Focus order: coarse rotate first, zoom to 2x/4x, then fine rotate at each zoom level. The camera icon appears in the upper-right title bar when focus is close enough; tight focus enables shorter exposures. Background Subtraction is not for new users doing initial setup. Quick-start link with helpful images: `https://pifinder.readthedocs.io/en/release/quick_start.html#setting-focus-first-solve`.
- **"Bright pixels" / very bright or noisy image on Focus screen during first setup** = focus problem, NOT exposure. The lens has a narrow focus range for stars; outside it, on-by-default Background Subtraction has nothing to subtract and generates a bright/noisy image. Concrete starting point: aim at a bright star or distant tree, set the lens so **~6mm of thread is showing (about as wide as a pencil)**, then coarse focus → zoom (+/-) → fine focus at each zoom level. The quick-start link shows what good vs poor focus looks like with BG sub. Exposure tuning belongs once solves are happening, not during first-focus.
- **IMU → plate solve transition benchmark**: PiFinder should switch back to plate solve within <1 second after the scope stops. If longer, focus improvements or AUTO exposure are the path.
- **PiFinder type vs Telescope type are different settings** (frequently confused):
  - **PiFinder type** (Settings → Advanced → PiFinder type: Left/Right/Flat) controls constellation/chart orientation and push-to arrow directions. **Must match the physical mounting.** When constellations appear backwards or push-to is flipped, check *this*.
  - **Telescope type** (web interface equipment settings) controls object-image preview flip/flop based on optical path. **No effect on plate solving.**
- **Near-zenith symptoms on alt-az scopes are geometry, not settings.** Huge push-to jumps, 150+ degree arrow swings, or direction reversal (including vertical) near zenith on a Dob/alt-az are not a "PiFinder type" misconfiguration. Alt/az compresses near zenith and deltas reverse as the scope crosses over. Multiple symptoms together near zenith usually share this single root cause. The PiFinder is not a panacea for zenith objects on alt-az; the graphical starchart workaround (SkySafari with live scope position) helps. See "Zenith / Dobson's Hole Behavior" in the KB.
- **Sleep mode vs push-to dimming are different.** Sleep mode dims the entire screen+keypad and reduces camera frequency; push-to number dimming = plate solve (bright) vs IMU estimation (dim). For motorized mounts with "bumpy" position updates during slow slewing, sleep mode is the likely cause — very smooth movement may not trigger the IMU.
- **Multi-device connectivity** (e.g., SkySafari on iPhone + iPad): only one device can connect to the LX200 server at a time.
- **SmartEye-style workflow with a GoTo mount + SkySafari**: the manual workflow that works today is SkySafari → Go-To → sends target to PiFinder → PiFinder displays push-to instructions → user manually moves the scope to center the object. That IS plate-solve-corrected pointing, just not motorized. The missing piece is plate-solve-corrected *motorized* slews, which is on the GoTo roadmap.
- **PiSugar switch failure → replace.** A broken/erratic switch (e.g., only powers when held between positions, toggle broken off) is replaced with a PiSugar S Plus 5000mAh. A quick solder reflow check can be tried first.
- **PiSugar disassembly for a switch/battery swap** (high level): camera off, side screws, lift back, swap battery, reverse. The v3 assembly doc has visuals. The swap takes a bit of disassembly but isn't too tricky.
- **Switch broken-in-On symptom**: "Runs on USB but not on battery" usually means the switch broke off in the On position. The power-only USB-C port (closest to screen) bypasses the **battery system entirely** (NOT just the switch); a stuck-on switch drains the battery and prevents charging.
- **USB-C ports differ**: power-only port (near keypad) only powers; charging port (top rear) powers and/or charges. "Non-charging port" is acceptable terminology alongside "power-only port."
- **Bright blue charging LED at the eyepiece**: plugging external power into the power-only port (closest to the keypad) powers the unit without charging the battery, which avoids the blue light. The blue LED is the **charging indicator on the charging port**; the power-only port doesn't trigger it.
- **Unexpected battery drain / slow charging / standby**: slide the **physical power switch to OFF after shutdown**. Standby draw is significant even with the PiFinder software not running.
- **Multi-night observing power bank options**: (1) run the PiFinder directly from the bank during sessions, (2) charge the internal battery from the bank during the day if observing 4-5 hours/night. For longer sessions, hot-plug mid-night. The "preserve internal battery via switch-off while powered externally" trick exists but is rarely needed for the typical multi-night case.
- **Roadmap features**: when a concrete roadmap solution exists for a pain point, the roadmap details (what it does, how it's used, timeline) are what matter. ServoCat-style closed-loop GoTo for ServoFi owners is a capability gap that would need a community-built INDI driver.
- **Migrating from another system** (Argo Navis, Nexus DSC): relevant upcoming PiFinder features include user-supplied catalogs.
- **Known hardware limitations and their design rationale**: e.g., no on-screen battery indicator and no graceful low-battery shutdown — a future hardware revision will address these; the current design uses the off-the-shelf PiSugar to keep PiFinder DIY-friendly. Workaround: a USB-C power bank can be hot-plugged for a longer observing session.
- **First-use tips** for new owners: Focus and Alignment steps, exposure adjustments.
- On non-primary scopes where orientation isn't ideal, the physical workaround is to peek around the side to see the screen and use the keypad; the web interface is the other option.
- **SCT/fork mounts**: Flat works below head height; Left/Right when the tube top is too high to see Flat comfortably.
- **Non-standard finder mounting points** (e.g., Tak FS-128 two-screw finder bracket, proprietary bayonet brackets): the Vixen/Synta foot is widespread enough that **commercial aftermarket adapters** are often available. Custom 3D printing is reserved for truly unusual setups (Mak side-saddle, etc.) where commercial options don't exist. The proper finder shoe **may already be on the scope**.
- **Non-perpendicular mounting (tilted but not inverted)**: IMU degradation is graceful. It won't be noticeable unless making big azimuth moves, where position may be a few degrees off when stopping.
- **EQ platforms / changing mount orientation**: plate solving always corrects underlying changes in mount and orientation, no user action required. **An EQ tracking platform under an alt-az scope (Dob) is NOT the same as an EQ mount.** A Dob on a platform is still operated as alt-az; the platform just rotates to track. EQ mode (RA/Dec push-to) is for true EQ mounts.
- **Configuration conversion (Flat↔L/R, L↔R)**: most parts are the same; a couple extras are needed for Flat↔L/R. The camera ribbon cable is the fragile piece, which is why repeated swapping between scopes isn't recommended.
- **L/R conversion instructions are generic** ("the side you want to mount on" / "the opposite side"), not hardcoded directions.
- **v3 hardware questions**: reference the [v3 assembly document](https://docs.google.com/document/d/1qPrIb4E8s5cmlWeev730kk9axFQ7yM9QXBx4Yvpj7oE/edit?tab=t.0) — readthedocs doesn't cover v3.
- **Software updates**: done from the PiFinder menu (Tools > Software Upd); also possible via the web interface. Default docs link: `https://pifinder.readthedocs.io/en/release/user_guide.html#update-software`. Use version-specific URLs (`/en/vX.Y.Z/`) only for very old software AND after verifying the URL exists.
- **Known compatibility caveats** (e.g., EQ mount): note them alongside any recommendation.

## Hardware-themed content discipline

- **Customer-proposed hardware/STL fixes**: a fix that works on one printer/setup may be printer-specific. For example, printed M12×0.5 threads are unreliable on many printers; an existing workaround is to print a smaller diameter and tap for threads.
- **A floated design idea may already exist** as a printable STL in the PiFinder repo — the longer dovetail foot with hard-stop, the safety block, the updated adjustable foot, alt-mount STLs, etc. are already shipped solutions. See KB **Dovetail mount** / **Mounting** for the catalog of existing parts.
- **Validating frustration with older software**: the 1.x interface was tricky, which is why it was overhauled for 2.x.
- **For experimental/new features**: tester programs are relevant (e.g., GoTo integration for Linux/CLI testers).
