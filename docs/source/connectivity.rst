===========================
Connecting to Your PiFinder
===========================

The PiFinder works on its own.  Connect a phone, tablet, or computer and you get more: a web
interface for remote control and configuration, planetarium apps that follow your telescope,
and direct access to your logged observations and images.  This page covers how the
PiFinder's WiFi works and each way to connect.

WiFi
==========================

Access Point and Client Mode
----------------------------------

The PiFinder has two WiFi modes.  In Client mode it connects to an existing network.  In
Access Point (AP) mode it creates its own wireless network for your phone, tablet, or
computer.  Use the :ref:`connectivity:web interface` or the :ref:`user_guide:status screen`
to switch modes and to see which mode is active.

The access point is called PiFinderAP and has no password, so you can connect quickly in the
field.

To use Client mode, add the WiFi network you want the PiFinder to join.  Add it from the web
interface, as described in :ref:`connectivity:connecting to a new wifi network`.

PiFinder address
-----------------

In most cases you can reach the PiFinder at ``pifinder.local``.  On older computers, or
those without zeroconf networking, use the IP address shown on the
:ref:`Status<user_guide:status screen>` screen.  You can connect via:


* A web browser, for the :ref:`connectivity:web interface` (remote control, WiFi setup, and configuration changes)
* SSH, for shell access (advanced users)
* SMB (Samba), to access saved images, logs, and observing lists
* LX200 protocol, to update a planetarium app such as :doc:`skysafari` with the telescope's position

Web Interface
==============

The PiFinder's web interface lets you:

* See the PiFinder's current status
* Control the PiFinder remotely with a virtual screen and keypad
* Change network settings and connect to new WiFi networks
* Add and edit your telescopes and eyepieces (see :doc:`equipment`)
* Back up and restore your observing logs, settings, and other data
* View and download your logged observations
* Select or upload a logging configuration to capture detailed logs for a bug report

To reach the web interface for the first time, make sure the PiFinder is in Access Point
mode (see :ref:`user_guide:settings menu`).  New PiFinders start in this mode to make first
setup easy.  From a phone, tablet, or computer, connect to the PiFinder's open wireless
network, PiFinderAP (no password).  Then open your browser and visit:
``http://pifinder.local``


.. note::
   If you're connected to the PiFinderAP network and can't load the web interface at
   http://pifinder.local, try http://10.10.10.1 instead.  Some systems don't support the
   network features needed to resolve local computer names.

.. list-table::
   :width: 100%

   * - .. image:: images/user_guide/pf_web_home_fullnav.jpg

     - .. image:: images/user_guide/pf_web_home_hamburger.jpg

The home screen shows general PiFinder status and a live view of the PiFinder's screen.  On
a large screen you see a navigation bar along the top.  On a smaller screen the same options
sit under a 'hamburger' menu in the upper-left.

The home screen needs no password, but most other functions do.  The web interface password
is the same as the ``pifinder`` user's password.  If you change one, you change the other.
The default for new images and PiFinders is ``solveit``.  You can change it from the Tools
page of the web interface.

The web interface is available in English, German, French, Spanish, and Chinese.  It follows your
browser's preferred language.  Set the language on your phone or computer, and the web
interface matches it.

Connecting to a new WiFi network
---------------------------------

By default the PiFinder creates its own WiFi network, ``PiFinderAP``.  Connect to it to
configure additional networks.  To connect the PiFinder to an existing WiFi network with
Internet access, follow these steps:

1) Make sure the PiFinder is in Access Point mode
2) Connect your phone, tablet, or computer to the PiFinder's WiFi network called PiFinderAP
3) Open http://pifinder.local in your web browser
4) Click the 'Network Setup' link in the top bar.  On a smaller screen, click the three stacked horizontal lines in the upper-left corner and select 'Network Setup'.
    .. image:: images/user_guide/pf_web_net0.png
5) When prompted, enter the password for your PiFinder.  The default is ``solveit``.
6) Scroll down to the 'Wifi Networks' section and click the + button to add a network
    .. image:: images/user_guide/pf_web_net1.jpg
7) Enter the name (SSID) and password of your network.  If your network has no password, leave the Password field blank.
8) Click the 'SAVE' button to save the new network
9)  The network you added now appears in the 'Wifi Networks' section
10) Scroll up and change the Wifi mode from 'Access Point' to 'Client' so the PiFinder connects to your network on its next restart
11) Click the 'UPDATE AND RESTART' button

To add more WiFi networks, open the Network Setup page of the
:ref:`connectivity:web interface`, click the + button near the WiFi networks list, and
repeat the steps above.

Logging configuration
---------------------

When you're tracking down a problem, the Logs page of the web interface can turn up the
detail the PiFinder records.  Select one of the built-in configurations (default, debug, or
webserver), or upload your own.  The PiFinder restarts with the new configuration in place.
The richer logs make it much easier to capture what happened for a bug report.  Switch back
to default when you're done.

SkySafari and Planetarium Apps
==============================

The PiFinder can send real-time pointing information to SkySafari and other planetarium apps
over the LX200 protocol.  It also accepts the objects those apps send back.  The
:doc:`skysafari` page has the connection settings and takes you through the setup step by
step.

Shared Data Access
===================

The PiFinder creates several data files you may want.  It shares them over SMB (samba) at
``//pifinder.local/shared``.  Access depends on your operating system, but the PiFinder
should appear in a network browser.  The share needs no password.  Connect as ``guest`` and
leave the password blank.

Once connected, you see:


* ``captures/``\ : The images the PiFinder saves when you log an object.  Each name contains the observation ID from the database.
* ``obslists/``\ : Observing lists.  Copy list files here (subfolders welcome) to load
  them at the telescope.  See :ref:`user_guide:observing lists`.
* ``screenshots/``\ : Screenshots you take while using the PiFinder.  Hold **SQUARE** and
  press **0** to take one.
* ``solver_debug_dumps/``\ : Solver performance information, as a collection of images and json files, if you turn it on.
* ``observations.db``\ : The SQLite database holding all logged observations.
