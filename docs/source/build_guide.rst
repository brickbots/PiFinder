
===========
Build Guide
===========

Introduction and Overview
=================================

.. note::
   This guide covers the self-built (DIY) PiFinder, which uses the v2.5 hardware
   and comes together in one of three configurations: Left, Right, or Flat.
   v3 PiFinders are sold assembled and aren't built from these instructions.

Welcome to the PiFinder build guide. It's split into three main parts: building the :ref:`UI Board<build_guide:pifinder ui hat>` with its screen and buttons, :ref:`3d printing<build_guide:printed parts>` and preparing the case parts, and :ref:`final assembly<build_guide:assembly>`. Alongside these, consult the :doc:`Bill of Materials<BOM>` for the full parts list, and reach out with any questions via `email <mailto:info@pifinder.io>`_ or `discord <https://discord.gg/Nk5fHcAtWD>`_


PiFinder UI Hat
========================

A key part of the PiFinder is a custom 'Hat' that matches the general form factor of the Raspberry Pi and connects to its GPIO header. It carries the switches, screen, Inertial Measurement Unit, and the keypad backlight components.

Everything is through-hole, so this is approachable even for beginners. The build order matters, though, as some components block access to others.

Some photos here still show the v1 non-backlit board, but the assembly is the same once the backlight components are in place.

You'll need the TWO PCBs to start. One holds the electronic components; the other carries the shine-through legends and goes on top of the assembled board at the end. Gerber files for both are in the main `PiFinder git repo <https://github.com/brickbots/PiFinder/tree/release/gerbers>`_

Backlight Components
------------------------

Start with the LEDs. They sit close to the board, and doing them first makes it easier to keep them aligned.

.. image:: images/build_guide/ui_module_1.jpeg


Polarity matters, so mind the direction. The longer lead of the LED goes through the round hole in the footprint. The photo below shows the orientation.

.. image:: ../../images/build_guide/led_build_03.jpeg

Position each one carefully. They should be fairly uniform, though small inconsistencies don't matter much. Place them all in the board, then tape them in place.

.. image:: images/build_guide/ui_module_2.jpeg

.. image:: images/build_guide/ui_module_3.jpeg

Pull the legs straight and solder one leg of each LED. Remove the tape and check again. If any are wildly out of place, reheat that one joint and adjust.

.. image:: images/build_guide/ui_module_4.jpeg

When satisfied, solder the remaining legs and clip the leads down to a single pair. We'll check the LEDs in the next section before moving on, so leave one pair of legs long to power the backlight for testing.

.. image:: images/build_guide/ui_module_5.jpeg

The two resistors and the transistor are next. R2 is the vertical 330 ohm part; R1 is the 22 ohm part oriented horizontally. Direction doesn't matter for the resistors, but it does for the transistor. Check the photo below for orientation, and make sure the transistor sits flat against the PCB and the resistors are low. Solder from the back and clip the leads once they look good.

.. image:: images/build_guide/ui_module_6a.jpeg

Testing the Backlight
^^^^^^^^^^^^^^^^^^^^^^

Test the backlight (and LEDs) now using any 3V coin cell, such as a CR2032. Connect the positive side of the battery to the longer pin of an LED and the negative side to the shorter pin, as shown below with a single LED. This works for all the LEDs at once since they're wired in parallel on the board. Once connected, every LED should light up:

.. image:: images/build_guide/test_leds_1.jpeg

Replace any LEDs that aren't working properly before proceeding.

Switches
------------------------

Switches go next. Place each one on its footprint and press it down fully. Before soldering, visually inspect them for any that are tilted.


.. image:: images/build_guide/ui_module_6b.jpeg


It's also worth placing the top legend plate over them to confirm they all clear the holes properly. Then solder them up. You don't need to clip the leads on the switches; they have plenty of room.

.. image:: images/build_guide/ui_module_6c.jpeg


Headers
---------

Do the headers next. These will receive the IMU, GPS, and Screen. The procedure is the same for all three: insert the header, solder one pin, check that it's flat and straight, then solder the rest. Clip the pins flush and apply some insulating tape.

Start with the IMU header. It goes on the underside of the board and is soldered from the top.

.. image:: images/build_guide/ui_module_7.jpeg

.. image:: images/build_guide/ui_module_8.jpeg

Apply the insulating tape and move on to the screen header, which goes in from the top side:

.. image:: images/build_guide/ui_module_9.jpeg

