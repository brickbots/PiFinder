"""Recovery mode: the Software screen alone (ADR 0038).

pifinder.service runs this module in place of PiFinder.main when the
recovery flag exists (see PiFinder.recovery_hold). The app has the display,
the keypad and the Software screen (UISoftware). It starts no camera,
solver, IMU, GPS, integrator, web server or sound process.

The Software screen shows the local generations first (Rollback), with a
mark on the confirmed ones, then the internet channels. A pick goes through
the normal upgrade (PiFinder.nixos_upgrade): it becomes the boot default and
the Pi restarts.

The app sends READY=1 after its first frame, so the boot watchdog checks its
health like the health of the normal app. On rev4 a thread reads the battery
charger, so the screen offers Install only on USB-C power.
"""

import argparse
import gettext
import logging
import os
import queue
import sys
import threading
import time
import traceback
from multiprocessing import Process, Queue
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

import PiFinder.i18n  # noqa: F401
from PiFinder import config, hardware_detect, lazy_import, utils
from PiFinder.battery_bq25895 import BQ25895, POLL_INTERVAL
from PiFinder.catalogs import Catalogs
from PiFinder.displays import DisplayBase, get_display
from PiFinder.keyboard_interface import KeyboardInterface
from PiFinder.multiproclogging import MultiprocLogging
from PiFinder.state import UIState
from PiFinder.types.hardware import BatteryState, HardwareCapabilities
from PiFinder.ui.base import UIModule
from PiFinder.ui.software import UISoftware

try:
    from rpi_hardware_pwm import HardwarePWM
except ImportError:
    # Only on the Pi (aarch64).
    HardwarePWM = None

if TYPE_CHECKING:

    def _(a) -> Any:
        return a


logger = logging.getLogger("Recovery")

FRAME_INTERVAL = 1 / 30

KEYPAD_OFFSETS = {
    "+3": 2,
    "+2": 1.6,
    "+1": 1.3,
    "0": 1,
    "-1": 0.75,
    "-2": 0.5,
    "-3": 0.25,
    "-4": 0.13,
    "Off": 0,
}

KEYBOARD_MODULES = {
    "pi": "PiFinder.keyboard_pi",
    "local": "PiFinder.keyboard_local",
    "none": "PiFinder.keyboard_none",
}


class RecoveryState:
    """The part of the shared state that the screens of recovery mode use.

    All screens run in this process, so a plain object replaces the
    multiprocessing manager of the normal app.
    """

    def __init__(self) -> None:
        self._ui_state = UIState()
        self._battery: Optional[BatteryState] = None
        self._screen = None

    def ui_state(self) -> UIState:
        return self._ui_state

    def battery(self) -> Optional[BatteryState]:
        return self._battery

    def set_battery(self, battery: Optional[BatteryState]) -> None:
        self._battery = battery

    def screen(self):
        return self._screen

    def set_screen(self, image) -> None:
        self._screen = image


class RecoveryScreens:
    """A stack of screens with the Software screen at the bottom.

    The Software screen can open release notes on top. LEFT closes the top
    screen. The Software screen does not close: LEFT, or Cancel after a
    failed install, starts it again from the version list.
    """

    def __init__(
        self,
        display_class: DisplayBase,
        shared_state: RecoveryState,
        cfg: config.Config,
    ) -> None:
        self.display_class = display_class
        self.shared_state = shared_state
        self.cfg = cfg
        self.catalogs = Catalogs([])
        self.stack: List[UIModule] = []
        self.add_to_stack(
            {"name": _("Recovery"), "class": UISoftware, "recovery": True}
        )

    def _make(self, item: Dict[str, Any]) -> UIModule:
        return item["class"](
            display_class=self.display_class,
            camera_image=None,
            shared_state=self.shared_state,
            command_queues={},
            config_object=self.cfg,
            catalogs=self.catalogs,
            item_definition=item,
            add_to_stack=self.add_to_stack,
            remove_from_stack=self.remove_from_stack,
            jump_to_label=self.jump_to_label,
        )

    def add_to_stack(self, item: Dict[str, Any]) -> None:
        if self.stack:
            self.stack[-1].inactive()
        self.stack.append(self._make(item))
        self.stack[-1].active()

    def remove_from_stack(self) -> None:
        self.stack[-1].inactive()
        if len(self.stack) > 1:
            self.stack.pop()
        self.stack[-1].active()

    def jump_to_label(self, _label: str) -> None:
        """Recovery mode has no menu tree, so a jump does nothing."""

    def keep_awake(self) -> bool:
        return self.stack[-1].keep_awake

    def key(self, keycode: int) -> None:
        """Send one key to the screen on top."""
        top = self.stack[-1]
        if keycode < 10:
            top.key_number(keycode)
            return
        handlers: Dict[int, Callable[[], Any]] = {
            KeyboardInterface.PLUS: top.key_plus,
            KeyboardInterface.MINUS: top.key_minus,
            KeyboardInterface.SQUARE: top.key_square,
            KeyboardInterface.UP: top.key_up,
            KeyboardInterface.DOWN: top.key_down,
            KeyboardInterface.RIGHT: top.key_right,
        }
        if keycode == KeyboardInterface.LEFT:
            if top.key_left():
                self.remove_from_stack()
        elif keycode in handlers:
            handlers[keycode]()

    def update(self) -> None:
        """Draw the screen on top and send it to the display."""
        top = self.stack[-1]
        top.update()
        if time.time() < UIModule.message_until:
            return
        frame = top.screen.convert(self.display_class.device.mode)
        self.display_class.device.display(frame)
        UIModule.publish_screen(self.shared_state, frame)


