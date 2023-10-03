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
import time
import queue
import datetime
import json
import uuid
import os
import sys
import logging
import argparse
import pickle
from pathlib import Path
from PIL import Image, ImageOps
from multiprocessing import Process, Queue
from multiprocessing.managers import BaseManager
from timezonefinder import TimezoneFinder


from luma.core.interface.serial import spi

from PiFinder import solver
from PiFinder import integrator
from PiFinder import config
from PiFinder import pos_server
from PiFinder import utils
from PiFinder import server
from PiFinder import keyboard_interface

from PiFinder.ui.chart import UIChart
from PiFinder.ui.preview import UIPreview
from PiFinder.ui.console import UIConsole
from PiFinder.ui.status import UIStatus
from PiFinder.ui.catalog import UICatalog
from PiFinder.ui.locate import UILocate
from PiFinder.ui.config import UIConfig
from PiFinder.ui.log import UILog

from PiFinder.state import SharedStateObj

from PiFinder.image_util import (
    subtract_background,
    DeviceWrapper,
    RED_RGB,
    RED_BGR,
    GREY,
)


hardware_platform = "Pi"
display_device: DeviceWrapper = DeviceWrapper(None, RED_RGB)
keypad_pwm = None


def init_display():
    global display_device
    global hardware_platform

    if hardware_platform == "Fake":
        from luma.emulator.device import pygame

        # init display  (SPI hardware)
        pygame = pygame(
            width=128,
            height=128,
            rotate=0,
            mode="RGB",
            transform="scale2x",
            scale=2,
            frame_rate=60,
        )
        display_device = DeviceWrapper(pygame, RED_RGB)
    elif hardware_platform == "Pi":
        from luma.oled.device import ssd1351

        # init display  (SPI hardware)
        serial = spi(device=0, port=0)
        device_serial = ssd1351(serial, rotate=0, bgr=True)
        device_serial.capabilities(width=128, height=128, rotate=0, mode="RGB")
        display_device = DeviceWrapper(device_serial, RED_RGB)
    else:
        print("Hardware platform not recognized")


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
        logging.error("Invalid percentage for keypad brightness")
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
StateManager.register("NewImage", Image.new)


def get_sleep_timeout(cfg):
    """
    returns the sleep timeout amount
    """
    sleep_timeout_option = cfg.get_option("sleep_timeout")
    sleep_timeout = {"Off": 100000, "10s": 10, "30s": 30, "1m": 60}[
        sleep_timeout_option
    ]
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
    set_brightness(screen_brightness, cfg)
    display_device.device.show()
    orig_power_state = shared_state.power_state()
    shared_state.set_power_state(1)  # Normal
    return orig_power_state


