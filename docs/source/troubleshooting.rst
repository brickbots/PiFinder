Troubleshooting & FAQ
=====================

.. note::
   This page applies to rev4, v3 and v2.5 PiFinders running software |min_software| or above.  If
   you're on older software, updating is often the fix in itself.  See
   :ref:`user_guide:update software`.

   Not sure which you have?  See
   :ref:`Which PiFinder do I have? <quick_start:which pifinder do i have?>` in the Quick Start.

Most PiFinder problems have a quick fix.  The cause is usually something simple, such as focus
or a settings mismatch, rather than a fault.  This page is organised by *symptom*.  Find the
line that matches what you're seeing and follow it to the fix.  If your symptom isn't listed,
or a fix doesn't work, the PiFinder community on the
`Discord server <https://discord.gg/Nk5fHcAtWD>`_ is quick to help.


The PiFinder won't turn on
--------------------------

Power is the button marked **PWR**, on the front below the keypad.  Press and hold it for
about two seconds to turn the PiFinder on.  The **PWR** label lights while it boots.  Press
and hold it while the PiFinder is running to bring up the shutdown confirmation.  The
**SQUARE** key never controls power.

Things to check:

- **Is the battery charged?**  Plug a USB-C cable into the **POWER** port.  The **CHG** light
  comes on while the battery charges.  Once the PiFinder is running, the title bar shows
  roughly how much longer it will run.  See :ref:`user_guide:the battery indicator`.
- **Try a different cable and supply.**  Some USB-C cables cannot reliably carry the current
  the PiFinder draws.  If the PiFinder runs on external power but not on battery, the fault
  is in the battery, not the computer.

If none of that helps, press and hold the **PWR** button for more than **14 seconds**.  This
resets the power system itself rather than the software.  It cuts power to a PiFinder whose
software has hung and will not shut down.  It also lets a PiFinder turn on again when
something is stopping it from starting normally.  This is a hard cut rather than a clean
shutdown, so keep it for when the PiFinder is genuinely unresponsive.

.. note::
   On v3 and v2.5 PiFinders, power is a small white **slide switch**.  It slides side to side
   and is not a push button.  Facing the screen, slide right for on, left for off.  A v3 has
   no battery indicator, so plug in to charge if you're unsure.  The charging light glows
   blue while charging and green when full.  The port closest to the keypad powers the
   PiFinder *immediately, regardless of switch position*, which is a quick way to tell a flat
   battery or a failed switch from a dead computer.  If you built your own PiFinder and it
   won't turn on at all, double-check the connections to the PiSugar battery board.
   |v3_docs|


The screen is blank, or it won't finish booting
-----------------------------------------------

Rule out the simple explanations first:

- **Brightness turned all the way down.**  If you last used the PiFinder at a dark site, the
  screen may be dimmed to nothing.  Hold **SQUARE** and press **+** several times to bring it
  back.
- **Give it time on the first boot.**  A normal boot reaches the welcome screen in about
  20 seconds.  The *first* boot after re-imaging takes a minute or two and restarts itself
  several times while it sets up.  This is expected.  Wait a full five minutes before
  deciding something is wrong.

If the screen is still blank, the keypad backlight tells you where the problem is:

- **No keypad light and no screen**: this is almost always **SD card corruption**, the most
  common hardware issue.  A faint red LED inside the case means the Pi has power but is not
  booting.  Re-image the card with the latest release, or request a fresh one.  :doc:`sd_card`
  covers getting at the card on each revision.  SD card faults are all-or-nothing.  They stop
  the PiFinder booting rather than causing subtle misbehaviour, so don't re-image to explain
  slow solves or the occasional position jump.
- **Keypad lights up, but the screen is blank or garbled**: this points to the screen's
  connection, not the software.  Confirm it through the
  :ref:`web interface <connectivity:web interface>`.  If the remote screen looks correct
  there, the software is fine and the physical screen connection needs attention.  On DIY
  builds that usually means a solder reflow.

For re-imaging instructions, see :ref:`user_guide:update software` and the
:doc:`software` page.


The camera view is blank or black
---------------------------------

The Focus screen opens on its magnified star tiles, which stay black whenever the PiFinder
detects no stars.  A perfectly healthy camera therefore looks dead there in daylight or under
cloud.  Don't judge the camera by that screen.