class KeypadLight:
    """The keypad backlight, at the level that the normal app uses."""

    def __init__(self, cfg: config.Config, hardware: bool) -> None:
        self.cfg = cfg
        self.pwm = None
        if hardware and HardwarePWM is not None:
            try:
                self.pwm = HardwarePWM(pwm_channel=1, hz=120)
                self.pwm.start(0)
            except Exception as exc:  # noqa: BLE001 - the light is optional
                logger.warning("No keypad light: %s", exc)

    def set_level(self, level: int) -> None:
        if self.pwm is None:
            return
        offset = KEYPAD_OFFSETS.get(self.cfg.get_option("keypad_brightness"), 1)
        percentage = max(0.0, min(100.0, level * 0.05 * offset))
        try:
            self.pwm.change_duty_cycle(percentage)
        except Exception as exc:  # noqa: BLE001 - the light is optional
            logger.warning("Cannot set the keypad light: %s", exc)


def read_battery(shared_state: RecoveryState, stop: threading.Event) -> None:
    """Thread: read the rev4 battery charger until `stop` is set.

    Without a reading the battery state stays None, and the Software screen
    counts the Pi as on USB-C power, as on rev3.
    """
    try:
        chip = BQ25895()
    except Exception as exc:  # noqa: BLE001 - the reading is optional
        logger.warning("No battery charger: %s", exc)
        return
    while not stop.is_set():
        try:
            shared_state.set_battery(chip.read_state())
        except Exception as exc:  # noqa: BLE001 - keep the screen working
            logger.warning("Battery read failed: %s", exc)
        stop.wait(POLL_INTERVAL)


def keyboard_function(name: str) -> Callable[..., Any]:
    """The run_keyboard function of a keyboard module, loaded in the child."""
    return lazy_import.lazy_function(KEYBOARD_MODULES[name], "run_keyboard")


def install_language(cfg: config.Config) -> None:
    lang = cfg.get_option("language", "en")
    gettext.translation(
        "messages", "locale", languages=[lang], fallback=(lang == "en")
    ).install()


def run(
    log_helper: MultiprocLogging,
    display_hardware: str,
    keyboard_name: str,
    hardware: bool,
    capabilities: HardwareCapabilities,
) -> None:
    if not utils.acquire_single_instance_lock():
        return
    # The log sink reads only the queues that exist when it starts.
    keyboard_logqueue: Queue = log_helper.get_queue()
    log_helper.start()

    cfg = config.Config()
    install_language(cfg)
    display_device = get_display(display_hardware)
    if cfg.get_option("screen_direction") in ["as_bloom", "as_heart"]:
        display_device.device.rotate = 2
    brightness = cfg.get_option("display_brightness")
    display_device.set_brightness(brightness)
    KeypadLight(cfg, hardware).set_level(brightness)

    shared_state = RecoveryState()
    stop = threading.Event()
    if capabilities.has_bq25895:
        threading.Thread(
            target=read_battery, args=(shared_state, stop), daemon=True
        ).start()

    keyboard_queue: Queue = Queue()
    keyboard_process = Process(
        name="Keyboard",
        target=keyboard_function(keyboard_name),
        args=(keyboard_queue, None, keyboard_logqueue),
        daemon=True,
    )
    keyboard_process.start()

    screens = RecoveryScreens(display_device, shared_state, cfg)
    screens.update()
    # The first frame is on the display: the health signal for the boot
    # watchdog. No-op outside systemd.
    utils.sd_notify("READY=1")
    logger.info("Recovery mode is ready")

    try:
        while True:
            try:
                while True:
                    keycode = keyboard_queue.get(block=False)
                    if keycode == KeyboardInterface.POWER_BTN:
                        logger.info("Power button: shutting down")
                        utils.get_sys_utils().shutdown()
                    else:
                        screens.key(keycode)
            except queue.Empty:
                pass
            screens.update()
            time.sleep(FRAME_INTERVAL)
    except KeyboardInterrupt:
        logger.info("Recovery mode stops")
    finally:
        stop.set()
        keyboard_process.terminate()
        log_helper.join()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="PiFinder recovery mode")
    parser.add_argument(
        "--display",
        help="Display hardware (default: the display of this board)",
        default=None,
    )
    parser.add_argument(
        "-k",
        "--keyboard",
        help="Keyboard: pi, local or none",
        choices=sorted(KEYBOARD_MODULES),
        default="pi",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(format="%(asctime)s BASIC %(name)s: %(levelname)s %(message)s")
    log_helper = MultiprocLogging(
        utils.active_logconf_path(), utils.data_dir / "pifinder.log"
    )
    MultiprocLogging.configurer(log_helper.get_queue())

    capabilities = hardware_detect.detect_capabilities()
    display_hardware = args.display or (
        "ssd1333" if capabilities.is_rev4 else "ssd1351"
    )
    hardware = not display_hardware.startswith(("pg_", "headless"))
    try:
        run(log_helper, display_hardware, args.keyboard, hardware, capabilities)
    except Exception:
        logger.exception("Recovery mode failed")
        # The log goes through a queue to another process. Write the
        # traceback to stderr too, so the journal has it.
        traceback.print_exc()
        sys.stderr.flush()
        logging.shutdown()
        os._exit(1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
