
PiFinder™ Menu Map
==================

.. note::
   This map reflects rev4, v3 and v2.5 PiFinders running software |min_software| or above.  The
   exact items you see can vary slightly with your configuration and software
   version.

The menu system controls everything the PiFinder does.  This page is a
bird's-eye view of that system: a diagram of each branch, with a short note on
what every menu item does.  See :ref:`user_guide:the menu system` for how to
scroll and select, and for the Quick Menu that brings common actions into
easier reach.

The top level has six sections:

.. mermaid::

   flowchart LR
       PF([PiFinder]) --> Start
       PF --> Chart
       PF --> Objects
       PF --> SQM
       PF --> Settings
       PF --> Tools

- **Start** gets you ready for the night: focus, align, and check your GPS fix.
- **Chart** draws a live star chart of where the telescope points.
- **Objects** is where you choose what to look at: catalogs, recent objects,
  search, and the filters that narrow your lists.
- **SQM** is a Sky Quality Meter.  It estimates how dark your sky is from the
  camera.
- **Settings** configures the interface, chart, camera, WiFi, and hardware.
- **Tools** holds status, equipment, location and time, updates, and power.


Start
-----

.. mermaid::

   flowchart LR
       Start --> Focus
       Start --> Align
       Start --> AlignDay["Align (Day)"]
       Start --> GPS["GPS Status"]

Focus
   Magnified views of the four brightest stars the camera sees, with an **HFD**
   readout of how spread-out they are.  Adjust focus until the number is as low
   as it will go.  Sharp stars let the PiFinder solve.  Press **SQUARE** to
   cycle the Stars, Single, Image, and Stats views.  The screen holds the camera
   exposure steady while it is open, so only the lens changes what you see.
   Press **UP** and **DOWN** to step the exposure.  A bar along the bottom
   shows the held exposure and the keys that change it.  Nothing you set here
   is saved.  Your previous exposure setting returns when you leave.  To set an
   exposure the PiFinder keeps, select Camera Exp in the Settings menu.
Align
   Align the PiFinder to your eyepiece.  Center a known star and confirm.  Your
   Push-To distances then account for any offset between the camera and where
   you're actually looking.
Align (Day)
   Set the same eyepiece alignment in daylight by marking where a distant
   eyepiece-centered object appears in the camera image.
GPS Status
   The current GPS fix: satellites in view, lock state, and the location and
   time the PiFinder acquired.  You can also reach this screen from Tools,
   under Place & Time.


Chart
-----

Chart
   A star chart centered on where your telescope points, redrawn as you move.
   Press **+** and **-** to zoom.  Set its appearance under Chart in the
   Settings menu: reticle, constellation lines, deep-sky markers, coordinate
   readout, and center object.


Objects
-------

The Objects menu is where you choose what to look at.  Every list here, apart
from Name Search and Recent, shows only objects that meet your current
:ref:`filter criteria <user_guide:filters>`.  See :ref:`user_guide:object list`
for how the lists work.

.. mermaid::

   flowchart LR
       Objects --> AF["All Filtered"]
       Objects --> BC["By Catalog"]
       Objects --> Recent
       Objects --> OL["Obs Lists"]
       Objects --> Custom
       Objects --> NS["Name Search"]
       Objects --> SF["Set Filters"]
       BC --> Planets
       BC --> Comets
       BC --> NGC
       BC --> Messier
       BC --> DSO["DSO... (14 catalogs)"]
       BC --> Stars["Stars... (7 catalogs)"]
       SF --> RA["Reset All"]
       SF --> Cat["Catalogs"]
       SF --> Type
       SF --> Alt["Altitude"]
       SF --> Mag["Magnitude"]
       SF --> Obs["Observed"]

All Filtered
   Every object, across all catalogs, that meets your current filters.  With
   loose filters this can be many thousands of objects, so it's most useful once
   you've set strict filters.
By Catalog
   View one catalog at a time, still narrowed by your filters.  Common catalogs
   sit at the top.  The rest are grouped under DSO... and Stars....  See
   :doc:`catalogs` for what each catalog contains.

   Planets
      The major solar-system planets.
   Comets
      The comets the PiFinder currently tracks.
   NGC
      The New General Catalogue.
   Messier
      The 110 Messier objects.
   DSO...
      Less-common deep-sky catalogs: Abell planetary nebulae, Arp peculiar
      galaxies, Barnard dark nebulae, Caldwell, Collinder open clusters,
      extragalactic globulars, Harris globulars, Herschel 400, IC, Lyngå open
      clusters, Messier, NGC, Sharpless emission nebulae, and the TAAS 200 list.
   Stars...
      Star catalogs: bright named stars, the SAC double, asterism and red-star
      lists, RASC and WDS doubles, and TLK's hand-picked variable stars.
Recent
   The objects you've viewed this session, most recent first.  It starts empty
   each session.
Obs Lists
   Load an observing list file you've copied to the PiFinder, in SkySafari,
   CSV, or one of several other formats.
   See :ref:`user_guide:observing lists`.
