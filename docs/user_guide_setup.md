# PiFinder User Manual

- [Introduction and Overview](user_guide.md#introduction-and-overview)
- [How-To](user_guide_howto.md)
- [Hardware](user_guide_hw.md)
- [UI Screens](user_guide_ui)
- [Setup](user_guide_setup.md)
- [FAQ](user_guide_faq.md)

### First Time Setup

Here's a quick start guide for your first time operating the PiFinder:
* Check that your camera aperture and focus are roughly set
* Mount the PiFinder to your scope and power it on.  See the [Mount and Power](./build_guide.md) section of the build guide
* Once the PiFinder has booted and you looking at the preview
	* Set exposure if needed and Focus your lens. See the [Preview](#preview) screen for details on setting exposure and zooming in to check focus
	* Use a star or distant object to align the PiFinder with your telescope
* If it's night-time, and you've got somewhere close for exposure and focus, the PiFinder should have already started solving.  If not:
	* Adjust exposure to make sure you see some stars in the preview display.  If the exposure is too long, relative brightness between stars will be lost and this can also prohibit solving.  
	* Focus is somewhat less critical, but being too far out of focus will reduce the number of faint stars available for solving.
* If you are in an open area, the GPS dongle should have achieved a lock.  Check  the status indicator in the title bar, or the [Status](#status) screen to verify.  If not, double check the status light on the dongle and make sure it has an unobstructed view of as much sky as possible.  The first solve after being off for a few days needs more satellites and will take longer.  Subsequent locks will be much quicker using some cached data in the dongle.


### Camera Setup
After you mount your PiFinder the first time, you'll need to setup the camera aperture and focus.
If you are using the recommended lens, it will have two adjustment rings on it; One to adjust the aperture (f-stop) and one for focus.

![Camera controls](../images/user_guide/camera_controls.png)

#### F-Stop
Make sure the aperture of your lens is all the way open.  For the recommend lens, turn the f-stop ring towards you all the way if you are looking at the unit like like the image above.

#### Focus
Focus for plate solving is actually not all the critical, and defocusing a bit can even improve the solve as it spreads star light across multiple pixels.  You can either use a very distant object during the day, or a bright star at night.  Start with the focus ring all the way to the 'Far' end and you'll probably be close enough to solve most areas of the sky.  Better focus may help pick out a few dimmer stars and allow you to potentially reduce exposure time.

There is a focus helper in the [Preview](#preview) options to help.  This will show a zoomed in image from the center of the camera view to help you hit focus on the small screen.
To activate the focus helper, hold down the 'A' function key while in preview mode and turn on the option from the settings menu.  As you adjust the focus ring, you'll have to wait a second or two make after each adjustment to see the results in the exposure.


### Camera alignment
Once your PiFinder is mounted to your telescope, you'll need to align it with the optical axis of your telescope just like a RACI or red-dot finder.   To do this, you can use the three thumbscrews at the back of the unit to adjust where the camera is pointing:

![Camera Thumbscrews](../images/camera_thumbscrews.png)

* To start, point your telescope at a distant object or bright star and center it in your telescope eyepiece.  
* Turn on the PiFinder if it's not on already
* Make sure your PiFinder is in [Preview](#preview) mode so you can see what the camera sees.
  * If you are doing this during the day, you'll need to use the _DN_ key to reduce the exposure
* Use the three thumbscrews to adjust the tilt of the camera.  Between each adjustment, make sure you wait for a new exposure to be taken to see the results.  This normally takes about 1.5 seconds (at night), depending on your exposure settings.
* If the PiFinder is not holding alignment between observing sessions, try tightening the middle screw, or selecting a stronger spring, to help hold the cell more tightly against the thumbscrews. 

