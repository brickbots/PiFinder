#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is for IMU related functions

"""

import time
from PiFinder import config
from PiFinder.multiproclogging import MultiprocLogging
from PiFinder.types.positioning import ImuSample
from PiFinder.i2c_bus import get_i2c
import adafruit_bno055
import logging
import quaternion  # Numpy quaternion

logger = logging.getLogger("IMU.pi")

QUEUE_LEN = 10


class Imu:
    """
    Previous version modified the IMU axes but the IMU now outputs the
    measurements using its native axes and the transformation from the IMU
    axes to the camera frame is done by the IMU dead-reckonig functionality.
    """

    def __init__(self):
        i2c = get_i2c()
        self.sensor = adafruit_bno055.BNO055_I2C(i2c)
        # IMPLUS mode: Accelerometer + Gyro + Fusion data
        self.sensor.mode = adafruit_bno055.IMUPLUS_MODE
        # self.sensor.mode = adafruit_bno055.NDOF_MODE

        self.quat_history = [(0, 0, 0, 0)] * QUEUE_LEN
        self._flip_count = 0
        self.calibration = 0
        self.avg_quat = (0, 0, 0, 0)  # Scalar-first quaternion as float: (w, x, y, z)
        # Raw sensor readings taken alongside the quaternion, for telemetry
        self.gyro = None
        self.accel = None
        # Epoch of the last successful sensor read
        self.last_read_time = 0.0
        self.__moving = False
        self.__reading_diff = 0.0

        self.last_sample_time = time.time()

        # Calibration settings
        self.imu_sample_frequency = 1 / 30

        # First value is delta to exceed between samples
        # to start moving, second is threshold to fall below
        # to stop moving.

        cfg = config.Config()
        # Raw gyro/accel capture is opt-in: two extra I2C transactions per
        # sample on a bus the BNO055 is sensitive about, and only useful
        # for telemetry analysis.
        self._raw_telemetry = bool(cfg.get_option("telemetry_raw_imu", False))
        imu_threshold_scale = cfg.get_option("imu_threshold_scale", 1)
        self.__moving_threshold = (
            0.0005 * imu_threshold_scale,
            0.0003 * imu_threshold_scale,
        )

    def moving(self):
        """
        Compares most recent reading
        with past readings
        """
        return self.__moving

    def update(self):
        # check for update frequency
        if time.time() - self.last_sample_time < self.imu_sample_frequency:
            return

        self.last_sample_time = time.time()

        # Throw out non-calibrated data
        self.calibration = self.sensor.calibration_status[1]
        if self.calibration == 0:
            logger.warning("NOIMU CAL")
            return True
        # adafruit_bno055 uses quaternion convention (w, x, y, z)
        quat = self.sensor.quaternion
        if quat[0] is None:
            logger.warning("IMU: Failed to get sensor values")
            return

        # When enabled, read raw sensor data alongside the quaternion so
        # the telemetry sample is coherent (same instant, same I2C burst).
        if self._raw_telemetry:
            try:
                self.gyro = self.sensor.gyro
                self.accel = self.sensor.linear_acceleration
            except (OSError, RuntimeError):
                self.gyro = None
                self.accel = None
        self.last_read_time = time.time()

        _quat_diff = []
        for i in range(4):
            _quat_diff.append(abs(quat[i] - self.quat_history[-1][i]))

        self.__reading_diff = sum(_quat_diff)

        # This seems to be some sort of defect / side effect
        # of the integration system in the BNO055
        # When not moving quat output will vaccilate
        # by exactly this amount... so filter this out
        if self.__reading_diff == 0.0078125:
            self.__reading_diff = 0
            return

        # Sometimes the quat output will 'flip' and change by 2.0+
        # from one reading to another.  This is clearly noise or an
        # artifact, so filter them out
        #
        # NOTE: This is probably due to the double-cover property of quaternions
        # where +q and -q describe the same rotation?
        if self.__reading_diff > 1.5:
            self._flip_count += 1
            if self._flip_count > 10:
                # with the history initialized to 0,0,0,0 the unit
                # can get stuck seeing flips if the IMU starts
                # returning data. This count will reset history
                # to the current state if it exceeds 10
                self.quat_history = [quat] * QUEUE_LEN
                self.__reading_diff = 0
            else:
                self.__reading_diff = 0
                return
        else:
            # no flip
            self._flip_count = 0

        # avg_quat is the latest quaternion measurement, not the average
        self.avg_quat = quat
        # Write over the quat_hisotry queue FIFO:
        if len(self.quat_history) == QUEUE_LEN:
            self.quat_history = self.quat_history[1:]
        self.quat_history.append(quat)

        if self.__moving:
            if self.__reading_diff < self.__moving_threshold[1]:
                self.__moving = False
        else:
            if self.__reading_diff > self.__moving_threshold[0]:
                self.__moving = True

    def __str__(self):
        return (
            f"IMU Information:\n"
            f"Calibration Status: {self.calibration}\n"
            f"Quaternion History: {self.quat_history}\n"
            f"Average Quaternion: {self.avg_quat}\n"
            f"Moving: {self.moving()}\n"
            f"Reading Difference: {self.__reading_diff}\n"
            f"Flip Count: {self._flip_count}\n"
            f"Last Sample Time: {self.last_sample_time}\n"
            f"IMU Sample Frequency: {self.imu_sample_frequency}\n"
            f"Moving Threshold: {self.__moving_threshold}\n"
        )


def imu_monitor(shared_state, console_queue, log_queue):
    MultiprocLogging.configurer(log_queue)
    logger.debug("Starting IMU")
    imu = None
    try:
        imu = Imu()
    except Exception as e:
        logger.error(f"Error starting phyiscal IMU : {e}")
        logger.error("Falling back to fake IMU")
        console_queue.put("IMU: Error starting physical IMU, using fake IMU")
        console_queue.put("DEGRADED_OPS IMU")
        from PiFinder.imu_fake import Imu as ImuFake

        imu = ImuFake()

    imu_calibrated = False
    imu_sample = ImuSample(
        # Scalar-first numpy quaternion(w, x, y, z) - init to invalid quaternion
        quat=quaternion.quaternion(0, 0, 0, 0),
        timestamp=0.0,  # set together with quat below, at sample time
        status=0,  # IMU Status: 3=Calibrated
        moving=False,
    )

    # update() already throttles the I2C reads to imu_sample_frequency (30 Hz),
    # but the loop body still runs every iteration — publishing the sample via
    # set_imu(), a Manager-proxy pickle. Without pacing this spins thousands/sec
    # (~19% CPU) and the per-publish pickle leaks. Capture the period once; the
    # fake-IMU fallback has no such attr (and self-throttles), hence the default.
    sample_period = getattr(imu, "imu_sample_frequency", 1 / 30)

    # A transient bus error (e.g. the BCM2711 clock-stretching bug NACKing
    # a transfer) must not kill the IMU process: skip the sample and retry.
    # Only a persistent failure warrants re-creating Imu() — construction
    # re-opens the bus and restores IMUPLUS mode, which matters because a
    # power-glitched BNO055 wakes up in CONFIG mode.
    reinit_after_errors = 60  # consecutive errors (~2 s at 30 Hz)
    consecutive_errors = 0

    while True:
        loop_start = time.monotonic()
        try:
            imu.update()
            consecutive_errors = 0
        except (OSError, RuntimeError) as e:
            consecutive_errors += 1
            if consecutive_errors == 1:
                logger.warning("IMU: bus error, retrying: %s", e)
            if consecutive_errors >= reinit_after_errors:
                logger.error("IMU: persistent bus errors, re-initialising sensor")
                console_queue.put("IMU: bus errors, re-initialising")
                try:
                    imu = Imu()
                except (OSError, RuntimeError) as reinit_error:
                    logger.error("IMU: re-init failed: %s", reinit_error)
                consecutive_errors = 0
            time.sleep(sample_period)
            continue
        imu_sample.status = imu.calibration

        # Raw data + read epoch are captured by imu.update() in the same
        # I2C burst as the quaternion; copy them onto the published sample.
        # The fresh timestamp per read keeps the telemetry recorder's
        # dedup-by-sample-epoch working while stationary.
        imu_sample.gyro = imu.gyro
        imu_sample.accel = imu.accel
        if imu.last_read_time:
            imu_sample.timestamp = imu.last_read_time

        if imu.moving():
            if not imu_sample.moving:
                logger.debug("IMU: move start")
                imu_sample.moving = True
            # Scalar-first (w, x, y, z)
            imu_sample.quat = quaternion.from_float_array(imu.avg_quat)
        else:
            if imu_sample.moving:
                # If we were moving and we now stopped
                logger.debug("IMU: move end")
                imu_sample.moving = False
                imu_sample.quat = quaternion.from_float_array(imu.avg_quat)

        if not imu_calibrated:
            if imu_sample.status == 3:
                imu_calibrated = True
                console_queue.put("IMU: NDOF Calibrated!")

        if shared_state is not None and imu_calibrated:
            shared_state.set_imu(imu_sample)

        # Pace the loop to the IMU sample rate: sleep only the remainder of the
        # sample period (period minus the work already done this iteration), so
        # the publish cadence tracks the sample rate instead of drifting to
        # period + work. The guard keeps the fake-IMU fallback (whose update()
        # already sleeps 0.1s) from sleeping a second time.
        sleep_remaining = sample_period - (time.monotonic() - loop_start)
        if sleep_remaining > 0:
            time.sleep(sleep_remaining)


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    logger.info("Trying to read state from IMU")
    imu = None
    try:
        imu = Imu()
        for i in range(10):
            imu.update()
            print(imu)
            time.sleep(0.5)
    except Exception as e:
        logger.exception("Error starting phyiscal IMU", e)
