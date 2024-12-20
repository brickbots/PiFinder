
Architecture
================

The key words "MUST", "MUST NOT", "REQUIRED", "SHALL", "SHALL NOT", "SHOULD", "SHOULD NOT", "RECOMMENDED",  
"MAY", and "OPTIONAL" in this page are to be interpreted as described in `RFC 2119 <https://datatracker.ietf.org/doc/html/rfc2119>`_.

Solution Platform Constraints
--------------------------------

To facilitate do-it-yourself building, the solution platform is the **Raspberry Pi with a 
self-developed HAT**, which contains an OLED display and a custom keyboard. Integrated into
the HAT is an IMU and a GPS chip with antenna. Only components compatible with
this solution platform will be used. That means that **only cameras compatible with the 
Raspberry Pi CSI camera connector are supported**.

Choice of Language: Python
----------------------------

The **main language of the PiFinder software is Python**. Python is a well known language
with a lot of support for managing astronomical data. There's good support for 
image manipulation, statistics, APIs and implementing web servers. 

The second most used language are shell scripts managing especially the setup of the
Raspberry Pi and upgrades.

Architecture 
---------------

Architecture determining Requirements
..........................................

As PiFinder is an interactive application with user input, 
there are some time-critical requirements: 

1. The camera picture SHALL be displayed as fast as possible on Raspberry Pi, 
   if it is displayed, so that movements of the telescope are reflected in the 
   display "instantanously" for the users. This implies a limit of 0.1s, see 
   [NIELSEN_LIMITS]_ [1]_.
2. The position derived on the celestial sky from the camera picture SHALL likewise 
   be displayed "instantanously". This means a very fast blind plate-solver MUST be used.
3. While the telescope is moved, the camera is not able to supply pictures that could
   be solved by the plate-solver (motion blur). In order to be able to provide 
   feedback on the movement to the users, PiFinder uses an IMU [2]_. Information derived
   from this subsystem MUST also be displayed to the user in an instantaneous fashion.
4. PiFinder offers a webserver interface, that users can connect to, 
   to remotely control PiFinder and to display and set certain configuration 
   information, that would be cumbersome to change using the keyboard. 
   This means that in parallel http requests MUST be parsed and serviced.
5. `SkySafari <https://skysafariastronomy.com/>`_ can connect to PiFinder and 
   be used as planetarium software to a) see there PiFinder is pointing and 
   b) to push targets to PiFinder. This means that PiFinder MUST support the 
   LX200 protocol as supported by SkySafari. 

.. [1] Realistically, < 0.5 - 1 s.
.. [2] inertial measurement unit, that uses accelerometers, gyroscopes and a magnetometer
       to record the movements it has undergone and estimates the position the 
       PiFinder is in.

PiFinder is a collaboration of processes
..............................................

This implies, that a lot of information needs to be collected in parallel, and MUST be 
processed and integrated to be displayed to the users. Given the choice of Python 
as the main programming language means that the choice of concurrency primitives is
important: 

As Python has a Global Interpreter Lock [GIL], **PiFinder uses separate processes
for the different tasks** mentioned above. This means that for communication between the 
processes either queues or shared memory are employed. Wherever possible, **we prefer to 
use queues** as a means to communicate between processes, as it provides a decoupling 
of creation and consumption of data, so that the receiving end can process the data 
at a convenient point in time.

Therefore PiFinder consists of the following processes with their main responsibilities:

- **main**: processing keystrokes and UI in file ``main.py``. This also sets 
  up all other processes. 
- **camera**: setup the image acquisition pipeline and acquire 
  images regularly, distributing this to the other modules in ``camera_pi.py``
- **gps**: read out gps position using a serial interface in ``gps_pi.py``
- **imu**: read out 3D position information from IMU in ``imu_pi.py``
- **keyboard**: read out keystrokes and send it to the keyboard queue in ``keyboard_pi.py``
- **pos_server**: the server that SkySafari connects to, in ``pos_server.py``.
- **server**: the web interface server process, in - you guessed it - ``server.py``.

Shared Image Handling
.....................

The exception to the rule of using queues for interprocess communication is the 
image that is recorded by the camera. This uses a **shared memory image, 
that is constantly updated by the image acquision thread**. Whenever working on 
this image, make sure that you create your own local copy of it, so it does not get 
changed while you process it. 

Logging
--------- 

This choice of architecture means that logging to disk is a little bit more complex, as we
need to avoid writing to the same log file from multiple processes, to avoid overwriting
each other's logs. We have therefore implemented a **log thread and queues delivering log 
messages from other processes**. This means that in a log file, the order of log messages 
can be out of order. 

To set this up, in each process you need to invoke logging like this:

.. code-block::

    from PiFinder.multiproclogging import MultiprocLogging
    
    # You can create loggers with-out setting up forwarding
    logger = logging.getLogger(„Solver“)
    
    ...
    
    # In the main loop of the process ... 
    def process( ..., log_queue, ...)
        MultiprocLogging.configurer(log_queue) # ... Enable log forwarding
        
        # only then create log messages
        logger.debug(„Starting Solver“)


Choice of Plate-Solver
------------------------ 

PiFinder uses `cedar-detect-server <https://github.com/smroid/cedar-detect>`_ 
in binary form to determine star centroids in an image. This is a fast centroider written
in the Rust programming language that is running in a separate process. A gRPC API is used
to interface with this process. 

The detected centroids are then passed to the 
`tetra3 solver <https://github.com/esa/tetra3>`_ for plate-solving. 
If the platform that PiFinder is running on is not supported by cedar, [3]_ PiFinder 
falls back to using the centroider of tetra3.

.. [3] This can only happen when PiFinder's software is not running on a Raspberry Pi.

Testing
----------

Unit Testing
...............

On commit or pull request to the repository the unit tests in ``python/tests`` are run using the 
configuration in ``pyproject.toml`` using nox (also see its configuration in 
``noxfile.py``). **Please provide unit tests with your pull requests.** 

Fuzz Testing
...............

A.k.a „monkey testing“.

PiFinder's software can be invoked with the ``--script <file>`` parameter, 
which plays back the key strokes listed in the specified file. 

In the ``scripts`` folder you will find two files that contain randomly created key
presses. One file contains 1k the other 10k simulated key presses. We recommend 
to run this after every change to the UI, before you create the pull request. 
This is currently not automatically done on commit to the repository.

There's also a script to create larger keystroke files. 
 
Help Needed
...............

Currently the number of tests is rather low and needs improvement. 

Please visit ``Issue #232 <https://github.com/brickbots/PiFinder/issues/232>``_ 
for a discussion of tests that we would like to implement.  

References
------------

.. [NIELSEN_LIMITS] https://www.nngroup.com/articles/response-times-3-important-limits/
.. [GIL] https://realpython.com/python-gil/
