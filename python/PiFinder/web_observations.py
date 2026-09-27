#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Everything the observations web pages need that isn't a route.

The device already knows a great deal about an object it has logged — what
it is, what it's called elsewhere, what the sky survey shows there, what
the Gaia charts look like — and none of it used to be reachable from a log
entry. This module turns the stored rows back into that picture: notes and
solutions decoded for display, catalog identity assembled across an
object's listings, and the two object images rendered at a size that suits
a browser rather than a 128px panel.
"""

import datetime
import io
import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image

from PiFinder import utils
from PiFinder.composite_object import CompositeObject, MagnitudeObject, SizeObject
from PiFinder.db.objects_db import ObjectsDatabase
from PiFinder.displays import GREY, DisplayBase
from PiFinder.object_images.chart_provider import ChartImageProvider
from PiFinder.object_images.image_base import ImageType
from PiFinder.object_images.poss_provider import POSSImageProvider
from PiFinder.observing_nights import parse_notes

logger = logging.getLogger("Web.Observations")

# Ratings the log screen records on a 1-5 scale; rendered as stars rather
# than as a number so a log entry reads at a glance.
RATING_NOTE_KEYS = ("observability", "appeal")
RATING_MAX = 5

# Note keys with a home of their own in the UI; everything else in the
# blob falls through to a generic chip so older schemas still show up.
HANDLED_NOTE_KEYS = set(RATING_NOTE_KEYS) | {"schema_ver", "sqm"}

# Web renders are square and much larger than the device panel; the fonts
# scale with them so burnt-in overlays stay legible.
CHART_RENDER_SIZE = 640

ONE_HOUR = datetime.timedelta(hours=1)


class WebDisplay(DisplayBase):
    """A display the object-image providers can render into.

    The providers are written against the device display: they read its
    resolution and multiply their output by its colour mask. A grey mask
    makes that multiply a no-op, so the browser gets the image in its own
    tones instead of the panel's night-vision red.
    """

    resolution = (CHART_RENDER_SIZE, CHART_RENDER_SIZE)
    color_mask = GREY
    base_font_size = 20
    bold_font_size = 24
    small_font_size = 16
    large_font_size = 30
    huge_font_size = 70


def rating_stars(value: Any) -> Optional[Dict[str, int]]:
    """A 1-5 rating as filled/empty counts, or None if not rated."""
    try:
        filled = int(value)
    except (TypeError, ValueError):
        return None
    if not 1 <= filled <= RATING_MAX:
        return None
    return {"filled": filled, "empty": RATING_MAX - filled}


def decode_notes(notes: Any) -> Dict[str, Any]:
    """Split an observation's notes into the pieces the templates draw.

    Returns the star ratings, the sky-brightness reading, and whatever
    else the blob holds as plain label/value chips — so notes written by
    an older schema still render instead of disappearing.
    """
    parsed = parse_notes(notes)

    ratings = {}
    for key in RATING_NOTE_KEYS:
        stars = rating_stars(parsed.get(key))
        if stars is not None:
            ratings[key] = stars

    chips = []
    for key, value in parsed.items():
        if key in HANDLED_NOTE_KEYS or value in (None, "", "NA"):
            continue
        chips.append({"label": key.replace("_", " "), "value": value})

    sqm = parsed.get("sqm")
    if not isinstance(sqm, dict) or sqm.get("source") in (None, "None"):
        sqm = None

    return {"ratings": ratings, "chips": chips, "sqm": sqm}


def decode_solution(solution: Any) -> Dict[str, Any]:
    """Where the PiFinder was pointing when an observation was logged.

    The solution is stored for every log entry but has never been shown;
    it carries the constellation and the object's altitude at that moment,
    which is the difference between "logged M 13" and "logged M 13 at 61
    degrees in Hercules".
    """
    if not solution:
        return {}
    if isinstance(solution, str):
        try:
            solution = json.loads(solution)
        except (TypeError, ValueError):
            return {}
    if not isinstance(solution, dict):
        return {}

    decoded: Dict[str, Any] = {}
    constellation = solution.get("constellation")
    if constellation:
        decoded["constellation"] = constellation
    altitude = solution.get("Alt")
    if altitude is not None:
        decoded["altitude"] = round(float(altitude))
    azimuth = solution.get("Az")
    if azimuth is not None:
        decoded["azimuth"] = round(float(azimuth))
    return decoded


def decorate_logs(logs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Log rows with their notes and solutions decoded for display.

    Consecutive entries from different software runs are flagged, which is
    what lets a night show where it was interrupted without pretending the
    interruption was a different night.
    """
    decorated = []
    previous_session = None
    for log in logs:
        entry = dict(log)
        entry["notes"] = decode_notes(log.get("notes"))
        entry["solution"] = decode_solution(log.get("solution"))
        entry["starts_new_run"] = (
            previous_session is not None and log.get("session_uid") != previous_session
        )
        previous_session = log.get("session_uid")
        decorated.append(entry)
    return decorated