Trim the pins and tape it up.

.. image:: images/build_guide/ui_module_10.jpeg

The GPS header is next. The modules ship with a yellow header, but any will do. It inserts from the bottom, then gets soldered and taped like the rest.

.. image:: images/build_guide/ui_module_11.jpeg

.. image:: images/build_guide/ui_module_12.jpeg


IMU
------------------------

The Inertial Measurement Unit is next. It has an annoyingly bright green LED that you'll want to either paint over with a few layers of black nail polish or destroy with your soldering iron. You can deal with it after soldering if you forget, but it's much easier beforehand. See the image below to identify the offending component.

.. image:: ../../images/build_guide/adafruit_IMU.png
   :target: ../../images/build_guide/adafruit_IMU.png
   :alt: Green led on IMU


The photo below shows the orientation on the back of the PCB. Make sure it sits flat and square with the board. It doesn't need to be perfect, but should be secure and low-profile. Solder it into position and you're good to go.

.. image:: images/build_guide/ui_module_13.jpeg


Display
------------------

The display comes next and will cover the IMU header's solder points, so double-check those joints before proceeding.

Remove the stand-offs by unscrewing them from the front.


.. image:: ../../images/build_guide/IMG_4648.jpeg
   :target: ../../images/build_guide/IMG_4648.jpeg
   :alt: Display as shipped



.. image:: ../../images/build_guide/IMG_4649.jpeg
   :target: ../../images/build_guide/IMG_4649.jpeg
   :alt: Display with standoffs removed


Next, remove the plug from the underside of the board. This isn't strictly necessary, but it helps the display sit lower and flatter. Use sharp cutters to cut each lead to the connector first, cutting low though the exact spot isn't critical. Then use clippers to cut away the plastic at the attachment points on both short sides.


.. image:: ../../images/build_guide/IMG_4650.jpeg
   :target: ../../images/build_guide/IMG_4650.jpeg
   :alt: Connector cut free


To make the top plate fit better and look tidier, sand back or cut the bottom tabs on the display PCB. There's no circuitry there; they just provide unneeded screw points.


.. image:: ../../images/build_guide/IMG_4652.jpeg
   :target: ../../images/build_guide/IMG_4652.jpeg
   :alt: Cut/Sand tabs on display


Test-fit the screen with the header installed and the top plate in place. Everything should fit nicely and sit square.


.. image:: ../../images/build_guide/IMG_4653.jpeg
   :target: ../../images/build_guide/IMG_4653.jpeg
   :alt: Screen test fit


When you're ready, solder the screen in place. Do one pin first and check all around to make sure it's sitting flat. If not, heat that one joint and adjust.

.. image:: images/build_guide/ui_module_14.jpeg

GPS
------------------

.. danger::
   Complete the :ref:`Testing the Backlight<build_guide:testing the backlight>` step before soldering on the GPS unit. The GPS unit blocks access to some LED pins and would need to be removed to replace any blocked LEDs. Removing it is difficult and can destroy the PCB. It has happened to us. Make sure the LEDs work before proceeding.

   If you do need to desolder the GPS unit later, be very careful and patient, and use a desoldering pump.


.. caution::
   If you want to test the switches, you can leave the GPS unit out entirely until the end, since it also blocks access to some switch pins. The GPIO connector for attaching the hat to the Raspberry Pi will then make this awkward.

   This isn't recommended: the LEDs have given us trouble in the past, but the switches have usually been rock solid.


The last active component is the GPS module. It goes component side up so you can access the antenna plug. Check the photo below and solder it securely.

.. image:: images/build_guide/ui_module_15.jpeg

Connect the antenna to the GPS module. It's fiddly, so check the alignment carefully before applying too much force. It will snap in and then rotate easily.

.. list-table::

   * - .. image:: images/build_guide/common_3.jpeg

     - .. image:: images/build_guide/common_4.jpeg


Routing the antenna cable well matters for reception. Following the photo below, tape it to the back of the board to keep it secure and out of the way during the build.


.. image:: images/build_guide/ui_module_15b.jpeg

Connector
------------------

The GPIO connector is the last soldered part of the Hat. To space it correctly, mount the PCB to your Pi using the stand-offs you'll use for final assembly.

The connector's pins are long to accommodate various spacings. Plug the connector firmly into your Pi, mount the PiFinder hat with stand-offs and screws, and then solder the connector at the correct spacing.

