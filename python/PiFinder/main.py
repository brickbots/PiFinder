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

import gettext

import os

# skyfield performance fix, see: https://rhodesmill.org/skyfield/accuracy-efficiency.html
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
import time
import queue
import datetime
import json
import uuid
import logging
import argparse
import pickle
from pathlib import Path
from PIL import Image, ImageOps
from multiprocessing import Process, Queue
from multiprocessing.managers import BaseManager

import PiFinder.i18n  # noqa: F401
from PiFinder import solver
from PiFinder import integrator
from PiFinder import config
from PiFinder import pos_server
from PiFinder import utils
from PiFinder import server
from PiFinder import keyboard_interface

from PiFinder.multiproclogging import MultiprocLogging
from PiFinder.catalogs import CatalogBuilder, CatalogFilter, Catalogs
from PiFinder.calc_utils import sf_utils

from PiFinder.ui.console import UIConsole
from PiFinder.ui.menu_manager import MenuManager

from PiFinder.state import SharedStateObj, UIState

from PiFinder.image_util import subtract_background

from PiFinder.displays import DisplayBase, get_display

from typing import Any, TYPE_CHECKING

# Mypy i8n fix
if TYPE_CHECKING:

    def _(a) -> Any:
        return a


logger = logging.getLogger("main")

hardware_platform = "Pi"
display_hardware = "SSD1351"
display_device: DisplayBase = DisplayBase()
keypad_pwm = None


def init_keypad_pwm():
    # TODO: Keypad pwm class that can be faked maybe?
    global keypad_pwm
    global hardware_platform
    if hardware_platform == "Pi":
        keypad_pwm = HardwarePWM(pwm_channel=1, hz=120)
        keypad_pwm.start(0)


def set_keypad_brightness(percentage: float):
    """
    keypad brightness between 0-100, although effective range seems 0-12
    """
    global keypad_pwm
    if percentage < 0 or percentage > 100:
        logger.error("Invalid percentage for keypad brightness")
        percentage = max(0, min(100, percentage))
    if keypad_pwm:
        keypad_pwm.change_duty_cycle(percentage)


