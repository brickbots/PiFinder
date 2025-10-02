#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
UIModule Testing Framework

This module provides a comprehensive testing framework for all UIModule subclasses.
It dynamically discovers UIModule subclasses and tests their interface compliance.

Features:
- Dynamic discovery of all UIModule subclasses in PiFinder.ui package
- Automatic generation of parametrized tests for each discovered subclass
- Mock infrastructure for all UIModule dependencies (display, state, config, etc.)
- Tests for instantiation, lifecycle methods, key handlers, and core functionality
- Integration with pytest markers (smoke, unit, integration)

Usage:
Run with nox: `nox -s smoke_tests` or `nox -s unit_tests`
Run directly: `pytest tests/test_ui_module_framework.py`

The framework will automatically discover and test any new UIModule subclasses
added to the codebase, ensuring interface compliance and catching regressions.

Results Summary:
- Discovers 15 UIModule subclasses automatically
- Successfully tests basic interface compliance
- Some UIModules require additional mocking for full instantiation
- Framework serves as living documentation of UIModule interface
"""

import importlib
import inspect
import pkgutil
import pytest
import time
from unittest.mock import Mock, patch
from typing import Type, List
from PIL import Image

from PiFinder.ui.base import UIModule
import PiFinder.ui


class MockDisplayBase:
    """Mock DisplayBase class for testing UIModules"""

    # CRITICAL: These must be real numbers, not Mocks, as they're used in arithmetic
    resolution = (128, 128)
    resX = 128
    resY = 128
    titlebar_height = 17
    base_font_size = 10
    bold_font_size = 12
    small_font_size = 8
    large_font_size = 15
    huge_font_size = 35
    fov_res = 128  # Field of view resolution for UIAlign

    # Class-level attributes (accessed as display_class.attribute)
    device = Mock()
    device.mode = "RGB"
    device.display = Mock()
    # CRITICAL: Add real numeric properties that UIModules expect for arithmetic
    device.width = 128
    device.height = 128

    colors = Mock()
    colors.get = Mock(side_effect=lambda x: (x, 0, 0) if x > 0 else (0, 0, 0))
    colors.mode = "RGB"
    # Add red_image for help() methods that use make_red
    colors.red_image = Image.new("RGB", (128, 128), (255, 0, 0))

    # Create real fonts using PIL's default font instead of mocks
    from PIL import ImageFont

    default_font = ImageFont.load_default()

    # Use real Mock objects but ensure font properties are real PIL fonts
    fonts = Mock()
    # Bold font - use real font with numeric properties
    fonts.bold = Mock()
    fonts.bold.font = default_font
    fonts.bold.width = 8
    fonts.bold.height = 12
    # Icon font - use real font
    fonts.icon_bold_large = Mock()
    fonts.icon_bold_large.font = default_font
    fonts.icon_bold_large.width = 12
    fonts.icon_bold_large.height = 16
    # Base font - use real font
    fonts.base = Mock()
    fonts.base.font = default_font
    fonts.base.height = 10
    fonts.base.width = 6
    fonts.base.line_length = 20  # Line length for SpaceCalculatorFixed
    # Large font
    fonts.large = Mock()
    fonts.large.font = default_font
    fonts.large.height = 15
    fonts.large.width = 9
    # Huge font
    fonts.huge = Mock()
    fonts.huge.font = default_font
    fonts.huge.height = 35
    fonts.huge.width = 20

    def __init__(self):
        # Instance is also initialized with the class attributes
        self.colors = self.__class__.colors
        self.fonts = self.__class__.fonts
        # Create a real PIL image as the screen buffer
        self.screen_buffer = Image.new("RGB", self.resolution, (0, 0, 0))
        # Create a real PIL ImageDraw object
        from PIL import ImageDraw

        self.draw = ImageDraw.Draw(self.screen_buffer)
        # CRITICAL: Add real numeric values for display dimensions
        self.width = 128
        self.height = 128

    def message(self, text, timeout=None):
        """Mock message method that does nothing during testing"""
        pass


class MockSharedState:
    """Mock shared state object for testing UIModules"""

    def __init__(self):
        self._ui_state = Mock()
        self._ui_state.message_timeout = Mock(return_value=0)
        self._ui_state.show_fps = Mock(return_value=False)
        self._ui_state.set_message_timeout = Mock()
        # Add recent_list method for UIObjectList "recent" mode
        self._ui_state.recent_list = Mock(return_value=[])
        # Add GPS state for UIGPSStatus
        self._gps_state = {
            "fix_quality": 1,
            "num_sat": 8,
            "lat": 40.7128,
            "lon": -74.0060,
            "alt": 100.0,
            "utc_time": "12:00:00",
        }

    def ui_state(self):
        return self._ui_state

    def altaz_ready(self):
        return True

    def imu(self):
        return {
            "pos": [0.0, 0.0, 0.0],  # Position array for UIStatus
            "moving": False,
            "status": "OK",  # Status string for UIStatus
        }

    def solve_state(self):
        return True

    def solution(self):
        return {
            "solve_time": 12345,
            "cam_solve_time": 12345,
            "constellation": "Ursa Major",
            "solve_source": "CAM",  # Required by UIStatus
            "Matches": 15,  # Number of star matches for UIStatus
            "Az": 180.0,  # Azimuth for UIStatus
            "Alt": 45.0,  # Altitude for UIStatus
            "status": "PASS",  # Status for UIStatus
            "Roll": 0.0,  # Roll angle for UILog
            "ra": 180.0,  # Right ascension
            "dec": 45.0,  # Declination
            "RA": 180.0,  # Right ascension (uppercase for UIAlign)
            "Dec": 45.0,  # Declination (uppercase for UIAlign)
            "camera_solve": {
                "RA": 180.0,
                "Dec": 45.0,
                "Roll": 0.0,
            },
            "camera_center": {
                "RA": 180.0,
                "Dec": 45.0,
                "Roll": 0.0,
            },
        }

    def set_screen(self, screen):
        pass

    def gps(self):
        return self._gps_state

    def location(self):
        from unittest.mock import Mock

        location = Mock()
        location.lat = 40.7128
        location.lon = -74.0060
        location.alt = 100.0
        location.altitude = 100.0  # Required by UIStatus for formatting
        location.lock = True
        location.lock_type = 2  # GPS lock type for comparison operations
        location.last_gps_lock = "12:00:00"  # Required by UIStatus
        return location

    def datetime(self):
        from datetime import datetime

        return datetime.now()

    def power_state(self):
        return 1  # Return non-zero to indicate normal power state

    def sats(self):
        return (8, 12)  # Return tuple (connected_sats, visible_sats) for GPS testing

    def last_image_metadata(self):
        """Mock last_image_metadata for UIPreview"""
        import time

        return {
            "exposure_end": time.time() - 1.0,  # 1 second ago
            "exposure_time": 1.0,
            "gain": 100,
        }

    def local_datetime(self):
        """Mock local_datetime for UIStatus"""
        from datetime import datetime

        return datetime.now()


class MockCatalogFilter:
    """Mock catalog filter for testing"""

    def __init__(self):
        pass

    def is_dirty(self):
        """Mock is_dirty method"""
        return False

    def get_filter_objects(self, **kwargs):
        """Mock get_filter_objects method"""
        return []


class MockCatalogs:
    """Enhanced mock catalogs object for testing UIModules"""

    def __init__(self):
        # Create sample astronomical objects
        self.sample_objects = [
            MockAstronomicalObject("M31 - Andromeda Galaxy"),
            MockAstronomicalObject("M42 - Orion Nebula"),
            MockAstronomicalObject("M13 - Hercules Globular Cluster"),
            MockAstronomicalObject("NGC 2237 - Rosette Nebula"),
            MockAstronomicalObject("IC 434 - Horsehead Nebula"),
        ]
        # Add catalog filter for UIObjectList
        self.catalog_filter = MockCatalogFilter()

    def get_objects(self, **kwargs):
        """Mock method to return sample objects"""
        return self.sample_objects[:3]  # Return first 3 objects

    def search_objects(self, query: str):
        """Mock search method"""
        return [obj for obj in self.sample_objects if query.lower() in obj.name.lower()]

    def search_by_text(self, query: str):
        """Mock search_by_text method for UITextEntry"""
        return [obj for obj in self.sample_objects if query.lower() in obj.name.lower()]

    def filter_catalogs(self):
        """Mock filter_catalogs method for UIObjectList"""
        pass

    def get_catalogs(self, only_selected=False):
        """Mock get_catalogs method for UIObjectList"""
        mock_catalog = Mock()
        mock_catalog.catalog_code = "NGC"
        mock_catalog.get_filtered_objects = Mock(return_value=self.sample_objects[:2])
        mock_catalog.get_age = Mock(return_value=30.0)
        return [mock_catalog]

    def get_catalog_by_code(self, code):
        """Mock get_catalog_by_code method for UIObjectDetails"""
        mock_catalog = Mock()
        mock_catalog.catalog_code = code
        mock_catalog.name = f"Mock Catalog {code}"
        mock_catalog.description = f"Mock description for {code} catalog"
        return mock_catalog


class MockLocation:
    """Mock location object for testing"""

    def __init__(self, name: str, lat: float, lon: float):
        self.name = name
        self.lat = lat
        self.lon = lon
        self.alt = 100.0  # Default altitude


class MockLocations:
    """Mock locations container for testing"""

    def __init__(self):
        self.locations = [
            MockLocation("Test Location 1", 40.7128, -74.0060),  # NYC
            MockLocation("Test Location 2", 34.0522, -118.2437),  # LA
            MockLocation("Test Location 3", 51.5074, -0.1278),  # London
        ]


class MockEquipment:
    """Mock equipment for testing"""

    def __init__(self):
        self.active_telescope = Mock()
        self.active_telescope.name = "Test Telescope"
        self.active_telescope.focal_length = 1000  # mm
        self.active_eyepiece = Mock()
        self.active_eyepiece.name = "Test Eyepiece"
        self.active_eyepiece.focal_length = 25  # mm

    def calc_magnification(self):
        """Calculate magnification for testing"""
        if hasattr(self.active_telescope, "focal_length") and hasattr(
            self.active_eyepiece, "focal_length"
        ):
            return (
                self.active_telescope.focal_length / self.active_eyepiece.focal_length
            )
        return 40.0  # Default magnification

    def calc_tfov(self):
        """Calculate true field of view for testing"""
        return 1.0  # Default 1 degree TFOV

    def __str__(self):
        """String representation for testing"""
        return f"{self.active_telescope.name} + {self.active_eyepiece.name}"

    def cycle_eyepieces(self, direction):
        """Mock cycle_eyepieces method for testing"""
        pass  # Do nothing during testing


class MockAstronomicalObject:
    """Mock astronomical object for testing"""

    def __init__(self, name: str = "Test Object"):
        from unittest.mock import Mock

        self.name = name
        self.display_name = name
        self.ra = 180.0  # Right ascension in degrees
        self.dec = 45.0  # Declination in degrees
        self.magnitude = 8.5
        self.mag_str = "8.5"  # String version for UI display
        self.object_type = "Galaxy"
        self.obj_type = "GAL"  # Short form for UI display
        self.catalog = "NGC"
        self.catalog_code = "NGC"  # For cat_images
        self.id = 1234
        self.sequence = 1234
        self.const = "UMa"  # Constellation
        self.size = 10.0  # Size in arcminutes
        self.size_str = "10.0'"  # String version for UI display
        self.description = "Test astronomical object for UIModule testing"
        self.desc = self.description  # Alias
        self.names = [name, f"NGC{self.sequence}"]  # Alternative names
        self.image_name = None  # Will be set by cat_images if needed

        # Additional attributes for comprehensive testing
        self.ra_str = "12h00m00s"
        self.dec_str = "+45°00'00\""
        self.alt = 45.0  # Altitude
        self.az = 180.0  # Azimuth

        # Add mag object for UIObjectList
        self.mag = Mock()
        self.mag.filter_mag = 8.5

        # Add last_filtered_result for UIObjectDetails
        self.last_filtered_result = True


class MockConfig:
    """Enhanced mock config object for testing UIModules"""

    def __init__(self):
        # Default config values that UIModules commonly expect
        self._config_defaults = {
            "solve_pixel": (256, 256),
            "camera_type": "debug",
            "display_type": "ssd1351",
            "gps_type": "none",
            "screen_direction": 0,
            "mount_type": "altaz",
        }

        # Complex nested objects
        self.locations = MockLocations()
        self.equipment = MockEquipment()

    def get_option(self, option_name, default=None):
        """Mock get_option that returns sensible defaults for testing"""
        return self._config_defaults.get(option_name, default)


class UIModuleTestBase:
    """Base class for UIModule testing with common utilities"""

    @pytest.fixture
    def mock_display_class(self):
        """Fixture providing a mock display class"""
        return MockDisplayBase

    @pytest.fixture
    def mock_camera_image(self):
        """Fixture providing a mock camera image"""
        return Image.new("RGB", (128, 128))

    @pytest.fixture
    def mock_shared_state(self):
        """Fixture providing a mock shared state"""
        return MockSharedState()

    @pytest.fixture
    def mock_command_queues(self):
        """Fixture providing mock command queues"""
        from unittest.mock import Mock

        mock_queue = Mock()
        mock_queue.put = Mock()
        return {
            "camera": mock_queue,
            "solver": mock_queue,
            "gps": mock_queue,
            "imu": mock_queue,
            "integrator": mock_queue,
        }

    @pytest.fixture
    def mock_config_object(self):
        """Fixture providing a mock config object"""
        return MockConfig()

    @pytest.fixture
    def mock_catalogs(self):
        """Fixture providing a mock catalogs object"""
        return MockCatalogs()

    @pytest.fixture
    def mock_ui_callbacks(self):
        """Fixture providing mock UI callback functions"""
        return {
            "add_to_stack": Mock(),
            "remove_from_stack": Mock(),
            "jump_to_label": Mock(),
        }

    def create_comprehensive_item_definition(self, mock_catalogs):
        """Create a comprehensive item_definition that works for all UIModules"""
        # Get a sample astronomical object from our mock catalogs
        sample_object = mock_catalogs.sample_objects[0]
        sample_object_list = mock_catalogs.sample_objects

        return {
            # For UITextMenu and UILocationList
            "items": [
                {"name": "Test Menu Item 1", "action": "test_action_1"},
                {"name": "Test Menu Item 2", "action": "test_action_2"},
                {"name": "Test Menu Item 3", "action": "test_action_3"},
            ],
            "select": "single",
            "start_index": 0,
            "name": "Test Menu",
            # For UILog and UIObjectDetails
            "object": sample_object,
            "object_list": sample_object_list,
            # For UIObjectList - specify object source type
            "objects": "custom",  # Use custom mode so we can provide object_list
            "value": "NGC",  # For catalog mode in UIObjectList
            # Generic attributes that might be needed
            "title": "Test UI Module",
            "description": "Test description for UI module",
        }

    def create_ui_module_instance(
        self,
        ui_module_class: Type[UIModule],
        mock_display_class,
        mock_camera_image,
        mock_shared_state,
        mock_command_queues,
        mock_config_object,
        mock_catalogs,
        mock_ui_callbacks,
        item_definition=None,
    ):
        """Helper method to create a UIModule instance with all required mocks"""
        if item_definition is None:
            item_definition = self.create_comprehensive_item_definition(mock_catalogs)

        try:
            # Minimal patches - let PIL work normally with our dummy screen buffer
            with patch.multiple(
                UIModule, message=lambda self, text, timeout=None: None
            ):
                instance = ui_module_class(
                    display_class=mock_display_class,
                    camera_image=mock_camera_image,
                    shared_state=mock_shared_state,
                    command_queues=mock_command_queues,
                    config_object=mock_config_object,
                    catalogs=mock_catalogs,
                    item_definition=item_definition,
                    add_to_stack=mock_ui_callbacks["add_to_stack"],
                    remove_from_stack=mock_ui_callbacks["remove_from_stack"],
                    jump_to_label=mock_ui_callbacks["jump_to_label"],
                )

            return instance
        except Exception as e:
            pytest.fail(f"Failed to instantiate {ui_module_class.__name__}: {e}")


class UIModuleDiscovery:
    """Utility class for discovering UIModule subclasses"""

    @staticmethod
    def discover_ui_modules() -> List[Type[UIModule]]:
        """Discover all UIModule subclasses in the PiFinder.ui package"""
        ui_modules = []

        # Set up translation function for modules that need it
        import builtins

        if not hasattr(builtins, "_"):

            def translation_func(text: str) -> str:
                return text

            builtins._ = translation_func  # type: ignore[attr-defined]

        # Walk through all modules in PiFinder.ui package
        for importer, modname, ispkg in pkgutil.iter_modules(
            PiFinder.ui.__path__, PiFinder.ui.__name__ + "."
        ):
            if modname.endswith(".base"):  # Skip the base module itself
                continue

            try:
                module = importlib.import_module(modname)

                # Find all classes in the module that inherit from UIModule
                for name, obj in inspect.getmembers(module, inspect.isclass):
                    if (
                        issubclass(obj, UIModule)
                        and obj != UIModule
                        and obj.__module__ == modname
                    ):
                        ui_modules.append(obj)

            except ImportError as e:
                print(f"Warning: Could not import {modname}: {e}")
                continue
            except NameError as e:
                print(f"Warning: NameError in {modname}: {e}")
                continue
            except Exception as e:
                print(f"Warning: Error importing {modname}: {e}")
                continue

        return ui_modules


class TestUIModuleFramework(UIModuleTestBase):
    """Main test class for UIModule framework"""

    @pytest.fixture(scope="class")
    def discovered_ui_modules(self):
        """Fixture that discovers all UIModule subclasses"""
        return UIModuleDiscovery.discover_ui_modules()

    @pytest.mark.smoke
    def test_ui_module_discovery(self, discovered_ui_modules):
        """Test that we can discover UIModule subclasses"""
        assert len(discovered_ui_modules) > 0, "No UIModule subclasses discovered"

        # Verify they're all actually UIModule subclasses
        for ui_module in discovered_ui_modules:
            assert issubclass(
                ui_module, UIModule
            ), f"{ui_module.__name__} is not a UIModule subclass"

    @pytest.mark.parametrize(
        "ui_module_class",
        UIModuleDiscovery.discover_ui_modules(),
        ids=lambda cls: cls.__name__,
    )
    class TestUIModuleInstantiation(UIModuleTestBase):
        """Test UIModule instantiation for all discovered subclasses"""

        @pytest.mark.smoke
        def test_can_instantiate(
            self,
            ui_module_class,
            mock_display_class,
            mock_camera_image,
            mock_shared_state,
            mock_command_queues,
            mock_config_object,
            mock_catalogs,
            mock_ui_callbacks,
        ):
            """Test that each UIModule subclass can be instantiated"""
            instance = self.create_ui_module_instance(
                ui_module_class,
                mock_display_class,
                mock_camera_image,
                mock_shared_state,
                mock_command_queues,
                mock_config_object,
                mock_catalogs,
                mock_ui_callbacks,
            )

            assert instance is not None
            assert isinstance(instance, UIModule)
            assert isinstance(instance, ui_module_class)

    @pytest.mark.parametrize(
        "ui_module_class",
        UIModuleDiscovery.discover_ui_modules(),
        ids=lambda cls: cls.__name__,
    )
    class TestUIModuleLifecycle(UIModuleTestBase):
        """Test UIModule lifecycle methods for all discovered subclasses"""

        @pytest.mark.unit
        def test_active_method(
            self,
            ui_module_class,
            mock_display_class,
            mock_camera_image,
            mock_shared_state,
            mock_command_queues,
            mock_config_object,
            mock_catalogs,
            mock_ui_callbacks,
        ):
            """Test that active() method can be called without errors"""
            instance = self.create_ui_module_instance(
                ui_module_class,
                mock_display_class,
                mock_camera_image,
                mock_shared_state,
                mock_command_queues,
                mock_config_object,
                mock_catalogs,
                mock_ui_callbacks,
            )

            try:
                instance.active()
            except Exception as e:
                pytest.fail(
                    f"{ui_module_class.__name__}.active() raised {type(e).__name__}: {e}"
                )
            try:
                # Call update after action
                instance.update()
            except Exception as e:
                pytest.fail(
                    f"{ui_module_class.__name__}.active() + update() raised {type(e).__name__}: {e}"
                )

        @pytest.mark.unit
        def test_inactive_method(
            self,
            ui_module_class,
            mock_display_class,
            mock_camera_image,
            mock_shared_state,
            mock_command_queues,
            mock_config_object,
            mock_catalogs,
            mock_ui_callbacks,
        ):
            """Test that inactive() method can be called without errors"""
            instance = self.create_ui_module_instance(
                ui_module_class,
                mock_display_class,
                mock_camera_image,
                mock_shared_state,
                mock_command_queues,
                mock_config_object,
                mock_catalogs,
                mock_ui_callbacks,
            )

            try:
                instance.inactive()
            except Exception as e:
                pytest.fail(
                    f"{ui_module_class.__name__}.inactive() raised {type(e).__name__}: {e}"
                )

        @pytest.mark.unit
        def test_help_method(
            self,
            ui_module_class,
            mock_display_class,
            mock_camera_image,
            mock_shared_state,
            mock_command_queues,
            mock_config_object,
            mock_catalogs,
            mock_ui_callbacks,
        ):
            """Test that help() method can be called without errors"""
            instance = self.create_ui_module_instance(
                ui_module_class,
                mock_display_class,
                mock_camera_image,
                mock_shared_state,
                mock_command_queues,
                mock_config_object,
                mock_catalogs,
                mock_ui_callbacks,
            )

            try:
                result = instance.help()
                # Help should return None or a list of Images
                assert result is None or (
                    isinstance(result, list)
                    and all(isinstance(img, Image.Image) for img in result)
                )
            except Exception as e:
                pytest.fail(
                    f"{ui_module_class.__name__}.help() raised {type(e).__name__}: {e}"
                )

    @pytest.mark.parametrize(
        "ui_module_class",
        UIModuleDiscovery.discover_ui_modules(),
        ids=lambda cls: cls.__name__,
    )
    class TestUIModuleCore(UIModuleTestBase):
        """Test core UIModule methods for all discovered subclasses"""

        @pytest.mark.unit
        def test_update_method(
            self,
            ui_module_class,
            mock_display_class,
            mock_camera_image,
            mock_shared_state,
            mock_command_queues,
            mock_config_object,
            mock_catalogs,
            mock_ui_callbacks,
        ):
            """Test that update() method can be called without errors"""
            instance = self.create_ui_module_instance(
                ui_module_class,
                mock_display_class,
                mock_camera_image,
                mock_shared_state,
                mock_command_queues,
                mock_config_object,
                mock_catalogs,
                mock_ui_callbacks,
            )

            try:
                for _ in range(5):
                    instance.update()
            except Exception as e:
                pytest.fail(
                    f"{ui_module_class.__name__}.update() raised {type(e).__name__}: {e}"
                )

        @pytest.mark.unit
        def test_clear_screen_method(
            self,
            ui_module_class,
            mock_display_class,
            mock_camera_image,
            mock_shared_state,
            mock_command_queues,
            mock_config_object,
            mock_catalogs,
            mock_ui_callbacks,
        ):
            """Test that clear_screen() method can be called without errors"""
            instance = self.create_ui_module_instance(
                ui_module_class,
                mock_display_class,
                mock_camera_image,
                mock_shared_state,
                mock_command_queues,
                mock_config_object,
                mock_catalogs,
                mock_ui_callbacks,
            )

            try:
                instance.clear_screen()
            except Exception as e:
                pytest.fail(
                    f"{ui_module_class.__name__}.clear_screen() raised {type(e).__name__}: {e}"
                )

        @pytest.mark.unit
        def test_message_method(
            self,
            ui_module_class,
            mock_display_class,
            mock_camera_image,
            mock_shared_state,
            mock_command_queues,
            mock_config_object,
            mock_catalogs,
            mock_ui_callbacks,
        ):
            """Test that message() method can be called without errors"""
            instance = self.create_ui_module_instance(
                ui_module_class,
                mock_display_class,
                mock_camera_image,
                mock_shared_state,
                mock_command_queues,
                mock_config_object,
                mock_catalogs,
                mock_ui_callbacks,
            )

            try:
                instance.message("Test message", timeout=0.1)
            except Exception as e:
                pytest.fail(
                    f"{ui_module_class.__name__}.message() raised {type(e).__name__}: {e}"
                )

        @pytest.mark.unit
        def test_screen_update_method(
            self,
            ui_module_class,
            mock_display_class,
            mock_camera_image,
            mock_shared_state,
            mock_command_queues,
            mock_config_object,
            mock_catalogs,
            mock_ui_callbacks,
        ):
            """Test that screen_update() method can be called without errors"""
            instance = self.create_ui_module_instance(
                ui_module_class,
                mock_display_class,
                mock_camera_image,
                mock_shared_state,
                mock_command_queues,
                mock_config_object,
                mock_catalogs,
                mock_ui_callbacks,
            )

            try:
                instance.screen_update()
            except Exception as e:
                pytest.fail(
                    f"{ui_module_class.__name__}.screen_update() raised {type(e).__name__}: {e}"
                )

    @pytest.mark.parametrize(
        "ui_module_class",
        UIModuleDiscovery.discover_ui_modules(),
        ids=lambda cls: cls.__name__,
    )
    class TestUIModuleKeyHandlers(UIModuleTestBase):
        """Test key handler methods for all discovered subclasses"""

        KEY_METHODS = [
            "key_up",
            "key_down",
            "key_left",
            "key_right",
            "key_plus",
            "key_minus",
            "key_square",
            "key_long_up",
            "key_long_down",
            "key_long_right",
        ]

        @pytest.mark.parametrize("key_method", KEY_METHODS)
        @pytest.mark.unit
        def test_key_methods(
            self,
            ui_module_class,
            key_method,
            mock_display_class,
            mock_camera_image,
            mock_shared_state,
            mock_command_queues,
            mock_config_object,
            mock_catalogs,
            mock_ui_callbacks,
        ):
            """Test that all key handler methods can be called without errors"""
            instance = self.create_ui_module_instance(
                ui_module_class,
                mock_display_class,
                mock_camera_image,
                mock_shared_state,
                mock_command_queues,
                mock_config_object,
                mock_catalogs,
                mock_ui_callbacks,
            )

            # Only patch update methods that might cause recursion, let PIL work normally
            with (
                patch.object(instance, "update", lambda force=False: None),
                patch.object(instance, "screen_update", lambda: None),
            ):
                try:
                    method = getattr(instance, key_method)
                    result = method()

                    # key_left should return a boolean
                    if key_method == "key_left":
                        assert isinstance(result, bool) or result is None

                except Exception as e:
                    pytest.fail(
                        f"{ui_module_class.__name__}.{key_method}() raised {type(e).__name__}: {e}"
                    )

                try:
                    # Call update after action
                    instance.update()
                except Exception as e:
                    pytest.fail(
                        f"{ui_module_class.__name__}.{key_method}() + update() raised {type(e).__name__}: {e}"
                    )
                

        @pytest.mark.unit
        def test_key_number_method(
            self,
            ui_module_class,
            mock_display_class,
            mock_camera_image,
            mock_shared_state,
            mock_command_queues,
            mock_config_object,
            mock_catalogs,
            mock_ui_callbacks,
        ):
            """Test that key_number() method can be called without errors"""
            instance = self.create_ui_module_instance(
                ui_module_class,
                mock_display_class,
                mock_camera_image,
                mock_shared_state,
                mock_command_queues,
                mock_config_object,
                mock_catalogs,
                mock_ui_callbacks,
            )

            try:
                for number in range(10):
                    instance.key_number(number)
            except Exception as e:
                pytest.fail(
                    f"{ui_module_class.__name__}.key_number() raised {type(e).__name__}: {e}"
                )

    @pytest.mark.parametrize(
        "ui_module_class",
        UIModuleDiscovery.discover_ui_modules(),
        ids=lambda cls: cls.__name__,
    )
    class TestUIModuleDisplay(UIModuleTestBase):
        """Test display-related methods for all discovered subclasses"""

        @pytest.mark.unit
        def test_cycle_display_mode(
            self,
            ui_module_class,
            mock_display_class,
            mock_camera_image,
            mock_shared_state,
            mock_command_queues,
            mock_config_object,
            mock_catalogs,
            mock_ui_callbacks,
        ):
            """Test that cycle_display_mode() method can be called without errors"""
            instance = self.create_ui_module_instance(
                ui_module_class,
                mock_display_class,
                mock_camera_image,
                mock_shared_state,
                mock_command_queues,
                mock_config_object,
                mock_catalogs,
                mock_ui_callbacks,
            )

            try:
                instance.cycle_display_mode()
            except Exception as e:
                pytest.fail(
                    f"{ui_module_class.__name__}.cycle_display_mode() raised {type(e).__name__}: {e}"
                )


@pytest.mark.smoke
def test_framework_meta():
    """Meta test to ensure the testing framework itself works"""
    discovered_modules = UIModuleDiscovery.discover_ui_modules()
    assert (
        len(discovered_modules) > 0
    ), "Framework should discover at least one UIModule"

    # Test that our mock classes can be instantiated
    mock_display = MockDisplayBase()
    mock_state = MockSharedState()
    mock_catalogs = MockCatalogs()
    mock_config = MockConfig()

    assert mock_display is not None
    assert mock_state is not None
    assert mock_catalogs is not None
    assert mock_config is not None
