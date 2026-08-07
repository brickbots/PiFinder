Board Bring-up
==============

.. note::
   Bring-up is part of the PiFinder software from 2.6.1 onward, and covers rev4
   and v3 boards.  It is a bench tool for builders.  If you are trying to work
   out why a finished PiFinder is misbehaving under the stars, start with
   :doc:`troubleshooting` instead.

A bring-up run is the first power-on validation of a freshly assembled board.
One command drives the screen, the keypad backlight and the buzzer, interrogates
the IMU and the charger, and watches the keypad while you press every switch —
all on one live screen.

It deliberately does not start the PiFinder application: no catalogs, no solver,
no camera, no menus.  So it runs on a card that has only just been imaged, it is
ready in about a second, and a board with no camera fitted still brings up
everything else.

Run one when you have just assembled a board, after reworking or replacing a
part, and before you configure a unit or send it out.  It is quick enough that
running it twice — once before the case goes on and once after — costs almost
nothing.

Running a bring-up
------------------

The application holds the panel, both PWM channels and the I²C bus, so stop it
first.  Over SSH, or on a console at the bench:

.. code-block:: bash

    sudo systemctl stop pifinder
    cd ~/PiFinder/python
    python3 -m PiFinder.bringup

If the service is still running, the run refuses to start and says so rather
than fighting it for the hardware.

The run opens with three full-screen patterns, about a second and a half each,
then settles onto the dashboard and stays there.  Press every key, tilt the
board, watch the grid fill in, and end the run when you are satisfied.

A run assumes a rev4 board.  For a v3 board add ``--revision rev3``, which
selects both the right set of switches and the right panel.  Bloom and Heart
builds mount the screen upside down relative to the others, so add
``--rotate 2`` to read the dashboard the right way up.

The pre-flight: the card, not the board
---------------------------------------

Before anything is driven, the run prints one line describing how the **card**
is provisioned — whether the I²C bus is enabled, and whether each PWM channel is
routed to the pin its consumer needs:

.. code-block:: text

    PRE-FLIGHT  i2c-1 ok | pwm ch1->gpio13 (backlight) ok | pwm ch0->gpio12 (buzzer) ok

This line comes first because a misprovisioned card and a bad board look
identical from the outside.  A PWM channel that the kernel has exported but
muxed to no pin makes a perfectly good buzzer silent, and a builder who reaches
for a soldering iron at that point will desolder a healthy part.

So read the pre-flight before you read anything else.  ``NOT ROUTED`` or
``MISSING`` is a fault in the card's ``config.txt``, not in your soldering.
Checks that depend on something the pre-flight found missing are reported as
``skipped`` rather than failed — the run did not verify that part, and it will
not blame the board for the card.

.. note::
   Images built by ``pifinder_setup.sh`` route only PWM channel 1, so a fresh
   install reports ``pwm ch0->gpio12 (buzzer) NOT ROUTED`` and the buzzer stays
   silent with no other complaint.  Replace the ``dtoverlay=pwm,pin=13,func=4``
   line in ``/boot/firmware/config.txt`` (``/boot/config.txt`` on older Raspberry
   Pi OS releases) with the two-channel form, then reboot:

   .. code-block:: text

       dtoverlay=pwm-2chan,pin=12,func=4,pin2=13,func2=4

The six checks
--------------

A run reports on six named checks, and each one is a different kind of claim.
The kind is the point of the whole tool: it says who established the result, and
therefore how much it is worth.

A **probed** check is one the program answers on its own, by talking to the
part.  An **exercised** check is one you drive and the program confirms.  A
**witnessed** check is one the program can only *emit* — it drives the hardware,
and **you** are the sensor.

.. list-table::
   :header-rows: 1
   :width: 100%

   * - Check
     - Kind
     - What happens
   * - ``SCREEN``
     - witnessed
     - Three full-screen patterns, then the live dashboard
   * - ``BACKLIGHT``
     - witnessed
     - A continuous brightness ramp on the keypad LEDs
   * - ``BUZZER``
     - witnessed
     - A startup tone, then one tone per switch closure
   * - ``IMU``
     - probed
     - The BNO055 answers its chip identity and produces a live quaternion
   * - ``CHARGER``
     - probed
     - The BQ25895 answers its part-number register; voltages decode
   * - ``SWITCHES``
     - exercised
     - Every populated switch is observed closing at least once

