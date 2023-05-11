# Build Guide

Welcome to the PiFinder build guide!  Please consult the [Bill of Materials](./BOM.md) for a full list of parts required and reach out with any questions.  Below are many of the parts you'll need for assembly.  Not pictured here are the parts for the keypad backlight which is a feature in current versions of the PiFinder.

This guide currently contains a mix of photos from the older, non-backlit, version and the new backlit version, but the build is the same once you get the backlight components installed.

![Part Layout](../images/build_guide/IMG_4633.jpeg)

## PiFinder Hat
A key part of the PiFinder is a custom 'Hat' which matches the general form factor of the Raspberry Pi and connects to it's GPIO header.  It contains the switches, screen and Inertial Measurement Unit.  

It's all through-hole components, so should be approachable to even beginners... but the component build order is important as some items block access to others.

### Backlight Components
The two resistors are an easy place to start.  R2 is the vertical oriented 330ohm part and R1 is the 22ohm oriented horizontally.  Direction does not matter with these, just make sure they sit flat and trim the leads on the back when they are soldered.

![Resistors](../images/build_guide/led_build_02.jpeg)

The LED's are the next lowest components, so they go next.  Polarity matters here, so mind the direction.  The longer lead of the LED should go through the round hole in the footprint.  The photo below shows the orientation

![LED Orientation](../images/build_guide/led_build_03.jpeg)

Take you time and make sure each is positioned well.  They should be pretty uniform, but little inconsistencies don't matter too much.  I like to place them all in the board, turn it upright and solder one leg of each.  Then I go back and press on each LED as I reheat the one soldered leg to make sure it's sitting flat and even-ish.

![LED Orientation](../images/build_guide/led_build_05.jpeg)

Once I've verified they all look okay, I'll solder the other leg and trim all the leads.

![LED Orientation](../images/build_guide/led_build_06.jpeg)

The final component for the keypad backlight is the drive transistor.  It's located right by R2 and the GPIO connector.  When inserting the part, the flat side of the package should line up with the flat side of the silkscreen.  Once it's inserted fold the flat side of the transistor agains the PCB so it will be clear of the keypad cover PCB

You can see the position/orientation in the image below.  Once you've got it situated, solder it in and clip the leads.

![LED Orientation](../images/build_guide/led_build_08.jpeg)

### Switches
Switches are easy and can go next.  Place each one on a footprint and press it down fully.  Once they are all inserted, before you start soldering visually inspect them for any that are tilted.  

![PCB with switches](../images/build_guide/led_build_10.jpeg)

It's also a good idea to place the top legend plate over them to make sure they all clear the holes properly.  Then solder them up!

![PCB with switches soldered](../images/build_guide/led_build_11.jpeg)

### IMU
The Inertial Measurement unit is next.  The IMU has an annoyingly bright green LED on it, which you will probably want to paint over with a drop of black nail polish.  It can be done after it's soldered, but it's much easier before hand.  See the image below to ID the offending component.

![Green led on IMU](../images/build_guide/adafruit_IMU.png)

The photo below shows the orientation on the back of the PCB.  Solder the headers into the PCB first, then orient the IMU, make sure it sits flat and square with the board.  It does not need to be perfect, but should be secure and low-profile. Solder it into position then trim back the leads of the header to help make sure they don't touch the Raspberry Pi later.


![PCB with switches soldered](../images/build_guide/IMG_4643.jpeg)

### Display
The display comes next and will cover the solder points for the IMU header, so double check your solder joints there before proceeding!

You'll need to remove the stand-offs by unscrewing them from the front.  

![Display as shipped](../images/build_guide/IMG_4648.jpeg)


![Display with standoffs removed](../images/build_guide/IMG_4649.jpeg)

Next you'll need to remove the plug from the underside of the board.  This is not absolutely necessary, but will help the display sit lower and flatter.  Use a sharp pair of cutters to cut each of the leads to the connector first.  Cut down low, but the exact location is not critical.  Once this is done, you can use clippers to cut away the plastic at the attachment points on both of the short sides.

![Connector cut free](../images/build_guide/IMG_4650.jpeg)

