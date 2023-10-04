# Build Guide - Assembly

- [Introduction and Overview](build_guide.md)
- [UI Board](build_guide_ui.md)
- [Part Printing and Prep](build_guide_parts.md)
- [Assembly](build_guide_assembly.md)

## Assembly Overview

From here on out you'll need the M2.5 screws, stand-offs, and thumbscrews along with the 3d printed parts, UI hat and other bits like the camera, lens and GPS unit.  Most of the photos in this part of the guide show a build with the PiSugar, but if you are powering the PiFinder in some other way, the assembly is almost identical.

*In all cases, don't over tighten the hardware!*  There is no need and you could end up damaging the 3d printed pieces, inserts or screws.  Once they feel snug, that's probably enough force.  The case forms a ridged assembly once everything is in place and will easily support the camera and other bits.

## Pi Mounting and Camera Prep

The first step is to mount the Pi and PiSugar battery to the Pi Mount piece.  The pieces you'll need are shown below

![Build Guide Step](../images/build_guide/v1.6/build_guide_04.jpeg)

Regardless of the orientation of your build, the Raspberry Pi and battery always mount in this same orientation.  The Raspberry Pi and PiSugar (if you are using one) will mount on top of the posts in the RPI Holder.

If you are using a PiSugar it's time to mount the battery pack.  If not, just skip this step and continue on.  Flip the PiMount piece over and use the zip ties to secure the battery as shown.  No need to tighten these down very much, doing so may damage the battery.  It needs just enough to keep it from moving too much. 

Mind the orientation of the battery pack to make sure the connector is situated in the notch as shown below

![Build Guide Step](../images/build_guide/v1.6/build_guide_05.jpeg)

Snip the zip-ties off and you are ready to move on.

![Build Guide Step](../images/build_guide/v1.6/build_guide_06.jpeg)

Now is a good time to route the camera cable, so you'll need to remove it from the camera module.  Start by removing the tripod mount, then gently pull up on the connector locking piece and slide the cable out.  See the photos below for more details

![Build Guide Step](../images/build_guide/v1.4/build_guide_07.jpg)
![Build Guide Step](../images/build_guide/v1.4/build_guide_08.jpg)
![Build Guide Step](../images/build_guide/v1.4/build_guide_09.jpg)
![Build Guide Step](../images/build_guide/v1.4/build_guide_10.jpg)
![Build Guide Step](../images/build_guide/v1.4/build_guide_11.jpg)

With the camera module at hand, let's assemble the camera enclosure.  The camera sits on top of the camera cell, the cover goes over both pieces and then the screws hold everything together.  Check the photos below:

![Build Guide Step](../images/build_guide/v1.6/build_guide_07.jpeg)

![Build Guide Step](../images/build_guide/v1.6/build_guide_08.jpeg)

If you are building a flat unit, just set the camera cable to the side as it gets routed in a different manner.  For left/right builds, it's easier to get the cable roughly positioned now.

Return to the Raspberry Pi assembly and thread the camera cable through as shown.  Note the orientation/direction of the silver contacts at each end of the cable.  The photo below shows the Right hand cable routing.  For the left-hand version, the routing goes the opposite direction.

![Build Guide Step](../images/build_guide/v1.6/build_guide_08b.jpeg)

IMPORTANT: If you are using the recommended S Plus unit, turn the 'Auto Startup' switch on the bottom of the unit to OFF. Having this in the ON position will prevent i2c from working and the IMU will not be used. Once the board is mounted, it's hard to reach this switch, so turn it off now :-). See the image below:  It's the switch in the orange box, and the photos shows the correct OFF position. 

ALSO IMPORTANT:  The blue power light on the PiSugar board is very bright.  You'll definitely want to cover it with some black nail polish or something similar.  Plug it in to the battery and turn it on to make sure it's subdued.  Check the image below for the position of this LED.  It's already blacked out with nail polish in the photo, but the orange arrow indicates which one you'll want to cover.

![Build Guide Step](../images/build_guide/pisugar_setup.jpg)