Custom
   Enter a right ascension and declination by hand to make a one-off Custom
   Target you can push to.  See :ref:`user_guide:custom targets`.
Name Search
   Find objects by common name, using multi-tap or T9 text entry on the keypad.
   See :ref:`user_guide:name search`.
Set Filters
   Narrow which objects appear in your lists.  These settings feed every list
   above except Name Search and Recent.  See :ref:`user_guide:filters` for the
   full picture.

   Reset All
      Clear every filter back to its default.  Select Confirm to apply, or
      Cancel to go back.
   Catalogs
      Select which catalogs feed the All Filtered list.  You can select more
      than one.  The grouping matches By Catalog: Planets, Comets, NGC,
      Messier, DSO..., and Stars....
   Type
      Limit by object type: galaxy, open cluster, cluster with nebulosity,
      globular, nebula, planetary nebula, dark nebula, star, double and triple
      stars, knot, asterism, planet, comet, and unknown.  You can select more
      than one.
   Altitude
      Hide objects below a minimum altitude above your horizon.  Values: None,
      0, 10, 20, 30, 40 degrees.
   Magnitude
      Hide objects fainter than the limit you select.  Values: None, 6 through
      15.
   Observed
      Limit the list by whether you have observed an object.  Values: Any,
      Observed, Not Observed.  This helps when you work through an observing
      project.


SQM
---

SQM
   A Sky Quality Meter that estimates how dark your sky is.  The PiFinder
   reports the estimate in magnitudes per square arcsecond.  Higher numbers
   mean darker skies: roughly 21–22 at a dark site, 18–19 in the suburbs, and
   16–17 under city lights.  The PiFinder measures the sky from its own camera,
   not from a separate hardware meter.  It does not need a plate solve to do
   this, so the reading keeps updating through cloud and star-poor frames.  See
   :doc:`sqm` for how to read the screen and when to calibrate.


Settings
--------

The Settings menu holds every user-configurable item.  See
:ref:`user_guide:settings menu` for more.

.. mermaid::

   flowchart LR
       Settings --> UP["User Pref..."]
       Settings --> CH["Chart..."]
       Settings --> IM["Image..."]
       Settings --> CE["Camera Exp"]
       Settings --> WM["WiFi Mode"]
       Settings --> MT["Mount Type"]
       Settings --> ADV["Advanced"]
       Settings --> IMU["IMU Sensit."]
       ADV --> PFT["PiFinder Type"]
       ADV --> CT["Camera Type"]
       ADV --> GPS["GPS Settings"]
       GPS --> GT["GPS Type"]
       GPS --> GB["GPS Baud Rate"]

