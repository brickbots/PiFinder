
====================
PiFinder User Manual
====================

.. note::
   This documentation is a work in progress for v3 and v2.5 PiFinders running software 2.0.0 or above.
   If you need docs for a previous version please `Click here <https://pifinder.readthedocs.io/en/v1.11.2/index.html>`_

Thanks for your interest in the PiFinder!  This guide describes how to use a PiFinder but if you want information on building one, please see the :doc:`Build Guide <build_guide>` and the :doc:`Bill of Materials <BOM>`.

This user manual is divided into several sections which you can access using the links to the left.  Now, let's dig deeper into the various functions of the PiFinder!

How It Works
===============

The PiFinder is a self-contained telescope positioning device.  It will let you know where your telescope is pointed, provide the ability to choose a particular target (like a Galaxy or other DSO) and direct you on how to move your telescope to find that object.  There are some other nice features along with these core functions, but the PiFinder is designed primarily as a way to get interesting objects into your eyepiece so you can take a look at them.

In order to direct you to wonders of the night sky, the PiFinder needs to know where your telescope is currently pointed.  The primary way it does this is directly, but taking photos of the night sky and examining the star patterns to determine what section of the sky it's seeing.  It can do this incredibly fast (up to two times per second!) and very accurately.  This only works well if your telescope is not moving, so it couples this very accurate system with an accelerometer to provide an estimate of how far your telescope has moved from the last known position.  This estimate will contain some error, but as soon as you stop moving the scope a new photo will be taken and any inaccuracty will be corrected.

Along with knowing where your telescope is pointing, the PiFinder knows where thousands of interesting objects are located. It can use these two pieces of information to indicate how you should move your telescope to bring any of those thousands of objects into your eyepiece.  Since it's directly observing where your telescope is pointing, you can be assured you are on target!

.. note::
   This documentation is a work in progress for v3 and v2.5 PiFinders running software 2.0.0 or above.
   If you need docs for a previous version please `Click here <https://pifinder.readthedocs.io/en/v1.11.2/index.html>`_


Observing Screens
=====================================

.. note::
   This documentation is a work in progress for v3 and v2.5 PiFinders running software 2.0.0 or above.
   If you need docs for a previous version please `Click here <https://pifinder.readthedocs.io/en/v1.11.2/index.html>`_



Settings Menu
----------------
.. note::
   This documentation is a work in progress for v3 and v2.5 PiFinders running software 2.0.0 or above.
   If you need docs for a previous version please `Click here <https://pifinder.readthedocs.io/en/v1.11.2/index.html>`_



Catalog
======================

.. note::
   This documentation is a work in progress for v3 and v2.5 PiFinders running software 2.0.0 or above.
   If you need docs for a previous version please `Click here <https://pifinder.readthedocs.io/en/v1.11.2/index.html>`_

Object Images
---------------

If you have used the prebuilt PiFinder image or have :ref:`downloaded<software:catalog image download>` the set of catalog images you can view what the selected object looks like via images from sky surveys.  Pressing the **B** key will cycle through various pages of information about each object including images from the Palomar Observatory Sky Survey and potentially updated images from the Sloan Digital Sky Survey.   

As an example, here are the images available for M57


.. image:: ../../images/screenshots/CATALOG_images_001_docs.png
   :target: ../../images/screenshots/CATALOG_images_001_docs.png
   :alt: Catalog Image


.. image:: ../../images/screenshots/CATALOG_images_002_docs.png
   :target: ../../images/screenshots/CATALOG_images_002_docs.png
   :alt: Catalog Image


.. image:: ../../images/screenshots/CATALOG_images_003_docs.png
   :target: ../../images/screenshots/CATALOG_images_003_docs.png
   :alt: Catalog Image


These images are oriented as they would be through the eyepiece in a newtonian reflector pointing at a specific area of the sky from your current location.   You can use the **+** and **-** keys to switch between several eyepiece field of view: 1, 0.5, 0.25, 0.12 degrees

The bottom left of the screen shows the source of the current image and the left side shows the current FOV information.


