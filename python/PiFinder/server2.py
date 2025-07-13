import io
import json
import logging
import time
import uuid
import os
import argparse
import sys
import multiprocessing
from datetime import datetime, timezone

import pydeepskylog as pds
from PIL import Image
from PiFinder import utils, calc_utils, config
from PiFinder.db.observations_db import (
    ObservationsDatabase,
)
from PiFinder.equipment import Telescope, Eyepiece
from PiFinder.keyboard_interface import KeyboardInterface
from PiFinder.multiproclogging import MultiprocLogging

from flask import Flask, request, jsonify, send_file, redirect, session, make_response
from jinja2 import Environment, FileSystemLoader, select_autoescape
from babel import Locale
from flask_babel import Babel, gettext, lazy_gettext, get_locale
# import gettext

sys_utils = utils.get_sys_utils()

# Initialize a safe gettext function that works in standalone mode
def safe_gettext(text):
    """Safe translation function that works with or without Flask context"""
    try:
        from flask import has_app_context
        if has_app_context():
            from flask_babel import gettext
            return gettext(text)
        else:
            return text
    except ImportError:
        return text

# Use safe translation function as default
_ = safe_gettext

logger = logging.getLogger("Server")

# Generate a secret to validate the auth cookie
SESSION_SECRET = str(uuid.uuid4())


def auth_required(func):
    def auth_wrapper(*args, **kwargs):
        # check for and validate session
        if 'authenticated' in session and session['authenticated']:
            return func(*args, **kwargs)
        
        # Store the original URL for redirect after login
        session['origin_url'] = request.url
        return redirect('/login')

    auth_wrapper.__name__ = func.__name__
    return auth_wrapper


class MockSharedState:
    """Mock shared state for standalone testing"""
    def __init__(self):
        self._location = type('Location', (), {
            'lock': False, 'lat': None, 'lon': None, 'altitude': None
        })()
        self._screen_img = None
        self._solve_state = False
        self._solution = None
    
    def location(self):
        return self._location
    
    def screen(self):
        return self._screen_img
    
    def solve_state(self):
        return self._solve_state
    
    def solution(self):
        return self._solution


def server2_locale():
    # Try to get from user preferences, session, or accept languages
    # For now, default to English
    return request.accept_languages.best_match(['en', 'fr', 'de', 'es']) or 'en'