To see what the camera sees, open the Start menu and select Align (Day).  It switches the
camera to a short daytime exposure and shows a full live image, which is the quickest way to
tell whether the camera works at all.  Point the PiFinder at something bright and you should
get a recognisable picture.  Even with the lens cap on you should see faint noise rather than
pure black.

If Align (Day) shows nothing whatsoever, the **Camera Type** setting probably doesn't match
the camera in your PiFinder.

- From the main menu, select Settings, scroll down to Advanced, then select Camera Type and
  try a different option.  A rev4 PiFinder takes ``v3 - imx462``.  There is no separate rev4
  entry, and that one is correct.  The v3 sensors are ``v3 - imx462`` and ``v3 - imx296``,
  and older v2 cameras are ``v2 - imx477``.  Trying each one does no harm.
- **After changing Camera Type, turn the PiFinder fully off and on again.**  A software
  restart alone does not apply it.
- A software update can quietly reset this setting, so re-check it after you update.


It won't plate solve ("can't find stars")
------------------------------------------

Plate solving is how the PiFinder works out where it points.  See
:ref:`quick_start:setting focus & first solve`.  When it won't solve, **focus is the cause far
more often than anything else**.  Stars that look fine at normal zoom are often not tight
enough.

Work through these in order:

- **Focus, properly.**  On the Focus screen, rotate the lens until the four magnified stars
  are as small as possible and the central HFD reaches its lowest value.  The difference
  between fair and good focus is less than half a turn.  Work in steps of an eighth to a
  quarter of a turn, and pause after each step for vibration to settle.  Judge by the HFD
  rather than the camera icon, which lags a second or so behind each change of the lens.
  Tight focus matters *even more* under bright, light-polluted skies, where slightly soft dim
  stars vanish into the background.  If you're starting from far off, set the lens so about
  6 mm of thread shows, roughly a pencil's width.  That is close to in focus.
- **Lens cap off, and hold still.**  The PiFinder can only solve a sharp, stationary
  image.
- **Exposure.**  The PiFinder defaults to **AUTO** and sets the exposure itself from each
  solve.  Leave it there unless you have a reason not to.  To set it by hand, select Settings
  from the main menu, then select Camera Exp.  0.2 s suits most skies, bright urban skies want
  0.4 s, and dark skies solve well at 0.1 s.  The Focus screen holds the exposure steady while
  it is open, so it reads ``HOLD`` there even on **AUTO**.  The **UP** and **DOWN** steps on
  that screen change the exposure for the visit only, and the PiFinder does not save them.
  Software older than 2.2 has no AUTO option, which is another reason to update.
- **High, thin cloud.**  An invisible drifting cloudbank stops solves at an otherwise perfect
  site.  If solves come and go while the telescope is dead still, suspect the sky before the
  hardware.
- **Did you fit a different lens?**  The PiFinder cannot see which lens is on the front, so it
  works from the Lens setting.  A setting that names the wrong lens stops solving completely
  rather than making it worse, because the PiFinder then looks for a patch of sky the wrong
  size.  Select Settings from the main menu, scroll down to Advanced, then select Lens.  Set
  the focal length printed on the lens barrel.  The PiFinder restarts when you change it.

.. note::
   You only need to set the Lens by hand if you fitted the lens yourself.  A PiFinder still
   set to the lens it shipped with works this out on its own.  It allows for every lens it
   might have come with, then records the one it measures after its first few solves.

.. note::
   On older v2 cameras the lens has two rings, a focus ring and an aperture ring.  The
   **aperture must be fully open** for the PiFinder to see enough stars to solve.


The GPS never locks
-------------------

A first lock takes several minutes, and often longer.  The receiver has to download orbit
data from the satellites before it can fix a position, and that download runs at a fixed
slow rate whatever the sky is like.  Most reports of a dead GPS turn out to be a wait that
was cut short.

- **Open the Start menu and select GPS Status, then leave the PiFinder there.**  The screen
  turns the camera off to help the receiver, and shows **Lock boost on** while it does.
- **"Sats seen/used: 0/0" is not a progress bar.**  It sits at 0/0 for most of the wait and
  then climbs quickly near the end.
- **Don't turn the PiFinder off and on again to check.**  A restart throws away the partial
  download and starts over.  Repeated restarts can stop a lock arriving at all.
- **Get the receiver under open sky.**  It does not work indoors or under a roof.
- **Don't compare it with your phone.**  Phones use assisted GPS over the mobile network, so
  they lock in seconds.  That comparison says nothing about your PiFinder or your sky.

