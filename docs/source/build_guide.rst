
===========
Build Guide
===========

Introduction and Overview
=================================

Welcome to the PiFinder build guide!  This guide is split into three main parts, one for building the `UI Board <build_guide_ui.md>`_ with Screen and Buttons, a section related to `3d printing <build_guide_parts.md>`_ and preparing the case parts, and one for `final assembly <build_guide_assembly.md>`_.   Along with these sections, please consult the `Bill of Materials <BOM>`_ for a full list of parts required and reach out with any questions via `email <mailto:info@pifinder.io>`_ or `discord <https://discord.gg/Nk5fHcAtWD>`_

If you've received a kit with an assembled UI Board + 3d Parts, you can jump right to the `final assembly <build_guide_assembly.md>`_.  Otherwise, fire up that 3d printer and get the `parts printing <build_guide_parts.md>`_ while you work to assemble the `UI Board <build_guide_ui.md>`_ 

PiFinder UI Hat
========================

A key part of the PiFinder is a custom 'Hat' which matches the general form factor of the Raspberry Pi and connects to it's GPIO header.  It contains the switches, screen and Inertial Measurement Unit along with keypad backlight components

It's all through-hole components, so should be approachable to even beginners... but the component build order is important as some items block access to others.

There are still some older photos here from the v1 non-backlit board, but the assembly is the same once the backlight components are in place.

Backlight Components
------------------------

The two resistors are an easy place to start.  R2 is the vertical oriented 330ohm part and R1 is the 22ohm oriented horizontally.  Direction does not matter with these, just make sure they sit flat and trim the leads on the back when they are soldered.


.. image:: ../../images/build_guide/led_build_02.jpeg
   :target: ../../images/build_guide/led_build_02.jpeg
   :alt: Resistors


The LED's are the next lowest components, so they go next.  Polarity matters here, so mind the direction.  The longer lead of the LED should go through the round hole in the footprint.  The photo below shows the orientation


.. image:: ../../images/build_guide/led_build_03.jpeg
   :target: ../../images/build_guide/led_build_03.jpeg
   :alt: LED Orientation


Take you time and make sure each is positioned well.  They should be pretty uniform, but little inconsistencies don't matter too much.  I like to place them all in the board, turn it upright and solder one leg of each.  Then I go back and press on each LED as I reheat the one soldered leg to make sure it's sitting flat and even-ish.


.. image:: ../../images/build_guide/led_build_05.jpeg
   :target: ../../images/build_guide/led_build_05.jpeg
   :alt: LED Orientation


Once I've verified they all look okay, I'll solder the other leg and trim all the leads.


.. image:: ../../images/build_guide/led_build_06.jpeg
   :target: ../../images/build_guide/led_build_06.jpeg
   :alt: LED Orientation


The final component for the keypad backlight is the drive transistor.  It's located right by R2 and the GPIO connector.  When inserting the part, the flat side of the package should line up with the flat side of the silkscreen.  Once it's inserted fold the flat side of the transistor agains the PCB so it will be clear of the keypad cover PCB

You can see the position/orientation in the image below.  Once you've got it situated, solder it in and clip the leads.


.. image:: ../../images/build_guide/led_build_08.jpeg
   :target: ../../images/build_guide/led_build_08.jpeg
   :alt: LED Orientation


Switches
------------------------

Switches are easy and can go next.  Place each one on a footprint and press it down fully.  Once they are all inserted, before you start soldering visually inspect them for any that are tilted.  


.. image:: ../../images/build_guide/led_build_10.jpeg
   :target: ../../images/build_guide/led_build_10.jpeg
   :alt: PCB with switches


It's also a good idea to place the top legend plate over them to make sure they all clear the holes properly.  Then solder them up!


.. image:: ../../images/build_guide/led_build_11.jpeg
   :target: ../../images/build_guide/led_build_11.jpeg
   :alt: PCB with switches soldered


IMU
------------------------

The Inertial Measurement unit is next.  The IMU has an annoyingly bright green LED on it, which you will probably want to paint over with a drop of black nail polish.  It can be done after it's soldered, but it's much easier before hand.  See the image below to ID the offending component.


.. image:: ../../images/build_guide/adafruit_IMU.png
   :target: ../../images/build_guide/adafruit_IMU.png
   :alt: Green led on IMU


