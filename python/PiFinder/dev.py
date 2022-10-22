#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is the main entry point for PiFinder it:
* Initializes the display
* Spawns keyboard process
* Sets up time/location via GPS
* Spawns camers/solver process
* then runs the UI loop

"""
from PIL import Image, ImageDraw, ImageFont, ImageChops, ImageOps
from time import sleep

from luma.core.interface.serial import spi
from luma.core.render import canvas
from luma.oled.device import ssd1351


serial = spi(device=0, port=0)
device = ssd1351(serial)

# setup red filtering image
RED = (0, 0, 255)
red_image = Image.new("RGB", (128, 128), RED)

gamma_value = 1


def set_brightness(level):
    """
    Sets oled brightness
    0-255
    """
    device.contrast(level)


def show_image(image_obj):
    image_obj = ImageChops.multiply(image_obj, red_image)
    device.display(image_obj.convert(device.mode))


def gamma(in_value):
    in_value = float(in_value) / 255
    out_value = pow(in_value, gamma_value)
    out_value = int(255 * out_value)

    return out_value


def main():
    """
    Get this show on the road!
    """
    global gamma_value
    # init screen
    console_font = ImageFont.load_default()
    console_screen = Image.new("RGB", (128, 128))
    console_draw = ImageDraw.Draw(console_screen)
    console_draw.text((10, 10), "Starting", font=console_font, fill=RED)
    device.display(console_screen.convert(device.mode))

    # load image
    test_image = Image.open("dbe03402.bmp")
    resize_image = test_image.resize((128, 128))
    resize_image = ImageOps.autocontrast(resize_image)
    show_image(resize_image)
    f = input()
    while True:
        gamma_image = Image.eval(resize_image, gamma)
        show_image(ImageOps.autocontrast(gamma_image))
        gamma_value = float(input())


if __name__ == "__main__":
    main()