If you would rather not wait, enter your location and time by hand and start observing.  See
:ref:`user_guide:place & time`.  For what the lock types mean, see
:ref:`user_guide:getting a gps lock`.

.. note::
   A GPS lock is not needed to focus, align, or push to objects once your location and time
   are set.  It is needed before the Planets and Comets catalogs fill in, because those
   depend on your time and place.


An object has "disappeared" from a list (for example, M45)
----------------------------------------------------------

The PiFinder never deletes objects.  If something you expect is missing, an active **filter**
is hiding it.  The filters cover magnitude, altitude, type, observed status, and which
catalogs are selected.  To bring everything back, open the Filter menu and select
**Reset All**.  See :ref:`user_guide:filters` for what each filter does.


The chart or Push-To directions look backwards
----------------------------------------------

**Reversed Push-To directions are the classic sign that the PiFinder Type setting doesn't
match your hardware.**  You push the telescope the way the arrows point, and the object moves
further away instead of closer.  A mirrored star chart is the same fault showing itself
somewhere else.  One setting drives both.

On rev4, suspect this first.  The body rotates between the Left, Right and Straight positions
without tools, so it's easy to reposition the PiFinder for a different telescope and leave the
setting describing where the screen used to face.  Set it to match under Settings, as
described in :ref:`Configuration Setup <quick_start:configuration setup>`.

.. note::
   You can also configure the clockwise / counter-clockwise Push-To arrows to suit how you
   picture turning your telescope.  If only the left/right (azimuth) direction feels reversed,
   change that preference in Settings rather than the PiFinder Type.


"Is this normal?"
-----------------

A few PiFinder behaviours surprise people into thinking something is broken.  These are
all expected:

- **The alignment reticle isn't centred.**  The Telrad-style reticle on the Align screen shows
  where your telescope points *within* the camera's wide 10° view.  It is not meant to sit in
  the middle, and a reticle off to one side is normal.  See :ref:`quick_start:alignment`.
- **The star chart is "zenith up", not eyepiece-matched.**  The on-screen chart is a naked-eye
  view, oriented as you'd see the sky looking up, so it won't match the flipped or rotated
  view through your eyepiece.  The object *image* previews, by contrast, are rotated to match
  the eyepiece.
- **Push-To numbers dim while you move the telescope.**  While you move, the PiFinder
  estimates position from its motion sensor and dims the numbers to say so.  The instant you
  stop, it takes a fresh photo, the numbers brighten, and the position is exact again.  This
  is separate from the whole screen dimming in power-save mode.
- **The charging light is slow to turn green.**  Near a full charge the current tapers off, so
  the final stretch from blue to green takes a while.  That's normal, not a fault.


Frequently Asked Questions
--------------------------

**It's cloudy.  Can I still learn my way around?**
   Yes.  Test Mode solves a saved star image from disk and supplies a stand-in location, so
   the PiFinder behaves as though it is pointed at the sky.  You can explore the menus,
   catalogs, filters and Push-To indoors.  From the main menu, select Tools, then select Test
   Mode.  It stays on until you restart the PiFinder, and it blocks real observing while it
   runs, so restart before you go out.

**Do I still need a finder scope or Telrad?**
   Not for finding objects.  Once aligned to your telescope, the PiFinder replaces a
   traditional finder.  A zero-power finder, such as a red dot or a Telrad, is handy for the
   *initial* alignment, because that step asks you to put a bright star in your eyepiece to
   select it on the PiFinder's chart.

**Does it work in light-polluted skies?**
   Yes, very well.  Leave the exposure on **AUTO** and the PiFinder adapts it to the sky.  If
   you set it by hand, a longer 0.4 s helps pull stars out under heavy light pollution.  Good
   focus matters most of all here.

**How do I update the software?**
   Connect the PiFinder to a WiFi network with internet access (Client mode).  From the main
   menu, select Tools, then select Software Upd.  If the version reads "unknown", the PiFinder
   can't reach the internet to check.  That is a connectivity issue, not a reason to re-image.
   Full details are in :ref:`user_guide:update software`.

**What's the default password for the web interface?**
   ``solveit``, all lowercase, one word.  You can view the home screen without it.  The other
   pages require it.  You can change it on the web interface's Tools page.