The photo below shows the orientation on the back of the PCB.  Solder the headers into the PCB first, then orient the IMU, make sure it sits flat and square with the board.  It does not need to be perfect, but should be secure and low-profile. Solder it into position then trim back the leads of the header to help make sure they don't touch the Raspberry Pi later.


.. image:: ../../images/build_guide/IMG_4643.jpeg
   :target: ../../images/build_guide/IMG_4643.jpeg
   :alt: PCB with switches soldered


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


It's a good idea to trim and insulate the IMU header pins.  There should be clearance, but it's easy to do and will avoid potential problems later.


.. image:: ../../images/build_guide/IMG_4651.jpeg
   :target: ../../images/build_guide/IMG_4651.jpeg
   :alt: Insulate that header


To make the top plate fit a bit better and look tidier, I suggest sanding back or simply cutting the bottom tabs on the display PCB.  There is no circuitry there, they are just providing screw points which are not needed.


.. image:: ../../images/build_guide/IMG_4652.jpeg
   :target: ../../images/build_guide/IMG_4652.jpeg
   :alt: Cut/Sand tabs on displya


Test fit the screen with the header installed and the top-plate.  Everything should fit nicely and be square.  It's nice to face the longer pins of the header down for a cleaner look up top.


.. image:: ../../images/build_guide/IMG_4653.jpeg
   :target: ../../images/build_guide/IMG_4653.jpeg
   :alt: Screen test fit


Remove the screen, turn over the board and solder the header into place


.. image:: ../../images/build_guide/IMG_4656.jpeg
   :target: ../../images/build_guide/IMG_4656.jpeg
   :alt: Headers in place



.. image:: ../../images/build_guide/IMG_4657.jpeg
   :target: ../../images/build_guide/IMG_4657.jpeg
   :alt: Headers in place


Trim these leads back when done.  Then flip the board back over, place the screen and solder it in.  Take your time and make sure it's nice and lined up for a clean look.

Connector
------------------

Attaching the GPIO connector is the last soldered bit for the Hat.  To get this properly spaced, you'll need to mount the PCB to your Pi using the stand-off's you'll be using for final assembly.  

The pins on the connector are long to accommodate various spacings.  Plug the connector firmly into your Pi and once you have mounted the PiFinder hat to your Pi with stand-offs/screws you'll be able to solder the connector with the correct spacing.

Make sure you've added any heatsinks you plan to use.  In these photos, I'm using a RP3 for assembly and I know what spacing I need.  Take your time here and make sure the hat is secured properly to the Pi, that there is no mechanical interference, and that you're satisfied with the spacing before soldering the connector.  

Depending on your heatsink, you may need a more complicated stand-off arrangement.  You want the hat to completely clear the Pi, but be as low-profile as possible after than.  

Check the photos below for the procedure, it's easier than it sounds!


.. image:: ../../images/build_guide/IMG_4661.jpeg
   :target: ../../images/build_guide/IMG_4661.jpeg
   :alt: Figuring out connector spacing


.. image:: ../../images/build_guide/IMG_4662.jpeg
   :target: ../../images/build_guide/IMG_4662.jpeg
   :alt: Figuring out connector spacing


.. image:: ../../images/build_guide/IMG_4663.jpeg
   :target: ../../images/build_guide/IMG_4663.jpeg
   :alt: Figuring out connector spacing


.. image:: ../../images/build_guide/IMG_4666.jpeg
   :target: ../../images/build_guide/IMG_4666.jpeg
   :alt: Figuring out connector spacing


.. image:: ../../images/build_guide/IMG_4667.jpeg
   :target: ../../images/build_guide/IMG_4667.jpeg
   :alt: Figuring out connector spacing


.. image:: ../../images/build_guide/IMG_4668.jpeg
   :target: ../../images/build_guide/IMG_4668.jpeg
   :alt: Figuring out connector spacing


There you go!  The PiFinder hat is fully assembled and you can move on to the `assembly <build_guide_assembly.md>`_ of the rest of the unit.

Printed Parts
===========================


The PiFinder can be built in a left, right or flat configuration to work well on many types of telescopes.  See the `Hardware Users Guide <user_guid_hw.md>`_ for more information including example photos.  To build each configuration, only a subset of the available parts are required.

Inserts
---------

In the photos below you can see the location of most of the heat-set inserts.  The remainder are inserted into the edge of the Back (2x) and RPI Mount (4x) pieces.  If there is a hole in the edge of a piece, it gets an insert.   

