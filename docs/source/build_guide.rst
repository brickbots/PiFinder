
===========
Build Guide
===========

Introduction and Overview
=================================

Welcome to the PiFinder build guide!  This guide is split into three main parts, one for building the :ref:`UI Board<build_guide:pifinder ui hat>` with Screen and Buttons, a section related to :ref:`3d printing<build_guide:printed parts>` and preparing the case parts, and one for :ref:`final assembly<build_guide:assembly>`.   Along with these sections, please consult the :doc:`Bill of Materials<BOM>` for a full list of parts required and reach out with any questions via `email <mailto:info@pifinder.io>`_ or `discord <https://discord.gg/Nk5fHcAtWD>`_


PiFinder UI Hat
========================

A key part of the PiFinder is a custom 'Hat' which matches the general form factor of the Raspberry Pi and connects to it's GPIO header.  It contains the switches, screen and Inertial Measurement Unit along with keypad backlight components

It's all through-hole components, so should be approachable to even beginners... but the component build order is important as some items block access to others.

There are still some older photos here from the v1 non-backlit board, but the assembly is the same once the backlight components are in place.

You'll need the TWO pcb's to start with.  One contains the electronic components and the other has the shine-through legends and goes on top of the assembled board at the end.  You can find the gerber files for both in the main `PiFinder git repo <https://github.com/brickbots/PiFinder/tree/release/gerbers>`_

Backlight Components
------------------------

I like to start with the LEDs.  They sit close to the board and doing them first makes it 
easier to make sure they are all aligned.  

.. image:: images/build_guide/ui_module_1.jpeg


Polarity matters here, so mind the direction.  The longer lead of the LED should go through the round hole in the footprint.  The photo below shows the orientation

.. image:: ../../images/build_guide/led_build_03.jpeg

Take you time and make sure each is positioned well.  They should be pretty uniform, but little inconsistencies don't matter too much.  I like to place them all in the board, and then tape them in place.

.. image:: images/build_guide/ui_module_2.jpeg

.. image:: images/build_guide/ui_module_3.jpeg

Pull the legs straight and solder one of each LED.  Then remove the tape and check them again.  If any
are wildly out of place, you can heat up the solder on the one leg and adjust.  

.. image:: images/build_guide/ui_module_4.jpeg

When satisfied, solder the remaining legs and clip the leads up to a single pair. In the next section we are now going to check if the LEDs work before moving on. If you leave a pair of legs long, you can use them to power the backlight for testing.

.. image:: images/build_guide/ui_module_5.jpeg

The two resistors and transitor are next.  R2 is the vertical oriented 330ohm part and R1 is the 22ohm oriented horizontally.  Direction does not matter with these, but it's important for the transistor. Check the photo below for orientation and make sure this is bent flat against the PCB and the resistors are low.  Solder them from the back and clip the leads once you've verified they look good.

.. image:: images/build_guide/ui_module_6a.jpeg

Testing the Backlight
______________________________________

Using a CR2032 (any 3V coin cell will do) battery, you can test the backlight now (and LEDs).  Connect the positive part of the battery to the longer pin of LED and the negative part of the battery to the shorter pin, as demonstrated in the following picture with a single LED. This also works with all the LEDs as they are connected in parallel on the board. Once you connect the battery, all the LEDs should light up: 

.. image:: images/build_guide/test_leds_1.jpeg

Replace the LEDs, which are not working properly before proceeding.

Switches
------------------------

Switches are easy and can go next.  Place each one on a footprint and press it down fully.  Once they are all inserted, before you start soldering visually inspect them for any that are tilted.  


.. image:: images/build_guide/ui_module_6b.jpeg


It's also a good idea to place the top legend plate over them to make sure they all clear the holes properly.  Then solder them up!  You don't need to clip the leads on all the switches, they have plenty of room.

.. image:: images/build_guide/ui_module_6c.jpeg


Headers
---------

I like to do all the headers next.  These will eventually receive the IMU, GPS and Screen.  The procedure is roughly the same for 
all three: Insert them, solder one pin, check that they are flat and straight and then solder the rest of the pins.  Clip them flush and apply some insulating tape.  

Start with the IMU header.  It goes on the underside of the board and is soldered from the top

.. image:: images/build_guide/ui_module_7.jpeg

.. image:: images/build_guide/ui_module_8.jpeg

Apply the insulating tape and move on to the screen header.  It goes in from the top side:

.. image:: images/build_guide/ui_module_9.jpeg

Trim the pins and tape it up

.. image:: images/build_guide/ui_module_10.jpeg

The GPS header is next. The modules come with a yellow header, but any will do.  It gets inserted from the bottom, soldered and taped liked the rest.