Add any heatsinks you plan to use first. Take your time and make sure the hat is secured properly to the Pi, that there's no mechanical interference, and that you're happy with the spacing before soldering.

Check the photos below for the procedure; it's easier than it sounds. There are a lot of pins, so make sure each is secure, as this part takes force every time the hat is installed and removed.

.. image:: images/build_guide/ui_module_16.jpeg

.. image:: images/build_guide/ui_module_17.jpeg

With all the pins soldered, insert the SD card and power it up to double-check everything works.

.. image:: images/build_guide/ui_module_18.jpeg

Once it has started completely, you'll be greeted with :ref:`"the menu"<user_guide:the menu system>`. Use the buttons below the screen to navigate; see the faceplate for button functions.

Navigate to the ``Tools > Status`` :ref:`screen<user_guide:status screen>` and verify the IMU is detected: the "IMU" lines should show some numbers. Then go to ``Objects > Name Search`` and enter a few letters of an object name to test the keypad. The keypad is now working properly.

There you go. The PiFinder hat is fully assembled, and you can move on to printing your parts or :ref:`final assembly<build_guide:assembly>`

Configurations Overview
========================

There are three ways to build a PiFinder so it works conveniently on a variety of telescopes.


.. list-table::

   * - .. figure:: images/build_guide/config_example_left.jpeg

          Left Handed

     - .. figure:: images/build_guide/config_example_right.jpeg

          Right Handed

     - .. figure:: images/build_guide/config_example_flat.jpeg

          Flat

Any configuration can work with any scope, but since the camera always needs to face the sky, the different configurations let you place the screen and keyboard for easy access. The Left and Right configurations are mainly for newtonian-style scopes, like dobsonians, whose focuser sits perpendicular to the light path.

The Flat configuration puts the keypad and screen in easy reach for refractors, SCTs, and other rear-focuser scopes. When the scope points upward, the screen tilts towards you for quick access.

All the STL files for the PiFinder case parts are in the main `PiFinder git repo case folder <https://github.com/brickbots/PiFinder/tree/release/case>`_


Printed Parts
===========================


The PiFinder can be built in a left, right, or flat configuration to suit many telescopes. See the :ref:`configurations overview<build_guide:configurations overview>` for more, including example photos. Each configuration needs only a subset of the available parts.


Common Parts
-----------------------

Some parts are common to all three configurations. The Bezel, Camera Cover, and RPI Mount are used in every build.

Right and Left configurations
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Below are all the parts needed to build a left- or right-hand PiFinder. Thanks to the edge inserts, these pieces assemble into either configuration, so you need just one set of parts regardless of which side your focuser faces. The assembly guide covers how to orient the pieces as you put them together.

.. image:: images/build_guide/parts_1.jpeg
   :target: images/build_guide/parts_1.jpeg



Flat Configuration
^^^^^^^^^^^^^^^^^^

The pieces for the flat version are pictured below. The same parts are used with or without a PiSugar battery.

.. image:: images/build_guide/parts_2.jpeg
   :target: images/build_guide/parts_2.jpeg


Printing
--------

These pieces print without supports in the orientation shown. I use 3 perimeter layers and 15% infill, but the parts are small and don't take heavy forces, so almost any print settings will work.

Use a material other than PLA, since your PiFinder will likely see some sunlight and PLA degrades under moderate heat and UV. PETG or a co-polymer like NGen is a good choice. Prusament Galaxy PETG is the official PiFinder filament and appears in most of the build guide, except where grey provided needed contrast.

Inserts
-------

Only some holes receive inserts; the rest take M2.5 screws that pass through into inserts in other pieces. The brass inserts used here are M2.5 x 4mm long. Some go into holes through the full thickness of the piece, and some go into blind holes in the edges. Each part with inserts is pictured below for reference:

Pi Mount
^^^^^^^^^

The Pi Mount takes eight inserts total: four in the printed stand-offs and four in the edges.

.. image:: images/build_guide/parts_3.jpeg
   :target: images/build_guide/parts_3.jpeg

.. image:: images/build_guide/parts_4.jpeg
   :target: images/build_guide/parts_4.jpeg

Bottom
^^^^^^^

For left/right builds this is the bottom piece. It needs four inserts to attach the dovetail mount.

.. image:: images/build_guide/parts_5.jpeg
   :target: images/build_guide/parts_5.jpeg


