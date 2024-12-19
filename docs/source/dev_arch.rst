
Architecture
================

The key words "MUST", "MUST NOT", "REQUIRED", "SHALL", "SHALL NOT", "SHOULD", "SHOULD NOT", "RECOMMENDED",  
"MAY", and "OPTIONAL" in this page are to be interpreted as described in `RFC 2119 <https://datatracker.ietf.org/doc/html/rfc2119>`_.

Overview
----------------

As PiFinder is an interactive application with user input, there is some time-critical requirements: 

1. The camera picture SHALL be displayed as fast as possible on Raspberry Pi, if it is displayed, so that movements 
   of the telescope are reflected in the display "instantanously" for the users. This implies a limit of 0.1s, see [NIELSEN_LIMITS]. 
2. The position derived on the celestial sky from the camera picture shall likewise be diplayed "instantanously". 
   This means a very fast blind plate-solver is needed. Depending
3. 



.. [NIELSEN_LIMITS] https://www.nngroup.com/articles/response-times-3-important-limits/
.. [GIL] https://realpython.com/python-gil/