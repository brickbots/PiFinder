
===========
Build Guide
===========

Introduction and Overview
=================================

.. note::
   This guide covers the self-built (DIY) PiFinder. It uses the v2.5 hardware
   and comes together in one of three configurations: Left, Right, or Flat.
   v3 PiFinders ship assembled and do not use these instructions.

Welcome to the PiFinder build guide. The build has three main parts: the :ref:`UI Hat <build_guide:pifinder ui hat>` with its screen and buttons, :ref:`3d printing <build_guide:printed parts>` and preparing the case parts, and :ref:`final assembly <build_guide:assembly>`. The :doc:`Bill of Materials <BOM>` lists every part you need. Send any questions by `email <mailto:info@pifinder.io>`_ or on `discord <https://discord.gg/Nk5fHcAtWD>`_.


PiFinder UI Hat
========================

A key part of the PiFinder is the UI Hat, a custom board that matches the general form factor of the Raspberry Pi and connects to its GPIO header. It carries the switches, the screen, the Inertial Measurement Unit, and the keypad backlight components.

Every component is through-hole, so this build is approachable even for beginners. The build order matters, though, because some components block access to others.

Some photos here still show the v1 non-backlit board, but the assembly is the same once the backlight components are in place.

You need both PCBs to start. One holds the electronic components. The other carries the shine-through legends and goes on top of the assembled board at the end. The main `PiFinder git repo <https://github.com/brickbots/PiFinder/tree/release/gerbers>`_ holds the Gerber files for both.

Backlight Components
------------------------

Start with the LEDs. They sit close to the board, so fitting them first makes them easier to align.

.. image:: images/build_guide/ui_module_1.jpeg


Polarity matters, so check the direction of each LED. The longer lead goes through the round hole in the footprint. The photo below shows the orientation.

.. image:: ../../images/build_guide/led_build_03.jpeg

Position each LED carefully. Keep them fairly uniform, though small inconsistencies don't matter much. Place them all in the board, then tape them in place.

.. image:: images/build_guide/ui_module_2.jpeg

.. image:: images/build_guide/ui_module_3.jpeg

Pull the legs straight and solder one leg of each LED. Remove the tape and check again. If any are wildly out of place, reheat that one joint and adjust.

.. image:: images/build_guide/ui_module_4.jpeg

When you are happy with the alignment, solder the remaining legs and clip the leads down to a single pair. Leave one pair of legs long. You need them to power the backlight for the test in the next section.

.. image:: images/build_guide/ui_module_5.jpeg

Fit the two resistors and the transistor next. R2 is the 330 ohm part and stands vertically. R1 is the 22 ohm part and lies horizontally. Direction doesn't matter for the resistors, but it does for the transistor. Check the photo below for the orientation. Make sure the transistor sits flat against the PCB and the resistors sit low. Solder from the back and clip the leads once they look good.

.. image:: images/build_guide/ui_module_6a.jpeg

Testing the Backlight
^^^^^^^^^^^^^^^^^^^^^^

Test the backlight and the LEDs now with any 3V coin cell, such as a CR2032. Connect the positive side of the battery to the longer pin of an LED and the negative side to the shorter pin, as shown below with a single LED. The LEDs are wired in parallel on the board, so this lights all of them at once. Every LED should light up:

.. image:: images/build_guide/test_leds_1.jpeg

Replace any LED that doesn't light before you continue.

Switches
------------------------

Fit the switches next. Place each one on its footprint and press it down fully. Before you solder, check that none of them sit tilted.


.. image:: images/build_guide/ui_module_6b.jpeg


Place the top legend plate over them to confirm they all clear the holes properly. Then solder them. You don't need to clip the switch leads, because they have plenty of room.

.. image:: images/build_guide/ui_module_6c.jpeg


Headers
---------

Fit the headers next. They receive the IMU, the GPS module, and the screen. The procedure is the same for all three: insert the header, solder one pin, check that it sits flat and straight, then solder the rest. Clip the pins flush and apply some insulating tape.

Start with the IMU header. It goes on the underside of the board. Solder it from the top.

.. image:: images/build_guide/ui_module_7.jpeg

.. image:: images/build_guide/ui_module_8.jpeg

Apply the insulating tape. Fit the screen header next. It goes in from the top side:

.. image:: images/build_guide/ui_module_9.jpeg

