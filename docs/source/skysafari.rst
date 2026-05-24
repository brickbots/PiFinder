===============
SkySafari
===============


Network Setup
=============

Before using this guide, make sure that your device is on the same network as the PiFinder.  See the :ref:`User Guide<user_guide:wifi>` for details on changing WiFi modes and finding the IP address of the PiFinder

App Setup
===============

Connecting to a telescope requires SkySafari Plus or Pro and the first step is to setup a telescope profile.  Do this via the settings page in the Telescope section:


.. image:: images/SkySafari/IMG_4792.jpeg
   :alt: Setup


After clicking 'Presets', use the + button at the bottom right to add a new profile.


.. image:: images/SkySafari/IMG_4793.jpeg
   :alt: Type


Select 'Other' as the telescope type


.. image:: images/SkySafari/IMG_4794.jpeg
   :alt: Setup


The 'Alt-Az.' GoTo as the scope type, even if you don't have a GoTo scope.  Selecting GoTo here allows you to send objects from SkySafari to the PiFinder observing list if desired.


.. image:: images/SkySafari/IMG_4796.jpeg
   :alt: Setup


Select 'Meade LX200 Classic' for the scope type and click 'Next'


.. image:: images/SkySafari/IMG_4797.jpeg
   :alt: Setup


You should be able to use ``pifinder.local`` for the IP address, but if this does not work, check the Status screen for the numeric IP address of the PiFinder.  Port 4030 seems to be the default for SkySafari, but change it to 4030 if there is another value populated.

Click 'Next' to continue


.. image:: images/SkySafari/IMG_4798.jpeg
   :alt: Setup


The defaults are good for the Readout rate and Timeout.  Give your profile a name and click the 'Save Preset' button.  This will save your new profile and make it the active one.

Now you should be able to select the Telescope icon on the main SkySafari screen and click the connect button to start requesting position updates from the PiFinder.  If no solution has been obtained yet, the PiFinder will send a default location to SkySafari (0 degrees RA/DEC) until it completes the first exposure/solve.

Using SkySafari
===============

Once connected, SkySafari and the PiFinder work together in two main ways:

* **Follow your scope on the star chart.**  As you move the telescope, the PiFinder reports
  its solved position and SkySafari keeps your location marked on its chart — a large,
  zoomable view of where you are pointed.  This is especially handy near the zenith, where
  the PiFinder's own Push-To numbers become twitchy.
* **Send targets to the PiFinder.**  Pick an object in SkySafari and send it to the
  PiFinder's observing list, then use the PiFinder's Push-To guidance to find it.  It is a
  comfortable alternative to entering objects with the keypad.

A few things are worth knowing about what the connection does today:

* SkySafari does **not** command the PiFinder to slew or auto-center a GoTo mount.  The
  connection is for reading out position and sending targets; GoTo control is in
  development.
* Only **one** device can be connected to the PiFinder at a time.  To connect from a
  different phone or tablet, disconnect the first one.
* The PiFinder cannot talk to SkySafari and a GoTo mount at the same time — choose one.
* SkySafari 5 Plus, 6, and 7 all work; version 7 is the most reliable.

.. note::
   If the PiFinder drops into power-save mode it stops sending position updates, so
   SkySafari appears to freeze.  When you are relying on SkySafari, lengthen or turn off
   the sleep timer (see :ref:`quick_start:adjusting brightness`).

Troubleshooting
===============

**SkySafari won't connect, or the connection keeps dropping.**
The usual cause is your phone or tablet quietly leaving the ``PiFinderAP`` network.  Because
that network has no internet access, many devices switch back to cellular or a home network
in the background, which breaks the link.  Re-select ``PiFinderAP`` in your device's WiFi
settings, and if it offers a "smart network switching" or "auto-switch to mobile data"
option, turn that off.

**``pifinder.local`` doesn't resolve.**
Some phones and networks cannot reliably look up the ``.local`` name.  Use the PiFinder's
numeric IP address instead — you will find it on the Status screen.  In Access Point mode
that address is ``10.10.10.1``.

**It connects, but the position never updates.**
Until the PiFinder completes its first plate solve it reports 0°/0°, so give it a moment
with the camera focused on the sky.  If the position was updating and then froze, the
PiFinder has most likely entered power-save mode — see the note above.

**The connection is intermittent at a star party.**
Two nearby PiFinders using the same network name (SSID) can interfere with each other.
Give each one a distinct network name to avoid this.
