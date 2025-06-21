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
pip install -r requirements_imu.txt
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

# Approach: Improved IMU support for quaternions for Altaz

During normal operation, we want to find the pointing of the scope, expressed using $q_{hor2scope}$, which is the quaternion that rotates the scope axis in the horizontal frame from the *home* pointing to the current pointing.

$$q_{hor2scope} = q_{hor2imu} \; q_{drift} \; q_{imu2scope}$$

The IMU outputs its orientation $q_{hor2imu}$ but this drifts over time by $q_{drift}$. $q_{imu2scope}$ rotates the IMU frame to the scope frame and is assumed to be fixed and determined during alignment of the PiFinder:

$$q_{imu2scope} =  q_{hor2imu}^{-1} \; q_{hor2scope}$$

During alignment, plate solving gives the pointing of the scope which can be used to estimate $q_{hor2scope}$ assuming a perfect altaz mount. For unit quaternions, we can also use the conjugate $q^*$ instead of $q^{-1}$, which is slightly faster to compute.

When plate solved scope pointings are available during normal operation, we can estimate the drift, $q_{drift}$;

$$q_{drift} = q_{hor2imu}^{-1} \; q_{hor2scope} \; q_{imu2scope}^{-1}$$

where $q_{hor2scope}$ can be estimated from plate solving (again, assuming a perfect altaz mount) and the IMU gives $q_{hor2imu}$.

## Equatorial mounts

It's possible that this can also work with equatorial mounts. Clearly, it won't be correct to use $q_{hor2scope}$ for the scope pointing because this is for altaz mounts and EQ mounts also rate the scope around its axis. It's possible that $q_{drift}$ will compensate for this but it won't be the most efficient way.