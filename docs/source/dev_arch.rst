
Architecture
================

The key words "MUST", "MUST NOT", "REQUIRED", "SHALL", "SHALL NOT", "SHOULD", "SHOULD NOT", "RECOMMENDED",  
"MAY", and "OPTIONAL" in this page are to be interpreted as described in `RFC 2119 <https://datatracker.ietf.org/doc/html/rfc2119>`_.

Solution Platform Constraints
--------—-------------------- 

To facilitate do-it-yourself building, the solution platform is the Raspberry Pi with a 
self-developed HAT, which contains an OLED display and a custom keyboard. Integrated into
the HAT is an IMU and a GPS chip with antenna. Only components compatible with
this solution platform will be used. That means that only cameras compatible with the 
Raspberry Pi CSI camera connector are supported.

Choice of Language: Python
----------------------------

The main language of the PiFinder software is Python. Python is a well known language
with a lot of support for managing astronomical data. There‘s good support for 
image manipulation, statistics, APIs and implementing web servers. 

The second most used language are shell scripts managing especially the setup of the
Raspberry Pi and upgrades.

Architecture determining Requirements
-----------------------------------------

As PiFinder is an interactive application with user input, 
there are some time-critical requirements: 

1. The camera picture SHALL be displayed as fast as possible on Raspberry Pi, 
   if it is displayed, so that movements of the telescope are reflected in the 
   display "instantanously" for the users. This implies a limit of 0.1s, see 
   [NIELSEN_LIMITS].[1]_ 
2. The position derived on the celestial sky from the camera picture SHALL likewise 
   be displayed "instantanously". This means a very fast blind plate-solver MUST be used.
3. While the telescope is moved, the camera is not able to supply pictures that could
   be solved by the plate-solver (motion blur). In order to be able to provide 
   feedback on the movement to the users, PiFinder MUST use an IMU[2]_. 
   
This implies, that a lot of information needs to be collected in parallel, and MUST be 
processed and integrated to be displayed to the users. Given the choice of Python 
as the main programming language means that the choice of concurrency primitives is
important: 

As Python has a Global Interpreter Lock [GIL], PiFinder uses separate processes
for the different tasks mentioned above. This means that for communication between the 
processes either queues or shared memory are employed. **Wherever possible, we prefer to 
use queues, as it provides a decoupling of creation and consumption of data, so that
the receiving end can process the data at a convenient point in time.**

Therefore PiFinder consists of the following processes: 

- **a** cde
- **b** efg
- tbd.

.. [1] Realistically, < 0.5 - 1 s.
.. [2] inertial measurement unit, that uses accelerometers, gyroscopes and a magnetometer
       to estimate the movements it has undergone

Logging
--------- 

This choice of architecture means that logging to disk is a little bit more complex, as we
need to avoid writing to the same log file from multiple processes, to avoid overwriting
each other‘s logs. We have therefore implemented a log thread and queues delivering log 
messages from the processes. This means that in a log file, the order of log messages 
can be out of order.  

Choice of Plate-Solver
------------------------ 

PiFinder uses 


Testing
-------—--



.. [NIELSEN_LIMITS] https://www.nngroup.com/articles/response-times-3-important-limits/
.. [GIL] https://realpython.com/python-gil/