It's a good idea to trim and insulate the IMU header pins.  There should be clearance, but it's easy to do and will avoid potential problems later.

![Insulate that header](../images/build_guide/IMG_4651.jpeg)

To make the top plate fit a bit better and look tidier, I suggest sanding back or simply cutting the bottom tabs on the display PCB.  There is no circuitry there, they are just providing screw points which are not needed.

![Cut/Sand tabs on displya](../images/build_guide/IMG_4652.jpeg)

Test fit the screen with the header installed and the top-plate.  Everything should fit nicely and be square.  It's nice to face the longer pins of the header down for a cleaner look up top.

![Screen test fit](../images/build_guide/IMG_4653.jpeg)

Remove the screen, turn over the board and solder the header into place

![Headers in place](../images/build_guide/IMG_4656.jpeg)

![Headers in place](../images/build_guide/IMG_4657.jpeg)

Trim these leads back when done.  Then flip the board back over, place the screen and solder it in.  Take your time and make sure it's nice and lined up for a clean look.

### Connector
Attaching the GPIO connector is the last soldered bit for the Hat.  To get this properly spaced, you'll need to mount the PCB to your Pi using the stand-off's you'll be using for final assembly.  

The pins on the connector are long to accommodate various spacings.  Plug the connector firmly into your Pi and once you have mounted the PiFinder hat to your Pi with stand-offs/screws you'll be able to solder the connector with the correct spacing.

Make sure you've added any heatsinks you plan to use.  In these photos, I'm using a RP3 for assembly and I know what spacing I need.  Take your time here and make sure the hat is secured properly to the Pi, that there is no mechanical interference, and that you're satisfied with the spacing before soldering the connector.  

Depending on your heatsink, you may need a more complicated stand-off arrangement.  You want the hat to completely clear the Pi, but be as low-profile as possible after than.  

Check the photos below for the procedure, it's easier than it sounds!

![Figuring out connector spacing](../images/build_guide/IMG_4661.jpeg)
![Figuring out connector spacing](../images/build_guide/IMG_4662.jpeg)
![Figuring out connector spacing](../images/build_guide/IMG_4663.jpeg)
![Figuring out connector spacing](../images/build_guide/IMG_4666.jpeg)
![Figuring out connector spacing](../images/build_guide/IMG_4667.jpeg)
![Figuring out connector spacing](../images/build_guide/IMG_4668.jpeg)

There you go!  The PiFinder hat is fully assembled.  

## Camera

It's time to prepare the camera an mount it to the 3d printed cell so it can be adjusted to align with your telescope.  

First step is to remove the tripod mount from the camera.  There are two hex screws securing it to the mount-ring.  Just unscrew them and it will come right off.

Next, you'll need to mount the camera module to the camera cell.  Start by inserting the heat-set inserts into the part.  The part is 4mm thick, and the 4 inserts on at the corners are for M2.5 screws.  The middle is M3.

Place short stand-offs in the M2.5 inserts.  Makes these as short as possible, but the spacing is not critical.

![Stand off setup](../images/build_guide/IMG_4707.jpeg)

Then use some short M2.5 screws to secure the camera to the cell

![Stand off setup](../images/build_guide/IMG_4708.jpeg)

Finally, you can attach the lens now, or a bit later in the assembly.  It screws right into the existing knurled adapter that comes with the camera.

![Lens install](../images/build_guide/IMG_4716.jpeg)

## Power

Before continuing to the case build, you'll have to decide how you are going to power the PiFinder.   If you already have 5v power on the scope, or the facility to add a battery pack somewhere, this is probably the easiest way.  

The power consumption of the PiFinder averages .9amp under full load.  In power save mode (configurable in the Options page of the Status screen) it's about .5amp.  Depending on your usage you should get more than 1.25 hour of usage out of each 1000mah of your battery pack.

If you want the unit to be fully self-contained, I suggest the PiSugar-S power system.  They are a thin board that mounts right under the Pi between it and the 3d printed holder.  A nice 5000mah battery is included and it can provide enough power for the unit for about 5 hours.  If you are going to use a PiSugar, make sure you print the case pieces with the `_ps` suffixes for best results.  The shroud is a bit longer and has a cut-out for the power switch while the back-piece is a bit wider to make room for the battery beside the camera.  Here's a photo of a left-handed unit with the PiSugar installed:

