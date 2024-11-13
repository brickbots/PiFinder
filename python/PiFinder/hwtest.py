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
import logging
import argparse
import shutil
from pathlib import Path
from PIL import Image
from multiprocessing import Process, Queue
from multiprocessing.managers import BaseManager

from PiFinder import utils
from PiFinder import keyboard_interface

from PiFinder.multiproclogging import MultiprocLogging

from PiFinder.ui.console import UIConsole

from PiFinder.state import SharedStateObj, UIState

from PiFinder.displays import DisplayBase, get_display
from PiFinder import sys_utils

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


def set_brightness(level):
    """
    Sets oled/keypad brightness
    0-255
    """
    global display_device
    display_device.set_brightness(level)

    if keypad_pwm:
        set_keypad_brightness(level * 0.05)


class StateManager(BaseManager):
    pass


StateManager.register("SharedState", SharedStateObj)
StateManager.register("UIState", UIState)
StateManager.register("NewImage", Image.new)


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

    # init queues
    console_queue: Queue = Queue()
    keyboard_queue: Queue = Queue()
    gps_queue: Queue = Queue()
    camera_command_queue: Queue = Queue()
    alignment_command_queue: Queue = Queue()
    alignment_response_queue: Queue = Queue()
    ui_queue: Queue = Queue()

    # init queues for logging
    keyboard_logqueue: Queue = log_helper.get_queue()
    gps_logqueue: Queue = log_helper.get_queue()
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

    # init screen
    set_brightness(255)

    cfg = None
    import PiFinder.manager_patch as patch

    patch.apply()

    with StateManager() as manager:
        shared_state = manager.SharedState()  # type: ignore[attr-defined]
        ui_state = manager.UIState()  # type: ignore[attr-defined]
        shared_state.set_ui_state(ui_state)
        shared_state.set_arch(arch)  # Normal
        logger.debug("Ui state in main is" + str(shared_state.ui_state()))
        console = UIConsole(
            display_device, None, shared_state, command_queues, cfg, None
        )
        console.write("Starting....")
        console.update()

        # Load last location, set lock to false
        initial_location = {"gps_lock": False}
        shared_state.set_location(initial_location)

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

        # IMU
        console.write("   IMU")
        console.update()
        imu_process = Process(
            name="IMU",
            target=imu.imu_monitor,
            args=(shared_state, console_queue, imu_logqueue),
        )
        imu_process.start()

        # Start main event loop
        console.write("   Event Loop")
        console.update()

        console.active()

        # Start of main except handler / loop
        kp_level = 100
        try:
            while True:
                imu_state = shared_state.imu()
                if imu_state is None:
                    if kp_level > 0:
                        kp_level = 0
                    else:
                        kp_level = 100
                    set_keypad_brightness(kp_level)
                    time.sleep(0.250)

                # Console
                try:
                    console_msg = console_queue.get(block=False)
                    console.write(console_msg)
                except queue.Empty:
                    pass

                # GPS
                try:
                    gps_msg, gps_content = gps_queue.get(block=False)
                    console.write(f"{gps_msg} / {gps_content}")
                    console.update()
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

                # Keyboard
                keycode = None
                try:
                    while True:
                        keycode = keyboard_queue.get(block=False)
                except queue.Empty:
                    pass

                # Register activity here will return True if the power
                # state changes.  If so, we DO NOT process this keystroke
                if keycode is not None:
                    if keycode == 204:  # lng square
                        sys_utils.shutdown()
                    if kp_level > 0:
                        kp_level = 0
                    else:
                        kp_level = 10
                    set_keypad_brightness(kp_level)

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

            logger.info("\tGPS...")
            gps_process.terminate()

            logger.info("\tIMU...")
            imu_process.join()

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
    print("Bootstrap logging configuration ...")
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
        # gps_monitor = importlib.import_module("PiFinder.gps_pi")
    else:
        hardware_platform = "Pi"
        display_hardware = "ssd1351"
        from rpi_hardware_pwm import HardwarePWM

        imu = importlib.import_module("PiFinder.imu_pi")
        gps_monitor = importlib.import_module("PiFinder.gps_pi")

    if args.display is not None:
        display_hardware = args.display.lower()

    if args.camera.lower() == "pi":
        rlogger.info("using pi camera")
    elif args.camera.lower() == "debug":
        rlogger.info("using debug camera")
    elif args.camera.lower() == "asi":
        rlogger.info("using asi camera")
    else:
        rlogger.warn("not using camera")

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