class Server2:
    def __init__(
        self,
        keyboard_queue=None,
        ui_queue=None,
        gps_queue=None,
        shared_state=None,
        is_debug=False,
    ):
        self.version_txt = f"{utils.pifinder_dir}/version.txt"
        self.keyboard_queue = keyboard_queue or multiprocessing.Queue()
        self.ui_queue = ui_queue or multiprocessing.Queue() 
        self.gps_queue = gps_queue or multiprocessing.Queue()
        self.shared_state = shared_state or MockSharedState()
        self.ki = KeyboardInterface()
        # gps info
        self.lat = None
        self.lon = None
        self.altitude = None
        self.gps_locked = False

        button_dict = {
            "UP": self.ki.PLUS,
            "DN": self.ki.MINUS,
            "SQUARE": self.ki.SQUARE,
            "A": self.ki.LEFT,
            "B": self.ki.UP,
            "C": self.ki.DOWN,
            "D": self.ki.RIGHT,
            "ALT_PLUS": self.ki.ALT_PLUS,
            "ALT_MINUS": self.ki.ALT_MINUS,
            "ALT_LEFT": self.ki.ALT_LEFT,
            "ALT_UP": self.ki.ALT_UP,
            "ALT_DOWN": self.ki.ALT_DOWN,
            "ALT_RIGHT": self.ki.ALT_RIGHT,
            "ALT_0": self.ki.ALT_0,
            "LNG_LEFT": self.ki.LNG_LEFT,
            "LNG_UP": self.ki.LNG_UP,
            "LNG_DOWN": self.ki.LNG_DOWN,
            "LNG_RIGHT": self.ki.LNG_RIGHT,
            "LNG_SQUARE": self.ki.LNG_SQUARE,
        }

        self.network = sys_utils.Network()

        # Initialize Flask app with absolute template path
        views2_path = os.path.join(os.path.dirname(__file__), '..', 'views2')
        views2_path = os.path.abspath(views2_path)
        logger.debug(f"Template folder path: {views2_path}")
        
        app = Flask(__name__, template_folder=views2_path)
        app.secret_key = SESSION_SECRET
        app.config['DEBUG'] = True
        logger.info(f"Flask app created successfully: {app}")
        logger.info(f"Template folder: {app.template_folder}")
        
        # Setup Babel for i18n
        babel = Babel(app, locale_selector=server2_locale)
        
        # Configure Jinja2 environment for i18n
        app.jinja_env.add_extension('jinja2.ext.i18n')
        
        # # Create a simple gettext function for templates that works without translation files
        # def simple_gettext(text):
        #     return text
        
        # def simple_ngettext(singular, plural, n):
        #     return singular if n == 1 else plural
            
        # app.jinja_env.install_gettext_callables(simple_gettext, simple_ngettext, newstyle=True)
        
        # # Create a context-safe translation function
        # def translate(text):
        #     try:
        #         from flask_babel import gettext
        #         return gettext(text)
        #     except:
        #         return text
        
        # # Make translation function available to routes
        # app.jinja_env.globals['_'] = translate
        

        # Static files routes
        @app.route('/images/<path:filename>')
        def send_image(filename):
            return send_file(f'../views2/images/{filename}', mimetype='image/png')

        @app.route('/js/<path:filename>')
        def send_js(filename):
            return send_file(f'../views2/js/{filename}')

        @app.route('/css/<path:filename>')
        def send_css(filename):
            return send_file(f'../views2/css/{filename}')

        @app.route('/')
        def home():
            logger.debug("/ called")
            # Get version info
            software_version = "Unknown"
            try:
                with open(self.version_txt, "r") as ver_f:
                    software_version = ver_f.read()
            except (FileNotFoundError, IOError) as e:
                logger.warning(f"Could not read version file: {str(e)}")

            # Try to update GPS state
            try:
                self.update_gps()
            except Exception as e:
                logger.error(f"Failed to update GPS in home route: {str(e)}")

            # Use GPS data if available
            lat_text = str(self.lat) if self.gps_locked else ""
            lon_text = str(self.lon) if self.gps_locked else ""
            gps_icon = "gps_fixed" if self.gps_locked else "gps_off"
            gps_text = gettext("Locked") if self.gps_locked else gettext("Not Locked")

            # Default camera values
            ra_text = "0"
            dec_text = "0"
            camera_icon = "broken_image"

            # Try to get solution data
            try:
                if self.shared_state.solve_state() is True:
                    camera_icon = "camera_alt"
                    solution = self.shared_state.solution()
                    if solution:
                        hh, mm, _ = calc_utils.ra_to_hms(solution["RA"])
                        ra_text = f"{hh:02.0f}h{mm:02.0f}m"
                        dec_text = f"{solution['Dec']: .2f}"
            except Exception as e:
                logger.error(f"Failed to get solution data: {str(e)}")

            # Render the template with available data
            return app.jinja_env.get_template('index.html').render(
                title=gettext("Home"),
                software_version=software_version,
                wifi_mode=self.network.wifi_mode(),
                ip=self.network.local_ip(),
                network_name=self.network.get_connected_ssid(),
                gps_icon=gps_icon,
                gps_text=gps_text,
                lat_text=lat_text,
                lon_text=lon_text,
                camera_icon=camera_icon,
                ra_text=ra_text,
                dec_text=dec_text,
            )

        @app.route('/login', methods=['GET', 'POST'])
        def login():
            if request.method == 'POST':
                password = request.form.get('password')
                origin_url = session.get('origin_url', '/')
                if sys_utils.verify_password("pifinder", password):
                    session['authenticated'] = True
                    session.pop('origin_url', None)
                    return redirect(origin_url)
                else:
                    return app.jinja_env.get_template('login.html').render(
                        title=gettext("Login"),
                        origin_url=origin_url, 
                        error_message=gettext("Invalid Password")
                    )
            else:
                origin_url = session.get('origin_url', '/')
                return app.jinja_env.get_template('login.html').render(
                    title=gettext("Login"),
                    origin_url=origin_url
                )

        @app.route('/remote')
        @auth_required
        def remote():
            return app.jinja_env.get_template('remote.html').render(
                title=_("Remote")
            )

        @app.route('/advanced')
        @auth_required
        def advanced():
            return app.jinja_env.get_template('advanced.html').render(
                title=_("Advanced")
            )

        @app.route('/network')
        @auth_required
        def network_page():
            show_new_form = request.args.get('add_new', 0)

            return app.jinja_env.get_template('network.html').render(
                title=_("Network"),
                net=self.network,
                show_new_form=show_new_form,
            )

        @app.route('/gps')
        @auth_required
        def gps_page():
            self.update_gps()
            show_new_form = request.args.get('add_new', 0)
            logger.debug(
                "/gps: %f, %f, %f ",
                self.lat or 0.0,
                self.lon or 0.0,
                self.altitude or 0.0,
            )

            return app.jinja_env.get_template('gps.html').render(
                title=_("GPS"),
                show_new_form=show_new_form,
                lat=self.lat,
                lon=self.lon,
                altitude=self.altitude,
            )

        @app.route('/gps/update', methods=['POST'])
        @auth_required
        def gps_update():
            lat = request.form.get('latitudeDecimal')
            lon = request.form.get('longitudeDecimal')
            altitude = request.form.get('altitude')
            date_req = request.form.get('date')
            time_req = request.form.get('time')
            gps_lock(float(lat), float(lon), float(altitude))
            if time_req and date_req:
                datetime_str = f"{date_req} {time_req}"
                datetime_obj = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M:%S")
                datetime_utc = datetime_obj.replace(tzinfo=timezone.utc)
                time_lock(datetime_utc)
            logger.debug(
                "GPS update: %s, %s, %s, %s, %s", lat, lon, altitude, date_req, time_req
            )
            time.sleep(1)  # give the gps thread a chance to update
            return redirect('/')

        @app.route('/locations')
        @auth_required
        def locations_page():
            show_new_form = request.args.get('add_new', 0)
            cfg = config.Config()
            cfg.load_config()  # Ensure config is loaded
            return app.jinja_env.get_template('locations.html').render(
                title=_("Locations"),
                locations=cfg.locations.locations,
                show_new_form=show_new_form,
            )

        @app.route('/locations/add', methods=['POST'])
        @auth_required
        def location_add():
            try:
                name = request.form.get('name').strip()
                lat = float(request.form.get('latitude'))
                lon = float(request.form.get('longitude'))
                altitude = float(request.form.get('altitude'))
                error_in_m = float(request.form.get('error_in_m', '0'))
                source = request.form.get('source', 'Manual Entry')

                # Server-side validation
                if not name:
                    raise ValueError(_("Location name is required"))
                if not (-90 <= lat <= 90):
                    raise ValueError(_("Latitude must be between -90 and 90"))
                if not (-180 <= lon <= 180):
                    raise ValueError(_("Longitude must be between -180 and 180"))
                if not (-1000 <= altitude <= 10000):
                    raise ValueError(_("Altitude must be between -1000 and 10000 meters"))
                if not (0 <= error_in_m <= 10000):
                    raise ValueError(_("Error must be between 0 and 10000 meters"))

                from PiFinder.locations import Location

                new_location = Location(
                    name=name,
                    latitude=lat,
                    longitude=lon,
                    height=altitude,
                    error_in_m=error_in_m,
                    source=source,
                )

                cfg = config.Config()
                cfg.load_config()
                cfg.locations.add_location(new_location)
                cfg.save_locations()

                self.ui_queue.put("reload_config")
                return redirect('/locations')

            except ValueError as e:
                return app.jinja_env.get_template('locations.html').render(
                    title=_("Locations"),
                    locations=config.Config().locations.locations,
                    show_new_form=1,
                    error_message=str(e),
                )

        # Continue with other routes...
        # (The rest of the routes would follow the same pattern of conversion from Bottle to Flask/Jinja2)

        @app.route('/key_callback', methods=['POST'])
        @auth_required
        def key_callback():
            button = request.json.get('button')
            if button in button_dict:
                self.key_callback(button_dict[button])
            else:
                self.key_callback(int(button))
            return jsonify({"message": "success"})

        @app.route('/image')
        def serve_pil_image():
            empty_img = Image.new(
                "RGB", (60, 30), color=(73, 109, 137)
            )  # create an image using PIL
            img = None
            try:
                img = self.shared_state.screen()
            except (BrokenPipeError, EOFError):
                pass

            if img is None:
                img = empty_img
            img_byte_arr = io.BytesIO()
            img.save(img_byte_arr, format="PNG")  # adjust for your image format
            img_byte_arr.seek(0)

            return send_file(img_byte_arr, mimetype='image/png')

        def gps_lock(lat: float = 50, lon: float = 3, altitude: float = 10):
            msg = (
                "fix",
                {
                    "lat": lat,
                    "lon": lon,
                    "altitude": altitude,
                    "error_in_m": 0,
                    "source": "WEB",
                    "lock": True,
                },
            )
            self.gps_queue.put(msg)
            logger.debug("Putting location msg on gps_queue: {msg}")

        def time_lock(time=datetime.now()):
            msg = ("time", time)
            self.gps_queue.put(msg)
            logger.debug("Putting time msg on gps_queue: {msg}")

        # Store the app reference for running
        self.app = app

    def run(self):
        # If the PiFinder software is running as a service
        # it can grab port 80.  If not, it needs to use 8080
        try:
            self.app.run(host="0.0.0.0", port=80, debug=True, passthrough_errors=True)
            logger.info("Webserver started on port 80")
        except (PermissionError, OSError, SystemExit) as e:
            logger.debug(f"Permission denied on port 80, trying 8080. {e}")
            try:
                self.app.run(host="0.0.0.0", port=8080, debug=True, passthrough_errors=True)
                logger.info("Webserver started on port 8080")
            except (Exception, SystemExit) as e2:
                logger.exception(f"Failed to start server on port 8080. {e2}")
                raise
        logger.debug("Webserver is running")

    def key_callback(self, key):
        self.keyboard_queue.put(key)

    def update_gps(self):
        """Update GPS information"""
        location = self.shared_state.location()

        if location.lock is True:
            self.gps_locked = True
            self.lat = location.lat
            self.lon = location.lon
            self.altitude = location.altitude
        else:
            self.gps_locked = False
            self.lat = None
            self.lon = None
            self.altitude = None


def run_server(
    keyboard_queue, ui_queue, gps_queue, shared_state, log_queue, verbose=False
):
    # MultiprocLogging.configurer(log_queue)
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s %(name)s:%(levelname)s:%(message)s'
    )
    server = Server2(keyboard_queue, ui_queue, gps_queue, shared_state, verbose)
    server.run()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PiFinder Flask Web Server with i18n support")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--port", type=int, default=8080, help="Port to run server on (default: 8080)")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to (default: 0.0.0.0)")
    
    args = parser.parse_args()
    
    # Setup basic logging for standalone mode
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format='%(asctime)s %(name)s:%(levelname)s:%(message)s'
    )
    
    logger.info("Starting PiFinder Server2 in standalone mode")
    
    # Create a single queue for command line testing
    test_queue = multiprocessing.Queue()
    
    # Create server with mock components
    server = Server2(
        keyboard_queue=test_queue,
        ui_queue=test_queue, 
        gps_queue=test_queue,
        shared_state=MockSharedState(),
        is_debug=args.debug
    )
    
    # Override the default port behavior for command line usage
    try:
        logger.info(f"Starting web server.")
        server.run()
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Server failed to start: {e}")
        sys.exit(1)
