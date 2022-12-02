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
import gc
from PIL import Image, ImageDraw, ImageFont, ImageChops, ImageOps
from multiprocessing import Process, Queue
from multiprocessing.managers import BaseManager
from timezonefinder import TimezoneFinder

from luma.core.interface.serial import spi
from luma.core.render import canvas
from luma.oled.device import ssd1351

import keyboard
import camera
import solver
import gps
import imu
import config

from uimodules import UIChart, UIPreview, UIConsole, UIStatus, UICatalog, UILocate

from image_util import subtract_background

serial = spi(device=0, port=0)
device = ssd1351(serial)

# Clean up what might be garbage so far.
gc.collect(2)
# Exclude current items from future GC.
gc.freeze()
#
allocs, gen1, gen2 = gc.get_threshold()
allocs = 50_000  # Start the GC sequence every 50K not 700 allocations.
gen1 = gen1 * 2
gen2 = gen2 * 2
gc.set_threshold(allocs, gen1, gen2)

def set_brightness(level):
    """
    Sets oled brightness
    0-255
    """
    device.contrast(level)


class StateManager(BaseManager):
    pass


class SharedStateObj:
    def __init__(self):
        self.__solve_state = None
        self.__last_image_time = (0, 0)
        self.__solution = None
        self.__imu = None
        self.__location = None
        self.__datetime = None
        self.__target = None

    def target(self):
        return self.__target

    def set_target(self, target):
        self.__target = target

    def solve_state(self):
        return self.__solve_state

    def set_solve_state(self, v):
        self.__solve_state = v

    def imu(self):
        return self.__imu

    def set_imu(self, v):
        self.__imu = v

    def solution(self):
        return self.__solution

    def set_solution(self, v):
        self.__solution = v

    def location(self):
        return self.__location

    def set_location(self, v):
        self.__location = v

    def last_image_time(self):
        return self.__last_image_time

    def set_last_image_time(self, v):
        self.__last_image_time = v

    def datetime(self):
        return self.__datetime

    def set_datetime(self, dt):
        self.__datetime = dt


StateManager.register("SharedState", SharedStateObj)
StateManager.register("NewImage", Image.new)


def main():
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
    # init screen
    screen_brightness = cfg.get_option("display_brightness")
    set_brightness(screen_brightness)
    console = UIConsole(device, None, None, command_queues)
    console.write("Starting....")
    console.update()

    # multiprocessing.set_start_method('spawn')
    # spawn keyboard service....
    console.write("   Keyboard")
    console.update()
    keyboard_process = Process(target=keyboard.run_keyboard, args=(keyboard_queue,))
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

        # Start main event loop
        console.write("   Event Loop")
        console.update()

        ui_modes = [
            UIChart(device, camera_image, shared_state, command_queues),
            UICatalog(device, camera_image, shared_state, command_queues),
            UILocate(device, camera_image, shared_state, command_queues),
            UIPreview(device, camera_image, shared_state, command_queues),
            UIStatus(device, camera_image, shared_state, command_queues),
            console,
        ]
        # What is the highest index for observing modes
        # vs status/debug modes accessed by alt-A
        ui_observing_modes = 2
        ui_mode_index = 3

        # Start of main except handler
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
                    print(f"{keycode =}")
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
                            ui_modes[ui_mode_index].active()

                        if keycode == keyboard.ALT_0:
                            # screenshot
                            ui_modes[ui_mode_index].screengrab()
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

                            with open(
                                f"{test_image_path}/{uid}_datetime.json", "w"
                            ) as f:
                                json.dump(debug_dt.isoformat(), f, indent=4)

                            console.write(f"Debug dump: {uid}")

                    elif keycode == keyboard.A:
                        # A key, mode switch
                        ui_mode_index += 1
                        if ui_mode_index > ui_observing_modes:
                            ui_mode_index = 0
                        ui_modes[ui_mode_index].active()

                    else:
                        if keycode < 10:
                            ui_modes[ui_mode_index].key_number(keycode)

                        elif keycode == keyboard.UP:
                            ui_modes[ui_mode_index].key_up()

                        elif keycode == keyboard.DN:
                            ui_modes[ui_mode_index].key_down()

                        elif keycode == keyboard.GO:
                            ui_modes[ui_mode_index].key_enter()

                        elif keycode == keyboard.B:
                            ui_modes[ui_mode_index].key_b()

                        elif keycode == keyboard.C:
                            ui_modes[ui_mode_index].key_c()

                        elif keycode == keyboard.D:
                            ui_modes[ui_mode_index].key_d()

                update_msg = ui_modes[ui_mode_index].update()
                if update_msg:
                    for i, ui_class in enumerate(ui_modes):
                        if ui_class.__class__.__name__ == update_msg:
                            ui_mode_index = i
                            ui_class.active()

                #time.sleep(0.05)

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
    main()
