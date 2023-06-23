Here's a full list of all the items you'll need to build your own PiFinder.  It roughly follows the [Build Guide](./build_guide.md) and I've tried to provide current sources where possible.  Reach out with any questions!

For those folks in the US, Digikey has most of the electronics components and this List can get you started:
[https://www.digikey.com/en/mylists/list/JMHESEPVKV](https://www.digikey.com/en/mylists/list/JMHESEPVKV)

## PiFinder Hat Components
These are the electronic bits needed to build the Display/Keypad unit that fits onto the Raspberry Pi as a 'Hat'.  It's all through-hole soldering so should be approachable for all skill levels.

| Qty | Item                                         | URL                                                     | Notes                                                                                 |
| --- | -------------------------------------------- | ------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| 1   | PCB Set                                      | https://github.com/brickbots/PiFinder/tree/main/gerbers | You'll need a PiFinder board and the PiFinder top plate                               |
| 17  | 6 x 6mm x 7mm PCB Momentary Switch 4 Pin DIP |                                                         | Diptonics DTS63K 1nm recommended                                                      |
| 17  | Red 1.8 mm (miniplast) leds| https://www.mouser.com/ProductDetail/78-TLUR2401                                                        | These need to be 2.5W x 3.3L x 3H to fit properly|
| 1   | 2N222A NPN Transistor | https://www.mouser.com/ProductDetail/637-2N2222A                                                        | Diptonics DTS63K 1nm recommended                                                      |
| 1   | 22ohm Axial Resistor | | R01 - 5% - 1/4w |
| 1   | 330ohm Axial Resistor| | R02 - 5% - 1/4w | 
| 1   | Waveshare 1.5 RGB Oled                       | [https://www.waveshare.com/wiki/1.5inch_RGB_OLED_Module](https://www.waveshare.com/wiki/1.5inch_RGB_OLED_Module)      |                                                                                       |
| 1   | Adafruit IMU Fusion Breakout - BNO055        | https://www.adafruit.com/product/4646                   |                                                                                       |
| 1   | 2x20 40 Pin Stacking Female Header           | https://www.amazon.com/dp/B0827THC7R                    | Depending on your heatsink/clearance you'll need long pins on this to make up the gap |



## Raspberry Pi / Camera / GPS
These are the bigger items/assemblies which you'll need to purchase to include in the overall build.

| Qty | Item                            | URL                                           | Notes                                                                                                                    |
| --- | ------------------------------- | --------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| 1   | Raspberry Pi 4b 2gb             | https://www.adafruit.com/product/4292         | More memory is fine here...                                                                                              |
| 1   | Micro SD Card                    |                                               | High quality is best to avoid power sensitivity and corruption.  The software only needs a couple gigs, so almost any available size should be fine                                                                                                                     |
| 1   | Raspberry Pi HQ camera          | https://www.adafruit.com/product/4561         |                                                                                                                          |
| 1   | 25mm F1.4 CCTV Lens for C Mount | https://www.amazon.com/gp/product/B01IECVHB6/ | Other lenses might work here, but something fast with a 10deg FOV is ideal                                               |
| 1   | GPS USB Dongle.  | https://www.amazon.com/gp/product/B00N32HKIW/ | Almost any GPS receiver should work here, but this is easy to position the antenna and is what has been fully tested

## Case hardware
In addition to the 3d printed parts detailed in the [Build Guide](./build_guide.md) you'll need some bolts, heat-set inserts and standoffs to complete the build.  Everything is M2.5 and some of the lengths can vary a bit.

| Qty | Item                  | URL | Notes                                                                                                                                                                     |
| --- | --------------------- | --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 22   | M2.5x4mm heat set inserts           |     | |
| 14   | M2.5x8mm bolts           |     | Primary fastener for case frame|
| 4   | M2.5x20mm standoffs       |     | Between Pi and Hat Depending on your heatsink and such you may need longer or shorter amounts here and you'll probably need to screw a couple together to get this length |
| 4   | M2.5x6mm standoffs        |     | Between the 3d printed Pi mount and the Pi                                                                                                                                |
| 3   | M2.5x12mm thumbscrews     |     | Camera cell adjustment bolts                                                                                                                                              |
| 4   | M2.5x12mm bolt            |     | Camera cell tensioner and 3 for the shroud/top plate attachment|

## Power
The PiFinder takes about .9amp at 5v under full load, and about 60% of this when in power-save/idle mode.  For battery sizing a good rule of thumb would be 1.25 hour of run time per 1000mah of battery capacity.  You can use any batter pack that will produce at least 1.5 amp of power and plug this into the USB-C port on the unit.

If you'd like to have a fully stand-alone unit with integrated rechargeable battery, there are instructing in the build guide for integrating a [PiSugar S plus](https://github.com/PiSugar/PiSugar/wiki/PiSugarS-Plus).  This is the lower-cost version without RTC, but it has a 5000mah battery which should provide about 5 hours of run time.  