The screen patterns are worth watching closely, because the dashboard alone
cannot reveal what they show.  A full white field exposes dead pixels and
uniformity.  The second pattern draws a one-pixel border, corner ticks, a solid
block in the top-left corner only and a centre cross — offset, rotation, a
mirrored panel and clipped edges all become obvious against it.  The third
sweeps red, green and blue stripes, which catches a wrong colour order or the
wrong panel part.  A finished PiFinder only ever shows red to protect your night
vision; the stripes deliberately bypass that to prove all three channels reach
the glass.

The backlight sweeps rather than sitting at a fixed level, because a dim or
partly-lit LED string is obvious against a ramp and invisible against a steady
brightness.

The IMU row shows ``cal0 q ----`` until the sensor reports calibration.  Leave
the board still for a moment, then tilt it: once a live quaternion appears the
check passes.  A part that answers on the bus but never fuses a reading does not
pass, which is exactly the failure a bare presence probe would miss.

The verdict
^^^^^^^^^^^

The verdict is computed over the probed and exercised checks only, and it is
what the process exit status reports.  When it passes, the title bar inverts and
reads ``PASS``, so the result is readable from across the bench.

Witnessed checks never contribute.  The run reports them as ``emitted`` — it
drove the panel, the LEDs and the buzzer, and whether light or sound came out is
not something it is in a position to know.  A passing verdict means the IMU and
charger answered and every populated switch closed.  It says nothing at all
about your screen, your backlight or your buzzer; those are yours to judge.

The dashboard
-------------

The live screen carries a title bar, three status rows and the switch grid.

The title bar reads ``BRING-UP`` on the left and the board revision on the
right, and inverts to ``PASS`` when the verdict passes.  Below it:

.. code-block:: text

    IMU  ok  cal3 q+0.71
    CHG  ok  4.02V BAT
    SW   10/18      PWR *

``IMU`` shows the calibration figure and the leading term of the live
quaternion.  ``CHG`` shows whether the charger was identified, the battery
voltage it reports, and whether the board is running on external power (``PG``)
or on the battery (``BAT``).  ``SW`` counts how many populated switches have
been observed closing, and marks the power switch with ``*`` once it has been
tapped.  A part that never answered shows ``--`` and the reason.

The switch grid
---------------

The grid below the status rows has one cell per **matrix position** — one
``(row, column)`` coordinate in the scanned keypad matrix.  Bring-up reports
positions rather than key names on purpose: more than one position can send the
same key, so "the UI received SQUARE" would not tell you which joint conducted.

Each cell carries a single character naming the key that position sends: the
digits, ``+`` and ``-``, ``#`` for SQUARE, and ``^ v < >`` for the four
directions.  The grid is the wiring matrix, not a picture of the keypad, so the
letters — not the shape — are what you read.  On a rev4 board it looks like
this:

.. code-block:: text

              col 0   col 1   col 2   col 3   col 4

      row 0     7       8       9               ^
      row 1     4       5       6       +       <
      row 2     1       2       3       -       v
      row 3             0               #       >
      row 4                                     #

                        PWR

The power switch is wired to its own line rather than into the matrix, so it has
no matrix position and gets a wider cell of its own below the grid.

A cell is drawn dimly until that switch has been seen closing, brightly once it
has, and filled solid while it is held down.  Seen and held are kept apart
deliberately: a position that reads permanently closed is a solder bridge, and
one that closes but never releases is a mechanical fault.  A press counter alone
would score both as good.

Sweep the whole keypad, including a tap of the power switch, and every cell
should end up bright.  Anything still dim is a switch that never closed.

Two positions send SQUARE on rev4 — the calculator pad's own button at row 3,
and the joystick centre at row 4 — so both have to be pressed for the grid to
fill.

If a position that carries no switch closes anyway, it is drawn with ``?`` and
reported as ``unexpected``.  That does not fail the run, since the map rather
than the board may be what is wrong, but it is never silently dropped.

Blank cells are not faults
^^^^^^^^^^^^^^^^^^^^^^^^^^

The matrix is scanned identically on every board revision, but revisions
populate different subsets of it — and a position that carries no switch is
simply not part of the run.

On rev4 the bottom row is empty except for its last cell, because rev4 has no
bottom directional row: the directional control moved into the right-hand
column.  On a v3 board the opposite holds — the bottom row carries the four
arrow buttons and the right-hand column is empty.  Either way the run counts
closures only against the switches that revision actually has: 18 on rev4, 17 on
v3.  Blank cells in the grid are not dead switches, so do not go looking for
them with an iron.

The joystick is one component
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

On rev4 the five populated positions in the right-hand column are the five
contacts of a **single 5-way joystick** — four directions plus a centre press —
not five separate switches.

