# PiFinder User Manual - How To

- [Introduction and Overview](user_guide.md#introduction-and-overview)
- [How-To](#how-to)
  * [First Time Setup](#first-time-setup)
  * [WiFi](#wifi)
  * [SkySafari](#skysafari)
  * [Data Access (SMB Share)](#data-access)
  * [Shutdown and Restart](#shutdown-and-Restart)
  * [Observing lists](#observing-lists)
  * [Update Software](#update-software)
- [Hardware](user_guide_hw.md)
- [UI Screens](user_guide_ui)
- [Setup](user_guide_setup.md)
- [FAQ](user_guide_faq.md)

## How-To

### Switch Sides
By default, the PiFinder software is set for right-side focuser operation.   To switch to left-side orientation, use the [Options](user_guide_ui.md#options) page of the [Status](user_guide_ui.md#status) screen.  This will make sure the preview is displayed correct side up and the IMU up/down direction is correct.

### WiFi
The PiFinder can either connect to an existing network, or serve as an wireless access point for other devices to connect to.  Use the [Options](user_guide_ui.md#system-options) page of the Status screen to switch between these two modes and see which mode is currently active.

Using the PiFinder in Access Point mode creates a network called AP_PiFinder with no password to allow easy connection of phones, tablets and other devices in the field.

In most cases, you can use the name `pifinder.local` to connect to the PiFinder.  On older computer or those that don't support zeroconf networking, you can use the IP address provides on the [Status](user_guide_ui.md#status) screen to connect.  You can connect to the PiFinder via:
* SSH to get shell access for software updates and other admin tasks
* SMB (Samba) to access saved images, logs an observing lists
* LX200 protocol to allow updating of a planetarium app, such as [SkySafari](#skysafari), with the position of the telescope

### SkySafari
The PiFinder can provide real-time pointing information to a device running SkySafari via the LX200 protocol.  See this [guide](./skysafari.md) for complete details, but here is the connection info:
* Use 'Other' telescope type
* Mount Type: Alt-Az, GoTo.. even if your scope is Push-To.  This allows sending of targets from SkySafari to the PiFinder
* Scope Type: Meade LX200 classic
* IP Address: `pifinder.local` or IP address provides on the [Status](user_guide_ui.md#status) screen.
* Port: 4030

### Data Access
In the course of using the PiFinder several data files are created that may be of interest.  These are available via a SMB (samba) network share called `//pifinder.local/shared`.  Accessing this will depend on your OS, but the PiFinder should be visible in a network browser provided.  There is no password requirement, just connect as `guest` with no password provided.

Once connected, you'll see:
* `captures/`: These are images saved when logging objects.  They are named with the observation ID from the database.
* `obslists/`: This folder holds observing saved during a PiFinder session or to load for future sessions.
* `screenshots/`:  It's possible to take screenshots while using the PiFinder (hold down _ENT_ and press _0_).  They are stored here.
* `solver_debug_dumps/`: If enabled, information about solver performance is stored here as a collection of images and json files.
* `observations.db`: This is the SQLite database which holds all the logged observations.


### Shutdown and Restart

Although shutting down is not strictly needed before power-off, the PiFinder is a computer and there is a chance of file corruption.  Some MicroSD cards are more sensitive to this than others.

Shutdown and Restart actions are available from the [Options](user_guide_ui.md#options) for the [Status](user_guide_ui.md#status) screen.  Hold down _Ent_ and press _A_ to cycle through the system screens until you see the status screen, the press and hold _A_ to access the options.

Restarting the PiFinder software should not normally be needed, but can be useful for generating a new session id which is included for a photos and logging during a particular execution of the PiFinder software.

### Observing lists
PiFinder maintains two lists of objects for each observing session; The History list and the Observing list.  The [Locate](user_guide_ui.md#locate) screen lets you scroll through these lists and push the telescope to any object on them.

The History list will record any object that you set as a target to push-to.  It's added to as soon as you press the _ENT_ key on the catalog screen to select an object.  The main purpose of the History list is to let you scroll back through objects you have observed that session.

The Observing list is a list of objects that is populated from either a filtered catalog or a file on disk.  It's a list of objects you'd like to observe during a session.  

Both these lists start empty at the beginning of each session.  To populate an observing list you can push a filtered list of objects from the [Catalog](user_guide_ui.md#catalog) screen or use the [Options](user_guide_ui.md#options) page of the [Locate](user_guide_ui.md#locate) screen to load an observing list from disk.  The PiFinder supports .skylist file format used in SkySafari and adopted in many other applications as well.

### Update Software
##### v1.2.2 or greater
A Software action is available from the [Options](#options) for the [Status](#status) screen.  This will both show which version the PiFinder currently has installed and allow you to Upd the software if the PiFinder is connected to the internet.  You man need to switch [WiFi](#wifi) modes to Client if the device is in AP mode.

Select the option for 'Software' and then 'Upd'.  You should see a message that says 'Updating...' followed by 'Ok! Restarting'.  The PiFinder should restart and the new software version should be displayed when checking the [Options](#options) for the [Status](#status) screen

##### Pre v1.2.2
Prior to version 1.2.2 you'll need to SSH into the PiFinder to update the software.  Once connected to the PiFinder and logged in type:

```
cd PiFinder
git stash
git pull
```

This should update to the latest release and from then forward you'll be able to use the built-in software update system.


## FAQ

Have any questions?  Please send them through to me at [rich@brickbots.com](mailto:rich@brickbots.com) and I'll do my best to help and potentially add your question here.  Better yet, feel free to fork this repo and contribute via a pull request!