Flat Adaptor
^^^^^^^^^^^^^
.. note::
   The photos for the Flat Adaptor and the Back shown here are for the v2 build. The v2.5 parts
   are almost identical, but have 2 camera mount holes rather than 4.

This piece replaces the bottom and back pieces from the left/right build. It needs eight inserts: four to attach the dovetail mount and four to attach the camera.

.. image:: images/build_guide/parts_6.jpeg
   :target: images/build_guide/parts_6.jpeg


Back
^^^^^^^^^

The back piece holds the camera for left/right builds and reinforces the PiMount and Bottom piece to keep everything square and sturdy. It needs six inserts: four to mount the camera and two in the bottom edge to connect with the bottom piece.

.. image:: images/build_guide/parts_7.jpeg
   :target: images/build_guide/parts_7.jpeg

Dovetail Bottom
^^^^^^^^^^^^^^^^

The dovetail bottom has two inserts for the longer 12mm screws that allow angle adjustment. These inserts go in the side opposite where the top piece connects. The screws pass through the top piece and part of the bottom before engaging the inserts. This makes the assembly strong enough to hold the set angle once the screws are sufficiently tight.

.. image:: images/build_guide/parts_8.jpeg
   :target: images/build_guide/parts_8.jpeg


Installation
^^^^^^^^^^^^^

Because I use a lot of these inserts, I use a tool to seat them plumb into the parts, but I've done plenty freehand and it's not difficult. Use a temperature a bit below your normal printing temperature (I print PETG at 230c and use 170-200c for inserts) and give the plastic time to melt around them.


.. image:: ../../images/build_guide/v1.4/build_guide_02.jpg
   :target: ../../images/build_guide/v1.4/build_guide_02.jpg
   :alt: Insert Inserting



Mounting
--------

Most people will print the dovetail mount, which fits the finder shoe included on most telescopes. The dovetail mount is angle adjustable, letting you orient the screen surface roughly vertical and perpendicular to the ground. This puts the inertial motion sensor into its expected position. See the image below for a clearer explanation:


.. image:: ../../images/finder_shoe_angle.png
   :target: ../../images/finder_shoe_angle.png
   :alt: Finder shoe angle


Adjustable Dovetail Assembly
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

If you print your own parts, add heat-set inserts as pictured in the photo above. The inserts must go in from the outside of the bottom piece, as pictured. The holes on the inside aren't large enough for inserts; they just let the screws pass through into the inserts.

See the photos below for how the pieces fit together. Once assembled, loosen both screws to adjust the angle up to 40 degrees from horizontal, then secure them again. No need to go too tight, but a bit of friction is required to hold the angle.


.. image:: images/build_guide/dovetail_1.jpeg

.. image:: images/build_guide/dovetail_2.jpeg

.. image:: images/build_guide/dovetail_3.jpeg

.. image:: images/build_guide/dovetail_4.jpeg


If you need more flexibility, there's also a go-pro compatible plate that bolts into the bottom plate. You'll need to add inserts into the bottom plate mounting footprint to use this option.

Once all the parts are printed and the inserts are seated, you're ready to :ref:`assemble<build_guide:assembly>`!

Rigel Quickfinder Assembly
^^^^^^^^^^^^^^^^^^^^^^^^^^

You'll need the following for a Rigel Quickfinder adapter:

.. list-table::
   :header-rows: 1

   * - Qty
     - Item
     - URL
     - Notes
   * - 1
     - PiToQuickfinder v2 - Part 1.stl
     - `git repo quikfinder <https://github.com/brickbots/PiFinder/tree/release/case/adapter/quikfinder>`_
     - You'll need both this and the next item
   * - 1
     - PiToQuickfinder v2 - Part 2.stl
     - `git repo quikfinder <https://github.com/brickbots/PiFinder/tree/release/case/adapter/quikfinder>`_
     - You'll need both this and the previous item
   * - 2
     - heat-set insert M2.5 x 4 mm
     -
     - Same as for the case

Print "Part 2" to maximize the strength of the "hook". Print it with supports, like this:

.. image:: images/build_guide/quickfinder_base_4.jpeg

If you print your own parts, add heat-set inserts as pictured below. Space is limited, so fix it to the PiFinder first and then insert the second part. Tighten the screws just a little to hold the second part so it can't fall off.

After putting it on a Rigel Quickfinder base, tighten the screws fully. Note that the double-sided foam adhesive supplied with the Rigel Quikfinder may compress under the weight of the PiFinder (about 6 times the weight of a Quikfinder), so you may need to reconsider how the base plate is fixed to your scope.