Trim the pins and tape it up.

.. image:: images/build_guide/ui_module_10.jpeg

Fit the GPS header next. The modules ship with a yellow header, but any header works. Insert it from the bottom, then solder and tape it like the rest.

.. image:: images/build_guide/ui_module_11.jpeg

.. image:: images/build_guide/ui_module_12.jpeg


IMU
------------------------

Fit the Inertial Measurement Unit next. It has an annoyingly bright green LED. Paint over it with a few layers of black nail polish, or destroy it with your soldering iron. You can deal with it after soldering if you forget, but it is much easier beforehand. The image below shows the offending component.

.. image:: ../../images/build_guide/adafruit_IMU.png
   :target: _images/adafruit_IMU.png
   :alt: Green led on IMU


The photo below shows the orientation on the back of the PCB. Make sure the IMU sits flat and square with the board. It doesn't need to be perfect, but it must be secure and low-profile. Solder it into position.

.. image:: images/build_guide/ui_module_13.jpeg


Display
------------------

The screen comes next. It covers the solder points of the IMU header, so check those joints before you continue.

Unscrew the stand-offs from the front and remove them.


.. image:: ../../images/build_guide/IMG_4648.jpeg
   :target: _images/IMG_4648.jpeg
   :alt: Display as shipped



.. image:: ../../images/build_guide/IMG_4649.jpeg
   :target: _images/IMG_4649.jpeg
   :alt: Display with standoffs removed


Next, remove the plug from the underside of the board. This step isn't strictly necessary, but it helps the screen sit lower and flatter. First cut each lead to the connector with sharp cutters. Cut low, though the exact spot isn't critical. Then cut away the plastic at the attachment points on both short sides with clippers.


.. image:: ../../images/build_guide/IMG_4650.jpeg
   :target: _images/IMG_4650.jpeg
   :alt: Connector cut free


Sand back or cut the bottom tabs on the screen PCB. This makes the top plate fit better and look tidier. The tabs carry no circuitry and only provide screw points you don't need.


.. image:: ../../images/build_guide/IMG_4652.jpeg
   :target: _images/IMG_4652.jpeg
   :alt: Cut/Sand tabs on display


Test-fit the screen with the header installed and the top plate in place. Everything should fit neatly and sit square.


.. image:: ../../images/build_guide/IMG_4653.jpeg
   :target: _images/IMG_4653.jpeg
   :alt: Screen test fit


Solder the screen in place. Solder one pin first and check all around to make sure the screen sits flat. If it doesn't, heat that one joint and adjust.

.. image:: images/build_guide/ui_module_14.jpeg

GPS
------------------

.. danger::
   Complete the :ref:`Testing the Backlight <build_guide:testing the backlight>` step before you solder on the GPS module. The GPS module blocks access to some LED pins. To replace a blocked LED, you have to remove the module first. Removing it is difficult and can destroy the PCB. It has happened to us. Make sure the LEDs work before you continue.

   If you do need to desolder the GPS module later, work slowly and carefully, and use a desoldering pump.


.. caution::
   The GPS module also blocks access to some switch pins, so you can leave it out entirely until the end if you want to test the switches. The GPIO connector that attaches the UI Hat to the Raspberry Pi then makes this awkward.

   We don't recommend it. The LEDs have given us trouble in the past, but the switches have usually been rock solid.


The last active component is the GPS module. It goes component side up so you can access the antenna plug. Check the photo below and solder it securely.

.. image:: images/build_guide/ui_module_15.jpeg

Connect the antenna to the GPS module. The plug is fiddly, so check the alignment carefully before you apply much force. It snaps in and then rotates easily.

.. list-table::

   * - .. image:: images/build_guide/common_3.jpeg

     - .. image:: images/build_guide/common_4.jpeg


The route of the antenna cable matters for reception. Tape the cable to the back of the board as shown below. This keeps it secure and out of the way during the build.


.. image:: images/build_guide/ui_module_15b.jpeg

Connector
------------------

The GPIO connector is the last soldered part of the UI Hat. To space it correctly, mount the PCB to your Pi with the stand-offs you use for final assembly.

The pins of the connector are long, so they suit a range of spacings. Plug the connector firmly into your Pi, mount the UI Hat with stand-offs and screws, then solder the connector at the correct spacing.

