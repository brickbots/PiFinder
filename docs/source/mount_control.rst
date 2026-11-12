=============
Mount Control
=============

.. note::

   Mount control is experimental and is only in the NixOS image.  Keep your hand
   controller or app near, and stop the mount with the **0** key or the mount's own
   stop button if something goes wrong.

The PiFinder can move a GoTo mount.  Select an object, press **5**, and the mount
slews to it.  The PiFinder then plate solves, corrects the mount, and moves again
until the object is centered.  The PiFinder talks to the mount through INDI, the
driver library of KStars/Ekos, so it supports most GoTo mounts: OnStep and OnStepX
(for example the MLAstro SAL-33), SkyWatcher (EQMod, AZ-GTi), iOptron, Celestron,
Meade, ZWO AM5 and more.

You do not need a star alignment.  The plate solve tells the mount where it points.


Connect the mount
-----------------

USB
   Connect a USB cable from the mount controller to the PiFinder.  The port is
   usually ``/dev/ttyUSB0`` (most USB-serial cables and ESP32 boards) or
   ``/dev/ttyACM0`` (boards with native USB, such as a Teensy).

WiFi, mount as access point
   The mount makes its own WiFi network.  OnStepX uses ``192.168.0.1``, port
   ``9999``.  The SkyWatcher AZ-GTi uses ``192.168.4.1``, port ``11880``.  Join the
   mount's network from the PiFinder: see :doc:`connectivity` for client mode.

WiFi, mount in station mode
   The mount joins the PiFinder access point.  The **Mount** page of the web
   interface lists the devices on the PiFinder WiFi.  Select the mount there to use
   its address.


Set up the mount
----------------

You can set up the mount on the PiFinder or in the web interface.  The settings
apply at once.  The PiFinder does not restart.

On the PiFinder
   Open **Settings > Experimental > Mount Control**:

   - **Mount Control**: On or Off.
   - **Mount**: select the manufacturer, then the model.
   - **Connection**: USB or WiFi.
   - **WiFi Address**: the default of a common mount access point, or the driver
     default.  For another address, use the web interface.
   - **Port** and **Baud Rate**: for USB.  OnStep and most mounts use 9600 baud.

In the web interface
   Open **Mount** in the menu of the web interface.  The page has the same settings,
   a free field for the WiFi address (``host:port``), and the **presets**.

Presets
   A preset sets the mount, the connection, the port, the baud rate and the
   address with one click.  It does not turn mount control on or off.  The PiFinder
   has built-in presets for OnStep (WiFi and USB), the AZ-GTi (WiFi) and the INDI
   telescope simulator.  To make your own preset, set up the mount on the page, type
   a name and click **Save as preset**.  If your preset has the name of a built-in
   preset, your preset replaces it.  Delete your preset to get the built-in preset
   back.


Use the mount
-------------

When mount control is on and the mount is connected, the PiFinder shows **Mount
ready**.  It has sent the GPS location and the time to the mount, unparked it, and
started sidereal tracking.

On an object's detail screen, the number keys control the mount:

===========  ==================================================================
Key          Action
===========  ==================================================================
**1**        Init: connect the mount again and sync it to the last plate solve.
**5**        Goto the object on the screen, and open the mount page.
**7**        Sync the mount to the last plate solve.
**0**        Stop the mount.
**8** **2**  Move up or down in the view by one step.
**4** **6**  Move left or right in the view by one step.
**3** **9**  Make the step smaller or larger.
===========  ==================================================================

The first step is 20% of the eyepiece field of view.  One press moves the telescope by
one step: with a step of 14.6', the object moves 14.6 arcminutes in the eyepiece.

Directions
   By default the direction keys follow the eyepiece view: **8** moves the telescope
   towards what you see at the top of the eyepiece, and **4** towards what you see on
   the left.  The PiFinder works out the view from the last plate solve and the
   telescope's image settings (flip and flop), the same way it turns the object
   images.  Before the first plate solve, and with the **Arrows** setting at
   **Compass**, the keys use north up and east left.  The mount page shows which
   compass direction each key moves to now, for example **↑ S**.

A goto (**5**) opens the mount page.  You can also press the **square** key until it
shows, or use the marking menu.  Its top band shows what the mount
does now, for example **SLEWING 12.4°** with the distance to the object, the step size,
and a bar that fills while the mount slews.  Below the band is a map of the keypad: each
function is where its key is, with **GOTO** in the middle, the four directions around it
and **STOP** across the bottom.  A key flashes when you press it.  On this page the
progress messages do not pop up, because the band shows them; warnings still pop up.
The **Mount** page of the web interface shows the same status.

On the mount page the arrow keys (and the rev 4 joystick) move the mount like **8**,
**2**, **4** and **6**: a short press moves one step.  Hold an arrow to move the mount
continuously at a medium slew speed; it stops when you let go, and after 30 seconds at
the latest.  The key shows inverted while you hold it, and the band shows **MOVING**.
So **LEFT** moves the mount on this page and does not go back.  To leave the page,
press the **square** key.

Hold the **square** key on the mount page for its marking menu: **CONNECT** (connect
the mount again), **SETUP** (the Mount Control settings), **STEP** (the step goes back
to 20% of the field) and **ARROWS** (switch between the eyepiece view and the compass).

When no mount is connected, the mount page is a connection screen instead.  It shows
why the mount is not connected (for example **Mount not found** or **No INDI
server**), the mount and the link that are set up, and two actions: **1 Connect** and
**2 Settings**.  **2** opens the Mount Control settings.  The other keys do nothing on
this screen.

After each command, the PiFinder shows a short message: **Slewing**, **Target
reached**, **Refining 1/3**, **On target**, **Mount synced**, **Mount stopped**, or
the step, for example **North 14.6'**.  A fault shows as a warning, for example
**Mount not found** or **Goto failed!**.

After a goto, the PiFinder waits for a plate solve that was taken after the mount
stopped.  If the object is more than 0.01° from the center, the PiFinder syncs the
mount and moves again, at most three times.  It then shows **On target** or
**Refine stopped**.


Troubleshooting
---------------

**Mount not found**
   Check the cable or the WiFi network, the port and the baud rate.  For WiFi, check
   that the PiFinder is on the mount's network.

**No WiFi in driver**
   The driver of the selected mount has no network connection.  Use USB, or select
   the WiFi model of your mount (for example "AZ-GTi Alt-Az WiFi").

**Replug USB device**
   You changed the GPS Type.  A USB-serial cable that is already plugged in keeps
   its old owner until you plug it in again.

A USB GPS dongle and a USB mount on the same type of USB-serial chip
   With GPS Type **GPSD (generic)**, the PiFinder gives these chips to the GPS
   software, so a mount on the same chip type does not work.  The built-in GPS of the
   PiFinder is not affected.

The mount does not go exactly to the object
   Mount controllers such as OnStepX can have their own pointing model.  It can
   disagree with the plate solve.  The refine step corrects small errors.  For large
   errors, clear the pointing model in the mount controller.
