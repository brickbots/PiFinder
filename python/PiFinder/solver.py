#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is the solver
* Checks IMU
* Plate solves high-res image

"""
import queue
import pprint
import time
from tetra3 import Tetra3


def solver(shared_state, camera_image):
    t3 = Tetra3("default_database")
    last_image_fetch = 0
    while True:
        last_image_time = shared_state.last_image_time()
        if last_image_time > last_image_fetch:
            print("SOLVER: New Image")
            solve_image = camera_image.copy()
            solved = t3.solve_from_image(
                solve_image,
                fov_estimate=10.2,
                fov_max_error=0.1,
            )
            pprint.pprint(solved)
            shared_state.set_solve(solved)
            last_image_fetch = last_image_time