Add any heatsinks you plan to use first. Before you solder, take your time and check that the UI Hat sits securely on the Pi, that no parts interfere mechanically, and that you are happy with the spacing.

The photos below show the procedure, which is easier than it sounds. There are a lot of pins, so solder each one securely. This part takes force every time you install or remove the UI Hat.

.. image:: images/build_guide/ui_module_16.jpeg

.. image:: images/build_guide/ui_module_17.jpeg

With all the pins soldered, insert the SD card and turn the PiFinder on to check that everything works.

.. image:: images/build_guide/ui_module_18.jpeg

Once it has started completely, the :ref:`menu system <user_guide:the menu system>` appears. Use the buttons below the screen to scroll and select. The faceplate shows what each button does.

From the main menu, select Tools, then select Status to open the :ref:`Status screen <user_guide:status screen>`. Check that the PiFinder detects the IMU. The "IMU" lines show some numbers when it does. Then select Objects, select Name Search, and enter a few letters of an object name to test the keypad. The keypad is now working properly.

The UI Hat is now fully assembled. Move on to printing your parts or to :ref:`final assembly <build_guide:assembly>`.

Configurations Overview
========================

You can build the PiFinder in three configurations, so that it works conveniently on a wide range of telescopes.


.. list-table::

   * - .. figure:: images/build_guide/config_example_left.jpeg

          Left Handed

     - .. figure:: images/build_guide/config_example_right.jpeg

          Right Handed

     - .. figure:: images/build_guide/config_example_flat.jpeg

          Flat

Any configuration works with any telescope. The camera always needs to face the sky, so the configurations differ in where they put the screen and the keypad for easy access. The Left and Right configurations mainly suit newtonian-style telescopes, such as Dobsonians, whose focuser sits perpendicular to the light path.

The Flat configuration puts the keypad and the screen in easy reach on refractors, SCTs, and other rear-focuser telescopes. When the telescope points upward, the screen tilts towards you for quick access.

All the STL files for the PiFinder case parts are in the main `PiFinder git repo case folder <https://github.com/brickbots/PiFinder/tree/release/case>`_.


Printed Parts
===========================


You can build the PiFinder in a left, right, or flat configuration to suit many telescopes. See the :ref:`configurations overview <build_guide:configurations overview>` for more, including example photos. Each configuration needs only some of the available parts.


Common Parts
-----------------------

Some parts are common to all three configurations. Every build uses the Bezel, the Camera Cover, and the Pi Mount.

Right and Left configurations
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The photo below shows all the parts for a left- or right-hand PiFinder. The edge inserts let these pieces assemble into either configuration, so you need just one set of parts whichever side your focuser faces. The assembly guide covers how to orient the pieces as you put them together.

.. image:: images/build_guide/parts_1.jpeg
   :target: _images/parts_1.jpeg



Flat Configuration
^^^^^^^^^^^^^^^^^^

The photo below shows the pieces for the flat version. The parts are the same with or without a PiSugar battery.

.. image:: images/build_guide/parts_2.jpeg
   :target: _images/parts_2.jpeg


Printing
--------

These pieces print without supports in the orientation shown. I use 3 perimeter layers and 15% infill. The parts are small and don't take heavy forces, so almost any print settings work.

Print in a material other than PLA. Your PiFinder probably sees some sunlight, and PLA degrades under moderate heat and UV. PETG or a co-polymer such as NGen is a good choice. Prusament Galaxy PETG is the official PiFinder filament and appears in most of this guide, except where grey provided needed contrast.

Inserts
-------

Only some holes take inserts. The rest take M2.5 screws that pass through into inserts in other pieces. The brass inserts used here are M2.5 x 4mm long. Some go into holes through the full thickness of the piece, and some go into blind holes in the edges. The photos below show each part that takes inserts:

Pi Mount
^^^^^^^^^

The Pi Mount takes eight inserts total: four in the printed stand-offs and four in the edges.

.. image:: images/build_guide/parts_3.jpeg
   :target: _images/parts_3.jpeg

.. image:: images/build_guide/parts_4.jpeg
   :target: _images/parts_4.jpeg

Bottom
^^^^^^^

For left/right builds this is the bottom piece. It needs four inserts to attach the dovetail mount.

.. image:: images/build_guide/parts_5.jpeg
   :target: _images/parts_5.jpeg


