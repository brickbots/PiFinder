# PiFinder User Manual - FAQ

- [Introduction and Overview](user_guide.md#introduction-and-overview)
- [How-To](user_guide_howto.md)
- [Hardware](user_guide_hw.md)
- [UI Screens](user_guide_ui.md)
- [Setup](user_guide_setup.md)
- [FAQ](user_guide_faq.md)

## FAQ

### What is the pifinder account password for prebuilt images?

`solveit` 

### When I use the shutdown function, the screen just says "Shutting Down", but never turns off or otherwise indicates it's safe to power down.  What's up with that?

The shutdown command in the menu issues the standard shutdown command for the OS… so once it’s issued the PiFinder software stops and can no longer update the display.

On all the RPI4’s I’ve tested, once the OS gets to a certain point, the screen will go blank, but on the RPI3’s it stays illuminated even after the OS is halted.  

Neither the blank screen or lingering message a good indication of when it’s ’safe’ to turn the unit off.  On the RPI4, the screen blanks a bit before the OS actually halts, and on the RPI3 it never blanks even after it’s halted!  

I’ll keep thinking about this as it’s kind of tricky to use the system to show it’s safe to turn off then the system itself is halted….. but if you give it about 10 seconds, you can be almost certain the OS is halted and it’s safe to turn off.


### I have other questions... what should I do?

Please send them through to me at [info@pifinder.io](mailto:info@pifinder.io) and I'll do my best to help and potentially add your question here.  Better yet, feel free to fork this repo and contribute via a pull request!
