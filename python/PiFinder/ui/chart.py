#!/usr/bin/python
# -*- coding:utf-8 -*-
# mypy: ignore-errors
"""
This module contains the chart (starfield + constellation lines) UI Module class

"""

from __future__ import (
    annotations,
)  # To support | in typehints (remove this for Python 3.10+)

import datetime
import logging
import math
import time
from dataclasses import dataclass
from PIL import ImageChops, Image

from PiFinder.ui.marking_menus import MarkingMenuOption, MarkingMenu
from PiFinder.obj_types import OBJ_TYPE_MARKERS
from PiFinder import plot
from PiFinder import satellite_catalog
from PiFinder.ui.base import UIModule
from PiFinder import calc_utils
from PiFinder.composite_object import MagnitudeObject
from PiFinder.nearby import ClosestObjectsFinder
from PiFinder.ui.chart_satellites import (
    REFRESH_SECONDS as SATELLITE_REFRESH_SECONDS,
    SatelliteLayer,
    angular_sep_deg,
    track_segment,
)
from PiFinder.ui.center_object import (
    CenterObjectTracker,
    center_object_text,
    readout_enabled,
    readout_scroll_speed,
    readout_y,
)
from PiFinder.ui.ui_utils import TextLayouterScroll


logger = logging.getLogger("Chart")

# Smallest on-screen span (px) worth outlining. Below this the object's marker
# glyph carries the position and an outline would just be a blob.
_MIN_OUTLINE_PX = 4

# The marker symbol of a satellite (markers/mrk_sat.png).
SATELLITE_SYMBOL = OBJ_TYPE_MARKERS[satellite_catalog.OBJ_TYPE]
# The track line of a satellite in the field, in pixels on a 128 px screen:
# the gap between the symbol centre and the line, and the shortest and the
# longest line. Larger screens scale these.
_TRACK_GAP_PX = 6
_TRACK_MIN_PX = 4
_TRACK_MAX_PX = 14


def size_perimeter_radec(
    ra0: float,
    dec0: float,
    extents: list,
    position_angle: float,
    steps: int = 48,
) -> list:
    """Build a closed RA/Dec perimeter for a numeric-extent size.

    ``extents`` are angular sizes in arcseconds (as stored by ``SizeObject``):

    * ``[d]``            -> circle of diameter ``d``
    * ``[major, minor]`` -> ellipse, ``position_angle`` measured N through E
    * ``[r1, r2, ...]``  -> polygon of radial distances at equal angular steps

    Returns ``[[ra, dec], ...]`` in degrees, first point repeated at the end so
    the caller can draw a closed outline. Empty near the poles where the RA
    scaling blows up.
    """
    if not extents:
        return []
    cos_dec0 = math.cos(math.radians(dec0))
    if abs(cos_dec0) < 1e-6:
        return []

    pa = math.radians(position_angle)
    sin_pa = math.sin(pa)
    cos_pa = math.cos(pa)

    # Local tangent-plane offsets in arcsec: E(ast), N(orth).
    offsets = []
    if len(extents) == 1:
        r = extents[0] / 2.0
        for i in range(steps):
            t = 2.0 * math.pi * i / steps
            offsets.append((r * math.cos(t), r * math.sin(t)))
    elif len(extents) == 2:
        a = extents[0] / 2.0
        b = extents[1] / 2.0
        for i in range(steps):
            t = 2.0 * math.pi * i / steps
            u = a * math.cos(t)  # along major axis
            v = b * math.sin(t)  # along minor axis
            offsets.append((u * sin_pa + v * cos_pa, u * cos_pa - v * sin_pa))
    else:
        step = 2.0 * math.pi / len(extents)
        for i, ext in enumerate(extents):
            phi = pa + i * step  # position angle of this radial spoke, N through E
            r = ext / 2.0
            offsets.append((r * math.sin(phi), r * math.cos(phi)))

    radec = [[ra0 + (e / 3600.0) / cos_dec0, dec0 + n / 3600.0] for e, n in offsets]
    radec.append(radec[0])
    return radec


# --- Nearby-DSO marker tuning ------------------------------------------------
# Starting values; tune on-device (see the chart-markers handoff). The radius
# query fetches catalog objects within ``fov * NEARBY_RADIUS_FACTOR`` degrees of
# the pointing, then the mag/cap filters below decide which get drawn.
NEARBY_RADIUS_FACTOR = 0.75
# When more than this many objects survive the mag filter, keep the brightest.
NEARBY_MARKER_CAP = 20
# Linear magnitude-limit curve over the chart's full zoom range: more zoomed in
# (small FOV) -> show dimmer objects. Endpoints are (fov_deg, mag_limit) pairs.
_MAG_LIMIT_LO = (5.0, 11.0)
_MAG_LIMIT_HI = (60.0, 7.0)


def dso_mag_limit(fov: float) -> float:
    """Magnitude limit for nearby DSO markers as a function of chart FOV."""
    fov_lo, mag_lo = _MAG_LIMIT_LO
    fov_hi, mag_hi = _MAG_LIMIT_HI
    if fov <= fov_lo:
        return mag_lo
    if fov >= fov_hi:
        return mag_hi
    perc = (fov - fov_lo) / (fov_hi - fov_lo)
    return mag_lo + (mag_hi - mag_lo) * perc