Flat Adaptor
^^^^^^^^^^^^^
.. note::
   The photos for the Flat Adaptor and the Back show the v2 build. The v2.5 parts
   are almost identical, but they have 2 camera mount holes rather than 4.

This piece replaces the bottom and back pieces from the left/right build. It needs eight inserts: four to attach the dovetail mount and four to attach the camera.

.. image:: images/build_guide/parts_6.jpeg
   :target: _images/parts_6.jpeg


Back
^^^^^^^^^

The back piece holds the camera for left/right builds. It also reinforces the Pi Mount and the Bottom piece to keep everything square and sturdy. It needs six inserts: four to mount the camera and two in the bottom edge to connect with the bottom piece.

.. image:: images/build_guide/parts_7.jpeg
   :target: _images/parts_7.jpeg

Dovetail Bottom
^^^^^^^^^^^^^^^^

The dovetail bottom has two inserts for the longer 12mm screws that allow angle adjustment. These inserts go in the side opposite where the top piece connects. The screws pass through the top piece and part of the bottom before they engage the inserts. This makes the assembly strong enough to hold the angle you set once the screws are tight enough.

.. image:: images/build_guide/parts_8.jpeg
   :target: _images/parts_8.jpeg


Installation
^^^^^^^^^^^^^

I use a lot of these inserts, so I use a tool to seat them plumb into the parts. I have also done plenty freehand, and it isn't difficult. Use a temperature a bit below your normal printing temperature (I print PETG at 230c and use 170-200c for inserts) and give the plastic time to melt around them.


.. image:: ../../images/build_guide/v1.4/build_guide_02.jpg
   :target: _images/build_guide_02.jpg
   :alt: Insert Inserting



Mounting
--------

Most people print the dovetail mount. It fits the finder shoe included on most telescopes. The angle of the dovetail mount adjusts, so you can set the screen surface roughly vertical and perpendicular to the ground. This puts the IMU into its expected position. The image below explains it more clearly:


.. image:: ../../images/finder_shoe_angle.png
   :target: _images/finder_shoe_angle.png
   :alt: Finder shoe angle


Adjustable Dovetail Assembly
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

If you print your own parts, add heat-set inserts as pictured in the photo above. The inserts must go in from the outside of the bottom piece, as pictured. The holes on the inside aren't large enough for inserts. They only let the screws pass through into the inserts.

The photos below show how the pieces fit together. Once assembled, loosen both screws to adjust the angle up to 40 degrees from horizontal, then secure them again. They don't need to be too tight, but they need a bit of friction to hold the angle.


.. image:: images/build_guide/dovetail_1.jpeg

.. image:: images/build_guide/dovetail_2.jpeg

.. image:: images/build_guide/dovetail_3.jpeg

.. image:: images/build_guide/dovetail_4.jpeg


If you need more flexibility, a go-pro compatible plate also bolts into the bottom plate. To use it, add inserts to the mounting footprint on the bottom plate.

Once all the parts are printed and the inserts are seated, you're ready to :ref:`assemble <build_guide:assembly>`.

Rigel Quikfinder Assembly
^^^^^^^^^^^^^^^^^^^^^^^^^

You need the following for a Rigel Quikfinder adapter:

.. list-table::
   :header-rows: 1

   * - Qty
     - Item
     - URL
     - Notes
   * - 1
     - PiToQuikfinder v2 - Part 1.stl
     - `git repo quikfinder <https://github.com/brickbots/PiFinder/tree/release/case/adapters/quikfinder>`_
     - You need both this and the next item
   * - 1
     - PiToQuikfinder v2 - Part 2.stl
     - `git repo quikfinder <https://github.com/brickbots/PiFinder/tree/release/case/adapters/quikfinder>`_
     - You need both this and the previous item
   * - 2
     - heat-set insert M2.5 x 4 mm
     -
     - Same as for the case

Print "Part 2" to maximize the strength of the "hook". Print it with supports, as shown below:

.. image:: images/build_guide/quickfinder_base_4.jpeg

If you print your own parts, add heat-set inserts as pictured below. Space is limited, so fix it to the PiFinder first and then insert the second part. Tighten the screws just a little to hold the second part so it can't fall off.

After you put it on a Rigel Quikfinder base, tighten the screws fully. The double-sided foam adhesive supplied with the Rigel Quikfinder may compress under the weight of the PiFinder, which is about 6 times the weight of a Quikfinder. You may need to fix the base plate to your telescope another way.


