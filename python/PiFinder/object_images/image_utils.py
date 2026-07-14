#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Shared image utility functions for object images

Provides common operations for:
- POSS survey images
- Generated Gaia star charts
"""

import math
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw, ImageChops

from PiFinder.ui import ui_utils


def rotation_radians(image_rotate: float) -> float:
    """Image rotation as a y-down pixel-space angle, in radians.

    PIL's Image.rotate() turns the image counterclockwise, which in
    y-down pixel coordinates is a rotation by the negated angle.
    """
    return math.radians(-image_rotate)


def cardinal_vectors(
    image_rotate: float, fx: int = 1, fy: int = 1
) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    """Return (nx, ny), (ex, ey) unit vectors for North and East.

    image_rotate: degrees the field image was rotated.
    fx, fy: -1 to mirror that axis (flip/flop), +1 otherwise.
    """
    theta = rotation_radians(image_rotate)
    n = (fx * math.sin(theta), fy * -math.cos(theta))
    e = (-fx * math.cos(theta), -fy * math.sin(theta))
    return n, e


def size_overlay_points(
    extents: List[float],
    pa: float,
    image_rotate: float,
    px_per_arcsec: float,
    cx: float,
    cy: float,
    fx: int = 1,
    fy: int = 1,
) -> Optional[List[Tuple[float, float]]]:
    """Compute outline points for the size overlay.

    Returns a list of (x, y) tuples.
    For 1 extent returns None (caller should use native ellipse).
    """
    if not extents or len(extents) == 1:
        return None

    theta = rotation_radians(image_rotate) - math.radians(pa + 90)
    cos_t = math.cos(theta)
    sin_t = math.sin(theta)

    points = []
    if len(extents) == 2:
        rx = extents[0] * px_per_arcsec / 2
        ry = extents[1] * px_per_arcsec / 2
        for i in range(36):
            t = 2 * math.pi * i / 36
            x = rx * math.cos(t)
            y = ry * math.sin(t)
            points.append(
                (cx + fx * (x * cos_t - y * sin_t), cy + fy * (x * sin_t + y * cos_t))
            )
    else:
        step = 2 * math.pi / len(extents)
        for i, ext in enumerate(extents):
            angle = i * step - math.pi / 2
            r = ext * px_per_arcsec / 2
            x = r * math.cos(angle)
            y = r * math.sin(angle)
            points.append(
                (cx + fx * (x * cos_t - y * sin_t), cy + fy * (x * sin_t + y * cos_t))
            )
    return points


def vertex_overlay_points(
    vertices: List[List[float]],
    obj_ra: float,
    obj_dec: float,
    image_rotate: float,
    px_per_arcsec: float,
    cx: float,
    cy: float,
    fx: int = 1,
    fy: int = 1,
) -> List[Tuple[float, float]]:
    """Project RA/Dec vertex pairs to pixel coords via gnomonic projection.

    vertices: list of [ra, dec] pairs in degrees.
    obj_ra, obj_dec: object center in degrees.
    Returns list of (x, y) pixel tuples.
    """
    theta = rotation_radians(image_rotate)
    cos_t = math.cos(theta)
    sin_t = math.sin(theta)

    ra0 = math.radians(obj_ra)
    dec0 = math.radians(obj_dec)
    cos_dec0 = math.cos(dec0)
    sin_dec0 = math.sin(dec0)

    points = []
    for ra_deg, dec_deg in vertices:
        ra = math.radians(ra_deg)
        dec = math.radians(dec_deg)
        cos_dec = math.cos(dec)
        sin_dec = math.sin(dec)
        dra = ra - ra0

        cos_c = sin_dec0 * sin_dec + cos_dec0 * cos_dec * math.cos(dra)
        if cos_c <= 0:
            continue
        # gnomonic: xi points East, eta points North (radians)
        xi = (cos_dec * math.sin(dra)) / cos_c
        eta = (cos_dec0 * sin_dec - sin_dec0 * cos_dec * math.cos(dra)) / cos_c

        # convert to arcsec offsets then pixels
        dx_arcsec = -xi * 206264.806  # negate: East is left on the survey image
        dy_arcsec = -eta * 206264.806  # negate: North is up, pixel y is down

        dx_px = dx_arcsec * px_per_arcsec
        dy_px = dy_arcsec * px_per_arcsec

        # apply image rotation
        rx = dx_px * cos_t - dy_px * sin_t
        ry = dx_px * sin_t + dy_px * cos_t

        points.append((cx + fx * rx, cy + fy * ry))
    return points


def project_radec_to_chart(
    ra_deg: float,
    dec_deg: float,
    center_ra: float,
    center_dec: float,
    fov: float,
    width: int,
    height: int,
    rotation: float,
) -> Tuple[float, float]:
    """Project one RA/Dec point to Gaia-chart pixel coordinates.

    Mirrors the tangent-plane projection in ``GaiaChartGenerator.render_chart``
    exactly (RA scaled by centre declination, East to the left, screen rotation
    by ``rotation`` degrees) so overlays land on the same pixels as the stars.
    Flip/flop are applied by the caller via ``Image.transpose`` after drawing.
    """
    ra = math.radians(ra_deg)
    dec = math.radians(dec_deg)
    cra = math.radians(center_ra)
    cdec = math.radians(center_dec)

    dra = ra - cra
    if dra > math.pi:
        dra -= 2 * math.pi
    elif dra < -math.pi:
        dra += 2 * math.pi
    ddec = dec - cdec

    x_proj = dra * math.cos(cdec)
    y_proj = ddec
    pixel_scale = width / math.radians(fov)

    x = width / 2.0 - x_proj * pixel_scale
    y = height / 2.0 - y_proj * pixel_scale

    if rotation:
        # Negated to match render_chart's screen-space rotation (y-down, same
        # visual direction as PIL.rotate / the POSS image).
        rot = math.radians(-rotation)
        cos_r = math.cos(rot)
        sin_r = math.sin(rot)
        x_rel = x - width / 2.0
        y_rel = y - height / 2.0
        x = (x_rel * cos_r - y_rel * sin_r) + width / 2.0
        y = (x_rel * sin_r + y_rel * cos_r) + height / 2.0

    return (x, y)


def extent_perimeter_polylines(
    center_ra: float,
    center_dec: float,
    size,
    steps: int = 48,
) -> List[List[List[float]]]:
    """Build RA/Dec polylines outlining a ``SizeObject``'s angular extent.

    Returns a list of polylines, each a list of ``[ra, dec]`` points in degrees:

    * stored vertices  -> the polyline as-is
    * stored segments  -> one 2-point polyline per segment
    * ``[d]``          -> a closed circle of diameter ``d``
    * ``[major, minor]`` -> a closed ellipse, position angle N through E
    * ``[r1, r2, ...]``  -> a closed polygon of radial spokes

    Numeric extents are stored in arcseconds. Empty near the poles where the RA
    scaling blows up, or when no usable extent is present.
    """
    if not size or not size.extents:
        return []
    if size.is_segments:
        return [list(seg) for seg in size.extents]
    if size.is_vertices:
        return [list(size.extents)]

    cos_dec0 = math.cos(math.radians(center_dec))
    if abs(cos_dec0) < 1e-6:
        return []

    pa = math.radians(size.position_angle)
    sin_pa = math.sin(pa)
    cos_pa = math.cos(pa)
    extents = size.extents

    # Local tangent-plane offsets in arcsec: East, North.
    offsets: List[Tuple[float, float]] = []
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
            phi = pa + i * step  # position angle of this spoke, N through E
            r = ext / 2.0
            offsets.append((r * math.sin(phi), r * math.cos(phi)))

    radec = [
        [center_ra + (e / 3600.0) / cos_dec0, center_dec + n / 3600.0]
        for e, n in offsets
    ]
    radec.append(radec[0])  # close the outline
    return [radec]


def add_orientation_overlays(
    image,
    display_class,
    catalog_object,
    fov,
    image_rotate,
    fx=1,
    fy=1,
    show_nsew=True,
    show_bbox=True,
):
    """Draw NSEW cardinal labels and the object size box on a field image.

    Restores the image_nsew / image_bbox behaviour for the object_images
    backend. Operates on the square field image (display_class.fov_res),
    before any padding, with the centre at fov_res / 2.
    """
    if not (show_nsew or show_bbox):
        return image

    draw = ImageDraw.Draw(image)
    cx = display_class.fov_res / 2
    cy = display_class.fov_res / 2

    # NSEW cardinal labels — show the leftmost and rightmost of the four
    # cardinals out at the FOV ring, clamped clear of the titlebar/footer.
    if show_nsew:
        (nx, ny), (ex, ey) = cardinal_vectors(image_rotate, fx, fy)
        label_font = display_class.fonts.base
        label_color = display_class.colors.get(128)
        r_label = display_class.fov_res / 2 - 2
        top_limit = display_class.titlebar_height + label_font.height
        bottom_limit = display_class.fov_res - label_font.height * 2
        candidates = [
            ("N", nx, ny),
            ("S", -nx, -ny),
            ("E", ex, ey),
            ("W", -ex, -ey),
        ]
        by_x = sorted(candidates, key=lambda c: c[1])
        for label, dx, dy in (by_x[0], by_x[-1]):
            lx = cx + dx * r_label - label_font.width / 2
            ly = cy + dy * r_label - label_font.height / 2
            lx = max(0, min(lx, display_class.fov_res - label_font.width))
            ly = max(top_limit, min(ly, bottom_limit))
            ui_utils.shadow_outline_text(
                draw,
                (lx, ly),
                label,
                font=label_font,
                align="left",
                fill=label_color,
                shadow_color=display_class.colors.get(0),
                outline=1,
            )

    # Size overlay
    size = getattr(catalog_object, "size", None)
    extents = size.extents if size else None
    if show_bbox and extents and fov > 0:
        px_per_arcsec = display_class.fov_res / (fov * 3600)
        overlay_color = display_class.colors.get(100)

        if size.is_vertices:
            points = vertex_overlay_points(
                extents,
                catalog_object.ra,
                catalog_object.dec,
                image_rotate,
                px_per_arcsec,
                cx,
                cy,
                fx,
                fy,
            )
            if len(points) >= 2:
                draw.line(points, fill=overlay_color, width=1)
        elif len(extents) == 1:
            r = extents[0] * px_per_arcsec / 2
            draw.ellipse(
                [cx - r, cy - r, cx + r, cy + r],
                outline=overlay_color,
                width=1,
            )
        else:
            points = size_overlay_points(
                extents,
                size.position_angle,
                image_rotate,
                px_per_arcsec,
                cx,
                cy,
                fx,
                fy,
            )
            if points:
                draw.polygon(points, outline=overlay_color)

    return image


def add_image_overlays(
    image,
    display_class,
    fov,
    magnification,
    eyepiece,
    burn_in=True,
    limiting_magnitude=None,
):
    """
    Add FOV/magnification/eyepiece overlays to image

    This function is shared by:
    - POSS image display (poss_provider.py)
    - Generated Gaia star charts (chart_provider.py)

    Args:
        image: PIL Image to modify
        display_class: Display configuration object
        fov: Field of view in degrees
        magnification: Telescope magnification
        eyepiece: Active eyepiece object
        burn_in: Whether to add overlays (default True)
        limiting_magnitude: Optional limiting magnitude to display (for generated charts)

    Returns:
        Modified PIL Image with overlays added
    """
    if not burn_in:
        return image

    draw = ImageDraw.Draw(image)

    # Top-left: FOV in degrees
    ui_utils.shadow_outline_text(
        draw,
        (1, display_class.titlebar_height - 1),
        f"{fov:0.2f}°",
        font=display_class.fonts.base,
        align="left",
        fill=display_class.colors.get(254),
        shadow_color=display_class.colors.get(0),
        outline=2,
    )

    # Top-right: Magnification
    mag_text = f"{magnification:.0f}x" if magnification and magnification > 0 else "?x"
    ui_utils.shadow_outline_text(
        draw,
        (
            display_class.resX - (display_class.fonts.base.width * 4),
            display_class.titlebar_height - 1,
        ),
        mag_text,
        font=display_class.fonts.base,
        align="right",
        fill=display_class.colors.get(254),
        shadow_color=display_class.colors.get(0),
        outline=2,
    )

    # Top-center: Limiting magnitude (for generated charts)
    if limiting_magnitude is not None:
        # Show ">17" if exceeds catalog limit, otherwise show actual value
        if limiting_magnitude > 17.0:
            lm_text = "LM:>17"
        else:
            lm_text = f"LM:{limiting_magnitude:.1f}"
        lm_bbox = draw.textbbox((0, 0), lm_text, font=display_class.fonts.base.font)
        lm_width = lm_bbox[2] - lm_bbox[0]
        lm_x = (display_class.resX - lm_width) // 2

        ui_utils.shadow_outline_text(
            draw,
            (lm_x, display_class.titlebar_height - 1),
            lm_text,
            font=display_class.fonts.base,
            align="left",
            fill=display_class.colors.get(254),
            shadow_color=display_class.colors.get(0),
            outline=2,
        )

    # Bottom-left: Eyepiece name
    if eyepiece:
        eyepiece_text = f"{eyepiece.focal_length_mm:.0f}mm {eyepiece.name}"
        ui_utils.shadow_outline_text(
            draw,
            (1, display_class.resY - (display_class.fonts.base.height * 1.1)),
            eyepiece_text,
            font=display_class.fonts.base,
            align="left",
            fill=display_class.colors.get(128),  # Dimmer than FOV/mag
            shadow_color=display_class.colors.get(0),
            outline=2,
        )

    return image


def create_loading_image(
    display_class, message="Loading...", progress_text=None, progress_percent=0
):
    """
    Create a placeholder image with loading message and optional progress

    Args:
        display_class: Display configuration object
        message: Main text to display (default "Loading...")
        progress_text: Optional progress status text
        progress_percent: Progress percentage (0-100)

    Returns:
        PIL Image with centered message and progress
    """
    image = Image.new("RGB", display_class.resolution, (0, 0, 0))
    draw = ImageDraw.Draw(image)

    # Use center of display for positioning
    center_x = display_class.resolution[0] // 2
    center_y = display_class.resolution[1] // 2

    # Draw main message
    text_bbox = draw.textbbox((0, 0), message, font=display_class.fonts.large.font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]

    x = center_x - (text_width // 2)
    y = center_y - (text_height // 2) - 20

    draw.text(
        (x, y),
        message,
        font=display_class.fonts.large.font,
        fill=(128, 0, 0),  # Medium red for night vision
    )

    # Draw progress text if provided
    if progress_text:
        progress_bbox = draw.textbbox(
            (0, 0), progress_text, font=display_class.fonts.base.font
        )
        progress_width = progress_bbox[2] - progress_bbox[0]

        px = center_x - (progress_width // 2)
        py = y + text_height + 8

        draw.text(
            (px, py),
            progress_text,
            font=display_class.fonts.base.font,
            fill=(100, 0, 0),  # Dimmer red
        )

    # Draw progress bar if percentage > 0
    if progress_percent > 0:
        bar_width = int(display_class.resolution[0] * 0.8)
        bar_height = 4
        bar_x = center_x - (bar_width // 2)
        bar_y = display_class.resolution[1] - 25

        # Background bar
        draw.rectangle(
            [bar_x, bar_y, bar_x + bar_width, bar_y + bar_height],
            outline=(64, 0, 0),
            fill=(32, 0, 0),
        )

        # Progress fill
        fill_width = int(bar_width * (progress_percent / 100))
        if fill_width > 0:
            draw.rectangle(
                [bar_x, bar_y, bar_x + fill_width, bar_y + bar_height], fill=(128, 0, 0)
            )

        # Percentage text
        percent_text = f"{progress_percent}%"
        percent_bbox = draw.textbbox(
            (0, 0), percent_text, font=display_class.fonts.base.font
        )
        percent_width = percent_bbox[2] - percent_bbox[0]

        draw.text(
            (center_x - (percent_width // 2), bar_y + bar_height + 4),
            percent_text,
            font=display_class.fonts.base.font,
            fill=(100, 0, 0),
        )

    return image


def create_no_image_placeholder(display_class, burn_in=True):
    """
    Create a "No Image" placeholder

    Used when neither POSS nor Gaia chart is available

    Args:
        display_class: Display configuration object
        burn_in: Whether to add text (default True)

    Returns:
        PIL Image with "No Image" message
    """
    image = Image.new("RGB", display_class.resolution)
    if burn_in:
        draw = ImageDraw.Draw(image)
        draw.text(
            (30, 50),
            "No Image",
            font=display_class.fonts.large.font,
            fill=display_class.colors.get(128),
        )
    return image


def apply_circular_vignette(image, display_class):
    """
    Apply circular vignette to show eyepiece FOV boundary

    Creates a circular mask that dims everything outside
    the eyepiece field of view, then adds a subtle outline.

    Args:
        image: PIL Image to modify
        display_class: Display configuration object

    Returns:
        Modified PIL Image with circular vignette
    """
    # Create dimming mask (circle is full brightness, outside is dimmed)
    _circle_dim = Image.new(
        "RGB",
        (display_class.fov_res, display_class.fov_res),
        display_class.colors.get(127),  # Dim the outside
    )
    _circle_draw = ImageDraw.Draw(_circle_dim)
    _circle_draw.ellipse(
        [2, 2, display_class.fov_res - 2, display_class.fov_res - 2],
        fill=display_class.colors.get(255),  # Full brightness inside
    )

    # Apply dimming by multiplying
    image = ImageChops.multiply(image, _circle_dim)

    # Add subtle outline
    draw = ImageDraw.Draw(image)
    draw.ellipse(
        [2, 2, display_class.fov_res - 2, display_class.fov_res - 2],
        outline=display_class.colors.get(64),
        width=1,
    )

    return image


def pad_to_display_resolution(image, display_class):
    """
    Pad image to match display resolution

    If FOV resolution differs from display resolution,
    centers the image and pads with black.

    Args:
        image: PIL Image to pad
        display_class: Display configuration object

    Returns:
        Padded PIL Image at display resolution
    """
    # Pad horizontally if needed
    if display_class.fov_res != display_class.resX:
        pad_image = Image.new("RGB", display_class.resolution)
        pad_image.paste(
            image,
            (
                int((display_class.resX - display_class.fov_res) / 2),
                0,
            ),
        )
        image = pad_image

    # Pad vertically if needed
    if display_class.fov_res != display_class.resY:
        pad_image = Image.new("RGB", display_class.resolution)
        pad_image.paste(
            image,
            (
                0,
                int((display_class.resY - display_class.fov_res) / 2),
            ),
        )
        image = pad_image

    return image