![PiSugar Installed](../images/build_guide/IMG_4827.jpeg)

During the build I'll include some specific instructions for incorporating the PiSugar system.

In my case, I already have power on my scope from 12v batteries and there is a 5v source near where I am mounting the PiFinder.  If you have existing power, you can feed it through the USB-C port on the top of the pi, or there is an un-populated power connector on the PCB which can be used to supply REGULATED 5v power.

## Mounting the PiFinder on your scope

### Focuser Side
The PiFinder screen and keyboard should face the direction your focuser does, with the camera pointing forward.  To accommodate left hand and right hand orientations the Pi Mount and Back Plate have two versions denoted with lh and rh suffixes in the filenames.   The rest of the pieces work with either configurations.

Left and Right hand refer to the side of the scope with the focuser when standing near the mirror and facing the aperture end.  Generally 'Behind' the scope.

There is a software option for left and right handed operation.  See the [User Guide](user_guide.md#switch-sides) for details on setting this.


### GoPro
The GoPro mounting system is very flexible and offers a lot of options.  There is a GoPro compatible mounting piece in the `/case/mount` directory of the repo.  To use this mount you'll print the `bottom_plate.3mf` file and insert M3 threaded inserts into the 4 central holes.

The 3d printed GoPro mount will screw into these inserts from the bottom at the end of the build.  You should likely orient it so the slots run parallel to the short dimension of the bottom piece.  This will allow you to 'roll' the PiFinder so that you can have it oriented straight up and down on your scope.

### Dovetail / Finder Shoe
For a more sturdy and repeatable attachment, the dovetail is preferred.  Many scopes already have a shoe for a finder and they are usually the standard 'synta' size.  The dovetail files in the `/case/mount` directory will fit into these standard shoes.

Print one of the 3 dovetail brackets which most closely matches the orientation of your finder shoe.  If your shoe is at the top of your scope, and is parallel to the ground, use the `dovetail_0deg` file and the PiFinder will sit upright on top of it.  

Finder shoes are often not right at the very top of the scope, and they will be angled relative to the ground/direction of gravity.  You can use the 15 / 30 degree models to adjust for this and get the PiFinder to sit closer to plumb.  See the image below for details.  The exact angle is not critical, it's just nice to have the unit pointed perpendicular to the ground for use/visibility.

![Dovetail angle diagram](../images/finder_shoe_angle.png)

The dovetail mount parts take their own M3 heat set inserts and need to be mounted with screws through the bottom piece into the dovetail mount early in the build process.

## Case

The main structure of the PiFinder is made of 3d printed pieces.  STL's for all of the pieces are in the case directory.  Some pieces are specific for either left hand or right hand focuser.  See the section above on 'Focuser Side' for details.

There are two versions of the bottom piece, one designed with inserts to allow the go-pro mount to screw into it, and the other has M3 holes to screw through the bottom into the dovetail mount.  See the [mount](#mount) section below to figure out which way you want to go.

The image below shows all the 3d printed pieces and indicates which threaded inserts go in which hole.  These are early versions of some pieces and yours may not be identical, but the inserts should be the same.  All of the structural bits use M3 screws, but the Pi and Camera mount with M2.5 screws.  The case shroud and bezel only have M2.5 through holes and get secured to the stand-off's holding the Hat.

![Case part ID / Insert details](../images/build_guide/case_parts.png)
The Pi Mount piece can receive M2.5 inserts which can then have short stand-offs, or you can screw through it into stand-offs already mounted on the Pi.  This depends on your preference and the heat-sink arrangement you ended up with.  

Prepare the case parts by inserting all the heat-set inserts.  All parts are 4mm thick and the inserts should push completely through and sit flush.  

## Assembly

All the case parts are held together with M3 screws.  6-8mm length should work great.  See the photo below for all of the parts ready for assembly.

![Case assembly](../images/build_guide/IMG_4669.jpeg)


I think mounting the Pi to the Pi Holder is a good place to start.  For these photos I'm screwing through the Pi Holder into stand-offs in already in the Pi, but you can use threaded inserts and put the standoffs in the Pi Holder first depending on your needs.

![Pi Mounting](../images/build_guide/IMG_4685.jpeg)

##### PiSugar
If you are using a PiSugar, now is the time to fit it under the Pi between it and the holder.  But, before you do, you should paint over the blue power LED with some black nail-polish.  It's shockingly bright and is not really needed as the nice red LED on the Pi itself indicates power.  

Use the standoffs to screw into the PiSugar securing it to the Pi, then use the double female stand-offs.

IMPORTANT: If you are using the recommended S Plus unit, turn the 'Auto Startup' switch on the bottom of the unit to OFF (opposite of what is pictured below).  Having this in the ON position will prevent i2c from working and the IMU will not be used.  Once the board is mounted, it's hard to reach this switch, so turn it off now :-)

![PiSugar Mounting](../images/build_guide/IMG_4809.jpeg)

![Pi Mounting](../images/build_guide/IMG_4686.jpeg)

![Pi Mounting](../images/build_guide/IMG_4687.jpeg)

![Pi Mounting](../images/build_guide/IMG_4688.jpeg)

##### PiSugar
Here's a photo of the PiSugar arrangement in a left-hand unit with the newer Pi mount piece.  The mount is the same for builds with and without the Pi Sugar but is different for Left and Right hand builds.  

![PiSugar Pi mounting](../images/build_guide/IMG_4812.jpeg)


Next, attach the camera cable to the pi and route it around and through the hole in the Pi Mount.  This can be done later, but it's just a bit fussier.   If you have the Hat fitted, remove it first and route the cable per below

![Pi Mounting](../images/build_guide/IMG_4690.jpeg)

### Camera Cable Routing
As you continue the assembly, keep an eye on the camera cable routing.  It's a bit delicate and it is best to be routing it as you assemble more and more of the unit.  For both right and left hand units, the cable should ultimately exit the camera from the side of the camera that faces the Pi.  

Refer to these images as needed while you complete the assembly:

#### Left Handed
For the left handed units, you'll need to get a half-twist in the cable during the routing.  It's probably easiest to do this in the space between the Pi and the UI Hat.  Thank you [u/rwills](https://www.reddit.com/user/rwills) for working out the orientation/cable routing for left hand versions and providing these photos.
![Left hand cable routing 1](../images/build_guide/lh_cable_route.png)

#### Right Handed
Right handed units don't require the cable twist, but still require some forethought to make the final assembly easy and tidy.
![Camera Mounting](../images/build_guide/IMG_4716.jpeg)

##### PiSugar
Before securing the Pi mount piece to the bottom, you need to prepare two zip-ties to hold the battery secure.  These slide between the PiSugar board and the mount plate and fit into the notches on the edge of the mount plate.  Keep them very loose, they just need to be there before you screw it to the bottom plate, and make sure the camera cable is routed as well. (see second image).  

![Pi Mounting](../images/build_guide/IMG_4815.jpeg)

![Pi Mounting](../images/build_guide/IMG_4816.jpeg)

Once you have secured the Pi mount piece to the bottom plate, go head and slide in the battery, minding the cable is in the right place to plug into the PiSugar, and secure the battery with the zip ties.  Don't go tight here, it won't take much to hold this securely and you don't want to damage the battery.  If it slides a little bit, you are a-okay.
![Pi Mounting](../images/build_guide/IMG_4820.jpeg)

If you are going to use the Dovetail mount, you need to affix it to the bottom before continuing.  My finder shoe is offset from the top of my scope, so I've got a 30 degree angle on my dovetail adaptor to make the PiFinder plumb vertically when mounted on my scope.  It's not critical that it be plumb, but I suggest using the dovetail which ends up with the PiFinder as close to plumb as possible. 

If you are using the GoPro mount, you'll be able to screw that into the bottom at the end of the build.  Just make sure you've inserted the M3 threaded inserts for the mount into the bottom.

See the photos below for the dovetail mounting details

![Dovetail Mounting](../images/build_guide/IMG_4695.jpeg)

![Dovetail Mounting](../images/build_guide/IMG_4696.jpeg)

Now mount the Pi Holder to the Bottom, securing through the Pi Holder tabs into the threaded inserts on the bottom.
![Pi Holder to bottom assembly](../images/build_guide/IMG_4698.jpeg)

Next comes the back piece which screws into the bottom and the Pi Holder

![Back Piece](../images/build_guide/IMG_4701.jpeg)

![Back Piece](../images/build_guide/IMG_4702.jpeg)
![Back Piece](../images/build_guide/IMG_4703.jpeg)

##### PiSugar
You'll be using a wider back piece here (indicated with the `_ps` suffix) to move the camera outboard a bit to clear the camera.  Once the back-plate is secured, make sure to plug the battery into the PiSugar board.  The rest of the build proceeds normally.. just make sure to use the `_ps` shroud piece to allow access to the PiSugar switch.

With the frame complete you can now mount the camera cell.  Like the cell of most reflector telescopes this cell is held against 3 adjustable screws to control it's tilt.  Start by inserting the 3 thumbscrews and screwing them almost all the way in.  

![Camera Mounting](../images/build_guide/IMG_4709.jpeg)

![Camera Mounting](../images/build_guide/IMG_4710.jpeg)

![Camera Mounting](../images/build_guide/IMG_4711.jpeg)

 Now prepare the central M3 screw which is used to pull the cell against the adjustment screws.  If you have a suitable spring, it can be used to make adjustment a little easier, but less sturdy.  After using the unit for a bit, I actually prefer it without the spring and suggest you build it this way.  Pick an M3 screw that allows you to pull the camera cell snug against the three adjustment screws.  Then you just need to move the screws in pairs (one out, one in) to keep tension even on the back of the cell while adjusting.

![Camera Mounting](../images/build_guide/IMG_4712.jpeg)

Before your proceed, connect the camera cable to the camera.  When mounting the cell, the cable side goes towards the Pi and the cable sticks into the rectangular cut-out.  See the image below for final mounting orientation

![Camera Mounting](../images/build_guide/IMG_4716.jpeg)

Insert the tensioning screw from the back through the back piece, hold the cell in place and then thread the tensioning screw into the cell.  Be careful not to thread more than 4mm into the cell or it could come out the other side and damage the camera mounted there.

Adjust the length of the tensioning screw depending on your configuration.  Below are photos with and without a spring.

![Camera Mounting](../images/build_guide/IMG_4713.jpeg)
![Camera Mounting](../images/build_guide/IMG_4714.jpeg)

Adjust the spring, screw length and thumbscrews until the cell is pulled tight againt the thumbscrews

![Camera Mounting](../images/build_guide/IMG_4715.jpeg)

![Camera Mounting](../images/build_guide/IMG_4714.jpeg)

Mount the lens now if you have not already and you are done with the frame assembly!
![Camera Mounting](../images/build_guide/IMG_4717.jpeg)

Turn the PiFinder around so that you can plug in the Hat PCB.  Make sure you have the required stand-offs in the Pi, but don't screw it in yet. 
![Hat / Shroud assembly](../images/build_guide/IMG_4718.jpeg)

The shroud slides over the PCB and lines up like so....
![Hat / Shroud assembly](../images/build_guide/IMG_4719.jpeg)

The bezel goes on next and sits in place on top of the shroud.  
![Hat / Shroud assembly](../images/build_guide/IMG_4720.jpeg)

The top plate with key legends goes on top and the whole thing is secured with 3 M2.5 screws through the stack into the stand-offs in the Pi.  You'll need to use fairly long screws here as they go through the top plate, the bezel, the shroud, the Hat and finally into the stand-offs

![Hat / Shroud assembly](../images/build_guide/IMG_4721.jpeg)

Plug in the GPS dongle and mount it where the top faces the sky.  Now you have your very own PiFinder!

![Hat / Shroud assembly](../images/build_guide/IMG_4725.jpeg)

Here's a parting shot of a right and left handed unit, with the PiSugar installed on the left-handed unit... which has the wrong shroud... use the `_ps` one!

![Left/Right Handed](../images/build_guide/IMG_4825.jpeg)