.. image:: images/build_guide/quickfinder_base_1.jpeg

.. image:: images/build_guide/quickfinder_base_2.jpeg

.. image:: images/build_guide/quickfinder_base_3.jpeg


To adjust the orientation of your PiFinder so it stands vertical on your telescope, you also need these:

.. list-table::
   :header-rows: 1

   * - Qty
     - Item
     - URL
     - Notes
   * - 1
     - Pi2Q2Dovetail.stl
     - `git repo quikfinder <https://github.com/brickbots/PiFinder/tree/release/case/adapters/quikfinder>`_
     - You need at least this and the next item
   * - 1
     - dovetail_top.stl
     - `git repo dovetail <https://github.com/brickbots/PiFinder/tree/release/case/v2>`_
     - You need at least this and the previous item
   * - 6
     - heat-set insert M2.5 x 4 mm
     -
     - Same as for the case

Add 4 heat-set inserts as shown in the photos below:

.. image:: images/build_guide/quickfinder_base_5.jpeg

.. image:: images/build_guide/quickfinder_base_6.jpeg

Assembly then follows the dovetail assembly in the previous section. You can fix the optional adapter in either of two orientations, depending on your needs. Make sure the "long lip" points in the same direction as the PiFinder. The photos below show the fully assembled adapter:

.. image:: images/build_guide/quickfinder_base_7.jpeg

.. image:: images/build_guide/quickfinder_base_8.jpeg

Once all the parts are printed and the inserts are seated, you're ready to :ref:`assemble <build_guide:assembly>`.


Assembly
======================


Assembly Overview
-----------------

From here you need the M2.5 screws, stand-offs, and thumbscrews, along with the 3d printed parts, the UI Hat, and the camera, lens, and GPS module. Most photos in this part show a build with the PiSugar. If you power the PiFinder another way, the assembly is almost identical.

*In all cases, don't over tighten the hardware.* There's no need, and you could damage the 3d printed pieces, inserts, or screws. Once they feel snug, that's enough. Once everything is in place, the case forms a rigid assembly that easily supports the camera and the other parts.

Pi Mounting
---------------------------

First, mount the Pi and the PiSugar battery to the Pi Mount piece. The photo below shows the pieces you need.


.. image:: images/build_guide/common_1.jpeg
   :target: _images/common_1.jpeg
   :alt: Build Guide Step


Whatever the orientation of your build, the Raspberry Pi and the battery always mount this same way, on top of the posts in the Pi Mount.

If you use a PiSugar, mount the battery pack now. Otherwise, skip this step. Flip the Pi Mount piece over and secure the battery with the zip ties as shown. Don't tighten these much, because that may damage the battery. Tighten them just enough to keep the battery from moving too much.

Orient the battery pack so the connector sits in the notch, as shown below.


.. image:: images/build_guide/common_1b.jpeg
   :target: _images/common_1b.jpeg


Snip off the loose ends of the zip ties, then move on.


.. image:: images/build_guide/common_1c.jpeg
   :target: _images/common_1c.jpeg



Camera Prep
---------------------------

The new v3 camera comes with one of two lens holders already installed. Remove and replace it in either case.

.. include:: includes/camera_prep.rst


Cable Routing
---------------------------

For a flat build, set the camera cable aside, because it routes differently. For left/right builds, it's easier to position the cable roughly now.

Return to the Raspberry Pi assembly and thread the camera cable through as shown. Note the orientation of the silver contacts at each end of the cable. The photos below show the cable routing for left- and right-hand builds.

.. list-table::

   * - .. image:: images/build_guide/left_1.jpeg
          :target: _images/left_1.jpeg

       Left hand cable routing

     - .. image:: images/build_guide/right_1.jpeg
          :target: _images/right_1.jpeg

       Right hand cable routing

.. important::
    If you use the recommended PiSugar S Plus, prepare it now.

    * Set the 'Auto Startup' switch on the bottom of the PiSugar to OFF. If you leave it ON, i2c does not work and the PiFinder cannot use the IMU. The orange outline in the image below shows the switch in the correct OFF position.

    * The blue power light on the PiSugar board is very bright. Cover it with black nail polish or destroy it with a soldering iron. Plug the board into the battery and turn it on to confirm the light is subdued. The orange arrow in the image below points to the LED you need to cover. The photo shows it already blacked out with nail polish.


