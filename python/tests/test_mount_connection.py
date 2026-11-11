"""USB and WiFi mount connections: the driver properties that PiFinder sets,
the settings and presets, and the Mount web form."""

import time
from pathlib import Path
from queue import Queue
from unittest.mock import Mock

import jinja2
import pytest

from PiFinder import indi_drivers, mount_settings
from PiFinder.mount_settings import MountSettings, Preset
from PiFinder.indi_client import IndiProperty
from PiFinder.mountcontrol_indi import MountControlIndi, split_address
from PiFinder.mountcontrol_interface import MountControlPhases
from PiFinder.state import SharedStateObj

pytestmark = pytest.mark.unit

VIEWS = Path(__file__).parent.parent / "views"


class FakeClient:
    """The part of IndiClient that _configure_connection uses."""

    def __init__(self, props: dict[str, dict]):
        self.props = {
            name: IndiProperty("Mount", name, "switch", elements=dict(elements))
            for name, elements in props.items()
        }
        self.sent: list[tuple] = []

    def get_property(self, device, name):
        return self.props.get(name)

    def get_value(self, device, name, element):
        prop = self.props.get(name)
        return None if prop is None else prop.elements.get(element)

    def wait_property(self, device, name, timeout):
        return self.props.get(name)

    def set_switch(self, device, name, element, on=True):
        self.sent.append(("switch", name, element))
        return True

    def set_text(self, device, name, values):
        self.sent.append(("text", name, values))
        return True


def _mount(client, connection, address="", port="/dev/ttyACM0", baud=115200):
    mount = MountControlIndi(
        Queue(),
        Queue(),
        Mock(spec=SharedStateObj),
        None,
        MountSettings(True, "SAL-33", connection, port, baud, address),
    )
    mount.client = client
    mount.device = "Mount"
    return mount


TCP_DRIVER = {
    "CONNECTION_MODE": {"CONNECTION_SERIAL": True, "CONNECTION_TCP": False},
    "DEVICE_PORT": {"PORT": "/dev/ttyUSB0"},
    "DEVICE_BAUD_RATE": {"9600": True, "115200": False},
    "DEVICE_ADDRESS": {"ADDRESS": "", "PORT": ""},
}


def test_usb_sets_serial_mode_port_and_baud():
    client = FakeClient(TCP_DRIVER)
    assert _mount(client, "usb")._configure_connection()
    assert client.sent == [
        ("switch", "CONNECTION_MODE", "CONNECTION_SERIAL"),
        ("text", "DEVICE_PORT", {"PORT": "/dev/ttyACM0"}),
        ("switch", "DEVICE_BAUD_RATE", "115200"),
    ]


def test_wifi_sets_tcp_mode_and_address():
    client = FakeClient(TCP_DRIVER)
    assert _mount(client, "wifi", "192.168.0.1:9999")._configure_connection()
    assert client.sent == [
        ("switch", "CONNECTION_MODE", "CONNECTION_TCP"),
        ("text", "DEVICE_ADDRESS", {"ADDRESS": "192.168.0.1", "PORT": "9999"}),
    ]


def test_wifi_empty_address_keeps_driver_default():
    client = FakeClient(TCP_DRIVER)
    assert _mount(client, "wifi", "")._configure_connection()
    assert client.sent == [("switch", "CONNECTION_MODE", "CONNECTION_TCP")]


def test_wifi_host_only_keeps_driver_port():
    client = FakeClient(TCP_DRIVER)
    assert _mount(client, "wifi", "10.42.0.23")._configure_connection()
    assert client.sent[-1] == ("text", "DEVICE_ADDRESS", {"ADDRESS": "10.42.0.23"})


def test_wifi_fails_for_driver_without_network():
    client = FakeClient({"DEVICE_PORT": {"PORT": "/dev/ttyUSB0"}})
    mount = _mount(client, "wifi", "192.168.0.1:9999")
    assert not mount._configure_connection()
    assert mount.console_queue.get_nowait()[0] == "WARNING"
    assert client.sent == []


@pytest.mark.parametrize(
    "address, expected",
    [
        ("192.168.0.1:9999", ("192.168.0.1", "9999")),
        ("onstep.local", ("onstep.local", "")),
        (":11880", ("", "11880")),
        ("", ("", "")),
    ],
)
def test_split_address(address, expected):
    assert split_address(address) == expected


# The Mount web form


