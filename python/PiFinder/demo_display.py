"""
Demo display: the PiFinder screen inside a photo of the device.

The window shows the photo, puts the live UI into the screen area and makes
each pressed button glow. A click on a button in the photo presses that key.
The window can also go to an MP4 file through ffmpeg. This makes instruction
videos with no screen recorder and no overlay tool.

The photo and the button positions are in ``images/demo_display/``. Edit the
positions with ``python/tools/demo_layout_editor.py``.
See docs/adr/0044-demo-display-in-process.md.
"""

import json
import logging
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Optional

import pygame
from luma.core.device import dummy
from PIL import Image

from PiFinder import utils
from PiFinder.keyboard_interface import KeyboardInterface

logger = logging.getLogger("Display.Demo")

LAYOUT_PATH = utils.pifinder_dir / "images" / "demo_display" / "layout.json"

FRAME_RATE = 30
GLOW_SECONDS = 0.8

# Glow types. A press is red, a long press is orange, and an ALT chord
# (SQUARE + key) is blue on both buttons.
PRESS = "press"
LONG = "long"
ALT = "alt"
GLOW_COLORS = {
    PRESS: (255, 80, 80),
    LONG: (255, 180, 50),
    ALT: (100, 200, 255),
}

PRESS_KEYS = {
    "PLUS": KeyboardInterface.PLUS,
    "MINUS": KeyboardInterface.MINUS,
    "SQUARE": KeyboardInterface.SQUARE,
    "LEFT": KeyboardInterface.LEFT,
    "UP": KeyboardInterface.UP,
    "DOWN": KeyboardInterface.DOWN,
    "RIGHT": KeyboardInterface.RIGHT,
    **{str(digit): digit for digit in range(10)},
}
LONG_KEYS = {
    "LEFT": KeyboardInterface.LNG_LEFT,
    "UP": KeyboardInterface.LNG_UP,
    "DOWN": KeyboardInterface.LNG_DOWN,
    "RIGHT": KeyboardInterface.LNG_RIGHT,
    "SQUARE": KeyboardInterface.LNG_SQUARE,
}
ALT_KEYS = {
    "PLUS": KeyboardInterface.ALT_PLUS,
    "MINUS": KeyboardInterface.ALT_MINUS,
    "LEFT": KeyboardInterface.ALT_LEFT,
    "UP": KeyboardInterface.ALT_UP,
    "DOWN": KeyboardInterface.ALT_DOWN,
    "RIGHT": KeyboardInterface.ALT_RIGHT,
    "SQUARE": KeyboardInterface.ALT_SQUARE,
    "0": KeyboardInterface.ALT_0,
}

_GLOWS_BY_KEY: dict[int, list[tuple[str, str]]] = {}
for _name, _code in PRESS_KEYS.items():
    _GLOWS_BY_KEY[_code] = [(_name, PRESS)]
for _name, _code in LONG_KEYS.items():
    _GLOWS_BY_KEY[_code] = [(_name, LONG)]
for _name, _code in ALT_KEYS.items():
    _GLOWS_BY_KEY[_code] = [("SQUARE", ALT)] + (
        [] if _name == "SQUARE" else [(_name, ALT)]
    )


def glows_for_key(keycode: int) -> list[tuple[str, str]]:
    """The (button, glow type) pairs that show a keycode. Empty for a
    keycode with no button in the photo, for example POWER_BTN."""
    return _GLOWS_BY_KEY.get(keycode, [])


def keycode_for_click(button: str, long_press: bool, alt: bool) -> Optional[int]:
    """The keycode for a click on a button in the photo. A long press or an
    ALT chord falls back to a plain press on a button that has none."""
    if long_press and button in LONG_KEYS:
        return LONG_KEYS[button]
    if alt and button in ALT_KEYS:
        return ALT_KEYS[button]
    return PRESS_KEYS.get(button)


@dataclass
class DemoLayout:
    background: Path
    screen: tuple[int, int, int, int]
    buttons: dict[str, tuple[int, int]]
    button_radius: int

    @classmethod
    def load(cls, path: Path = LAYOUT_PATH) -> "DemoLayout":
        with open(path) as layout_file:
            data = json.load(layout_file)
        return cls(
            background=path.parent / data["background"],
            screen=tuple(data["screen"]),
            buttons={name: tuple(pos) for name, pos in data["buttons"].items()},
            button_radius=data["button_radius"],
        )

    def save(self, path: Path = LAYOUT_PATH) -> None:
        data = {
            "background": self.background.name,
            "screen": list(self.screen),
            "button_radius": self.button_radius,
            "buttons": {name: list(pos) for name, pos in self.buttons.items()},
        }
        with open(path, "w") as layout_file:
            json.dump(data, layout_file, indent=2)
            layout_file.write("\n")

    def button_at(self, pos: tuple[int, int]) -> Optional[str]:
        """The button under a window position, or None."""
        best, best_dist = None, self.button_radius**2
        for name, (x, y) in self.buttons.items():
            dist = (pos[0] - x) ** 2 + (pos[1] - y) ** 2
            if dist <= best_dist:
                best, best_dist = name, dist
        return best


