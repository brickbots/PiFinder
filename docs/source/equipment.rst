Equipment
=========

The PiFinder can keep track of the telescopes and eyepieces you observe with.
Telling it about your gear is optional, but it unlocks several conveniences:
it works out the magnification and true field of view for any
telescope-and-eyepiece pairing, it sizes and orients the survey images on the
:ref:`user_guide:object details` screen to match what you actually see at the
eyepiece, and it lets the push-to arrows follow the way your particular setup
moves.

You manage your equipment from two places. The :ref:`user_guide:web interface`
is where you add and edit telescopes and eyepieces, and the Equipment screen on
the PiFinder itself is where you pick which ones are active for tonight's
session.

Telescopes and eyepieces
------------------------

A **telescope** records the optical details of one of your instruments: its
make and name, aperture, focal length, central obstruction, and mount type,
along with a few display options covered below. The aperture and focal length
are what let the PiFinder calculate magnification and field of view.

An **eyepiece** records its focal length and apparent field of view (and, if
you know it, the field stop, which gives a more precise field-of-view figure).
You can store as many of each as you like and switch between them as you change
eyepieces through the night.

Adding and editing your gear
----------------------------

Telescopes and eyepieces are added through the :ref:`user_guide:web interface`.
Connect to the PiFinder as described there, then open the Equipment page from
the navigation menu. You'll find a list of your telescopes and a list of your
eyepieces, each with buttons to add a new one, edit an existing one, or remove
it.

A new PiFinder starts with a generic 200mm Dobsonian and a small set of Plössl
eyepieces so the calculations have something to work with out of the box. Edit
or replace these with your own equipment whenever you're ready.

.. note::
   The on-device Equipment menu builds its list of telescopes and eyepieces
   when the PiFinder starts up. If you add new gear in the web interface while
   the PiFinder is running, restart the PiFinder so the new items appear in the
   on-device selection lists.

Choosing your active telescope and eyepiece
-------------------------------------------

The PiFinder uses one **active** telescope and one **active** eyepiece at a
time for its calculations and displays. You can set these from either place:

* **On the PiFinder**, open the :ref:`user_guide:tools` menu and select
  Equipment. The Equipment screen shows your active telescope and eyepiece and,
  when both are set, the resulting magnification and true field of view. Choose
  "Telescope..." or "Eyepiece..." to pick from your stored gear.
* **In the web interface**, use the Equipment page to mark a telescope or
  eyepiece as active.

.. image:: images/equipment/equipment_screen_docs.png

Choosing "Telescope..." or "Eyepiece..." opens a list of your stored gear, with
a check mark next to the active one. Use the **UP/DOWN** arrows to highlight a
different item and **RIGHT** to make it active.

.. image:: images/equipment/select_telescope_docs.png
   :width: 45%
.. image:: images/equipment/select_eyepiece_docs.png
   :width: 45%

If nothing is selected, the PiFinder simply skips the magnification and
field-of-view figures and shows the object image in its default orientation.

Magnification and true field of view
-------------------------------------

Once an active telescope and eyepiece are set, the PiFinder shows two numbers
on the Equipment screen:

* **Magnification** is the telescope's focal length divided by the eyepiece's
  focal length. A 1000mm telescope with a 25mm eyepiece gives 40×.
* **True field of view** (TFOV) is how much sky you actually see through that
  combination, in degrees. This is the figure to compare against the push-to
  distance: when the object is within half your true field of view of the
  centre, it's in the eyepiece.

The true field of view also sets the starting zoom of the survey image on the
:ref:`user_guide:object details` screen, so the image frames roughly the same
patch of sky your eyepiece shows. You can still zoom in and out from there with
the **+** and **-** keys.

Both figures also appear on the object image itself — the field of view in the
top-left corner and the magnification in the top-right — so you always know the
scale of what you're looking at.

.. image:: images/equipment/object_image_fov_mag_docs.png

Matching the object image to your eyepiece: flip and flop
---------------------------------------------------------

The survey images on the object details screen are oriented to match the view
through your eyepiece, so you can compare them to what you see directly. Because
different telescopes flip the view in different ways, two per-telescope options
let you correct the orientation:

* **Flip image (upside down)** mirrors the image top to bottom.
* **Flop image (left right)** mirrors the image left to right.

You don't need to reason about your optics to set these. Point at a bright,
recognisable object, compare the object image to your eyepiece view, and toggle
the two options until they match:

* If the image is **upside down** compared to the eyepiece, turn on **Flip**.
* If the image is **mirrored** left-to-right, turn on **Flop**.
* If it's both, turn on both.

As a starting point for common setups:

.. list-table::
   :header-rows: 1
   :width: 100%

   * - Your telescope
     - Flip
     - Flop
   * - Newtonian / Dobsonian
     - off
     - off
   * - Refractor or SCT, straight through (no diagonal)
     - off
     - off
   * - Refractor or SCT with a star diagonal
     - one of the two — try Flop first
     -
   * - Refractor with a correct-image (erecting) diagonal
     - on
     - on

A plain Newtonian or Dobsonian needs neither option, which is why both are off
by default. A star diagonal produces a mirror image, so you'll need exactly one
of Flip or Flop; which one depends on how the diagonal sits in the focuser, so
just pick whichever makes the image match.

.. note::
   Early PiFinder software shipped the default Dobsonian with Flop turned on by
   mistake. If a Newtonian or Dobsonian image looks mirrored, open the telescope
   in the Equipment page and turn Flop off.

Reversing the push-to arrows
----------------------------

The same telescope settings include **Reverse Arrow A** and **Reverse Arrow B**.
These flip the direction of the push-to arrows so they point the way your
telescope actually moves. If you find that nudging the scope in the direction an
arrow points sends the target further away instead of closer, turn on the
matching reverse option. The two arrows cover the two directions of movement, so
enable A, B, or both until the arrows guide you the right way.
