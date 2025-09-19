README: IMU support prototyping
===============================

> This README is temporary during the prototyping phase of the IMU support.

# TODO

>Remove this before release!

Issues:
* Doesn't run wih v3 Flat. Issue in main branch?
* Issue in requirements? Can't get it to work in a new env.
* Doesn't pass Nox
* In EQ mode flickers between 0° and 359°. This is also in the main branch.

TODO:
* Use RaDecRoll class --> Done. Need to test.
* Use alignment rather than calculating every loop
* Go through TODOs in code
* Discuss requirements.txt with Richard

Later:
* Update imu_pi.py

Done:
* Support other PiFinder types
* Adjust Roll depending on mount_type for charts
* Lint
* Type hints for integrator.py


# Sky test log

>Remove this before release!

## 20250819: 700f77c (tested 19/20 Aug)

* Tested on altaz mount in altaz & eq mode
* OK:
  * Changed chart display so that altaz is in horizontal frame and EQ mode displays in equatorial
  coordinates. This appears to work.
  * Tracking on chart and SkySafari OK.
* Issues:
  * Catalog crashes in altaz mode (ok in EQ mode). Probably because we don't calculate altaz in integrator.py? Same behaviour under test mode so we could do desktop tests.


## 20250817: 5cf8aae

* Tested on altaz and eq mounts
* **altaz:** Tracked fine. When the PiFinder was non-upright, I got the
  feeling it tended to jump after an IMU track and got a plate-solve. This
  wasn't seen when the PiFinder was upright. When non-upright, the crosshair
  moved diagonally when the scope was moved in az or alt. The rotated
  constellations in the chart were hard to make out.
* **EQ:** Seemed to work fine but I'm not experienced with EQ. The display on
  SkySafari showed RA movement along the horizontal direction and Dec along
  the vertical. This seemed to make sense.

# Installation & set up

## Install additional packages

This branch needs the `numpy.quaternion` package. For desktop-testing, you
could install it in a virtual environment. For field-testing, it's more
practical to install it as default.

### Create a virtual environment

Skip this section if you want to install the packages as default.

This step creates a virtual environment using `venv`. Connect to the PiFinder using `ssh` and install venv to create a virtual environment:

```bash
sudo apt-get install python3-venv
```