.. image:: images/build_guide/ui_module_11.jpeg

.. image:: images/build_guide/ui_module_12.jpeg


IMU
------------------------

The Inertial Measurement unit is next.  The IMU has an annoyingly bright green LED on it, which you will either want to paint over with a few laywers of black nail polish, or you can use your soldering iron to destroy it.  It can be handled  after it's soldered if you forget, but it's much easier before hand.  See the image below to ID the offending component.

.. image:: ../../images/build_guide/adafruit_IMU.png
   :target: ../../images/build_guide/adafruit_IMU.png
   :alt: Green led on IMU


The photo below shows the orientation on the back of the PCB. Make sure it sits flat and square with the board.  It does not need to be perfect, but should be secure and low-profile. Solder it into position and you're good to go!

.. image:: images/build_guide/ui_module_13.jpeg


Display
------------------

The display comes next and will cover the solder points for the IMU header, so double check your solder joints there before proceeding!

You'll need to remove the stand-offs by unscrewing them from the front.  


.. image:: ../../images/build_guide/IMG_4648.jpeg
   :target: ../../images/build_guide/IMG_4648.jpeg
   :alt: Display as shipped



.. image:: ../../images/build_guide/IMG_4649.jpeg
   :target: ../../images/build_guide/IMG_4649.jpeg
   :alt: Display with standoffs removed


Next you'll need to remove the plug from the underside of the board.  This is not absolutely necessary, but will help the display sit lower and flatter.  Use a sharp pair of cutters to cut each of the leads to the connector first.  Cut down low, but the exact location is not critical.  Once this is done, you can use clippers to cut away the plastic at the attachment points on both of the short sides.


.. image:: ../../images/build_guide/IMG_4650.jpeg
   :target: ../../images/build_guide/IMG_4650.jpeg
   :alt: Connector cut free


To make the top plate fit a bit better and look tidier, I suggest sanding back or simply cutting the bottom tabs on the display PCB.  There is no circuitry there, they are just providing screw points which are not needed.


.. image:: ../../images/build_guide/IMG_4652.jpeg
   :target: ../../images/build_guide/IMG_4652.jpeg
   :alt: Cut/Sand tabs on displya


It's not a bad idea to test fit the screen with the header installed and the top-plate in place.  Everything should fit nicely and be square. 


.. image:: ../../images/build_guide/IMG_4653.jpeg
   :target: ../../images/build_guide/IMG_4653.jpeg
   :alt: Screen test fit


When you are ready, solder the screen in place.  Do one pin first and check it all around to make sure it's sitting flat.  If not, heat that one joint and adjust.

.. image:: images/build_guide/ui_module_14.jpeg

GPS
------------------

.. danger::
   The :ref:`Testing the Backlight<build_guide:testing the backlight>` step should be carried out before soldering on the GPS unit. The GPS unit will block access to some LED pins and will need to be removed before replacing the blocked LEDs. Removing the GPS unit is a difficult operation in which you might destroy the PCB. It has happened to us. Make sure the LEDs are working nicely before proceeding. 
   
   If you need to desolder the GPS unit later, be very careful and patient. We recommend using a desoldering pump, if you need to do it.


.. caution::
   Note that if you want to test the switches, you can leave out the GPS unit entirely until the end as well, since it also blocks access to some switch pins. The GPIO connector for connecting the hat to the Raspberry Pi will then make this awkward. 
   
   This is not recommended: While the LEDs have given us problems in the past, the switches have usually been rock solid.


The last active component is the GPS module.  It goes component side up so you can access the antenna plug.  Check the photo below and solder it securely.

.. image:: images/build_guide/ui_module_15.jpeg

Connect the antenna to the GPS module. It's a bit fiddly, so check the alignment carefully before
applying too much force.  It will snap in and then rotate pretty easily. 

.. list-table::

   * - .. image:: images/build_guide/common_3.jpeg

     - .. image:: images/build_guide/common_4.jpeg


The routing of the antenna cable is important for the best possible reception.  Reference the photo below and tape it to the back of
the board to keep it secure and out of the way during the build.


.. image:: images/build_guide/ui_module_15b.jpeg

Connector
------------------

Attaching the GPIO connector is the last soldered bit for the Hat.  To get this properly spaced, you'll need to mount the PCB to your Pi using the stand-off's you'll be using for final assembly.  

The pins on the connector are long to accommodate various spacings.  Plug the connector firmly into your Pi and once you have mounted the PiFinder hat to your Pi with stand-offs/screws you'll be able to solder the connector with the correct spacing.

Make sure you've added any heatsinks you plan to use. Take your time here and make sure the hat is secured properly to the Pi, that there is no mechanical interference, and that you're satisfied with the spacing before soldering the connector.  

