# PiFinder User Manual

- [Introduction and Overview](user_guide.md#introduction-and-overview)
  * [Keypad and Screen](#keypad-and-screen)
  * [Power Save Mode](#power-save-mode)
- [How-To](user_guide_howto.md)
- [Hardware](user_guide_hw.md)
- [UI Screens](user_guide_ui)
- [Setup](user_guide_setup.md)
- [FAQ](user_guide_faq.md)

## Introduction and Overview
Thanks for your interest in the PiFinder!  This guide describes how to use a PiFinder but if you want information on building one, please see the [Build Guide](./build_guide.md) and the [Bill of Materials](BOM.md).

The PiFinder is a self-contained telescope positioning device.  It will let you know where your telescope is pointed, provide the ability to choose a particular target (like a Galaxy or other DSO) and direct you on how to move your telescope to find that object.  There are some other nice features along with these core functions, but the PiFinder is designed primarily as a way to get interesting objects into your eyepiece so you can take a look at them.

The primary way PiFinder determines where your telescope is pointing is by taking photos of the sky and using stars contained therein to determine where it's pointing.  Having the camera of the PiFinder 

This user manual is divided into several sections which you can access using the links at the top of any section.  

### Keypad and Screen
The main way you'll interact with the PiFinder is through the Keypad and Screen located on the front.  Ideally this will be mounted near your eyepiece for easy access. 

![Hardware UI Overview](../images/ui_reference.png)

Along with the 1.5" oled screen, the keypad has three primary parts, a numeric keypad (_0-9_), four functions keys (_A, B, C, D_), and three control keys (_UP, DN, ENT_).  The screen will display different content depending on the mode you are in, but there will always be a Status Bar along the top which displays which mode the UI is in, the current constellation being pointed at (if a solve has been completed), GPS and Solver Status.

- If the GPS has locked and provided a location, the GPS square in the status bar will be filled in and the G will be in black.  
- The solver status will show either C (Camera) or I (IMU) depending on the source of the last position fix.  The background of this square fades from red to black, over six seconds, indicating the time since last solve.  


### Power Save Mode

The PiFinder will dim the screen and reduce the frequency of exposures, solving, and other processes when it's been idle for a period of time.  This helps save battery power and can also prevent glare at the eyepiece in especially dark environments.  The default is 30 seconds and this can be configured, or turned off completely, in the [Options](user_guide_ui.md#options) page of the [Status](user_guide_ui.md#status) screen.

Pressing any button, or moving the PFinder will wake it from power save mode.