@pytest.fixture
def drivers(tmp_path, monkeypatch):
    (tmp_path / "drivers.xml").write_text(
        '<driversList><devGroup group="Telescopes">'
        '<device label="SAL-33" manufacturer="MLAstro">'
        '<driver name="LX200 OnStep">indi_lx200_OnStep</driver></device>'
        "</devGroup></driversList>"
    )
    monkeypatch.setenv("INDI_DATA_DIR", str(tmp_path))


def _form(**values):
    form = {
        "enabled": "on",
        "model": "SAL-33",
        "connection": "wifi",
        "port": "/dev/ttyUSB0",
        "baud": "9600",
        "address": " 192.168.0.1:9999 ",
    }
    form.update(values)
    return {k: v for k, v in form.items() if v is not None}


def test_form_to_settings(drivers):
    assert mount_settings.settings_from_form(_form()) == MountSettings(
        enabled=True,
        model="SAL-33",
        connection="wifi",
        port="/dev/ttyUSB0",
        baud=9600,
        address="192.168.0.1:9999",
    )
    off = mount_settings.settings_from_form(_form(enabled=None, model=""))
    assert off.enabled is False
    assert off.model == ""
    by_id = "/dev/serial/by-id/usb-Silicon_Labs_CP2102_0001-if00-port0"
    assert mount_settings.settings_from_form(_form(port=by_id)).port == by_id


@pytest.mark.parametrize(
    "values",
    [
        {"connection": "bluetooth"},
        {"model": "No Such Mount"},
        {"port": "/etc/passwd"},
        {"port": "/dev/ttyUSB0; reboot"},
        {"baud": "1234"},
        {"baud": "fast"},
        {"address": "bad host:9999"},
        {"address": "192.168.0.1:70000"},
        {"address": "192.168.0.1:port"},
    ],
)
def test_form_errors(drivers, values):
    with pytest.raises(ValueError):
        mount_settings.settings_from_form(_form(**values))


def test_wifi_clients_from_leases(tmp_path):
    (tmp_path / "dnsmasq-wlan0.leases").write_text(
        "1794400000 aa:bb:cc:dd:ee:ff 10.42.0.23 OnStep-SWS 01:aa:bb\n"
        "1794400000 11:22:33:44:55:66 10.42.0.24 * *\n"
        "garbage\n"
    )
    clients = mount_settings.wifi_clients(str(tmp_path / "dnsmasq-*.leases"))
    assert clients == [
        mount_settings.WifiClient("OnStep-SWS", "10.42.0.23"),
        mount_settings.WifiClient("", "10.42.0.24"),
    ]
    assert mount_settings.wifi_clients(str(tmp_path / "none-*.leases")) == []


def test_mount_template_renders():
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(VIEWS)))
    env.globals["_"] = lambda s: s
    html = env.get_template("mount.html").render(
        title="Mount",
        values={
            "enabled": True,
            "model": "SAL-33",
            "connection": "wifi",
            "port": "/dev/ttyACM0",
            "baud": 115200,
            "address": "10.42.0.23:9999",
        },
        manufacturers={"MLAstro": ["SAL-33"], "OnStep": ["LX200 OnStep"]},
        usb_ports=mount_settings.USB_PORTS,
        baud_rates=mount_settings.BAUD_RATES,
        presets=mount_settings.presets(FakeConfig()),
        clients=[mount_settings.WifiClient("OnStep-SWS", "10.42.0.23")],
        error_message=None,
        status_message="Settings applied",
    )
    assert '<option value="SAL-33" selected>' in html
    assert 'value="wifi" id="connection_wifi" checked' in html
    assert '<option value="115200" selected>' in html
    assert "OnStep-SWS (10.42.0.23)" in html
    assert "/mount/update" in html
    assert "Settings applied" in html
    assert "OnStep WiFi" in html and "(built-in)" in html


class FakeConfig:
    """The get_option/set_option part of Config, in memory."""

    def __init__(self, options=None):
        self.options = dict(options or {})

    def get_option(self, option, default=None):
        return self.options.get(option, default)

    def set_option(self, option, value):
        self.options[option] = value


def test_settings_round_trip_through_config():
    cfg = FakeConfig()
    settings = MountSettings(True, "SAL-33", "wifi", "/dev/ttyACM0", 115200, "x:1")
    for option, value in settings.options().items():
        cfg.set_option(option, value)
    assert MountSettings.from_config(cfg) == settings
    assert MountSettings.from_config(FakeConfig()) == MountSettings()