.. image:: ../../images/build_guide/pisugar_setup.jpg
   :target: _images/pisugar_setup.jpg
   :alt: Build Guide Step


The PiSugar ships with a protective film on the screw posts, as shown below. Remove it, or the screws are frustrating to fit.


.. image:: ../../images/build_guide/v1.6/build_guide_01.jpeg
   :target: _images/build_guide_01.jpeg
   :alt: Build Guide Step


The PiSugar sits under the Raspberry Pi with the gold pogo pins pressed against the bottom of the Pi. The side facing up in the image above presses against the bottom of the Raspberry Pi. The PiSugar documentation covers this in more detail.

Secure the combined PiSugar/RPI stack to the Pi Mount with the 20mm stand-offs. The photos below show the right- and left-hand stacks with their respective cable routing. Flat configurations build the same way, without any camera cable.

.. list-table::

   * - .. figure:: images/build_guide/left_2.jpeg

          Left hand PiSugar stack

     - .. figure:: images/build_guide/right_2.jpeg

          Right hand PiSugar stack

   * - .. figure:: images/build_guide/left_3.jpeg

          Secured with stand offs

     - .. figure:: images/build_guide/right_3.jpeg

          Secured with stand offs



Right / Left Configuration
---------------------------

Continue here to build a right- or left-hand PiFinder. The build is the same for both versions, with some differences in part orientation. Each step shows photos with the left-hand version on the left and the right-hand version on the right.

Now that the RPI is mounted, secure the Pi Mount to the bottom plate. You can flip the bottom plate so the screen faces the right or the left side, as the two photos below show.

In both cases, the RPI/Screen always faces the same direction as the long, flat side of the bottom piece. The angled cutout is always on the camera side, and the lens faces the angled portion.

.. list-table::

   * - .. image:: images/build_guide/left_4.jpeg

     - .. image:: images/build_guide/right_4.jpeg


First, screw the Pi Mount assembly to the bottom plate. Use two screws from underneath, running through the bottom plate into the threaded inserts in the side of the Pi Mount piece.


.. list-table::

   * - .. image:: images/build_guide/left_5.jpeg

     - .. image:: images/build_guide/right_5.jpeg



The back piece is next. First screw in the four short stand-offs that support the camera module. These can go on either side for left- or right-hand configurations. Check the photos below to see how the back piece fits each configuration, then decide which side takes the stand-offs.

.. list-table::

   * - .. image:: images/build_guide/left_6.jpeg

     - .. image:: images/build_guide/right_6.jpeg

   * - .. image:: images/build_guide/left_7.jpeg

     - .. image:: images/build_guide/right_7.jpeg

Secure the back piece to the assembly with three M2.5 8mm screws. One goes through the back plate into the side-insert in the Pi Mount. The Pi Mount has one of these inserts on either side, for left- and right-hand builds. The other two go through the bottom plate into the side-inserts on the back plate.


.. list-table::

   * - .. image:: images/build_guide/left_8.jpeg

     - .. image:: images/build_guide/right_8.jpeg

   * - .. image:: images/build_guide/left_9.jpeg

     - .. image:: images/build_guide/right_9.jpeg

Now mount the camera module. You need the module, the camera tray, and 2x 12mm M2.5 screws.

.. note::
   The images here show an older back piece and camera tray. New kits have a back piece
   with two holes which match the camera holder. In this simpler arrangement the camera
   tray has two holes through it and does not screw directly to the back piece.
   Longer screws pass through the tray and into the two holes in the back piece to hold
   the camera holder.

Connect the cable to the new camera module first.

.. include:: includes/camera_cable_connect.rst

.. note::
   The photos in the rest of this guide do not yet show the v3 camera.
   The build proceeds just the same, and we will update the photos soon.


Flip the PiFinder over and connect the RPI end of the camera cable. The photo below shows the proper cable orientation into the connector, with the silver contacts facing the white portion of the connector.

.. image:: images/build_guide/assembly_insert_cable.jpeg

The left-hand version needs a twist in the cable before it enters the connector on the RPI. Work gently. You can adjust the twist when you fit the UI Hat later.

.. list-table::

   * - .. image:: images/build_guide/left_14.jpeg

     - .. image:: images/build_guide/right_14.jpeg