Common Parts
-----------------------

There are many parts which are common to all three configurations.  The Bezel, Camera Cell, Camera Cover and RPI Mount are used in all configurations. 

Right and Left configurations
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Below is an image showing all the parts required to build a left or right hand PiFinder.  Note that the Back Plate piece comes in two versions, one for use with a PiSugar (PS) and one without.  The PiSugar piece moves the camera slightly outboard to make room for the PiSugar battery pack.  You'll only need one of these or the other.


.. image:: ../../images/build_guide/v1.6/build_guide_02.jpeg
   :target: ../../images/build_guide/v1.6/build_guide_02.jpeg
   :alt: Parts List


Due to the use of edge inserts, these pieces can be assembled in either left, or right, handed configurations so you just need the one set of parts regardless of which side your focuser is facing.  In the assembly guide you'll find info about how to orient the pieces as you put them together. 

Flat Configuration
^^^^^^^^^^^^^^^^^^

The pieces required for building the flat versions are pictured below.  The same parts are used with or without a PiSugar battery.


.. image:: ../../images/build_guide/v1.6/build_guide_03.jpeg
   :target: ../../images/build_guide/v1.6/build_guide_03.jpeg
   :alt: Parts List


Printing
--------

These pieces will print without supports in the orientation shown on the photo.  I use 3 perimeter layers and 15% infill, but the pieces are not large and don't need to handle heavy forces so almost any print settings should work.

You will want to consider using a material other than PLA, as your PiFinder is likely to experience some sunlight in it's lifetime and PLA degrades under moderate heat and UV.  PETG or some co-polymer like NGen would be a good choice.  Prusamint Galaxy PETG is the official PiFinder filament and is pictured in most of the build guide, except where grey provided needed contrast.

Inserts
-------

Only some holes receive inserts, the rest have M2.5 screws inserted through them into the inserts in other pieces.  The brass inserts used in this project are M2.5 x 4mm long.  There are some inserts that go into holes through the entire piece thickness, and some that go into blind holes in the edges.  The edge inserts are indicated in the image above with arrows.

The Bottom Plate, Shroud, Bezel and Camera Cover have no inserts in them at all.

Because I use a lot of these inserts, I use a tool to help seat them plumb into the parts,  but I've done plenty freehand and it's not overly difficult.  Use a temperature a bit below your normal printing temperature (for reference, I print PETG at 230c and use 170-200c for inserts) and give the plastic time to melt around them.  


.. image:: ../../images/build_guide/v1.4/build_guide_02.jpg
   :target: ../../images/build_guide/v1.4/build_guide_02.jpg
   :alt: Insert Inserting


You can see a closer view of the through and blind inserts below


.. image:: ../../images/build_guide/v1.4/build_guide_03.jpg
   :target: ../../images/build_guide/v1.4/build_guide_03.jpg
   :alt: Insert Inserting
 

Mounting
--------

Most people will want to print the dovetail mount which fits into the finder shoe included on most telescopes.  The Flat configuration has it's own fixed dovetail mount, and the left/right hand version has an angle adjustable dovetail mount.  This is to allow the PiFinder to sit upright so the screen is easily visible.   See the image below for a better explanation:


.. image:: ../../images/finder_shoe_angle.png
   :target: ../../images/finder_shoe_angle.png
   :alt: Finder shoe angle


Adjustable Dovetail Assembly
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

If you purchased a kit, the dovetail will already be assembled.  If you print your own parts, you'll need to add heat-set inserts as pictured in the first phot below.  Note that the inserts must be inserted from the outside of the bottom piece, as pictured.  The holes on the inside are not large enough for inserts, they just allow the screws to pass through into the inserts.

See the photos below for how the pieces fit together.  Once assembled you can loosen both screws to adjust the angle up to 40 degrees from horizontal and then secure them again.  No need to go too tight, but a bit of friction will be required to hold the angle.


.. image:: ../../images/build_guide/adjustable_dovetail/DSC_8569.jpeg
   :target: ../../images/build_guide/adjustable_dovetail/DSC_8569.jpeg
   :alt: Dovetail assembly


.. image:: ../../images/build_guide/adjustable_dovetail/DSC_8574.jpeg
   :target: ../../images/build_guide/adjustable_dovetail/DSC_8574.jpeg
   :alt: Dovetail assembly


