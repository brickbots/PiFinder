Troubleshooting & FAQ
=====================

.. note::
   This page applies to v3 and v2.5 PiFinders running software |min_software| or above.  If you're on
   older software, updating is often the fix in itself — see
   :ref:`user_guide:update software`.

Most PiFinder hiccups have a quick fix, and the cause is usually something simple —
focus, or a settings mismatch — rather than a fault.  This page is organised by
*symptom*: find the line that matches what you're seeing and follow it to the cure.
If your symptom isn't listed, or a fix doesn't sort it out, the PiFinder community on
the `Discord server <https://discord.gg/Nk5fHcAtWD>`_ is quick to help.


The PiFinder won't turn on
--------------------------

Power is a small white **slide switch** on top of the unit, above the screen — it slides
side to side, not a push button.  Facing the screen, slide right for on, left for off.
(The **SQUARE** key never controls power.)

Things to check:

- **Is the battery charged?**  There's no battery-level indicator on screen, so plug in
  to charge if you're unsure.  The charging light glows blue while charging, green when
  full.
- **Try external power.**  Plug a USB-C cable into the port closest to the keypad.  That
  port powers the unit *immediately, regardless of switch position* — so if the PiFinder
  runs this way but not on battery, the trouble is the battery or the switch, not the
  computer.
- If you built your own unit and it won't power up at all, double-check the PiSugar
  battery board connections.


The screen is blank, or it won't finish booting
-----------------------------------------------

Rule out the simple explanations first:

- **Brightness turned all the way down.**  If the PiFinder was last used at a dark site,
  the screen may be dimmed to nothing.  Hold **SQUARE** and tap **+** several times to
  bring it back.
- **Give it time on the first boot.**  A normal start-up reaches the welcome screen in
  about 20 seconds.  The *first* boot after re-imaging takes a minute or two and restarts
  itself several times while it sets up — that's expected.  Wait a full five minutes
  before deciding something is wrong.

If the screen is still blank, the keypad backlight tells you where the problem is:

- **No keypad light and no screen** (a faint red LED inside the case means the Pi has
  power but isn't booting): this is almost always **SD card corruption**, the most common
  hardware issue.  Re-image the card with the latest release, or request a fresh one.  SD
  card faults are all-or-nothing — they stop the PiFinder booting rather than causing
  subtle misbehaviour, so don't re-image to explain slow solves or the occasional position
  jump.
- **Keypad lights up, but the screen is blank or garbled**: that points to the screen's
  connection, not the software.  Confirm it through the
  :ref:`web interface <connectivity:web interface>` — if the remote screen looks correct
  there, the software is fine and the physical screen connection needs attention (a solder
  reflow on DIY builds).

For re-imaging instructions, see :ref:`user_guide:update software` and the
:doc:`software` page.


The camera view is blank or black
---------------------------------

If the Focus screen shows nothing at all — not even faint noise with the lens cap on —
the **Camera Type** setting probably doesn't match the camera in your unit.

- Open Settings → Advanced and try a different Camera Type.  The v3 sensors are ``imx462`` and
  ``imx296``; older v2 cameras are ``imx477``.  It won't hurt to try each.
- **After changing Camera Type you must fully power the PiFinder off and on** — a software
  restart alone won't apply it.
- A software update can quietly reset this setting, so re-check it after you update.

A healthy camera shows at least faint noise with the lens cap on, and a brighter image in
daylight — use that to confirm the camera is alive before chasing focus or exposure.


It won't plate solve ("can't find stars")
------------------------------------------

Plate solving is how the PiFinder works out where it's pointed (see
:ref:`quick_start:setting focus & first solve`).  When it won't solve, **focus is the
cause far more often than anything else** — and stars that look fine at normal zoom are
often not tight enough.

Work through these in order:

- **Focus, properly.**  On the Focus screen, use **+/-** to zoom to 2x and 4x and rotate
  the lens until the stars are as small as you can make them.  The difference between fair
  and good focus is less than half a turn, so work in steps of an eighth to a quarter of a
  turn with a pause for vibration to settle, and judge by the HFD readout rather than the
  camera icon, which lags a second or so behind each change of the lens.  Tight focus
  matters *even more* under bright, light-polluted skies, where slightly soft dim stars
  vanish into the background.  If you're starting from way off, set the lens so about 6 mm
  of thread is showing — roughly a pencil's width — which is close to in focus.
- **Lens cap off, and hold still.**  The PiFinder can only solve a sharp, stationary
  image.
- **Exposure.**  The PiFinder defaults to **AUTO**, setting the exposure itself from each
  solve — leave it there unless you have a reason not to.  To set it by hand, 0.2 s suits
  most skies, bright urban skies want 0.4 s, and dark skies solve well at 0.1 s.
  (Software older than 2.2 doesn't have the AUTO option — another reason to update.)
- **High, thin cloud.**  An invisible drifting cloudbank will stop solves at an otherwise
  perfect site.  If solves come and go while the scope is dead still, suspect the sky
  before the hardware.

.. note::
   On older v2 cameras the lens has two rings — a focus ring and an aperture ring.  The
   **aperture must be fully open** for the PiFinder to see enough stars to solve.


An object has "disappeared" from a list (for example, M45)
----------------------------------------------------------

Objects are never deleted.  If something you expect is missing, it's being hidden by an
active **filter** — magnitude, altitude, type, observed status, or which catalogs are
selected.  To bring everything back, open the Filter menu and choose **Reset All**.  See
:ref:`user_guide:filters` for what each filter does.


The chart or Push-To directions look backwards
----------------------------------------------

If the star chart appears mirrored, or the Push-To arrows consistently send you the wrong
way, the likely cause is the **PiFinder Type** setting not matching how your unit is
mounted — for example, set to Right when it should be Left.  This setting tells the
PiFinder its orientation, driving both the chart and the Push-To directions.  Set it to
match your hardware under Settings, as described in
:ref:`Configuration Setup <quick_start:configuration setup>`.

.. note::
   The clockwise / counter-clockwise Push-To arrows are also *configurable* to suit how
   you picture turning your scope.  If only the left/right (azimuth) direction feels
   reversed, try flipping that preference in Settings rather than changing the PiFinder
   Type.


"Is this normal?"
-----------------

A few PiFinder behaviours surprise people into thinking something is broken.  These are
all expected:

- **The alignment reticle isn't centred.**  The Telrad-style reticle on the Align screen
  shows where your scope points *within* the camera's wide 10° view — it isn't meant to
  sit in the middle, and a reticle off to one side is normal.  See
  :ref:`quick_start:alignment`.
- **The star chart is "zenith up", not eyepiece-matched.**  The on-screen chart is a
  naked-eye view, oriented as you'd see the sky looking up, so it won't match the flipped
  or rotated view through your eyepiece.  The object *image* previews, by contrast, are
  rotated to match the eyepiece.
- **Push-To numbers dim while you move the scope.**  While moving, the PiFinder estimates
  position from its motion sensor and dims the numbers to say so; the instant you stop, it
  takes a fresh photo, the numbers brighten, and the position is exact again.  (This is
  separate from the whole screen dimming in power-save mode.)
- **The charging light is slow to turn green.**  Near a full charge the current tapers
  off, so the final stretch from blue to green takes a while.  That's normal, not a fault.


Frequently Asked Questions
--------------------------

**Do I still need a finder scope or Telrad?**
   Not for finding objects — once aligned to your scope, the PiFinder replaces a
   traditional finder.  A zero-power finder (a red dot or Telrad) is handy for the
   *initial* alignment, since that step asks you to put a bright star in your eyepiece to
   select it on the PiFinder's chart.

**Does it work in light-polluted skies?**
   Yes — very well.  Leave the exposure on **AUTO** and the PiFinder adapts it to the sky;
   setting it by hand, a longer 0.4 s helps pull stars out under heavy light pollution.
   Good focus matters most of all here.

**How do I update the software?**
   From the unit, go to Tools → Software Upd while connected to a WiFi network with
   internet access (Client mode).  If the version reads "unknown", the PiFinder can't
   reach the internet to check — that's a connectivity issue, not a reason to re-image.
   Full details are in :ref:`user_guide:update software`.

**What's the default password for the web interface?**
   ``solveit`` — all lowercase, one word.  The home screen is viewable without it; other
   pages require it.  You can change it under the web interface's Tools page.

**How long does the battery last?**
   Four to five hours, but it's highly activity-dependent: sitting on a single object lets
   the PiFinder drop into a lower-power mode and stretches runtime, while a fast tour
   through many objects shortens it.  There's no battery gauge, and the unit shuts off
   abruptly when empty, so for long sessions keep a USB-C power bank handy — you can
   hot-plug it while the PiFinder is running.

**Where are my saved observations and images?**
   On the PiFinder's network share, reachable at ``//pifinder.local/shared`` (connect as
   guest, no password).  See :ref:`connectivity:shared data access`.