This matters when one of them fails to register.  The grid tells you *which
contact* is not conducting, but the part you rework is one joystick: reflow its
joints, and replace the whole component if reflowing does not fix it.  Reading
those five cells as five switches sends you hunting for a part that is not on
the board.

.. note::
   On a v3 board the four directions are four separate switches along the bottom
   row, and each really is its own part.

Ending the run
--------------

A run is open-ended and keeps reporting until you end it, in one of three ways.

**Hold the power switch for a second.**  This is the one to use at a bench with
no terminal in sight.  The power cell fills a bar — ``[#---]`` through
``[####]`` — for the whole second, so you can see it coming and let go, and at
the end the screen reads ``SHUTTING DOWN``, a tone plays and the card is shut
down cleanly.  Pulling power on a mounted filesystem is how a builder corrupts
an image somewhere between the first board and the tenth.

A *tap* is a different thing from a hold, and both are wanted: a tap is all the
``SWITCHES`` check needs, and registers on the first scan that sees it.  The
power switch is the only one whose duration means anything.

``--no-power-shutdown`` removes the gesture entirely for a builder who would
rather not risk it; a tap still counts toward the switch check.

**Press Ctrl-C** if you have a terminal in front of you.

**Set a time limit** with ``--timeout SECONDS`` and the run ends by itself after
that long — handy when you are working through a batch of boards.

Whichever way it ends, the buzzer is silenced and the backlight darkened on the
way out.

.. note::
   The power hold asks the operating system to shut down and never cuts power
   itself.  If that request fails — on a card whose ``sudo`` rules do not allow
   it — the run says so rather than swallowing it, and the board is still up.
   Shut it down properly before pulling power.

Reading the summary
-------------------

When the run ends it prints the pre-flight line again and one line per check:

.. code-block:: text

    SCREEN     emitted   3 patterns + dashboard                 (witnessed)
    BACKLIGHT  emitted   ramp 0-12% on pwm ch1                  (witnessed)
    BUZZER     emitted   startup + keypress earcons             (witnessed)
    IMU        PASS      BNO055 id ok, cal 3, q live            (probed)
    CHARGER    PASS      BQ25895 pn=0b111, 4.02V, BAT           (probed)
    SWITCHES   PASS      18/18                                  (exercised)
    VERDICT    PASS

The exit status is 0 when the verdict passes and 1 when it does not, so a run
can be scripted into a batch workflow.

A failing run names what it found.  Here one switch never closed, and the
position is spelled out along with the key it sends:

.. code-block:: text

    SWITCHES   FAIL      17/18 - (2,4) DOWN never closed        (exercised)
    VERDICT    FAIL

Three distinctions are worth holding on to when reading a summary:

* ``FAIL`` on a probed or exercised check points at the **board** — a joint, a
  missing part, a wrong part.
* ``skipped`` points at the **card**.  Fix the provisioning, reboot and run
  again; nothing is wrong with the hardware until a run with a clean pre-flight
  says so.
* ``emitted`` is not a pass and not a failure.  It means the run drove that
  hardware.  Whether the screen lit, the keypad glowed and the buzzer sounded is
  what you were watching for.

Options
-------

.. list-table::
   :header-rows: 1
   :width: 100%

   * - Option
     - What it does
   * - ``--revision``
     - Board revision being brought up: ``rev4`` (the default) or ``rev3`` for a
       v3 board.  Sets both the switch population and the default panel
   * - ``--display``
     - Open a specific panel instead of the revision's own.  Rarely needed
   * - ``--rotate``
     - Quarter-turns to rotate the screen, added to the panel's own orientation.
       Bloom and Heart builds want ``2``
   * - ``--no-patterns``
     - Skip the screen patterns and go straight to the dashboard
   * - ``--pattern-loop``
     - Loop the patterns forever, for panel-only work.  Ctrl-C to stop
   * - ``--backlight-max``
     - Peak duty percentage of the backlight ramp.  The default is 12
   * - ``--volume``
     - Buzzer volume for the tones: ``Off`` or ``1``–``5``.  The default is 5
   * - ``--no-power-shutdown``
     - Do not end the run and shut down when the power switch is held.  A tap
       still counts toward the switch check
   * - ``--timeout``
     - End the run after this many seconds instead of waiting for you

Run ``python3 -m PiFinder.bringup --help`` on the unit for the current list.

With a clean bring-up behind you, the board is ready for
:doc:`Software Setup <software>` and a first night out with the
:doc:`quick_start`.
