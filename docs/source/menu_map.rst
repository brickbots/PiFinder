
PiFinder™ Menu Map
==================

.. note::
   This map reflects v3 and v2.5 PiFinders running software |min_software| or above.  The
   exact items you see can vary slightly with your configuration and software
   version.

Everything the PiFinder does is reached through its menu system.  This page is a
bird's-eye view of that system: a diagram of each branch, with a short note on
what every option does.  For how to scroll and select — and for the Quick Menu
that brings common actions into easier reach — see
:ref:`user_guide:the menu system`.

The top level has six sections:

.. mermaid::

   flowchart LR
       PF([PiFinder]) --> Start
       PF --> Chart
       PF --> Objects
       PF --> SQM
       PF --> Settings
       PF --> Tools

- **Start** — Get set up for the night: focus, align, and check your GPS fix.
- **Chart** — A live star chart of where the scope is pointing.
- **Objects** — Choose what to look at: catalogs, recent objects, search, and
  the filters that narrow your lists.
- **SQM** — A Sky Quality Meter that estimates how dark your sky is from the
  camera.
- **Settings** — Configure the interface, chart, camera, WiFi, and hardware.
- **Tools** — Status, equipment, location and time, updates, and power.


Start
-----

.. mermaid::

   flowchart LR
       Start --> Focus
       Start --> Align
       Start --> AlignDay["Align (Day)"]
       Start --> GPS["GPS Status"]

Focus
   A live camera view for focusing the lens.  Adjust focus until stars are as
   small and sharp as possible — sharp stars are what let the PiFinder solve.
   The Quick Menu here adjusts the camera Exposure.
Align
   Align the PiFinder to your eyepiece.  Center a known star, confirm, and your
   Push-To distances then account for any offset between the camera and where
   you're actually looking.
Align (Day)
   Set the same eyepiece alignment in daylight by marking where a distant
   eyepiece-centered object appears in the camera image.
GPS Status
   The current GPS fix: satellites in view, lock state, and the location and
   time the PiFinder has acquired.  (Also reachable from Tools, under Place &
   Time.)


Chart
-----

Chart
   A star chart centered on where your telescope is pointing, redrawn as you
   move.  Zoom with the **+** / **-** keys.  Its appearance — reticle,
   constellation lines, deep-sky markers, and coordinate readout — is set under
   the Settings menu's Chart options.


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
   Browse one catalog at a time (still narrowed by your filters).  Common
   catalogs sit at the top; the rest are grouped under DSO... and Stars....  For
   what each catalog contains, see :doc:`catalogs`.

   Planets
      The major solar-system planets.
   Comets
      Comets currently tracked by the PiFinder.
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
   Load an observing list file you've copied to the PiFinder — SkySafari,
   CSV, and several other formats.  See :ref:`user_guide:observing lists`.
Custom
   Enter a right ascension and declination by hand to make a one-off target you
   can push to.  See :ref:`user_guide:custom targets`.
Name Search
   Find objects by common name using the keypad — multi-tap or T9 text entry.
   See :ref:`user_guide:name search`.
Set Filters
   Narrow which objects appear in your lists.  These settings feed every list
   above except Name Search and Recent.  See :ref:`user_guide:filters` for the
   full picture.

   Reset All
      Clear every filter back to its default.  Choose Confirm to apply, or
      Cancel to back out.
   Catalogs
      Choose which catalogs feed the All Filtered list — multi-select, using the
      same grouping (Planets, Comets, NGC, Messier, DSO..., Stars...) as By
      Catalog.
   Type
      Limit by object type: galaxy, open cluster, cluster with nebulosity,
      globular, nebula, planetary nebula, dark nebula, star, double and triple
      stars, knot, asterism, planet, comet, and unknown.  Multi-select.
   Altitude
      Hide objects below a minimum altitude above your horizon — None, or 0, 10,
      20, 30, or 40 degrees.
   Magnitude
      Hide objects fainter than the limit you pick — None, or 6 through 15.
   Observed
      Show Any object, only those you've Observed, or only those Not Observed —
      handy for working through an observing project.


SQM
---