Check the photos below for the procedure, it's easier than it sounds!  There are a lot of pins, make sure each is secure as this
part can have force applied as the hat is installed and removed.  

.. image:: images/build_guide/ui_module_16.jpeg

.. image:: images/build_guide/ui_module_17.jpeg

After you have all the pins soldrerd, it's a good time to insert the SD card and power it up to double check everything is working

.. image:: images/build_guide/ui_module_18.jpeg

Once it started completely, you will be greeted with :ref:`"the menu"<user_guide:the menu system>`. You can now use the buttons below the screen to navigate. See the faceplate for button functions.

Navigate to the ``Tools > Status`` :ref:`screen<user_guide:status screen>` and verify that the IMU is detected properly: The lines displaying "IMU" in the status screen should show some numbers. Then navigate to the ``Objects > Name Search`` entry and use it to test the keypad to enter a few letters of an object name.  Congratulations, the keypad is working properly.

There you go!  The PiFinder hat is fully assembled and you can move on to printing your parts or :ref:`final assembly<build_guide:assembly>`

Configurations Overview
========================

There are three different ways to build a PiFinder allowing it to be convieniently used on a variety of telescopes.  


.. list-table::

   * - .. figure:: images/build_guide/config_example_left.jpeg

          Left Handed

     - .. figure:: images/build_guide/config_example_right.jpeg

          Right Handed

     - .. figure:: images/build_guide/config_example_flat.jpeg

          Flat

Any configuration can technically work with any scope, but since the camera always needs to face the sky the different configurations allow the screen and keyboard to be placed for easy access.  The Left and Right configruations are primarily for newtonian style scopes, like dobsonians, which have the focuser perpendicular to the light path.

The Flat configuration places the keypad and screen in easy reach for refractors, SCT's and other rear-focuser scopes.  When the scope is pointed upward, the screen is tilted towards you for quick access.

All the STL files for the PiFinder case parts can be found in the main `PiFinder git repo case folder <https://github.com/brickbots/PiFinder/tree/release/case>`_


Printed Parts
===========================


The PiFinder can be built in a left, right or flat configuration to work well on many types of telescopes.  See the :ref:`configurations overview<build_guide:configurations overview>` for more information including example photos.  To build each configuration, only a subset of the available parts are required.


Common Parts
-----------------------

There are some parts which are common to all three configurations.  The Bezel, Camera Cover and RPI Mount are used in all configurations. 

Right and Left configurations
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Below is an image showing all the parts required to build a left or right hand PiFinder.  
Due to the use of edge inserts, these pieces can be assembled in either left, or right, handed 
configurations so you just need the one set of parts regardless of which side your focuser is 
facing.  In the assembly guide you'll find info about how to orient the pieces as you put them together. 

.. image:: images/build_guide/parts_1.jpeg
   :target: images/build_guide/parts_1.jpeg



Flat Configuration
^^^^^^^^^^^^^^^^^^

The pieces required for building the flat versions are pictured below.  The same parts are used with or without a PiSugar battery.

.. image:: images/build_guide/parts_2.jpeg
   :target: images/build_guide/parts_2.jpeg


Printing
--------

These pieces will print without supports in the orientation shown in the photos.  I use 3 perimeter layers and 15% infill, but the pieces are not large and don't need to handle heavy forces so almost any print settings should work.

You will want to consider using a material other than PLA, as your PiFinder is likely to experience some sunlight in it's lifetime and PLA degrades under moderate heat and UV.  PETG or some co-polymer like NGen would be a good choice.  Prusament Galaxy PETG is the official PiFinder filament and is pictured in most of the build guide, except where grey provided needed contrast.

Inserts
-------

Only some holes receive inserts, the rest have M2.5 screws inserted through them into the inserts in other pieces.  The brass inserts used in this project are 
M2.5 x 4mm long.  There are some inserts that go into holes through the entire piece thickness, and some that go into blind holes in the edges.  Each part
with inserts is pictured below for reference:

Pi Mount
^^^^^^^^^

There are eight inserts total for the Pi Mount.  Four go in the printed stand-offs and four go into the edges.

.. image:: images/build_guide/parts_3.jpeg
   :target: images/build_guide/parts_3.jpeg

.. image:: images/build_guide/parts_4.jpeg
   :target: images/build_guide/parts_4.jpeg

Bottom
^^^^^^^

For left/right builds this is the bottom piece.  It needs four inserts for attaching the dovetail mount.

.. image:: images/build_guide/parts_5.jpeg
   :target: images/build_guide/parts_5.jpeg


