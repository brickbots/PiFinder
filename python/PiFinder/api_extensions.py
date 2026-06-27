#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PiFinder API Extensions
=======================
Registers machine-readable REST API endpoints on PiFinder's Flask Web Server.

Usage:
    Add the following at the end of Server.__init__ in
    PiFinder/python/PiFinder/server.py, before run() is called:

        from PiFinder.api_extensions import register_api_routes
        register_api_routes(app, self, require_auth=False)

Dependencies: No additional dependencies. Reuses PiFinder's existing Flask / PIL / shared state.
"""

import io
import json
import logging

from flask import request, session, Response
from PIL import Image
from PiFinder import utils

logger = logging.getLogger("PiFinderAPI")


def _json_response(data, status=200):
    """Unified JSON response format"""
    return Response(
        json.dumps(data, default=str, ensure_ascii=False),
        status=status,
        content_type="application/json; charset=utf-8",
    )


def _pil_to_png_bytes(img: Image.Image) -> bytes:
    """Convert a PIL Image to PNG bytes"""
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _png_response(img: Image.Image) -> Response:
    """Wrap a PIL Image in a Flask PNG response"""
    return Response(_pil_to_png_bytes(img), content_type="image/png")


def _pointing_to_dict(p):
    """Serialize a :class:`Pointing` (or ``None``) to a plain
    ``{RA, Dec, Roll}`` dict of floats."""
    if p is None:
        return {"RA": None, "Dec": None, "Roll": None}
    return {"RA": float(p.RA), "Dec": float(p.Dec), "Roll": float(p.Roll)}


def _solution_to_dict(sol) -> dict:
    """Serialize a :class:`PointingEstimate` to the JSON shape the REST API
    has always emitted (the legacy ``solved`` dict keys), so external
    clients (e.g. OpenClaw) keep a stable contract across the dataclass
    migration in PR #429.

    Mapping back to the canonical access shape:

    * top-level ``RA``/``Dec``/``Roll`` ← ``pointing.aligned.estimate``
      (where the eyepiece points — the IMU-progressed aligned pointing).
    * ``camera_center`` ← ``pointing.camera.estimate`` (IMU-progressed
      camera-axis pointing).
    * ``camera_solve`` ← ``pointing.camera.solve`` (the IMU-untouched
      plate-solve at the camera centre).
    * ``solve_time`` ← ``estimate_time`` (renamed in ADR-0013; the old key
      is kept here for wire compatibility).

    ``imu_quat`` from the old dict is intentionally dropped — it was a raw
    numpy quaternion that no endpoint reads and never serialized cleanly.
    """
    pm = sol.pointing
    aligned = _pointing_to_dict(pm.aligned.estimate)
    diag = sol.diagnostics
    return {
        "RA": aligned["RA"],
        "Dec": aligned["Dec"],
        "Roll": aligned["Roll"],
        "camera_center": {
            **_pointing_to_dict(pm.camera.estimate),
            "Alt": None,
            "Az": None,
        },
        "camera_solve": _pointing_to_dict(pm.camera.solve),
        "Alt": float(sol.Alt) if sol.Alt is not None else None,
        "Az": float(sol.Az) if sol.Az is not None else None,
        "solve_source": sol.solve_source.value if sol.solve_source else None,
        "solve_time": sol.estimate_time,
        # cam_solve_time was dropped from the dataclass (value-identical to
        # last_solve_success under epoch semantics); keep the key for clients.
        "cam_solve_time": sol.last_solve_success,
        "last_solve_attempt": sol.last_solve_attempt,
        "last_solve_success": sol.last_solve_success,
        "constellation": sol.constellation,
        "FOV": diag.FOV,
        "Matches": diag.Matches,
        "RMSE": diag.RMSE,
        "Prob": diag.Prob,
        "T_solve": diag.T_solve,
        "T_extract": diag.T_extract,
    }


def register_api_routes(app, server_instance, require_auth=False):
    """
    Register all /api/* routes on the Flask app.

    Parameters
    ----------
    app : Flask
        The existing Flask application instance in the PiFinder Server
    server_instance : Server
        The PiFinder Server class instance (self), used to access shared_state, etc.
    require_auth : bool
        Whether to enable session authentication for /api/* endpoints.
        Defaults to False for easier access by automation tools.
    """

    # Built-in simple token authentication (optional), to avoid modifying the auth_required decorator
    api_token = getattr(server_instance, "api_token", None)

    def _check_auth():
        if not require_auth and not api_token:
            return True
        # 1) Session authentication (same as the Web UI)
        if session.get("authenticated"):
            return True
        # 2) URL query token authentication (convenient for scripts/OpenClaw)
        if api_token and request.args.get("token") == api_token:
            return True
        return False

    def _auth_wrapper(func):
        """Return 401 if authentication is enabled and the request is not authorized"""

        def wrapper(*args, **kwargs):
            if not _check_auth():
                return _json_response({"error": "Unauthorized"}, 401)
            return func(*args, **kwargs)

        return wrapper

    # ───────────────────────────────────────────────
    # 1. Aggregated status endpoint (fetch everything at once)
    # ───────────────────────────────────────────────
    @app.route("/api/status")
    def api_status():
        try:
            ss = server_instance.shared_state
            loc = ss.location()
            sol = ss.solution()
            dt_utc = ss.datetime()

            data = {
                "power_state": ss.power_state(),
                "solve_state": ss.solve_state(),
                "camera_type": ss.camera_type(),
                "location": loc.to_dict() if loc else None,
                "solution": _solution_to_dict(sol),
                "datetime": {
                    "utc": dt_utc.isoformat() if dt_utc else None,
                    "local": ss.local_datetime().isoformat() if dt_utc else None,
                },
                "imu": ss.imu().to_dict() if ss.imu() else None,
                "sqm": ss.sqm().to_dict() if ss.sqm() else None,
                "software_version": _get_version(server_instance),
            }
            return _json_response(data)
        except Exception as e:
            logger.error("api/status error: %s", e)
            return _json_response({"error": str(e)}, 500)

    # ───────────────────────────────────────────────
    # 2. Atomic endpoints (fetch individual items on demand)
    # ───────────────────────────────────────────────

    @app.route("/api/time")
    def api_time():
        try:
            ss = server_instance.shared_state
            dt_utc = ss.datetime()
            data = {
                "utc": dt_utc.isoformat() if dt_utc else None,
                "local": ss.local_datetime().isoformat() if dt_utc else None,
                "timezone": ss.location().timezone if ss.location() else "UTC",
            }
            return _json_response(data)
        except Exception as e:
            logger.error("api/time error: %s", e)
            return _json_response({"error": str(e)}, 500)

    @app.route("/api/location")
    def api_location():
        try:
            server_instance.update_gps()  # 先刷新 GPS 缓存
            loc = server_instance.shared_state.location()
            if loc and loc.lock:
                return _json_response(loc.to_dict())
            return _json_response(
                {
                    "lock": False,
                    "note": "GPS not locked or location unavailable",
                    "location": loc.to_dict() if loc else None,
                },
                503,
            )
        except Exception as e:
            logger.error("api/location error: %s", e)
            return _json_response({"error": str(e)}, 500)

    @app.route("/api/solution")
    def api_solution():
        try:
            ss = server_instance.shared_state
            if ss.solve_state() is not True:
                return _json_response(
                    {
                        "solve_state": ss.solve_state(),
                        "note": "No valid plate solve yet",
                    },
                    503,
                )
            sol = ss.solution()
            if not sol.has_pointing():
                return _json_response({"note": "Solution data empty"}, 503)

            payload = _solution_to_dict(sol)

            # Add Alt/Az if location and datetime are ready
            if ss.altaz_ready():
                try:
                    from PiFinder.calc_utils import sf_utils

                    ts = sf_utils.ts
                    dt = ss.datetime()
                    aligned = sol.pointing.aligned.estimate
                    ra_h = float(aligned.RA) / 15.0
                    dec_d = float(aligned.Dec)
                    from skyfield.positionlib import position_of_radec

                    p = position_of_radec(
                        ra_hours=ra_h, dec_degrees=dec_d, epoch=ts.J2000
                    )
                    alt, az, _ = p.altaz(
                        observer=sf_utils.topos(
                            ss.location().lat, ss.location().lon, ss.location().altitude
                        ),
                        epoch=ts.from_datetime(dt),
                    )
                    payload["Alt"] = alt.degrees
                    payload["Az"] = az.degrees
                except Exception:
                    pass

            return _json_response(payload)
        except Exception as e:
            logger.error("api/solution error: %s", e)
            return _json_response({"error": str(e)}, 500)

    @app.route("/api/visible_stars")
    def api_visible_stars():
        """
        Return the visible star data within the current PiFinder field of view.

        Design goals:
            1. Use the RA / Dec / Roll from camera_solve, without being affected by IMU correction;
            2. Re-render the star field using PiFinder.plot.Starfield;
            3. Return star coordinates for high-resolution rendering in OpenClaw;
            4. Also indicate which stars are recommended for labeling with label=true;
            5. Support render_mag_limit / label_mag_limit / max_labels.

        Query parameters:
            render_mag_limit:
                Magnitude limit used for "drawing star points". Default is 5.5.
                Example: /api/visible_stars?render_mag_limit=5.5

            mag_limit:
                Backward-compatible legacy parameter.
                Used if render_mag_limit is not provided.
                Example: /api/visible_stars?mag_limit=5.5

            label_mag_limit:
                Magnitude limit used for "automatically labeling star names". Default is 2.5.
                Example: /api/visible_stars?label_mag_limit=4.0

            max_labels:
                Maximum number of stars to label. Default is 5.
                If there are too few stars within label_mag_limit, the brightest stars
                currently in the field of view will be added automatically.

            constellation_brightness:
                Brightness of constellation lines. Default is 32.

            shade_frustrum:
                Whether to render the frustum shadow. Default is true.

            include_image:
                Whether to include the PiFinder-rendered star chart as a base64 PNG.
                Default is false.

            use_camera_solve:
                Whether to prefer the camera-axis plate-solve
                (pointing.camera.solve) over the aligned estimate.
                Default is true.

            fov:
                Rendering FOV. Default is 10.2.

            render_size:
                Rendering size. Default is 1088.
                For example, when render_size=2048, x_pos / y_pos will be output
                in a 2048×2048 coordinate system.
        """
        try:
            import base64

            ss = server_instance.shared_state

            # --------------------------------------------------
            # 1. Check plate-solving status
            # --------------------------------------------------
            solve_state = ss.solve_state()

            if solve_state is not True:
                return _json_response(
                    {
                        "success": False,
                        "solve_state": solve_state,
                        "note": "No valid plate solve yet",
                    },
                    503,
                )

            sol = ss.solution()

            if not sol.has_pointing():
                return _json_response(
                    {
                        "success": False,
                        "note": "Solution data empty",
                    },
                    503,
                )

            # --------------------------------------------------
            # 2. Read query parameters
            # --------------------------------------------------

            # Backward compatibility with the legacy mag_limit parameter.
            # In the new logic, render_mag_limit represents the magnitude limit for "drawing star points".
            try:
                render_mag_limit = float(
                    request.args.get(
                        "render_mag_limit",
                        request.args.get("mag_limit", 5.5),
                    )
                )
            except Exception:
                render_mag_limit = 5.5

            # label_mag_limit represents the magnitude limit for "recommended star name labeling".
            try:
                label_mag_limit = float(request.args.get("label_mag_limit", 2.5))
            except Exception:
                label_mag_limit = 2.5

            # If there are not enough stars within label_mag_limit, add the brightest stars currently in the field of view.
            try:
                max_labels = int(request.args.get("max_labels", 5))
            except Exception:
                max_labels = 5

            if max_labels < 0:
                max_labels = 0
            if max_labels > 30:
                max_labels = 30

            try:
                constellation_brightness = int(
                    request.args.get("constellation_brightness", 32)
                )
            except Exception:
                constellation_brightness = 32

            shade_frustrum_q = str(request.args.get("shade_frustrum", "true")).lower()
            shade_frustrum = shade_frustrum_q not in ("0", "false", "no", "off")

            include_image_q = str(request.args.get("include_image", "false")).lower()
            include_image = include_image_q in ("1", "true", "yes", "on")

            use_camera_solve_q = str(
                request.args.get("use_camera_solve", "true")
            ).lower()
            use_camera_solve = use_camera_solve_q not in ("0", "false", "no", "off")

            try:
                solve_fov = sol.diagnostics.FOV
                fov = float(
                    request.args.get(
                        "fov", solve_fov if solve_fov is not None else 10.2
                    )
                )
            except Exception:
                fov = 10.2

            try:
                render_size = int(request.args.get("render_size", 1088))
            except Exception:
                render_size = 1088

            if render_size < 128:
                render_size = 128
            if render_size > 4096:
                render_size = 4096

            # --------------------------------------------------
            # 3. Select the solve source
            # --------------------------------------------------
            source = "camera_solve"

            if use_camera_solve and sol.pointing.camera.solve is not None:
                camera_solve = sol.pointing.camera.solve

                ra = float(camera_solve.RA)
                dec = float(camera_solve.Dec)
                roll = float(camera_solve.Roll)

            else:
                source = "solution"

                aligned = sol.pointing.aligned.estimate
                ra = float(aligned.RA)
                dec = float(aligned.Dec)
                roll = float(aligned.Roll)

            # --------------------------------------------------
            # 4. Get the API-specific Starfield object
            # --------------------------------------------------
            #
            # This relies on the helper function you added earlier:
            #
            #     _get_api_starfield(...)
            #
            # It creates and caches PiFinder.plot.Starfield.
            # This avoids the need to look for the align app's starfield inside server_instance.
            #
            starfield = _get_api_starfield(
                server_instance,
                resolution=(render_size, render_size),
                mag_limit=7,
                fov=fov,
            )

            # --------------------------------------------------
            # 5. Call PiFinder's native star chart rendering logic
            # --------------------------------------------------
            image_obj, visible_stars = starfield.plot_starfield(
                ra,
                dec,
                roll,
                constellation_brightness,
                shade_frustrum=shade_frustrum,
            )

            # --------------------------------------------------
            # 6. Build visible_stars
            # --------------------------------------------------
            stars_payload = []
            label_indices = set()
            mag_col = None

            if hasattr(visible_stars, "copy") and hasattr(visible_stars, "columns"):
                df = visible_stars.copy()

                # Look up the magnitude field. PiFinder Starfield usually uses magnitude.
                for candidate in ("vmag", "mag", "magnitude", "Vmag", "V"):
                    if candidate in df.columns:
                        mag_col = candidate
                        break

                # First filter by render_mag_limit: these stars will be used for drawing.
                if mag_col is not None:
                    df = df[df[mag_col].astype(float) <= render_mag_limit].copy()

                # Generate label_indices:
                # 1. First label stars within label_mag_limit;
                # 2. If the count is less than max_labels, add the brightest stars currently in the field of view.
                if mag_col is not None and not df.empty and max_labels > 0:
                    try:
                        bright_df = df[df[mag_col].astype(float) <= label_mag_limit]
                        label_indices.update(bright_df.index.tolist())

                        if len(label_indices) < max_labels:
                            brightest_df = df.sort_values(mag_col).head(max_labels)
                            label_indices.update(brightest_df.index.tolist())
                    except Exception:
                        label_indices = set()

                # Convert the DataFrame to JSON.
                # Note: In the Hipparcos catalog, the index is usually the HIP number,
                # so here we return the index as hip_id.
                for hip_id, row in df.iterrows():
                    item = {}

                    item["hip_id"] = _safe_json_value(hip_id)

                    for key, value in row.to_dict().items():
                        item[key] = _safe_json_value(value)

                    item["display_name"] = _guess_star_name(item)

                    mag_value = _extract_mag_value(item)

                    item["label"] = hip_id in label_indices

                    if mag_value is not None and mag_value <= label_mag_limit:
                        item["label_reason"] = f"magnitude <= {label_mag_limit}"
                    elif item["label"]:
                        item["label_reason"] = f"top {max_labels} brightest in field"
                    else:
                        item["label_reason"] = None

                    stars_payload.append(item)

            elif isinstance(visible_stars, list):
                # Compatibility for the list[dict] case.
                tmp_items = []

                for i, row in enumerate(visible_stars):
                    if isinstance(row, dict):
                        item = {k: _safe_json_value(v) for k, v in row.items()}
                    else:
                        item = {"value": _safe_json_value(row)}

                    if "hip_id" not in item:
                        item["hip_id"] = item.get("HIP", item.get("hip", i))

                    item["display_name"] = _guess_star_name(item)

                    mag_value = _extract_mag_value(item)

                    if mag_value is not None and mag_value > render_mag_limit:
                        continue

                    item["_mag_value_for_sort"] = mag_value
                    tmp_items.append(item)

                # Also apply the labeling logic for the list case.
                bright_items = []
                sortable_items = []

                for item in tmp_items:
                    mag_value = item.get("_mag_value_for_sort")

                    if mag_value is not None:
                        sortable_items.append(item)

                        if mag_value <= label_mag_limit:
                            bright_items.append(item)

                label_ids = set()

                for item in bright_items:
                    label_ids.add(str(item.get("hip_id")))

                if len(label_ids) < max_labels:
                    sortable_items.sort(
                        key=lambda x: (
                            99
                            if x.get("_mag_value_for_sort") is None
                            else x.get("_mag_value_for_sort")
                        )
                    )
                    for item in sortable_items[:max_labels]:
                        label_ids.add(str(item.get("hip_id")))

                for item in tmp_items:
                    mag_value = item.get("_mag_value_for_sort")
                    item.pop("_mag_value_for_sort", None)

                    item["label"] = str(item.get("hip_id")) in label_ids

                    if mag_value is not None and mag_value <= label_mag_limit:
                        item["label_reason"] = f"magnitude <= {label_mag_limit}"
                    elif item["label"]:
                        item["label_reason"] = f"top {max_labels} brightest in field"
                    else:
                        item["label_reason"] = None

                    stars_payload.append(item)

            else:
                return _json_response(
                    {
                        "success": False,
                        "error": "Unsupported visible_stars type",
                        "type": str(type(visible_stars)),
                    },
                    500,
                )

            # --------------------------------------------------
            # 7. Sort: brightest stars first
            # --------------------------------------------------
            try:
                stars_payload.sort(
                    key=lambda s: (
                        99 if _extract_mag_value(s) is None else _extract_mag_value(s)
                    )
                )
            except Exception:
                pass

            label_count = sum(1 for s in stars_payload if s.get("label"))

            # --------------------------------------------------
            # 8. Assemble the response
            # --------------------------------------------------
            data = {
                "success": True,
                "source": source,
                "solve_state": solve_state,
                "camera": {
                    "RA": ra,
                    "Dec": dec,
                    "Roll": roll,
                },
                "filters": {
                    "render_mag_limit": render_mag_limit,
                    "label_mag_limit": label_mag_limit,
                    "max_labels": max_labels,
                    "constellation_brightness": constellation_brightness,
                    "shade_frustrum": shade_frustrum,
                    "fov": fov,
                    "render_size": render_size,
                },
                "count": len(stars_payload),
                "label_count": label_count,
                "visible_stars": stars_payload,
            }

            if include_image:
                png_bytes = _pil_to_png_bytes(image_obj)
                data["image"] = {
                    "format": "png",
                    "encoding": "base64",
                    "data": base64.b64encode(png_bytes).decode("ascii"),
                }

            return _json_response(data)

        except Exception as e:
            logger.exception("api/visible_stars error")
            return _json_response({"success": False, "error": str(e)}, 500)

    @app.route("/api/imu")
    def api_imu():
        try:
            imu = server_instance.shared_state.imu()
            if imu:
                return _json_response(imu.to_dict())
            return _json_response({"note": "IMU data not available"}, 503)
        except Exception as e:
            logger.error("api/imu error: %s", e)
            return _json_response({"error": str(e)}, 500)

    @app.route("/api/sqm")
    def api_sqm():
        try:
            sqm = server_instance.shared_state.sqm()
            if sqm:
                return _json_response(sqm.to_dict())
            return _json_response({"note": "SQM data not available"}, 503)
        except Exception as e:
            logger.error("api/sqm error: %s", e)
            return _json_response({"error": str(e)}, 500)

    # ───────────────────────────────────────────────
    # 3. Image endpoint (no authentication required, convenient for direct embedding in browsers/OpenClaw)
    # ───────────────────────────────────────────────

    @app.route("/api/screen")
    def api_screen():
        """Return the current screen display as a 128x128 PNG, equivalent to /image"""
        try:
            img = server_instance.shared_state.screen()
            if img is None:
                img = Image.new("RGB", (128, 128), color=(0, 0, 0))
            return _png_response(img)
        except Exception as e:
            logger.error("api/screen error: %s", e)
            empty = Image.new("RGB", (128, 128), color=(73, 109, 137))
            return _png_response(empty)

    @app.route("/api/camera/raw")
    def api_camera_raw():
        """Return the raw CMOS image, if available"""
        try:
            raw = server_instance.shared_state.cam_raw()
            if raw is None:
                return _json_response({"note": "No raw image available"}, 503)
            # raw may be a PIL Image or a NumPy array
            if hasattr(raw, "save"):
                img = raw.convert("RGB") if raw.mode != "RGB" else raw
            else:
                import numpy as np

                arr = np.asarray(raw)
                if arr.ndim == 2:
                    img = Image.fromarray(arr, mode="L").convert("RGB")
                else:
                    img = Image.fromarray(arr)
            return _png_response(img)
        except Exception as e:
            logger.error("api/camera/raw error: %s", e)
            return _json_response({"error": str(e)}, 500)

    @app.route("/api/camera/debug")
    def api_camera_debug():
        """Return the latest debug frame from the solver_debug_dumps directory"""
        try:
            from pathlib import Path

            debug_dir = utils.debug_dump_dir
            if not debug_dir.exists():
                debug_dir = Path("solver_debug_dumps")
            if not debug_dir.exists():
                return _json_response({"note": "Debug dump directory not found"}, 503)

            files = sorted(
                debug_dir.glob("*.png"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if not files:
                return _json_response({"note": "No debug frames available"}, 503)

            with open(files[0], "rb") as f:
                return Response(f.read(), content_type="image/png")
        except Exception as e:
            logger.error("api/camera/debug error: %s", e)
            return _json_response({"error": str(e)}, 500)

    # ───────────────────────────────────────────────
    # 4. Lightweight control endpoints (optional, for remote triggering by OpenClaw)
    # ───────────────────────────────────────────────

    @app.route("/api/key", methods=["POST"])
    def api_key():
        """Simulate button input. JSON body: {"button": "UP"} or {"button": 1}"""
        try:
            body = request.get_json(silent=True)
            if not body or "button" not in body:
                return _json_response({"error": "Missing 'button' field"}, 400)
            btn = body["button"]
            # Reuse server_instance's button_dict, if it exists
            bd = getattr(server_instance, "button_dict", {})
            if isinstance(btn, str) and btn in bd:
                server_instance.keyboard_queue.put(bd[btn])
            else:
                server_instance.keyboard_queue.put(int(btn))
            return _json_response({"success": True, "button": btn})
        except Exception as e:
            logger.error("api/key error: %s", e)
            return _json_response({"error": str(e)}, 500)

    @app.route("/api/stop", methods=["POST"])
    def api_stop():
        """Cleanly shut down the entire PiFinder application.

        PiFinder's normal shutdown is driven by a terminal Ctrl-C: SIGINT is
        delivered to the *whole* foreground process group at once, so every
        child (camera, solver, integrator, imu, web server, multiprocessing
        helpers) exits from its own KeyboardInterrupt and the main process's
        .join() calls return. Most children run bare ``while True`` loops and
        neither catch KeyboardInterrupt nor watch a stop flag, so signalling
        only the main process would leave it hanging in .join() forever.

        This handler runs inside the web-server child, so ``os.getpgid(0)`` is
        the PiFinder process group. Signalling that group reproduces the Ctrl-C
        path. The signal is fired from a short-lived timer thread so this HTTP
        response can flush before the server process itself is torn down.

        For automation that launched PiFinder in its own session (the expected
        case), this group is isolated from the launcher, so the launcher
        survives and can escalate to SIGTERM/SIGKILL if a child still stalls.

        Body (optional JSON): {"delay": <seconds before signalling, default 0.5>}
        """
        import os
        import signal
        import threading

        try:
            body = request.get_json(silent=True) or {}
            delay = float(body.get("delay", 0.5))
        except Exception:
            delay = 0.5
        # Keep the delay sane: long enough to flush the response, not so long
        # that an automated stop appears to hang.
        delay = min(max(delay, 0.0), 5.0)

        def _shutdown():
            try:
                pgid = os.getpgid(0)
                logger.info("api/stop: sending SIGINT to process group %s", pgid)
                os.killpg(pgid, signal.SIGINT)
            except Exception:
                logger.exception("api/stop: killpg failed; signalling self instead")
                try:
                    os.kill(os.getpid(), signal.SIGINT)
                except Exception:
                    logger.exception("api/stop: self-signal failed")

        threading.Timer(delay, _shutdown).start()
        return _json_response(
            {"success": True, "note": "Shutting down PiFinder", "delay": delay}
        )

    logger.info(
        "PiFinder API extensions registered (%s auth)",
        "with" if require_auth else "without",
    )


def _get_version(server_instance) -> str:
    """Try to read the PiFinder software version"""
    try:
        version_txt = getattr(server_instance, "version_txt", None)
        if version_txt:
            with open(version_txt, "r") as f:
                return f.read().strip()
    except Exception:
        pass
    return "Unknown"


def _safe_json_value(value):
    """
    Convert pandas / NumPy / NaN objects into JSON-serializable objects.
    """
    try:
        import math
        import numpy as np

        if value is None:
            return None

        # numpy scalar
        if isinstance(value, np.generic):
            value = value.item()

        # NaN / inf
        if isinstance(value, float):
            if math.isnan(value) or math.isinf(value):
                return None

        # Basic built-in types
        if isinstance(value, (str, int, float, bool)):
            return value

        # list / tuple
        if isinstance(value, (list, tuple)):
            return [_safe_json_value(v) for v in value]

        # dict
        if isinstance(value, dict):
            return {str(k): _safe_json_value(v) for k, v in value.items()}

        return str(value)

    except Exception:
        return str(value)


def _guess_star_name(item):
    """
    Try to infer the star name from the fields in visible_stars.
    Different PiFinder versions may use slightly different catalog field names,
    so try several possible field names.。
    """
    name_keys = [
        "common_name",
        "name",
        "proper",
        "proper_name",
        "bayer",
        "bayer_name",
        "bayer_or_flamsteed",
        "label",
        "star_name",
        "hr",
        "hr_id",
        "hip",
        "hip_id",
        "hd",
        "hd_id",
    ]

    for key in name_keys:
        value = item.get(key)
        if value not in (None, "", "nan", "None"):
            return str(value)

    return None


def _extract_mag_value(item):
    """
    Extract the magnitude from a star dictionary.
    """
    for key in ("vmag", "mag", "magnitude", "Vmag", "V"):
        if key in item:
            try:
                return float(item[key])
            except Exception:
                return None
    return None


class _ApiGrayColors:
    """
    Minimal colors object used by PiFinder.plot.Starfield.

    Starfield.__init__ calls colors.get(64) and colors.get(256).
    For API-side star chart re-rendering, we do not need the full UI theme colors;
    we only need to return a valid RGB tuple.
    """

    def get(self, value):
        try:
            v = int(value)
        except Exception:
            v = 255

        if v < 0:
            v = 0
        if v > 255:
            v = 255

        return (v, v, v)


def _get_api_starfield(
    server_instance,
    resolution=(1088, 1088),
    mag_limit=7,
    fov=10.2,
):
    """
    Get or create the API-specific Starfield object.

    Why cache it?
        Starfield initialization loads the Hipparcos catalog and constellation line data,
        so recreating it for every request would be relatively slow.

    Why not look for it in server_instance?
        PiFinder's Web Server object usually does not directly hold the align app's starfield,
        so creating one in the API layer is more stable.
    """
    cache_key = (
        int(resolution[0]),
        int(resolution[1]),
        float(mag_limit),
        float(fov),
    )

    cached_key = getattr(server_instance, "_api_starfield_cache_key", None)
    cached_obj = getattr(server_instance, "_api_starfield_cache", None)

    if cached_key == cache_key and cached_obj is not None:
        return cached_obj

    from PiFinder.plot import Starfield

    colors = _ApiGrayColors()

    starfield = Starfield(
        colors=colors,
        resolution=resolution,
        mag_limit=mag_limit,
        fov=fov,
    )

    server_instance._api_starfield_cache_key = cache_key
    server_instance._api_starfield_cache = starfield

    return starfield
