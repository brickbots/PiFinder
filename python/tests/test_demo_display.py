"""Unit tests for the demo display (PiFinder.demo_display)."""

import io
import shutil
import subprocess

import pygame
import pytest
from PIL import Image

from PiFinder.demo_display import (
    ALT,
    LONG,
    PRESS,
    DemoDevice,
    DemoLayout,
    Recorder,
    glows_for_key,
    keycode_for_click,
)
from PiFinder.keyboard_interface import KeyboardInterface

pytestmark = pytest.mark.unit


@pytest.fixture
def device(monkeypatch):
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    device = DemoDevice((128, 128))
    yield device
    device.cleanup()
    pygame.quit()


def test_glows_for_a_press_a_long_press_and_an_alt_chord():
    assert glows_for_key(5) == [("5", PRESS)]
    assert glows_for_key(KeyboardInterface.PLUS) == [("PLUS", PRESS)]
    assert glows_for_key(KeyboardInterface.LNG_SQUARE) == [("SQUARE", LONG)]
    assert glows_for_key(KeyboardInterface.ALT_UP) == [("SQUARE", ALT), ("UP", ALT)]
    assert glows_for_key(KeyboardInterface.ALT_SQUARE) == [("SQUARE", ALT)]


def test_no_glow_for_a_key_with_no_button_in_the_photo():
    assert glows_for_key(KeyboardInterface.POWER_BTN) == []
    assert glows_for_key(KeyboardInterface.NA) == []


def test_keycode_for_click():
    assert keycode_for_click("7", long_press=False, alt=False) == 7
    assert (
        keycode_for_click("LEFT", long_press=True, alt=False)
        == KeyboardInterface.LNG_LEFT
    )
    assert (
        keycode_for_click("MINUS", long_press=False, alt=True)
        == KeyboardInterface.ALT_MINUS
    )
    # No long press on a digit, and no ALT chord on 5: a plain press.
    assert keycode_for_click("5", long_press=True, alt=False) == 5
    assert keycode_for_click("5", long_press=False, alt=True) == 5


def test_layout_has_every_keypad_button_inside_the_photo():
    layout = DemoLayout.load()
    width, height = Image.open(layout.background).size
    names = {"UP", "DOWN", "LEFT", "RIGHT", "SQUARE", "PLUS", "MINUS"}
    assert set(layout.buttons) == names | {str(digit) for digit in range(10)}
    for x, y in layout.buttons.values():
        assert 0 <= x < width and 0 <= y < height
    x, y, w, h = layout.screen
    assert 0 <= x and x + w <= width and 0 <= y and y + h <= height


def test_button_at_finds_the_nearest_button_within_the_radius():
    layout = DemoLayout.load()
    x, y = layout.buttons["8"]
    assert layout.button_at((x + 3, y - 2)) == "8"
    assert layout.button_at((5, 5)) is None


def test_recorder_repeats_frames_to_keep_the_wall_clock_rate():
    stream = io.BytesIO()
    recorder = Recorder(stream, fps=10, start=0.0)
    recorder.write(b"a", now=0.0)
    recorder.write(b"b", now=0.05)  # same frame slot: nothing new
    recorder.write(b"c", now=0.45)  # four slots later
    assert stream.getvalue() == b"acccc"


def test_ui_image_goes_into_the_screen_area(device):
    device.display(Image.new("RGB", (128, 128), (255, 0, 0)))
    x, y, w, h = device.layout.screen
    assert device.window.get_at((x + w // 2, y + h // 2))[:3] == (255, 0, 0)


def test_hidden_screen_is_black(device):
    device.display(Image.new("RGB", (128, 128), (255, 0, 0)))
    device.hide()
    device.draw()
    x, y, w, h = device.layout.screen
    assert device.window.get_at((x + w // 2, y + h // 2))[:3] == (0, 0, 0)


def test_pressed_button_glows_and_the_glow_fades(device):
    device.display(Image.new("RGB", (128, 128)))
    pos = device.layout.buttons["5"]
    before = device.window.get_at(pos)

    device.show_key(5, now=100.0)
    device.draw(now=100.0)
    glowing = device.window.get_at(pos)
    assert glowing.r > before.r + 50

    device.draw(now=101.0)
    assert device.glows == {}
    assert device.window.get_at(pos) == before


def test_click_on_a_button_gives_its_keycode(device):
    x, y = device.layout.buttons["UP"]
    click = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(x, y))
    right_click = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=3, pos=(x, y))
    miss = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(5, 5))
    assert device.keycode_for_event(click) == KeyboardInterface.UP
    assert device.keycode_for_event(right_click) == KeyboardInterface.LNG_UP
    assert device.keycode_for_event(miss) is None


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_recording_makes_a_video_file(device, tmp_path):
    path = tmp_path / "demo.mp4"
    device.start_recording(path)
    device.recorder.start -= 1.0  # one second of video
    device.display(Image.new("RGB", (128, 128), (255, 0, 0)))
    device.cleanup()

    assert path.stat().st_size > 0
    if shutil.which("ffprobe") is not None:
        frames = subprocess.run(
            ["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0"]
            + ["-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(path)],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        assert 31 <= int(frames) <= 33