The PiSugar will have a protective film on the screw posts as seen in the photo below, make sure to remove this or you'll have a frustrating time getting everything screwed together.

![Build Guide Step](../images/build_guide/v1.6/build_guide_01.jpeg)

The PiSugar sits under the Raspberry Pi with the gold pogo pins pressed up against the bottom of the Raspberry Pi.  The side facing up in the image above is the side that should press against the bottom of the Raspberry Pi.  The PiSugar documentation has more info if needed. 

The combined PiSugar/RPI stack then gets secured to the PI Mount using the 20mm stand-offs
![Build Guide Step](../images/build_guide/v1.6/build_guide_09.jpeg)

![Build Guide Step](../images/build_guide/v1.6/build_guide_10.jpeg)

![Build Guide Step](../images/build_guide/v1.6/build_guide_11.jpeg)

### Flat Configuration
Please see the [Flat Build Guide](build_guide_flat.md) for the remainder of the instructions for the Flat Build

### Right / Left Configuration
Continue on with this document to build a Right/Left hand unit.  The build progresses the same for both versions, but the initial orientations are a bit different and will be noted where appropriate. 

Now that the RPI is mounted, it's time to secure the mount plate to the bottom plate.  The bottom plate can be flipped to allow for the screen to be facing the right, or left side.  As you can see from the two photos below.

In both cases, the RPI/Screen will always be face the same direction as the long, flat side of the bottom piece.  The angled cut out is always on the camera side, and the lens faces the angled portion.  

Left hand focuser configuration.  Camera will face to the left side of the photo and when put on the scope the screen will face the focuser while the camera faces the business end of the scope.
![Build Guide Step](../images/build_guide/v1.6/build_guide_12.jpeg)

Right hand focuser configuration.  Camera will face to the right side of the photo and when put on the scope the screen will face the focuser while the camera faces the business end of the scope.
![Build Guide Step](../images/build_guide/v1.6/build_guide_13.jpeg)

The remainder of the guide will be a right-hand build, but the same steps apply, it's just a matter of aligning everything with the bottom plate direction for your build.

Before affixing the RPI Mount sub-section to the bottom plate, it's time to mount the dovetail.  This can be done after the attaching the RPI mount to the bottom plate, but it's difficult, especially with the PiSugar battery.

