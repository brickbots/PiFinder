===========================
Connecting to Your PiFinder
===========================

The PiFinder doesn't need another device to do its job, but connecting your phone, tablet,
or computer opens up a lot: a web interface for remote control and configuration,
planetarium apps that follow your telescope, and direct access to your logged observations
and images.  This page covers how the PiFinder's WiFi works and each way to connect.

WiFi
==========================

Access Point and Client Mode
----------------------------------

The PiFinder can connect to an existing network in Client mode, or serve as a wireless
access point for other devices in Access Point (AP) mode.  Use the
:ref:`connectivity:web interface` or the :ref:`user_guide:status screen` to switch between
the two modes and see which is active.

In Access Point mode the PiFinder creates a network called PiFinderAP with no password, for
easy connection of phones, tablets, and other devices in the field.

To use Client mode, add the WiFi network you'd like the PiFinder to connect to using the
Web Interface, as described in :ref:`connectivity:connecting to a new wifi network`

PiFinder address
-----------------

In most cases you can reach the PiFinder at ``pifinder.local``.  On older computers, or
those without zeroconf networking, use the IP address shown on the
:ref:`Status<user_guide:status screen>` screen.  You can connect via:


* A web browser, for the :ref:`connectivity:web interface` — remote control, WiFi setup, and configuration changes
* SSH, for shell access (advanced users)
* SMB (Samba), to access saved images, logs, and observing lists
* LX200 protocol, to update a planetarium app such as :doc:`skysafari` with the telescope's position

Web Interface
==============

The PiFinder's web interface lets you:

* See the current PiFinder status
* Remote control the PiFinder via a virtual screen and keypad
* Change network settings and connect to new WiFi networks
* Add and edit your telescopes and eyepieces (see :doc:`equipment`)
* Back up and restore your observing logs, settings, and other data
* View and download your logged observations

To reach the web interface for the first time, make sure the PiFinder is in Access Point mode (see :ref:`user_guide:settings menu`) — the default for new PiFinders, to ease first-time setup.  From a phone, tablet, or computer, connect to the PiFinder's open wireless network, PiFinderAP (no password), then open your browser and visit:
``http://pifinder.local``


.. note::
   If you're connected to the PiFinderAP network and can't load the web interface at
   http://pifinder.local, try http://10.10.10.1 — some systems don't support the network
   features needed to resolve local computer names.

.. list-table::
   :width: 100%

   * - .. image:: images/user_guide/pf_web_home_fullnav.jpg

     - .. image:: images/user_guide/pf_web_home_hamburger.jpg

The home screen shows general PiFinder status and a live view of the screen.  Depending on
your screen size you'll see either a navigation bar along the top or a 'hamburger' menu in
the upper-left holding the same options on smaller screens.

The home screen needs no password, but most other functions do.  The web interface password
is the same as the ``pifinder`` user's; changing one changes the other.  The default for new
images and PiFinders is ``solveit``, and you can change it from the Tools option in the web
interface.

Connecting to a new WiFi network
---------------------------------

By default the PiFinder generates its own WiFi network, ``PiFinderAP``, that you connect to
in order to configure additional networks.  To have the PiFinder connect to an existing
WiFi network with Internet access, follow these steps:

1) Make sure the PiFinder is in Access Point mode
2) Connect your phone, tablet, or computer to the PiFinder's wifi network called PiFinderAP
3) Visit http://pifinder.local using your web browser
4) Click the 'Network' link in the top bar, or on a smaller screen click the three stacked horizontal lines in the upper-right corner and choose 'Network'.
    .. image:: images/user_guide/pf_web_net0.png
5) When prompted, enter the password for your PiFinder.  The default is `solveit`.
6) Scroll down to the 'Wifi Networks' section and click the + button to add a network
    .. image:: images/user_guide/pf_web_net1.jpg
7) Enter the name (SSID) and password of your network.  If your network has no password, leave the Password field blank.
8) Click the 'SAVE' button to save the new network
9)  The network you added should now appear in the 'Wifi Networks' section
10) Scroll up and change the Wifi mode from 'Access Point' to 'Client' so the PiFinder connects to your network on its next restart
11) Click the 'UPDATE AND RESTART' button

To add more WiFi networks, navigate to the Network Setup page of the :ref:`connectivity:web interface`, click the + button near the WiFi networks list, and repeat the steps above.

SkySafari and Planetarium Apps
==============================

The PiFinder can provide real-time pointing information to SkySafari and other planetarium
apps via the LX200 protocol, and accept targets they send back.  The :doc:`skysafari` page
has the connection settings and walks through the setup step by step.

Shared Data Access
===================

The PiFinder creates several data files you may want.  They're available via an SMB (samba)
network share, ``//pifinder.local/shared``.  Access depends on your OS, but the PiFinder
should appear in a network browser.  No password is required — connect as ``guest`` with no
password.

Once connected, you'll see:


* ``captures/``\ : Images saved when logging objects, named with the observation ID from the database.
* ``obslists/``\ : Observing lists saved during a session or kept for future sessions.
* ``screenshots/``\ : Screenshots taken while using the PiFinder (hold **SQUARE** and
  press **0**) are stored here.
* ``solver_debug_dumps/``\ : If enabled, solver performance information is stored here as a collection of images and json files.
* ``observations.db``\ : The SQLite database holding all logged observations.