**Can I connect SkySafari?**
   Yes — the PiFinder talks to SkySafari and other planetarium apps over WiFi.  See the
   :doc:`skysafari` page for setup.

**Can I enter my own coordinates?**
   Yes.  You can type an arbitrary RA/Dec for objects that aren't in the built-in catalogs
   — handy for asteroids, comets, or newly discovered objects — and you can also send
   targets from SkySafari.  See :ref:`user_guide:custom targets` for how.

**Can I use the PiFinder on an EQ mount?**
   Yes — the PiFinder works with any mount, and plate solving behaves the same whatever the
   mount type.  Switch it to EQ mode in the :ref:`user_guide:settings menu` by setting
   "Mount Type" to EQ, which presents Push-To distances in RA/Dec instead of Alt/Az.  On
   software 2.5.0 and earlier the accelerometer tracking doesn't work correctly in EQ mode,
   so the Push-To numbers are unreliable while you move the scope; once you stop and the
   camera solves, the correct distances appear.  From version 2.6.0 on, EQ mode is fully
   supported with accelerometer tracking.

**Can I control my motorized (GoTo) mount with the PiFinder?**
   Not yet — this is in active development.  It will rely on INDI support for your mount,
   so even once the software is ready it may not work with every one; check INDI's
   supported-mount list at http://drivers.indilib.org/mounts/.  There's no arrival date
   yet, as it depends on a planned move to a newer OS distribution with a more current
   version of INDI.

**The operating system clock is wrong — does that matter?**
   No.  The PiFinder runs standalone without internet, and the Raspberry Pi has no
   real-time clock, so it can't keep accurate time on its own.  It saves the time at
   shutdown and reads it back at startup as a rough estimate, which can be off by days if
   the unit has been powered down for a while.  The software doesn't trust the system clock
   — it uses GPS time for everything except log-file timestamps.

   To sync the system clock to GPS time, run these commands in a terminal on the PiFinder:

   .. code-block:: bash

      sudo apt update
      sudo apt install chrony

   Then add the following to ``/etc/chrony/chrony.conf`` before the ``pool`` directive:

   .. code-block:: text

      refclock SHM 0 poll 3 refid gps1

   This lets chrony use GPS time as a reference.  In WiFi client mode chrony will usually
   prefer internet NTP servers over GPS, so the OS time may still be a second or two off.
   When running off-grid, the system clock stays inaccurate until you get a GPS lock.

Have another question?  Send it to `info@PiFinder.io <mailto:info@pifinder.io>`_ and I'll
do my best to help, and maybe add it here.  Better yet, fork the repo and contribute the
answer via a pull request.