class ObjectLookup:
    """Catalog identity for an object the observer logged.

    Log entries name a listing (catalog, sequence); everything else — what
    the object is, its other designations, its descriptions — lives in the
    objects database, which is opened once and reused.
    """

    def __init__(self, objects_db: Optional[ObjectsDatabase] = None):
        self.db = objects_db or ObjectsDatabase()

    def composite(self, catalog: str, sequence: int) -> Optional[CompositeObject]:
        """The full object behind a listing, or None if it's unknown.

        Log entries can outlive their catalog: a listing that no longer
        resolves simply has no object to show.
        """
        catalog_row = self.db.get_catalog_object_by_sequence(catalog, sequence)
        if catalog_row is None:
            return None

        catalog_row = dict(catalog_row)
        object_row = self.db.get_object_by_id(catalog_row["object_id"])
        if object_row is None:
            return None

        composite = dict(object_row)
        composite.pop("id", None)
        composite.update(catalog_row)
        composite["names"] = self.db.get_names_by_object_id(catalog_row["object_id"])

        obj = CompositeObject.from_dict(composite)
        # Magnitude and size are stored as JSON text; the catalog loader
        # turns them into the objects that know how to display themselves,
        # and a page rendered straight from the DB must do the same.
        try:
            magnitude = MagnitudeObject.from_json(composite.get("mag", ""))
            obj.mag = magnitude
            obj.mag_str = magnitude.calc_two_mag_representation()
        except Exception:
            obj.mag = MagnitudeObject([])
            obj.mag_str = ""
        obj.size = SizeObject.from_json(composite.get("size", ""))
        return obj

    def other_listings(self, obj: CompositeObject) -> List[Dict[str, Any]]:
        """The object's designations in other catalogs, with their text.

        The same object described twice is worth reading twice: catalogs
        disagree, and a second description often says what the first left
        out.
        """
        listings = []
        for row in self.db.get_catalog_objects_by_object_id(obj.object_id):
            row = dict(row)
            if (
                row["catalog_code"] == obj.catalog_code
                and row["sequence"] == obj.sequence
            ):
                continue
            listings.append(
                {
                    "catalog": row["catalog_code"],
                    "sequence": row["sequence"],
                    "description": (row.get("description") or "").strip(),
                }
            )
        return sorted(listings, key=lambda listing: listing["catalog"])


def poss_image_path(obj: CompositeObject) -> Optional[str]:
    """The survey image on disk for this object, if one was downloaded.

    The full-resolution source is served to the browser rather than the
    device render: no red mask, no vignette, no downscale to 128px.
    """
    path = POSSImageProvider()._resolve_image_name(obj, source="POSS")
    return path if path and os.path.exists(path) else None


def gaia_catalog_available() -> bool:
    """Whether this device carries the Gaia star catalog."""
    return os.path.exists(
        os.path.join(str(utils.data_dir), "gaia_stars", "metadata.json")
    )


def render_chart(
    obj: CompositeObject,
    config_object,
    shared_state,
    fov: float = 1.0,
    display: Optional[DisplayBase] = None,
) -> Optional[bytes]:
    """A Gaia star chart for this object as PNG bytes, or None.

    The chart provider yields progressive frames for the device's
    panel — placeholders first, then the chart as magnitude bands load —
    so the browser gets the last real frame it produced. When the catalog
    is still loading (or absent) the generator ends without one, and the
    page simply shows no chart until a later request finds it ready.
    """
    display = display or WebDisplay()
    provider = ChartImageProvider(config_object, shared_state)

    chart = None
    try:
        for frame in provider.get_image(
            obj,
            eyepiece_text="",
            fov=fov,
            roll=0,
            display_class=display,
            burn_in=False,
            config_object=config_object,
            shared_state=shared_state,
        ):
            if getattr(frame, "image_type", None) == ImageType.GAIA_CHART:
                chart = frame
    except Exception:
        logger.warning(
            "Gaia chart render failed for %s", obj.display_name, exc_info=True
        )
        return None

    if chart is None:
        return None
    return _png_bytes(chart)


def _png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="PNG")
    return buffer.getvalue()


def night_summary(nights: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Headline figures across every night on record."""
    return {
        "night_count": len(nights),
        "object_count": sum(night["observations"] for night in nights),
        "total_hours": sum(night["span_hours"] for night in nights),
    }


def strip_ticks(night: Dict[str, Any], logs: List[Dict[str, Any]]) -> List[float]:
    """Each observation's position along a night, as a 0-1 fraction.

    Drives the span strip: a night's shape — a steady run, a burst before
    cloud, a lone object — is legible from the spacing alone.
    """
    span = night["end_epoch"] - night["start_epoch"]
    if span <= 0:
        return [0.5 for _ in logs]
    return [
        round((log["epoch"] - night["start_epoch"]) / span, 4)
        for log in logs
        if log.get("epoch") is not None
    ]


def hour_marks(night: Dict[str, Any]) -> List[Tuple[float, str]]:
    """Whole-hour gridlines inside a night's span, as (fraction, label).

    Walks real hours -- absolute instants -- and reads the observer's
    clock at each one, rather than adding an hour to a local time. Across
    a DST fold those differ: the clock lives through 02 twice, and the
    strip should say so instead of quietly sliding an hour out of step.
    """
    span = night["end_epoch"] - night["start_epoch"]
    if span <= 0:
        return []

    zone = night["start"].tzinfo
    start = night["start"]
    # Distance to the next whole local hour, which is not always a whole
    # number of minutes from the start (zones like Asia/Kolkata run at
    # half-hour offsets, but their hour boundaries are still hour marks).
    into_hour = start.minute * 60 + start.second
    epoch = night["start_epoch"] + (3600 - into_hour if into_hour else 0)

    marks = []
    while epoch < night["end_epoch"]:
        fraction = (epoch - night["start_epoch"]) / span
        if fraction > 0:
            label = datetime.datetime.fromtimestamp(epoch, zone).strftime("%H")
            marks.append((round(fraction, 4), label))
        epoch += ONE_HOUR.total_seconds()
    return marks
