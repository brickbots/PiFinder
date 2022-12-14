Here's a full list of all the items you'll need to build your own PiFinder.  It roughly follows the [Build Guide](./build_guide.md) and I've tried to provide current sources where possible.  Reach out with any questions!

## PiFinder Hat Components
These are the electronic bits needed to build the Display/Keypad unit that fits onto the Raspberry Pi as a 'Hat'.  It's all throughhole soldering so should be approachable for all skill levels.

| Qty | Item                                         | URL                                                     | Notes                                                                                 |
| --- | -------------------------------------------- | ------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| 1   | PCB Set                                      | https://github.com/brickbots/PiFinder/tree/main/gerbers | You'll need a PiFidner board and the PiFinder top plate                               |
| 17  | 6 x 6mm x 7mm PCB Momentary Switch 4 Pin DIP |                                                         | Diptonics DTS63K 1nm recommended                                                      |
| 1   | Waveshare 1.5 RGB Oled                       | https://www.waveshare.com/wiki/1.5inch_OLED_Module      |                                                                                       |
| 1   | Adafruit IMU Fusion Breakout - BNO055        | https://www.adafruit.com/product/2472                   |                                                                                       |
| 1   | 2x20 40 Pin Stacking Female Header           | https://www.amazon.com/dp/B0827THC7R                    | Depending on your heatsink/clearance you'll need long pins on this to make up the gap |
| 3   | M3x11 Bolts                                  |                                                         |                                                                                       |


## Rapsberry Pi / Camera / GPS
These are the bigger items/assemblies which you'll need to purchase to include in the overall build.

| Qty | Item                            | URL                                           | Notes                                                                                                                    |
| --- | ------------------------------- | --------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| 1   | Raspberry Pi 4b 2gb             | https://www.adafruit.com/product/4292         | More memory is fine here...                                                                                              |
| 1   | Micro SD Card                    |                                               | High quality is best to avoid power sensitivity and corruption.  The software only needs a couple gigs, so almost any available size should be fine                                                                                                                     |
| 1   | Raspberry Pi HQ camera          | https://www.adafruit.com/product/4561         |                                                                                                                          |
| 1   | 25mm F1.4 CCTV Lens for C Mount | https://www.amazon.com/gp/product/B01IECVHB6/ | Other lenses might work here, but something fast with a 10deg FOV is ideal                                               |
| 1   | GPS USB Dongle                  | https://www.amazon.com/gp/product/B00N32HKIW/ | Almost any GPS reciever should work here, but this is easy to position the antenna and is what the software here assumes |

## Case hardware
In addition to the 3d printed parts detailed in the [Build Guide](./build_guide.md) you'll need some bolts, heat-set inserts and standoffs to complete the build.  There is some room for improvisation here!

| Qty | Item                  | URL | Notes                                                                                                                                                                     |
| --- | --------------------- | --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 3   | M3x11mm bolts           |     | To secure top plate/case bezel                                                                                                                                            |
| 4   | M3x28mm standoffs       |     | Between Pi and Hat Depending on your heatsink and such you may need longer or shorter amounts here and you'll probably need to screw a couple together to get this length |
| 4   | M3x5mm standoffs        |     | Between the 3d printed Pi mount and the Pi                                                                                                                                |
| 12   | M3x8mm bolts            |     | Hold case portions together                                                                                                                                               |
| 20  | M3x4mm heat set inserts |     | General case assembly                                                                                                                                                     |
| 3   | M3x12mm thumbscrews     |     | Camera cell adjustment bolts                                                                                                                                              |
| 1   | M3x20mm bolt            |     | Camera cell tensioner, length can vary, but it needs to be longer than the thumbscrews                                                                                                                                                        |
| 1   | Spring                |     | Camera cell tensioner, length can vary                                                                                                                                                        |
| 4   | M2x6mm bolt             |     | Secure camera to cell                                                                                                                                                     |
| 4   | M2 heat set inserts   |     | Secure camera to cell                                                                                                                                                     |
| 4   | M2x2mm spacer           |     | Length is not critical                                                                                                                                                                          |