.. note::
   The rest of the build is almost the same for left- and right-hand builds. The photos below mix left and
   right handed builds. Where the difference is important, both appear for clarity.


Next, connect the UI Hat and fit the shroud. Lay the board out as it connects and slide the antenna into the holder on the Pi Mount piece. The ceramic top with the silver dimple needs to face upwards. See the photos below.

.. image:: images/build_guide/right_16.jpeg

.. image:: images/build_guide/right_17.jpeg

.. image:: images/build_guide/right_18.jpeg

.. note::
   The images above show the GPS cable loose and routed incorrectly. Use the
   routing shown in the :ref:`GPS <build_guide:gps>` section.

Now plug the UI Hat carefully into the Raspberry Pi. Make sure both rows of pins line up, and take your time with the camera and GPS cables. The photos below show the cable routing for the left and right configurations.

.. list-table::

   * - .. image:: images/build_guide/left_20.jpeg

     - .. image:: images/build_guide/right_20.jpeg


The screw holes on the UI Hat should line up with three of the four stand-offs. The fourth provides support but does not secure the outer case. Collect the Shroud, the Bezel, and the cover plate, along with three of the 12mm screws, for the next steps.

.. image:: images/build_guide/common_5.jpeg
   :target: _images/common_5.jpeg


The shroud has three optional openings: one on top for the PiSugar power switch, one for the USB ports, and one on the side for easier access to the SD card. Remove these with a little force or a sharp knife. If you use a PiSugar battery, you must remove the power switch tab. See the photo below:

.. image:: images/build_guide/common_6.jpeg

Slide the shroud over the PiFinder, then stack the bezel and the front PCB plate on top. Secure them all with the three screws.

.. image:: images/build_guide/common_7.jpeg

.. image:: images/build_guide/common_8.jpeg

.. image:: images/build_guide/common_9.jpeg

.. image:: images/build_guide/common_10.jpeg

That's looking great. The PiFinder now needs a way to mount to the telescope. The top portion of the adjustable dovetail screws directly to the bottom of the PiFinder. The bottom portion then secures to the top. The orientation of the top part matters, so that the dovetail adjusts the proper way. See the left- and right-hand photos below:


.. image:: images/build_guide/right_21.jpeg

.. image:: images/build_guide/right_22.jpeg


The final dovetail assembly is tricky to photograph on the PiFinder. Follow the photos below and secure the bottom dovetail portion to the top:

.. image:: images/build_guide/dovetail_1.jpeg

.. image:: images/build_guide/dovetail_2.jpeg

.. image:: images/build_guide/dovetail_3.jpeg

.. image:: images/build_guide/dovetail_4.jpeg



That's it! You now have a fully assembled PiFinder.

If you haven't already prepared an SD card, continue to the :doc:`software setup <software>`.


.. image:: images/build_guide/common_11.jpeg
   :target: _images/common_11.jpeg


Flat Assembly
----------------

This section covers a Flat build. This configuration is great for refractors, SCTs, and other rear-focuser telescopes. The screen sits 'flat' when mounted and the camera faces forward:


.. image:: ../../images/flat_mount.png
   :target: _images/flat_mount.png
   :alt: Flat example


Follow the :ref:`general assembly guide <build_guide:assembly>` through to the point pictured below, then return here.


.. image:: ../../images/build_guide/v1.6/build_guide_11.jpeg
   :target: _images/build_guide_11.jpeg
   :alt: Pi Module Assembled


If you routed the cable as above, pull the camera cable out of the RPI assembly. The routing differs for a flat build.

Collect the flat adapter and the dovetail. The dovetail secures to the underside of the flat adapter with screws through the adapter. The Pi Mount assembly slots into the flat adapter, and screws into the edge inserts hold it there. See the photos below for details.

.. image:: ../../images/build_guide/v1.6/flat/flat_build_guide_01.jpeg
   :target: _images/flat_build_guide_01.jpeg
   :alt: Assembly Steps


.. image:: ../../images/build_guide/v1.6/flat/flat_build_guide_02.jpeg
   :target: _images/flat_build_guide_02.jpeg
   :alt: Assembly Steps


.. image:: ../../images/build_guide/v1.6/flat/flat_build_guide_03.jpeg
   :target: _images/flat_build_guide_03.jpeg
   :alt: Assembly Steps