def set_brightness(level, cfg):
    """
    Sets oled/keypad brightness
    0-255
    """
    global display_device
    display_device.set_brightness(level)

    if keypad_pwm:
        # determine offset for keypad
        keypad_offsets = {
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
        keypad_brightness = cfg.get_option("keypad_brightness")
        set_keypad_brightness(level * 0.05 * keypad_offsets[keypad_brightness])


def setup_dirs():
    utils.create_path(Path(utils.data_dir))
    utils.create_path(Path(utils.data_dir, "captures"))
    utils.create_path(Path(utils.data_dir, "obslists"))
    utils.create_path(Path(utils.data_dir, "screenshots"))
    utils.create_path(Path(utils.data_dir, "solver_debug_dumps"))
    utils.create_path(Path(utils.data_dir, "logs"))
    os.chmod(Path(utils.data_dir), 0o777)


class StateManager(BaseManager):
    pass


StateManager.register("SharedState", SharedStateObj)
StateManager.register("UIState", UIState)
StateManager.register("NewImage", Image.new)


class PowerManager:
    def __init__(self, cfg, shared_state, display_device):
        self.cfg = cfg
        self.shared_state = shared_state
        self.display_device = display_device
        self.last_activity = time.time()

    def register_activity(self):
        """
        Resets idle counter, wakes up systems if needed
        returns True if activity caused wakeup
        """
        self.last_activity = time.time()

        # power states
        # 0 = Sleep
        # 1 = Wake
        if self.shared_state.power_state() < 1:
            # wake up
            self.wake_up()
            return True

        return False

    def wake_up(self):
        """
        Do all the wakeup things
        """
        self.last_activity = time.time()
        self.shared_state.set_power_state(1)
        self.wake_screen()

    def go_to_sleep(self):
        """
        Do all the sleep things
        """
        self.shared_state.set_power_state(0)
        self.sleep_screen()

    def update(self):
        """
        Check IMU for activity
        go to sleep if needed
        if asleep, Introduce wait state
        """
        if self.get_sleep_timeout() <= 0:
            # Disabled
            self.register_activity()
            return

        if self.shared_state.power_state() > 0:
            # We are awake, should we sleep?
            if time.time() - self.last_activity > self.get_sleep_timeout():
                self.go_to_sleep()

        else:  # We are asleepd, should we wake up?
            _imu = self.shared_state.imu()
            if _imu:
                if _imu["moving"]:
                    self.wake_up()

        # should we pause execution for a bit?
        if self.shared_state.power_state() < 1:
            time.sleep(0.2)

    def get_sleep_timeout(self):
        """
        returns the sleep timeout amount
        """
        sleep_timeout_option = self.cfg.get_option("sleep_timeout")
        sleep_timeout = {
            "Off": -1,
            "10s": 10,
            "20s": 20,
            "30s": 30,
            "1m": 60,
            "2m": 120,
        }[sleep_timeout_option]
        return sleep_timeout

    def get_screen_off_timeout(self):
        """
        returns the screen off timeout amount
        """
        screen_off_option = self.cfg.get_option("screen_off_timeout")
        screen_off = {
            "Off": -1,
            "30s": 30,
            "1m": 60,
            "10m": 600,
            "30m": 1800,
        }[screen_off_option]
        return screen_off

    def wake_screen(self) -> None:
        screen_brightness = self.cfg.get_option("display_brightness")
        set_brightness(screen_brightness, self.cfg)
        self.display_device.device.show()

    def sleep_screen(self):
        screen_brightness = self.cfg.get_option("display_brightness")
        set_brightness(int(screen_brightness / 4), self.cfg)
        self.display_device.device.show()


def main(
    log_helper: MultiprocLogging,
    script_name=None,
    show_fps=False,
    verbose=False,
    profile_startup=False,
) -> None:
    """
    Get this show on the road!
    """
    global display_device, display_hardware

    display_device = get_display(display_hardware)
    init_keypad_pwm()
    setup_dirs()

    # Instantiate base keyboard class for keycode
    keyboard_base = keyboard_interface.KeyboardInterface()

    # init queues
    console_queue: Queue = Queue()
    keyboard_queue: Queue = Queue()
    gps_queue: Queue = Queue()
    camera_command_queue: Queue = Queue()
    solver_queue: Queue = Queue()
    alignment_command_queue: Queue = Queue()
    alignment_response_queue: Queue = Queue()
    ui_queue: Queue = Queue()

    # init queues for logging
    keyboard_logqueue: Queue = log_helper.get_queue()
    gps_logqueue: Queue = log_helper.get_queue()
    camera_logqueue: Queue = log_helper.get_queue()
    solver_logqueue: Queue = log_helper.get_queue()
    server_logqueue: Queue = log_helper.get_queue()
    posserver_logqueue: Queue = log_helper.get_queue()
    integrator_logqueque: Queue = log_helper.get_queue()
    imu_logqueue: Queue = log_helper.get_queue()

    # Start log consolidation process first.
    log_helper.start()

    os_detail, platform, arch = utils.get_os_info()
    logger.info("PiFinder running on %s, %s, %s", os_detail, platform, arch)

    # init UI Modes
    command_queues = {
        "camera": camera_command_queue,
        "console": console_queue,
        "ui_queue": ui_queue,
        "align_command": alignment_command_queue,
        "align_response": alignment_response_queue,
        "gps": gps_queue,
    }
    cfg = config.Config()

    # init screen
    screen_brightness = cfg.get_option("display_brightness")
    set_brightness(screen_brightness, cfg)
    if cfg.get_option("screen_direction") == "as_bloom":
        display_device.device.rotate = 3

    # Set user interface language
    lang = cfg.get_option("language", "en")
    langXX = gettext.translation(
        "messages", "locale", languages=[lang], fallback=(lang == "en")
    )
    langXX.install()

    import PiFinder.manager_patch as patch

    patch.apply()

    with StateManager() as manager:
        shared_state = manager.SharedState()  # type: ignore[attr-defined]
        location = shared_state.location()
        ui_state = manager.UIState()  # type: ignore[attr-defined]
        ui_state.set_show_fps(show_fps)
        ui_state.set_hint_timeout(cfg.get_option("hint_timeout"))
        shared_state.set_ui_state(ui_state)
        shared_state.set_arch(arch)  # Normal
        logger.debug("Ui state in main is" + str(shared_state.ui_state()))
        console = UIConsole(
            display_device, None, shared_state, command_queues, cfg, Catalogs([])
        )
        console.write("Starting....")
        console.update()
        logger.info("Starting ....")

        # spawn gps service....
        console.write("   GPS")
        console.update()
        logger.info("   GPS")
        gps_process = Process(
            name="GPS",
            target=gps_monitor.gps_monitor,
            args=(
                gps_queue,
                console_queue,
                gps_logqueue,
            ),
        )
        gps_process.start()
        console.set_shared_state(shared_state)

        # spawn keyboard service....
        console.write("   Keyboard")
        logger.info("   Keyboard")
        console.update()
        if cfg.get_option("screen_direction") == "as_bloom":
            bloom_key_remap = True
        else:
            bloom_key_remap = False
        keyboard_process = Process(
            name="Keyboard",
            target=keyboard.run_keyboard,
            args=(keyboard_queue, shared_state, keyboard_logqueue, bloom_key_remap),
        )
        keyboard_process.start()
        if script_name:
            script_path = f"../scripts/{script_name}.pfs"
            p = Process(
                name="Script",
                target=keyboard_interface.KeyboardInterface.run_script,
                args=(script_path, keyboard_queue, keyboard_logqueue),
            )
            p.start()

        # Web server
        console.write("   Webserver")
        logger.info("   Webserver")
        console.update()

        server_process = Process(
            name="Webserver",
            target=server.run_server,
            args=(
                keyboard_queue,
                ui_queue,
                gps_queue,
                shared_state,
                server_logqueue,
                verbose,
            ),
        )
        server_process.start()

        console.write("   Camera")
        logger.info("   Camera")
        console.update()
        camera_image = manager.NewImage("RGB", (512, 512))  # type: ignore[attr-defined]
        bias_image = manager.NewImage("RGB", (512, 512))  # type: ignore[attr-defined]
        image_process = Process(
            name="Camera",
            target=camera.get_images,
            args=(
                shared_state,
                camera_image,
                bias_image,
                camera_command_queue,
                console_queue,
                camera_logqueue,
            ),
        )
        image_process.start()
        time.sleep(1)

        # IMU
        console.write("   IMU")
        logger.info("   IMU")
        console.update()
        imu_process = Process(
            name="IMU",
            target=imu.imu_monitor,
            args=(shared_state, console_queue, imu_logqueue),
        )
        imu_process.start()

        # Solver
        console.write("   Solver")
        logger.info("   Solver")
        console.update()
        solver_process = Process(
            name="Solver",
            target=solver.solver,
            args=(
                shared_state,
                solver_queue,
                camera_image,
                bias_image,
                console_queue,
                solver_logqueue,
                alignment_command_queue,
                alignment_response_queue,
                verbose,
            ),
        )
        solver_process.start()

        # Integrator
        console.write("   Integrator")
        logger.info("   Integrator")
        console.update()
        integrator_process = Process(
            name="Integrator",
            target=integrator.integrator,
            args=(
                shared_state,
                solver_queue,
                console_queue,
                integrator_logqueque,
                verbose,
            ),
        )
        integrator_process.start()

        # Server
        console.write("  POS Server")
        logger.info("  POS Server")
        console.update()
        posserver_process = Process(
            name="SkySafariServer",
            target=pos_server.run_server,
            args=(shared_state, ui_queue, posserver_logqueue),
        )
        posserver_process.start()

        # Initialize Catalogs
        console.write("   Catalogs")
        logger.info("   Catalogs")
        console.update()

        # Start profiling (automatic for performance analysis)
        import cProfile
        import pstats
        profiler = cProfile.Profile()
        profiler.enable()
        startup_profile_start = time.time()

        # Initialize Catalogs (pass ui_queue for background loading completion signal)
        catalogs: Catalogs = CatalogBuilder().build(shared_state, ui_queue)

        # Establish the common catalog filter object
        _new_filter = CatalogFilter(shared_state=shared_state)
        _new_filter.load_from_config(cfg)
        catalogs.set_catalog_filter(_new_filter)
        console.write("   Menus")
        console.update()

        # Initialize menu manager
        menu_manager = MenuManager(
            display_device,
            camera_image,
            shared_state,
            command_queues,
            cfg,
            catalogs,
        )

        # Initialize power manager
        power_manager = PowerManager(cfg, shared_state, display_device)

        # Start main event loop
        console.write("   Event Loop")
        logger.info("   Event Loop")
        console.update()

        # Stop profiling and save results
        profiler.disable()
        startup_profile_time = time.time() - startup_profile_start

        # Save to file
        profile_path = utils.data_dir / "startup_profile.prof"
        profiler.dump_stats(str(profile_path))

        # Print summary
        logger.info(f"=== Startup Profiling Complete ({startup_profile_time:.2f}s) ===")
        logger.info(f"Profile saved to: {profile_path}")
        logger.info("To analyze, run:")
        logger.info(f"  python -c \"import pstats; p = pstats.Stats('{profile_path}'); p.sort_stats('cumulative').print_stats(30)\"")

        # Also save a text summary
        summary_path = utils.data_dir / "startup_profile.txt"
        with open(summary_path, 'w') as f:
            ps = pstats.Stats(profiler, stream=f)
            f.write(f"=== STARTUP PROFILING ({startup_profile_time:.2f}s) ===\n\n")
            f.write("Top 30 functions by cumulative time:\n")
            f.write("=" * 80 + "\n")
            ps.sort_stats('cumulative').print_stats(30)
            f.write("\n" + "=" * 80 + "\n")
            f.write("Top 30 functions by internal time:\n")
            f.write("=" * 80 + "\n")
            ps.sort_stats('time').print_stats(30)
        logger.info(f"Text summary saved to: {summary_path}")

        log_time = True
        # Start of main except handler / loop
        try:
            while True:
                # Console
                try:
                    console_msg = console_queue.get(block=False)
                    if console_msg.startswith("DEGRADED_OPS"):
                        menu_manager.message(_("Degraded\nCheck Status"), 5)
                        time.sleep(5)
                    else:
                        console.write(console_msg)
                except queue.Empty:
                    time.sleep(0.1)

                # GPS
                try:
                    while True:  # Consume from gps_queue until empty
                        gps_msg, gps_content = gps_queue.get(block=False)
                        if gps_msg == "fix":
                            if gps_content["lat"] + gps_content["lon"] != 0:
                                location = shared_state.location()

                            # Only update GPS fixes, as soon as it's loaded or comes from the WEB it's untouchable
                            if (
                                not location.source == "WEB"
                                and not location.source.startswith("CONFIG:")
                                and (
                                    location.error_in_m == 0
                                    or float(gps_content["error_in_m"])
                                    < float(
                                        location.error_in_m
                                    )  # Only if new error is smaller
                                )
                            ):
                                logger.info(
                                    f"Updating GPS location: new content: {gps_content}, old content: {location}"
                                )
                                location.lat = gps_content["lat"]
                                location.lon = gps_content["lon"]
                                location.altitude = gps_content["altitude"]
                                location.source = gps_content["source"]
                                if "error_in_m" in gps_content:
                                    location.error_in_m = gps_content["error_in_m"]
                                if "lock" in gps_content:
                                    location.lock = gps_content["lock"]
                                if "lock_type" in gps_content:
                                    location.lock_type = gps_content["lock_type"]

                                    dt = shared_state.datetime()
                                    if dt is None:
                                        location.last_gps_lock = "--"
                                    else:
                                        location.last_gps_lock = dt.time().isoformat()[
                                            :8
                                        ]
                                    console.write(
                                        f"GPS: Location {location.lat} {location.lon} {location.altitude} {location.error_in_m}"
                                    )
                                    shared_state.set_location(location)
                                    sf_utils.set_location(
                                        location.lat,
                                        location.lon,
                                        location.altitude,
                                    )
                        if gps_msg == "time":
                            if isinstance(gps_content, datetime.datetime):
                                gps_dt = gps_content
                            else:
                                gps_dt = gps_content["time"]
                            shared_state.set_datetime(gps_dt)
                            if log_time:
                                logger.info("GPS Time (logged only once): %s", gps_dt)
                                log_time = False
                        if gps_msg == "reset":
                            location.reset()
                            shared_state.set_location(location)
                        if gps_msg == "satellites":
                            # logger.debug("Main: GPS nr sats seen: %s", gps_content)
                            shared_state.set_sats(gps_content)
                except queue.Empty:
                    pass

                # ui queue
                try:
                    ui_command = ui_queue.get(block=False)
                except queue.Empty:
                    ui_command = None
                if ui_command == "set_brightness":
                    set_brightness(screen_brightness, cfg)
                elif ui_command == "push_object":
                    menu_manager.jump_to_label("recent")
                elif ui_command == "reload_config":
                    cfg.load_config()
                elif ui_command == "catalogs_fully_loaded":
                    logger.info(
                        "All catalogs loaded - WDS and extended catalogs available"
                    )
                    menu_manager.message(_("Catalogs\nFully Loaded"), 2)
                elif ui_command == "test_mode":
                    dt = datetime.datetime(2025, 6, 28, 11, 0, 0)
                    shared_state.set_datetime(dt)
                    location.lat = 41.13
                    location.lon = -120.97
                    location.altitude = 1315
                    location.source = "test"
                    location.error_in_m = 5
                    location.lock = True
                    location.lock_type = 3
                    location.last_gps_lock = (
                        datetime.datetime.now().time().isoformat()[:8]
                    )
                    console.write(
                        f"GPS: Location {location.lat} {location.lon} {location.altitude}"
                    )
                    shared_state.set_location(location)
                    sf_utils.set_location(
                        location.lat,
                        location.lon,
                        location.altitude,
                    )

                # Keyboard
                keycode = None
                try:
                    while True:
                        keycode = keyboard_queue.get(block=False)
                except queue.Empty:
                    pass

                # Register activity here will return True if the power
                # state changes.  If so, we DO NOT process this keystroke
                if keycode is not None and power_manager.register_activity() is False:
                    # ignore keystroke if we have been asleep
                    if keycode > 99:
                        # Long left is return to top
                        if keycode == keyboard_base.LNG_LEFT:
                            menu_manager.key_long_left()

                        # Long right is return to last observed object
                        if keycode == keyboard_base.LNG_RIGHT:
                            menu_manager.key_long_right()

                        # Long square is marking menu
                        if keycode == keyboard_base.LNG_SQUARE:
                            menu_manager.key_long_square()

                        # Special codes....
                        if (
                            keycode == keyboard_base.ALT_PLUS
                            or keycode == keyboard_base.ALT_MINUS
                        ):
                            if keycode == keyboard_base.ALT_PLUS:
                                screen_adjust = int(screen_brightness * 0.2)
                                if screen_adjust < 2:
                                    screen_adjust = 2

                                screen_brightness += screen_adjust
                                if screen_brightness > 255:
                                    screen_brightness = 255
                            else:
                                screen_adjust = int(screen_brightness * 0.1)
                                if screen_adjust < 1:
                                    screen_adjust = 1

                                screen_brightness -= screen_adjust
                                if screen_brightness < 0:
                                    screen_brightness = 0

                            set_brightness(screen_brightness, cfg)
                            cfg.set_option("display_brightness", screen_brightness)
                            console.write("Brightness: " + str(screen_brightness))
                            logger.info("Brightness: %s", screen_brightness)

                        if keycode == keyboard_base.ALT_0:
                            # screenshot
                            menu_manager.screengrab()
                            console.write("Screenshot saved")
                            logger.info("Screenshot saved")

                        if (
                            keycode == keyboard_base.ALT_LEFT
                            or keycode == keyboard_base.ALT_RIGHT
                        ):
                            # Image snapshot (ALT_LEFT) or Debug snapshot (ALT_RIGHT)
                            uid = str(uuid.uuid1()).split("-")[0]

                            # wait two seconds for any vibration from
                            # pressing the button to pass.
                            menu_manager.message("Saving: 2", 1)
                            time.sleep(1)
                            menu_manager.message("Saving: 1", 1)
                            time.sleep(1)
                            menu_manager.message("Saving...", 1)
                            time.sleep(1)
                            debug_image = camera_image.copy()

                            # Always save images for both ALT_LEFT and ALT_RIGHT
                            debug_image.save(f"{utils.debug_dump_dir}/{uid}_raw.png")
                            debug_image = subtract_background(debug_image)
                            debug_image = debug_image.convert("RGB")
                            debug_image = ImageOps.autocontrast(debug_image)
                            debug_image.save(f"{utils.debug_dump_dir}/{uid}_sub.png")

                            if keycode == keyboard_base.ALT_RIGHT:
                                # Additional debug information only for ALT_RIGHT
                                # current screen
                                ss = menu_manager.stack[-1].screen.copy()
                                debug_solution = shared_state.solution()
                                debug_location = shared_state.location()
                                debug_dt = shared_state.datetime()

                                ss.save(f"{utils.debug_dump_dir}/{uid}_screenshot.png")

                                with open(
                                    f"{utils.debug_dump_dir}/{uid}_solution.dbg", "w"
                                ) as f:
                                    f.write(str(debug_solution))

                                with open(
                                    f"{utils.debug_dump_dir}/{uid}_location.dgb", "w"
                                ) as f:
                                    f.write(str(debug_location))

                                if debug_dt is not None:
                                    with open(
                                        f"{utils.debug_dump_dir}/{uid}_datetime.json",
                                        "w",
                                    ) as f:
                                        json.dump(debug_dt.isoformat(), f, indent=4)

                                # Dump shared state
                                # shared_state.serialize(
                                #    f"{utils.debug_dump_dir}/{uid}_sharedstate.pkl"
                                # )

                                # Dump UI State
                                with open(
                                    f"{utils.debug_dump_dir}/{uid}_uistate.pkl", "wb"
                                ) as f:
                                    pickle.dump(ui_state, f)

                                console.write(f"Debug dump: {uid}")
                                logger.info(f"Debug dump: {uid}")
                                menu_manager.message("Debug Info Saved", timeout=1)
                            else:
                                # ALT_LEFT - just image saved
                                console.write(f"Image saved: {uid}")
                                logger.info(f"Image saved: {uid}")
                                menu_manager.message("Image Saved", timeout=1)

                    else:
                        if keycode < 10:
                            menu_manager.key_number(keycode)

                        elif keycode == keyboard_base.PLUS:
                            menu_manager.key_plus()

                        elif keycode == keyboard_base.MINUS:
                            menu_manager.key_minus()

                        elif keycode == keyboard_base.SQUARE:
                            menu_manager.key_square()

                        elif keycode == keyboard_base.LEFT:
                            menu_manager.key_left()

                        elif keycode == keyboard_base.UP:
                            menu_manager.key_up()

                        elif keycode == keyboard_base.DOWN:
                            menu_manager.key_down()

                        elif keycode == keyboard_base.RIGHT:
                            menu_manager.key_right()

                menu_manager.update()
                power_manager.update()

        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt received: shutting down.")
            logger.info("SHUTDOWN")
            try:
                logger.debug("\tClearing console queue...")
                while True:
                    console_queue.get(block=False)
            except queue.Empty:
                pass

            logger.info("\tKeyboard...")
            try:
                while True:
                    keyboard_queue.get(block=False)
            except queue.Empty:
                keyboard_process.join()

            logger.info("\tServer...")
            server_process.join()

            logger.info("\tPos Server...")
            posserver_process.join()

            logger.info("\tGPS...")
            gps_process.terminate()

            logger.info("\tImaging...")
            image_process.join()

            logger.info("\tIMU...")
            imu_process.join()

            logger.info("\tIntegrator...")
            integrator_process.join()

            logger.info("\tSolver...")
            solver_process.join()

            log_helper.join()
            exit()


if __name__ == "__main__":
    print("Bootstrap logging configuration ...")
    logging.basicConfig(format="%(asctime)s BASIC %(name)s: %(levelname)s %(message)s")
    rlogger = logging.getLogger()
    rlogger.setLevel(logging.INFO)
    log_path = utils.data_dir / "pifinder.log"
    try:
        log_helper = MultiprocLogging(
            Path("pifinder_logconf.json"),
            log_path,
        )
        MultiprocLogging.configurer(log_helper.get_queue())
    except FileNotFoundError:
        rlogger.warning(
            "Cannot find log configuration file, proceeding with basic configuration."
        )
        rlogger.warning("Logs will not be stored on disk, unless you use --log")
        logging.getLogger("PIL.PngImagePlugin").setLevel(logging.WARNING)
        logging.getLogger("tetra3.Tetra3").setLevel(logging.WARNING)
        logging.getLogger("picamera2.picamera2").setLevel(logging.WARNING)

    rlogger.info("Starting PiFinder ...")
    parser = argparse.ArgumentParser(description="eFinder")
    parser.add_argument(
        "-fh",
        "--fakehardware",
        help="Use fake hardware for imu, gps",
        default=False,
        action="store_true",
        required=False,
    )
    parser.add_argument(
        "-c",
        "--camera",
        help="Specify which camera to use: pi, asi, debug or none",
        default="pi",
        required=False,
    )
    parser.add_argument(
        "-k",
        "--keyboard",
        help="Specify which keyboard to use: pi, local or server",
        default="pi",
        required=False,
    )
    parser.add_argument(
        "--script",
        help="Specify a testing script to run",
        default=None,
        required=False,
    )

    parser.add_argument(
        "-f",
        "--fps",
        help="Display FPS in title bar",
        default=False,
        action="store_true",
        required=False,
    )

    parser.add_argument(
        "--display",
        help="Display Hardware to use",
        default=None,
        required=False,
    )

    parser.add_argument(
        "-n",
        "--notmp",
        help="Don't use the /dev/shm temporary directory.\
                (usefull if not on pi)",
        default=False,
        action="store_true",
        required=False,
    )
    parser.add_argument(
        "-x", "--verbose", help="Set logging to debug mode", action="store_true"
    )
    parser.add_argument("-l", "--log", help="Log to file", action="store_true")
    parser.add_argument(
        "--lang",
        help="Force user interface language (iso2 code). Changes configuration",
        type=str,
    )
    parser.add_argument(
        "--profile-startup",
        help="Profile startup performance (catalog/menu loading)",
        default=False,
        action="store_true",
        required=False,
    )
    args = parser.parse_args()
    # add the handlers to the logger
    if args.verbose:
        rlogger.setLevel(logging.DEBUG)

    import importlib

    if args.fakehardware:
        hardware_platform = "Fake"
        display_hardware = "pg_128"
        imu = importlib.import_module("PiFinder.imu_fake")
        gps_monitor = importlib.import_module("PiFinder.gps_fake")
    else:
        hardware_platform = "Pi"
        display_hardware = "ssd1351"
        from rpi_hardware_pwm import HardwarePWM

        imu = importlib.import_module("PiFinder.imu_pi")
        cfg = config.Config()

        # verify and sync GPSD baud rate
        try:
            from PiFinder import sys_utils
            baud_rate = cfg.get_option("gps_baud_rate", 9600)  # Default to 9600 if not set
            if sys_utils.check_and_sync_gpsd_config(baud_rate):
                logger.info(f"GPSD configuration updated to {baud_rate} baud")
        except Exception as e:
            logger.warning(f"Could not check/sync GPSD configuration: {e}")

        gps_type = cfg.get_option("gps_type")
        if gps_type == "ublox":
            gps_monitor = importlib.import_module("PiFinder.gps_ubx")
        else:
            gps_monitor = importlib.import_module("PiFinder.gps_gpsd")

    if args.display is not None:
        display_hardware = args.display.lower()

    if args.camera.lower() == "pi":
        rlogger.info("using pi camera")
        from PiFinder import camera_pi as camera
    elif args.camera.lower() == "debug":
        rlogger.info("using debug camera")
        from PiFinder import camera_debug as camera  # type: ignore[no-redef]
    elif args.camera.lower() == "asi":
        rlogger.info("using asi camera")
    else:
        rlogger.warn("not using camera")
        from PiFinder import camera_none as camera  # type: ignore[no-redef]

    if args.keyboard.lower() == "pi":
        from PiFinder import keyboard_pi as keyboard

        rlogger.info("using pi keyboard hat")
    elif args.keyboard.lower() == "local":
        from PiFinder import keyboard_local as keyboard  # type: ignore[no-redef]

        rlogger.info("using local keyboard")
    elif args.keyboard.lower() == "none":
        from PiFinder import keyboard_none as keyboard  # type: ignore[no-redef]

        rlogger.warning("using no keyboard")

    if args.lang:
        if args.lang.lower() not in ["en", "de", "fr", "es"]:
            raise Exception(f"Unknown language '{args.lang}' passed via command line.")
        else:
            config.Config().set_option("language", args.lang)

    try:
        main(log_helper, args.script, args.fps, args.verbose, args.profile_startup)
    except Exception:
        rlogger.exception("Exception in main(). Aborting program.")
        os._exit(1)