.. image:: ../../images/build_guide/adjustable_dovetail/DSC_8575.jpeg
   :target: ../../images/build_guide/adjustable_dovetail/DSC_8575.jpeg
   :alt: Dovetail assembly


.. image:: ../../images/build_guide/adjustable_dovetail/DSC_8578.jpeg
   :target: ../../images/build_guide/adjustable_dovetail/DSC_8578.jpeg
   :alt: Dovetail assembly


If you need more flexibility, there is also a go-pro compatible plate that will bolt into the bottom plate.  You'll need to add inserts into the bottom plate mounting footprint to use this option.

Once you've got all the parts printed and inserts inserted, you're ready to `assemble <build_guide_assembly.md>`_\ !

Assembly
======================


Assembly Overview
-----------------

From here on out you'll need the M2.5 screws, stand-offs, and thumbscrews along with the 3d printed parts, UI hat and other bits like the camera, lens and GPS unit.  Most of the photos in this part of the guide show a build with the PiSugar, but if you are powering the PiFinder in some other way, the assembly is almost identical.

*In all cases, don't over tighten the hardware!*  There is no need and you could end up damaging the 3d printed pieces, inserts or screws.  Once they feel snug, that's probably enough force.  The case forms a ridged assembly once everything is in place and will easily support the camera and other bits.

Pi Mounting and Camera Prep
---------------------------

The first step is to mount the Pi and PiSugar battery to the Pi Mount piece.  The pieces you'll need are shown below


.. image:: ../../images/build_guide/v1.6/build_guide_04.jpeg
   :target: ../../images/build_guide/v1.6/build_guide_04.jpeg
   :alt: Build Guide Step


Regardless of the orientation of your build, the Raspberry Pi and battery always mount in this same orientation.  The Raspberry Pi and PiSugar (if you are using one) will mount on top of the posts in the RPI Holder.

If you are using a PiSugar it's time to mount the battery pack.  If not, just skip this step and continue on.  Flip the PiMount piece over and use the zip ties to secure the battery as shown.  No need to tighten these down very much, doing so may damage the battery.  It needs just enough to keep it from moving too much. 

Mind the orientation of the battery pack to make sure the connector is situated in the notch as shown below


.. image:: ../../images/build_guide/v1.6/build_guide_05.jpeg
   :target: ../../images/build_guide/v1.6/build_guide_05.jpeg
   :alt: Build Guide Step


Snip the zip-ties off and you are ready to move on.


.. image:: ../../images/build_guide/v1.6/build_guide_06.jpeg
   :target: ../../images/build_guide/v1.6/build_guide_06.jpeg
   :alt: Build Guide Step


Now is a good time to route the camera cable, so you'll need to remove it from the camera module.  Start by removing the tripod mount, then gently pull up on the connector locking piece and slide the cable out.  See the photos below for more details


.. image:: ../../images/build_guide/v1.4/build_guide_07.jpg
   :target: ../../images/build_guide/v1.4/build_guide_07.jpg
   :alt: Build Guide Step


.. image:: ../../images/build_guide/v1.4/build_guide_08.jpg
   :target: ../../images/build_guide/v1.4/build_guide_08.jpg
   :alt: Build Guide Step


.. image:: ../../images/build_guide/v1.4/build_guide_09.jpg
   :target: ../../images/build_guide/v1.4/build_guide_09.jpg
   :alt: Build Guide Step


.. image:: ../../images/build_guide/v1.4/build_guide_10.jpg
   :target: ../../images/build_guide/v1.4/build_guide_10.jpg
   :alt: Build Guide Step


.. image:: ../../images/build_guide/v1.4/build_guide_11.jpg
   :target: ../../images/build_guide/v1.4/build_guide_11.jpg
   :alt: Build Guide Step


With the camera module at hand, let's assemble the camera enclosure.  The camera sits on top of the camera cell, the cover goes over both pieces and then the screws hold everything together.  Check the photos below:


.. image:: ../../images/build_guide/v1.6/build_guide_07.jpeg
   :target: ../../images/build_guide/v1.6/build_guide_07.jpeg
   :alt: Build Guide Step



.. image:: ../../images/build_guide/v1.6/build_guide_08.jpeg
   :target: ../../images/build_guide/v1.6/build_guide_08.jpeg
   :alt: Build Guide Step


If you are building a flat unit, just set the camera cable to the side as it gets routed in a different manner.  For left/right builds, it's easier to get the cable roughly positioned now.