.. image:: ../../images/build_guide/v1.6/flat/flat_build_guide_04.jpeg
   :target: _images/flat_build_guide_04.jpeg
   :alt: Assembly Steps


.. image:: ../../images/build_guide/v1.6/flat/flat_build_guide_05.jpeg
   :target: _images/flat_build_guide_05.jpeg
   :alt: Assembly Steps


Note the one additional screw on the other side, visible in the next photo. Once the Pi Mount is secure in the flat adapter, connect the camera cable to the RPi and to the camera as shown below.


.. image:: ../../images/build_guide/v1.6/flat/flat_build_guide_06.jpeg
   :target: _images/flat_build_guide_06.jpeg
   :alt: Assembly Steps


Turn the PiFinder around and screw in the three thumbscrews as shown. Check the threads for excess plastic. If you hit resistance, try screwing them in from the other side first to clear any obstruction. Screw them most of the way in, but leave some room for adjustment.


.. image:: ../../images/build_guide/v1.6/flat/flat_build_guide_07.jpeg
   :target: _images/flat_build_guide_07.jpeg
   :alt: Assembly Steps


Next, position the camera module and secure it with the longer M2.5 screw. Insert the screw through the center hole in the back of the flat adapter and thread it into the center hole in the camera cell. It should screw in 3-4mm and pull the camera cell against the ends of the three thumbscrews. If the cell isn't secure, extend the thumbscrews until they support it. No need to tighten anything too much here. You adjust it again later to align the PiFinder with the optical axis of your telescope.


.. image:: ../../images/build_guide/v1.6/flat/flat_build_guide_09.jpeg
   :target: _images/flat_build_guide_09.jpeg
   :alt: Assembly Steps


Gently plug in the UI Hat and tuck the cable underneath it. Take your time and make sure the camera cable isn't pinched between the stand-offs and the UI Hat.


.. image:: ../../images/build_guide/v1.6/flat/flat_build_guide_10.jpeg
   :target: _images/flat_build_guide_10.jpeg
   :alt: Assembly Steps


.. image:: ../../images/build_guide/v1.6/flat/flat_build_guide_11.jpeg
   :target: _images/flat_build_guide_11.jpeg
   :alt: Assembly Steps


.. image:: ../../images/build_guide/v1.6/flat/flat_build_guide_12.jpeg
   :target: _images/flat_build_guide_12.jpeg
   :alt: Assembly Steps


Once the UI Hat is plugged in all the way and the cable is tidy, gather the remaining parts to finish the build. The shroud slips over the UI Hat first, then the bezel slots on top, and finally the top PCB. Secure everything together with three of the long screws, as shown in the photos below.

.. note::
   If you haven't already flashed the SD card and inserted it into the Raspberry Pi, do it
   now. The card is harder to reach once the shroud is installed. If you use a PiSugar,
   also check that you have cut and punched the power switch opening out of the shroud.


.. image:: ../../images/build_guide/v1.6/flat/flat_build_guide_13.jpeg
   :target: _images/flat_build_guide_13.jpeg
   :alt: Assembly Steps



.. image:: ../../images/build_guide/v1.6/flat/flat_build_guide_14.jpeg
   :target: _images/flat_build_guide_14.jpeg
   :alt: Assembly Steps


.. image:: ../../images/build_guide/v1.6/flat/flat_build_guide_15.jpeg
   :target: _images/flat_build_guide_15.jpeg
   :alt: Assembly Steps


.. image:: ../../images/build_guide/v1.6/flat/flat_build_guide_16.jpeg
   :target: _images/flat_build_guide_16.jpeg
   :alt: Assembly Steps


.. image:: ../../images/build_guide/v1.6/flat/flat_build_guide_17.jpeg
   :target: _images/flat_build_guide_17.jpeg
   :alt: Assembly Steps


One task remains: fit the camera lens. Unscrew the cap from the camera module, but leave the knurled adapter in place. The adapter sets the correct focus distance. Remove the cap from the silver end of the lens and gently screw the two together.


.. image:: ../../images/build_guide/v1.6/flat/flat_build_guide_19.jpeg
   :target: _images/flat_build_guide_19.jpeg
   :alt: Assembly Steps


Congratulations, you have a PiFinder! See the :doc:`Software Setup <software>` guide for next steps.
