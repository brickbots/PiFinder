README: IMU support prototyping
===============================

> This README is temporary during the prototyping phase of the IMU support.

# Installation & set up

## Set up a virtual environment to test the PiFinder

We need to install additional Python packages for the changes by creating a conda environment.

## Create a virtual environment

The first step is to create a virtual environment using `venv`. Connect to the PiFinder using `ssh` and install venv to create a virtual environment:

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

#### Scope frame (altaz)
* +z is boresight, +y is the vertical direction of the scope and +x is the
  horizontal direction to the left when looking along the boresight.
* In the ideal case, the Scope frame is assumed to be the same as the Gimbal
  frame. In reality, there may be errors due to mounting or gravity.

#### Camera frame
* The camera frame describes the pointing of the PiFinder's camera. There will
  be an offset between the camera and the scope.
* $+z$ is the boresight of the camera, $+y$ and $+x$ are respectively the
  vertical and horizontal (to the left) directions of the camera.

## Roll

The roll (as given by Tetra3) is defined as the rotation of the north pole
relative to the camera image's "up" direction ($+y$). A positive roll angle
means that the pole is counter-clockwise from image "up". The roll offset is
defined as

```
roll_offset = camera_roll - expected_camera_roll
```

The `expected_camera_roll` is the roll at the camera center given its
plate-solved RA and Dec for a camera on a perfect horizontal mount (i.e. the
"up" $+y$ direction of the camera always points to the zenith). The camera pose
is rotated by the angle `roll_offset` around its boresight.

## Telescope coordinate transformations

**TO EDIT...**

We will use quaternions to rotate between the coordinate frames. For example,
the quaternion `q_horiz2mnt` rotates the Horizontal frame to the Mount frame.
The quaternions can be multiplied to apply successive intrinsic rotation from
the Horizontal frame to the Camera;

```python
q_horiz2camera = q_horiz2mnt * q_mnt2gimb * q_gimb2scope * q_scope2camera
```

`q_mnt2gimb` depends on the gimbal angles, which is what we can control to move
the scope. 

## Coordinate frame transformation for altaz mounts

During normal operation, we want to find the pointing of the scope, expressed
using $q_{hor2scope}$, which is the quaternion that rotates the scope axis in
the horizontal frame from the *home* position to the current pointing.

### Plate solving 

Plate solving returns the pointing of the PiFinder camera in RA/Dec/Roll
coordinates which can be converted to the quaternion rotation $q_{hor2cam}$. 

Plate solving also returns the roll but this is probably less accurate. For
this reason, we will will initially assume a perfect altaz mount with the
PiFinder mounted upright.

The alignment offset $q_{cam2scope}$ between the PiFinder camera frame and the
scope frame is determined during alignment of the PiFinder with the scope.
Assuming that this offset is constant, we can infer the pointing of the scope
at time step $k$:

$$q_{hor2scope}(k) = q_{hor2cam}(k) \; q_{cam2scope}$$

We will use the PiFinder's camera frame as the reference because plate solving
is done relative to the camera frame.

The quaternion $q_{hor2cam}$ represents the orientation of the PiFinder camera
relative to the Horizontal frame. Using the axis-angle interpretation, the axis
points along the altaz of the camera center and rotated by the roll offset
(explained above).

### Alignment

As already mentioned, the alignment of the PiFinder determines $q_{cam2scope}$
and we assume that this is fixed.

During alignment, plate solving gives the RA/Dec of the the camera frame
pointing which can be used to estimate $q_{hor2cam}$ assuming a perfect altaz
mount. The roll measurement by the camera could be used to determine the
rotation of the camera frame around its $z_{cam}$ axis if the roll measurement
is accurate enough. Otherwise the roll will need to be inferred assuming that
the PiFinder is mounted upright.

At the same time, the user selects the target seen by the scope, which gives
the RA/Dec of the scope pointing. We can use this to get a fix on
$q_{hor2scope}$ (assuming a perfect altaz mount);

$$q_{hor2scope}(k) = q_{hor2cam}(k) \; q_{cam2scope}$$

Rearranging this gives,

$$q_{cam2scope} = q_{hor2cam}^{-1}(k) \; q_{hor2scope}(k)$$

Note that for unit quaternions, we can also use the conjugate $q^*$ instead of
$q^{-1}$, because the conjugate is slightly faster to compute.