Observing Lists
======================

.. note::
   This documentation is a work in progress for v3 and v2.5 PiFinders running software 2.0.0 or above.
   If you need docs for a previous version please `Click here <https://pifinder.readthedocs.io/en/v1.11.2/index.html>`_

Logging Observations
======================

.. note::
   This documentation is a work in progress for v3 and v2.5 PiFinders running software 2.0.0 or above.
   If you need docs for a previous version please `Click here <https://pifinder.readthedocs.io/en/v1.11.2/index.html>`_


* Transp. :  The transparency of the sky.  This is often noted along with Seeing below
* Seeing:  The stillness of the atmosphere. 
* Eyepiece:  You can note which of your eyepieces you are using.
* Obsabillit:  Observability - How easy is it to spot and recognize this object
* Appeal: Overall rating of this object.. would you refer a friend?


Observing Projects
===================
.. note::
   This documentation is a work in progress for v3 and v2.5 PiFinders running software 2.0.0 or above.
   If you need docs for a previous version please `Click here <https://pifinder.readthedocs.io/en/v1.11.2/index.html>`_

If you are like me, you may enjoy various observing projects, such as observing all the Messier or Herschel objects.  The PiFinder makes these longer term efforts easy by allowing you to log each object and then only showing you objects you have left that are visible during any observing session!

This section covers a lot of the basic catalog/locating/observing features of the PiFinder and how it can be used to pursue such a project.

Combining the ability to filter a catalog by observation status and pushing the nearest 'X' objects to the observing list allows you to work your way through a collection of objects easily.


WiFi
==========================

Access Point and Client Mode
----------------------------------

The PiFinder can either connect to an existing network via the Client mode, or serve as an wireless access point for other devices to connect to via the Access Point (AP) mode.  Use the :ref:`user_guide:Web Interface` or the :ref:`user_guide:settings menu` page of the Status screen to switch between these two modes and to see which mode is currently active.

Using the PiFinder in Access Point mode creates a network called PiFinderAP with no password to allow easy connection of phones, tablets and other devices in the field.

To use the Client mode, you'll need to add information about the WiFi network you'd like the PiFinder to connect to using the Web Interface as described in :ref:`user_guide:connecting to a new wifi network`

PiFinder address
-----------------

In most cases, you can use the name ``pifinder.local`` to connect to the PiFinder.  On older computers or those that don't support zeroconf networking, you can use the IP address provides on the :ref:`Global Options<user_guide:settings menu>` screen to connect.  You can connect to the PiFinder via:


* A web browser to use the :ref:`user_guide:Web Interface` for remote control, setting up access to other WiFi networks and for configuration changes
* SSH to get shell access for advanced users
* SMB (Samba) to access saved images, logs an observing lists
* LX200 protocol to allow updating of a planetarium app, such as :doc:`skysafari` , with the position of the telescope

Web Interface
==============

The PiFinder provides an easy to use web interface which allows you to:

* See the current PiFinder status
* Remote control the PiFinder via a virtural screen and keypad
* Change network settings and connect to new WiFi networks
* Backup and restore your observing logs, settings and other data
* View and download your logged observations

To access the web interface for the first time, make sure the PiFinder is in Access Point mode (see :ref:`user_guide:settings menu`).  This is the default for new PiFinders to make first time set up easier.  Using a phone, tablet or computer, connect to the PiFinder's wireless network called PiFinderAP.  It's an open network with no password required.  Once connected, open your web browser and visit:
``http://pifinder.local``

.. list-table::
   :width: 100%

   * - .. image:: images/user_guide/pf_web_home_fullnav.jpg

     - .. image:: images/user_guide/pf_web_home_hamburger.jpg

The home screen shows the general PiFinder status info and a live view of the screen.  Depending on your screen size you'll either see a navigation bar along the top of the page, or a 'hamburger' menu in the upper-left which contains these same options for smaller screens.

While the home screen not require a password, most other functions will.  The password for the web interface is the same as what is used for the ``pifinder`` user and changing one will change the other.  The default password for new images and PiFinders is ``solveit``.  This can be changed using the Tools option in the web interface.