.. image:: images/build_guide/quickfinder_base_1.jpeg

.. image:: images/build_guide/quickfinder_base_2.jpeg

.. image:: images/build_guide/quickfinder_base_3.jpeg


Optionally, if you need to adjust your PiFinder's orientation to make it vertical on your scope, you'll also need these:

.. list-table::
   :header-rows: 1

   * - Qty
     - Item
     - URL
     - Notes
   * - 1
     - Pi2Q2Dovetail.stl
     - `git repo quikfinder <https://github.com/brickbots/PiFinder/tree/release/case/adapter/quikfinder>`_
     - You'll at least need this and the next item
   * - 1
     - dovetail_top.stl
     - `git repo dovetail <https://github.com/brickbots/PiFinder/tree/release/case/v2>`_
     - You'll at least need this and the previous item
   * - 6
     - heat-set insert M2.5 x 4 mm
     -
     - Same as for the case

Add 4 heat-set inserts as indicated in the following pictures:

.. image:: images/build_guide/quickfinder_base_5.jpeg

.. image:: images/build_guide/quickfinder_base_6.jpeg

Assembly then follows the dovetail assembly in the previous section. Depending on your needs, you can fix the optional adapter in two orientations. Make sure the "long lip" points the same direction as the PiFinder. The fully assembled adapter looks like this:

.. image:: images/build_guide/quickfinder_base_7.jpeg

.. image:: images/build_guide/quickfinder_base_8.jpeg

Once all the parts are printed and the inserts are seated, you're ready to :ref:`assemble<build_guide:assembly>`!


Assembly
======================


Assembly Overview
-----------------

From here you'll need the M2.5 screws, stand-offs, and thumbscrews along with the 3d printed parts, UI hat, and the camera, lens, and GPS unit. Most photos in this part show a build with the PiSugar, but if you're powering the PiFinder another way the assembly is almost identical.

*In all cases, don't over tighten the hardware.* There's no need, and you could damage the 3d printed pieces, inserts, or screws. Once they feel snug, that's enough. The case forms a rigid assembly once everything is in place and will easily support the camera and other bits.

Pi Mounting
---------------------------

First, mount the Pi and PiSugar battery to the Pi Mount piece. The pieces you'll need are shown below.


.. image:: images/build_guide/common_1.jpeg
   :target: images/build_guide/common_1.jpeg
   :alt: Build Guide Step


Whatever your build's orientation, the Raspberry Pi and battery always mount this same way, on top of the posts in the RPI Holder.

If you're using a PiSugar, mount the battery pack now; otherwise skip this step. Flip the PiMount piece over and use the zip ties to secure the battery as shown. Don't tighten these much, as that may damage the battery, just enough to keep it from moving too much.

Mind the orientation of the battery pack so the connector sits in the notch as shown below.


.. image:: images/build_guide/common_1b.jpeg
   :target: _images/common_1b.jpeg


Snip the zip-ties off and you're ready to move on.


.. image:: images/build_guide/common_1c.jpeg
   :target: images/build_guide/common_1c.jpeg



Camera Prep
---------------------------

The new v3 camera may come with one of two lens holders already installed. Either way, you'll remove and replace it.

.. include:: includes/camera_prep.rst


Cable Routing
---------------------------

For a flat unit, set the camera cable aside, as it's routed differently. For left/right builds, it's easier to position the cable roughly now.

Return to the Raspberry Pi assembly and thread the camera cable through as shown. Note the orientation of the silver contacts at each end of the cable. The photos below show the cable routing for left- and right-hand builds.

.. list-table::

   * - .. image:: images/build_guide/left_1.jpeg
          :target: images/build_guide/left_1.jpeg

       Left hand cable routing

     - .. image:: images/build_guide/right_1.jpeg
          :target: images/build_guide/right_1.jpeg

       Right hand cable routing

.. important::
    If you're using the recommended S Plus unit, prepare it now.

    * Turn the 'Auto Startup' switch on the bottom of the unit to OFF. Leaving it ON prevents i2c from working and the IMU won't be used. The switch is outlined in orange in the image below, shown in the correct OFF position.

    * The blue power light on the PiSugar board is very bright. Cover it with black nail polish or destroy it with a soldering iron. Plug it into the battery and turn it on to confirm it's subdued. The orange arrow in the image below indicates which LED to cover; it's already blacked out with nail polish in the photo.