def main(script_name=None, has_server=False, show_fps=False):
    """
    Get this show on the road!
    """
    global display_device

    init_display()
    init_keypad_pwm()
    setup_dirs()

    # Instantiate base keyboard class for keycode
    keyboard_base = keyboard_interface.KeyboardInterface()

    # Set path for test images
    root_dir = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))

    # init queues
    console_queue = Queue()
    keyboard_queue = Queue()
    gps_queue = Queue()
    camera_command_queue = Queue()
    solver_queue = Queue()
    ui_queue = Queue()

    # init UI Modes
    command_queues = {
        "camera": camera_command_queue,
        "console": console_queue,
        "ui_queue": ui_queue,
    }
    cfg = config.Config()

    # Unit UI shared state
    ui_state = {
        "history_list": [],
        "observing_list": [],
        "target": None,
        "message_timeout": 0,
        "show_fps": show_fps,
        "hint_timeout": cfg.get_option("hint_timeout"),
    }
    ui_state["active_list"] = ui_state["history_list"]

    # init screen
    screen_brightness = cfg.get_option("display_brightness")
    set_brightness(screen_brightness, cfg)
    console = UIConsole(display_device, None, None, command_queues, ui_state, cfg)
    console.write("Starting....")
    console.update()
    time.sleep(2)

    # spawn gps service....
    console.write("   GPS")
    console.update()
    gps_process = Process(
        target=gps_monitor.gps_monitor,
        args=(
            gps_queue,
            console_queue,
        ),
    )
    gps_process.start()

    with StateManager() as manager:
        shared_state = manager.SharedState()
        console.set_shared_state(shared_state)

        # multiprocessing.set_start_method('spawn')
        # spawn keyboard service....
        console.write("   Keyboard")
        console.update()
        keyboard_process = Process(
            target=keyboard.run_keyboard,
            args=(keyboard_queue, shared_state),
        )
        keyboard_process.start()
        if script_name:
            script_path = f"../scripts/{script_name}.pfs"
            p = Process(
                target=keyboard_interface.KeyboardInterface.run_script,
                args=(script_path, keyboard_queue),
            )
            p.start()
        if has_server:
            server_process = Process(
                target=server.run_server,
                args=(keyboard_queue, gps_queue, shared_state),
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

        console.write("   Camera")
        console.update()
        camera_image = manager.NewImage("RGB", (512, 512))
        image_process = Process(
            target=camera.get_images,
            args=(shared_state, camera_image, camera_command_queue, console_queue),
        )
        image_process.start()
        time.sleep(1)

        # IMU
        console.write("   IMU")
        console.update()
        imu_process = Process(
            target=imu.imu_monitor, args=(shared_state, console_queue)
        )
        imu_process.start()

        # Solver
        console.write("   Solver")
        console.update()
        solver_process = Process(
            target=solver.solver,
            args=(shared_state, solver_queue, camera_image, console_queue),
        )
        solver_process.start()

        # Integrator
        console.write("   Integrator")
        console.update()
        integrator_process = Process(
            target=integrator.integrator,
            args=(shared_state, solver_queue, console_queue),
        )
        integrator_process.start()

        # Server
        console.write("   Server")
        console.update()
        server_process = Process(
            target=pos_server.run_server, args=(shared_state, None)
        )
        server_process.start()

        # Start main event loop
        console.write("   Event Loop")
        console.update()

        ui_modes = [
            UIConfig(
                display_device,
                camera_image,
                shared_state,
                command_queues,
                ui_state,
                cfg,
            ),
            UIChart(
                display_device,
                camera_image,
                shared_state,
                command_queues,
                ui_state,
                cfg,
            ),
            UICatalog(
                display_device,
                camera_image,
                shared_state,
                command_queues,
                ui_state,
                cfg,
            ),
            UILocate(
                display_device,
                camera_image,
                shared_state,
                command_queues,
                ui_state,
                cfg,
            ),
            UIPreview(
                display_device,
                camera_image,
                shared_state,
                command_queues,
                ui_state,
                cfg,
            ),
            UIStatus(
                display_device,
                camera_image,
                shared_state,
                command_queues,
                ui_state,
                cfg,
            ),
            console,
            UILog(
                display_device,
                camera_image,
                shared_state,
                command_queues,
                ui_state,
                cfg,
            ),
        ]

        # What is the highest index for observing modes
        # vs status/debug modes accessed by alt-A
        ui_observing_modes = 4
        ui_mode_index = 4
        logging_mode_index = 7

        current_module = ui_modes[ui_mode_index]

        # Start of main except handler / loop
        screen_dim, screen_off = _calculate_timeouts(cfg)
        bg_task_warmup = 5
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
                        gps_dt = gps_content
                        shared_state.set_datetime(gps_dt)
                except queue.Empty:
                    pass

                # ui queue
                try:
                    ui_command = ui_queue.get(block=False)
                except queue.Empty:
                    ui_command = None
                if ui_command:
                    if ui_command == "set_brightness":
                        set_brightness(screen_brightness, cfg)

                # Keyboard
                try:
                    keycode = keyboard_queue.get(block=False)
                except queue.Empty:
                    keycode = None

                if keycode is not None:
                    # logging.debug(f"Keycode: {keycode}")
                    screen_dim, screen_off = _calculate_timeouts(cfg)
                    original_power_state = wake_screen(
                        screen_brightness, shared_state, cfg
                    )

                    # ignore keystroke if we have been asleep
                    if original_power_state > 0:
                        if keycode > 99:
                            # Special codes....
                            if (
                                keycode == keyboard_base.ALT_UP
                                or keycode == keyboard_base.ALT_DN
                            ):
                                if keycode == keyboard_base.ALT_UP:
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

                            if keycode == keyboard_base.ALT_A:
                                # Switch between non-observing modes
                                ui_mode_index += 1
                                if ui_mode_index >= len(ui_modes):
                                    ui_mode_index = ui_observing_modes + 1
                                if ui_mode_index <= ui_observing_modes:
                                    ui_mode_index = ui_observing_modes + 1
                                current_module = ui_modes[ui_mode_index]
                                current_module.active()

                            if keycode == keyboard_base.LNG_A and ui_mode_index > 0:
                                # long A for config of current module
                                target_module = current_module
                                if target_module._config_options:
                                    # only activate this if current module
                                    # has config options
                                    ui_mode_index = 0
                                    current_module = ui_modes[0]
                                    current_module.set_module(target_module)
                                    current_module.active()

                            if keycode == keyboard_base.LNG_ENT and ui_mode_index > 0:
                                # long ENT for log observation
                                ui_mode_index = logging_mode_index
                                current_module = ui_modes[logging_mode_index]
                                current_module.active()

                            if keycode == keyboard_base.ALT_0:
                                # screenshot
                                current_module.screengrab()
                                console.write("Screenshot saved")

                            if keycode == keyboard_base.LNG_D:
                                current_module.delete()
                                console.write("Deleted")

                            if keycode == keyboard_base.LNG_C:
                                current_module.key_long_c()

                            if keycode == keyboard_base.ALT_D:
                                # Debug snapshot
                                uid = str(uuid.uuid1()).split("-")[0]
                                debug_image = camera_image.copy()
                                debug_solution = shared_state.solution()
                                debug_location = shared_state.location()
                                debug_dt = shared_state.datetime()

                                # current screen
                                ss = current_module.screen.copy()

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

                                if debug_dt != None:
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
                                current_module.message("Debug Info Saved")

                        elif keycode == keyboard_base.A:
                            # A key, mode switch
                            if ui_mode_index == 0:
                                # return control to original module
                                for i, ui_class in enumerate(ui_modes):
                                    if ui_class == ui_modes[0].get_module():
                                        ui_mode_index = i
                                        current_module = ui_class
                                        current_module.update_config()
                                        current_module.active()
                            else:
                                ui_mode_index += 1
                                if ui_mode_index > ui_observing_modes:
                                    ui_mode_index = 1
                                current_module = ui_modes[ui_mode_index]
                                current_module.active()

                        else:
                            if keycode < 10:
                                current_module.key_number(keycode)

                            elif keycode == keyboard_base.UP:
                                current_module.key_up()

                            elif keycode == keyboard_base.DN:
                                current_module.key_down()

                            elif keycode == keyboard_base.ENT:
                                current_module.key_enter()

                            elif keycode == keyboard_base.B:
                                current_module.key_b()

                            elif keycode == keyboard_base.C:
                                current_module.key_c()

                            elif keycode == keyboard_base.D:
                                current_module.key_d()

                update_msg = current_module.update()
                if update_msg:
                    for i, ui_class in enumerate(ui_modes):
                        if ui_class.__class__.__name__ == update_msg:
                            ui_mode_index = i
                            current_module = ui_class
                            current_module.active()

                # check for BG task time...
                bg_task_warmup -= 1
                if bg_task_warmup == 0:
                    bg_task_warmup = 5
                    for module in ui_modes:
                        module.background_update()

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
            print("SHUTDOWN")
            print("\tClearing console queue...")
            try:
                while True:
                    console_queue.get(block=False)
            except queue.Empty:
                pass

            print("\tKeyboard...")
            try:
                while True:
                    keyboard_queue.get(block=False)
            except queue.Empty:
                keyboard_process.join()

            print("\tServer...")
            server_process.join()

            print("\tGPS...")
            gps_process.terminate()

            print("\tImaging...")
            image_process.join()

            print("\tIMU...")
            imu_process.join()

            print("\tIntegrator...")
            integrator_process.join()

            print("\tSolver...")
            solver_process.join()
            exit()


if __name__ == "__main__":
    print("Starting PiFinder ...")
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logging.getLogger("PIL.PngImagePlugin").setLevel(logging.WARNING)
    logging.getLogger("tetra3.Tetra3").setLevel(logging.WARNING)
    logging.getLogger("picamera2.picamera2").setLevel(logging.WARNING)
    logging.basicConfig(format="%(asctime)s %(name)s: %(levelname)s %(message)s")
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
        help="Specify which camera to use: pi, asi or debug",
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
        "-s",
        "--server",
        help="Start a server to control the pifinder",
        default=False,
        action="store_true",
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
        logger.setLevel(logging.DEBUG)

    if args.fakehardware:
        hardware_platform = "Fake"
        from PiFinder import imu_fake as imu
        from PiFinder import gps_fake as gps_monitor
    else:
        hardware_platform = "Pi"
        from rpi_hardware_pwm import HardwarePWM
        from PiFinder import imu_pi as imu
        from PiFinder import gps_pi as gps_monitor

    if args.camera.lower() == "pi":
        logging.debug("using pi camera")
        from PiFinder import camera_pi as camera
    elif args.camera.lower() == "debug":
        logging.debug("using debug camera")
        from PiFinder import camera_debug as camera
    elif args.camera.lower() == "asi":
        logging.debug("using asi camera")
        from PiFinder import camera_asi as camera_debug
    else:
        logging.debug("not using camera")
        from PiFinder import camera_none as camera

    if args.keyboard.lower() == "pi":
        from PiFinder import keyboard_pi as keyboard
    elif args.keyboard.lower() == "local":
        from PiFinder import keyboard_local as keyboard

    if args.log:
        datenow = datetime.datetime.now()
        filehandler = f"PiFinder-{datenow:%Y%m%d-%H_%M_%S}.log"
        fh = logging.FileHandler(filehandler)
        fh.setLevel(logger.level)
        logger.addHandler(fh)

    main(args.script, args.server, args.fps)