Still on the PiFinder, create a virtual environment called `.venv_imu`. Note 
that the virtual environment is created in the home directory because `venv` 
creates the environment folder `.venv_imu\` where you run this command.

```bash
cd ~
python3 -m venv .venv_imu
```

Type this to activate the environment:

```bash
source .venv_imu/bin/activate
```

Follow the next step to install the packages in the virtual environmnet.

At the end, it can be de-activated by typing:

```bash
deactivate
```

### Install the packages

Update `pip`:

```bash
pip install --upgrade pip
```

Ensure that you're in new virtual environment and install the Python packages using `pip`. 

```bash
cd PiFinder/python
pip install -r requirements.txt
pip install -r requirements_dev.txt
```

The last line installs the additional packages required (just `numpy-quaternion`). PiFinder can be
run from the command line as usual:

```bash
python3 -m PiFinder.main
```

For testing, running the following command will dump the raw IMU measurements to the terminal:

```bash
python PiFinder/imu_print_measurements.py
```

# Theory

## Quaternion rotation

A quaternion is defined by

$$\mathbf{q} = \cos(\theta/2) + (u_x \mathbf{i} + u_y \mathbf{j} + u_z
\mathbf{k}) \sin(\theta / 2)$$

This can be interpreted as a rotation around the axis $\mathbf{u}$ by an angle
$\theta$ in the clockwise direction when looking along $\mathbf{u}$ from the
origin. Alternatively, using the right-hand corkscrew rule, the right thumb
points along the axis and fingers in the direction of positive rotation.

We can express a quaternion as

$$\mathbf{q} = (w, x, y, z)$$

where $w$ is the scalar part and $(x, y, z)$ is the vector part. We will use
the *scalar-first* convention used by Numpy Quaternion.

A vector can be rotated by the quaternion $\mathbf{q}$ by defining the vector
as a pure quaternion $\mathbf{p}$ (where the scalar part is zero) as follows:

$\mathbf{p^\prime} = \mathbf{qpq}^{-1}$


### Numpy quaternion

In Numpy Quaternion, we can create a quaternion using

```python
q = np.quaternion(w, x, y, z)
```

Quaternion multiplications are simply `q1 * q2`.

The inverse (or conjugate) is given by `q.conj()`.


### Intrinsic and extrinsic rotation

Intrinsic rotation of $q_0$ followed by $q_1$

$$q_{new} = q_0 q_1$$

For an extrinsic rotation of $q_0$ followed by $q_1$, left multiply

$$q_{new} =  q_1 q_0$$


## Coordinate frames

### Home positions

For an altaz mount, we define the *home position* as az=0°, alt=0°. i.e. the
scope points due North and is horizontal. The $z_{mnt}$ axis of the mount frame
corresponds to the axis of the scope in the *home* position in the ideal case.

### Coordinate frame definitions

We define the following reference frames:


#### Equatorial coordinate system
* Centered around the center of the Earth with the $xy$ plane running through
  the Earths' equator. $+z$ points to the north pole and $+x$ to the Vernal
  equinox.

#### Horizontal coordinate system
* Centred around the observer. We will use the convention:
* $x$ points South, $y$ to East and $z$ to the zenith.

#### Mount frame (altaz)
* $y$ is defined as the axis of the azimuthal gimbal rotation. $z$ is the cross
  product between the altitude and azimuthal gimbal axes and $x = y \times z$.
* For a perfect mount where $y$ points to the zenith and the gimbal axes are
  orthogonal, $x$ is the altitude gimbal axis when in the *home position*.
* A perfect system in the *home position*, $x$ points West and $z$ points due
  North and horizontal.
* Non-orthogonality between the axes are allowed by for now, we will assume the
  orthogonal case for simplicity.

#### Gimbal frame
* The mount frame rotated around the mount's azimuthal gimbal axes by
  $\theta_{az}$ followed by a rotation around the mount's altitude axis by
  $\theta_{alt}$.

#### Scope frame
* +z is boresight. 
* On an altaz mount, we define +y as the vertical direction of the scope and +x as the
  horizontal direction to the left when looking along the boresight.
* In the ideal case, the Scope frame is assumed to be the same as the Gimbal
  frame. In reality, there may be errors due to mounting or gravity.

#### Camera frame
* The camera frame describes the pointing of the PiFinder's camera. There will
  be an offset between the camera and the scope.
* $+z$ is the boresight of the camera, $+y$ and $+x$ are respectively the
  vertical and horizontal (to the left) directions of the camera.

#### IMU frame
* The IMU frame is the local coordinates that the IMU outputs the data in.
* The diagram below illustrates the IMU coordinate frame for the v2 PiFinder with the Adafruit BNO055 IMU. 

### IMU and camera coordinate frames

To use the IMU for dead-reckoning, we need to know the transformation between
the IMU's own coordinate frame and the PiFinder's camera coordinate frame
(which we use as the PiFinder's reference coordinate frame).

The picture below illustrate the IMU and camera coordinates for the v2 flat
version of the PiFinder. For each type, we need to work out the quaternion
rotation `q_imu2cam` that rotates the IMU frame to the camera frame.

![Image](docs/PiFinder_Flat_bare_PCB_camera_coords.jpg)

The transformations will be approximate and there will be small errors in 
`q_imu2cam` due to mechanical tolerances. These errors will contribute to the 
tracking error between the plate solved coordinates and the IMU dead-reckoning.

### Roll

The roll (as given by Tetra3) is defined as the rotation of the north pole
relative to the camera image's "up" direction ($+y$). A positive roll angle
means that the pole is counter-clockwise from image "up" (i.e. towards West).
The roll offset is defined as

```
roll_offset = camera_roll - expected_camera_roll
```

The `expected_camera_roll` is the roll at the camera center given its
plate-solved RA and Dec for a camera on a perfect horizontal mount (i.e. the
"up" $+y$ direction of the camera always points to the zenith). The camera pose
is rotated by the angle `roll_offset` around its boresight.

### Telescope coordinate transformations

We can use quaternions to rotate between the coordinate frames.
For example, the quaternion `q_horiz2mnt` rotates the Horizontal frame to the
Mount frame. The quaternions can be multiplied to apply successive *intrinsic*
rotation from the Horizontal frame to the Camera frame;

```python
q_horiz2camera = q_horiz2mnt * q_mnt2gimb * q_gimb2scope * q_scope2camera
```

Note that this convention makes it clear when applying intrinsic rotations (right-multiply).

The Mount and Gimbal frames are not used in the current implementation but this
framework could be used to extend the implementation to control the mount. For
example, `q_mnt2gimb` depends on the gimbal angles, which is what we can
control to move the scope. 

## Coordinate frame transformation

We will use the equatorial frame as the reference frame. The goal is determine the scope pointing in RA and Dec. The pointing of the scope relative to the equatorial frame can be described by quaternion $q_{eq2scope}$.

The PiFinder uses the coordinates from plate-solving but this is at a low rate and plate-solving may not succeed when the scope is moving so the IMU measurements can be used to infer the pointing between plate-solving by dead-reckoning.

### Plate solving 

Plate-solving returns the pointing of the PiFinder camera in (RA, Dec, Roll) coordinates. The quaternion rotation of the camera pointing relative to the equatorial frame for time step $k$ is given by $q_{eq2cam}(k)$ and the scope pointing is give by,

$$q_{hor2scope}(k) = q_{hor2cam}(k) \; q_{cam2scope}$$

We use the PiFinder's camera frame as the reference because plate solving is done relative to the
camera frame. $q_{cam2scope}$ is the quaternion that represents the alignment offset between the
PiFinder camera frame and the scope frame

### Alignment

The alignment offset between the PiFinder camera frame and the
scope frame is determined during alignment of the PiFinder with the scope and is assumed to be fixed. The goal of alignment is to determine the quaternion $q_{cam2scope}$.

During alignment, the user user selects the target seen in the center the scope, which gives the (RA, Dec) of the scope pointing but not the roll. We can assume some arbitrary roll value (say roll = 0) and get $q_{eq2scope}$. At the same time, plate solving measures the (RA, Dec, Roll) at the camera center or $q_{eq2cam}$. We can express the relation by,

$$q_{eq2scope} = q_{eq2cam} \; q_{cam2scope}$$

Rearranging this gives,

$$q_{cam2scope} = q_{hor2cam}^{-1} \; q_{hor2scope}$$

Note that for unit quaternions, we can also use the conjugate $q^*$ instead of
$q^{-1}$, because the conjugate is slightly faster to compute.

Roll returned by plate-solving is not relevant for pointing and it can be arbitrary but it is needed for full three degrees-of-freedom dead-reckoning by the IMU.

### Dead-reckoning

Between plate solving, the IMU extrapolates the scope orientation by dead reckoning. Suppose that we
want to use the IMU measurement at time step $k$ to estimate the scope pointing;

```python
q_eq2scope(k) = q_eq2cam(k-m) * q_cam2imu * q_x2imu(k-m).conj() * q_x2imu(k) * q_imu2cam * q_cam2scope
```

Where
1. `k` represents the current time step and `k-m` represents the time step
   where we had a last solve. 
2. `q_x2imu(k)` is the current IMU measurement quaternion w.r.t its own
   drifting reference frame `x`.
3. Note that the quaternion `q_x2imu(k-m).conj() * q_x2imu(k)` rotates the IMU
   body from the orientation in the last solve (at time step `k-m`) to to the
   current orientation (at time step `k`).
4. `q_cam2imu = q_imu2cam.conj()` is the alignment of the IMU to the camera and depends on the
PiFinder configuration. There will be some error due to mechanical tolerances which will propagate
to the pointing error when using the IMU.

We can pre-compute the first three terms after plate solving at time step
`k-m`, which corresponds to the quaternion rotation from the `eq` frame to the
IMU's reference frame `x`.

```python
q_eq2x(k-m) = q_eq2cam(k-m) * q_cam2imu * q_x2imu(k-m).conj()
```

## Potential future improvements

A potential next step could be to use a Kalman filter framework to estimate the pointing. Some of
the benefits are:

* Smoother, filtered pointing estimate. 
* Improves the accuracy of the pointing estimate. Accuracy may be more beneficial when using the
  PiFinder estimate to control driven mounts. 
* Potentially enable any generic IMU (with gyro and accelerometer) to be used
  without internal fusion FW, which tends to add to the BOM cost.
* If required, could take fewer plate-solving frames by only triggering a plate solve when the
uncertainty of the Kalman filter estimate based on IMU dead-reckoning exceeds some limit. This can
reduce power consumption and allow for a cheaper, less powerful computing platform to be used.

The accuracy improvement will likely come from the following sources:

* Filtering benefits from the averaging effects of using multiple measurements. 
* The Kalman filter will estimate the accelerometer and gyro bias online. The
calibration will be done in conjunction with the plate-solved measurements so
it will be better than an IMU-only calibration.
* The orientation of the IMU to the camera frame, $q_{imu2cam}$, has errors
because of mechanical tolerances. The Kalman filter will calibrate for this online.
This will improve the accuracy and enable other non-standard form-factors.