Return to the Raspberry Pi assembly and thread the camera cable through as shown.  Note the orientation/direction of the silver contacts at each end of the cable.  The photo below shows the Right hand cable routing.  For the left-hand version, the routing goes the opposite direction.


.. image:: ../../images/build_guide/v1.6/build_guide_08b.jpeg
   :target: ../../images/build_guide/v1.6/build_guide_08b.jpeg
   :alt: Build Guide Step


IMPORTANT: If you are using the recommended S Plus unit, turn the 'Auto Startup' switch on the bottom of the unit to OFF. Having this in the ON position will prevent i2c from working and the IMU will not be used. Once the board is mounted, it's hard to reach this switch, so turn it off now :-). See the image below:  It's the switch in the orange box, and the photos shows the correct OFF position. 

ALSO IMPORTANT:  The blue power light on the PiSugar board is very bright.  You'll definitely want to cover it with some black nail polish or something similar.  Plug it in to the battery and turn it on to make sure it's subdued.  Check the image below for the position of this LED.  It's already blacked out with nail polish in the photo, but the orange arrow indicates which one you'll want to cover.


.. image:: ../../images/build_guide/pisugar_setup.jpg
   :target: ../../images/build_guide/pisugar_setup.jpg
   :alt: Build Guide Step


The PiSugar will have a protective film on the screw posts as seen in the photo below, make sure to remove this or you'll have a frustrating time getting everything screwed together.


.. image:: ../../images/build_guide/v1.6/build_guide_01.jpeg
   :target: ../../images/build_guide/v1.6/build_guide_01.jpeg
   :alt: Build Guide Step


The PiSugar sits under the Raspberry Pi with the gold pogo pins pressed up against the bottom of the Raspberry Pi.  The side facing up in the image above is the side that should press against the bottom of the Raspberry Pi.  The PiSugar documentation has more info if needed. 

The combined PiSugar/RPI stack then gets secured to the PI Mount using the 20mm stand-offs

.. image:: ../../images/build_guide/v1.6/build_guide_09.jpeg
   :target: ../../images/build_guide/v1.6/build_guide_09.jpeg
   :alt: Build Guide Step



.. image:: ../../images/build_guide/v1.6/build_guide_10.jpeg
   :target: ../../images/build_guide/v1.6/build_guide_10.jpeg
   :alt: Build Guide Step



.. image:: ../../images/build_guide/v1.6/build_guide_11.jpeg
   :target: ../../images/build_guide/v1.6/build_guide_11.jpeg
   :alt: Build Guide Step


Right / Left Configuration
---------------------------

Continue on with this document to build a Right/Left hand unit.  The build progresses the same for both versions, but the initial orientations are a bit different and will be noted where appropriate. 

Now that the RPI is mounted, it's time to secure the mount plate to the bottom plate.  The bottom plate can be flipped to allow for the screen to be facing the right, or left side.  As you can see from the two photos below.

In both cases, the RPI/Screen will always be face the same direction as the long, flat side of the bottom piece.  The angled cut out is always on the camera side, and the lens faces the angled portion.  

Left hand focuser configuration.  Camera will face to the left side of the photo and when put on the scope the screen will face the focuser while the camera faces the business end of the scope.

.. image:: ../../images/build_guide/v1.6/build_guide_12.jpeg
   :target: ../../images/build_guide/v1.6/build_guide_12.jpeg
   :alt: Build Guide Step


Right hand focuser configuration.  Camera will face to the right side of the photo and when put on the scope the screen will face the focuser while the camera faces the business end of the scope.

.. image:: ../../images/build_guide/v1.6/build_guide_13.jpeg
   :target: ../../images/build_guide/v1.6/build_guide_13.jpeg
   :alt: Build Guide Step


The remainder of the guide will be a right-hand build, but the same steps apply, it's just a matter of aligning everything with the bottom plate direction for your build.

Before affixing the RPI Mount sub-section to the bottom plate, it's time to mount the dovetail.  This can be done after the attaching the RPI mount to the bottom plate, but it's difficult, especially with the PiSugar battery.

See the mounting section of the `Parts <build_guide_parts.md#mounting>`_ build guide for more information about the dovetail mount assembly.  Even if you are going to use the PiFinder with no angle on the finder shoe, it helps to angle it a bit to assure the proper orientation.  The high side of the dovetail mount should face the flat side of the bottom plate.   Place the bottom plate on top of the dovetail and secure with 4 of the M2.5 8mm screws through the bottom plate into the inserts in the dovetail.