class UIChart(UIModule):
    __title__ = "CHART"
    __help_name__ = "chart"

    # The key and the result of the last DSO marker collection. See
    # _cached_dso_markers.
    _dso_markers_key = None
    _dso_markers = None
    _dso_markers_refs = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.last_update = time.time()
        self.starfield = plot.Starfield(self.colors, self.display_class.resolution)
        self.solution = None
        self.fov_list = [5, 10.2, 20, 30, 60]
        self.fov_index = 1
        self.fov_set_time = time.time()
        self.fov_target_time = None
        self.desired_fov = self.fov_list[self.fov_index]
        self.fov = self.desired_fov
        self.set_fov(self.desired_fov)

        # Spatial index for the "nearby catalog DSOs" marker layer. Rebuilt
        # from the active "All Filtered" set only when the catalog filter
        # changes (tracked via dirty_time) or deferred catalogs finish loading
        # -- never per frame. The radius query itself runs on the new-solve
        # path in plot_markers().
        self._nearby_finder = ClosestObjectsFinder()
        self._nearby_filter_dirty_time = None
        # The DSO markers of the last collection, their marker image and the
        # key they belong to. A satellite frame with the same key uses them
        # again.
        self._dso_markers_key = None
        self._dso_markers = None
        self._dso_markers_refs = None

        # --- Satellites at their live positions
        self._satellite_layer = SatelliteLayer()
        # The live RA/Dec of each drawn satellite, by id() of its object.
        # The center object uses these instead of the 5 s catalog positions.
        self._live_radec = {}
        # True when the last frame drew a satellite: the chart then draws
        # again every SATELLITE_REFRESH_SECONDS, also without a new solve.
        self._satellites_shown = False
        self._markers_time = 0.0
        # The starfield of the last solve, without the markers, and the
        # chart orientation of that solve.
        self._starfield_base = None
        self._orientation = None

        # --- Center object + its readout
        # The markers plot_markers() emitted a symbol for this solve; the
        # tracker's candidate set (see ADR 0031).
        self._drawn_objects = []
        self._center_tracker = CenterObjectTracker()
        self._center_scroller = None
        self._center_scroll_speed = None
        # The finished chart, cached so the readout strip can be repainted every
        # frame -- the starfield under it is only redrawn on a new solve.
        self._chart_backdrop = None
        self._center_arrow_px = int(self.fonts.base.font.getlength(self._RIGHT_ARROW))

        # Marking menu definition
        self.marking_menu = MarkingMenu(
            left=MarkingMenuOption(),
            down=MarkingMenuOption(
                label=_("Settings"),
                menu_jump="chart_settings",
            ),
            right=MarkingMenuOption(),
        )

    def plot_markers(self):
        """
        Plot the chart's markers, in four deduped layers:

        * The **target** cross -- the last-viewed object (``ui_state.target()``)
          -- always drawn at full brightness and independent of ``chart_dso``,
          with its designator label when it's on-screen. A satellite target
          is at its live position at the time of the frame.
        * The **observing list** (loaded from a saved list) -- always on, no
          mag limit, uncapped.
        * **Nearby catalog DSOs** -- objects from the active "All Filtered" set
          that fall inside the field, magnitude-filtered by zoom and capped.
        * **Satellites** in the field, at their live positions, each with a
          short track line in its direction of motion. See
          ``chart_satellites``. The DSO layers skip satellites.

        Called on a new solve, and every ``SATELLITE_REFRESH_SECONDS`` while a
        satellite is on the chart. ``chart_dso`` scales the DSO and satellite
        layers but never the target cross.

        Also records what it drew in ``self._drawn_objects``, which is the
        center object's candidate set -- so with ``chart_dso`` off the early
        return below leaves the target cross as the only candidate.
        """
        self._drawn_objects = []
        self._live_radec = {}
        self._satellites_shown = False
        self._markers_time = time.monotonic()
        if not self.solution:
            return

        W, H = self.display_class.resolution
        center = self._chart_center()
        dt = self.snapshot.datetime()

        # --- Target cross: always drawn, full brightness, chart_dso-independent
        target = self.ui_state.target()
        exclude_ids = set()
        exclude_satellites = frozenset()
        target_radec = self._target_radec(target, dt)
        if target_radec is not None:
            exclude_ids.add(target.object_id)
            if satellite_catalog.is_satellite(target):
                exclude_satellites = frozenset([target.sequence])
            self._draw_target(target, W, H, *target_radec)
            self._draw_object_outline(target, self.colors.get(255), center)
            self._drawn_objects.append(target)

        marker_brightness = self.config_object.get_option("chart_dso", 128)
        if marker_brightness == 0:
            return

        # --- DSO layers (observing list + nearby), deduped against the target
        marker_image, outline_objects, marker_objects = self._cached_dso_markers(
            exclude_ids, marker_brightness
        )
        self._drawn_objects.extend(marker_objects)

        # --- Satellites in the field, at their live positions
        field = self._field_satellites(center, dt, exclude_satellites)
        satellite_markers = []
        for sat in field:
            satellite_markers.append(
                (plot.Angle(degrees=sat.ra)._hours, sat.dec, SATELLITE_SYMBOL)
            )
            self._drawn_objects.append(sat.obj)
            self._live_radec[id(sat.obj)] = (sat.ra, sat.dec)

        if satellite_markers:
            # The marker images add with saturation, so the DSO image plus
            # the satellite image equals one image of all the markers.
            satellite_image = self.starfield.plot_markers(satellite_markers)
            if marker_image is None:
                marker_image = satellite_image
            else:
                marker_image = ImageChops.add(marker_image, satellite_image)

        if marker_image is not None:
            marker_image = ImageChops.multiply(
                marker_image,
                Image.new(
                    "RGB",
                    self.display_class.resolution,
                    self.colors.get(marker_brightness),
                ),
            )
            self.screen.paste(ImageChops.add(self.screen, marker_image))

        line_color = self.colors.get(marker_brightness)
        for obj in outline_objects:
            self._draw_object_outline(obj, line_color, center)
        self._draw_satellite_tracks(field, line_color)

    def _target_radec(self, target, dt):
        """The RA/Dec of the target cross, or None without a target.

        A satellite target is at its live position at ``dt``, the time of
        the frame, not at the position of the last catalog update. The chart
        then counts as a use of the satellite catalog.
        """
        if target is None or target.ra is None or target.dec is None:
            return None
        if not satellite_catalog.is_satellite(target):
            return target.ra, target.dec
        self._satellites_shown = True
        radec = None
        if dt is not None:
            radec = satellite_catalog.live_radec(target, dt)
        if radec is None:
            radec = (target.ra, target.dec)
        self._live_radec[id(target)] = radec
        return radec

    def _field_satellites(self, center, dt, exclude):
        """The satellites to draw in the field around ``center`` at ``dt``:
        see ``SatelliteLayer.field``.

        Empty when the satellite catalog is not a selected catalog. The
        catalog filter decides which satellites can show. The open chart counts
        as a use of a selected satellite catalog, so the catalog builds its
        objects and keeps its positions current while the chart is open.
        """
        if self.catalogs is None:
            return []
        catalog = self.catalogs.get_catalog_by_code(satellite_catalog.CATALOG_CODE)
        if catalog is None or not catalog.is_selected() or center is None or dt is None:
            self._satellite_layer.reset()
            return []
        catalog.touch()
        field = self._satellite_layer.field(
            catalog,
            catalog.get_filtered_objects(),
            center,
            self.fov * NEARBY_RADIUS_FACTOR,
            dt,
            dso_mag_limit(self.fov),
            exclude,
        )
        if field:
            self._satellites_shown = True
        return field

    def _draw_satellite_tracks(self, field, color):
        """Draw a short line from each satellite in its direction of motion.

        The line shows where the satellite goes in the next
        ``chart_satellites.TRACK_SECONDS``, limited in length so it stays
        visible at each zoom.
        """
        if not field:
            return
        ras = [sat.ra for sat in field] + [sat.ahead_ra for sat in field]
        decs = [sat.dec for sat in field] + [sat.ahead_dec for sat in field]
        xs, ys = self.starfield.radec_to_xy_many(ras, decs)
        n = len(field)
        scale = self.display_class.resX / 128.0
        for i in range(n):
            # The marker glyph is centred one pixel up and left of the point.
            segment = track_segment(
                xs[i] - 1,
                ys[i] - 1,
                xs[n + i] - 1,
                ys[n + i] - 1,
                _TRACK_GAP_PX * scale,
                _TRACK_MIN_PX * scale,
                _TRACK_MAX_PX * scale,
            )
            if segment is not None:
                self.draw.line(segment, fill=color, width=1)

    def _chart_center(self):
        """(RA, Dec) the chart is currently centred on, or ``None``."""
        if self.solution and self.solution.has_pointing():
            est = self.solution.pointing.aligned.estimate
            return est.RA, est.Dec
        return None

    def _draw_object_outline(self, obj, line_color, center):
        """Outline an object's true angular extent on the chart.

        Draws polyline/segment shapes as stored, and renders numeric
        circle/ellipse/polygon sizes from their major/minor axes and position
        angle. Objects well outside the field, or too small to resolve into
        more than a glyph, are skipped so the outline never degrades to a blob.
        """
        size = getattr(obj, "size", None)
        if not size or not size.extents:
            return

        # Cheap RA/Dec cull before any projection: skip anything comfortably
        # off the current field of view.
        if center is not None:
            if angular_sep_deg(obj.ra, obj.dec, center[0], center[1]) > self.fov:
                return

        if size.is_segments:
            for seg in size.extents:
                pts = self.starfield.project_vertices(seg)
                if len(pts) >= 2:
                    self.draw.line(pts, fill=line_color, width=1)
            return

        if size.is_vertices:
            pts = self.starfield.project_vertices(size.extents)
            if len(pts) >= 2:
                self.draw.line(pts, fill=line_color, width=1)
            return

        radec = size_perimeter_radec(obj.ra, obj.dec, size.extents, size.position_angle)
        if not radec:
            return
        pts = self.starfield.project_vertices(radec)
        if len(pts) < 2:
            return
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        if (max(xs) - min(xs)) < _MIN_OUTLINE_PX and (
            max(ys) - min(ys)
        ) < _MIN_OUTLINE_PX:
            return
        self.draw.line(pts, fill=line_color, width=1)

    def _draw_target(self, target, W, H, ra, dec):
        """
        Draw the target cross (+ off-screen pointer) at full brightness, and
        its designator label when the target is on-screen. Rendered separately
        from the ``chart_dso``-scaled DSO layers so it stays fully bright and
        visible even when ``chart_dso`` is 0. ``ra``/``dec`` give the position
        of the cross.
        """
        target_image = self.starfield.plot_markers(
            [(plot.Angle(degrees=ra)._hours, dec, "target")]
        )
        target_image = ImageChops.multiply(
            target_image,
            Image.new("RGB", self.display_class.resolution, self.colors.get(255)),
        )
        self.screen.paste(ImageChops.add(self.screen, target_image))

        # Designator label only when the cross itself is on-screen; off-screen
        # the pointer arrow (drawn above) already communicates direction.
        tx, ty = self.starfield.radec_to_xy(ra, dec)
        if 0 <= tx < W and 0 <= ty < H:
            self.draw.text(
                (int(tx) + 6, int(ty) - 4),
                target.display_name,
                font=self.fonts.base.font,
                fill=self.colors.get(255),
            )

    def _dso_markers_cache_key(self, exclude_ids, marker_brightness, refs):
        """The inputs of ``_collect_dso_markers`` and of its marker image, as
        a tuple to compare.

        It holds the solve (its time and the aligned RA/Dec), the FOV, the
        target ids, the ``chart_dso`` setting, the observing list (its
        identity and length), the selected catalogs, the dirty time of the
        catalog filter and the starfield view (its projection, roll and
        scale). The catalogs are filtered first, so that a stale filter
        bumps the dirty time before it goes into the key.

        ``refs`` holds the observing list and the projection, whose ids are
        in the key.
        """
        observing_list, projection = refs
        aligned = self.solution.pointing.aligned.estimate
        catalogs_key = None
        if self.catalogs is not None:
            selected = self.catalogs.get_catalogs(only_selected=True)
            self.catalogs.filter_catalogs(selected)
            catalog_filter = getattr(self.catalogs, "catalog_filter", None)
            catalogs_key = (
                id(self.catalogs),
                tuple(id(catalog) for catalog in selected),
                getattr(catalog_filter, "dirty_time", None),
            )
        return (
            getattr(self.solution, "estimate_time", None),
            aligned.RA,
            aligned.Dec,
            self.fov,
            frozenset(exclude_ids),
            marker_brightness,
            id(observing_list),
            len(observing_list),
            catalogs_key,
            id(projection),
            getattr(self.starfield, "roll", None),
            getattr(self.starfield, "pixel_scale", None),
        )

    def _cached_dso_markers(self, exclude_ids, marker_brightness):
        """The DSO markers: ``(marker_image, outline_objects,
        marker_objects)``.

        ``marker_image`` is the image of the DSO marker symbols before the
        ``chart_dso`` brightness, or None without symbols. The other two are
        as in ``_collect_dso_markers``.

        The collection and the image are made again only when the key of
        ``_dso_markers_cache_key`` changes. A satellite frame between two
        solves has the same key, so it uses the markers of the last frame.
        """
        refs = (
            self.ui_state.observing_list(),
            getattr(self.starfield, "projection", None),
        )
        key = self._dso_markers_cache_key(exclude_ids, marker_brightness, refs)
        if key != self._dso_markers_key or self._dso_markers is None:
            marker_list, outline_objects, marker_objects = self._collect_dso_markers(
                exclude_ids
            )
            marker_image = None
            if marker_list:
                marker_image = self.starfield.plot_markers(marker_list)
            self._dso_markers = (marker_image, outline_objects, marker_objects)
            self._dso_markers_key = key
            # The key holds the ids of these objects. The references keep
            # them alive, so a new object cannot get the same id.
            self._dso_markers_refs = refs
        marker_image, outline_objects, marker_objects = self._dso_markers
        return marker_image, list(outline_objects), list(marker_objects)

    def _collect_dso_markers(self, exclude_ids):
        """
        Build the marker list for the observing-list and nearby-catalog layers,
        deduped by ``object_id`` with precedence target -> observing-list ->
        nearby (``exclude_ids`` seeds the target). Returns
        ``(marker_list, outline_objects, marker_objects)`` where marker_list
        holds ``(ra_hours, dec_deg, symbol)`` tuples for
        ``Starfield.plot_markers``, outline_objects holds sized observing-list
        objects (nearby markers are symbols only), and marker_objects holds the
        objects behind marker_list in the same order, for the center-object
        candidate set.
        """
        marker_list = []
        outline_objects = []
        marker_objects = []
        seen = set(exclude_ids)

        # Observing list: always on, uncapped, no mag limit.
        for obj in self.ui_state.observing_list():
            # Satellites move: the satellite layer draws them.
            if obj.object_id in seen or satellite_catalog.is_satellite(obj):
                continue
            seen.add(obj.object_id)
            if obj.size and obj.size.extents:
                outline_objects.append(obj)
            symbol = OBJ_TYPE_MARKERS.get(obj.obj_type)
            if symbol:
                marker_list.append((plot.Angle(degrees=obj.ra)._hours, obj.dec, symbol))
                marker_objects.append(obj)

        # Nearby catalog DSOs: symbols only.
        for obj in self._get_nearby_markers():
            if obj.object_id in seen or satellite_catalog.is_satellite(obj):
                continue
            seen.add(obj.object_id)
            symbol = OBJ_TYPE_MARKERS.get(obj.obj_type)
            if symbol:
                marker_list.append((plot.Angle(degrees=obj.ra)._hours, obj.dec, symbol))
                marker_objects.append(obj)

        return marker_list, outline_objects, marker_objects

    def _get_nearby_markers(self):
        """
        Catalog objects near the current pointing to draw as nearby markers:
        drawn from the active "All Filtered" set, restricted to drawable object
        types, magnitude-filtered for the current FOV (unknown mags hidden),
        and capped at ``NEARBY_MARKER_CAP`` keeping the brightest.

        The BallTree is (re)built only when the catalog filter's ``dirty_time``
        changes (filter edits) or deferred catalogs finish loading (which marks
        the filter dirty) -- otherwise the cached tree is reused. The radius
        query runs each call. ``_cached_dso_markers`` calls it only when
        the solve, the FOV, the target, the observing list or the filter
        changes, so a satellite frame between two solves does not query.
        """
        if self.catalogs is None:
            return []

        # Object lists filter only the catalogs they show, so bring the
        # selected catalogs up to date first. This is a cheap check when the
        # filter has not changed.
        selected = self.catalogs.get_catalogs(only_selected=True)
        self.catalogs.filter_catalogs(selected)
        catalog_filter = getattr(self.catalogs, "catalog_filter", None)
        dirty_time = getattr(catalog_filter, "dirty_time", None)
        if dirty_time != self._nearby_filter_dirty_time:
            objects = self.catalogs.get_objects(only_selected=True, filtered=True)
            self._nearby_finder.calculate_objects_balltree(objects)
            self._nearby_filter_dirty_time = dirty_time

        aligned = self.solution.pointing.aligned.estimate
        radius = self.fov * NEARBY_RADIUS_FACTOR
        candidates = self._nearby_finder.get_objects_within_radius(
            aligned.RA, aligned.Dec, radius
        )

        mag_limit = dso_mag_limit(self.fov)
        eligible = []
        for obj in candidates:
            # The index holds the satellite positions of its build time, so
            # the satellite layer draws them instead.
            if OBJ_TYPE_MARKERS.get(
                obj.obj_type
            ) is None or satellite_catalog.is_satellite(obj):
                continue
            mag = obj.mag
            if mag is None:
                continue
            filter_mag = mag.filter_mag
            if filter_mag == MagnitudeObject.UNKNOWN_MAG or filter_mag > mag_limit:
                continue
            eligible.append((filter_mag, obj))

        # Brightest first, then keep at most NEARBY_MARKER_CAP.
        eligible.sort(key=lambda pair: pair[0])
        return [obj for _, obj in eligible[:NEARBY_MARKER_CAP]]

    def _draw_orientation_indicator(self, orientation: "ChartOrientation"):
        """
        Draw a small "up" indicator at the top-left of the chart.

        Communicates which orientation the chart is using (NCP / SCP / Zenith)
        and, when GPS hasn't arrived yet but the user picked a GPS-dependent
        mode, prefixes a "!" so the user knows the orientation will flip
        once GPS comes online.
        """
        # TRANSLATORS: chart corner label, e.g. "Zenith up" — keep short
        text = _("{label} up").format(label=orientation.up_label)
        if orientation.is_fallback:
            text = "!" + text
        font = self.fonts.base
        # Brighter when fallback so the "!" reads as a hint, not noise.
        brightness = 255 if orientation.is_fallback else 128
        x = 2
        # Sit just below the title bar
        y = self.display_class.titlebar_height + 1
        self.draw.text(
            (x, y),
            text,
            font=font.font,
            fill=self.colors.get(brightness),
        )

    def draw_reticle(self):
        """
        draw the reticle if desired
        """
        brightness = self.config_object.get_option("chart_reticle", 128)
        if brightness == 0:
            # None....
            return

        fov = self.fov
        for circ_deg in [4, 2, 0.5]:
            circ_rad = ((circ_deg / fov) * self.display_class.fov_res) / 2
            bbox = [
                self.display_class.centerX - circ_rad,
                self.display_class.centerY - circ_rad,
                self.display_class.centerX + circ_rad,
                self.display_class.centerY + circ_rad,
            ]
            self.draw.arc(bbox, 20, 70, fill=self.colors.get(brightness))
            self.draw.arc(bbox, 110, 160, fill=self.colors.get(brightness))
            self.draw.arc(bbox, 200, 250, fill=self.colors.get(brightness))
            self.draw.arc(bbox, 290, 340, fill=self.colors.get(brightness))

    # --- Center object + readout ------------------------------------------
    #
    # The center object is the drawn marker nearest the middle of the chart;
    # the readout is the optional line along the bottom that names it. See
    # ADR 0031 and docs/ax/ui/CONTEXT.md.

    def _center_readout_enabled(self):
        return readout_enabled(
            self.config_object.get_option("chart_center_object", "On")
        )

    def _update_center_object(self):
        """
        Re-pick the center object from the markers ``plot_markers`` just drew,
        and restart the marquee if the pick changed.

        Projects the drawn objects to screen space in one batched call and
        hands the result to the tracker, which does the bounds check, the
        ranking and the hysteresis.

        Skipped entirely while the readout is off. Nothing else consumes the
        pick -- RIGHT is gated on the readout too -- so there is no one to pay
        the projection for, and a stale pick must not linger in the published
        UI state either, hence the reset on the way past.
        """
        if not self._center_readout_enabled():
            if self._center_tracker.center_object is not None:
                self._center_tracker.reset()
                self._center_scroller = None
            return

        drawn = [
            obj
            for obj in self._drawn_objects
            if obj.ra is not None and obj.dec is not None
        ]
        positions = [self._live_radec.get(id(obj), (obj.ra, obj.dec)) for obj in drawn]
        xs, ys = self.starfield.radec_to_xy_many(
            [ra for ra, _dec in positions], [dec for _ra, dec in positions]
        )
        candidates = list(zip(drawn, xs, ys))

        self._center_tracker.update(
            candidates,
            (self.display_class.centerX, self.display_class.centerY),
            self.display_class.resolution,
        )
        if self._center_tracker.changed:
            self._build_center_scroll()

    def _center_readout_y(self):
        """
        Top of the center-object strip. Recomputed each frame because the
        RA/Dec setting it stacks against can change while the preloaded chart
        is live. See ``center_object.readout_y`` for the rule.
        """
        return readout_y(
            self.display_class.resY,
            self.fonts.base.height,
            self.config_object.get_option("chart_radec"),
        )

    def _center_scroll_speed_config(self):
        return readout_scroll_speed(
            self.config_object.get_option("text_scroll_speed", "Med")
        )

    def _build_center_scroll(self):
        """
        (Re)build the readout's marquee, which restarts it from the left.
        Called when the center object changes, when the scroll speed setting
        changes, and from ``active()``.
        """
        obj = self._center_tracker.center_object
        if obj is None:
            self._center_scroller = None
            return

        font = self.fonts.base
        speed = self._center_scroll_speed_config()
        # TextLayouterScroll slices a fixed-width string, so its width is a
        # character count: the screen less the right-pinned arrow glyph.
        width = max(
            1,
            int((self.display_class.resX - self._center_arrow_px - 2) // font.width),
        )
        text = center_object_text(obj)
        if speed == 0:
            # Not scrolling, and TextLayouterScroll then draws the string in
            # full -- PIL would clip it at the panel edge with no ellipsis, so
            # truncate here instead.
            text = text[:width]

        self._center_scroller = TextLayouterScroll(
            text,
            self.draw,
            self.colors.get(255),
            font,
            width=width,
            scrollspeed=speed,
        )
        self._center_scroll_speed = speed

    def _draw_center_readout(self):
        """
        Draw the center-object line, on every frame rather than only on a new
        solve -- otherwise the marquee would stutter along at the 1-2 Hz solve
        rate. The strip is repainted from the cached chart backdrop first, so
        the previous frame's text doesn't smear.
        """
        if not self._center_readout_enabled():
            return
        if self._center_tracker.center_object is None or self._chart_backdrop is None:
            return

        if self._center_scroll_speed != self._center_scroll_speed_config():
            self._build_center_scroll()
        if self._center_scroller is None:
            return

        font = self.fonts.base
        strip_y = self._center_readout_y()
        box = (
            0,
            strip_y,
            self.display_class.resX,
            min(self.display_class.resY, strip_y + font.height + 1),
        )
        self.screen.paste(self._chart_backdrop.crop(box), (box[0], box[1]))

        self._center_scroller.draw((0, strip_y))
        self.draw.text(
            (self.display_class.resX - self._center_arrow_px, strip_y),
            self._RIGHT_ARROW,
            font=font.font,
            fill=self.colors.get(255),
        )

    def active(self):
        """
        Restart the marquee when the chart is revealed again --
        ``remove_from_stack`` calls ``active()`` on the module below, and the
        chart is preloaded and stateful, so this is the hook for coming back
        from an object's details.
        """
        super().active()
        self._build_center_scroll()

    def key_right(self):
        """
        Open the center object's details.

        Gated on the readout: with it off, or with no center object (no solve,
        nothing drawn, nothing on screen), RIGHT stays inert as it was before
        the readout existed. Long RIGHT isn't ours -- ``MenuManager`` takes it
        for the most recent object -- so the chart has both: short RIGHT for
        what you're pointed at, long RIGHT for what you last looked at.
        """
        from PiFinder.ui.object_details import UIObjectDetails

        if not self._center_readout_enabled():
            return
        obj = self._center_tracker.center_object
        if obj is None:
            return

        self.add_to_stack(
            {
                "name": obj.display_name,
                "class": UIObjectDetails,
                "object": obj,
                # Nearest-first, so UP/DOWN inside details walks outward
                # through the chart's own markers.
                "object_list": list(self._center_tracker.ranked),
                "label": "object_details",
            }
        )

    def serialize_ui_state(self) -> dict:
        """
        Chart state for ``/api/current-selection``: the zoom level and the
        current center object, so the readout is checkable without OCR-ing a
        screenshot. ``center_object`` is null while ``center_object_readout``
        is false -- with the readout off nothing picks one, so there is
        nothing to report rather than something the user can't see.
        """
        obj = self._center_tracker.center_object
        center = None
        if obj is not None:
            xy = self._center_tracker.center_xy
            center = {
                "display_name": obj.display_name,
                "object_id": obj.object_id,
                "screen_px": [round(xy[0], 1), round(xy[1], 1)] if xy else None,
            }
        return {
            "fov": self.fov,
            "center_object_readout": self._center_readout_enabled(),
            "center_object": center,
        }

    def set_fov(self, fov):
        self.fov = fov
        self.starfield.set_fov(fov)
        return

        # TODO: Fix zoom animation
        self.starting_fov = self.fov
        self.fov_starting_time = time.time()
        self.desired_fov = fov

    def animate_fov(self):
        # TODO: Fix zoom animation
        return
        if self.fov == self.desired_fov:
            return

        fov_progress = (time.time() - self.fov_starting_time) * 20
        if self.desired_fov > self.starting_fov:
            current_fov = self.starting_fov + fov_progress
            if current_fov > self.desired_fov:
                current_fov = self.desired_fov
        else:
            current_fov = self.starting_fov - fov_progress
            if current_fov < self.desired_fov:
                current_fov = self.desired_fov
        self.fov = current_fov
        self.starfield.set_fov(current_fov)

    def update(self, force=False):
        if force:
            self.last_update = 0

        if self.snapshot.solve_state():
            self.animate_fov()
            constellation_brightness = self.config_object.get_option(
                "chart_constellations", 64
            )
            self.solution = self.snapshot.solution()
            last_estimate_time = self.solution.estimate_time

            if last_estimate_time is None:
                self.plot_no_solve()
            elif self.solution_is_new(last_estimate_time):
                aligned = self.solution.pointing.aligned.estimate
                # Solution is new so plot the updated chart
                orientation = get_chart_rotation_angle(
                    aligned.RA,
                    aligned.Dec,
                    chart_coord_sys=self.config_object.get_option("chart_coord_sys"),
                    location=self.snapshot.location(),
                    dt=self.snapshot.datetime(),
                )
                chart_rot_angle = orientation.rot_deg if orientation else None
                # This needs to be called first to set RA/DEC/chart_rot_angle
                image_obj, _visible_stars = self.starfield.plot_starfield(
                    aligned.RA,
                    aligned.Dec,
                    chart_rot_angle,
                    constellation_brightness,
                )
                image_obj = ImageChops.multiply(
                    image_obj.convert("RGB"), self.colors.red_image
                )
                self._starfield_base = image_obj
                self._orientation = orientation
                self.screen.paste(image_obj)
                self._draw_overlays(aligned, orientation)
                self.last_update = last_estimate_time
            elif self._satellite_frame_due():
                # Satellites move between two solves: draw the markers again
                # on the starfield of the last solve.
                self.screen.paste(self._starfield_base)
                self._draw_overlays(
                    self.solution.pointing.aligned.estimate, self._orientation
                )
        else:
            self.plot_no_solve()

        self._draw_center_readout()
        return self.screen_update()

    def _draw_overlays(self, aligned, orientation):
        """Draw everything on top of the starfield: the markers, the
        orientation indicator, the RA/Dec, the reticle. Then cache the
        finished chart."""

        self.plot_markers()
        self._update_center_object()
        if orientation is not None:
            self._draw_orientation_indicator(orientation)

        # Display RA/DEC in selected format if enabled, anchored just
        # above the bottom edge (derived so it tracks resolution).
        radec_y = self.display_class.resY - self.fonts.base.height - 3
        if self.config_object.get_option("chart_radec") == "HH:MM":
            ra_h, ra_m, ra_s = calc_utils.ra_to_hms(aligned.RA)
            dec_d, dec_m, dec_s = calc_utils.dec_to_dms(aligned.Dec)
            ra_dec_disp = (
                f"{ra_h:02d}:{ra_m:02d}:{ra_s:02d} / {dec_d:02d}°{dec_m:02d}:{dec_s}"
            )
            self.draw.text(
                (0, radec_y),
                ra_dec_disp,
                font=self.fonts.base.font,
                fill=self.colors.get(255),
            )
        if self.config_object.get_option("chart_radec") == "Degr":
            ra_h, ra_m, ra_s = calc_utils.ra_to_hms(aligned.RA)
            dec_d, dec_m, dec_s = calc_utils.dec_to_dms(aligned.Dec)
            ra_dec_disp = f"{aligned.RA:0>6.2f} / {aligned.Dec:0>5.2f}"
            self.draw.text(
                (0, radec_y),
                ra_dec_disp,
                font=self.fonts.base.font,
                fill=self.colors.get(255),
            )

        self.draw_reticle()

        # Cache the finished chart so _draw_center_readout can repaint
        # its strip every frame without the starfield underneath it.
        self._chart_backdrop = self.screen.copy()

    def _satellite_frame_due(self):
        """True when the last frame drew a satellite and its position is
        older than ``SATELLITE_REFRESH_SECONDS``."""
        return (
            self._satellites_shown
            and self._starfield_base is not None
            and self.solution is not None
            and self.solution.has_pointing()
            and time.monotonic() - self._markers_time >= SATELLITE_REFRESH_SECONDS
        )

    def plot_no_solve(self):
        """Plot message: Can't plot No solve yet"""
        # The screen is about to be cleared, so there are no drawn markers to
        # be the center object and no backdrop to repaint its strip from.
        self._drawn_objects = []
        self._center_tracker.reset()
        self._center_scroller = None
        self._chart_backdrop = None
        self._starfield_base = None
        self._satellites_shown = False
        self.draw.rectangle(
            [0, 0, self.display_class.resX, self.display_class.resY],
            fill=self.colors.get(0),
        )
        self.draw.text(
            (16, self.display_class.titlebar_height + 10),
            _("Can't plot"),
            font=self.fonts.large.font,
            fill=self.colors.get(255),
        )
        self.draw.text(
            (
                26,
                self.display_class.titlebar_height + 10 + self.fonts.large.height + 4,
            ),
            _("No Solve Yet"),
            font=self.fonts.base.font,
            fill=self.colors.get(255),
        )

    def solution_is_new(self, last_estimate_time):
        """
        Returns True if the solution (coordinates) is valid and new since
        last_estimate_time.
        """
        if last_estimate_time is None or self.last_update is None:
            return False
        if last_estimate_time <= self.last_update:
            return False
        if not self.solution.has_pointing():
            return False

        return True  # Solution is valid and new

    def change_fov(self, direction):
        self.fov_index += direction
        if self.fov_index < 0:
            self.fov_index = 0
        if self.fov_index >= len(self.fov_list):
            self.fov_index = len(self.fov_list) - 1
        self.set_fov(self.fov_list[self.fov_index])
        self.update(force=True)

    def key_plus(self):
        self.change_fov(-1)

    def key_minus(self):
        self.change_fov(1)

    def key_square(self):
        # Set back to 10.2 to match the camera view
        self.fov_index = 1
        self.set_fov(self.fov_list[self.fov_index])
        self.update()


@dataclass
class ChartOrientation:
    """
    Resolved chart rotation plus what's "up" on screen.

    - ``rot_deg`` is the angle to rotate the chart by (the value previously
      returned bare by ``get_chart_rotation_angle``).
    - ``up_label`` is a short string describing what's at the top of the
      chart: ``"NCP"`` / ``"SCP"`` / ``"Zenith"``.
    - ``is_fallback`` is True when the user picked an orientation mode that
      needs GPS (horizontal, or eq-auto in the southern hemisphere) but GPS
      data isn't available yet, so the chart is showing a default NCP-up
      orientation that will change once GPS arrives. The chart UI surfaces
      this so the user isn't startled by the orientation flip.
    """

    rot_deg: float
    up_label: str
    is_fallback: bool


def get_chart_rotation_angle(
    ra_deg: float,  # Right Ascension of the target in degrees
    dec_deg: float,  # Declination of the target in degrees
    chart_coord_sys: str,
    location=None,
    dt: datetime.datetime | None = None,
) -> ChartOrientation | None:
    """
    Returns the rotation and "up" orientation for the chart, depending on
    the configured chart coordinate system. The rotation was previously
    called "roll": the chart is plotted rotated around (RA, Dec); +ve means
    anti-clockwise rotation. The RA and Dec of the target must be provided
    (in degrees); returns ``None`` if either is missing.

    Modes:

    * horiz: Display the chart in horizontal coordinates so up points at
      the Zenith. Needs a GPS location and a datetime; without either,
      falls back to NCP up and flags ``is_fallback=True``.
    * EQ (Auto): Display the chart in equatorial coordinates, NCP-up in
      the northern hemisphere and SCP-up in the southern. Without GPS
      location, defaults to NCP up and flags ``is_fallback=True``.
    * EQ (North-up), EQ (South-up): Display the chart with NCP or SCP up.
      Never a fallback — explicit user choice.
    """
    if (ra_deg is None) or (dec_deg is None):
        return None  # Can't calculate without RA/Dec

    has_gps = bool(location and getattr(location, "lock", False))

    if chart_coord_sys == "horiz":
        if has_gps and dt:
            calc_utils.sf_utils.set_location(
                location.lat, location.lon, location.altitude
            )
            # Use -parallactic_angle
            rot_deg = -calc_utils.sf_utils.radec_to_pa(ra_deg, dec_deg, dt)
            return ChartOrientation(rot_deg, "Zenith", False)
        # No location/time: default to NCP up but flag as a fallback so
        # the UI can show that the orientation will change once GPS arrives.
        return ChartOrientation(0.0, "NCP", True)
    if chart_coord_sys == "eq_auto":
        if has_gps:
            if location.lat < 0.0:
                return ChartOrientation(180.0, "SCP", False)
            return ChartOrientation(0.0, "NCP", False)
        # No location: northern-hemisphere default, but flag as fallback.
        return ChartOrientation(0.0, "NCP", True)
    if chart_coord_sys == "eq_north_up":
        return ChartOrientation(0.0, "NCP", False)
    if chart_coord_sys == "eq_south_up":
        return ChartOrientation(180.0, "SCP", False)

    logger.error(
        f"Unknown chart coordinate system: {chart_coord_sys}. Defaulting to EQ North-up."
    )
    return ChartOrientation(0.0, "NCP", False)
