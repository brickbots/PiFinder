Machine-readable API
====================

PiFinder exposes optional JSON endpoints for automation and external tools.

Endpoints
---------

GET /api/status
    Returns current power state, solve state, camera type, location, solution,
    IMU, SQM, and software version.

GET /api/solution
    Returns current plate solve solution when available.

GET /api/visible_stars
    Returns visible stars for the current field.

Query parameters:

``render_mag_limit``
    Magnitude limit for stars returned for rendering. Default: 5.5.

``label_mag_limit``
    Magnitude limit for stars suggested for labeling. Default: 2.5.

``max_labels``
    Maximum number of suggested labels. Default: 5.

``source``
    ``camera`` uses ``solution.camera_solve``.
    ``screen`` uses top-level ``solution.RA`` / ``solution.Dec`` / ``solution.Roll``.

Example
-------

.. code-block:: bash

    curl http://pifinder.local/api/status
    curl "http://pifinder.local/api/visible_stars?source=camera&render_mag_limit=5.5"
    curl "http://pifinder.local/api/visible_stars?source=screen&render_mag_limit=5.5"