
PiFinder™ Catalogs
===================

The PiFinder includes several astronomical catalogs that you can search and
filter. Each has a short catalog code that appears on the screen. Select which
catalogs are active in the :ref:`Filters<user_guide:filters>` menu.

A few catalogs, especially the Washington Double Star catalog, hold far too many
entries to scroll. For those, use **Name Search** to jump to an object by its
designation, or sort by **Nearest** to show the objects closest to where your
telescope points.

To observe objects the PiFinder doesn't carry, build your own list rather than
adding a catalog. See :ref:`user_guide:observing lists` for importing a list as a
CSV file, and :ref:`user_guide:custom targets` for entering coordinates by hand.

Abl
----
The Abell Catalog of Planetary Nebulae (George O. Abell, 1966): 79 confirmed planetary nebulae.

Arp
----
Atlas of Peculiar Galaxies (Arp 1966). Galaxies with unusual shapes. See `Wikipedia - Atlas of Peculiar Galaxies <https://en.wikipedia.org/wiki/Atlas_of_Peculiar_Galaxies>`_.

B
----
Barnard's Catalogue of 349 Dark Objects

C
----------
Caldwell catalog

CM
----
Comets. The PiFinder computes each comet's position from orbital elements
published by the Minor Planet Center.

The catalog fills in once the PiFinder knows your location and time, because a comet's
position depends on both. A GPS lock supplies them, and so does entering them by hand
in :ref:`user_guide:place & time`. Until then the catalog appears empty.

The PiFinder refreshes the orbital elements by itself. Whenever it starts up with
internet access in Client mode, it checks the Minor Planet Center for a newer set
and downloads it. There is no manual update to run. If you plan a night of comet
observing, turn the PiFinder on at home on WiFi for 15 to 20 minutes beforehand
so it can collect fresh elements.

Col
----------
471 open clusters compiled by Swedish astronomer Per Collinder.

EGC
----
Catalog of Extra-Galactic Globular Clusters: globular clusters associated with nearby galaxies, mostly in Andromeda, visible through modest amateur telescopes.

H
----------
A subset of William Herschel's original Catalogue of Nebulae and Clusters of Stars, selected in response to a letter in Sky and Telescope.

Harris
-------
Globular Clusters in the Milky Way (Harris, 1997). Compiled by William E. Harris, used by permission.

IC
----------
IC catalog

Lyn
----
Open Cluster Data, 5th Edition (Lyngå 1987): 1,151 open clusters.

M
----------
Messier catalog

NGC
----------
NGC 2000.0, The Complete New General Catalogue and Index Catalogue of Nebulae and Star Clusters by J.L.E. Dreyer (edited by R.W. Sinnott).

PK
----
The Perek-Kohoutek catalog of galactic planetary nebulae: 1,510 objects, from
Kohoutek's 2001 revision of the 1967 original.

A PK designation encodes galactic position rather than brightness:
PK 036+17.1 lies at galactic longitude 36°, latitude +17°, and is the first
nebula listed in that cell. Use **Name Search** to jump straight to one. The
list itself is numbered 1 to 1,510 in order of right ascension, matching the
printed catalog, so ``PK 743`` is a position in the list rather than a
designation.

The source catalog records positions and identifications only, so most entries
carry no magnitude. Entries that are also NGC, IC, Abell or Sharpless objects
take their magnitude from that catalog. Roughly 200 to 300 of these nebulae are
within reach of a small telescope; many of the rest are faint or heavily
reddened by dust in the galactic plane. Sizes come from the Strasbourg-ESO
Catalogue of Galactic Planetary Nebulae (Acker et al. 1992), which covers about
two thirds of the entries.

PL
----
Mercury, Venus, Mars, Jupiter, Saturn, Uranus and Neptune, along with the Moon and
Pluto. The Sun is not included. The PiFinder computes their positions for the
moment you look, and updates them as the night goes on.

The catalog fills in once the PiFinder knows your location and time, because a planet's
position depends on both. A GPS lock supplies them, and so does entering them by hand
in :ref:`user_guide:place & time`. Until then the catalog appears empty.

RDS
----
The RASC Double Stars Observing Program: 110 double stars visible from the northern hemisphere across many constellations.

SaA
----------
Saguaro Astronomy Club Asterisms Database Version 3.2

SaM
----
Saguaro Astronomy Club Double Star Database Version 4.0: 2,162 double stars.

SaR
----
SAC Red Stars Database Version 2.0

Sh2
----
313 H II regions (emission nebulae), comprehensive north of declination −27°.

Str
----
Named bright stars. Especially useful for aligning GoTo telescopes.

Ta2
----------
The TAAS 200 deep-sky observing list for the intermediate observer: the best 200 non-Messier objects easily visible from central New Mexico (north of declination −48°).

TLK
----
TLK's hand-picked list of interesting variable stars visible from the northern hemisphere.

WDS
----
The PiFinder includes over 130,000 double and multiple star pairs from the
Washington Double Star Catalog. The full list is far too long to scroll. Find a
pair with **Name Search** by typing its WDS designation, or sort by **Nearest**
to show the doubles closest to where your telescope points.
For more on WDS, see `https://www.astro.gsu.edu/wds/ <https://www.astro.gsu.edu/wds/>`_.
