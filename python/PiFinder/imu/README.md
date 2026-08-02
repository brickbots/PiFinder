# Camera-IMU alignment (extrinsic calibration)

To track the pointing using IMU dead-reckoning, we need to know the relative
orientation or alignment between the camera and IMU. The development code here
estimates the alignment.

The alignment error will introduce a "jump" when the IMU dead-reckoning hands
off to the camera solve which is (probably) approximately proportional to the
product of the camera-IMU alignment error and the angle moved under
dead-reckoning (in radians).

See the header comments in `imu_extrinsic_calibration.py` for explanation of
the algorithm.

## Previous studies

In a previous study, we used recorded telemetry data to estimate the camera-IMU
alignment. The extrinsic calibration estimated an adjustment over the nominal
orientation by 1.6 degrees with an uncertainty of ±0.5 degrees. This was based
on around 1 minute of data which gave 9 samples (after outlier removal). 

With 4 minutes of data, we might be able to get it down to something around
±0.1 degrees but this might be unrealistic because it needs continual movement
and (based on simulations) the main source of error doesn't look like
nicely-behaved random noise but something else. The difference between the
moment of camera exposure and the IMU measurement could be just one issue. 

When compared to using the improved alignment with the nominal alignment, the
improvement isn't that big. It cuts the angular jump by around a half, which is
what we'd expect given the uncertainty. 

Simulations with realistic noise gave much better results. This suggests that
the accuracy of the real results may be limited by one or more of the following
following potential root causes:

1. The alignment algorithm needs to be fed with pairs of start/end samples
with paired camera solves and IMU measurements. Outliers could introduce errors
so better selection criteria may be needed to filter out outliers.
2. The telemetry recording used the BNO055 IMU in fusion mode. This is known to 
be noisy so better filtering and outlier rejections may be needed.
3. The BNO055 is an older IMU and it may be that its poorer accuracy propagates
to alignment inaccuracies. It is possible that a more modern IMU could give better
alignment results. 
4. The camera and IMU samples are assumed to be from the same time instance.
Relative delays could introduce errors. Filtering of the IMU could also
introduce delays.

## What still needs to be done

The study showed that the camera-IMU alsignment could be estimated to ±0.5
degrees. This is good enough to replace the nominal alignments that need to be
set in configurations.

A rough alignment feature could be built based on the algorithm in this 
directory and the sample code below.

To improve the alignment accuracy to reduce the "jumps", the potential root
causes listed above may need to be investigated.

## Sample code from the Jupyter notebooks

The following is a sample code from the Jupyter notebooks that was used to
analyse the data from telemetry. It could form the basis of an implementation
in PiFinder.


