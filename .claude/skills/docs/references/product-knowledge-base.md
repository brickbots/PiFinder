# PiFinder Product Knowledge Base

> **Using this in the `docs` skill:** This is a curated PiFinder product-facts
> reference for documentation. When writing documentation, mine it for **facts** —
> hardware specs, default values, how features behave, why things happen, and the
> steps that actually fix problems. Rewrite the facts in the manual's own voice.
> If a fact here conflicts with the code or existing docs, trust the code/docs and
> flag the discrepancy.

---

## About PiFinder

The PiFinder is an open-source, Raspberry Pi–based telescope finder/push-to guidance system. The PiFinder uses a camera and plate-solving to determine where a telescope is pointing and provides push-to guidance to help observers find objects in the night sky. The project website is **https://pifinder.io** and documentation lives at **https://pifinder.readthedocs.io**.

---

## Product Versions & Configurations

### Hardware Versions
- **v1**: Early/rare hardware. Uses a GPS dongle (external USB GPS). Has some unique characteristics around screw assembly.
- **v2 / v2.5**: Mid-generation. A v2 to v2.5 upgrade kit is available. The v2.5 introduced improved hardware.
- **v3**: Current production version (as of early 2026). Uses internal GPS (UBLOX module) and internal battery. Ships with either imx462 or imx296 camera sensor depending on availability at time of assembly. Dimensions: ~110mm wide × 100mm tall × 90mm deep (Left/Right); ~110mm × 120mm × 120mm (Flat). Weight: ~370g with battery, ~290g without (lighter than a Telrad with batteries at 315g). **Note**: v3 does not have a DIY version, so there is no detailed build guide on readthedocs. A separate [assembly document](https://docs.google.com/document/d/1qPrIb4E8s5cmlWeev730kk9axFQ7yM9QXBx4Yvpj7oE/edit?tab=t.0) with photos and general assembly info is available.
- **rev4** (revision 4 — avoid "v4"): Planned future revision — goals include improved manufacturability, better battery/power integration, slightly larger screen (1.92" vs current 1.5", ~30% taller/wider text). As of early 2026, still in early design: engineering samples of potential screens exist but no working prototype on a scope yet. Same software, camera, and computer — will provide the same experience, not a breaking change. All existing PiFinders will continue to receive software updates.

### Form Factors (Configurations)
There are four main form factors, and the choice depends on the telescope type and mounting:

1. **Flat PiFinder**: Camera lens on top, screen faces backward at a **30-degree angle**. Best for rear-focus scopes (refractors, SCTs, Cassegrains) and most common setups. Also good for binocular telescopes (e.g., Oberwerk, Explore Scientific giant binos). The screen angle is convenient for looking down at the device while standing at the eyepiece. A **"Flat-Flat" variant** (no angle) is available as a custom option — better for near-zenith viewing on SCTs but less comfortable at lower altitudes.

2. **Left PiFinder**: Screen faces left. For Dobsonians/Newtonians where the focuser is on the left side of the tube.

3. **Right PiFinder**: Screen faces right. For Dobsonians/Newtonians where the focuser is on the right side of the tube. Slightly more popular than Left for Dobs, but it's a close split.

4. **Straight PiFinder**: Screen faces backwords directly away from the camera.  Not commonly needed. For rear focus scopes which are larger and mounted at or above head hight. The Flat version would be difficult to see on top of the optical tube assembly (OTA) with the scope mounted this high.

### Key Recommendation Logic
- **Refractors / SCTs / rear-focus scopes** → Flat, Left, or Right PiFinder depending on mounting height. Below head height, Flat is a great option — it positions the screen/keypad back and slightly up, making it easy to use from the focuser. If the tube is mounted high enough that the top is too high to see the screen comfortably, Left/Right works well (also good for Dobs and other Newtonian-style scopes). For fork mount SCTs (e.g., C11 on a wedge), Flat is often the best choice since the scope tends to be at a comfortable height.
- **Dobsonians** → Left or Right, matching the focuser side
- **Newtonians on EQ mounts** (e.g., Celestron AVX 6") → Left PiFinder. Since the tube can be rotated in the rings, either could work, but Left is the default recommendation. Note the EQ mount limitations (see Equatorial Mount Support section).
- **Multiple scope types (Dob + refractor)** → Choose a Left/Right that matches the Dob's focuser side. Any PiFinder configuration works on any scope; the choice is about ergonomics. A side-facing PiFinder is generally more convenient on a rear-focuser than a flat version on a large Dob.
- **Self-contained system**: Unlike encoder-based systems (e.g., Nexus DSC, Argo Navis), the PiFinder does not need to be attached to the mount to work. It's fully self-contained and mounts on the OTA.
- **Plate solving vs encoders near zenith ("Dobson's hole")**: Encoder-based systems (Argo Navis, Nexus DSC) struggle near the zenith on Dobsonian mounts because small mechanical errors translate to large positional errors in the azimuth axis. Plate solving doesn't have this problem — it directly measures sky position regardless of mechanical accuracy. **However**, the PiFinder is not a full panacea for zenith observing on alt-az scopes — see "Zenith / Dobson's Hole Behavior" below for the nuanced reality of using push-to numbers near the zenith.
- **You do NOT need two PiFinders** for different scopes. One unit works on all scopes. When the screen faces the "wrong" way, it's easy to peek around the side to see the screen and use the keypad; and the web interface on a phone/tablet provides full remote control as well.
- **Binocular telescopes** (e.g., Oberwerk with picatinny rail) → Flat version recommended.
  - **Picatinny mounting — Richard's preferred two-part off-the-shelf solution**:
    1. Picatinny-to-1/4" adapter plate: `https://www.amazon.com/Metal-Picatinny-Dovetail-Adapter-Camera/dp/B09VYFV9VV/`
    2. Dovetail shoe with 1/4" hole: `https://www.amazon.com/Telescope-Finderscope-Dovetail-Mirrorless-Astrophotography/dp/B09VYCJG84/` — the knurled-knob portion can come off so the top dovetail piece can be used alone, keeping height down.
  - **Lowest-profile alternative**: a custom 3D-printed PiFinder part that mounts the PiFinder directly to the 1/4-20 bolt (using the picatinny-to-1/4" adapter above without the dovetail shoe). This sacrifices the universal dovetail foot, so the PiFinder can't easily be moved between scopes — only worth it when minimal height is the priority.

### Reconfiguring Between Form Factors
- **Left ↔ Right**: These use all the same parts and can be converted by the user with just a screwdriver. Requires near-complete disassembly (~10-15 minutes at a workbench with good lighting). Some fragile parts involved — not recommended as a regular swap between scopes, but fine as a one-time change. Does not void warranty.
  - **Key difference between Left and Right**: The Left version has the camera ribbon cable twisted 180 degrees between the keypad board and the Raspberry Pi. The Right version does not have this twist. Converting between them requires untwisting (or twisting) the cable and rerouting it.
  - **v2.5 DIY kits**: The readthedocs build guide covers both left and right assembly side by side from the same parts. DIY kit customers can follow the cable routing section to convert: https://pifinder.readthedocs.io/en/release/build_guide.html#cable-routing — no need to buy a new unit.
  - **v3 Assembly document** (shows a right-hand build, helpful visual reference): https://docs.google.com/document/d/1qPrIb4E8s5cmlWeev730kk9axFQ7yM9QXBx4Yvpj7oE/edit?tab=t.0
  - **v3 Conversion steps (generic, works for either Left → Right or Right → Left)**:
    1. Remove the two screws on either side of the camera lens to free the camera assembly from the holder
    2. Disconnect the camera ribbon cable from the **camera** (not the Pi) by gently sliding the dark-grey clip away using the tabs on either side. Use a small screwdriver; be gentle as the grey retaining portion can come off completely with too much force
    3. Remove the three screws on each side of the PiFinder and separate the back piece from the bottom plate. Mind the battery — it will be connected to the power board. Unplug it or leave it plugged in, just be aware it's there
    4. Flip the PiFinder over and remove the three screws in the faceplate to fully remove the top cover, exposing the internals
    5. Unroute the camera cable so it no longer goes around the Raspberry Pi and power board and into the back section
    6. For a Right configuration, the cable loops under without a twist; for Left, it requires a 180 degree twist before being routed back through the gap and into the back section
    7. Put the front portion of the case back on and re-secure with three screws
    8. Flip the PiFinder over, route the camera cable so it comes out the side you want to mount the camera on — there are slots in the back piece on both sides. You may need to route the cable under the battery
    9. Put the back cover on, feeding the cable through the slot in the back
    10. Reconnect the camera
    11. Secure the camera holder to the side via three screws
    12. Secure the camera module to the holder with two screws
    13. Put the cover in place on the opposite side with three screws
  - **After the hardware conversion, you MUST also change the software setting**: Settings → Advanced → PiFinder Type (set to match the new hardware configuration). If mismatched, the position estimation system behaves strangely between plate solves (constellations may appear backwards, push-to arrows flipped, IMU-driven motion in the wrong direction). After the conversion, check the camera is producing an image via the Focus screen (uniformly bright indoors, varies with hand over lens), since the camera ribbon cable is the most delicate piece of the swap.
- **Flat/Straight ↔ Left/Right**: These use different 3D printed parts, so converting requires additional parts beyond what ships with the unit. The conversion also requires almost fully disassembling the PiFinder — it's not a casual swap. The camera ribbon cable is also a bit fragile, so the conversion isn't suitable for regularly going back and forth between scopes (repeated swaps can damage the cable), but fine as a one-time change. A Flat PiFinder can still be used on a Dob (any config works on any scope), but the screen/keypad will face up/back rather than toward the observer at the eyepiece, making it less convenient.

- **Conversion-from-Flat data**: All of these require disconnecting and reconnecting the camera at the **ZIF connector on the camera end**. After the hardware swap, a software config setting must be changed and the unit should be re-tested to ensure everything is in order (~a couple of minutes for reconfig + test). Time estimates below assume someone who has done the swap a couple of times.
  - **Flat → Right**: ~5 minutes + testing. Minimal disassembly of the core internals for a quick cable re-route. Leaves 3 unused Flat parts; requires 2 new parts.
  - **Flat → Left**: ~10 minutes + testing. More disassembly because the cable routing is more complicated (takes a bit longer than Right). Same 3 unused Flat parts; same 2 new parts as the Right conversion.
  - **Flat → Straight**: ~3 minutes + testing — easiest, no need to open the core case (just swapping external bits). Same 3 unused Flat parts; requires 3 new parts (one is common with the L/R config).

### "Left-Handed" Scopes
Some scopes (e.g., Apertura AD8, Apertura AD12) are considered "left-handed" for PiFinder mounting purposes. This means the focuser is on the opposite side from the more common configuration. Photos are helpful to determine the correct version.

### Dobsonian Configuration Reference
Known Left/Right mappings for specific Dobsonian models. "Left" or "Right" refers to the focuser side as seen standing behind the primary mirror, looking up toward the aperture.

| Manufacturer | Model | PiFinder Config | Notes |
|---|---|---|---|
| Apertura | AD8 | Left | "Left-handed" scope |
| Apertura | AD12 | Left | "Left-handed" scope |
| Explore Scientific | 16" Ultralight (Gen II) | Right | |
| Obsession | UC18 | Left or Right | Upper ring assembly can be reoriented to either side |
| Explore Scientific | 12" | Right | |
| Orion | XT series (XT6, XT8, XT8i, XT10, XT12, etc.) | Left | All XT Dobs are left-handed |

**How to determine Left vs Right:** Stand behind the primary mirror and face up toward the aperture. The focuser side determines the PiFinder config: focuser on the left → Left PiFinder, focuser on the right → Right PiFinder. When a model isn't listed, photos are the most reliable way to confirm.

---

## Setup & First Use

### Initial Power On
- The PiFinder has a small **slide switch** (not a push button) for power. It slides (right=on, left=off), not depresses. This is a common point of confusion.
- **Switch ergonomics tip**: The slide switch is small and hard to find by feel in the dark. A dab of hot glue or Sugru (moldable silicone) on top gives it a bigger surface area. Requires a bit of care to apply but isn't too hard.
- The SQUARE key does NOT control power — it is used for various software functions.
- After powering on, a startup screen with the PiFinder logo appears, followed by the main menu.
- First boot after re-imaging takes extra time as the system expands the filesystem — typically a minute or two, **and the unit will reboot multiple times** during this initial setup. "It boots and then restarts" on a first boot is expected.

### Power & Charging Details
- **Two USB-C ports**: The port closest to the keypad (closest to the screen) powers the unit only; the port at the top rear (furthest from the screen) both powers and charges the internal battery. The **power-only port** is preferred during observing because the charging port's blue/green LED is distractingly bright at night. **Important**: The power-only port (closest to screen) powers the unit immediately regardless of the power switch position — it bypasses the switch entirely.
- **Charging indicator**: Glows blue while charging, turns green when complete.
- **Charging time**: ~3 hours from empty when the power switch is OFF, but charge time **depends a lot on the power source** and is variable. Runtime is the more consistent measure. If the PiFinder is running (switch on or switch broken), it may draw about as much current as the charger provides and the battery may not fill up appreciably. A long charge session that results in a still-empty battery is a strong indicator the unit was running during charging — check the power switch.
- **Power consumption**: ~950mA at 5V under full load, ~60% draw during idle/power-save mode. Minimum 2A rated supply recommended (startup peaks at ~1.5A).
- **Battery**: Internal PiSugar S Plus 5000mAh. **Runtime: 4-5 hours, but highly activity-dependent.** Sitting at the eyepiece on a single object for minutes at a time, or walking away from the scope frequently, puts the PiFinder into a lower-power mode and extends runtime. Active UI use and pushing the scope between objects (camera + IMU + screen all active) draws more power — a fast run through lots of objects yields a shorter runtime. Battery life degrades below freezing but the PiFinder's internal heat keeps it warm in most conditions. **Important**: Only the PiSugar S Plus model is compatible — other PiSugar models interact with the I2C bus and cause IMU communication issues. The Amazon listing may say "PiSugar S Pro" but it's the correct S Plus model (check photos). Reference: https://github.com/PiSugar/PiSugar/wiki/PiSugarS-Plus
- **No on-screen battery level indicator**: There is no battery percentage or level indicator on the PiFinder screen, and no auto-shutdown when the battery runs low. The battery is good for 4-5 hours and will **abruptly shut off** when charge is depleted. The only external power indicator is the LED on the charging USB-C port (blue charging / green full), which only tells you about charging state, not the battery's level when running standalone. A future hardware revision will address this; the current design keeps the PiFinder DIY-friendly using the off-the-shelf PiSugar board for the power system. **Practical workaround**: a USB-C power bank can be hot-plugged while the PiFinder is running to extend a session.
- **Hot-swap power**: USB-C power can be plugged in mid-session without restart. Behavior depends on which USB-C port is used: the power-only port (near keypad) powers the unit only; the charging port (top rear) powers the unit and/or charges the battery.
- **Runtime extension trick**: Plug external USB-C power into the **power-only port** while the unit is running on battery, **then switch off the battery system**. The unit keeps running on external power and the battery is preserved for after the external power is unplugged — useful for stretching a session beyond the internal battery's runtime.
- **External power without battery**: Units sold without battery have no power switch — if USB is plugged in, it's on. This also means even if the power switch fails on a battery unit, it can still run on external USB.
- **12V telescope power**: **Do NOT run 12V directly into the PiFinder** — it expects 5V USB-C power. Use a 12V-to-5V USB-C DC-DC step-down converter. Richard uses this on his own scope. Example product: https://www.amazon.com/gp/aw/d/B09DGDQ48H — for international customers, note they may need to source a similar adapter locally. Ensure good quality cables — cheap cables with long runs can cause voltage drop issues.
- **USB power banks / portable power stations**: When using a device like a Jackery, the direct USB output should work if rated ≥2A. However, plugging a USB wall charger into the unit's AC inverter may not deliver clean enough power. Also watch for flaky USB cables — some cables are unreliable at the ~2A current draw the PiFinder needs. If experiencing power dropouts, try swapping the USB cable first.
- **External power bank capacity rule of thumb**: ~1,000mAh runs the PiFinder for about an hour, so a 10,000mAh bank gives roughly 8-10 hours of use. (Slightly more conservative than the internal-battery rule of thumb because power banks lose some efficiency through voltage conversion.)
- **Power-save mode (sleep mode)**: After a configurable idle period (default 30 seconds), the **entire screen dims along with the keypad** and the **camera takes images much less frequently**. Any button press or scope movement (detected by IMU) reawakens full functionality. Can be adjusted or disabled in Settings. **IMU sensitivity setting**: Controls how much motion is needed to wake from sleep. Default is **Medium**, which works well for most situations. **Important distinction**: Sleep mode dimming (entire screen + keypad) is **different from push-to number dimming** — push-to numbers dim/brighten to indicate whether the position is from IMU estimation (dim) or plate solve confirmation (bright). **Important**: Sleep mode can silently stop sending position updates to SkySafari — when relying on SkySafari, extend or disable the sleep timer. **Motorized mount caveat**: Very slow/smooth slewing (e.g., guide speed on a ServoCat) may not be detected by the IMU, causing the PiFinder to enter sleep mode during motion. Symptoms: numbers freeze during slow movement and abruptly update. Fix: bump the scope or press any key to wake it. With motorized mounts doing frequent slow slewing, extend or disable the sleep timer entirely.

### Brightness Control
- Hold **SQUARE** and press **+** for brighter or **-** for dimmer. Adjusts both screen and keypad brightness. Essential for preserving dark adaptation.
- **Keypad brightness** can be adjusted independently via **Settings → Keypad Brt** (ratio relative to screen).
  - **UX gotcha**: Changing the ratio does NOT take effect immediately — the keypad brightness only refreshes the next time the overall PiFinder brightness is changed. Workflow: set the new ratio, then use SQUARE + / SQUARE - to bump overall brightness up/down to see the new keypad level take effect.
- **Caution**: A very dim setting from a previous nighttime session can make the screen appear completely blank in daylight. Always try brightening before assuming a hardware failure.

### GPS Lock
- The PiFinder requires a GPS lock to determine location and time. This is necessary for initializing catalogs (including planets).
- GPS lock can take time, especially in buildings. Metal structures, balconies, and indoor locations can block or reflect GPS signals.
- Check GPS status under **Tools → Status** or the dedicated GPS screen under the **Start** menu.
- The GPS screen shuts off the camera solver and devotes resources to GPS acquisition, reducing electromagnetic noise interference for faster lock.
- **GPS antenna is directional** — it's in the "bump" on top of the PiFinder. When the scope points near zenith, the antenna points toward the horizon, degrading reception. **Tip: Point the scope lower (toward horizon) during initial GPS acquisition** to aim the antenna skyward.
- **Camera ribbon cable routing**: The flat white camera ribbon cable generates RF noise. If routed too close to the GPS module, it can prevent GPS lock. Keep the cable routed away from the GPS.
- **Daytime vs nighttime**: GPS signals are stronger at night. The sun creates interference through its interaction with the atmosphere. A lock is still possible during the day, but nighttime acquisition is more reliable.
- **Antenna connection**: The GPS antenna plug should be fully affixed to the GPS module and rotate easily/freely when fully engaged. Worth checking if GPS won't lock.
- **"Many satellites seen, 0 used"**: This pattern indicates an antenna problem (not a receiver issue). May need antenna replacement.
- **Indoor use**: GPS is unlikely to get a lock indoors. Manual location/time entry is available via the web interface — click the pencil icon next to GPS info on the main page. Time auto-sets to UTC from browser; location entered in decimal format.
- After lock, the status screen will show satellites seen/used (except for v1 units with generic GPS dongles, which always show 0/0 but still lock properly).
- **GPS diagnostic via SSH**: For technical users with SSH access (built in on Linux/macOS, available via PuTTY/etc on Windows), `ssh pifinder@pifinder.local` (password `solveit`) and run `gpsmon` to see live decoded NMEA sentences and satellite info. The bottom panel shows raw messages streaming in; the top section shows decoded state; **NAV_SVINFO** on the left shows satellites appearing/disappearing. If messages stream but no satellites appear, that points to a defective GPS radio or antenna problem (the microcontroller is communicating fine). Prefer `gpsmon` over raw `cat /dev/serial0` — it gives decoded state, not just bytes.
  - **Empty DEVICES list** (`{"class":"DEVICES","devices":[]}`) means gpsd is running but has no GPS device attached — the GPS isn't reaching the daemon at all. On a working PiFinder you'd see `/dev/serial0` in the list. This is upstream of the GPS module itself, somewhere between the Pi's UART and the device file gpsd is expecting. **First suspect: wrong Pi model** (Pi 3B+ instead of Pi 4 — see DIY hardware section above). Also possible: UART damage on the Pi, or wiring/header contact issue on a DIY board.
  - **Exit gpsmon**: Ctrl-C returns to the shell. No preliminary commands are needed — gpsd starts automatically at boot; the "JSON slave-driver" fallback prompt is just what gpsmon shows when there are no devices.

### Status Screen Icons
- **Satellite dish icon** (upper right): Solid = GPS locked; flashing = searching for satellites.
- **Camera icon** (upper right): Turns fully opaque each time a plate solve succeeds, then fades out over ~1 second. When solving is working well with good focus/exposure, the icon should be **basically always opaque while the scope is stationary**. Seeing the icon fade while the scope is still indicates a focus/exposure issue (or occasionally high-thin clouds).
- **X symbol**: No pointing determination achieved yet.
- **Status screen details**: Shows solver state (LST SLV) — seconds since last solve, current mode (I=IMU, C=Camera), matched stars count. Also shows WiFi mode, network name, and IP address.
- **"Degraded, check status" message with blank IMU data**: Indicates a dead/non-functional IMU. Once a replacement IMU is soldered in, the status page should populate with IMU data and the degraded message will go away on the next boot.

### Title Bar Display
- The title bar area alternates every few seconds between showing the **constellation** the scope is currently pointed at and the **Sky Quality Meter (SQM)** reading.
- **SQM (Sky Quality Meter)**: An experimental feature that uses the PiFinder's camera to measure sky darkness/brightness. The value is displayed in **magnitudes per square arcsecond** — higher numbers mean darker (better) skies:
  - ~17: Suburban skies
  - ~18–19: Rural/good skies
  - ~20–21+: Very dark skies
- The SQM reading changes as you point at different parts of the sky — it's typically darker at the zenith and brighter near the horizon or toward light pollution sources.
- A dedicated SQM screen with more detailed readout is available under **Tools → Experimental**.
- This is an experimental/recently released feature.

### WiFi Setup
- In **AP (Access Point) mode**: The PiFinder generates its own WiFi network ("PiFinderAP") that you connect to directly. No internet access in this mode.
- In **Client mode**: The PiFinder connects to your home/observatory WiFi.
- WiFi status can be checked under **Tools → Status**. The SSID field should show the connected network name; blank = not connected.
- If WiFi is not connecting in client mode, try removing and re-entering the WiFi credentials. Both SSID and password are **case-sensitive**.
- **Common browser issues**: Some browsers (notably Chrome on Windows) may fail to load `pifinder.local`. Try Edge, or explicitly type `http://` (not `https://`). The PiFinder uses HTTP only.
- **Device auto-disconnect**: Since PiFinderAP has no internet, some phones/tablets auto-switch to cellular or another WiFi network. Disable "smart network switching" or similar features.
- **Securing PiFinderAP with a password**: The AP does not currently support a WPA password through the UI — it's open by design. The web interface password (default `solveit`) still gates everything beyond the home screen, so bystanders can't change settings. Adding WPA to the AP is planned for a future update. Linux-comfortable users can manually add a WiFi password today.
- **iPhone hotspot (Client mode)**: Enable **Maximize Compatibility** in the iPhone's Personal Hotspot settings, and keep the Hotspot settings screen open while the PiFinder connects for the first time (iPhones sleep the hotspot aggressively otherwise).
- Ethernet connection is an alternative (easier once set up). Plugging a Cat6 cable directly to the Pi (requires opening the case) enables updates even when WiFi won't connect.

### Web Interface
- Access at **http://pifinder.local** from any device on the same network.
- **When troubleshooting connection failures, first verify the device is on the right WiFi network** — the PiFinder should be in AP mode and the device should be connected to the **PiFinderAP** network. It's the foundational prerequisite and easy to overlook.
- In AP mode, if `pifinder.local` doesn't resolve, try **http://10.10.10.1** as a fallback. Some browsers also need the trailing slash variant: `http://10.10.10.1` ( `http://10.10.10.1/` ).
- Default password: **solveit** (all lowercase, one word). This is also the system `pifinder` user password — changing one changes the other.
- The home screen is accessible **without a password**; other functions (Network, Tools, etc.) require authentication.
- Functions include: Remote control (virtual screen + keypad), configuration, software updates, network settings, backup/restore of logs/settings/data, viewing and downloading logged observations.
- Password can be changed via Web Interface → Tools.
- If "Invalid Password" error occurs: try a different browser, clear cache/cookies. If still failing, the fix is to re-image the SD card to reset the password.

### Data Access via SMB (Network Share)
- Access the PiFinder's files via SMB at **//pifinder.local/shared** (connect as guest, no password).
- **captures/**: Images from logged observations, named by observation database ID.
- **obslists/**: Observing lists (can save during sessions or load for future sessions).
- **screenshots/**: Screenshots captured via SQUARE + 0.
- **solver_debug_dumps/**: Solver performance data (if enabled).
- **observations.db**: SQLite database containing all logged observations.

### Camera Configuration & Focus
- V3 PiFinders ship with either **imx462** or **imx296** camera sensor — either performs similarly. Default is imx462.
- Camera type options in Settings → Camera Type: **imx462**, **imx296**, or **imx477** (v2 cameras with larger lens that has aperture + focus rings). It won't hurt to try all options if unsure.
- **After changing camera type, a full power-off/on cycle is required** — a software restart alone is NOT sufficient.
- **Camera verification test**: On the Focus screen, a working camera shows at least some noise with the lens cap on, and a brighter image during the day or stars at night. Use this to confirm the camera initialized before worrying about focus/exposure.
- **Software updates can reset the camera type setting** — always verify camera type after updating.
- The camera/focus screen is under **Start → Focus** (renamed from "Camera" and moved to the Start menu in newer software).
- **Focusing procedure**: Aim scope at a region of sky with bright stars, select Focus, the live preview highlights stars and removes background skyglow. Slowly rotate the lens until stars are as small and sharp as possible. Then use **+/-** to zoom to 2x and 4x and repeat the rotation for fine adjustment at each zoom level. As focus improves, more stars will appear, and the **camera icon** will appear in the **upper right of the title bar** when focus is close enough for plate solving. **Tight focus also enables shorter exposures** because star light is concentrated into fewer pixels. Focus is the #1 cause of plate solve failures. **Focus is more critical under brighter skies** — slightly defocused dim stars disappear into the sky background, so tight focus matters even more in light-polluted conditions. **Quick-start guide with images**: https://pifinder.readthedocs.io/en/release/quick_start.html#setting-focus-first-solve
- **First-time focus / "bright pixels" or noisy image on Focus screen**: The lens has a **narrow range of focus** that yields star points. If focus is well outside that range, the on-by-default **Background Subtraction has no stars to subtract** and the live preview becomes very bright/noisy. Customers reporting "bright pixels" on first setup are almost always badly out of focus, not seeing a sky-brightness or exposure problem. Fix is focus, not AUTO exposure.
- **First-time focus starter step**: Roughly aim at a very bright star or even a tree in the distance. Set the lens so **~6mm of thread is showing (about as wide as a pencil)** — this is close to in-focus. From there, coarse focus first by rotating the lens, then zoom in (+/-) to 2x/4x for fine adjustment at each zoom level. The quick-start guide shows what good vs poor focus looks like with regard to background subtraction.
- **Daytime focus preview tip**: Set exposure to the shortest value and use the Focus preview screen in daytime to fine-tune camera tilt/alignment — e.g., adjusting a mounting bracket until nearby structure is just out of the camera's field of view.
- **Focus starting point for new builds**: Target a 6mm gap between the top of the lens holder and the bottom of the lip on the lens (~10mm of threads engaged).
- **Older v2 lens has TWO rings**: Focus ring (near back) and aperture ring (toward front). The **aperture must be fully open** for the PiFinder to work. This is a common confusion point for second-hand/v2 units.
- **Plate solve rate**: V3/v2.5 cameras can solve up to **20 times per second** under dark skies, 5-10/sec under brighter skies. V2 cameras: ~5/sec dark, 2-3/sec bright.
- **Lens cap replacement**: The stock lens cap is small and easily lost. **Bolt end caps (15-16mm diameter)** work well as replacements — they slide over the entire lens.

### Button Mapping (Post-Software Update)
- In current software, the right-hand side buttons (formerly up/down) are now **+/-**
- The **ABCD buttons** are now arrow keys for menu control: B=Up, C=Down, D=Select/Right, A=Back/Left
- Updated faceplates are available to reflect the new button mapping.
- The SQUARE key (bottom right, under +/-) is used for: entering star-selection mode during alignment, screenshots (SQUARE + 0), and debug functions (SQUARE + /)
- **Hold LEFT** for 1+ seconds to jump directly to the main menu from any screen.
- **Hold SQUARE** to open a context-sensitive **radial quick menu** with up to four options (one per arrow direction). Some quick menus have multiple layers. Help pages are often available as the UP option in quick menus.

### "Alignment Failed" Error
This error means the PiFinder isn't plate solving reliably enough to complete the alignment. Troubleshooting order:
1. **Check software version first** — the alignment system has been improved over time. On older software, update before diving into focus/exposure.
2. **Focus and/or exposure** — the usual root causes. See the focusing procedure above and exposure settings. Quick-start guide's focus section for visual reference: https://pifinder.readthedocs.io/en/release/quick_start.html#setting-focus-first-solve
3. **Quick re-align alternative**: with an object centered in the eyepiece, hold SQUARE and choose "Align" to zero out offsets without going through the full alignment screen. Useful when the full alignment flow is giving trouble.

### Alignment System (v2.1.0+)
The PiFinder has a digital alignment system that maps where within its 10° field of view (about 20 full moons) the telescope's optical axis actually points:
1. Select **Align** from the **Start** menu
2. A rendered star chart with constellation lines appears
3. Point the scope at a recognizable bright star
4. Press **SQUARE** to enter star-selection mode
5. Use arrow keys to highlight the star that's centered in your telescope's eyepiece — the cursor hops between labeled stars on the chart rather than moving freely, jumping to the nearest star in the direction pressed
6. Press **SQUARE** again to complete alignment

**Quick re-align**: After centering any known object in the eyepiece, hold SQUARE for 1 second and select "Align" to update alignment without repeating the full process.

**Alignment tips:**
- Alignment requires reliable plate solving at 2+ solves per second — the camera icon must be solid (not fading).
- In light-polluted skies, align on bright stars (e.g., Vega) rather than dim ones like Polaris.
- **Defocus trick**: Greatly defocus the star in the eyepiece so the disc fills most of the FOV — this makes centering much easier.
- Alignment only maps the PiFinder-to-scope offset. It persists as long as the PiFinder doesn't physically move relative to the scope — no need to re-align when swapping eyepieces or adding Barlows.
- The 10° FOV is wide enough that rough alignment works — the PiFinder doesn't need to be precisely collimated with the scope's optical axis.
- **Camera FOV box on alignment screen**: When zoomed out on the alignment screen, a **darker box** is visible that represents the camera's field of view. The alignment star must be within this box. If a customer reports a star being "way out of field" during alignment, first clarify whether they mean outside this box. If the PiFinder camera is more than ~5 degrees offset from the telescope's view, physical adjustment is needed (adjust the mounting shoe or camera holder position).
- **Physical alignment vs digital alignment**: When a customer reports alignment problems, first verify they understand the alignment procedure (especially the SQUARE button press). If the camera is physically pointed too far from the telescope's optical axis (>5 degrees), no amount of digital alignment will help — the star won't be in the camera's FOV at all.

### Finding Objects & Push-To Guidance
- Access objects via main menu → **Objects** → choose **By Catalog**, **All Filtered**, **Recent** (session history), or **Name Search** (keypad text entry — multi-tap by default, or T9 via the Search Input setting).
- In object lists, pressing **SQUARE** cycles through info displays: catalog designation → common names → magnitude/size with observation checkmarks.
- **Push-to guidance** (from Object Details screen):
  - **Top number**: Rotational direction (CW/CCW) and degrees to move
  - **Bottom number**: Vertical movement (toward zenith/horizon) and degrees
  - **Azimuth arrows are configurable**: People have different intuitions about how CW/CCW arrows relate to telescope movement. The direction can be swapped in settings to match the user's preference. If push-to directions seem "opposite" in azimuth, this configurability is the likely explanation rather than a misconfiguration.
  - Numbers **dim** during accelerometer-estimated position (scope moving) and **brighten** after plate solving confirms position (scope stationary). **Note**: This dimming is different from sleep mode dimming — see Power-save mode section.
  - **Eyepiece FOV relationship**: For a 0.5° true-FOV eyepiece, getting below 0.25°/0.25° ensures the object is in the field
- **"What am I looking at?" feature**: Sort any object list by **Nearest** (via quick menu) — the object closest to where the scope is pointing appears at the top. Point the scope at a spot in the sky, filter for a specific type of object, and discover new and unexpected objects.
- **Planets** appear as "Pl1, Pl2, etc." in catalog ID view — press SQUARE to see full planet names.
- **Star chart orientation**: The rendered star chart on the screen (with constellation lines and object markers) is a **wide naked-eye view**, oriented **"zenith up"** — it matches how you see the patterns with the naked eye, not what you see through the eyepiece. Even at maximum zoom the chart still covers **several degrees** of sky — more than an eyepiece FOV. Distinct from the object image previews (which ARE eyepiece-matched — see next bullet). The chart display automatically matches the sky regardless of how the PiFinder is physically mounted. Plate solving is orientation-independent, so there is no "upside down" concern for the chart. **If constellations appear backwards/flipped**, the most likely cause is the **PiFinder type** setting (Settings/Advanced/PiFinder type) being wrong — e.g., set to Right when it should be Left. This setting must match the physical mounting orientation. The PiFinder type setting also affects push-to arrow directions.
- **Object image previews** (13,000+ prebuilt): Sourced primarily from the Palomar Sky Surveys with full image coverage for the complete NGC/IC catalog. Images are oriented to match eyepiece view for **Newtonian reflectors** by default, and are **rotated to match the object's orientation depending on its location in the sky** — so they should be a very close match to what's seen at the eyepiece. **+/- cycles through eyepiece framings** when the user has entered their scope + eyepiece specs in the web interface equipment settings (shows how the object would frame in each eyepiece). Without those specs entered, +/- zooms.
  - **Telescope type setting**: The web interface equipment settings let you configure your telescope type. It has **no effect on plate solving**. The telescope + eyepiece combination **does** drive FOV and magnification (scale) in the preview.
  - **Current state of flip/flop**: The *plan* is for the telescope type setting to flip/flop previews based on optical path, but that's not yet hooked up. The equipment interface is still new, so for now previews always show the image as it would appear in a Newtonian, regardless of telescope type. Scaling by telescope + eyepiece works today; flip/flop is planned but not yet implemented.
- **Manual RA/DEC entry** (v2.3.0+): Enter arbitrary coordinates for objects not in built-in catalogs (asteroids, newly discovered objects). Also available by sending targets from SkySafari.
- **Chart screen RA/DEC readout**: The chart screen displays the current pointing position in RA/DEC. Useful for quickly panning to something whose RA/DEC you know without setting up full push-to guidance — pair with manual entry as adjacent capabilities for ad-hoc targets.
- **Custom object lifecycle** (current limitations as of v2.x):
  - The **"Custom"** menu item is the entry form itself — selecting it always opens a fresh coordinate entry and creates a new object. There's no "list of custom objects" under that menu item.
  - Previously entered custom objects appear in **Main Menu → Objects → Recent**, auto-named **User1, User2, …**.
  - **Recent is session-only** — custom objects disappear after a reboot.
  - No in-place **edit**, **rename**, or **delete** for individual custom entries. The workaround for a correction is to re-enter the object with the fixed coordinates and ignore the old one.
  - The forthcoming user-supplied observing lists feature (see Catalogs section) is the planned path for persistent custom objects.

### Zenith / Dobson's Hole Behavior
For customers asking about pointing accuracy, large push-to jumps, or reversed arrow directions near the zenith on alt-az scopes (Dobs, SCTs on alt-az mounts), the core story is:

- **Plate solving itself is not the issue at zenith.** Position is measured directly from the sky and remains accurate regardless of where the scope points. An EQ-mount PiFinder provides easy-to-follow guidance for zenith objects because RA/DEC coordinates are well-ordered at the zenith.
- **The issue is that the PiFinder presents push-to instructions in the alt/az coordinate system**, which compresses dramatically near the zenith where the geometry breaks down. Near zenith, tiny physical movements correspond to huge azimuth changes, and push-to numbers/arrows can shift wildly.
- **Alt and az deltas can both reverse as the scope crosses over the zenith** — a push-to arrow indicating "up" before crossing may indicate "down" after, and similarly for azimuth. This is a geometric artifact of alt/az coordinates, not a PiFinder type setting issue or a bug. Do NOT default to diagnosing this as a "PiFinder type" misconfiguration.
- **Compounding factors**:
  - Physical Dobson's hole difficulty — smooth, precise movements near zenith are hard.
  - A real telescope is unlikely to align exactly with the theoretical alt/az coordinate system, so the physical "dead spot" and the geometric dead spot are slightly offset.
- **Practical workaround**: ignore the push-to numbers right at the zenith and use a graphical starchart showing both scope position and object position — SkySafari works well for this because the PiFinder's position is transmitted live.
- **Roadmap**: adding the current target to the PiFinder's on-screen star chart so visual navigation works without needing a phone/tablet.
- The PiFinder is not a panacea for observing objects right at the zenith on an alt-az scope. The physics of the mount and the alt/az coordinate system still cause difficulty up there.

### Filtering System
Object lists (except Name Search and Recent) display only items matching filter criteria:
- **Catalogs Filter**: Select which catalogs to include (multi-select)
- **Type Filter**: Filter by object type (galaxy, nebula, cluster, etc.)
- **Altitude Filter**: Only objects above a specified altitude
- **Magnitude Filter**: Only objects brighter than a specified magnitude
- **Observed Filter**: Show only logged, never-logged, or any status
- **Reset All** removes all filters

### Observation Logging
From Object Details, press RIGHT to open the logging interface:
- **Observability**: Rate visibility/recognition difficulty (1-5 scale)
- **Appeal**: Overall recommendation rating (1-5 scale)
- **Conditions**: Transparency and seeing
- **Eyepiece**: Which eyepiece was used
- Objects can be logged with or without filling in context fields.
- Supports **multi-session observing projects** — combine filters (e.g., observed status + nearest sorting) to systematically work through catalogs like Messier or Herschel 400.

---

## Common Support Issues

### SD Card Problems
**Symptoms**: Device not booting, intermittent crashes, software corruption, blank screen on startup (no keypad backlight either).
**Resolution**:
- SD card corruption is one of the most common issues. Re-writing/re-imaging the SD card with the latest software release .img file typically resolves the issue.
- **SD card symptoms are binary, not subtle**: SD card errors/corruption generally prevent any operation (no boot, crashes, blank screen), not introduce small changes to behavior. Functional-but-degraded behavior (e.g., slow plate solves, occasional jumps) is unlikely to be caused by the SD card — diagnose the actual symptom instead rather than reflashing as a first step.
- **Self-reimage option**: GitHub releases link (https://github.com/brickbots/PiFinder/releases) and docs link to the prebuilt-release-image instructions (https://pifinder.readthedocs.io/en/release/software.html#prebuilt-release-image). The most common stumbling block for self-reimagers: "Use the Raspberry Pi Imager with 'Use Custom' to load the .img and configure your WiFi in the imager settings (but do not set a hostname or username/password)."
- **Variable-stage boot hang (different stop points across attempts — catalogs one time, menus the next)**: textbook SD card corruption signature. The Pi is clearly past filesystem repair (it's reaching named UI stages), so the standard "wait 5 minutes" advice doesn't apply here. The fix is a fresh card or self-reimage.
- **SD card access (v2 hardware)**: Two options: (1) On revision 2 hardware, there is a small snap-out access door on the right-hand side of the unit — snap it out to expose the SD card directly. (2) Alternatively, remove the 3 screws in the faceplate and the whole shroud slides off easily, giving full access. The SD card sits between the green Raspberry Pi board and the black battery control board. The white camera ribbon cable may need to be gently moved aside. Be careful not to crack the SD card during reassembly.
- **Battery access** (different from SD card access): Remove 3 screws on *each* side of the PiFinder, disconnect the camera, and remove the back panel to expose the battery, which is connected via a plug. More involved than SD card access but manageable. Battery should last years of normal use.

### Software Updates
- Updates are performed directly from the **PiFinder menu** (**Tools → Software Upd**). Also accessible via the web interface, or by re-imaging the SD card.
- Update requires Client Mode with internet connection. PiFinder checks internet access and compares installed version against latest release. Updates take several minutes with automatic restart.
- **Release cadence**: PiFinder releases software updates every couple of months, adding new catalogs and features developed by the team and the community. Shipped units are often a version or two behind the latest release, so an in-the-field update is part of the normal first-week experience.
- The latest .img file can be downloaded from the PiFinder GitHub releases page for SD card re-imaging.
- **Re-imaging note**: Use Raspberry Pi Imager with "Use Custom" to load the downloaded .img file. Configure WiFi SSID/password/country in imager settings but do **NOT** set hostname or username/password (SSH is enabled by default on the image). The prebuilt image includes 13,000+ catalog images pre-downloaded (~5GB).
- **"Unknown" release version**: Means the PiFinder cannot reach the internet to check for the latest release. This happens when the PiFinder is in AP mode (no internet connection) OR when in Client mode but WiFi is not configured or misconfigured. The fix is to get the PiFinder connected to a WiFi network with internet access via Client mode — do NOT suggest re-imaging the SD card for this issue.
- **WiFi setup for updates**: Step-by-step: (1) Put PiFinder in AP mode, (2) connect device to the "PiFinderAP" WiFi network, (3) open http://pifinder.local, (4) use the **Network** menu to configure home WiFi credentials, (5) switch to Client mode. The PiFinder will restart and connect. Detailed docs: https://pifinder.readthedocs.io/en/release/user_guide.html#connecting-to-a-new-wifi-network
- **If WiFi is configured but version still shows "unknown"**: Try moving closer to the WiFi router, or delete and re-enter the network info to rule out password typos.
- After re-imaging, configuration may need to be restored (camera type, WiFi settings, etc.).
- **SSH manual update** (fallback when on-device update fails): `ssh pifinder@pifinder.local` (password: `solveit`), then `cd PiFinder && git pull`. Restart after.
- **Reverting to a previous version**: Possible via SSH (git checkout of a specific version tag) or by re-imaging the SD card with an older .img file. Both methods are **not especially easy** for most users.
- **GPS type setting**: If using a GPS dongle (v1/older units), switch GPS type from the default **UBLOX** to **Generic**. Do a full power cycle after changing.
- Software version 2.4.0 fixed GPS dongle issues for v1 hardware.
- **LX200 server stability**: The LX200 server (used by SkySafari) has had no changes between versions 2.3.0 and 2.4.0. If a customer reports SkySafari connection issues after updating, the LX200 server code is unlikely to be the cause.

### Power & Battery Issues
- The PiFinder's internal computer dissipates ~5 watts, making it an effective dew heater.
- PiFinder has proven resilient to extreme temperatures: tested from 40°C/100°F down to -15°C/5°F.
- Battery data is being collected; users have contributed cold-weather runtime data.
- **Can't turn on with internal battery**: Verify the power switch operation (slide, not push). Check if the PiSugar battery board (for DIY builds) needs attention.
- **Charging**: Use USB-C (the charging port at top rear, not the power-only port near the keypad). Charging indicator: blue = charging, green = complete. If using a non-PD (Power Delivery) source, charging will be slower but still works at 5V. PD-compliant sources negotiate higher power delivery.
- **Smoking/dead PiFinder**: Very rare. Usually indicates a defective Raspberry Pi power component.
- **Rebooting issues**: Can indicate battery or power control board problems. **Diagnostic**: Test on external USB power — if it reboot-cycles on both battery and USB, it's likely an SD card issue (re-image). If only on battery, it's a battery/power control board issue.
- **PiSugar ribbon cable**: During reassembly, the battery ribbon cable must lie flat and be fully inserted. A dislodged cable causes the battery to not charge or power the unit.
- **PiSugar replacement part**: PiSugar S Plus 5000mAh. **Only use the S Plus model** — other PiSugar models interfere with the I2C bus and cause IMU communication issues. The PiSugar board attaches to the Raspberry Pi via hexagonal standoffs (not separate screws).
- **PiSugar switch failures**: The switches can physically break off from handling; they are well recessed inside the case and rarely break in shipping. If the switch is behaving erratically (e.g., only powers when held between positions), reflowing the switch solder joints is a quick check; if that doesn't resolve it, the PiSugar S Plus is replaced.
- **Switch broken in "On" position — common symptom pattern**: Unit runs fine while plugged into the power-only USB-C port (closest to screen) but won't run on battery alone. Mechanism: the power-only port bypasses the battery system entirely (which is why it runs while plugged in), but a switch stuck "On" continuously drains the battery and prevents it from properly charging back up — so when the power supply is removed, there's nothing left to run on.

### Blank Screen on Startup
**Diagnostic approach** — check what the keypad does:
- **No keypad backlight AND no screen**: Likely SD card or power issue. A faint blinking red LED inside = Pi is powered but not booting. Try re-imaging the SD card.
- **Blinking LED inside the unit (v3)**: On v3 units, a blinking LED visible inside the housing is most likely the **GPS module's power LED**, which flashes when it has a GPS lock. This is **normal operation** — do not confuse it with the Raspberry Pi power LED indicating voltage issues. **Diagnostic use**: If the GPS LED and/or the small red power LED on the far-right of the Raspberry Pi are visible when the power switch is in the OFF position (and no USB is connected), this indicates the power switch is not properly disconnecting power — a potential hardware fault that can prevent charging and drain the battery.
- **Keypad lights up but screen is blank or shows garbled characters/hieroglyphs**: Screen hardware/solder connection issue. Confirm by connecting via web interface — if the web shows the screen correctly, the software is fine and the physical screen connection needs reflowing.
- **Everything was working, now blank**: Check if brightness was turned very low during a previous nighttime session — try SQUARE + several presses of +.
- **Normal boot time is ~20 seconds to the splash screen.** On rare occasions when SD card corruption is suspected, the Pi runs a filesystem repair on boot which can delay the splash screen by a few minutes. Once the scan/repair completes, subsequent boot times return to the normal ~20 seconds. When power-cycling a non-booting unit, wait at least 5 minutes before concluding failure.
- Can also be a screen solder connection issue (especially on DIY builds). Getting the screen solder right the first time can be tricky; reflowing all solder joints can fix it.
- After swapping SD cards, may need to reconfigure the camera type.
- **Screen header pin contact with USB/Ethernet ports**: On some units, the header pins on the underside of the UI board (screen board) can come into contact with the top of the USB/Ethernet ports on the Raspberry Pi when the faceplate screws are tightened. Symptoms: device works with faceplate screws loose but fails (no screen/keypad) when screws are fully tightened. This is distinct from a cracked solder joint — the tightening pushes the UI board down onto the Pi's port housings. **Fix**: Check the header pins on the underside of the UI board and trim them flush if needed; apply Kapton tape (or other heavy-duty tape) over the trimmed pins or on top of the Ethernet/USB ports as insulation. Richard now trims header pins flush and adds Kapton tape as standard practice during assembly. This has been a recurring issue — a few returns have been traced to this cause.

### Device Freezing
- If the screen/device freezes (becomes unresponsive), clarify whether the screen content is static or blank.
- Often related to SD card corruption or software crash.
- Try a power cycle (full off and on via the slide switch).
- If persistent, re-image the SD card.

### Shutdown
- **Recommended procedure**: Tools Menu → Shutdown, or quick shutdown: hold LEFT (1+ sec) → hold SQUARE → press DOWN for SHUTDOWN → press RIGHT to confirm.
- Screen and keypad turn off after several seconds; then safe to toggle power switch.
- Although shutdown is not strictly required before power-off, the PiFinder is a computer and there is a chance of SD card file corruption if you skip it.
- Some users report issues with clean shutdown; fixes that preserve the authentication system are in progress.

### Plate Solving Not Working
- The PiFinder needs a clear view of the sky to plate-solve.
- Works well in light-polluted skies (Bortle 6/7+, even Bortle 8 for LAAS sidewalk astronomy) but requires longer exposures. Default exposure is 0.2s; increase to 0.4s for very bright skies. For darker skies, use Auto exposure or set to 0.1 or 0.05s. **To enable auto-exposure**: select **AUTO** from the exposure menu. Enabling **Background Subtraction** can help in bright skies.
- Field of view is approximately 10 degrees (512×512 sensor with sub-pixel centroiding).
- For observatory use in a dome: the 10° FOV only needs a slit width of about 1.7 feet when 8 feet from the slit center.
- Pointing accuracy: ~0.01 degrees (~36 arcseconds). Can reliably place objects in the center of a 333× eyepiece.
- **Plate solving is orientation-independent** — works regardless of camera rotation or inversion. Star patterns are recognized in any orientation.
- **Star pattern database**: Built from the **Hipparcos catalog** (not the Yale Bright Star Catalog). Hipparcos provides much deeper coverage than the ~9,000 stars in Yale BSC; its lower magnitude bound is well-matched to the PiFinder's ~10° FOV. The camera picks up stars well below naked-eye limits, so a deeper catalog is needed than what BSC provides.
- **Plate solve vs IMU is exclusive** — the PiFinder uses either camera plate solving OR IMU estimation, never both simultaneously. When the camera can solve, that's the source of truth. During scope movement, IMU estimates are used as a fallback.
- **IMU → plate solve transition should be fast** — after the scope stops, the PiFinder should switch from IMU estimate (dim push-to numbers) to plate solve (bright numbers) in under 1 second. If it takes longer, check focus or try the AUTO exposure setting to optimize solve time.
- **Gamma and BG sub settings** only affect the preview image on screen — they have NO effect on plate solving performance.
- **Intermittent solving at dark-sky sites**: If solves are dropping out at a genuinely dark site with the scope stationary, focus is the most common cause. **High-thin clouds** are a real second possibility. Manual exposure targets at dark skies: **0.2s is very solid, 0.1s should work as well**. AUTO exposure is also worth trying.

### Upside-Down / Non-Standard Mounting
- **Plate solving works fine** when mounted upside down or at unusual angles — it's orientation-independent.
- **Accelerometer (IMU) estimates are the issue**: While the telescope is moving, images are too motion-blurred to plate solve, so the PiFinder uses its accelerometer to estimate pointing position. The current software expects right-side-up mounting, so these motion estimates will be incorrect when inverted.
- **Non-perpendicular mounting (tilted but not inverted)**: Degradation is very graceful. The closer to the ideal perpendicular orientation, the better the in-motion estimates. In practice, users won't notice any difference unless making big moves in azimuth, where the estimate may be off by a few degrees when stopping. Once the scope stops moving, plate solving gives an accurate position regardless of tilt.
- **Inverted/upside-down mounting**: More significant degradation — motion estimates will be substantially incorrect.
- **Once the scope stops moving**, plate solving kicks in and corrects any accumulated error from bad IMU estimates.
- **Workaround for inverted mounting**: Users can ignore the estimated position while slewing and stop periodically for plate solves, but it's a degraded experience.
- **Upcoming fix**: A new orientation-agnostic accelerometer method is in testing (as of March 2026) and will be released shortly as an experimental update. Once released, upside-down and arbitrary-orientation mounting will work seamlessly.

### Dew
- The ~5W heat dissipation from the internal computer acts as an effective dew heater. Even in heavy dew conditions, the PiFinder lens rarely dews up.

---

## Connectivity & Integration

### SkySafari
The PiFinder connects to SkySafari (and other planetarium apps) via WiFi using the LX200 protocol.

**SkySafari Setup Steps:**
1. Settings → Telescope → Presets → **+** (add new)
2. Telescope Type: **Other**
3. Scope Type: **Alt-Az GoTo** (even for push-to scopes — this enables sending targets from SkySafari to PiFinder)
4. Scope Model: **Meade LX200 Classic**
5. Address: **pifinder.local** (or IP from PiFinder's Status screen)
6. Port: **4030**
7. Save the preset

**Usage notes:**
- Select the Telescope icon on SkySafari's main screen and click Connect
- PiFinder initially sends 0° RA/DEC until the first plate solve completes
- Works with **SkySafari 5 Plus, 6, and 7** (7 is most reliable)
- SkySafari can lock the view to the scope's position
- SkySafari can send objects to PiFinder's observing list (useful alternative to keypad text entry)
- **Single connection limit**: Only one device/app can connect to the PiFinder's LX200 server at a time. If SkySafari is connected on an iPhone, it must be disconnected before connecting from an iPad (or vice versa).
- **SkySafari cannot connect to PiFinder and a GoTo mount simultaneously** — choose one
- **Sleep mode warning**: If PiFinder enters sleep mode, it stops sending position updates. Extend or disable the sleep timer if using SkySafari continuously.

**SkySafari Troubleshooting:**
- **Phone/tablet disconnects from PiFinderAP**: Some phones and tablets (iPads especially) will silently disconnect from the PiFinderAP WiFi network because it doesn't provide internet access. They can be pretty aggressive about switching to another network in the background if there is another network available, breaking the SkySafari connection. Fix: check WiFi settings and reselect the PiFinderAP network. This is the most common SkySafari connection issue.
- **Multiple PiFinders at star parties**: If two PiFinders on the field have the same network name (SSID), they can interfere with each other and cause intermittent SkySafari connection issues. Consider this when troubleshooting intermittent connectivity at star parties or club events.
- **".local" name resolution fails**: Use the numeric IP address from the PiFinder's Status screen (e.g., 10.0.0.xxx) instead of pifinder.local. The .local name resolution can be unreliable depending on the phone/network — it causes issues in circumstances that aren't fully understood, and 10.10.10.1 (in AP mode) or the numeric IP (in client mode) is a reliable fallback.

### Connection Protocols
The PiFinder supports multiple connection methods:
- **Web browser**: Interface, configuration, remote control (http://pifinder.local)
- **SSH**: Shell access for advanced users (user: `pifinder`)
- **SMB (Samba)**: File sharing for images, logs, observing lists (//pifinder.local/shared)
- **LX200 protocol**: Planetarium app integration (port 4030) — works with SkySafari, Stellarium, Guide 9, Cartes du Ciel (via ASCOM/INDI LX200 drivers), and any software supporting standard telescope control protocols
- **INDI support** is being added as part of GoTo mount integration (see below). Currently LX200 is the only supported protocol for planetarium apps.

### GoTo Mount Support
- As of May 2026, GoTo mount integration is **in active development** and Richard's working target is release within roughly a month (~June 2026).
- This will be a **software-only update** — all existing PiFinders will be compatible.
- Will support triggering and correcting GoTo moves. Plate solving is superior to encoders for large Dobs — self-correcting and immune to mechanical slippage.
- **Tracking**: GoTo tracking will use plate solved position + object position. Because it uses plate solving (not sidereal rate), it can track non-sidereal objects like comets that don't move at sidereal rate.
- **Targeting INDI**: Any mount that offers INDI drivers will be supported. This includes the ZWO AM5, OnStep-based mounts, and many others.
- **Currently seeking testers** with experience in Linux and command-line tools to install the testing version of the software.
- **ServoCat (retired)**: ServoCat integration was specifically part of the GoTo development effort, but this ended when the **ServoCat company closed down**. No longer an active target. A path forward for existing ServoCat/ServoFi owners would require a community-built INDI driver for ServoFi.
- **OnStep focus**: OnStep is a more modern and popular solution for Dobsonian mechanization. GoTo development is continuing with OnStep support as a primary target.
- Mounts accessible via WiFi will work natively. USB→Serial cable connection is possible for older serial-only mounts but requires more setup.
- **Celestron vs Sky-Watcher note**: Sky-Watcher mounts allow sidereal tracking without alignment (can use PiFinder for push-to while tracking). Celestron requires full alignment initialization before enabling tracking.
- Integration with SkySafari as an interface option is planned.

### Equatorial Mount Support
- EQ support in the PiFinder is currently **functional but being improved**.
- **Plate solving** works perfectly on EQ mounts when the scope is stationary — same accuracy as Alt/Az.
- **EQ Mode setting**: When using the PiFinder on an **EQ mount**, switch it into **EQ mode** so push-to directions are presented as degrees to move in **RA/Dec** rather than Alt/Az. **Critical distinction**: EQ Mode is for **EQ mounts**, NOT for **alt-az scopes (Dobs, etc.) sitting on an EQ tracking platform**. A platform user still operates the scope in alt-az; the platform rotates around a polar axis to track. EQ mode is not for platform users — plate solving handles the platform's orientation changes automatically and push-to should stay in Alt/Az.
- **IMU estimates degrade** on EQ mounts because the accelerometer code is optimized for Alt/Az motion and does not always generate good estimates for EQ axis motion. Practical impact: while the scope is moving on an EQ mount, push-to numbers won't be as accurate as they are on an Alt/Az scope. Once the scope stops, the camera captures images and the plate solver updates with the correct position. Use a **"move, stop, check, adjust"** approach.
- **EQ mount update — testing complete** (as of April 2026): Updated code to turn accelerometer movements into accurate sky position estimates across any scope motion type is **complete and will ship in the next software release**. The new system produces more accurate estimates across **all motion types** (including Alt/Az), not just EQ. Once shipped, this code **completely removes the need for any particular mounting orientation** (the long-standing "perpendicular to the ground" guidance becomes obsolete).
- **Drift-based polar alignment**: Planned as a follow-on feature after the EQ mount motion update. Has proven to work well in testing. For rough polar alignment in the meantime, users can use the RA/DEC coordinates display to point the scope at the celestial pole.
- **Equatorial platforms**: Work well. The PiFinder continually corrects for orientation changes via plate solving. Slight IMU drift between solves is corrected each time the scope stops.
- For SkySafari with EQ platform/mount: Still set up as GoTo scope. Can choose RA/DEC or Alt/Az — the only difference is the reticle orientation in SkySafari.


---

## DIY Build Support

### Recommended Hardware
- **Raspberry Pi 4B 2GB** (higher memory acceptable but unnecessary). The Raspberry Pi Foundation has committed to manufacturing Pi 4 variants through 2033. Pi 5 compatibility is targeted for end of 2026 for DIY users, but the project will remain based around the Pi 4 for the foreseeable future.
  - **Pi 3B+ will NOT work** — PiFinder uses one of the **additional serial ports introduced in the Pi 4** for GPS communication. A Pi 3B+ does not have these extra UARTs, so the GPS won't communicate even if everything else looks fine. When "GPS not working" appears on a board that's working otherwise, **confirm which Pi model is in use** before going deeper.
  - **Identifying the Pi model**: The Raspberry Pi 4 has **always had USB-C** for power input (since its initial release). "Older Pi 4 before they switched to USB-C" is a red flag — that's likely a **Pi 3B+** (which uses micro-USB for power). The Pi 3B+ is otherwise physically similar to the Pi 4 at a glance, so the confusion is understandable.
- **Camera**: innomaker imx296 (mono) or imx462 (color) — either performs similarly; choose based on availability
- **Lens**: 16mm F2 CCTV Lens (M12 mount) — provides ~10° field of view. e.g., https://www.amazon.com/dp/B07VDWNSG9
- **Display**: Waveshare 1.5" RGB OLED
- **IMU**: Adafruit BNO055 Fusion Breakout — specifically **Adafruit product 4646** (STEMMA QT version). Note: Adafruit also sells **product 2472**, a physically similar but different product with a different pinout (pins 4 and 5 / VIN/3V3 swapped) — the PiFinder has always used the 4646. The BNO055 is the underlying Bosch Sensortech IMU chip and many companies make breakouts for it.
- **GPS**: GT-U7 GPS Transceiver board
- **Switches**: 17× Diptronics DTS63K or Apem ADTS63KV (6×6mm × 7mm PCB momentary, 4-pin DIP)
- **LEDs**: 17× Red 1.8mm miniplast LEDs (must be 2.5W × 3.3L × 3H dimensions)
- **Case hardware**: 22× M2.5×4mm brass heat-set inserts, 20× M2.5×8mm bolts, 4× M2.5×20mm standoffs, 7× M2.5×12mm bolts
- **Full BOM**: https://pifinder.readthedocs.io/en/release/BOM.html
- **DIY v2.5 board schematic** (PDF): https://github.com/brickbots/PiFinder/blob/release/PiFinder_schematic.pdf — reference for probing specific points (GPIO header, GPS lines, etc.).

### Common Build Issues
- **Screen soldering**: Can be tricky. Remove the connector plug by cutting leads low, then clip away plastic. Sand or cut bottom tabs for better top plate fit. Not uncommon to not get it right the first time.
- **IMU green LED**: The Adafruit BNO055 has an annoyingly bright green LED. Cover with several layers of black nail polish, or use soldering iron to destroy it.
- **PiSugar blue power LED**: Also very bright — cover with black nail polish.
- **PiSugar model compatibility**: Only the PiSugar S Plus is compatible. Other models interact with the I2C bus and cause IMU communication issues.
- **PiSugar Auto Startup switch**: Must be set to **OFF** for i2c/IMU to function properly. **Verification method after a PiSugar swap**: Use **Tools → Status** page and confirm it reads **static/moving** state and shows the **IMU readout values changing** as the scope is moved. If the Auto Startup switch is set incorrectly, the IMU won't function and Status won't update.
- **PiSugar swap procedure**: (1) Power off and unplug any USB-C. (2) **Remove the camera module first** — unscrew the two screws holding it in, then gently slide back the grey clip on the cable connector to free the cable. The v2.5 upgrade docs (`https://pifinder.readthedocs.io/en/release/v25_upgrade.html`) are a good reference for the connector mechanics — different module, but same connector. (3) Open the case to expose the Pi+PiSugar stack — v3 assembly doc has photos: `https://docs.google.com/document/d/1qPrIb4E8s5cmlWeev730kk9axFQ7yM9QXBx4Yvpj7oE/edit?tab=t.0`. (4) Unplug the battery cable from the old PiSugar. (5) Unscrew hexagonal standoffs; old PiSugar lifts off the GPIO header. (6) **On the new PiSugar, flip "Auto Startup" to OFF before installing.** (7) **Clip off or cover the new PiSugar's power light** — bright and annoying; details in the v3 assembly guide electronics tab. (8) Press onto GPIO header, re-secure standoffs. (9) Reconnect battery cable, lying flat and fully seated. (10) Close up and power on to confirm boot+charge. The **camera ribbon cable is the most delicate item in the workspace**.
- **Post-swap bench tests on the PiSugar/battery system**: (1) confirm the **blue charging light** comes on when power is plugged into the PiSugar board, and (2) confirm the **on/off switch functions** as expected (clean transitions between states).
- **GT-U7 GPS yellow headers**: Have a varnish coating that resists solder. **Failure mode is sneaky** — joints can look good while the solder is actually sitting on top of the varnish without making electrical contact. Most common cause when GPS data won't come through on a DIY build. Two fixes: (1) Reflow each joint aggressively with extra heat and flux to break through the varnish, or (2) replace the yellow headers with standard 0.1" pitch header strips. Swapping the yellow headers for standard strips is recommended because the included headers are troublesome.
- **GPS solder order**: Solder the GPS module **after** testing the backlight LEDs — the GPS blocks access to some LED pins.
- **SQUARE key stuck**: If the software behaves as if the SQUARE key is being held down after assembly, check the keypad connections. This causes abnormal menu behavior.
- **Any switch appears stuck / menu fights you**: Almost always a bridged solder joint, either at the GPIO header or between one of the switch legs. **Important**: Due to the matrix wiring of the keypad, the stuck button displayed may not be the one with the actual bridge — check ALL switch joints and both sides of the GPIO header carefully.
- **Screen glitching / freezing (DIY builds)**: Check all screen solder joints, especially the **GND connection** (second pin from the top of the screen header). Poor GND contact causes display corruption and freezes.
- **Boot failure / power issues (DIY builds)**: Before assuming hardware failure or SD card corruption, **try a different USB-C cable and power source first**. Bad cables and inadequate power supplies are a very common source of wasted troubleshooting time on new builds.
- **Camera type**: Must be set correctly in software settings. If camera displays no image, the type selection is likely wrong.
- **Camera pin headers**: Some cameras come with pin headers installed — clip them as close as possible to the board before mounting.
- **Lens focus starting point**: Target a 6mm gap between the top of the lens holder and the bottom of the lip on the lens.

### 3D Printing Specifications
- **Print settings**: 3 perimeter layers, 15% infill (parts are small and don't bear heavy loads)
- **Material**: Avoid PLA (UV degradation). Use PETG or co-polymers like NGen. **Prusament Galaxy PETG is the official PiFinder filament.**
- **Heat-set inserts**: M2.5×4mm brass. Insert temperature should be below normal printing temp (e.g., for PETG printed at 230°C, use 170-200°C for inserts). On the **assembled v3 case**, the heat-set inserts live in the **camera_mount** (not the shroud_back). When sourcing replacement parts after a damaged unit, the camera_mount is the part that needs the inserts; the shroud_back does not.
- **Threaded camera holddown (`v25_camera_holddown.stl`, M12×0.5)**: Printing proper threads at this size is hard for many printers. An alternative approach is to print a part with a smaller diameter and **cut threads in using a tap**, rather than relying on printed threads. Whether printed threads work well is printer-specific.
- All models are licensed under **GNU GPL** — users and retailers are free to print/modify them.
- STL files are available for custom adapters.

### Mounting
- **Dovetail mount**: Standard 32mm Synta/Vixen-style dovetail compatible with typical finder shoes. Allows up to 40° adjustment from horizontal. The tilt-adjustment piece (the 3D-printed part between the dovetail foot and the PiFinder body) has been redesigned to be more adjustable and more robust than earlier versions.
- **Updated adjustable foot (released mid-2025)**: Distinguished by a **larger M5 bolt** through it.
- **Adjustable foot screw hardware (v2.5 vs new foot)**: The **old adjustable foot used 2× M2.5×12 screws**; the **new (mid-2025) adjustable foot uses the included M5 hardware**. STL files for the new foot live in `case/v3/common`, but were not back-ported into the `v2.5` directory of the repo — so v2.5 DIY kit builders looking only at the v2.5 STLs will see the old foot. The new foot in `case/v3/common` is more adjustable and robust.
- Device must mount **close to perpendicular to the ground** for accurate IMU positioning estimates. Mount on the telescope tube (OTA), not the mount itself.
- **GoPro-compatible plate** and **Rigel Quickfinder adapter** are available as alternative mounts.
- **Obsession UC telescopes**: Custom 3D-printed tube clamps are designed for tubes **parallel to the light path**, not angled truss poles. For UC series scopes with a single UTA ring, the standard mounting locations are the **handle tube** or **counterweight tube** that protrude from the ring (where a Telrad is normally mounted). For the handle, remove a bit of foam from the end closest to the ring to make room for the clamp while preserving usable handle. Handle and counterweight tubes have **different outer diameters** — measure whichever location is chosen. For scopes with **two UTA rings**, clamps can go between the two rings on the parallel tubes. **Drilling/tapping holes in the ring** to add a mount point is an option but is much more in the DIY part of the spectrum. For angled truss poles, the parallel-tube requirement applies — use the handle/counterweight/inter-ring options rather than an angled clamp. Pole diameters vary by model — 30mm, 38mm, etc. STL files available in the GitHub repo. Note: The UC18 upper ring can be mounted either way (reversible orientation), which can help position the finder shoe on the desired side. **However, flipping the UC18 upper ring has in at least one case made the secondary impossible to collimate (off by a few millimeters); restoring the original ring orientation restored collimation.** The handle/counterweight tube clamp is the safer default.
- **Truss tube Dobs**: Custom 3D-printed tube clamps designed for tubes **parallel to the light path** — typically handles, counterweight tubes, or inter-ring tubes rather than angled truss poles.
- **Telrad base mounting**: A Telrad base with a 2" Telrad riser and a finder shoe from Scopestuff or Agena can work as a PiFinder mount.
- **Custom mounts**: Custom 3D-printed mounting solutions can be made for non-standard scopes (Mak scopes, side-saddle mounts, etc.).
- **Dovetail foot breakage**: The 3D-printed dovetail foot is a known stress point, especially at the screw holes.
- **Longer dovetail foot (printable STL in repo)**: A slightly longer version of the dovetail foot is available in the PiFinder repo as a printable part. It includes the capability to add a **hard-stop** to keep the PiFinder from sliding out of the finder shoe if the thumbscrews aren't fully engaged. The longer foot also improves **repeatability of placement and alignment**.
- **Dovetail foot thumbscrew wear**: The printed surface of the dovetail foot picks up small indentations from finder-shoe thumbscrew tips over time. This is **aesthetic only and does not affect performance**.

### Carrying / Protective Case
- No purpose-built PiFinder case exists yet.
- **Recommended**: **Nanuk 908** — a small padded case that fits the PiFinder well.
- Other options: small padded camera accessory pouches or eyepiece cases.

### Kit Contents
- The kit includes: UI module (electronics), 3D printed parts, screws, and faceplate
- A dovetail foot for mounting in finder shoe is included
- Special mounting options (e.g., 1/4"-20 tripod thread) are available

### Headers for DIY Builds
- The main header to source separately is a **2x20 (40-pin) stacking female header** with long pins for the Pi connection (needs to clear the heatsink).
- The **Adafruit BNO055 IMU** module comes with enough header strip for both the IMU and the screen.

### 3D Printed Parts Quality
- Some variation is normal in 3D printed parts. The front shroud piece has a tendency to warp due to its mass during cooling.

---

## Object Catalogs

### Available Catalogs
Descriptions at: https://pifinder.readthedocs.io/en/release/catalogs.html

| Code | Catalog | Notes |
|------|---------|-------|
| **NGC** | New General Catalogue | NGC 2000.0 (Dreyer/Sinnott) |
| **IC** | Index Catalogue | |
| **M** | Messier | 110 objects |
| **C** | Caldwell | |
| **Col** | Collinder | 471 open clusters |
| **Ta2** | TAAS 200 | Intermediate deep sky; visible from central New Mexico (dec > -48°) |
| **H** | Herschel 400 | Selected from William Herschel's original catalog |
| **SaA** | SAC Asterisms | Saguaro Astronomy Club Asterisms Database v3.2 |
| **SaM** | SAC Double Stars | 2,162 double stars (Saguaro v4.0) |
| **SaR** | SAC Red Stars | Red Stars Database v2.0 |
| **Str** | Named Bright Stars | Useful for aligning GoTo scopes |
| **EGC** | Extra-Galactic Globulars | Globulars near galaxies (primarily Andromeda) visible in amateur scopes |
| **RDS** | RASC Double Stars | 110 targets visible from northern hemisphere |
| **B** | Barnard's Dark Objects | 349 dark nebulae |
| **Sh2** | Sharpless | 313 H II regions (emission nebulae), comprehensive north of dec -27° |
| **Abl** | Abell Planetary Nebulae | 79 confirmed planetary nebulae |
| **Arp** | Atlas of Peculiar Galaxies | Galaxies with distinctive morphology |
| **Harris** | Globular Clusters in the Milky Way | Harris catalog of Milky Way globulars |
| **WDS** | Washington Double Star Catalog | Full catalog, ~130,000+ double star pairs. Too many to scroll, but searchable by name (type WDS designation) or sortable by Nearest from current pointing direction to find doubles near where the scope is aimed |

- **Planets catalog**: Only initializes after GPS lock is achieved (needs time/location data).
- **Comets**: Users have requested adding comets. Check documentation for current support.
- **Double stars**: PiFinder includes the **full Washington Double Star Catalog (WDS, ~130,000+ pairs)** plus two curated lists — **SaM** (SAC Doubles, 2,162) and **RDS** (RASC Doubles, 110). For WDS, the list view is too long to scroll, so use **search-by-name** with a WDS designation or pull up WDS and sort by **Nearest** from the current pointing direction.
- **HD and SAO catalogs**: Not included in the PiFinder's built-in database. Searches for HD/SAO designations will often yield no results, though a few of these stars are included as parts of other catalogs (so some may be found). Double star entries use their own catalog designations (e.g., Struve identifiers like STF and STT in the SAC doubles). Workaround: connect SkySafari, find the star by HD/SAO number there, and use SkySafari's "GoTo" to push the target to the PiFinder for push-to guidance.
- **Quasars**: Not currently built in. The Million Quasar Catalog is being added by a community contributor (as of March 2026). For large aperture scopes (e.g., 30"), this could yield between 1,000 and 80,000 potentially visible quasars depending on limiting magnitude cutoff.
- **Adding new catalogs**: New catalogs are regularly added by the community. The underlying database makes adding catalogs relatively straightforward, even for first-time contributors.
- **User-supplied catalogs/observing lists**: In development. The feature will accept lists exported from planning software *or* hand-assembled spreadsheets — customers drop them into the PiFinder's shared storage (SMB) and they appear in the menus alongside the built-in catalogs. Target: "the next few months, in the release after the next one" (as of May 2026).

### Object Search
- Use number keys pressed multiple times to cycle through letters (phone-style text entry) for name searches.

### Known Data Issues
- Some objects may be incorrectly categorized in the Steinicke dataset (e.g., NGC 7006 was incorrectly marked as an irregular galaxy instead of a globular cluster).

---

## Frequently Asked Questions (Quick Reference)

**Q: Which PiFinder version should I get?**
A: Depends on scope type and mounting height. For refractors/SCTs/rear-focus scopes mounted below head height, Flat is a great option (screen/keypad back and slightly up, easy from the focuser). If the tube top is too high to see the screen, Left or Right works well. For Dobs, Left or Right matching your focuser side. One PiFinder works on all your scopes.

**Q: Do I need a finder scope or Telrad with the PiFinder?**
A: Not for observing — once aligned with your scope's optical axis, the PiFinder replaces traditional finders completely. But a zero-power finder (red dot / Telrad) is **useful for the initial digital alignment**: the alignment step requires getting a bright star into the **eyepiece** of the scope (not just the PiFinder's camera field), so you can then select that star on the PiFinder's screen to establish the offset between the camera and the scope's optical axis. A zero-power finder makes it easier to aim the scope precisely enough to land the star in the narrow eyepiece field. After that first alignment, it's not needed for the rest of the session. If a Telrad is already mounted and there's concern about it blocking PiFinder access, it only needs to be in place at the start of the session.

Don't confuse the PiFinder's 10° camera FOV with what alignment requires — the camera just needs to see the sky for plate solving, but the alignment star needs to be **in the eyepiece** so the user can click the matching star on the chart.

**Q: Does it work in light-polluted skies?**
A: Yes. Works well in Bortle 6/7 with longer exposure times. Very tolerant of light pollution. Default exposure is 0.2s. For bright urban skies (Bortle 8+), increase to 0.4s. For darker skies, use Auto exposure or manually set to 0.1 or 0.05s.

**Q: What about extreme temperatures?**
A: Tested from -15°C/5°F to 40°C/100°F. Like all electronics, battery life decreases in cold.

**Q: Does it need a cable?**
A: The PiFinder has two USB-C ports. It does not come with a cable. Use any standard USB-C cable for charging (top rear port) or power-only (port near keypad).

**Q: Can it work with GoTo mounts?**
A: GoTo integration is in active development (as of April 2026). It targets INDI, so any mount with INDI drivers will be supported (AM5, OnStep, and many others). OnStep is a primary focus for Dobsonian mechanization. Expected to release as a software-only update within a few months. Testers with Linux/command-line experience are welcome. GoTo tracking will use plate solved position + object position, which also enables tracking non-sidereal objects like comets. Note: ServoCat integration was previously part of this effort but ended when the ServoCat company closed down; a path forward for ServoFi owners would require a community-built INDI driver. In the meantime, PiFinder works great for push-to use on GoTo mounts — users can use the hand controller or push the OTA by hand to find objects.

**Q: How do I update the software?**
A: From the PiFinder menu: **Tools → Software Upd**. Also accessible via the web interface at http://pifinder.local → Tools → Software Upd. The PiFinder must be in Client mode connected to a WiFi network with internet access. If the version shows "unknown," it means there's no internet connection. Re-imaging the SD card is an alternative but should not be the first step for update issues. When re-imaging, use Raspberry Pi Imager with "Use Custom" and do NOT set hostname or username/password. Default documentation link: `https://pifinder.readthedocs.io/en/release/user_guide.html#update-software`.

**Downloadable PDF manual:** The ReadTheDocs documentation is also available as a downloadable PDF (though not as polished as the web version). It can be accessed via the **Releases menu** in the lower-right corner of the ReadTheDocs site. For printing or a hardcopy manual, the PDF download is the best option; browser print scaling is a secondary option.

**Q: What's the default web password?**
A: `solveit` (all lowercase, one word). If it doesn't work, re-imaging the SD card will reset it.

**Q: Can it work in an observatory dome?**
A: Yes, but GPS lock may be difficult indoors. Experimental manual location/time entry features exist. The 10° FOV needs only a small slit opening.

**Q: How accurate is it?**
A: ~0.01 degrees pointing accuracy.

**Q: Is the software open source?**
A: Yes. The PiFinder software supports the official hardware. The code can be modified to work with different hardware, but as distributed it only supports PiFinder hardware.

**Q: Where can I find the parts list?**
A: https://pifinder.readthedocs.io/en/release/BOM.html — includes complete BOM with links.

**Q: Camera lens spec?**
A: 16mm F2 CCTV Lens, M12 mount. Provides ~10° field of view. Both v3 assembled and v2.5 DIY use the same lens. **Important:** The camera module ships with its own stock lens (wrong focal length for PiFinder). The correct 16mm F2 lens is a separate item in the kit. A lens with no markings/text is likely the camera module's stock lens installed instead of the PiFinder's 16mm. The correct lens has visible text/markings on it. **Note:** The build guide section on lens installation is known to be sparse and has some outdated photos — this is a common source of confusion for kit builders who miss the lens swap step.

**Q: How do I adjust screen brightness?**
A: Hold SQUARE and press + for brighter or - for dimmer. Works for both screen and keypad.

**Q: How long does the battery last?**
A: The PiSugar S Plus (5000mAh) is good for 4-5 hours, but runtime is highly activity-dependent — sitting at the eyepiece on one object or walking away from the scope puts the PiFinder into a lower-power mode and extends runtime; a fast tour through many objects (active UI + IMU + camera + screen) draws more power and shortens it. The unit will abruptly shut off when charge is depleted (no on-screen battery indicator, no graceful low-battery shutdown). Battery life decreases in cold weather. For longer sessions, a USB-C power bank can be hot-plugged while running.

**Q: How do I access my observation logs and images?**
A: Via SMB network share at //pifinder.local/shared (connect as guest, no password). Contains captures/, obslists/, screenshots/, and observations.db.

**Q: What 3D printing material should I use?**
A: Avoid PLA (UV degradation). Use PETG or co-polymers like NGen. Prusament Galaxy PETG is the official PiFinder filament. Settings: 3 perimeter layers, 15% infill.

**Q: Can I connect SkySafari to the PiFinder?**
A: Yes. Add as Other → Alt-Az GoTo → Meade LX200 Classic. Address: pifinder.local, Port: 4030. Works with SkySafari 5 Plus, 6, and 7 (7 is most reliable). Also works with Stellarium.

**Q: How much does it weigh?**
A: ~370g with battery, ~290g without. Similar to a Telrad with batteries (315g) and lighter than many 50mm RACI finders.

**Q: What are the dimensions?**
A: Left/Right: ~110×100×90mm. Flat: ~110×120×120mm. Plus mounting foot.

**Q: Can I use 12V telescope power?**
A: Yes, but do NOT run 12V directly into the PiFinder — it expects 5V USB-C. Use a 12V-to-5V USB-C DC-DC step-down converter (e.g., https://www.amazon.com/gp/aw/d/B09DGDQ48H). Use a good quality cable for longer runs.

**Q: Does it work on very large telescopes?**
A: Yes. Works well on 18", 22", 25", 30"+ Dobs. For tall scopes, mount PiFinder on the OTA and use SkySafari or web interface from ground level for push-to guidance.

**Q: Can I enter custom RA/DEC coordinates?**
A: Yes (v2.3.0+). Useful for asteroids, newly discovered objects, or targets from publications. You can also send targets from SkySafari, and the chart screen displays the current pointing position in RA/DEC for ad-hoc panning to known coordinates without push-to setup.

**Q: Does it work on equatorial mounts?**
A: Yes, with caveats. Plate solving is fully accurate when stationary. Switch the PiFinder into **EQ mode** so push-to directions show in RA/Dec rather than Alt/Az. While the scope is moving on an EQ mount, push-to numbers are less accurate than on an Alt/Az scope — use a "move, stop, check, adjust" approach. Works well with EQ platforms. The IMU update for EQ motion is testing-complete and ships in the next release; drift-based polar alignment is planned as a follow-on.

---

## Troubleshooting Quick Decision Tree

```
Issue: Device won't turn on
├─ Check slide switch position (slides, not pushes)
├─ Try USB-C external power
├─ Check if battery is charged
└─ If DIY build: verify PiSugar board connections

Issue: Blank screen
├─ Try SQUARE + several presses of + (brightness may be very low from nighttime)
├─ Check if keypad backlight is on:
│  ├─ No keypad light: SD card or power issue → re-image SD card
│  └─ Keypad on but screen blank/garbled: solder joint issue → reflow solder
├─ Wait several minutes (filesystem repair can delay boot)
├─ Check screen solder connections (DIY builds)
└─ Verify camera type setting after SD card swap

Issue: No plate solve / camera not working
├─ Verify camera type is correct (imx462 vs imx296 vs imx477)
│  └─ After changing camera type: FULL POWER CYCLE required (not just restart)
│  └─ Software updates can reset camera type — check after updating
├─ Verify lens cap is removed
├─ Check lens focus (Start → Focus screen, use +/- to zoom) — #1 cause of plate solve failure, especially under brighter skies
├─ Check exposure setting — try longer exposure for brighter skies; select AUTO from exposure menu for automatic adjustment
│  └─ For v2 lenses: verify aperture ring is fully OPEN (separate from focus ring)
├─ Ensure clear sky view (not indoors/obstructed)
├─ Try enabling Background Subtraction in light-polluted areas
├─ Check for lens condensation/dew
├─ Verify correct lens is installed — v3 pre-assembled units ship with the correct 16mm F2 lens already installed. For DIY builds, the camera module ships with its own stock lens (no markings, wrong focal length); the correct 16mm F2 lens is a separate kit item with visible text/markings. A different lens spec is likely based on v2 documentation which used a different camera/lens. A side photo showing lens markings confirms which lens is installed.
├─ Camera ribbon cable kinks: generally NOT a concern — ribbon cables tend to either work or not work entirely. A kinked cable won't cause partial/degraded images, so it's not a likely cause of image quality issues.
├─ Ensure PiFinder is stationary (plate solving requires still images)
├─ Check that sleep mode hasn't engaged (camera icon disappears)
└─ Re-image SD card if camera was previously working

Issue: GPS won't lock
├─ Point scope toward horizon (GPS antenna is directional — at zenith it points sideways)
├─ Move to area with clear sky view
├─ Check camera ribbon cable routing (keep away from GPS module — RF interference)
├─ Try at night (GPS signals stronger — sun creates atmospheric interference)
├─ Check antenna connection (plug fully affixed, rotates freely when engaged)
├─ Use dedicated GPS screen (Start menu — reduces EM noise from camera)
├─ "Many seen, 0 used" = antenna defect
├─ For v1 units: set GPS type to "Generic" (not UBLOX)
├─ Power cycle after changing GPS settings
└─ Indoors: use manual location/time entry via web interface pencil icon

Issue: "Unknown" software version / can't update
├─ PiFinder needs internet access to check version
├─ If in AP mode: configure WiFi client mode first
├─ If in client mode: check WiFi config, move closer to router
├─ Delete and re-enter WiFi credentials (check for typos)
└─ Do NOT re-image SD card for this — it's a connectivity issue

Issue: Can't connect to web interface
├─ FIRST: confirm device is connected to the PiFinderAP WiFi network (PiFinder in AP mode)
├─ Try http://pifinder.local (must be http://, NOT https://)
├─ In AP mode, try http://10.10.10.1 (or http://10.10.10.1/) as fallback
├─ Default password: solveit
├─ Try different browser (Chrome on Windows can fail; try Edge)
├─ Check phone hasn't auto-disconnected from PiFinderAP (no internet)
└─ Re-image SD card to reset password

Issue: Device rebooting/crashing
├─ Test on BOTH battery and external USB power:
│  ├─ Reboots on both: likely SD card issue → re-image
│  └─ Reboots on battery only: battery/power control board issue
├─ Check PiSugar ribbon cable is fully seated
├─ If persistent: send unit back for diagnosis
└─ May be power control board issue

Issue: Buttons not working as expected
├─ Button mapping changed in recent software
├─ ABCD = Arrow keys (B=Up, C=Down, D=Select, A=Back)
├─ Right side = +/- (not up/down)
└─ Request updated faceplate if needed
```

---

*Product details and feature availability may have changed since this document was compiled. Always check https://pifinder.io and https://pifinder.readthedocs.io for the latest information.*
