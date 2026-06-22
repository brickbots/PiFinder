Machine-readable API
====================

PiFinder exposes a set of optional JSON and image endpoints under ``/api/`` for
automation and external tools. They are registered on the same web server that
serves the PiFinder web interface, and by default they require **no
authentication**, so any client on the same network can call them.

Everything is served relative to the PiFinder's address, for example
``http://pifinder.local/api/status``. JSON endpoints return
``application/json``; image endpoints return ``image/png``. When the data a call
needs isn't ready yet — no GPS lock, no plate solve, no IMU or SQM reading — that
endpoint returns HTTP ``503`` with a short JSON ``note`` explaining why, rather
than failing outright.

Status and data
---------------

These endpoints return JSON. ``/api/status`` is the convenient one-shot call; the
rest let you fetch a single value on demand.

GET /api/status
    Aggregated snapshot, fetching everything in one call: ``power_state``,
    ``solve_state``, ``camera_type``, ``location``, ``solution``, ``datetime``
    (both ``utc`` and ``local``), ``imu``, ``sqm`` and ``software_version``.

GET /api/time
    The current ``utc`` and ``local`` time plus the active ``timezone``.

GET /api/location
    The current GPS location (latitude, longitude, altitude, timezone and lock
    state). The GPS cache is refreshed before responding, and the call returns
    ``503`` if GPS is not locked.

GET /api/solution
    The current plate-solve solution — RA, Dec, Roll, field of view and the
    matched-star statistics. ``Alt`` and ``Az`` are added when a location and
    time are available. Returns ``503`` if there is no valid solve yet.

GET /api/imu
    The current IMU data (orientation and movement state). Returns ``503`` when
    no IMU is present or no reading is available.

GET /api/sqm
    The latest Sky Quality Meter estimate of sky brightness. Returns ``503``
    when no reading is available.

GET /api/visible_stars
    Re-renders the star field for the current pointing and returns the visible
    stars as structured data, optionally with the rendered chart as a base64
    PNG. It uses the camera solve (RA / Dec / Roll) so the result isn't shifted
    by IMU dead-reckoning.

    The response carries the solve ``source`` and pointing, the ``filters`` that
    were applied, a ``count`` and ``label_count``, and a ``visible_stars`` array.
    Each star includes its catalog fields, a ``display_name``, and a ``label``
    flag (with ``label_reason``) marking the stars suggested for on-screen
    labelling. Rendered star positions are returned in the coordinate system set
    by ``render_size``.

Query parameters for ``/api/visible_stars``:

``render_mag_limit``
    Magnitude limit for the stars returned for rendering. Default: ``5.5``. The
    legacy name ``mag_limit`` is still accepted.

``label_mag_limit``
    Magnitude limit for the stars suggested for labelling. Default: ``2.5``.

``max_labels``
    Maximum number of suggested labels, clamped to 0–30. Default: ``5``. If too
    few stars fall within ``label_mag_limit``, the brightest stars in the field
    are added to reach this count.

``use_camera_solve``
    Prefer the camera solve over the integrated, IMU-corrected solution.
    Default: ``true``.

``fov``
    Rendering field of view in degrees. Default: the solve's FOV, or ``10.2``.

``render_size``
    Output resolution in pixels, clamped to 128–4096. Star positions are
    returned in this coordinate system. Default: ``1088``.

``constellation_brightness``
    Brightness of the constellation lines (0–255). Default: ``32``.

``shade_frustrum``
    Whether to shade the camera frustum. Default: ``true``.

``include_image``
    Include the rendered star chart in the response as a base64-encoded PNG.
    Default: ``false``.

Images
------

These endpoints return a PNG directly, which makes them easy to embed in a
browser or save to a file.

GET /api/screen
    The current 128×128 device screen as a PNG — the same image shown on the
    OLED.

GET /api/camera/raw
    The raw CMOS camera image as a PNG, when one is available; otherwise
    ``503``.

GET /api/camera/debug
    The most recent solver debug frame from the debug-dump directory, as a PNG;
    ``503`` if none have been written.

Control
-------

These endpoints accept a POST with a JSON body and change the state of the
PiFinder, so use them with care.

POST /api/key
    Simulate a keypad press. JSON body: ``{"button": "UP"}`` (a button name) or
    ``{"button": 1}`` (a raw key code).

POST /api/stop
    Cleanly shut down the entire PiFinder application, reproducing a terminal
    Ctrl-C. Optional JSON body ``{"delay": <seconds>}`` (default ``0.5``, capped
    at ``5``) sets how long to wait before signalling, so the HTTP response can
    flush first.

Example
-------

.. code-block:: bash

    # One-shot status, then individual values
    curl http://pifinder.local/api/status
    curl http://pifinder.local/api/solution
    curl http://pifinder.local/api/sqm

    # Visible stars, with the rendered chart embedded as a base64 PNG
    curl "http://pifinder.local/api/visible_stars?render_mag_limit=5.5&include_image=true"

    # Save the current screen to a file
    curl http://pifinder.local/api/screen -o screen.png

    # Simulate pressing the UP button
    curl -X POST http://pifinder.local/api/key \
         -H "Content-Type: application/json" \
         -d '{"button": "UP"}'