```python
from dataclasses import dataclass
from enum import Enum
import quaternion
import numpy as np
from pathlib import Path
import json

from astro_coords import RaDecRoll
import quaternion_transforms as qt


@dataclass
class ImuData:
    quat: quaternion.quaternion | None = None
    gyro: list  | None = None
    accel: list | None = None
    

@dataclass
class SolveData:
    camera_ra_dec_roll: RaDecRoll | None = None
    timestamp_exposure_end: float | None = None  # seconds, from time.time()
    imu_quat: quaternion.quaternion | None = None  # Quaternion at exposure end


class MeasurementType(Enum):
    CAMERA = 1
    IMU = 2


@dataclass
class Sample:
    timestamp: float | None = None  # seconds, from time.time()
    measurement_type: MeasurementType | None = None
    data: SolveData | ImuData | None = None
 
    def set(self, timestamp: float, measurement_type: MeasurementType, data):
        self.timestamp = timestamp
        self.measurement_type = measurement_type
        self.data = data

    def get(self):
        return self.timestamp, self.measurement_type, self.data


def read_samples_from_telemetry(path: Path, n_max_samples: int | None = None) -> list[Sample]:
    """
    Reads samples from a telemetry file and returns a list of Sample objects.
    Each line in the telemetry file is expected to be a JSON object with the following format:
    {
        "t": timestamp (float, seconds from time.time()),
        "e": event type (string, either "imu" or "solve"),
        "q": [w, x, y, z] (quaternion for IMU measurements),
        "ra": right ascension (float, degrees),
        "dec": declination (float, degrees),
        "roll": roll angle (float, degrees)
    }
    """
    samples = []
    counter = 0
    with open(path, 'r') as f:
        for line in f:
            d = json.loads(line)
            #print(d)  # For debugging (print the raw data from the telemetry file)
            if d["e"] == "imu":
                q = quaternion.quaternion(*d["q"])
                imu_data = ImuData(quat=q, gyro=d["gyro"], accel=d['accel'])
                samples.append(Sample(timestamp=d["t"], measurement_type=MeasurementType.IMU, data=imu_data))
            elif d["e"] == "solve":
                ra_dec_roll = RaDecRoll(ra=d["cam_ra"], dec=d["cam_dec"], roll=d["cam_roll"], deg=True)
                solve_data = SolveData(camera_ra_dec_roll=ra_dec_roll, 
                                       timestamp_exposure_end=d["lss"], imu_quat=quaternion.quaternion(*d["iq"]))
                samples.append(Sample(timestamp=d["t"], measurement_type=MeasurementType.CAMERA, data=solve_data))
            else:
                continue  # Skip unknown measurement types
            
            counter += 1
            #print(samples[-1])  # For debugging (print the stored sample)
            if n_max_samples is not None:
                if counter >= n_max_samples:
                    break

    return samples

def get_ang_diffs(last_camera_sample: Sample, camera_sample: Sample):
    ang_diff_cam = qt.get_quat_angular_diff(
        last_camera_sample.data.camera_ra_dec_roll.as_quaternion(), 
        camera_sample.data.camera_ra_dec_roll.as_quaternion())
    ang_diff_imu = qt.get_quat_angular_diff(
         last_camera_sample.data.imu_quat, 
         camera_sample.data.imu_quat)                

    return ang_diff_cam, ang_diff_imu

def pair_camera_imu_samples(samples: list[Sample],
                            max_time_diff=0.1,  # [s] Maximum time difference between IMU and platesolve
                            min_angle_diff=np.deg2rad(5),  # Reject if angle from prev. sample is less than this
                            verbose=False
                            ):
    """
    Pair up solved data (RaDecRoll) with the previous IMU sample. The time
    difference between the IMU and camera must be small and the angular
    movement between sequential pairs must be large enough.
    """
    paired_samples = []  # The result that will be returned
    quarantined_samples = []  # Samples that were too close in angle but could be used later
    prev_imu_idx = None
    for idx, samp in enumerate(samples):
        if samp.measurement_type is MeasurementType.IMU:
            prev_imu_idx = idx
            continue
        elif samp.measurement_type is MeasurementType.CAMERA and prev_imu_idx is not None:
            if not samp.data.camera_ra_dec_roll.valid:
                continue  # Skip if camera sample is not valid
            
            # Skip if IMU sample is after the camera sample or large time difference:
            #imu_sample = samples[prev_imu_idx]
            #time_diff = samp.timestamp - imu_sample.timestamp
            #print(f"{(time_diff)*1000:.1f} ms between IMU and camera sample")
            #if (time_diff < 0) or (time_diff > max_time_diff):
            #    continue
            
            if not paired_samples:
                paired_samples.append(samp)
                continue

            # See if we can use the oldest quarantined sample
            # TODO: Also add the time difference criterion to reject old samples
            if quarantined_samples:
                last_camera_sample = paired_samples[-1]
                q_samp = quarantined_samples[0]
                ang_diff_cam, ang_diff_imu = get_ang_diffs(last_camera_sample, q_samp)
                if abs(ang_diff_imu) >= min_angle_diff and abs(ang_diff_cam) >= min_angle_diff:
                    # Use the quarantined sample
                    paired_samples.append(q_samp)
                    quarantined_samples = quarantined_samples[1:]
 
            # Save pairs of data if the angular difference since the previous sample is large enough
            # Note: We could re-use these by another pairing
            if paired_samples:
                # Skip if angular diff too small (won't be able to solve)
                last_camera_sample = paired_samples[-1]                
                ang_diff_cam, ang_diff_imu = get_ang_diffs(last_camera_sample, samp)
                #print(f"Angular difference since last sample: {np.rad2deg(ang_diff):.1f} deg")
                if abs(ang_diff_imu) < min_angle_diff and abs(ang_diff_cam) < min_angle_diff or ang_diff_imu < min_angle_diff or ang_diff_cam < min_angle_diff:
                    quarantined_samples.append(samp)
                    continue
                else:
                    paired_samples.append(samp)

            assert "Shouldn't get here"

    return paired_samples
```