.. image:: ../../images/build_guide/pisugar_setup.jpg
   :target: ../../images/build_guide/pisugar_setup.jpg
   :alt: Build Guide Step


The PiSugar ships with a protective film on the screw posts, as seen below. Remove it, or you'll have a frustrating time getting everything screwed together.


.. image:: ../../images/build_guide/v1.6/build_guide_01.jpeg
   :target: ../../images/build_guide/v1.6/build_guide_01.jpeg
   :alt: Build Guide Step


The PiSugar sits under the Raspberry Pi with the gold pogo pins pressed against the bottom of the Pi. The side facing up in the image above is the side that should press against the bottom of the Raspberry Pi. The PiSugar documentation has more info if needed.

The combined PiSugar/RPI stack then gets secured to the PI Mount using the 20mm stand-offs. The photos below show the right/left-hand stack with their respective cable routing. Flat configurations build the same way, without any camera cable.

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

Continue here to build a Right/Left-hand unit. The build is the same for both versions, with some differences in part orientation. Each step shows photos with the left-hand version on the left and the right on the right.

Now that the RPI is mounted, secure the mount plate to the bottom plate. The bottom plate can be flipped so the screen faces the right or left side, as the two photos below show.

In both cases, the RPI/Screen always faces the same direction as the long, flat side of the bottom piece. The angled cutout is always on the camera side, and the lens faces the angled portion.

.. list-table::

   * - .. image:: images/build_guide/left_4.jpeg

     - .. image:: images/build_guide/right_4.jpeg


First, screw the Pi Mount assembly to the bottom plate. Use two screws from underneath, running through the bottom plate into the threaded inserts in the side of the Pi Mount piece.


.. list-table::

   * - .. image:: images/build_guide/left_5.jpeg

     - .. image:: images/build_guide/right_5.jpeg



The back piece is next, but first screw in the four short stand-offs that support the camera module. These can go on either side for left- or right-hand configurations. Check the photos below to match how the back piece fits each configuration and decide which side to put the stand-offs in.

.. list-table::

   * - .. image:: images/build_guide/left_6.jpeg

     - .. image:: images/build_guide/right_6.jpeg

   * - .. image:: images/build_guide/left_7.jpeg

     - .. image:: images/build_guide/right_7.jpeg

The back piece then secures to the assembly with three M2.5 8mm screws. One goes through the back plate into the side-insert in the RPI Mount; there's one of these inserts on either side of the RPI Mount for left/right-hand builds. The other two go through the bottom plate into the side-inserts on the back plate.


.. list-table::

   * - .. image:: images/build_guide/left_8.jpeg

     - .. image:: images/build_guide/right_8.jpeg

   * - .. image:: images/build_guide/left_9.jpeg

     - .. image:: images/build_guide/right_9.jpeg

Now mount the camera module. You'll need the module, camera tray, and 2x 12mm M2.5 screws.

.. note::
   The images here show an older back piece and camera tray. New kits have a back piece
   with two holes which match the camera holder. In this simpler arrangement the camera
   tray is not directly secured to the back piece, but rather has two holes through it.
   The camera holder is secured with longer screws through the tray into the two holes
   in the back piece

Start by connecting the cable to the new camera module.

.. include:: includes/camera_cable_connect.rst

.. note::
   The remainder of the build guide is yet to be updated with new photos
   including the v2.5 camera. The build proceeds just the same and we
   will be updating the photos soon.


Flip the unit over and connect the RPI end of the camera cable. The photo below shows the proper cable orientation into the connector, with the silver contacts facing the white portion of the connector.

.. image:: images/build_guide/assembly_insert_cable.jpeg

For the left-hand version you'll need a twist in the cable before it enters the connector on the RPI. Be gentle, and you'll be able to adjust it as you put on the UI Module later.

.. list-table::

   * - .. image:: images/build_guide/left_14.jpeg

     - .. image:: images/build_guide/right_14.jpeg

.. note::
   The remainder of the build is almost the same for left- or right-hand units. The photos below are a mix of left and
   right handed builds, but where there are important differences, you'll see both indicated for clarity.


Next, connect the UI Board and affix the shroud. Lay out the board as it will be connected and slide the antenna into the holder on the Pi Mount piece. The ceramic top with the silver dimple needs to face upwards. Consult the photos below.

.. image:: images/build_guide/right_16.jpeg

.. image:: images/build_guide/right_17.jpeg