**How long does the battery last?**
   About ten hours, and that is a floor.  It was measured with the camera solving
   continuously, the screen at full brightness and sleep off, so ordinary observing runs
   longer.  Runtime depends heavily on what you do.  Sitting on a single object lets the
   PiFinder drop into a lower-power mode and stretches the runtime, while a fast tour through
   many objects shortens it.  You don't have to guess.  The title bar's
   :ref:`battery indicator <user_guide:the battery indicator>` shows how much longer it
   will run, and the PiFinder warns at 10% and 5% before it performs
   :ref:`an orderly shutdown <user_guide:low-battery warnings and automatic shutdown>`
   rather than cutting out.  For long sessions keep a USB-C power bank handy.  You can
   hot-plug it while the PiFinder is running.

   .. note::
      A v3 or v2.5 PiFinder with the PiSugar battery runs for four to five hours, has no
      battery indicator, and shuts off abruptly when the cell is empty.
      |v3_docs|

**Where are my saved observations and images?**
   On the PiFinder's network share, reachable at ``//pifinder.local/shared`` (connect as
   guest, no password).  See :ref:`connectivity:shared data access`.

**Can I connect SkySafari?**
   Yes.  The PiFinder talks to SkySafari and other planetarium apps over WiFi.  See the
   :doc:`skysafari` page for setup.

**Can I enter my own coordinates?**
   Yes.  You can type an RA/Dec of your own for objects that aren't in the built-in catalogs,
   which is handy for asteroids, comets, or newly discovered objects.  You can also send
   objects from SkySafari.  See :ref:`user_guide:custom targets` for how.

**I rotated my PiFinder to fit a different telescope.  Do I need to change anything?**
   Yes.  One rev4 PiFinder covers all three positions, because its body rotates between Left,
   Right and Straight, and the software has to know which one you moved it to.  Skip that step
   and the **Push-To directions come out reversed**.  You push the telescope the way the
   arrows point, and the object moves further away.  Set **PiFinder Type** under Settings to
   match, as described in :ref:`Configuration Setup <quick_start:configuration setup>`.

**Can I use the PiFinder on an EQ mount?**
   Yes.  The PiFinder works with any mount, and plate solving behaves the same whatever the
   mount type.  Switch it to EQ mode in the :ref:`user_guide:settings menu` by setting
   "Mount Type" to EQ, which presents Push-To distances in RA/Dec instead of Alt/Az.

   An equatorial *platform* is the exception.  Leave "Mount Type" on Alt/Az when you put an
   alt-az telescope, such as a Dobsonian, on a tracking platform.  You still move the
   telescope in altitude and azimuth, and the PiFinder corrects for the platform's rotation
   on its own.  Setting EQ mode there is what makes the Push-To corrections jump around.

   On software 2.5.0 and earlier the accelerometer tracking doesn't work correctly in EQ
   mode, so the Push-To numbers are unreliable while you move the telescope.  Once you stop
   and the camera solves, the correct distances appear.  Version 2.6.0 and later support EQ
   mode fully, with accelerometer tracking.

**Can I control my motorized (GoTo) mount with the PiFinder?**
   Not yet.  This is in active development.  It will rely on INDI support for your mount, so
   even once the software is ready it may not work with every mount.  Check INDI's
   supported-mount list at http://drivers.indilib.org/mounts/.  There is no arrival date yet,
   because it depends on a planned move to a newer OS distribution with a more current version
   of INDI.

**The operating system clock is wrong.  Does that matter?**
   No.  The PiFinder runs standalone without internet, and the Raspberry Pi has no real-time
   clock, so it can't keep accurate time on its own.  It saves the time at shutdown and reads
   it back at startup as a rough estimate.  That estimate can be off by days if the PiFinder
   has been turned off for a while.  The software doesn't trust the system clock.  It uses GPS
   time for everything except log-file timestamps.

   To sync the system clock to GPS time, run these commands in a terminal on the PiFinder:

   .. code-block:: bash

      sudo apt update
      sudo apt install chrony

   Then add the following to ``/etc/chrony/chrony.conf`` before the ``pool`` directive:

   .. code-block:: text

      refclock SHM 0 poll 3 refid gps1

   This lets chrony use GPS time as a reference.  In WiFi client mode chrony usually prefers
   internet NTP servers over GPS, so the OS time may still be a second or two off.  When
   running off-grid, the system clock stays inaccurate until you get a GPS lock.

Have another question?  Send it to `info@PiFinder.io <mailto:info@pifinder.io>`_ and I'll do
my best to help, and maybe add it here.  Better yet, fork the repo and contribute the answer
in a pull request.
