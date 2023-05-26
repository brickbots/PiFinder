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
import pytz
import logging
import argparse
from PIL import Image, ImageDraw, ImageFont, ImageChops, ImageOps
from multiprocessing import Process, Queue, log_to_stderr
from multiprocessing.managers import BaseManager
from timezonefinder import TimezoneFinder
from pathlib import Path


from luma.core.interface.serial import spi
from luma.core.render import canvas
from PiFinder.camera_pi import CameraPI
from PiFinder.camera_debug import CameraDebug
from PiFinder.camera_asi import CameraASI


from PiFinder import camera
from PiFinder import solver
from PiFinder import integrator
from PiFinder import gps_monitor
from PiFinder import config
from PiFinder import pos_server
from PiFinder import utils

from PiFinder.ui.chart import UIChart
from PiFinder.ui.preview import UIPreview
from PiFinder.ui.console import UIConsole
from PiFinder.ui.status import UIStatus
from PiFinder.ui.catalog import UICatalog
from PiFinder.ui.locate import UILocate
from PiFinder.ui.config import UIConfig
from PiFinder.ui.log import UILog

from PiFinder.state import SharedStateObj

from PiFinder.image_util import subtract_background, DeviceWrapper
from PiFinder.image_util import RED_RGB, RED_BGR, GREY
from PiFinder.keyboard_local import KeyboardLocal
from PiFinder.keyboard_pi import KeyboardPi


device: DeviceWrapper = DeviceWrapper(None, RED_RGB)


def init_display(fakehardware):
    global device
    if fakehardware:
        from luma.emulator.device import pygame
        # init display  (SPI hardware)
        pygame = pygame(width=128, height=128, rotate=0, mode='RGB', transform='scale2x', scale=2, frame_rate=60)
        wrapper = DeviceWrapper(pygame, RED_RGB)
    else:
        from luma.oled.device import ssd1351
        # init display  (SPI hardware)
        serial = spi(device=0, port=0)
        device_serial = ssd1351(serial)
        wrapper = DeviceWrapper(device_serial, RED_BGR)
    return wrapper


def setup_dirs():
    utils.create_path(Path(utils.data_dir))
    utils.create_path(Path(utils.data_dir, 'captures'))
    utils.create_path(Path(utils.data_dir, 'obslists'))
    utils.create_path(Path(utils.data_dir, 'screenshots'))
    utils.create_path(Path(utils.data_dir, 'solver_debug_dumps'))
    utils.create_path(Path(utils.data_dir, 'logs'))
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