.. image:: images/build_guide/right_18.jpeg

.. note::
   The images above have the GPS cable loose and not routed properly. Please use the
   routing shown in the :ref:`GPS<build_guide:gps>` section

Now carefully plug the UI Module into the Raspberry Pi. Make sure both rows of pins are aligned and take your time to manage the camera and GPS cables. The photos below show the left and right configurations for the cable routing.

.. list-table::

   * - .. image:: images/build_guide/left_20.jpeg

     - .. image:: images/build_guide/right_20.jpeg


The screw holes on the UI Board should line up with three of the four stand-offs. The fourth provides support but isn't used to secure the outer case. Collect the Shroud, Bezel, and cover plate along with three of the 12mm screws for the next steps.

.. image:: images/build_guide/common_5.jpeg
   :target: images/build_guide/common_5.jpeg


The shroud has three optional openings: one for the PiSugar power switch on top, one for the USB ports, and one for the SD Card on the side for easier access. Remove these with a little force or a sharp knife. If you're using a PiSugar battery, you'll definitely need to remove that tab. See the photo below:

.. image:: images/build_guide/common_6.jpeg

Slide the shroud over the unit, then stack the bezel and the front PCB plate on top and secure them all with the three screws.

.. image:: images/build_guide/common_7.jpeg

.. image:: images/build_guide/common_8.jpeg

.. image:: images/build_guide/common_9.jpeg

.. image:: images/build_guide/common_10.jpeg

That's looking great. Now you just need a way to mount it to the scope. The top portion of the adjustable dovetail screws directly to the bottom of the PiFinder, then the bottom portion secures to the top. The orientation of the top part matters so the dovetail adjusts the proper way. See the left/right-hand photos below:


.. image:: images/build_guide/right_21.jpeg

.. image:: images/build_guide/right_22.jpeg


The final dovetail assembly is tricky to photograph on the PiFinder, so check these photos below and secure the bottom dovetail portion to the top:

.. image:: images/build_guide/dovetail_1.jpeg

.. image:: images/build_guide/dovetail_2.jpeg

.. image:: images/build_guide/dovetail_3.jpeg

.. image:: images/build_guide/dovetail_4.jpeg



That's it! You now have a fully assembled PiFinder.

Continue to the :doc:`software setup<software>` if you haven't already prepared an SD card.


.. image:: images/build_guide/common_11.jpeg
   :target: images/build_guide/common_11.jpeg


Flat Assembly
----------------

This section covers a Flat build. This configuration is great for refractors, SCTs, and other rear-focuser scopes, as the screen is 'flat' when mounted and the camera faces forward:


.. image:: ../../images/flat_mount.png
   :target: ../../images/flat_mount.png
   :alt: Flat example


If you haven't already followed the :ref:`general assembly guide<build_guide:assembly>` through to the point pictured below, do so and then return here.


.. image:: ../../images/build_guide/v1.6/build_guide_11.jpeg
   :target: ../../images/build_guide/v1.6/build_guide_11.jpeg
   :alt: Pi Module Assembled


If you routed the cable as above, pull the camera cable out to remove it from the RPI assembly, as the routing differs for a flat build.

Collect the flat adapter and dovetail. The dovetail secures to the underside of the flat adapter via screws through the adapter, and the RPI mount assembly slots into the flat adapter and is secured via screws into the edge inserts. See the photos below for details.

.. image:: ../../images/build_guide/v1.6/flat/flat_build_guide_01.jpeg
   :target: ../../images/build_guide/v1.6/flat/flat_build_guide_01.jpeg
   :alt: Assembly Steps


.. image:: ../../images/build_guide/v1.6/flat/flat_build_guide_02.jpeg
   :target: ../../images/build_guide/v1.6/flat/flat_build_guide_02.jpeg
   :alt: Assembly Steps


.. image:: ../../images/build_guide/v1.6/flat/flat_build_guide_03.jpeg
   :target: ../../images/build_guide/v1.6/flat/flat_build_guide_03.jpeg
   :alt: Assembly Steps


.. image:: ../../images/build_guide/v1.6/flat/flat_build_guide_04.jpeg
   :target: ../../images/build_guide/v1.6/flat/flat_build_guide_04.jpeg
   :alt: Assembly Steps


.. image:: ../../images/build_guide/v1.6/flat/flat_build_guide_05.jpeg
   :target: ../../images/build_guide/v1.6/flat/flat_build_guide_05.jpeg
   :alt: Assembly Steps