See the mounting section of the [Parts](build_guide_parts.md#mounting) build guide for more information about the dovetail mount assembly.  Even if you are going to use the PiFinder with no angle on the finder shoe, it helps to angle it a bit to assure the proper orientation.  The high side of the dovetail mount should face the flat side of the bottom plate.   Place the bottom plate on top of the dovetail and secure with 4 of the M2.5 8mm screws through the bottom plate into the inserts in the dovetail.
![Build Guide Step](../images/build_guide/v1.6/build_guide_14.jpeg)
![Build Guide Step](../images/build_guide/v1.6/build_guide_15.jpeg)

Once the dovetail is mounted to the bottom plate, turn the RPI mount sub-assembly over so that the edge inserts are facing up.  Flip the bottom plate/dovetail over as you'll be securing it through the bottom into the inserts in the edge of the RPI Mount.

![Build Guide Step](../images/build_guide/v1.6/build_guide_17.jpeg)

The bottom plate then goes on-top of this and is secured with two M2.5 8mm screws through the bottom plate into the edge of the PiMount plate. 
![Build Guide Step](../images/build_guide/v1.6/build_guide_18.jpeg)

![Build Guide Step](../images/build_guide/v1.6/build_guide_19.jpeg)

The back piece is next.  It secures to the rest of the assembly via three M2.5 8mm screws.  One goes through the back plate into the side-insert in the RPI Mount, there is one of these inserts on either side of the RPI Mount for left/right hand builds.  The other two go through the bottom plate into the side-inserts on the back plate. 

![Build Guide Step](../images/build_guide/v1.6/build_guide_20.jpeg)
![Build Guide Step](../images/build_guide/v1.6/build_guide_21.jpeg)
![Build Guide Step](../images/build_guide/v1.6/build_guide_22.jpeg)

Flip the unit over and connect the RPI end of the camera cable.  The photos below show the Right hand cable routing.  For the left hand version you will need a twist in the cable before it enters the connector on the RPI.  Be gentle with it and you'll be able to adjust as you put on the UI Module later.

![Build Guide Step](../images/build_guide/v1.6/build_guide_24.jpeg)
![Build Guide Step](../images/build_guide/v1.6/build_guide_25.jpeg)

Grab the camera assembly you prepared earlier.  It is held in place with one M2.5 12mm screw and rests against the three thumbscrews so it can be aligned with your telescope.

![Build Guide Step](../images/build_guide/v1.6/build_guide_27.jpeg)
Screw in the three thumbscrews so they have some travel left, but stick out to support the camera cell.  Depending on your printer, inserts, and luck, you may need to clear some plastic from the screwholes to get the thumbscrews moving freely.  

![Build Guide Step](../images/build_guide/v1.6/build_guide_28.jpeg)

Connect the camera end of the ribbon cable to the camera.  

![Build Guide Step](../images/build_guide/v1.6/build_guide_29.jpeg)

Use one of the M2.5 12mm screws through the back plate into the center insert in the camera cell to pull the camera cell against the thumbscrews.  Don't over-tighten this screw!  It should apply enough pressure to hold the cell against the thumbscrews, but also allow some adjustment.

![Build Guide Step](../images/build_guide/v1.6/build_guide_31.jpeg)
If you are using a PiSugar, connect the battery now if you have not already.  See the image below:
![Build Guide Step](../images/build_guide/v1.6/build_guide_30.jpeg)

Turn the unit back upright and grab the assembled UI Module.  It plugs into the RPI GPIO headers.  Make sure its aligned correctly and use firm pressure to seat it all the way down.  Check the camera cable as you plug in the UI Module to make sure it's clear of the stand-offs and not caught on anything

![Build Guide Step](../images/build_guide/v1.6/build_guide_32.jpeg)

![Build Guide Step](../images/build_guide/v1.6/build_guide_33.jpeg)

The screw holes on the UI Board should line up with three of the four stand-offs.  The fourth provides support, but does is not used to secure the outer case. 

![Build Guide Step](../images/build_guide/v1.6/build_guide_34.jpeg)

The shroud has two extra openings, one for the PiSugar power switch on top, and one for the SD Card on the side if you want easier access.  They are secured with two small tabs, indicated below, which can be cut.  Once these two tabs are cut, bend the cover portion out and it should snap cleanly off leaving an opening.

The cutout for the SD card is on the side opposite the USB opening and can be opened in the same way as the PiSugar power switch opening on top.

![Build Guide Step](../images/build_guide/v1.6/build_guide_35.jpeg)
![Build Guide Step](../images/build_guide/v1.6/build_guide_36.jpeg)

To complete the assembly, the shroud, front PCB plate and bezel get secured with the remaining 3 M2.5 12mm screws.
![Build Guide Step](../images/build_guide/v1.6/build_guide_37.jpeg)
![Build Guide Step](../images/build_guide/v1.6/build_guide_38.jpeg)

Go ahead and screw on the camera lens.  The cap on the Pi HQ camera screws off, but leave the knurled metal spacer there or the lens will not reach focus properly. 

Gently screw the lens into the camera module.  You'll need to hold the module with your hand as you tighten the lens.


![Build Guide Step](../images/build_guide/v1.6/build_guide_39.jpeg)
![Build Guide Step](../images/build_guide/v1.6/build_guide_40.jpeg)

To complete the unit, use the velcro to secure the GPS transceiver on top of the unit, with the label facing upwards.  Plug in the USB cable and you're done!

![Build Guide Step](../images/build_guide/v1.6/build_guide_41.jpeg)
![Build Guide Step](../images/build_guide/v1.6/build_guide_42.jpeg)

Continue on to the [software setup](software.md) if you've not already prepared a SD card.  

![Build Guide Step](../images/build_guide/v1.6/build_guide_44.jpeg)