def main(script_name, fakehardware, camera_type):
    """
    Get this show on the road!
    """
    # log_to_stderr(logging.DEBUG)
    device = init_display(fakehardware)
    setup_dirs()
    # Set path for test images
    root_dir = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))
    test_image_path = os.path.join(root_dir, "test_images")

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
    }
    ui_state["active_list"] = ui_state["history_list"]

    # init screen
    screen_brightness = cfg.get_option("display_brightness")
    device.set_brightness(screen_brightness)
    console = UIConsole(device, None, None, command_queues, ui_state, cfg)
    console.write("Starting....")
    console.update()
    time.sleep(2)

    # multiprocessing.set_start_method('spawn')
    # spawn keyboard service....
    console.write("   Keyboard")
    console.update()
    script_path = None
    if script_name:
        script_path = os.path.join(root_dir, "scripts", script_name)
    if fakehardware:
        keyboard = KeyboardLocal(keyboard_queue)
    else:
        keyboard = KeyboardPi(keyboard_queue)
        keyboard_process = Process(
            target=keyboard.run_keyboard, args=(keyboard_queue, script_path)
        )
        keyboard_process.start()

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

        # Load last location, set lock to false
        tz_finder = TimezoneFinder()
        initial_location = cfg.get_option("last_location")
        initial_location["timezone"] = tz_finder.timezone_at(
            lat=initial_location["lat"], lng=initial_location["lon"]
        )
        shared_state.set_location(initial_location)

        console.write("   Camera")
        console.update()
        if camera_type == "pi":
            camera_hardware = CameraPI()
        elif camera_type == "asi":
            camera_hardware = CameraASI()
        else:
            camera_hardware = CameraDebug()
        camera_image = manager.NewImage("RGB", (512, 512))
        print("camera hardware is", camera_hardware)
        image_process = Process(
            target=camera.get_images,
            args=(shared_state, camera_hardware, camera_image, camera_command_queue, console_queue),
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
            UIConfig(device, camera_image, shared_state, command_queues, ui_state, cfg),
            UIChart(device, camera_image, shared_state, command_queues, ui_state, cfg),
            UICatalog(
                device,
                camera_image,
                shared_state,
                command_queues,
                ui_state,
                cfg,
            ),
            UILocate(device, camera_image, shared_state, command_queues, ui_state, cfg),
            UIPreview(
                device, camera_image, shared_state, command_queues, ui_state, cfg
            ),
            UIStatus(device, camera_image, shared_state, command_queues, ui_state, cfg),
            console,
            UILog(device, camera_image, shared_state, command_queues, ui_state, cfg),
        ]

        # What is the highest index for observing modes
        # vs status/debug modes accessed by alt-A
        ui_observing_modes = 3
        ui_mode_index = 4
        logging_mode_index = 7

        current_module = ui_modes[ui_mode_index]

        # Start of main except handler / loop
        power_save_warmup = time.time() + get_sleep_timeout(cfg)
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
                            if location["gps_lock"] == False:
                                # Write to config if we just got a lock
                                location["timezone"] = tz_finder.timezone_at(
                                    lat=location["lat"], lng=location["lon"]
                                )
                                cfg.set_option("last_location", location)
                                console.write("GPS: Location")
                                location["gps_lock"] = True
                            shared_state.set_location(location)
                    if gps_msg == "time":
                        gps_dt = datetime.datetime.fromisoformat(
                            gps_content.replace("Z", "")
                        )

                        # Some GPS transcievers will report a time, even before
                        # they have one.  This is a sanity check for this.
                        if gps_dt > datetime.datetime(2023, 4, 1, 1, 1, 1):
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
                        device.set_brightness(screen_brightness)

                # Keyboard
                try:
                    keycode = keyboard_queue.get(block=False)
                except queue.Empty:
                    keycode = None

                if keycode != None:
                    power_save_warmup = time.time() + get_sleep_timeout(cfg)
                    keyboard.set_brightness(screen_brightness, cfg)
                    shared_state.set_power_state(1)  # Normal

                    # ignore keystroke if we have been asleep
                    if shared_state.power_state() > 0:
                        if keycode > 99:
                            # Special codes....
                            if keycode == keyboard.ALT_UP or keycode == keyboard.ALT_DN:
                                if keycode == keyboard.ALT_UP:
                                    screen_brightness = screen_brightness + 10
                                    if screen_brightness > 255:
                                        screen_brightness = 255
                                else:
                                    screen_brightness = screen_brightness - 10
                                    if screen_brightness < 1:
                                        screen_brightness = 1
                                device.set_brightness(screen_brightness)
                                cfg.set_option("display_brightness", screen_brightness)
                                console.write("Brightness: " + str(screen_brightness))

                            if keycode == keyboard.ALT_A:
                                # Switch between non-observing modes
                                ui_mode_index += 1
                                if ui_mode_index >= len(ui_modes):
                                    ui_mode_index = ui_observing_modes + 1
                                if ui_mode_index <= ui_observing_modes:
                                    ui_mode_index = ui_observing_modes + 1
                                current_module = ui_modes[ui_mode_index]
                                current_module.active()

                            if keycode == keyboard.LNG_A and ui_mode_index > 0:
                                # long A for config of current module
                                target_module = current_module
                                if target_module._config_options:
                                    # only activate this if current module
                                    # has config options
                                    ui_mode_index = 0
                                    current_module = ui_modes[0]
                                    current_module.set_module(target_module)
                                    current_module.active()

                            if keycode == keyboard.LNG_ENT and ui_mode_index > 0:
                                # long ENT for log observation
                                ui_mode_index = logging_mode_index
                                current_module = ui_modes[logging_mode_index]
                                current_module.active()

                            if keycode == keyboard.ALT_0:
                                # screenshot
                                current_module.screengrab()
                                console.write("Screenshot saved")

                            if keycode == keyboard.ALT_D:
                                # Debug snapshot
                                uid = str(uuid.uuid1()).split("-")[0]
                                debug_image = camera_image.copy()
                                debug_solution = shared_state.solution()
                                debug_location = shared_state.location()
                                debug_dt = shared_state.datetime()

                                # write images
                                debug_image.save(f"{test_image_path}/{uid}_raw.png")
                                debug_image = subtract_background(debug_image)
                                debug_image = debug_image.convert("RGB")
                                debug_image = ImageOps.autocontrast(debug_image)
                                debug_image.save(f"{test_image_path}/{uid}_sub.png")

                                with open(
                                    f"{test_image_path}/{uid}_solution.json", "w"
                                ) as f:
                                    json.dump(debug_solution, f, indent=4)

                                with open(
                                    f"{test_image_path}/{uid}_location.json", "w"
                                ) as f:
                                    json.dump(debug_location, f, indent=4)

                                if debug_dt is not None:
                                    with open(
                                        f"{test_image_path}/{uid}_datetime.json", "w"
                                    ) as f:
                                        json.dump(debug_dt.isoformat(), f, indent=4)

                                console.write(f"Debug dump: {uid}")

                        elif keycode == keyboard.A:
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

                            elif keycode == keyboard.UP:
                                current_module.key_up()

                            elif keycode == keyboard.DN:
                                current_module.key_down()

                            elif keycode == keyboard.ENT:
                                current_module.key_enter()

                            elif keycode == keyboard.B:
                                current_module.key_b()

                            elif keycode == keyboard.C:
                                current_module.key_c()

                            elif keycode == keyboard.D:
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
                if get_sleep_timeout(cfg):
                    # make sure that if there is a sleep
                    # time configured, the power_save_warmup is reset
                    if power_save_warmup == None:
                        power_save_warmup = time.time() + get_sleep_timeout(cfg)

                    _imu = shared_state.imu()
                    if _imu:
                        if _imu["moving"]:
                            power_save_warmup = time.time() + get_sleep_timeout(cfg)
                            keyboard.set_brightness(screen_brightness, cfg)
                            shared_state.set_power_state(1)  # Normal

                    # Check for going into power save...
                    if time.time() > power_save_warmup:
                        keyboard.set_brightness(int(screen_brightness / 4), cfg)
                        shared_state.set_power_state(0)  # sleep
                    if time.time() > power_save_warmup:
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
    script_name = None
    args = sys.argv
    print("starting main")
    if len(args) > 1:
        script_name = args[-1]
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logging.basicConfig(
        format="%(asctime)s %(name)s: %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="eFinder")
    parser.add_argument(
        "-fh",
        "--fakehardware",
        help="Use a fake hardware for imu, gps, keyboard",
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
    parser.add_argument(
        "-l", "--log", help="Log to file", action="store_true"
    )
    args = parser.parse_args()
    # add the handlers to the logger
    if args.verbose:
        logger.setLevel(logging.DEBUG)

    if args.fakehardware:
        from PiFinder import imu_fake as imu
    else:
        from PiFinder import imu

    if args.log:
        datenow = datetime.now()
        filehandler = f"PiFinder-{datenow:%Y%m%d-%H_%M_%S}.log"
        fh = logging.FileHandler(filehandler)
        fh.setLevel(logger.level)
        logger.addHandler(fh)

    main(script_name, args.fakehardware, args.camera)
