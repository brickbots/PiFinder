Version 2.5 Upgrade Kit Guide
================================================

Thanks for ordering a PiFinder v2.5 upgrade kit! It contains everything you need to bring your
PiFinder's camera up to v3 capabilities and swap the button faceplate for one labelled to match
the new software.

These photos show a Right-handed PiFinder, but the steps are the same for Left and Flat PiFinders.

Get Started
------------

Unpack your PiFinder v2 and all the kit parts. The photo below shows mine, on a messy workbench
and out of focus.

You also need a small Phillips screwdriver and a pair of side cutters. The whole process takes
about 10 minutes and isn't difficult. Read through this guide once before you start.

.. image:: images/v25_upgrade/v25_upgrade_10.jpeg

Camera Prep
----------------

The new v3 camera ships with one of two lens holders installed. In both cases, remove it and fit
the lens holder from the kit.

.. include:: includes/camera_prep.rst

Installing the Camera
----------------------

On your PiFinder, remove the four screws that hold the camera. If the internal battery is
installed, remove the lens first to make this easier.


.. image:: images/v25_upgrade/v25_upgrade_18.jpeg

.. image:: images/v25_upgrade/v25_upgrade_19.jpeg

Open the camera's cable connector by gently sliding the dark-grey part toward the cable. The cable
then comes loose easily.

Unplug the cable and set the camera aside. Keep the four m2.5 8mm screws.

.. image:: images/v25_upgrade/v25_upgrade_20.jpeg

.. image:: images/v25_upgrade/v25_upgrade_21.jpeg


Remove the four brass stand-offs that held the camera. You no longer need them.

.. image:: images/v25_upgrade/v25_upgrade_22.jpeg

Secure the adapter to the PiFinder back plate with the four screws, as shown. The adapter has an
opening on one side for the cable to exit. Align that opening with the direction the cable comes
from.

.. image:: images/v25_upgrade/v25_upgrade_23.jpeg

Next, connect the cable to the new camera module.

.. include:: includes/camera_cable_connect.rst

.. image:: images/v25_upgrade/v25_upgrade_27.jpeg

Swapping the Faceplate
-----------------------

This part is simple. Ignore the well-used state of my development PiFinder.

Remove the three screws, swap the plate, and screw it back on.

.. image:: images/v25_upgrade/v25_upgrade_28.jpeg

.. image:: images/v25_upgrade/v25_upgrade_29.jpeg

.. image:: images/v25_upgrade/v25_upgrade_30.jpeg

.. image:: images/v25_upgrade/v25_upgrade_31.jpeg

Software and Camera Set Up
----------------------------

To use the new camera, update to the latest PiFinder software. See the
`Version 1.x software update guide <https://pifinder.readthedocs.io/en/v1.11.2/user_guide.html#update-software>`_
for the different ways to update. If your PiFinder is very old, you may need to write a new SD card.

With the new software running, set Camera Type to one of the v3 sensors. Upgrade kits currently
ship with the Sony imx462 or imx296 sensor. The box your camera module came in shows which one
you have. From the main PiFinder menu:

* Scroll down and select Settings

.. image:: images/v25_upgrade/v25_upgrade_41.png

* Scroll down to Advanced, then select Camera Type

.. image:: images/v25_upgrade/v25_upgrade_42.png

* Select either v3 - imx462 or v3 - imx296

.. image:: images/v25_upgrade/v25_upgrade_44.png

Selecting the new sensor restarts the software, but that restart alone does not initialize the
camera. **Fully power the PiFinder off and back on.** Otherwise the camera view stays blank and
it looks as though the change didn't take. After the power cycle, the camera preview shows a
bright image or static, depending on the lighting. With the new camera, set your exposure to 0.4
or 0.2 at most. Try a lower value once you're out under the stars.

That's it. Congratulations on your new PiFinder v2.5.

See the :doc:`quick_start` for details on focusing and an introduction to the new software
interface.
