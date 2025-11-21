#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Shared image utility functions for POSS/SDSS images and generated charts
"""

from PIL import Image, ImageDraw


def add_image_overlays(
    image, display_class, fov, magnification, eyepiece, burn_in=True, limiting_magnitude=None
):
    """
    Add FOV/magnification/eyepiece overlays to image

    This function is shared by:
    - POSS/SDSS image display (cat_images.py)
    - Generated deep star charts (deep_chart.py)

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

    from PiFinder.ui import ui_utils

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


def create_loading_image(display_class, message="Loading...", progress_text=None, progress_percent=0):
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
    image = Image.new(
        "RGB", (display_class.fov_res, display_class.fov_res), (0, 0, 0)
    )
    draw = ImageDraw.Draw(image)

    # Draw main message
    text_bbox = draw.textbbox((0, 0), message, font=display_class.fonts.large.font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]

    x = (display_class.fov_res - text_width) // 2
    y = (display_class.fov_res - text_height) // 2 - 10

    draw.text(
        (x, y),
        message,
        font=display_class.fonts.large.font,
        fill=(128, 0, 0),  # Medium red for night vision
    )

    # Draw progress text if provided
    if progress_text:
        progress_bbox = draw.textbbox((0, 0), progress_text, font=display_class.fonts.base.font)
        progress_width = progress_bbox[2] - progress_bbox[0]

        px = (display_class.fov_res - progress_width) // 2
        py = y + text_height + 8

        draw.text(
            (px, py),
            progress_text,
            font=display_class.fonts.base.font,
            fill=(100, 0, 0),  # Dimmer red
        )

    # Draw progress bar if percentage > 0
    if progress_percent > 0:
        bar_width = int(display_class.fov_res * 0.6)
        bar_height = 4
        bar_x = (display_class.fov_res - bar_width) // 2
        bar_y = display_class.fov_res - 20

        # Background bar
        draw.rectangle(
            [bar_x, bar_y, bar_x + bar_width, bar_y + bar_height],
            outline=(64, 0, 0),
            fill=(32, 0, 0)
        )

        # Progress fill
        fill_width = int(bar_width * (progress_percent / 100))
        if fill_width > 0:
            draw.rectangle(
                [bar_x, bar_y, bar_x + fill_width, bar_y + bar_height],
                fill=(128, 0, 0)
            )

        # Percentage text
        percent_text = f"{progress_percent}%"
        percent_bbox = draw.textbbox((0, 0), percent_text, font=display_class.fonts.base.font)
        percent_width = percent_bbox[2] - percent_bbox[0]

        draw.text(
            ((display_class.fov_res - percent_width) // 2, bar_y + bar_height + 4),
            percent_text,
            font=display_class.fonts.base.font,
            fill=(100, 0, 0)
        )

    return image