.. image:: ../../images/build_guide/v1.6/build_guide_14.jpeg
   :target: ../../images/build_guide/v1.6/build_guide_14.jpeg
   :alt: Build Guide Step


.. image:: ../../images/build_guide/v1.6/build_guide_15.jpeg
   :target: ../../images/build_guide/v1.6/build_guide_15.jpeg
   :alt: Build Guide Step


Once the dovetail is mounted to the bottom plate, turn the RPI mount sub-assembly over so that the edge inserts are facing up.  Flip the bottom plate/dovetail over as you'll be securing it through the bottom into the inserts in the edge of the RPI Mount.


.. image:: ../../images/build_guide/v1.6/build_guide_17.jpeg
   :target: ../../images/build_guide/v1.6/build_guide_17.jpeg
   :alt: Build Guide Step


The bottom plate then goes on-top of this and is secured with two M2.5 8mm screws through the bottom plate into the edge of the PiMount plate. 

.. image:: ../../images/build_guide/v1.6/build_guide_18.jpeg
   :target: ../../images/build_guide/v1.6/build_guide_18.jpeg
   :alt: Build Guide Step



.. image:: ../../images/build_guide/v1.6/build_guide_19.jpeg
   :target: ../../images/build_guide/v1.6/build_guide_19.jpeg
   :alt: Build Guide Step


The back piece is next.  It secures to the rest of the assembly via three M2.5 8mm screws.  One goes through the back plate into the side-insert in the RPI Mount, there is one of these inserts on either side of the RPI Mount for left/right hand builds.  The other two go through the bottom plate into the side-inserts on the back plate. 


.. image:: ../../images/build_guide/v1.6/build_guide_20.jpeg
   :target: ../../images/build_guide/v1.6/build_guide_20.jpeg
   :alt: Build Guide Step


.. image:: ../../images/build_guide/v1.6/build_guide_21.jpeg
   :target: ../../images/build_guide/v1.6/build_guide_21.jpeg
   :alt: Build Guide Step


.. image:: ../../images/build_guide/v1.6/build_guide_22.jpeg
   :target: ../../images/build_guide/v1.6/build_guide_22.jpeg
   :alt: Build Guide Step


Flip the unit over and connect the RPI end of the camera cable.  The photos below show the Right hand cable routing.  For the left hand version you will need a twist in the cable before it enters the connector on the RPI.  Be gentle with it and you'll be able to adjust as you put on the UI Module later.


.. image:: ../../images/build_guide/v1.6/build_guide_24.jpeg
   :target: ../../images/build_guide/v1.6/build_guide_24.jpeg
   :alt: Build Guide Step


.. image:: ../../images/build_guide/v1.6/build_guide_25.jpeg
   :target: ../../images/build_guide/v1.6/build_guide_25.jpeg
   :alt: Build Guide Step


Grab the camera assembly you prepared earlier.  It is held in place with one M2.5 12mm screw and rests against the three thumbscrews so it can be aligned with your telescope.


.. image:: ../../images/build_guide/v1.6/build_guide_27.jpeg
   :target: ../../images/build_guide/v1.6/build_guide_27.jpeg
   :alt: Build Guide Step

Screw in the three thumbscrews so they have some travel left, but stick out to support the camera cell.  Depending on your printer, inserts, and luck, you may need to clear some plastic from the screwholes to get the thumbscrews moving freely.  


.. image:: ../../images/build_guide/v1.6/build_guide_28.jpeg
   :target: ../../images/build_guide/v1.6/build_guide_28.jpeg
   :alt: Build Guide Step


Connect the camera end of the ribbon cable to the camera.  


.. image:: ../../images/build_guide/v1.6/build_guide_29.jpeg
   :target: ../../images/build_guide/v1.6/build_guide_29.jpeg
   :alt: Build Guide Step


Use one of the M2.5 12mm screws through the back plate into the center insert in the camera cell to pull the camera cell against the thumbscrews.  Don't over-tighten this screw!  It should apply enough pressure to hold the cell against the thumbscrews, but also allow some adjustment.


.. image:: ../../images/build_guide/v1.6/build_guide_31.jpeg
   :target: ../../images/build_guide/v1.6/build_guide_31.jpeg
   :alt: Build Guide Step

