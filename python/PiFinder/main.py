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
from PIL import Image, ImageDraw, ImageFont, ImageChops, ImageOps
from multiprocessing import Process, Queue
from multiprocessing.managers import BaseManager
from timezonefinder import TimezoneFinder

from luma.core.interface.serial import spi
from luma.core.render import canvas
from luma.oled.device import ssd1351

from PiFinder import keyboard
from PiFinder import camera
from PiFinder import solver
from PiFinder import gps
from PiFinder import imu
from PiFinder import config
from PiFinder import pos_server

from PiFinder.ui.chart import UIChart
from PiFinder.ui.preview import UIPreview
from PiFinder.ui.console import UIConsole
from PiFinder.ui.status import UIStatus
from PiFinder.ui.catalog import UICatalog
from PiFinder.ui.locate import UILocate
from PiFinder.ui.config import UIConfig
from PiFinder.ui.log import UILog

from PiFinder.state import SharedStateObj

from PiFinder.image_util import subtract_background

serial = spi(device=0, port=0)
device = ssd1351(serial)


def set_brightness(level):
    """
    Sets oled brightness
    0-255
    """
    device.contrast(level)


class StateManager(BaseManager):
    pass


StateManager.register("SharedState", SharedStateObj)
StateManager.register("NewImage", Image.new)


def main(script_name=None):
    """
    Get this show on the road!
    """
    # Set path for test images
    root_dir = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))
    test_image_path = os.path.join(root_dir, "test_images")

    # init queues
    console_queue = Queue()
    keyboard_queue = Queue()
    gps_queue = Queue()
    camera_command_queue = Queue()

    # init UI Modes
    command_queues = {
        "camera": camera_command_queue,
        "console": console_queue,
    }
    cfg = config.Config()

    # Unit UI shared state
    ui_state = {
        "history_list": [],
        "observing_list": [],
        "target": None,
    }
    ui_state["active_list"] = ui_state["history_list"]

    # init screen
    screen_brightness = cfg.get_option("display_brightness")
    set_brightness(screen_brightness)
    console = UIConsole(device, None, None, command_queues)
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
    keyboard_process = Process(
        target=keyboard.run_keyboard, args=(keyboard_queue, script_path)
    )
    keyboard_process.start()

    # spawn gps service....
    console.write("   GPS")
    console.update()
    gps_process = Process(
        target=gps.gps_monitor,
        args=(
            gps_queue,
            console_queue,
        ),
    )
    gps_process.start()

    # spawn imaging service
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
            target=solver.solver, args=(shared_state, camera_image, console_queue)
        )
        solver_process.start()

        # Solver
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

        # Start of main except handler
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
                    gps_msg = gps_queue.get(block=False)
                    if gps_msg.sentence_type == "GGA":
                        if gps_msg.latitude + gps_msg.longitude != 0:
                            location = shared_state.location()
                            location["lat"] = gps_msg.latitude
                            location["lon"] = gps_msg.longitude
                            location["altitude"] = gps_msg.altitude
                            if location["gps_lock"] == False:
                                # Write to config if we just got a lock
                                location["timezone"] = tz_finder.timezone_at(
                                    lat=location["lat"], lng=location["lon"]
                                )
                                cfg.set_option("last_location", location)
                                console.write("GPS: Location")
                                location["gps_lock"] = True
                            shared_state.set_location(location)
                    if gps_msg.sentence_type == "RMC":
                        if gps_msg.datestamp:
                            if gps_msg.datestamp.year > 2021:
                                shared_state.set_datetime(
                                    datetime.datetime.combine(
                                        gps_msg.datestamp, gps_msg.timestamp
                                    )
                                )
                except queue.Empty:
                    pass

                # Keyboard
                try:
                    keycode = keyboard_queue.get(block=False)
                except queue.Empty:
                    keycode = None

                if keycode != None:
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
                            set_brightness(screen_brightness)
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

                            if debug_dt != None:
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

            print("\tSolver...")
            solver_process.join()
            exit()


if __name__ == "__main__":
    script_name = None
    args = sys.argv
    if len(args) > 1:
        script_name = args[-1]
    main(script_name)
