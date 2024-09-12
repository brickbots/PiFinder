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
import shutil
from pathlib import Path
from PIL import Image, ImageOps
from multiprocessing import Process, Queue
from multiprocessing.managers import BaseManager
from timezonefinder import TimezoneFinder

from PiFinder import solver
from PiFinder import integrator
from PiFinder import config
from PiFinder import pos_server
from PiFinder import utils
from PiFinder import server
from PiFinder import keyboard_interface

from PiFinder.multiproclogging import MultiprocLogging
from PiFinder.catalogs import CatalogBuilder, CatalogFilter, Catalogs

from PiFinder.ui.console import UIConsole
from PiFinder.ui.menu_manager import MenuManager

from PiFinder.state import SharedStateObj, UIState

from PiFinder.image_util import subtract_background

from PiFinder.calc_utils import sf_utils
from PiFinder.displays import DisplayBase, get_display

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


def get_sleep_timeout(cfg):
    """
    returns the sleep timeout amount
    """
    sleep_timeout_option = cfg.get_option("sleep_timeout")
    sleep_timeout = {
        "Off": 100000,
        "10s": 10,
        "20s": 20,
        "30s": 30,
        "1m": 60,
        "2m": 120,
    }[sleep_timeout_option]
    return sleep_timeout


def get_screen_off_timeout(cfg):
    """
    returns the screen off timeout amount
    """
    screen_off_option = cfg.get_option("screen_off_timeout")
    screen_off = {"Off": -1, "30s": 30, "1m": 60, "10m": 600, "30m": 1800}[
        screen_off_option
    ]
    return screen_off


def _calculate_timeouts(cfg):
    t = time.time()
    screen_dim = get_sleep_timeout(cfg)
    screen_dim = t + screen_dim if screen_dim > 0 else None
    screen_off = get_screen_off_timeout(cfg)
    screen_off = t + screen_off if screen_off > 0 else None
    return screen_dim, screen_off


def wake_screen(screen_brightness, shared_state, cfg) -> int:
    global display_device
    set_brightness(screen_brightness, cfg)
    display_device.device.show()
    orig_power_state = shared_state.power_state()
    shared_state.set_power_state(1)  # Normal
    return orig_power_state


