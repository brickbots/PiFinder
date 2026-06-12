Version 2.5 Upgrade Kit Guide
================================================

Thanks for ordering a PiFinder v2.5 upgrade kit! It contains everything you need to bring your
PiFinder's camera up to v3 capabilities and swap the button faceplate for one labelled to match
the new software.

These photos show a Right-handed PiFinder, but the steps are the same for Left and Flat units.

Get Started
------------

Unpack your PiFinder v2 and all the kit parts. Put them on a messy workbench and take an
out-of-focus picture....

You'll also need a small Phillips screwdriver and a pair of side cutters. The whole process takes
about 10 minutes and isn't tricky, but read through this guide once before diving in.

.. image:: images/v25_upgrade/v25_upgrade_10.jpeg

Camera Prep
----------------

The new v3 camera ships with one of two lens holders installed. Either way, you'll remove it and
fit the one from the kit.

.. include:: includes/camera_prep.rst

Installing the Camera
----------------------

Grab your PiFinder and remove the four screws holding the camera. If the internal battery is
installed, it's easier to remove the lens first.


.. image:: images/v25_upgrade/v25_upgrade_18.jpeg

.. image:: images/v25_upgrade/v25_upgrade_19.jpeg

Open the camera's cable connector by gently sliding the dark-grey part toward the cable. The cable
then comes loose easily.

Unplug the cable and set the camera aside, saving the four m2.5 8mm screws.

.. image:: images/v25_upgrade/v25_upgrade_20.jpeg

.. image:: images/v25_upgrade/v25_upgrade_21.jpeg


Remove the four brass stand-offs that held the camera; these are no longer needed.

.. image:: images/v25_upgrade/v25_upgrade_22.jpeg

Use the four screws to secure the adaptor to the PiFinder back plate as shown. The adapter has an
opening on one side for the cable to exit; align it with the direction the cable comes from.

.. image:: images/v25_upgrade/v25_upgrade_23.jpeg

Next, connect the cable to the new camera module.

.. include:: includes/camera_cable_connect.rst

.. image:: images/v25_upgrade/v25_upgrade_27.jpeg

Swapping the Faceplate
-----------------------

Not much to say here, except to ignore the well-used state of my development PiFinder.

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

With the new software running, switch the camera type to one of the v3 sensors. Upgrade kits
currently ship with the Sony imx462 or imx296 sensor; the box your camera module came in indicates
which. From the main PiFinder menu:

* Scroll down and choose Settings

.. image:: images/v25_upgrade/v25_upgrade_41.png

* Scroll down to Advanced, then choose Camera Type

.. image:: images/v25_upgrade/v25_upgrade_42.png

* Choose either v3 - imx462 or v3 - imx296

.. image:: images/v25_upgrade/v25_upgrade_44.png

Choosing the new sensor restarts the software, but that restart alone won't initialize the
camera.  **Fully power the PiFinder off and back on** — otherwise the camera view stays blank
and it looks as though the switch didn't take.  After the power cycle the camera preview shows
a bright image or static, depending on lighting. Set your exposure to 0.4 or 0.2 at most with
the new camera, and try lower once you're out under the stars.

That's it; congratulations on your new PiFinder v2.5.

Check out the :doc:`quick_start` for details on focusing and a primer on the new software
interface.