Connecting to a new WiFi network
---------------------------------

The default behavior of the PiFinder is to generate it's own WiFi network call ``PiFinderAP`` that you can connect to 
and configure additional networks. To get the PiFinder to connect to an existing WiFi network with Internet access you
can follow the steps below:

1) Make sure the PiFinder is in Access Point mode
2) Connect your phone, tablet, or computer to the PiFinder's wifi network called PiFinderAP
3) Visit http://pifinder.local using your web browser
4) Click the 'Network' link in the top bar, or if you have a smaller screen, click the three stacked horizontal lines in the upper-right corner to access the menu and choose 'Network' from there.
    .. image:: images/user_guide/pf_web_net0.png
5) When prompted enter the password for your PiFinder.  The default is `solveit`.
6) Scroll down until you see the 'Wifi Networks' section and click the + button to add a new network
    .. image:: images/user_guide/pf_web_net1.jpg
7) Enter the name (SSID) of your network and the password in the form.  If your network does not have a password, leave the Password field blank.
8) Click the 'SAVE' button to save the new network
9)  You should now see the network you added in the 'Wifi Networks' section of the page
10) Scroll up and change the Wifi mode from 'Access Point' to 'Client' so that the PiFinder will attempt to connect to your network next time it restarts
11) Click the 'UPDATE AND RESTART' button

To add more WiFi networks for the PiFinder to look for, navigate to the Network Setup page of the :ref:`user_guide:web interface` and click the + button near the list of WiFi networks and repeat the steps above.


SkySafari
===================

The PiFinder can provide real-time pointing information to a device running SkySafari via the LX200 protocol.  See this :doc:`skysafari` document for complete details, but here is the connection info:


* Use 'Other' telescope type
* Mount Type: Alt-Az, GoTo.. even if your scope is Push-To.  This allows sending of targets from SkySafari to the PiFinder
* Scope Type: Meade LX200 classic
* IP Address: ``pifinder.local`` or IP address provides on the Status screen
* Port: 4030

Shared Data Access
===================

In the course of using the PiFinder several data files are created that may be of interest.  These are available via a SMB (samba) network share called ``//pifinder.local/shared``.  Accessing this will depend on your OS, but the PiFinder should be visible in a network browser provided.  There is no password requirement, just connect as ``guest`` with no password provided.

Once connected, you'll see:


* ``captures/``\ : These are images saved when logging objects.  They are named with the observation ID from the database.
* ``obslists/``\ : This folder holds observing saved during a PiFinder session or to load for future sessions.
* ``screenshots/``\ :  It's possible to take screenshots while using the PiFinder (hold down **ENT** and press *0*\ ).  They are stored here.
* ``solver_debug_dumps/``\ : If enabled, information about solver performance is stored here as a collection of images and json files.
* ``observations.db``\ : This is the SQLite database which holds all the logged observations.

Update Software
==================
.. note::
   This documentation is a work in progress for v3 and v2.5 PiFinders running software 2.0.0 or above.
   If you need docs for a previous version please `Click here <https://pifinder.readthedocs.io/en/v1.11.2/index.html>`_

.. note::
   If the software version has not changed after the update, verify that the PiFinder is connected to a network with internet access, move 
   closer to the WiFi access point and try again.  To save power the WiFi transmitter on the PiFinder is not as powerful as a laptop or 
   other device so you may need to be fairly close to your WiFi access point to successfully complete the update.

You can also download a pre-built image of any software release and write it to the PiFinder's SD card.  
See our `release page <https://github.com/brickbots/PiFinder/releases>`_ to find information about any
of our releases and a link to download the images.


Instructions for writing software release images to an SD card can be found on the doc:`software setup<software>` page.

FAQ
====

Have any questions?  Please send them through to me at `rich@brickbots.com <mailto:rich@brickbots.com>`_ and I'll do my best to help and potentially add your question here.  Better yet, feel free to fork this repo and contribute via a pull request!