Some scopes and focusers can be rotated around its axis which also rotates the
PiFinder with it. This would currently require a re-alignment.

### Dead-reckoning

Between plate solving, the IMU extrapolates the scope orientation by dead
reckoning. Suppose that at the $k$ th time step, plate solves finds the camera
pointing, $q_{hor2cam}(k)$. It can be related to the IMU measurement
$q_{x2imu}(k)$ by,

$$q_{hor2cam}(k) = q_{hor2x}(k) \; q_{x2imu}(k) \; q_{imu2cam}$$

The IMU outputs its orientation $q_{x2imu}$ relative to a frame $X$ which is
similar to the horizontal frame but drifts over time; in particular, it will
predominantly drift by rotating around the $z_{hor}$ axis because the IMU with
just accelerometer/gyro fusion has no means to determine the bearing.
$q_{imu2cam}$ rotates the IMU frame to the scope frame. It depends on the
PiFinder type and is assumed to be fixed. Because of small errors in the
alignmet of the IMU relative to the camera, there will be errors that will not
be captured by the preset $q_{imu2cam}$. This will introduce errors in the
dead-reckoning.

The drift $q_{hor2x}$ is unknown but it drifts slowly enough that we can assume
that it will be constant between successive plate solves.

$$q_{hor2x}(k) = q_{hor2cam}(k) \; q_{imu2cam}^{-1} \; q_{x2imu}^{-1}(k)$$

In subsequent time steps, the drift, $q_{hor2x}(k)$, estimated in the last
plate solve can be used. At time step $k+l$ without plate solving, the the
camera pointing can be esimated by:

$$\hat{q}_{hor2cam}(k+l) = q_{hor2x}(k) \; q_{x2imu}(k+l) \; q_{imu2cam}$$

Where $\hat{q}_{hor2cam}$ represents an estimate of the camera pointing using
dead-reckoning from the IMU. From this, we can make a dead-reckoning estimate
of the scope pointing;

$$q_{hor2scope}(k + l) = \hat{q}_{hor2cam}(k + l) \; q_{cam2scope}$$


## Next steps in the development

The current implementation reproduces the existing functionality of the
PiFinder. The phase are:

1. Reproduce PiFinder functionality using quaternion transformaitons for altaz
   mounts. [Done]
2. Enable PiFinder to be mounted at any angle, not just upright.
3. Extend to equatorial mount.
4. Enable scopes to be rotated (i.e. rotate the PiFinder around the axis of the
   scope).

### Approach to support general PiFinder mounting angle 

Currently, we do not use the roll measurement in the alignment of the PiFinder
with the scope; $q_{cam2scope}$ only rotates in the alt/az directions. By using
the roll measurement, we will also account for rotation of the PiFinder around
the scope axis. This should (probably) enable the PiFinder to be mounted at any
angle rotated around the scope axis.


### Approach for equatorial mounts

It should be possible to take a similar approach for an equatorial mounts.  

One issue is that it's common to rotate EQ-mounteed scopes (particularly
Newtoninans) around its axis so that the eyepiece is at a comfortable position.
As mentioned in the alignment section, this would require a re-alignment. That
would need to be resolved in a future step.

#### Future improvements

The next step would be to use a Kalman filter framework to estimate the
pointing. Some of the benefits are:

* Smoother, filtered pointing estimate. 
* Improve the accuracy of the pointing estimate (possibly more beneficial when
  using the PiFinder estimate to control driven mounts). 
* Potentially enable any generic IMU (with gyro and accelerometer) to be used
  without internal fusion FW, which tends to add to the BOM cost.
* If required, could take fewer plate-solving frames by only triggering a plate
solve when the uncertainty of the Kalman filter estimate based on IMU
dead-reckoning exceeds some limit.

The accuracy improvement will come from the following sources:

* Filtering benefits from the averaging effects of using multiple measurements. 
* The Kalman filter will estimate the accelerometer and gyro bias online. The
calibration will be done in conjunction with the plate-solved measurements so
it will be better than an IMU-only calibration.
* The orientation of the IMU to the camera frame, $q_{imu2cam}$, has errors
because of alignment errors. The Kalman filter will calibrate for this online.
This will improve the accuracy and enable other non-standard form-factors.
