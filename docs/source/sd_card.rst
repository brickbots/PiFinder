Swapping the SD Card
====================

.. note::
   This page covers rev4 and v3 PiFinders.  The microSD card holds everything the
   PiFinder runs — the operating system, the PiFinder software, your settings,
   and the deep sky catalog images — so swapping it is how you recover from a
   corrupt card or move to a fresh or larger one.

The PiFinder boots from a microSD card.  On rev4 that card sits in a slot on the
side of the case, reachable from outside, so swapping it takes no tools and
nothing has to come apart.  This page covers getting at the card and swapping it.
To put software on the new card first, see :doc:`Software Setup <software>`.

.. note::
   On v3 PiFinders the card is inside the case, in the slot between the Raspberry
   Pi and the power board, and the case has to come apart to reach it.  See
   :ref:`sd_card:reaching the card on a v3 unit` below.

When you'd swap the card
------------------------

* The card has become corrupt and the PiFinder won't boot reliably (see
  :doc:`troubleshooting`).
* You'd rather re-image onto a spare card and keep your original as a backup.

Image the new card before you start — the
:ref:`software:prebuilt release image` is the quickest way, and it already
includes the catalog images.

Before you start
----------------

If the PiFinder is on, shut it down cleanly and wait for the screen and keypad to
go dark before you touch the card — see :ref:`user_guide:shutdown`.  Pulling a
card from a running unit can corrupt it.

.. note::
   On v3 PiFinders, switch the power off at the slide switch once the screen and
   keypad have gone dark, before you open the case.

Swapping the card
-----------------

The card slot is on the side of the case, and it's spring-loaded.  Press the card
in and let go — the spring pushes it part-way out — then slide it clear.  Push
the replacement in until it clicks and stays put.

The card is easy to crack once it's part-way out, so support it as you work and
don't flex it against the case.

.. TODO(rich): add a rev4 photo of the side SD slot with the card part-ejected.

Reaching the card on a v3 unit
------------------------------

On a v3 PiFinder the card sits inside the case, so the case has to come apart to
reach it.  You'll need a small Phillips screwdriver.  The card sits in a friction
slot — there's no spring to push it in or out, so you pull it straight out and
push the new one straight in.

Opening the case
~~~~~~~~~~~~~~~~

On every v3 unit, start by removing the three screws on the right-hand side as
you face the screen.

.. image:: images/sd_card/sd_card_remove_screws.jpeg
   :width: 70%

How you reach the card from there depends on your configuration.  If you're not
sure which one you have, the :ref:`build_guide:configurations overview` has
photos of each.

Right configuration
^^^^^^^^^^^^^^^^^^^

Simply lift off the separate cover held on by the three screws to expose the card.

Left configuration
^^^^^^^^^^^^^^^^^^

For the left configuration, the three screws hold the camera assembly in place.
Gently tilt the camera assembly out of the way to reach the card. Be mindful of
the cable, but there should be plenty of slack.

Flat configuration
^^^^^^^^^^^^^^^^^^

The three screws hold one side of the flat cradle. Removing them allows enough flex to
gently pull the flat holder down to expose the card.  The image below shows this, but
was taken during assembly before the camera is installed.  There is no need to remove
the camera to access the sd card.

.. image:: images/sd_card/flat_open.jpeg
   :width: 70%

Removing and replacing the card
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The card sits in the slot between the green Raspberry Pi board and the black
power board.  The white camera ribbon cable runs nearby — move it gently aside
if it's in the way, taking care not to crease or unseat it.

.. image:: images/sd_card/sd_card_closup.jpg
   :width: 47%
.. image:: images/sd_card/sd_card_closup_alt.jpeg
   :width: 47%

Grip the card and pull it straight out, then push the replacement straight in
until it's fully seated.  The card is easy to crack once it's part-way out, so
support it as you work and don't flex it against the case.

Reassembling
~~~~~~~~~~~~

Reverse the steps: refit the cover or holder for your configuration, check that
the camera ribbon is sitting flat and isn't pinched, and replace the three side
screws — snug, not forced.

First boot
----------

Power the PiFinder on.  The first boot from a freshly imaged card takes longer
than usual while it expands the filesystem to fill the card, so give it a couple
of minutes.

.. important::
   After swapping the card you'll most likely need to set the **Camera Type**
   again.  A freshly imaged card defaults to one sensor, and if it doesn't match
   your unit the camera view will be blank.  Set it under Settings → Advanced → Camera Type
   — the v3 sensors are ``imx462`` and ``imx296`` — then **fully power the
   PiFinder off and on**, as a software restart alone won't apply the change.
   See :ref:`troubleshooting:the camera view is blank or black` for more.  It's
   also worth re-checking your WiFi settings, since they won't carry over to a
   freshly imaged card.