Flat Adaptor
^^^^^^^^^^^^^
.. note::
   The photos for the Flat Adaptor and the Back shown here are for the v2 build.  The v2.5 parts 
   are almost identical, but have 2 camera mount holes rather than 4. 

This piece takes the place of the bottom and back piece in the left/right build.  It needs eight inserts, 
four to attach the dovetail mount and four to attach the camera

.. image:: images/build_guide/parts_6.jpeg
   :target: images/build_guide/parts_6.jpeg


Back
^^^^^^^^^

The back piece holds the camera for left/right builds and reinforces the PiMount and Bottom piece to 
help keep everything squar and sturdy.  It needs six inserts; four to mount the camera and two in the bottom
edge to connect with the bottom piece

.. image:: images/build_guide/parts_7.jpeg
   :target: images/build_guide/parts_7.jpeg

Dovetail Bottom
^^^^^^^^^^^^^^^^

The dovetail bottom has two inserts to receive the longer 12mm screws which allow angle adjustment.  These inserts
are placed in the side opposite where the top piece connects.  The screws pass through the top piece and part of the 
bottom before engaging with the inserts.  This makes this assembly strong enough to hold the set angle with the screws 
sufficiently tightend.

.. image:: images/build_guide/parts_8.jpeg
   :target: images/build_guide/parts_8.jpeg


Installation
^^^^^^^^^^^^^

Because I use a lot of these inserts, I use a tool to help seat them plumb into the parts,  but I've done plenty freehand and it's not overly difficult.  Use a temperature a bit below your normal printing temperature (for reference, I print PETG at 230c and use 170-200c for inserts) and give the plastic time to melt around them.  


.. image:: ../../images/build_guide/v1.4/build_guide_02.jpg
   :target: ../../images/build_guide/v1.4/build_guide_02.jpg
   :alt: Insert Inserting



Mounting
--------

Most people will want to print the dovetail mount which fits into the finder shoe included on most telescopes.  
The dovetail mount is angle adjustable.  This allows to orient the screen surface (roughly) vertical and perpendicular to the ground. 
This puts the inertial motion sensor into the expected position. See the image below for a better explanation:


.. image:: ../../images/finder_shoe_angle.png
   :target: ../../images/finder_shoe_angle.png
   :alt: Finder shoe angle


Adjustable Dovetail Assembly
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

If you print your own parts, you'll need to add heat-set inserts as pictured in the photo above.  Note that the inserts must be inserted from the outside of the bottom piece, as pictured.  The holes on the inside are not large enough for inserts, they just allow the screws to pass through into the inserts.

See the photos below for how the pieces fit together.  Once assembled you can loosen both screws to adjust the angle up to 40 degrees from horizontal and then secure them again.  No need to go too tight, but a bit of friction will be required to hold the angle.


.. image:: images/build_guide/dovetail_1.jpeg

.. image:: images/build_guide/dovetail_2.jpeg

.. image:: images/build_guide/dovetail_3.jpeg

.. image:: images/build_guide/dovetail_4.jpeg


If you need more flexibility, there is also a go-pro compatible plate that will bolt into the bottom plate.  You'll need to add inserts into the bottom plate mounting footprint to use this option.

Once you've got all the parts printed and inserts inserted, you're ready to :ref:`assemble<build_guide:assembly>`!

Rigel Quickfinder Assembly
^^^^^^^^^^^^^^^^^^^^^^^^^^

This is the list of things, that you'll need for a Rigel Quickfinder adapter: 

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

Please make sure to print "Part 2" in way, such as to maximize the strength of the "hook"! Please print it with supports like this: 

.. image:: images/build_guide/quickfinder_base_4.jpeg

If you print your own parts, you'll need to add heat-set inserts as pictured in the photos below. As the space is limited, you'll need to
fix it first to the PiFinder and then insert the second part. Just tighten the screws a little bit, to hold the second part, so it can't fall off.

After putting it on a Rigel Quickfinder base, tighten the screws fully. Note that the foam double-sided adhesive that's distributed with the
Rigel Quikfinder might be compressed by the weight of the PiFinder (the PiFinder is ~6 times the weight of a Quikfinder), so you might need to reconsider
how the base plate is fixed to your scope.  


.. image:: images/build_guide/quickfinder_base_1.jpeg

.. image:: images/build_guide/quickfinder_base_2.jpeg

.. image:: images/build_guide/quickfinder_base_3.jpeg


Optionally, if you need to adjust the orientation of your PiFinder to make it vertical on your scope, you need these in addition:

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
   
You need to add 4 heat-set inserts as indicated in the following pictures:

.. image:: images/build_guide/quickfinder_base_5.jpeg

.. image:: images/build_guide/quickfinder_base_6.jpeg