Note the one additional screw on the other side, visible in the next photo. Once the RPI Mount is secured to the flat adapter, connect the camera cable to the RPi and the camera as shown below.


.. image:: ../../images/build_guide/v1.6/flat/flat_build_guide_06.jpeg
   :target: ../../images/build_guide/v1.6/flat/flat_build_guide_06.jpeg
   :alt: Assembly Steps


Turn the PiFinder around and screw in the three thumbscrews as shown. Check for excess plastic in the threads; if you hit resistance, try screwing them from the other side first to clear any obstruction. Screw them most of the way in, but leave some room for adjustment.


.. image:: ../../images/build_guide/v1.6/flat/flat_build_guide_07.jpeg
   :target: ../../images/build_guide/v1.6/flat/flat_build_guide_07.jpeg
   :alt: Assembly Steps


Next, position the camera module and use the longer M2.5 screw to secure it. Insert the screw through the center hole in the flat adapter back and thread it into the center hole in the camera cell. It should screw in 3-4mm and pull the camera cell against the ends of the three thumbscrews. If it's not secure, extend the thumbscrews until it's supported. No need to tighten anything too much here; you'll adjust again to align the PiFinder with your telescope's optical axis.


.. image:: ../../images/build_guide/v1.6/flat/flat_build_guide_09.jpeg
   :target: ../../images/build_guide/v1.6/flat/flat_build_guide_09.jpeg
   :alt: Assembly Steps


Gently plug in the UI Module, tucking the cable underneath it. Take your time and make sure the camera cable isn't pinched between the stand-offs and the UI Module.


.. image:: ../../images/build_guide/v1.6/flat/flat_build_guide_10.jpeg
   :target: ../../images/build_guide/v1.6/flat/flat_build_guide_10.jpeg
   :alt: Assembly Steps


.. image:: ../../images/build_guide/v1.6/flat/flat_build_guide_11.jpeg
   :target: ../../images/build_guide/v1.6/flat/flat_build_guide_11.jpeg
   :alt: Assembly Steps


.. image:: ../../images/build_guide/v1.6/flat/flat_build_guide_12.jpeg
   :target: ../../images/build_guide/v1.6/flat/flat_build_guide_12.jpeg
   :alt: Assembly Steps


Once the UI Module is plugged in all the way and the cable is tidy, gather the remaining parts to wrap up the build. The shroud slips over the UI Module first, then the bezel slots on top, and finally the top PCB. Use three of the long screws to secure everything together, per the photos below.

NOTE: If you haven't already flashed and inserted the SD card into the Raspberry Pi, now's a good time, as it's harder to reach after the shroud is installed. Also check that the PiSugar power switch access is cut and punched out of the shroud if you're using a PiSugar.


.. image:: ../../images/build_guide/v1.6/flat/flat_build_guide_13.jpeg
   :target: ../../images/build_guide/v1.6/flat/flat_build_guide_13.jpeg
   :alt: Assembly Steps



.. image:: ../../images/build_guide/v1.6/flat/flat_build_guide_14.jpeg
   :target: ../../images/build_guide/v1.6/flat/flat_build_guide_14.jpeg
   :alt: Assembly Steps


.. image:: ../../images/build_guide/v1.6/flat/flat_build_guide_15.jpeg
   :target: ../../images/build_guide/v1.6/flat/flat_build_guide_15.jpeg
   :alt: Assembly Steps


.. image:: ../../images/build_guide/v1.6/flat/flat_build_guide_16.jpeg
   :target: ../../images/build_guide/v1.6/flat/flat_build_guide_16.jpeg
   :alt: Assembly Steps


.. image:: ../../images/build_guide/v1.6/flat/flat_build_guide_17.jpeg
   :target: ../../images/build_guide/v1.6/flat/flat_build_guide_17.jpeg
   :alt: Assembly Steps


The only thing left is to affix the camera lens. Unscrew the cap from the camera module, but leave the knurled adapter in place, as it's required to get the focus distance correct. Remove the cap from the silver end of the lens and gently screw them together.


.. image:: ../../images/build_guide/v1.6/flat/flat_build_guide_19.jpeg
   :target: ../../images/build_guide/v1.6/flat/flat_build_guide_19.jpeg
   :alt: Assembly Steps


Congratulations, you have a PiFinder! See the :doc:`Software Setup<software>` guide for next steps.