def test_builtin_presets_use_installed_models():
    # Each built-in preset names a model label that INDI ships.
    labels = {
        "LX200 OnStep",
        "AZ-GTi Alt-Az WiFi",
        indi_drivers.SIMULATOR,
    }
    assert {p.model for p in mount_settings.BUILTIN_PRESETS} <= labels


def test_user_preset_overrides_builtin_and_delete_restores_it():
    cfg = FakeConfig()
    builtin = mount_settings.find_preset(cfg, "OnStep WiFi")
    assert builtin.builtin and builtin.address == "192.168.0.1:9999"

    mine = MountSettings(True, "SAL-33", "wifi", address="10.42.0.23:9998")
    mount_settings.save_preset(cfg, "onstep wifi", mine)
    override = mount_settings.find_preset(cfg, "OnStep WiFi")
    assert not override.builtin
    assert (override.model, override.address) == ("SAL-33", "10.42.0.23:9998")
    names = [p.name.lower() for p in mount_settings.presets(cfg)]
    assert names.count("onstep wifi") == 1

    # Saving again under the same name replaces it.
    mount_settings.save_preset(cfg, "OnStep WiFi", mine)
    assert len(cfg.options[mount_settings.PRESETS_OPTION]) == 1

    mount_settings.delete_preset(cfg, "ONSTEP WIFI")
    assert mount_settings.find_preset(cfg, "OnStep WiFi").builtin


def test_preset_apply_keeps_enabled():
    preset = Preset("Mine", "SAL-33", "wifi", address="10.42.0.23")
    off = preset.apply(MountSettings(enabled=False))
    assert off.enabled is False
    assert (off.model, off.connection, off.address) == ("SAL-33", "wifi", "10.42.0.23")


@pytest.mark.parametrize("name", ["", "   ", "x" * 41])
def test_preset_name_checked(name):
    with pytest.raises(ValueError):
        mount_settings.save_preset(FakeConfig(), name, MountSettings())


def test_bad_user_preset_in_config_is_skipped():
    cfg = FakeConfig({mount_settings.PRESETS_OPTION: [{"name": "x", "bogus": 1}]})
    assert len(mount_settings.presets(cfg)) == len(mount_settings.BUILTIN_PRESETS)


def test_reload_config_command_reloads_settings():
    settings = [MountSettings(enabled=False)]
    mount = MountControlIndi(
        Queue(),
        Queue(),
        Mock(spec=SharedStateObj),
        None,
        settings[0],
        load_settings=lambda: settings[0],
    )
    assert mount.state.name == "MOUNT_UNKNOWN"
    settings[0] = MountSettings(enabled=True, model="SAL-33")
    for _step in mount._process_command({"type": "reload_config"}):
        pass
    assert mount.settings.model == "SAL-33"
    assert mount.state.name == "MOUNT_INIT_TELESCOPE"
    assert mount.console_queue.get_nowait()[0] == "MOUNT"


def _slewing_mount(target):
    mount = _mount(FakeClient({}), "usb")
    mount._slewing = True
    mount._slew_busy_seen = True
    mount._slew_target = target
    return mount


def test_slew_end_at_target_is_target_reached():
    mount = _slewing_mount((84.0, 22.0))
    mount._mount_current_position(84.001, 22.0, "Ok")
    assert mount.target_reached
    assert mount.console_queue.empty()


def test_slew_end_far_from_target_is_interrupted():
    """The driver ended the slew elsewhere: no target reached, so REFINE
    does not sync to a wrong place."""
    mount = _slewing_mount((84.0, 22.0))
    mount.state = MountControlPhases.MOUNT_TARGET_ACQUISITION_MOVE
    mount._mount_current_position(325.8, 22.0, "Ok")
    assert not mount.target_reached
    assert mount.state == MountControlPhases.MOUNT_STOPPED
    assert mount.console_queue.get_nowait() == ["WARNING", "Goto interrupted"]


def test_location_waits_while_the_mount_slews():
    mount = _mount(FakeClient({}), "usb")
    mount.sync_mount_location_and_time = Mock()
    mount._slewing = True
    mount._slew_start = time.time()
    mount.periodic_mount_task()
    mount.sync_mount_location_and_time.assert_not_called()
    mount._slewing = False
    mount.current_time = 0.0
    mount.periodic_mount_task()
    mount.sync_mount_location_and_time.assert_called_once()