The assembly is then like the dovetail assembly in the previous section. Depending on your needs, you can fix the optional adapter 
in two orientations. Make sure the "long lip" is pointing in the same directions like the PiFinder. The completely assembled adapter looks like this:

.. image:: images/build_guide/quickfinder_base_7.jpeg

.. image:: images/build_guide/quickfinder_base_8.jpeg

Once you've got all the parts printed and inserts inserted, you're ready to :ref:`assemble<build_guide:assembly>`!


Assembly
======================


Assembly Overview
-----------------

From here on out you'll need the M2.5 screws, stand-offs, and thumbscrews along with the 3d printed parts, UI hat and other bits like the camera, lens and GPS unit.  Most of the photos in this part of the guide show a build with the PiSugar, but if you are powering the PiFinder in some other way, the assembly is almost identical.

*In all cases, don't over tighten the hardware!*  There is no need and you could end up damaging the 3d printed pieces, inserts or screws.  Once they feel snug, that's probably enough force.  The case forms a ridged assembly once everything is in place and will easily support the camera and other bits.

Pi Mounting
---------------------------

The first step is to mount the Pi and PiSugar battery to the Pi Mount piece.  The pieces you'll need are shown below


.. image:: images/build_guide/common_1.jpeg
   :target: images/build_guide/common_1.jpeg
   :alt: Build Guide Step


Regardless of the orientation of your build, the Raspberry Pi and battery always mount in this same orientation.  The Raspberry Pi and PiSugar (if you are using one) will mount on top of the posts in the RPI Holder.

If you are using a PiSugar it's time to mount the battery pack.  If not, just skip this step and continue on.  Flip the PiMount piece over and use the zip ties to secure the battery as shown.  No need to tighten these down very much, doing so may damage the battery.  It needs just enough to keep it from moving too much. 

Mind the orientation of the battery pack to make sure the connector is situated in the notch as shown below


.. image:: images/build_guide/common_1b.jpeg
   :target: _images/common_1b.jpeg


Snip the zip-ties off and you are ready to move on.


.. image:: images/build_guide/common_1c.jpeg
   :target: images/build_guide/common_1c.jpeg



Camera Prep
---------------------------

The new v3 camera may come with one of two different lens holders aready installed. No matter 
which your camera has you'll be removing and replacing it.

.. image:: images/v25_upgrade/v25_upgrade_11.jpeg

Some cameras have pin headers installed, if you have one of these, you'll need to clip them as close
as reasonable to the board. It can help here to remove the black plastic portion by pulling it with
a pair of pliers.  Alternatively, you can just cut through it to get as close to the PCB as possilble.
Take care not to clip any of the surrounding components.

.. image:: images/v25_upgrade/v25_upgrade_12.jpeg

.. image:: images/v25_upgrade/v25_upgrade_13.jpeg

Grab the lens holder and look through it to make sure it's clear of any obstructions.

Place the lens holder on the table with the large side up oriented as in the photo below.  The two screw
tabs on the lens holder must stick out the opposite sides from the cream-white and dark-grey cable connector on the PCB.
You'll be removing the two screws (yours might be black) near the center of the green PCB and lifting it gently
to the new lens holder.  

Mind the sensor surface on the under side of the PCB. It should sit nicely in the square recess of the lens holder.
Use the same two screws to affix the sensor PCB to the lens holder.  The screws will be cutting their own threads, but
there are holes there to help get started.  Tighten the screws down against the PCB so nothing is wiggling/moving.

.. image:: images/v25_upgrade/v25_upgrade_14.jpeg

.. image:: images/v25_upgrade/v25_upgrade_15.jpeg

Flip the camera assembly over and thread in the lens.  Be slow and careful here.  With gentle force
the lens should slide in a few MM to get everything align and stop.  When it stops, check to make sure it seems 
straight and start screwing it into place.  To get focus about right, You'll want a 6mm gap (picured below) between the 
top of the lens holder and the bottom of the lip on the lens.  Don't fret too much about it as you'll do final focus 
under the stars.

.. image:: images/v25_upgrade/v25_upgrade_16.jpeg

.. image:: images/v25_upgrade/v25_upgrade_17.jpeg


Cable Routing
---------------------------

If you are building a flat unit, just set the camera cable to the side as it gets routed in a different manner.  For left/right builds, it's easier to get the cable roughly positioned now.

Return to the Raspberry Pi assembly and thread the camera cable through as shown.  Note the orientation/direction of the silver contacts at each end of the cable.  The photos below show the cable routing for left and right hand builds.

