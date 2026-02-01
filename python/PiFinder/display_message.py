#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Display a message on the PiFinder screen

Usage:
    python -m PiFinder.display_message "Your message here"
    python -m PiFinder.display_message "Line 1" "Line 2" "Line 3"

Or directly:
    cd /home/grimaldi/Projects/PiFinder/PiFinder/python
    python PiFinder/display_message.py "Your message here"
"""

import sys
import argparse
from PIL import Image, ImageDraw
from PiFinder import displays
from PiFinder import config


def display_message(lines, brightness=255, display_type=None):
    """
    Display one or more lines of text on the PiFinder screen.

    Args:
        lines: List of text lines to display
        brightness: Display brightness (0-255)
        display_type: Display hardware type ('ssd1351', 'st7789', 'pg_128', 'pg_320')
                     If None, defaults to 'ssd1351' (standard PiFinder OLED)
    """
    # Default to ssd1351 if not specified (standard PiFinder hardware)
    if display_type is None:
        display_type = "ssd1351"

    # Initialize display
    display = displays.get_display(display_type)
    display.set_brightness(brightness)

    # Get colors object from display
    colors = display.colors

    # Create blank image
    screen = Image.new("RGB", display.resolution, color=(0, 0, 0))
    draw = ImageDraw.Draw(screen)

    # Calculate text positioning
    # Start from top with some padding
    y_offset = 20
    line_spacing = display.fonts.base.height + 5

    # Use different font sizes based on number of lines and text length
    if len(lines) == 1 and len(lines[0]) < 20:
        # Single short message - use large font
        font = display.fonts.large.font
        line_spacing = display.fonts.large.height + 8
    elif len(lines) <= 3:
        # Few lines - use base font
        font = display.fonts.base.font
    else:
        # Many lines - use small font to fit more
        font = display.fonts.small.font
        line_spacing = display.fonts.small.height + 3

    # Draw each line of text
    for i, line in enumerate(lines):
        y_pos = y_offset + (i * line_spacing)

        # Wrap long lines if needed
        max_width = display.resolution[0] - 10  # 5px padding on each side

        # Simple word wrapping
        words = line.split()
        current_line = ""

        for word in words:
            test_line = current_line + (" " if current_line else "") + word
            bbox = draw.textbbox((0, 0), test_line, font=font)
            text_width = bbox[2] - bbox[0]

            if text_width <= max_width:
                current_line = test_line
            else:
                # Draw current line and start new one
                if current_line:
                    draw.text((5, y_pos), current_line, font=font, fill=colors.get(255))
                    y_pos += line_spacing
                current_line = word

        # Draw remaining text
        if current_line:
            draw.text((5, y_pos), current_line, font=font, fill=colors.get(255))

    # Display the image
    display.device.display(screen.convert(display.device.mode))

    return display


def main():
    parser = argparse.ArgumentParser(
        description="Display a message on the PiFinder screen",
        epilog="""
Examples:
  %(prog)s "Hello World"
  %(prog)s "Line 1" "Line 2" "Line 3"
  %(prog)s --brightness 200 "Bright message"
  %(prog)s --display st7789 "Message for LCD"
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument(
        "message",
        nargs="+",
        help="Message text (multiple arguments will be displayed on separate lines)"
    )

    parser.add_argument(
        "-b", "--brightness",
        type=int,
        default=125,
        help="Display brightness (0-255, default: 125)"
    )

    parser.add_argument(
        "-d", "--display",
        choices=["ssd1351", "st7789", "pg_128", "pg_320"],
        help="Display hardware type (auto-detected from config if not specified)"
    )

    args = parser.parse_args()

    # Validate brightness
    if not 0 <= args.brightness <= 255:
        print("Error: Brightness must be between 0 and 255")
        sys.exit(1)

    # Display the message
    try:
        display_message(args.message, brightness=args.brightness, display_type=args.display)
        print(f"Message displayed successfully on {args.display or 'auto-detected'} display")
    except Exception as e:
        print(f"Error displaying message: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
