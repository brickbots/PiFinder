Move to PiFinder Software 3
===========================

PiFinder software 3 runs on NixOS instead of Raspberry Pi OS.  A one-time upgrade moves a
PiFinder from software 2.6.4 to software 3.  The upgrade changes the SD card in place, so you do
not need a new card or a computer.

.. warning::
   The upgrade cannot be undone from the PiFinder.  After the upgrade, you can go back to
   software 2 only if you write a software 2 image to the SD card.

What you need
-------------

* A PiFinder with a Raspberry Pi 4 or a rev 4 PiFinder (CM4).
* At least 2 GB of RAM.
* An SD card of 16 GB or larger, with at least 4 GB free.
* The SD card as a PiFinder image wrote it.  A card with a changed partition layout cannot be
  upgraded.
* Software 2.6.4 or newer.  See :ref:`user_guide:update software`.
* WiFi in Client Mode, on a network with internet access.  See
  :ref:`connectivity:connecting to a new wifi network`.
* USB-C power for the full upgrade.  The upgrade does not start on battery.

If one of these is missing, the PiFinder shows **Cannot upgrade** and the reason, for example
"WiFi must be in client mode".  Nothing changes on the card.

What the upgrade keeps
----------------------

* Your observations and the images of your observations.
* Your observing lists and screenshots.
* Your settings.
* Your WiFi networks.
* The name of the PiFinder on the network, the name of its access point, and the password of
  the ``pifinder`` user.
* The SSH keys.
* The camera type.

Make a backup first
-------------------

The upgrade keeps your data, but make a copy before you start.  Connect to the shared folder
``//pifinder.local/shared`` (see :ref:`connectivity:shared data access`).  Copy
``observations.db``, ``captures/`` and ``obslists/`` to your computer.

Start the upgrade
-----------------

#. Connect the PiFinder to USB-C power.
#. Put the PiFinder in Client Mode on a network with internet access.
#. Select **Software Upd** from the :ref:`user_guide:tools` menu.
#. When the upgrade is available, the screen shows **Major Upgrade**.  It also shows the target
   version, the word **IRREVERSIBLE** and the download size.
#. Select **Confirm**, then press **RIGHT**.

To stop at this step, select **Cancel**.  On battery, the screen shows only **Cancel** and asks
you to plug in USB-C power.

During the upgrade
------------------

.. warning::
   Do not disconnect the power and do not remove the SD card until the PiFinder shows its
   normal screen again.

#. The PiFinder downloads the upgrade, then restarts.
#. The screen shows each step, for example **Converting card**, **Keeping your data** and
   **Installing NixOS**.  **Converting card** takes the longest.  The screen shows the time
   that this step has used.
#. The screen shows **Done, restarting**, and the PiFinder restarts into software 3.
#. At the first start, the PiFinder downloads the newest software 3 version and restarts again.
   Keep WiFi and power on during this step too.

After the upgrade, you get updates from **Software Upd**, as before.

If the upgrade fails
--------------------

* If the upgrade fails before it changes the card, the PiFinder goes back to software 2 by
  itself.
* If the screen shows **FAILED** and the PiFinder does not restart, take a photo of the screen.
  Ask for help on the `PiFinder Discord server <https://discord.gg/Nk5fHcAtWD>`_.
