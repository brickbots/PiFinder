Parts List
==========

Here's a full list of all the items you'll need to build your own PiFinder.  It roughly follows the :doc:`Build Guide<build_guide>` and I've tried to provide current sources where possible.  Reach out with any questions!

For those folks in the US, Digikey has most of the electronics components and this List can get you started:
`https://www.digikey.com/en/mylists/list/JMHESEPVKV <https://www.digikey.com/en/mylists/list/JMHESEPVKV>`_

PiFinder Hat Components
-----------------------

These are the electronic bits needed to build the Display/Keypad unit that fits onto the Raspberry Pi as a 'Hat'.  It's all through-hole soldering so should be approachable for all skill levels.

.. list-table::
   :header-rows: 1

   * - Qty
     - Item
     - URL
     - Notes
   * - 1
     - PCB Set
     - https://github.com/brickbots/PiFinder/tree/main/gerbers
     - You'll need a PiFinder board and the PiFinder top plate
   * - 17
     - 6 x 6mm x 7mm PCB Momentary Switch 4 Pin DIP
     - https://www.mouser.com/ProductDetail/113-DTS63KV or https://www.digikey.com/en/products/detail/apem-inc/ADTS63KV/1798560
     - Diptronics DTS63K or Apem ADTS63KV recommended
   * - 17
     - Red 1.8 mm (miniplast) leds
     - https://www.mouser.com/ProductDetail/78-TLUR2401
     - These need to be 2.5W x 3.3L x 3H to fit properly
   * - 1
     - 2N2222A NPN Transistor
     - https://www.mouser.com/ProductDetail/637-2N2222A
     - 
   * - 1
     - 22ohm Axial Resistor
     - 
     - R01 - 5% - 1/4w
   * - 1
     - 330ohm Axial Resistor
     - 
     - R02 - 5% - 1/4w
   * - 1
     - Waveshare 1.5 RGB Oled
     - `https://www.waveshare.com/wiki/1.5inch_RGB_OLED_Module <https://www.waveshare.com/wiki/1.5inch_RGB_OLED_Module>`_
     - 
   * - 1
     - Adafruit IMU Fusion Breakout - BNO055
     - https://www.adafruit.com/product/4646
     - 
   * - 1
     - 2x20 40 Pin Stacking Female Header
     - https://www.amazon.com/dp/B0827THC7R
     - Depending on your heatsink/clearance you'll need long pins on this to make up the gap
   * - 1
     - GT-U7 GPS Transceiver board
     - https://www.amazon.com/Microcontroller-Compatible-Sensitivity-Navigation-Positioning/dp/B07P8YMVNT
     - There may be other pin compatible devices, but this one works great and the antenna fits the holder


Raspberry Pi / Camera / GPS
---------------------------

These are the bigger items/assemblies which you'll need to purchase to include in the overall build.

.. list-table::
   :header-rows: 1

   * - Qty
     - Item
     - URL
     - Notes
   * - 1
     - Raspberry Pi 4b 2gb
     - https://www.adafruit.com/product/4292
     - More memory is fine here...
   * - 1
     - Micro SD Card
     - 
     - High quality is best to avoid power sensitivity and corruption.  The software only needs a couple gigs, so almost any available size should be fine
   * - 1
     - InnoMaker imx296 mono camera module
     - https://www.inno-maker.com/product/cam-mipi296raw-trigger/
     - 
   * - 1
     - 16mm F2 CCTV Lens for m12 Mount
     - https://www.amazon.com/dp/B07VDWNSG9
     - Other lenses might work here, but something fast with a 10deg FOV is ideal

Case hardware
-------------

In addition to the 3d printed parts detailed in the :doc:`Build Guide<build_guide>` you'll need some bolts, heat-set inserts and standoffs to complete the build.  Everything is M2.5 and some of the lengths can vary a bit.

.. list-table::
   :header-rows: 1

   * - Qty
     - Item
     - URL
     - Notes
   * - 22
     - M2.5x4mm heat set inserts
     - 
     - 
   * - 20
     - M2.5x8mm bolts
     - 
     - Primary fastener for case frame
   * - 4
     - M2.5x20mm standoffs
     - 
     - Between Pi and Hat Depending on your heatsink and such you may need longer or shorter amounts here and you'll probably need to screw a couple together to get this length
   * - 4
     - M2.5x5mm standoffs
     - 
     - Between the Camera and the 3d printed back piece
   * - 5
     - M2.5x12mm bolt
     - 
     - 2 for the adjustable dovetail mount and 3 for the shroud/top plate attachment


Power
-----

The PiFinder takes about .9amp at 5v under full load, and about 60% of this when in power-save/idle mode.  For battery sizing a good rule of thumb would be 1.25 hour of run time per 1000mah of battery capacity.  You can use any batter pack that will produce at least 1.5 amp of power and plug this into the USB-C port on the unit.

If you'd like to have a fully stand-alone unit with integrated rechargeable battery, there are instructing in the build guide for integrating a `PiSugar S plus <https://github.com/PiSugar/PiSugar/wiki/PiSugarS-Plus>`_.  This is the lower-cost version without RTC, but it has a 5000mah battery which should provide about 5 hours of run time.  