SQM
   A Sky Quality Meter that estimates how dark your sky is, reported in
   magnitudes per square arcsecond — higher numbers mean darker skies (roughly
   21–22 at a dark site, 18–19 in the suburbs, 16–17 under city lights).  The
   reading is a photometric measurement from a plate-solved camera frame, not a
   separate hardware meter, so a recent solve gives the most reliable value.


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
      Keypad backlight level, from -4 (dimmest) to +3.
   Sleep Time
      How long the PiFinder waits before power-save dims the screen — Off, or
      10s up to 2m.
   Menu Anim
      Menu scrolling animation speed — Off, Fast, Medium, or Slow.
   Scroll Speed
      How fast long lines of text scroll — Off, Fast, Medium, or Slow.
   Search Input
      How Name Search reads the keypad — Multi-Tap (cycle through each key's
      letters) or T9 (one press per letter).
   Az Arrows
      Direction of the azimuth Push-To arrows — Default or Reverse, to match how
      you read them at the scope.
   Language
      Interface language: English, German, French, Spanish, or Chinese.
Chart...
   How the Chart screen draws the sky.

   Coordinate Sys.
      Chart orientation — Horizontal, or equatorial with automatic, north-up, or
      south-up rotation.
   Reticle
      Brightness of the center reticle — Off, Low, Medium, or High.
   Constellation
      Brightness of constellation lines — Off, Low, Medium, or High.
   DSO Display
      Brightness of deep-sky object markers — Off, Low, Medium, or High.
   RA/DEC Disp.
      Show a coordinate readout — Off, HH:MM, or Degrees.
Image...
   Overlays on the :ref:`object image <user_guide:object images>`.

   NSEW Labels
      Mark the cardinal directions at the edge of the image — On or Off.
   Object Size
      Outline the object's cataloged size and orientation — On or Off.
Camera Exp
   Camera exposure time — Auto (the default), or a fixed value from 0.025s to
   1s.  On Auto the PiFinder adjusts the exposure itself from the plate-solve
   results.  Longer fixed exposures catch fainter stars but blur sooner as the
   scope moves.
WiFi Mode
   Switch between Client Mode (join an existing network) and AP Mode (the
   PiFinder serves its own PiFinderAP network).  See :ref:`connectivity:wifi`.
Mount Type
   Tell the PiFinder whether your scope is Alt/Az or Equatorial.  Changing this
   restarts the PiFinder.
Advanced
   Hardware setup normally configured once on a DIY build; opening it shows a
   brief "Options for DIY PiFinders" reminder, since on a fully built unit these
   already match your hardware.

   PiFinder Type
      Which physical configuration you have — Left, Right, Straight, Flat v3,
      Flat v2, AS Bloom, AS Heart, Rev4 Left, Rev4 Right, or Rev4 Straight.
      Restarts the PiFinder.
   Camera Type
      Which camera sensor is fitted — v2 (imx477), v3 (imx296), or v3 (imx462).
   GPS Settings
      Configure the GPS receiver.

      GPS Type
         UBlox (the built-in receiver) or GPSD for a generic receiver.  Restarts
         the PiFinder.
      GPS Baud Rate
         Serial speed for the receiver — 9600 (standard) or 115200 (UBlox-10).
IMU Sensit.
   How readily scope motion switches pointing from a camera solve to the
   motion-sensor estimate — Off (ignore the sensor), Very Low, Low, Medium, or
   High.  Changing this restarts the PiFinder.


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
   The PiFinder's current state — solver status, WiFi mode and address, GPS, and
   more.  See :ref:`user_guide:status screen`.
Equipment
   Pick your active telescope and eyepiece and see the resulting magnification
   and field of view.  See :doc:`equipment`.
Place & Time
   Manage your observing location and the clock.

   GPS Status
      The current GPS fix (the same screen as Start, GPS Status).
   Set Location
      Set your observing location.

      Enter Coords
         Type your latitude and longitude by hand.
      Load Location
         Choose one of your saved locations.
      Save Location
         Save the current location to recall later.
   Set Time/Date
      Set the clock by hand when there's no GPS fix.
   Reset Location
      Discard the current location.
   Reset Time/Date
      Discard the current time and date.
Console
   A running log of messages from the PiFinder's subsystems — useful when
   troubleshooting.
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
         Record a session's IMU and plate-solve data — optionally including
         camera Images — then Load a saved recording to replay it.  Intended for
         diagnosing and developing the PiFinder.
Power
   Shut down or restart the PiFinder.

   Shutdown
      Cleanly power down (Confirm or Cancel).  See :ref:`user_guide:shutdown`.
   Restart
      Reboot the PiFinder (Confirm or Cancel).