.. list-table::

   * - .. image:: images/build_guide/left_1.jpeg
          :target: images/build_guide/left_1.jpeg 

       Left hand cable routing

     - .. image:: images/build_guide/right_1.jpeg
          :target: images/build_guide/right_1.jpeg 

       Right hand cable routing

.. important::
    If you are using the recommended S Plus unit, now is the time to make sure you've got it all prepared.

    * Turn the 'Auto Startup' switch on the bottom of the unit to OFF. Having this in the ON position will prevent i2c from working and the IMU will not be used. See the image below:  The switch is outlined in orange, and the photos shows the correct OFF position.

    * The blue power light on the PiSugar board is very bright.  You'll definitely want to cover it with some black nail polish or use a soldering iron to destroy it.  Plug it in to the battery and turn it on to make sure it's subdued.  Check the image below for the position of this LED.  It's already blacked out with nail polish in the photo, but the orange arrow indicates which one you'll want to cover.


.. image:: ../../images/build_guide/pisugar_setup.jpg
   :target: ../../images/build_guide/pisugar_setup.jpg
   :alt: Build Guide Step


The PiSugar will have a protective film on the screw posts as seen in the photo below, make sure to remove this or you'll have a frustrating time getting everything screwed together.


.. image:: ../../images/build_guide/v1.6/build_guide_01.jpeg
   :target: ../../images/build_guide/v1.6/build_guide_01.jpeg
   :alt: Build Guide Step


The PiSugar sits under the Raspberry Pi with the gold pogo pins pressed up against the bottom of the Raspberry Pi.  The side facing up in the image above is the side that should press against the bottom of the Raspberry Pi.  The PiSugar documentation has more info if needed. 

The combined PiSugar/RPI stack then gets secured to the PI Mount using the 20mm stand-offs.  The photos below show the right/left hand stack with their respective cable routing.  For flat configurations, it builds just the same without any camera cable.

.. list-table::

   * - .. figure:: images/build_guide/left_2.jpeg
     
          Left hand PiSugar stack

     - .. figure:: images/build_guide/right_2.jpeg
     
          Right hand PiSugar stack

   * - .. figure:: images/build_guide/left_3.jpeg
     
          Secured with stand offs

     - .. figure:: images/build_guide/right_3.jpeg
     
          Secured wiith stand offs



Right / Left Configuration
---------------------------

Continue on with this section to build a Right/Left hand unit.  The build progresses the same for both versions with some differences in the part orientation.  
You'll see photos for each step with left hand version on the left and right on the right.

Now that the RPI is mounted, it's time to secure the mount plate to the bottom plate.  The bottom plate can be flipped to allow for the screen to 
be facing the right, or left side.  As you can see from the two photos below.

In both cases, the RPI/Screen will always be face the same direction as the long, flat side of the bottom piece.  The angled cut out is 
always on the camera side, and the lens faces the angled portion.  

.. list-table::

   * - .. image:: images/build_guide/left_4.jpeg

     - .. image:: images/build_guide/right_4.jpeg


The first step is to screw the Pi Mount assembly to the bottom plate.  You'll use two screws from underneath running through the bottom plate into the threaded
inserts in the side of the Pi Mount piece.


.. list-table::

   * - .. image:: images/build_guide/left_5.jpeg

     - .. image:: images/build_guide/right_5.jpeg



The back piece is next, but first screw in the four short stand-offs which will support the camera module.  These stand-offs
can be screwed in either side for left or right hand configurations.  Take a look at photos below to match up how the 
back piece fits with both configurations to decide which side to put the stand-offs in.

.. list-table::

   * - .. image:: images/build_guide/left_6.jpeg

     - .. image:: images/build_guide/right_6.jpeg

   * - .. image:: images/build_guide/left_7.jpeg

     - .. image:: images/build_guide/right_7.jpeg

Then the back piece secures to the rest of the assembly via three M2.5 8mm screws.  One goes through the 
back plate into the side-insert in the RPI Mount, there is one of these inserts on either side of the 
RPI Mount for left/right hand builds.  The other two go through the bottom plate into the side-inserts 
on the back plate. 


.. list-table::

   * - .. image:: images/build_guide/left_8.jpeg

     - .. image:: images/build_guide/right_8.jpeg

   * - .. image:: images/build_guide/left_9.jpeg

     - .. image:: images/build_guide/right_9.jpeg

Now it's time to mount the camera module.  You'll need the module, camera tray and 2x12mm m2.5 screws

.. note::
   The images here show an older back piece and camera tray. New kits have a back piece 
   with two holes which match the camera holder.  In this simpler arrangment the camera
   tray is not directly secured to the back piece, but rather has two holes through it.
   The camera holder is secured with longer screws through the tray into the two holes
   in the back piece