def main(
    log_helper: MultiprocLogging,
    script_name=None,
    show_fps=False,
    verbose=False,
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
    }
    cfg = config.Config()

    # init screen
    screen_brightness = cfg.get_option("display_brightness")
    set_brightness(screen_brightness, cfg)

    import PiFinder.manager_patch as patch

    patch.apply()

    with StateManager() as manager:
        shared_state = manager.SharedState()  # type: ignore[attr-defined]
        ui_state = manager.UIState()  # type: ignore[attr-defined]
        ui_state.set_show_fps(show_fps)
        ui_state.set_hint_timeout(cfg.get_option("hint_timeout"))
        # ui_state.set_active_list_to_history_list()
        shared_state.set_ui_state(ui_state)
        shared_state.set_arch(arch)  # Normal
        logger.debug("Ui state in main is" + str(shared_state.ui_state()))
        console = UIConsole(display_device, None, shared_state, command_queues, cfg)
        console.write("Starting....")
        console.update()

        # spawn gps service....
        console.write("   GPS")
        console.update()
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
        console.update()
        keyboard_process = Process(
            name="Keyboard",
            target=keyboard.run_keyboard,
            args=(keyboard_queue, shared_state, keyboard_logqueue),
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

        server_process = Process(
            name="Webserver",
            target=server.run_server,
            args=(keyboard_queue, gps_queue, shared_state, server_logqueue, verbose),
        )
        server_process.start()

        # Load last location, set lock to false
        tz_finder = TimezoneFinder()
        initial_location = cfg.get_option("last_location")
        initial_location["timezone"] = tz_finder.timezone_at(
            lat=initial_location["lat"], lng=initial_location["lon"]
        )
        initial_location["gps_lock"] = False
        initial_location["last_gps_lock"] = None
        shared_state.set_location(initial_location)
        sf_utils.set_location(
            initial_location["lat"],
            initial_location["lon"],
            initial_location["altitude"],
        )

        console.write("   Camera")
        console.update()
        camera_image = manager.NewImage("RGB", (512, 512))  # type: ignore[attr-defined]
        image_process = Process(
            name="Camera",
            target=camera.get_images,
            args=(
                shared_state,
                camera_image,
                camera_command_queue,
                console_queue,
                camera_logqueue,
            ),
        )
        image_process.start()
        time.sleep(1)

        # IMU
        console.write("   IMU")
        console.update()
        imu_process = Process(
            name="IMU",
            target=imu.imu_monitor,
            args=(shared_state, console_queue, imu_logqueue),
        )
        imu_process.start()

        # Solver
        console.write("   Solver")
        console.update()
        solver_process = Process(
            name="Solver",
            target=solver.solver,
            args=(
                shared_state,
                solver_queue,
                camera_image,
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
        console.write("   Server")
        console.update()
        posserver_process = Process(
            name="SkySafariServer",
            target=pos_server.run_server,
            args=(shared_state, ui_queue, posserver_logqueue),
        )
        posserver_process.start()

        # Start main event loop
        console.write("   Catalogs")
        console.update()

        # Initialize Catalogs
        catalogs: Catalogs = CatalogBuilder().build()

        # Establish the common catalog filter object
        catalogs.set_catalog_filter(
            CatalogFilter(
                shared_state=shared_state,
                magnitude=cfg.get_option("filter.magnitude"),
                object_types=cfg.get_option("filter.object_types"),
                altitude=cfg.get_option("filter.altitude", -1),
                observed=cfg.get_option("filter.observed", "Any"),
                selected_catalogs=cfg.get_option("active_catalogs"),
            )
        )
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

        # Start main event loop
        console.write("   Event Loop")
        console.update()

        # Start of main except handler / loop
        screen_dim, screen_off = _calculate_timeouts(cfg)
        try:
            while True:
                # Console
                try:
                    console_msg = console_queue.get(block=False)
                    console.write(console_msg)
                except queue.Empty:
                    pass

                # GPS
                try:
                    gps_msg, gps_content = gps_queue.get(block=False)
                    if gps_msg == "fix":
                        # logger.debug("GPS fix msg: %s", gps_content)
                        if gps_content["lat"] + gps_content["lon"] != 0:
                            location = shared_state.location()
                            location["lat"] = gps_content["lat"]
                            location["lon"] = gps_content["lon"]
                            location["altitude"] = gps_content["altitude"]
                            location["last_gps_lock"] = (
                                datetime.datetime.now().time().isoformat()[:8]
                            )
                            if location["gps_lock"] is False:
                                # Write to config if we just got a lock
                                location["timezone"] = tz_finder.timezone_at(
                                    lat=location["lat"], lng=location["lon"]
                                )
                                cfg.set_option("last_location", location)
                                console.write(
                                    f'GPS: Location {location["lat"]} {location["lon"]} {location["altitude"]}'
                                )
                                location["gps_lock"] = True

                            shared_state.set_location(location)
                    if gps_msg == "time":
                        # logger.debug("GPS time msg: %s", gps_content)
                        gps_dt = gps_content
                        shared_state.set_datetime(gps_dt)
                    if gps_msg == "satellites":
                        logger.debug("Main: GPS nr sats seen: %s", gps_content)
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

                # Keyboard
                keycode = None
                try:
                    while True:
                        keycode = keyboard_queue.get(block=False)
                except queue.Empty:
                    pass

                if keycode is not None:
                    # logger.debug("Keycode: %s", keycode)
                    screen_dim, screen_off = _calculate_timeouts(cfg)
                    original_power_state = wake_screen(
                        screen_brightness, shared_state, cfg
                    )

                    # ignore keystroke if we have been asleep
                    if original_power_state > 0:
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
                                    screen_brightness = screen_brightness + 10
                                    if screen_brightness > 255:
                                        screen_brightness = 255
                                else:
                                    screen_brightness = screen_brightness - 10
                                    if screen_brightness < 1:
                                        screen_brightness = 1

                                set_brightness(screen_brightness, cfg)
                                cfg.set_option("display_brightness", screen_brightness)
                                console.write("Brightness: " + str(screen_brightness))

                            if keycode == keyboard_base.ALT_0:
                                # screenshot
                                menu_manager.screengrab()
                                console.write("Screenshot saved")

                            if keycode == keyboard_base.ALT_RIGHT:
                                # Debug snapshot
                                uid = str(uuid.uuid1()).split("-")[0]

                                # current screen
                                ss = menu_manager.stack[-1].screen.copy()

                                # wait two seconds for any vibration from
                                # pressing the button to pass.
                                menu_manager.message("Debug: 2", 1)
                                time.sleep(1)
                                menu_manager.message("Debug: 1", 1)
                                time.sleep(1)
                                menu_manager.message("Debug: Saving", 1)
                                time.sleep(1)
                                debug_image = camera_image.copy()
                                debug_solution = shared_state.solution()
                                debug_location = shared_state.location()
                                debug_dt = shared_state.datetime()

                                # write images
                                debug_image.save(
                                    f"{utils.debug_dump_dir}/{uid}_raw.png"
                                )
                                debug_image = subtract_background(debug_image)
                                debug_image = debug_image.convert("RGB")
                                debug_image = ImageOps.autocontrast(debug_image)
                                debug_image.save(
                                    f"{utils.debug_dump_dir}/{uid}_sub.png"
                                )

                                ss.save(f"{utils.debug_dump_dir}/{uid}_screenshot.png")

                                with open(
                                    f"{utils.debug_dump_dir}/{uid}_solution.json", "w"
                                ) as f:
                                    json.dump(debug_solution, f, indent=4)

                                with open(
                                    f"{utils.debug_dump_dir}/{uid}_location.json", "w"
                                ) as f:
                                    json.dump(debug_location, f, indent=4)

                                if debug_dt is not None:
                                    with open(
                                        f"{utils.debug_dump_dir}/{uid}_datetime.json",
                                        "w",
                                    ) as f:
                                        json.dump(debug_dt.isoformat(), f, indent=4)

                                # Dump shared state
                                shared_state.serialize(
                                    f"{utils.debug_dump_dir}/{uid}_sharedstate.pkl"
                                )

                                # Dump UI State
                                with open(
                                    f"{utils.debug_dump_dir}/{uid}_uistate.json", "wb"
                                ) as f:
                                    pickle.dump(ui_state, f)

                                console.write(f"Debug dump: {uid}")
                                menu_manager.message("Debug Info Saved", timeout=1)

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

                # check for coming out of power save...
                if get_sleep_timeout(cfg) or get_screen_off_timeout(cfg):
                    # make sure that if there is a sleep
                    # time configured, the timouts are reset
                    if screen_dim is None:
                        screen_dim, screen_off = _calculate_timeouts(cfg)

                    _imu = shared_state.imu()
                    if _imu:
                        if _imu["moving"]:
                            screen_dim, screen_off = _calculate_timeouts(cfg)
                            wake_screen(screen_brightness, shared_state, cfg)
                            shared_state.set_power_state(1)  # Normal

                    power_state = shared_state.power_state()
                    # Check for going into power save...
                    if screen_off and time.time() > screen_off and power_state != -1:
                        shared_state.set_power_state(-1)  # screen off
                        keypad_value = (
                            3 if cfg.get_option("keypad_brightness") != "Off" else 0
                        )
                        set_keypad_brightness(keypad_value)
                        display_device.device.hide()
                    elif screen_dim and time.time() > screen_dim and power_state == 1:
                        shared_state.set_power_state(0)  # screen dimmed
                        set_brightness(int(screen_brightness / 4), cfg)
                    if power_state < 1:
                        time.sleep(0.2)

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


def rotate_logs() -> Path:
    """
    Rotates log files, returns the log file to use
    """
    log_index = list(range(5))
    log_index.reverse()
    for i in log_index:
        try:
            shutil.copyfile(
                utils.data_dir / f"pifinder.{i}.log",
                utils.data_dir / f"pifinder.{i+1}.log",
            )
        except FileNotFoundError:
            pass

    try:
        shutil.move(
            utils.data_dir / "pifinder.log",
            utils.data_dir / "pifinder.0.log",
        )
    except FileNotFoundError:
        pass

    return utils.data_dir / "pifinder.log"


if __name__ == "__main__":
    print("Boostrap logging configuration ...")
    logging.basicConfig(format="%(asctime)s BASIC %(name)s: %(levelname)s %(message)s")
    rlogger = logging.getLogger()
    rlogger.setLevel(logging.INFO)
    log_path = rotate_logs()
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
        help="Use a fake hardware for imu, gps",
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
    args = parser.parse_args()
    # add the handlers to the logger
    if args.verbose:
        rlogger.setLevel(logging.DEBUG)

    if args.fakehardware:
        hardware_platform = "Fake"
        display_hardware = "pg_128"
        from PiFinder import imu_fake as imu
        from PiFinder import gps_fake as gps_monitor
    else:
        hardware_platform = "Pi"
        display_hardware = "ssd1351"
        from rpi_hardware_pwm import HardwarePWM
        from PiFinder import imu_pi as imu  # type: ignore[no-redef]
        from PiFinder import gps_pi as gps_monitor  # type: ignore[no-redef]

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

        rlogger.warn("using no keyboard")

    # if args.log:
    #    datenow = datetime.datetime.now()
    #    filehandler = f"PiFinder-{datenow:%Y%m%d-%H_%M_%S}.log"
    #    fh = logging.FileHandler(filehandler)
    #    fh.setLevel(logger.level)
    #    rlogger.addHandler(fh)

    try:
        main(log_helper, args.script, args.fps, args.verbose)
    except Exception:
        rlogger.exception("Exception in main(). Aborting program.")
        os._exit(1)