User Pref...
   Day-to-day interface preferences.

   Key Bright
      Keypad backlight level.  Values: -4 (dimmest) to +3.
   Volume
      How loud the PiFinder's sounds are.  Values: Off, 1 (quietest) to 5.
      Selecting a level plays a sample tone at that level.  Only rev4 PiFinders
      have the buzzer.  See :ref:`user_guide:sounds`.
   Sleep Time
      How long the PiFinder waits before power-save dims the screen.  Values:
      Off, 10s to 2m.  Only key presses reset the timer.  Moving the PiFinder
      wakes it from sleep but does not keep it awake.
   Menu Anim
      Menu scrolling animation speed.  Values: Off, Fast, Medium, Slow.
   Scroll Speed
      How fast long lines of text scroll.  Values: Off, Fast, Medium, Slow.
   Search Input
      How Name Search reads the keypad.  Values: Multi-Tap (cycle through each
      key's letters), T9 (one press per letter).
   Az Arrows
      Direction of the azimuth Push-To arrows.  Values: Default, Reverse.  Set
      this to match how you read the arrows at the telescope.
   Language
      Interface language.  Values: English, German, French, Spanish, Chinese.
Chart...
   How the Chart screen draws the sky.

   Coordinate Sys.
      Chart orientation.  Values: Horizontal, EQ (Auto), EQ (North-up),
      EQ (South-up).
   Reticle
      Brightness of the center reticle.  Values: Off, Low, Medium, High.
   Constellation
      Brightness of constellation lines.  Values: Off, Low, Medium, High.
   DSO Display
      Brightness of deep-sky object markers.  Values: Off, Low, Medium, High.
   RA/DEC Disp.
      Show a coordinate readout.  Values: Off, HH:MM, Degrees.
   Center Object
      Name the object nearest the middle of the chart, on a line along the
      bottom.  Values: Off, On (the default).  Press **RIGHT** on the chart to
      open that object's details.
Image...
   Overlays on the :ref:`object image <user_guide:object images>`.

   NSEW Labels
      Mark the cardinal directions at the edge of the image.  Values: On, Off.
   Object Size
      Outline the object's cataloged size and orientation.  Values: On, Off.
Camera Exp
   Camera exposure time.  Values: Auto (the default), or a fixed time from
   0.025s to 1s.  On Auto the PiFinder adjusts the exposure itself from the
   results of each plate solve.  Longer fixed exposures catch fainter stars,
   but they blur sooner as the telescope moves.
WiFi Mode
   Switch between Client Mode (join an existing network) and AP Mode (the
   PiFinder serves its own PiFinderAP network).  See :ref:`connectivity:wifi`.
Mount Type
   Tell the PiFinder whether your telescope is Alt/Az or Equatorial.  Changing
   this restarts the PiFinder.
Advanced
   Hardware setup that you normally configure once on a DIY build.  Opening it
   shows a brief "Options for DIY PiFinders" reminder, because on a fully built
   PiFinder these already match your hardware.

   PiFinder Type
      Which physical configuration you have.  Values: Left, Right, Straight,
      Flat v3, Flat v2, AS Bloom, AS Heart, Rev4 Left, Rev4 Right,
      Rev4 Straight.  Changing this restarts the PiFinder.
   Camera Type
      Which camera sensor your PiFinder has.
      Values: v2 - imx477, v3 - imx296, v3 - imx462.  A rev4 PiFinder takes
      v3 - imx462.  There is no separate rev4 entry, and that one is correct.
   Lens
      Which lens is fitted in front of the camera.  Values: 12mm, 16mm, 25mm.
      The focal length is printed on the lens barrel.  The PiFinder cannot
      detect the lens, so this is you telling it what is fitted — and naming
      the wrong one stops solving completely rather than making it worse, so
      check the barrel before you change it.  Changing this restarts the
      PiFinder.
   GPS Settings
      Configure the GPS receiver.

      GPS Type
         Values: UBlox (the built-in receiver), GPSD (for a generic receiver).
         Changing this restarts the PiFinder.
      GPS Baud Rate
         Serial speed for the receiver.  rev4 PiFinders carry a 10th-generation
         UBlox receiver and run at 115200.  The older receiver in v3 and v2.5
         PiFinders runs at 9600.
IMU Sensit.
   How readily telescope motion switches pointing from a camera solve to the
   motion-sensor estimate.  Values: Off (ignore the sensor), Very Low, Low,
   Medium, High.  Changing this restarts the PiFinder.


Tools
-----

The Tools menu collects screens that aren't about observing but give useful
information or perform actions.  See :ref:`user_guide:tools`.

.. mermaid::

   flowchart LR
       Tools --> Status
       Tools --> Equipment
       Tools --> PnT["Place & Time"]
       Tools --> Console
       Tools --> SU["Software Upd"]
       Tools --> TM["Test Mode"]
       Tools --> Exp["Experimental"]
       Tools --> Power
       PnT --> G2["GPS Status"]
       PnT --> SL["Set Location"]
       PnT --> STD["Set Time/Date"]
       PnT --> RL["Reset Location"]
       PnT --> RTD["Reset Time/Date"]
       SL --> EC["Enter Coords"]
       SL --> LL["Load Location"]
       SL --> SV["Save Location"]
       Exp --> PA["Polar Align"]
       Exp --> DT["Dev Tools"]
       DT --> Tel["Telemetry"]
       Power --> Shutdown
       Power --> Restart

Status
   The PiFinder's current state: solver status, WiFi mode and address, GPS, and
   more.  See :ref:`user_guide:status screen`.
Equipment
   Select your active telescope and eyepiece.  The screen shows the resulting
   magnification and field of view.  See :doc:`equipment`.
Place & Time
   Manage your observing location and the clock.

   GPS Status
      The current GPS fix (the same screen as Start, GPS Status).
   Set Location
      Set your observing location.

      Enter Coords
         Type your latitude and longitude by hand.
      Load Location
         Select one of your saved locations.
      Save Location
         Save the current location to recall later.
   Set Time/Date
      Set the clock by hand when there's no GPS fix.
   Reset Location
      Discard the current location.
   Reset Time/Date
      Discard the current time and date.
Console
   A running log of messages from the PiFinder's subsystems.  Use it when you
   troubleshoot.
Software Upd
   Download and install software updates over WiFi.  See
   :ref:`user_guide:update software`.
Test Mode
   A demo/debug mode that solves a saved image from disk.  It blocks real use at
   night but lets you explore the PiFinder's features indoors.
Experimental
   Features still under development.

   Polar Align
      For equatorial platforms: capture two or three solves while rotating the
      platform, then use the platform's altitude and azimuth adjusters until the
      displayed correction reaches zero.  See
      :ref:`user_guide:polar alignment`.
   Dev Tools
      Developer instrumentation.

      Telemetry
         Record the IMU and plate solve data from a session, optionally
         including camera Images.  Load a saved recording to replay it.  This
         is intended for diagnosing and developing the PiFinder.
Power
   Shut down or restart the PiFinder.

   Shutdown
      Shut the PiFinder down cleanly (Confirm or Cancel).  See
      :ref:`user_guide:shutdown`.
   Restart
      Restart the PiFinder (Confirm or Cancel).
