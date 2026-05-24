Troubleshooting & FAQ
=====================

.. note::
   This page applies to v3 and v2.5 PiFinders running software 2.x.  If you're on
   older software, updating is often the fix in itself — see
   :ref:`user_guide:update software`.

Most PiFinder hiccups have a quick, known fix, and more often than not the cause is
something simple — focus, or a settings mismatch — rather than a fault.  This page is
organised by *symptom*: find the line that matches what you're seeing and follow it to
the cause and the cure.  If your symptom isn't listed, or a fix doesn't sort it out, the
PiFinder community on the `Discord server <https://discord.gg/Nk5fHcAtWD>`_ is friendly
and quick to help.


The PiFinder won't turn on
--------------------------

The power control is a small white **slide switch** on the top of the unit, above the
screen — it slides side to side, it is not a push button.  Facing the screen, slide it
right for on, left for off.  (The **SQUARE** key never controls power.)

A few things to check:

- **Is the battery charged?**  There's no battery-level indicator on the screen, so plug
  in to charge if you're unsure.  The charging light glows blue while charging and turns
  green when full.
- **Try external power.**  Plug a USB-C cable into the port closest to the keypad.  That
  port powers the unit *immediately, regardless of the switch position* — so if the
  PiFinder runs this way but not on battery alone, the trouble is the battery or the
  switch, not the computer.
- If you built your own unit and it won't power up at all, double-check the PiSugar
  battery board connections.


The screen is blank, or it won't finish booting
-----------------------------------------------

First, rule out the simple explanations:

- **Brightness turned all the way down.**  If the PiFinder was last used at a dark site,
  the screen may simply be dimmed to nothing.  Hold **SQUARE** and tap **+** several
  times to bring it back.
- **Give it time on the first boot.**  A normal start-up reaches the welcome screen in
  about 20 seconds.  The *first* boot after re-imaging takes a minute or two, and the
  unit will restart itself several times while it sets up — that's expected.  If a unit
  seems stuck, wait a full five minutes before deciding something is wrong.

If the screen is still blank, look at the keypad backlight — it tells you where the
problem is:

- **No keypad light and no screen** (you may see a faint red LED glowing inside the case,
  meaning the Pi has power but isn't booting): this is almost always **SD card
  corruption**, the single most common hardware issue.  Re-image the card with the latest
  release, or request a fresh one.  SD card faults are all-or-nothing — they stop the
  PiFinder booting rather than causing subtle misbehaviour, so don't reach for a re-image
  to explain slow solves or the occasional position jump.
- **Keypad lights up, but the screen is blank or shows garbled characters**: that points
  to the screen's connection rather than the software.  You can confirm it by connecting
  through the :ref:`web interface <user_guide:web interface>` — if the remote screen
  looks correct there, the software is fine and the physical screen connection needs
  attention (a solder reflow on DIY builds).

For re-imaging instructions, see :ref:`user_guide:update software` and the
:doc:`software` page.


The camera view is blank or black
---------------------------------

If the Focus screen shows nothing at all — not even faint noise with the lens cap on —
the **Camera Type** setting probably doesn't match the camera in your unit.

- Open Settings and try a different Camera Type.  The v3 sensors are ``imx462`` and
  ``imx296``; older v2 cameras are ``imx477``.  It won't hurt to try each.
- **After changing Camera Type you must fully power the PiFinder off and on** — a software
  restart alone won't apply it.
- A software update can quietly reset this setting, so it's worth re-checking after you
  update.

A healthy camera shows at least some faint noise with the lens cap on, and a brighter
image in daylight — use that to confirm the camera is alive before chasing focus or
exposure.


It won't plate solve ("can't find stars")
------------------------------------------

Plate solving is how the PiFinder works out where it's pointed (see
:ref:`quick_start:setting focus & first solve`).  When it won't solve, **focus is the
cause far more often than anything else** — and stars that look fine at normal zoom are
frequently not tight enough.

Work through these in order:

- **Focus, properly.**  On the Focus screen, use **+/-** to zoom to 2x and 4x and rotate
  the lens until the stars are as small as you can make them.  Tight focus matters *even
  more* under bright, light-polluted skies, where slightly soft dim stars vanish into the
  background.  If you're starting from way off, set the lens so about 6 mm of thread is
  showing — roughly a pencil's width — which is close to in focus.
- **Lens cap off, and hold still.**  The PiFinder can only solve a sharp, stationary
  image.
