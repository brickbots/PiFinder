# Build Guide - Assembly

- [Introduction and Overview](build_guide.md)
- [UI Board](build_guide_ui.md)
- [Part Printing and Prep](build_guide_parts.md)
- [Assembly](build_guide_assembly.md)

## Assembly Overview

From here on out you'll need the M2.5 screws, stand-offs, and thumbscrews along with the 3d printed parts, UI hat and other bits like the camera, lens and GPS unit.  Most of the photos in this part of the guide show a build with the PiSugar, but if you are powering the PiFinder in some other way, the assembly is almost identical.

*In all cases, don't over tighten the hardware!*  There is no need and you could end up damaging the 3d printed pieces, inserts or screws.  Once they feel snug, that's probably enough force.  The case forms a ridged assembly once everything is in place and will easily support the camera and other bits.

## Pi Mounting

The first step is to mount the Pi and PiSugar battery to the Pi Mount piece.  The pieces you'll need are shown below

![Build Guide Step](../images/build_guide/v1.4/build_guide_04.jpg)

Regardless of the orientation of your build, the Raspberry Pi and battery always mount in this same orientation.  Start by inserting the short stand-off's into the piece oriented as shown

![Build Guide Step](../images/build_guide/v1.4/build_guide_05.jpg)

Once these are in, it's time to mount the battery pack if you are using a PiSugar.  If not, just skip this step and continue on.  Flip the PiMount piece over and use the zip ties to secure the battery as shown.  No need to tighten these down very much, doing so may damage the battery.  It needs just enough to keep it from moving too much. 

Mind the orientation of the battery pack to make sure the connector is situated in the notch as shown below

![Build Guide Step](../images/build_guide/v1.4/build_guide_06.jpg)

Now is a good time to route the camera cable, so you'll need to remove it from the camera module.  Start by removing the tripod mount, then gently pull up on the connector locking piece and slide the cable out.  See the photos below for more details

![Build Guide Step](../images/build_guide/v1.4/build_guide_07.jpg)
![Build Guide Step](../images/build_guide/v1.4/build_guide_08.jpg)
![Build Guide Step](../images/build_guide/v1.4/build_guide_09.jpg)
![Build Guide Step](../images/build_guide/v1.4/build_guide_10.jpg)
![Build Guide Step](../images/build_guide/v1.4/build_guide_11.jpg)

Once the cable is free, thread it through the PiMount assembly as shown.  Note the orientation/direction of the silver contacts at each end of the cable.

![Build Guide Step](../images/build_guide/v1.4/build_guide_12.jpg)

If you are using a PiSugar, it comes with some protective covers on the screw posts.  Remove these four bits of plastic or it can be very annoying later :-). 

IMPORTANT: If you are using the recommended S Plus unit, turn the 'Auto Startup' switch on the bottom of the unit to OFF. Having this in the ON position will prevent i2c from working and the IMU will not be used. Once the board is mounted, it's hard to reach this switch, so turn it off now :-). See the image below:  It's the switch in the orange box, and the photos shows the correct OFF position. 

ALSO IMPORTANT:  The blue power light on the PiSugar board is very bright.  You'll definitely want to cover it with some black nail polish or something similar.  Plug it in to the battery and turn it on to make sure it's subdued.  Check the image below for the position of this LED.  It's already blacked out with nail polish in the photo, but the orange arrow indicates which one you'll want to cover.

![Build Guide Step](../images/build_guide/pisugar_setup.jpg)


![Build Guide Step](../images/build_guide/v1.4/build_guide_13.jpg)

The PiSugar sits under the Raspberry Pi with the gold pogo pins pressed up against the bottom of the Raspberry Pi.  The side facing up in the image above is the side that should press against the bottom of the Raspberry Pi.  The PiSugar documentation has more info if needed. 

The combined PiSugar/RPI stack then gets secured to the PI Mount using the 20mm stand-offs

![Build Guide Step](../images/build_guide/v1.4/build_guide_15.jpg)
![Build Guide Step](../images/build_guide/v1.4/build_guide_16.jpg)

Now that the RPI is mounted, it's time to secure the mount plate to the bottom plate.  The bottom plate can be flipped to allow for the screen to be facing the right, or left side.  As you can see from the two photos below.

In both cases, the RPI/Screen will always be face the same direction as the long, flat side of the bottom piece.  The angled cut out is always on the camera side, and the lens faces the angled portion.  

Left hand focuser configuration.  Camera will face to the left side of the photo and when put on the scope the screen will face the focuser while the camera faces the business end of the scope.
![Build Guide Step](../images/build_guide/v1.4/build_guide_17.jpg)

Right hand focuser configuration.  Camera will face to the right side of the photo and when put on the scope the screen will face the focuser while the camera faces the business end of the scope.
![Build Guide Step](../images/build_guide/v1.4/build_guide_18.jpg)

The remainder of the guide will be a right-hand build, but the same steps apply, it's just a matter of aligning everything with the bottom plate direction for your build.

Before affixing the RPI Mount sub-section to the bottom plate, it's time to mount the dovetail.  This can be done after the attaching the RPI mount to the bottom plate, but it's difficult, especially with the PiSugar battery.