If you are using a PiSugar, connect the battery now if you have not already.  See the image below:

.. image:: ../../images/build_guide/v1.6/build_guide_30.jpeg
   :target: ../../images/build_guide/v1.6/build_guide_30.jpeg
   :alt: Build Guide Step


Turn the unit back upright and grab the assembled UI Module.  It plugs into the RPI GPIO headers.  Make sure its aligned correctly and use firm pressure to seat it all the way down.  Check the camera cable as you plug in the UI Module to make sure it's clear of the stand-offs and not caught on anything


.. image:: ../../images/build_guide/v1.6/build_guide_32.jpeg
   :target: ../../images/build_guide/v1.6/build_guide_32.jpeg
   :alt: Build Guide Step



.. image:: ../../images/build_guide/v1.6/build_guide_33.jpeg
   :target: ../../images/build_guide/v1.6/build_guide_33.jpeg
   :alt: Build Guide Step


The screw holes on the UI Board should line up with three of the four stand-offs.  The fourth provides support, but does is not used to secure the outer case. 


.. image:: ../../images/build_guide/v1.6/build_guide_34.jpeg
   :target: ../../images/build_guide/v1.6/build_guide_34.jpeg
   :alt: Build Guide Step


The shroud has two extra openings, one for the PiSugar power switch on top, and one for the SD Card on the side if you want easier access.  They are secured with two small tabs, indicated below, which can be cut.  Once these two tabs are cut, bend the cover portion out and it should snap cleanly off leaving an opening.

The cutout for the SD card is on the side opposite the USB opening and can be opened in the same way as the PiSugar power switch opening on top.


.. image:: ../../images/build_guide/v1.6/build_guide_35.jpeg
   :target: ../../images/build_guide/v1.6/build_guide_35.jpeg
   :alt: Build Guide Step


.. image:: ../../images/build_guide/v1.6/build_guide_36.jpeg
   :target: ../../images/build_guide/v1.6/build_guide_36.jpeg
   :alt: Build Guide Step


To complete the assembly, the shroud, front PCB plate and bezel get secured with the remaining 3 M2.5 12mm screws.

.. image:: ../../images/build_guide/v1.6/build_guide_37.jpeg
   :target: ../../images/build_guide/v1.6/build_guide_37.jpeg
   :alt: Build Guide Step


.. image:: ../../images/build_guide/v1.6/build_guide_38.jpeg
   :target: ../../images/build_guide/v1.6/build_guide_38.jpeg
   :alt: Build Guide Step


Go ahead and screw on the camera lens.  The cap on the Pi HQ camera screws off, but leave the knurled metal spacer there or the lens will not reach focus properly. 

Gently screw the lens into the camera module.  You'll need to hold the module with your hand as you tighten the lens.


.. image:: ../../images/build_guide/v1.6/build_guide_39.jpeg
   :target: ../../images/build_guide/v1.6/build_guide_39.jpeg
   :alt: Build Guide Step


.. image:: ../../images/build_guide/v1.6/build_guide_40.jpeg
   :target: ../../images/build_guide/v1.6/build_guide_40.jpeg
   :alt: Build Guide Step


To complete the unit, use the velcro to secure the GPS transceiver on top of the unit, with the label facing upwards.  Plug in the USB cable and you're done!


.. image:: ../../images/build_guide/v1.6/build_guide_41.jpeg
   :target: ../../images/build_guide/v1.6/build_guide_41.jpeg
   :alt: Build Guide Step


.. image:: ../../images/build_guide/v1.6/build_guide_42.jpeg
   :target: ../../images/build_guide/v1.6/build_guide_42.jpeg
   :alt: Build Guide Step


Continue on to the `software setup <software.md>`_ if you've not already prepared a SD card.  


.. image:: ../../images/build_guide/v1.6/build_guide_44.jpeg
   :target: ../../images/build_guide/v1.6/build_guide_44.jpeg
   :alt: Build Guide Step


Flat Assembly
----------------

This section of the build guide contains the steps to complete a Flat build.  This configuration is great for refractors, SCT's and other scopes with rear-focusers as the screen is 'flat' when mounted and the camera faces forward:


.. image:: ../../images/flat_mount.png
   :target: ../../images/flat_mount.png
   :alt: Flat example


If you have not already followed the `general assembly guide <build_assembly.md>`_ through to get to the point pictured below, please do so and then return here.


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

