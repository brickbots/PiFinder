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
**5**        Goto the object on the screen.
**7**        Sync the mount to the last plate solve.
**0**        Stop the mount.
**8** **2**  Move north or south by one step.
**4** **6**  Move west or east by one step.
**3** **9**  Make the step smaller or larger.
===========  ==================================================================

The first step is 20% of the eyepiece field of view.  Press the **square** key until
the mount page shows.  Its first two lines show what the mount does now, for example
**Slewing 12.4°** (the distance to the object) and **Step 14.6'**.  Below them is a
reminder of the keys.  The **Mount** page of the web interface shows the same status.

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