Start by connecting the cable to the new camera module.  Open the connector all the way
by sliding the dark-grey piece away from the PCB.  Be gentle as this part can break with too
much force. 

Once the connector is open, slide the cable into the connector using gentle force and making 
sure it's well aligned.  Take you time and watch the
dark-grey clip.  It should not close as you are inserting the cable, and if it does, you'll need
to re-open it to get the cable to slide in all the way.

Once the cable is seated in the connector, close the dark-grey clip by sliding it shut, this 
may take a little force to get it completely closed.  Check the photo below if in doubt!

.. image:: images/v25_upgrade/v25_upgrade_24.jpeg

Situate the camera in the adapter and use the two new screws to secure it.  They are 
the same size as the other four, if they get mixed up.

.. image:: images/v25_upgrade/v25_upgrade_25.jpeg

.. image:: images/v25_upgrade/v25_upgrade_26.jpeg

.. note::
   The remainder of the build guide is yet to be updated with new photos
   including the v2.5 camera.  The build proceeds just the same and we
   will be updating the photos soon.


Flip the unit over and connect the RPI end of the camera cable.  The photo below show the proper orientation of the cable into the connector.  Note the silver contacts facing the white portion of the connector.

.. image:: images/build_guide/assembly_insert_cable.jpeg

For the left hand version you will need a twist in the cable before it enters the connector on the RPI.  Be gentle with it and you'll be able to adjust as you put on the UI Module later.

.. list-table::

   * - .. image:: images/build_guide/left_14.jpeg

     - .. image:: images/build_guide/right_14.jpeg

.. note::
   The remainder of the build is almost the same for left or right hand units.  The photos below are a mix of left and 
   right handed builds, but where there are important differences, you'll see both indicated for clarity.


Next up is to connect the UI Board and affix the shroud. Lay out the board as it will be connected and slide the antenna into the holder on the Pi Mount piece.  
The ceramic top with the silver dimple on it needs to face upwards.  Consult the photos below

.. image:: images/build_guide/right_16.jpeg

.. image:: images/build_guide/right_17.jpeg

.. image:: images/build_guide/right_18.jpeg

.. note::
   The images above have the GPS cable loose and not routed properly.  Please use the 
   routing shown in the :ref:`GPS<build_guide:gps>` section

Now carefully plug the UI Module into the Raspberry Pi.  Make sure both rows of pins are aligned and take your time to 
manage the camera and GPS cables.  The photos below show the left and right configurations for the cable routing.

.. list-table::

   * - .. image:: images/build_guide/left_20.jpeg

     - .. image:: images/build_guide/right_20.jpeg


The screw holes on the UI Board should line up with three of the four stand-offs.  The fourth provides support, but does is not used to secure the outer case. Collect up the Shroud, Bezel and cover plate along with three of the 12mm screws for the next steps

.. image:: images/build_guide/common_5.jpeg
   :target: images/build_guide/common_5.jpeg


The shroud has three optional openings, one for the PiSugar power switch on top, one for the USB ports, 
and one for the SD Card on the side if you want easier access.  These can all be removed with a little force 
or a sharp knife.  If you are using a PiSugar battery, you'll absolutely need to make sure that tab is removed
See the photo below:

.. image:: images/build_guide/common_6.jpeg

Slide the shroud over the unit then stack the bezel and the front PCB plate on top and secure
them all with the three screws

.. image:: images/build_guide/common_7.jpeg

.. image:: images/build_guide/common_8.jpeg

.. image:: images/build_guide/common_9.jpeg

.. image:: images/build_guide/common_10.jpeg

That's looking great!  Now we just need a way to mount it to the scope.  The top portion of the adjustable dovetail
gets screwed directly to the bottom of the PiFinder and then the bottom portion of the dovetail gets secured to the 
top portion.  The orientation of the top part is important to make sure the dovetail adjusts the proper way.  See
the left/right hand photos below:


.. image:: images/build_guide/right_21.jpeg

.. image:: images/build_guide/right_22.jpeg


It's tricky to photograph the final dovetail assembly details on the PiFinder, so check these photos below
and secure the bottom dovetail portion to the top:

.. image:: images/build_guide/dovetail_1.jpeg

.. image:: images/build_guide/dovetail_2.jpeg

.. image:: images/build_guide/dovetail_3.jpeg

.. image:: images/build_guide/dovetail_4.jpeg


The final step is to Go ahead and screw on the camera lens.  The cap on the Pi HQ camera screws off, 
but leave the knurled metal spacer there or the lens will not reach focus properly. 

Gently screw the lens into the camera module.  You'll need to hold the module with your hand as you tighten the lens.


.. image:: images/build_guide/cam_1.jpeg
   :target: images/build_guide/cam_1.jpeg

