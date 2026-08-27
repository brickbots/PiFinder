#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Center-object selection for the chart screen.

The **center object** is the plotted chart marker nearest the center of the
chart; the **center-object readout** is the optional line along the bottom of
the chart that names it. See ``docs/ax/ui/CONTEXT.md`` for the vocabulary and
ADR 0031 for why the candidate set is the markers the chart actually drew
rather than the Nearby ranking.

Deliberately free of PIL and ``plot.Starfield``: the chart hands in screen
coordinates it has already computed and everything here is plain arithmetic.
That keeps this unit-testable, which chart-level code isn't -- the chart needs
``hip_main.dat``, which is git-ignored and doesn't ship. The readout's layout
and config rules live here for the same reason; what stays in ``ui/chart.py``
is the drawing and the config reads that feed these.
"""

from __future__ import annotations

import math
from typing import List, Optional, Sequence, Tuple

from PiFinder.composite_object import CompositeObject
from PiFinder.ui.ui_utils import TextLayouterScroll, name_deduplicate

# How much closer a rival marker has to be before it takes the center-object
# line from the current one, as a fraction of the current distance. A fraction
# rather than a pixel count so it scales with the zoom level. Starting value;
# tune on-device (like NEARBY_MARKER_CAP in ui/chart.py).
STICKY_MARGIN = 0.15

# What the chart hands to CenterObjectTracker.update(): the object plus the
# screen coordinates the chart drew its marker at.
Candidate = Tuple[CompositeObject, float, float]

# The user's ``text_scroll_speed`` setting, in TextLayouterScroll's units.
_SCROLL_SPEEDS = {
    "Off": 0,
    "Fast": TextLayouterScroll.FAST,
    "Med": TextLayouterScroll.MEDIUM,
    "Slow": TextLayouterScroll.SLOW,
}


def readout_enabled(chart_center_object: Optional[str]) -> bool:
    """
    Whether the readout is on, from the ``chart_center_object`` config value.

    Anything that isn't exactly ``"On"`` is off, ``None`` included. Note that
    an upgrading user does not hit the ``None`` case: their config predates
    the setting, so ``get_option`` falls through to ``default_config.json``
    and they get ``"On"`` -- the readout appears on charts that never had one.
    """
    return chart_center_object == "On"


def readout_y(res_y: int, font_height: int, chart_radec: Optional[str]) -> int:
    """
    Top of the center-object strip, in screen pixels.

    The bottom of the chart stacks upward: the RA/Dec readout keeps the bottom
    line when it's on and the center-object line sits above it; with RA/Dec off
    the center-object line takes the bottom line itself. The ``radec_y`` here
    has to stay in step with the one ``UIChart.update`` draws coordinates at,
    or the two lines overlap.
    """
    radec_y = res_y - font_height - 3
    if chart_radec in ("HH:MM", "Degr"):
        return radec_y - font_height - 1
    return radec_y


def readout_scroll_speed(text_scroll_speed: Optional[str]) -> int:
    """
    The readout marquee's speed, from the user's ``text_scroll_speed`` setting.

    ``"Off"`` maps to 0, which stops ``TextLayouterScroll`` scrolling at all --
    the caller truncates the string itself in that case. An unrecognised value
    falls back to Medium rather than to no scrolling, so a stale config never
    silently clips a long name.
    """
    default = TextLayouterScroll.MEDIUM
    if text_scroll_speed is None:
        return default
    return _SCROLL_SPEEDS.get(text_scroll_speed, default)


def center_object_text(obj: CompositeObject) -> str:
    """
    The readout string for ``obj``: its designator followed by the first name
    the catalogs carry for it, e.g. ``"NGC 7000 North America nebula"``.

    Falls back to the designator alone when the object has no name that isn't
    just the designator again -- so "M 45" doesn't render as "M 45 M45".

    Note that ``names`` is in catalog order, and for Messier objects the first
    entry is usually a cross-designation rather than the popular name: M 57
    reads "M 57 NGC 6720", not "M 57 Ring nebula in Lyra", and M 45 reads
    "M 45 Cr 42" (the catalog has no "Pleiades" entry at all). That follows
    from taking names[0], which is what ``UIObjectList`` does too -- it lists
    the same names in the same order. Preferring a non-designation name would
    be a change to that shared convention, not a fix here.
    """
    designator = obj.display_name
    names = name_deduplicate(list(obj.names or []), [designator])
    if names:
        return f"{designator} {names[0]}"
    return designator


class CenterObjectTracker:
    """
    Picks and then *holds* the chart's center object across solves.

    ``update()`` is called once per solve with the markers the chart just drew.
    Candidates outside the screen bounds are dropped, the rest are ranked by
    pixel distance from the chart center, and the nearest wins -- except that an
    incumbent keeps the line until a rival beats it by ``sticky_margin``. Two
    near-equidistant markers would otherwise swap on IMU jitter alone, and each
    swap restarts the readout's marquee, so a long name would never finish a
    pass. A deliberate slew clears the margin immediately, so the stickiness
    costs nothing when the user means to change what they're looking at.

    Identity is ``object_id``; ``changed`` reports whether this tick picked a
    different object, which is what drives the marquee reset.
    """

    def __init__(self, sticky_margin: float = STICKY_MARGIN) -> None:
        self.sticky_margin = sticky_margin
        self.center_object: Optional[CompositeObject] = None
        # Screen position and pixel distance from center of the current pick.
        self.center_xy: Optional[Tuple[float, float]] = None
        self.center_distance: Optional[float] = None
        # On-screen candidates, nearest first. Snapshotted by the chart when
        # RIGHT opens the center object's details, so UP/DOWN there walks
        # outward through the chart's own markers.
        self.ranked: List[CompositeObject] = []
        self.changed = False

    def reset(self) -> None:
        """
        Forget the current center object -- no solve, or the chart cleared.
        Leaves ``changed`` set when there was something to forget.
        """
        self.changed = self.center_object is not None
        self.center_object = None
        self.center_xy = None
        self.center_distance = None
        self.ranked = []

    def update(
        self,
        candidates: Sequence[Candidate],
        center_xy: Tuple[float, float],
        bounds: Tuple[int, int],
    ) -> Optional[CompositeObject]:
        """
        Re-pick the center object from this solve's drawn markers.

        ``candidates`` is ``[(obj, screen_x, screen_y)]``, ``center_xy`` the
        chart center in the same coordinates, ``bounds`` the ``(width, height)``
        a marker has to fall inside to count. Returns the center object, or
        ``None`` when nothing qualifies.
        """
        cx, cy = center_xy
        width, height = bounds

        on_screen: List[Tuple[float, CompositeObject, float, float]] = []
        for obj, x, y in candidates:
            if not (0 <= x < width and 0 <= y < height):
                continue
            on_screen.append((math.hypot(x - cx, y - cy), obj, x, y))
        on_screen.sort(key=lambda entry: entry[0])
        ranked = [entry[1] for entry in on_screen]

        if not on_screen:
            self.reset()
            return None

        distance, winner, win_x, win_y = on_screen[0]

        # Hysteresis: if the incumbent is still on screen and the nearest marker
        # isn't it, the rival has to be closer by a clear margin to take over.
        if self.center_object is not None:
            held = next(
                (
                    e
                    for e in on_screen
                    if e[1].object_id == self.center_object.object_id
                ),
                None,
            )
            if held is not None and held[1].object_id != winner.object_id:
                if distance >= held[0] * (1 - self.sticky_margin):
                    distance, winner, win_x, win_y = held

        self.changed = (
            self.center_object is None
            or self.center_object.object_id != winner.object_id
        )
        self.center_object = winner
        self.center_xy = (win_x, win_y)
        self.center_distance = distance
        self.ranked = ranked
        return winner
