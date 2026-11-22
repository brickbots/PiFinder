"""
Unit tests for the SSD1333 frame path: ``ssd1333.display`` packs frames with
numpy and must send exactly the bytes luma's per-pixel ``color_device.display``
sends, for full frames, partial (diffed) frames, rotation and the gray scale
ceiling. No hardware: the driver talks to a recording serial stub.
"""

import random

import pytest
from luma.oled.device.color import color_device
from PIL import Image, ImageDraw

from PiFinder import ssd1333_device
from PiFinder.ssd1333_device import ssd1333

pytestmark = pytest.mark.unit


class RecordingSerial:
    """Serial interface stub that records every command and data write."""

    def __init__(self):
        self.writes = []

    def command(self, *cmd):
        self.writes.append(("cmd", list(cmd)))

    def data(self, data):
        self.writes.append(("data", list(data)))

    def cleanup(self):
        pass


def make_device(rotate=3):
    serial = RecordingSerial()
    device = ssd1333(serial, width=176, height=176, rotate=rotate, bgr=True)
    serial.writes.clear()
    return device, serial


def ui_frame(seed):
    """A menu-like frame: red text and shades on black, plus colored noise."""
    rng = random.Random(seed)
    image = Image.new("RGB", (176, 176))
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, 176, 20], fill=(64, 0, 0))
    for row in range(9):
        shade = rng.randrange(1, 256)
        draw.text((6, 24 + row * 16), f"Item {rng.random():.6f}", fill=(shade, 0, 0))
    for _ in range(200):
        xy = (rng.randrange(176), rng.randrange(176))
        image.putpixel(xy, tuple(rng.randrange(256) for _ in range(3)))
    return image


def send_frames(frames, rotate=3, ceiling=None, reference=False):
    device, serial = make_device(rotate)
    if ceiling is not None:
        device.gray_scale_ceiling(ceiling)
    for frame in frames:
        if reference:
            if device._gray_scale_lut is not None:
                frame = frame.point(device._gray_scale_lut)
            color_device.display(device, frame)
        else:
            device.display(frame)
    return serial.writes


def test_pack_rgb565_matches_luma_bit_layout():
    pixels = [(0, 0, 0), (255, 255, 255), (0xF8, 0, 0), (0, 0xFC, 0), (0, 0, 0xF8)]
    image = Image.new("RGB", (len(pixels), 1))
    image.putdata(pixels)
    packed = ssd1333_device.pack_rgb565(image)
    assert packed == bytes([0, 0, 0xFF, 0xFF, 0xF8, 0, 0x07, 0xE0, 0, 0x1F])


@pytest.mark.parametrize("rotate", [0, 3])
def test_full_frame_bytes_match_luma(rotate):
    frames = [ui_frame(1)]
    assert send_frames(frames, rotate) == send_frames(frames, rotate, reference=True)


def test_diffed_frames_match_luma():
    first = ui_frame(2)
    second = first.copy()
    ImageDraw.Draw(second).text((6, 60), "changed", fill=(200, 0, 0))
    frames = [first, second, second.copy(), ui_frame(3)]
    assert send_frames(frames) == send_frames(frames, reference=True)


@pytest.mark.parametrize("ceiling", [2, 5, 17, 30])
def test_gray_scale_ceiling_bytes_match_luma(ceiling):
    frames = [ui_frame(4), ui_frame(5)]
    assert send_frames(frames, ceiling=ceiling) == send_frames(
        frames, ceiling=ceiling, reference=True
    )