class Recorder:
    """Writes frames to a video stream at a fixed frame rate.

    The main loop does not run at an exact rate, so each write repeats the
    frame until the frame count agrees with the wall clock. The video length
    is then the real time, and a sound track from the same start agrees.
    """

    def __init__(
        self, stream: IO[bytes], fps: int = FRAME_RATE, start: Optional[float] = None
    ):
        self.stream = stream
        self.fps = fps
        self.start = time.monotonic() if start is None else start
        self.frames = 0
        self.process: Optional[subprocess.Popen] = None

    @classmethod
    def ffmpeg(
        cls, path: Path, size: tuple[int, int], audio: bool = False
    ) -> "Recorder":
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            raise RuntimeError(
                "Recording needs ffmpeg on the PATH. On Nix, run PiFinder "
                "in 'nix shell nixpkgs#ffmpeg-headless'."
            )
        cmd = [ffmpeg, "-y", "-loglevel", "error"]
        cmd += ["-thread_queue_size", "64", "-f", "rawvideo", "-pix_fmt", "rgb24"]
        cmd += ["-s", f"{size[0]}x{size[1]}", "-r", str(FRAME_RATE), "-i", "-"]
        if audio:
            cmd += ["-thread_queue_size", "1024", "-f", "pulse", "-i", "default"]
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18"]
        cmd += ["-pix_fmt", "yuv420p"]
        if audio:
            cmd += ["-c:a", "aac", "-b:a", "160k", "-shortest"]
        cmd.append(str(path))
        # A new session keeps Ctrl+C in the terminal away from ffmpeg. The
        # file then ends when PiFinder closes the pipe, not before.
        process = subprocess.Popen(cmd, stdin=subprocess.PIPE, start_new_session=True)
        assert process.stdin is not None
        recorder = cls(process.stdin)
        recorder.process = process
        logger.info("Recording to %s", path)
        return recorder

    def write(self, frame: bytes, now: Optional[float] = None) -> None:
        now = time.monotonic() if now is None else now
        due = int((now - self.start) * self.fps) + 1
        while self.frames < due:
            self.stream.write(frame)
            self.frames += 1

    def close(self) -> None:
        self.stream.close()
        if self.process is not None:
            self.process.wait(timeout=60)
            logger.info("Recording closed, %d frames", self.frames)


def _glow_surface(radius: int, color: tuple[int, int, int]) -> pygame.Surface:
    size = radius * 4
    surface = pygame.Surface((size, size), pygame.SRCALPHA)
    for r in range(radius * 2, 0, -1):
        alpha = int(180 * (1 - (r / (radius * 2)) ** 1.5))
        pygame.draw.circle(surface, (*color, alpha), (size // 2, size // 2), r)
    return surface


class DemoDevice(dummy):
    """A luma device that draws the UI into a photo of the PiFinder.

    ``display()`` keeps the UI image and draws the window. ``tick()`` draws it
    again, so that the glows fade and the recording keeps its rate while the
    UI sends no new frame.
    """

    def __init__(
        self, resolution: tuple[int, int], layout: Optional[DemoLayout] = None
    ):
        super().__init__(width=resolution[0], height=resolution[1], mode="RGB")
        self.layout = layout or DemoLayout.load()
        pygame.init()
        background = pygame.image.load(str(self.layout.background))
        self.window = pygame.display.set_mode(background.get_size())
        pygame.display.set_caption("PiFinder")
        self.background = background.convert()
        self.glow_images = {
            kind: _glow_surface(self.layout.button_radius, color)
            for kind, color in GLOW_COLORS.items()
        }
        # button name -> (press time, glow type)
        self.glows: dict[str, tuple[float, str]] = {}
        self.screen_on = True
        self.recorder: Optional[Recorder] = None

    def display(self, image: Image.Image) -> None:
        super().display(image)
        self.draw()

    def show(self) -> None:
        self.screen_on = True

    def hide(self) -> None:
        self.screen_on = False

    def show_key(self, keycode: int, now: Optional[float] = None) -> None:
        now = time.monotonic() if now is None else now
        for button, kind in glows_for_key(keycode):
            self.glows[button] = (now, kind)

    def keycode_for_event(self, event: pygame.event.Event) -> Optional[int]:
        """Right click is a long press. Ctrl + click is an ALT chord."""
        if event.type != pygame.MOUSEBUTTONDOWN or event.button not in (1, 3):
            return None
        button = self.layout.button_at(event.pos)
        if button is None:
            return None
        alt = bool(pygame.key.get_mods() & pygame.KMOD_CTRL)
        return keycode_for_click(button, long_press=event.button == 3, alt=alt)

    def tick(self) -> None:
        if self.glows or self.recorder is not None:
            self.draw()

    def draw(self, now: Optional[float] = None) -> None:
        now = time.monotonic() if now is None else now
        self.window.blit(self.background, (0, 0))
        x, y, w, h = self.layout.screen
        if not self.screen_on:
            self.window.fill((0, 0, 0), (x, y, w, h))
        elif self.image is not None:
            ui = pygame.image.frombytes(self.image.tobytes(), self.image.size, "RGB")
            self.window.blit(pygame.transform.smoothscale(ui, (w, h)), (x, y))

        for button, (pressed, kind) in list(self.glows.items()):
            fade = 1.0 - (now - pressed) / GLOW_SECONDS
            if fade <= 0:
                del self.glows[button]
                continue
            glow = self.glow_images[kind]
            glow.set_alpha(int(255 * fade))
            bx, by = self.layout.buttons[button]
            self.window.blit(
                glow, (bx - glow.get_width() // 2, by - glow.get_height() // 2)
            )

        pygame.display.flip()
        pygame.event.pump()
        if self.recorder is not None:
            try:
                self.recorder.write(pygame.image.tobytes(self.window, "RGB"), now)
            except BrokenPipeError:
                logger.error("ffmpeg stopped, recording ended")
                self.recorder = None

    def start_recording(self, path: Path, audio: bool = False) -> None:
        """Start after the last child process is forked. A child forked
        later keeps the ffmpeg pipe open, and the file does not end."""
        self.recorder = Recorder.ffmpeg(path, self.window.get_size(), audio)

    def cleanup(self) -> None:
        """Ends the recording. luma also calls this at exit."""
        if self.recorder is not None:
            self.recorder.close()
            self.recorder = None