.. image:: images/build_guide/cam_2.jpeg
   :target: images/build_guide/cam_2.jpeg


That's it! You now have a fully assembled PiFinder!  

Continue on to the :doc:`software setup<software>` if you've not already prepared a SD card.  


.. image:: images/build_guide/common_11.jpeg
   :target: images/build_guide/common_11.jpeg


Flat Assembly
----------------

This section of the build guide contains the steps to complete a Flat build.  This configuration is great for refractors, SCT's and other scopes with rear-focusers as the screen is 'flat' when mounted and the camera faces forward:


.. image:: ../../images/flat_mount.png
   :target: ../../images/flat_mount.png
   :alt: Flat example


If you have not already followed the :ref:`general assembly guide<build_guide:assembly>` through to get to the point pictured below, please do so and then return here.


.. image:: ../../images/build_guide/v1.6/build_guide_11.jpeg
   :target: ../../images/build_guide/v1.6/build_guide_11.jpeg
   :alt: Pi Module Assembled


If you routed the cable as above, pull the camera cable out to remove it from the RPI assembly as the routing is different for a flat build.  

Collect the flat adapter and dovetail.  The dovetail will be secured to the underside of the flat adapter via screws through the adapter and the RPI mount assembly will slot into it the flat adapter and be secured via screws into the edge inserts.  See the photos below for details.

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


Note the one additional screw on the other side visible in the next photo.  Once the RPI Mount is secured to the flat adapter, connect the camera cable to the RPi and the Camera as shown below.


.. image:: ../../images/build_guide/v1.6/flat/flat_build_guide_06.jpeg
   :target: ../../images/build_guide/v1.6/flat/flat_build_guide_06.jpeg
   :alt: Assembly Steps


Turn the PiFinder around and screw in the three thumbscrews as shown.  Check for any excess plastic in the threads and if you run into resistance, try screwing them from the other side first to clear any obstruction.   Screw them most of the way in, but leave some amount for adjustment.


.. image:: ../../images/build_guide/v1.6/flat/flat_build_guide_07.jpeg
   :target: ../../images/build_guide/v1.6/flat/flat_build_guide_07.jpeg
   :alt: Assembly Steps


Next you'll position the camera module and use the longer M2.5 screw to secure it.  The screw should be inserted through the center hole in the flat adapter back and threaded into the center hole in the camera cell.  It should screw in 3-4mm and pull the camera cell against the ends of the three thumbscrews.  If it's not secure, extend the thumbscrews until it's supported.  No need to tighten anything too much here, you'll adjust again to align the PiFinder with your telescopes optical axis.


.. image:: ../../images/build_guide/v1.6/flat/flat_build_guide_09.jpeg
   :target: ../../images/build_guide/v1.6/flat/flat_build_guide_09.jpeg
   :alt: Assembly Steps


Gently plug in the UI Module, working to tuck the cable underneath it.  Take you time and make sure the camera cable is not pinched between the stand-offs and the UI Module.


.. image:: ../../images/build_guide/v1.6/flat/flat_build_guide_10.jpeg
   :target: ../../images/build_guide/v1.6/flat/flat_build_guide_10.jpeg
   :alt: Assembly Steps


.. image:: ../../images/build_guide/v1.6/flat/flat_build_guide_11.jpeg
   :target: ../../images/build_guide/v1.6/flat/flat_build_guide_11.jpeg
   :alt: Assembly Steps


.. image:: ../../images/build_guide/v1.6/flat/flat_build_guide_12.jpeg
   :target: ../../images/build_guide/v1.6/flat/flat_build_guide_12.jpeg
   :alt: Assembly Steps


Once the UI Module is plugged in all the way and the cable is tidy, gather the remaining parts to wrap up the build!  The shroud will slip over the UI Module first, then the bezel slots on top and finally the top PCB.  Use three of the long screws to secure everything together per the photos below.

NOTE:  If you have not already flashed and inserted the SD card into the Raspberry Pi, nows a good time.  It will be harder to get to after the shroud is installed.  Also check to make sure the PiSugar power switch access is cut and punched out of the shroud if you are using a PiSugar.


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


The only remaining thing to do is to affix the camera lens.  Unscrew the cap from the camera module, but make sure you leave the knurled adapter in place as it's required to get the focus distance correct.  Remove the cap from the silver end of the lens and gently screw them together.


.. image:: ../../images/build_guide/v1.6/flat/flat_build_guide_19.jpeg
   :target: ../../images/build_guide/v1.6/flat/flat_build_guide_19.jpeg
   :alt: Assembly Steps


Congratulations, you have a PiFinder! See the :doc:`Software Setup<software>` guide for next steps!

