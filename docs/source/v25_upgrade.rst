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

.. image:: images/v25_upgrade/v25_upgrade_11.jpeg

If your camera has pin headers, clip them as close to the board as you reasonably can.

.. image:: images/v25_upgrade/v25_upgrade_12.jpeg

.. image:: images/v25_upgrade/v25_upgrade_13.jpeg

Look through the lens holder to confirm it's clear of obstructions.

Place the lens holder on the table, large side up, oriented as in the photo below. Its two screw
tabs must stick out the opposite sides from the cream-white and dark-grey cable connector on the
PCB. Remove the two screws (yours might be black) near the center of the green PCB and lift it
gently onto the new lens holder.

Mind the sensor surface on the underside of the PCB; it should sit neatly in the square recess of
the lens holder. Refit the same two screws to fasten the PCB to the lens holder. The screws cut
their own threads, but the holes help get them started. Tighten them down so nothing wiggles.

.. image:: images/v25_upgrade/v25_upgrade_14.jpeg

.. image:: images/v25_upgrade/v25_upgrade_15.jpeg

Flip the camera assembly over and thread in the lens, slowly and carefully. With gentle force it
slides in a few MM, aligns, and stops. Once it stops, check that it sits straight and screw it into
place. For a rough focus, leave a 6mm gap (pictured below) between the top of the lens holder and
the bottom of the lip on the lens. Don't fret over it; you'll do final focus under the stars.

.. image:: images/v25_upgrade/v25_upgrade_16.jpeg

.. image:: images/v25_upgrade/v25_upgrade_17.jpeg

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

Next, connect the cable to the new camera module. Open the connector fully by sliding the dark-grey
piece away from the PCB. Be gentle, as this part breaks with too much force.

With the connector open, slide the cable in with gentle force, keeping it well aligned. Take your
time and watch the dark-grey clip. It should stay open as you insert the cable; if it closes,
re-open it so the cable can slide all the way in.

Once the cable is seated, close the dark-grey clip by sliding it shut. This may take a little force
to fully close. Check the photo below if in doubt!

.. image:: images/v25_upgrade/v25_upgrade_24.jpeg

Situate the camera in the adapter and secure it with the two new screws. They match the other four,
in case they get mixed up.

.. image:: images/v25_upgrade/v25_upgrade_25.jpeg

.. image:: images/v25_upgrade/v25_upgrade_26.jpeg

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

* Choose Camera Type near the bottom

.. image:: images/v25_upgrade/v25_upgrade_42.png

* Choose either v3 - imx462 or v3 - imx296

.. image:: images/v25_upgrade/v25_upgrade_44.png

Your PiFinder reboots, and the camera preview screen shows a bright image or static, depending on
lighting. Set your exposure to 0.4 or 0.2 at most with the new camera, and try lower once you're
out under the stars.

That's it; congratulations on your new PiFinder v2.5.

Check out the :doc:`quick_start` for details on focusing and a primer on the new software
interface.