- **Exposure.**  The default of 0.2 s suits most skies.  For bright urban skies try
  0.4 s; for dark skies 0.1 s works well, or choose **AUTO** to let the PiFinder set it
  for you.  (Software older than 2.2 doesn't have the AUTO option — another reason to
  update.)
- **High, thin cloud.**  An invisible drifting cloudbank will stop solves at an otherwise
  perfect site.  If solves come and go while the scope is dead still, suspect the sky
  before the hardware.

.. note::
   On older v2 cameras the lens has two rings — a focus ring and an aperture ring.  The
   **aperture must be fully open** for the PiFinder to see enough stars to solve.


An object has "disappeared" from a list (for example, M45)
----------------------------------------------------------

Objects are never deleted.  If something you expect is missing from a list, it's being
hidden by an active **filter** — magnitude, altitude, type, observed status, or which
catalogs are selected.  To bring everything back, open the Filter menu and choose
**Reset All**.  See :ref:`user_guide:filters` for what each filter does.


The chart or Push-To directions look backwards
----------------------------------------------

If the star chart appears mirrored, or the Push-To arrows consistently send you the wrong
way, the most likely cause is the **PiFinder Type** setting not matching how your unit is
mounted — for example, set to Right when it should be Left.  This setting tells the
PiFinder its orientation, and it drives both the chart and the Push-To directions.  Set
it to match your hardware under Settings, as described in
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
  shows where your scope is pointing *within* the camera's wide 10° view — it is not meant
  to sit in the middle, and a reticle off to one side is completely normal.  See
  :ref:`quick_start:alignment`.
- **The star chart is "zenith up", not eyepiece-matched.**  The on-screen chart is a
  naked-eye view, oriented the way you'd see the sky looking up, so it won't match the
  flipped or rotated view through your eyepiece.  The object *image* previews, by
  contrast, are rotated to match the eyepiece.
- **Push-To numbers dim while you move the scope.**  While the scope is moving the
  PiFinder estimates position from its motion sensor and dims the numbers to say so; the
  instant you stop, it takes a fresh photo, the numbers brighten, and the position is
  exact again.  (This is separate from the whole screen dimming in power-save mode.)
- **The charging light is slow to turn green.**  Near a full charge the current tapers
  off, so the final stretch from blue to green takes a while.  That's normal charging
  behaviour, not a fault.


Frequently Asked Questions
--------------------------

**Do I still need a finder scope or Telrad?**
   Not for finding objects — once the PiFinder is aligned to your scope it replaces a
   traditional finder.  A zero-power finder (a red dot or Telrad) is handy for the
   *initial* alignment, though, since that step asks you to put a bright star in your
   eyepiece so you can select it on the PiFinder's chart.

**Does it work in light-polluted skies?**
   Yes — very well.  Bright skies just need a longer exposure: the default is 0.2 s, and
   for heavy light pollution you can raise it to 0.4 s.  Good focus matters most of all
   here.

**How do I update the software?**
   From the unit, go to Tools → Software Upd while connected to a WiFi network with
   internet access (Client mode).  If the version reads "unknown", the PiFinder simply
   can't reach the internet to check — that's a connectivity issue, not a reason to
   re-image.  Full details are in :ref:`user_guide:update software`.

**What's the default password for the web interface?**
   ``solveit`` — all lowercase, one word.  The home screen is viewable without it; other
   pages require it.  You can change it under the web interface's Tools page.

**How long does the battery last?**
   Four to five hours, but it's highly activity-dependent: sitting on a single object lets
   the PiFinder drop into a lower-power mode and stretches runtime, while a fast tour
   through many objects shortens it.  There's no on-screen battery gauge, and the unit
   shuts off abruptly when empty, so for long sessions keep a USB-C power bank handy — you
   can hot-plug it while the PiFinder is running.

**Where are my saved observations and images?**
   On the PiFinder's network share, reachable at ``//pifinder.local/shared`` (connect as
   guest, no password).  See :ref:`user_guide:shared data access`.

**Can I connect SkySafari?**
   Yes — the PiFinder talks to SkySafari and other planetarium apps over WiFi.  See the
   :doc:`skysafari` page for setup.

**Can I enter my own coordinates?**
   Yes.  You can type in an arbitrary RA/Dec for objects that aren't in the built-in
   catalogs — handy for asteroids, comets, or newly discovered objects — and you can also
   send targets to the PiFinder from SkySafari.