See the mounting section of the [Parts](build_guide_parts.md#mounting) build guide for more information about the dovetail mount angles. The high side of the dovetail mount should face the flat side of the bottom plate.   Place the bottom plate on top of the dovetail and secure with 4 of the M2.5 8mm screws through the bottom plate into the inserts in the dovetail.
![Build Guide Step](../images/build_guide/v1.4/build_guide_19.jpg)
![Build Guide Step](../images/build_guide/v1.4/build_guide_20.jpg)
![Build Guide Step](../images/build_guide/v1.4/build_guide_22.jpg)

Once the dovetail is mounted to the bottom plate, turn the RPI mount sub-assembly over so that the edge inserts are facing up.  
![Build Guide Step](../images/build_guide/v1.4/build_guide_23.jpg)

The bottom plate then goes on-top of this and is secured with two M2.5 8mm screws through the bottom plate into the edge of the PiMount plate. 
![Build Guide Step](../images/build_guide/v1.4/build_guide_24.jpg)

Turn the unit back over and it should look something like this.  Note that the RPI is facing upwards. 
![Build Guide Step](../images/build_guide/v1.4/build_guide_26.jpg)

The back piece is next.  It secures to the rest of the assembly via three M2.5 8mm screws.  Two go through the bottom plate into the side-inserts on the back plate, and the third goes through the back plate into the side-insert in the RPI Mount.  There is one of these inserts on either side of the RPI Mount for left/right hand builds.

![Build Guide Step](../images/build_guide/v1.4/build_guide_27.jpg)
![Build Guide Step](../images/build_guide/v1.4/build_guide_28.jpg)
![Build Guide Step](../images/build_guide/v1.4/build_guide_29.jpg)
![Build Guide Step](../images/build_guide/v1.4/build_guide_30.jpg)
![Build Guide Step](../images/build_guide/v1.4/build_guide_31.jpg)

Once the back is secured, it's time to build up the camera cell/cover.  See the photos below for how this fits together.  The screws are the standard M2.5 8mm.

![Build Guide Step](../images/build_guide/v1.4/build_guide_32.jpg)
![Build Guide Step](../images/build_guide/v1.4/build_guide_33.jpg)

The camera assembly is held in place with one M2.5 12mm screw and rests against the three thumbscrews so it can be aligned with your telescope.
![Build Guide Step](../images/build_guide/v1.4/build_guide_34.jpg)

Screw in the three thumbscrews so they have some travel left, but stick out to support the camera cell.  Depending on your printer, inserts, and luck, you may need to clear some plastic from the screwholes to get the thumbscrews moving freely.  

![Build Guide Step](../images/build_guide/v1.4/build_guide_35.jpg)
![Build Guide Step](../images/build_guide/v1.4/build_guide_36.jpg)

Connect the cable to the camera before securing the camera to the PiFinder.  The orientation is show below.  You may need to temporarily remove the camera cover to get better access to the connector.
![Build Guide Step](../images/build_guide/v1.4/build_guide_37.jpg)

Use one of the M2.5 12mm screws through the back plate into the center insert in the camera cell to pull the camera cell against the thumbscrews.  Don't over-tighten this screw!  It should apply enough pressure to hold the cell against the thumbscrews, but also allow some adjustment.
![Build Guide Step](../images/build_guide/v1.4/build_guide_38.jpg)

If you are using a PiSugar, connect the battery now.  See the image below:
![Build Guide Step](../images/build_guide/v1.4/build_guide_39.jpg)

Next, connect the other end of the camera cable to the Raspberry Pi camera connector.  This works just like the connector on the camera.  Gently pull the grey piece up to unlock the connector, insert the ribbon cable as show, and press the grey part back down to lock it in place.
![Build Guide Step](../images/build_guide/v1.4/build_guide_40.jpg)

Go ahead and screw on the camera lens.  The cap on the Pi HQ camera screws off, but leave the knurled metal spacer there or the lens will not reach focus properly. 
![Build Guide Step](../images/build_guide/v1.4/build_guide_41.jpg)
![Build Guide Step](../images/build_guide/v1.4/build_guide_42.jpg)

Turn the unit back upright and grab the assembled UI board.  It plugs into the RPI GPIO headers.  Make sure its aligned correctly and use firm pressure to seat it all the way down.

![Build Guide Step](../images/build_guide/v1.4/build_guide_44.jpg)
![Build Guide Step](../images/build_guide/v1.4/build_guide_45.jpg)

The screw holes on the UI Board should line up with three of the four stand-offs.  The fourth provides support, but does is not used to secure the outer case. 

To complete the assembly, the shroud, front PCB plate and bezel get secured with the remaining 3 M2.5 12mm screws.
![Build Guide Step](../images/build_guide/v1.4/build_guide_46.jpg)

The shroud has two extra openings, one for the PiSugar power switch on top, and one for the SD Card on the side if you want easier access.  They are secured with two small tabs, indicated below, which can be cut.  Once these two tabs are cut, bend the cover portion out and it should snap cleanly off leaving an opening.

![Build Guide Step](../images/build_guide/v1.4/build_guide_47.jpg)
![Build Guide Step](../images/build_guide/v1.4/build_guide_48.jpg)

The cutout for the SD card is on the side opposite the USB opening and can be opened in the same way as the PiSugar power switch opening on top.
![Build Guide Step](../images/build_guide/v1.4/build_guide_49.jpg)

Slip the shroud over the board, aligning the three screw holes.  The bezel comes next and the PCB cover sits on top to hold the whole thing together.    
![Build Guide Step](../images/build_guide/v1.4/build_guide_50.jpg)
![Build Guide Step](../images/build_guide/v1.4/build_guide_51.jpg)
![Build Guide Step](../images/build_guide/v1.4/build_guide_52.jpg)
![Build Guide Step](../images/build_guide/v1.4/build_guide_53.jpg)

To complete the unit, use the velcro to secure the GPS transceiver on top of the unit, with the label facing upwards.  Plug in the USB cable and you're done!

![Build Guide Step](../images/build_guide/v1.4/build_guide_54.jpg)
![Build Guide Step](../images/build_guide/v1.4/build_guide_55.jpg)
