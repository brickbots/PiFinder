"""Mount control settings: the config options, the presets, the web form
check, and the devices on the PiFinder access point."""

import glob
import re
from dataclasses import asdict, dataclass, replace
from typing import TYPE_CHECKING, Any, Mapping, Optional

import PiFinder.i18n  # noqa: F401
from PiFinder import indi_drivers

if TYPE_CHECKING:

    def _(a) -> Any:
        return a


CONNECTIONS = ("usb", "wifi")
BAUD_RATES = (9600, 19200, 38400, 57600, 115200)
USB_PORTS = ("/dev/ttyUSB0", "/dev/ttyUSB1", "/dev/ttyACM0", "/dev/ttyACM1")
# Config option of each MountSettings field.
OPTIONS = {
    "enabled": "mount_control",
    "model": "mount_control_model",
    "connection": "mount_control_connection",
    "port": "mount_control_port",
    "baud": "mount_control_baud",
    "address": "mount_control_address",
}
PRESETS_OPTION = "mount_control_presets"


@dataclass(frozen=True)
class MountSettings:
    enabled: bool = False
    model: str = ""
    connection: str = "usb"
    port: str = "/dev/ttyUSB0"
    baud: int = 9600
    address: str = ""

    @classmethod
    def from_config(cls, cfg) -> "MountSettings":
        default = cls()
        return cls(
            **{
                field: cfg.get_option(option, getattr(default, field))
                for field, option in OPTIONS.items()
            }
        )

    def as_dict(self) -> dict:
        return asdict(self)

    def options(self) -> dict:
        return {OPTIONS[field]: value for field, value in asdict(self).items()}


@dataclass(frozen=True)
class Preset:
    """A named mount setup. A preset does not turn mount control on or off."""

    name: str
    model: str
    connection: str
    port: str = "/dev/ttyUSB0"
    baud: int = 9600
    address: str = ""
    builtin: bool = False

    def apply(self, settings: MountSettings) -> MountSettings:
        return replace(
            settings,
            model=self.model,
            connection=self.connection,
            port=self.port,
            baud=self.baud,
            address=self.address,
        )


# Defaults of common mounts. A user preset with the same name overrides one.
BUILTIN_PRESETS = (
    Preset(
        "OnStep WiFi", "LX200 OnStep", "wifi", address="192.168.0.1:9999", builtin=True
    ),
    Preset("OnStep USB", "LX200 OnStep", "usb", port="/dev/ttyUSB0", builtin=True),
    Preset(
        "AZ-GTi WiFi",
        "AZ-GTi Alt-Az WiFi",
        "wifi",
        address="192.168.4.1:11880",
        builtin=True,
    ),
    Preset("Simulator", "Telescope Simulator", "usb", builtin=True),
)


def presets(cfg) -> list[Preset]:
    """The built-in presets with the user presets over them, by name."""
    merged = {p.name.lower(): p for p in BUILTIN_PRESETS}
    for raw in cfg.get_option(PRESETS_OPTION, []) or []:
        try:
            preset = Preset(**{**raw, "builtin": False})
        except TypeError:
            continue
        merged[preset.name.lower()] = preset
    return list(merged.values())


def find_preset(cfg, name: str) -> Optional[Preset]:
    for preset in presets(cfg):
        if preset.name.lower() == name.strip().lower():
            return preset
    return None


def save_preset(cfg, name: str, settings: MountSettings) -> Preset:
    """Store settings as a user preset. Same name: replace it."""
    name = name.strip()
    if not name or len(name) > 40:
        raise ValueError(_("Preset name must have 1 to 40 characters"))
    preset = Preset(
        name,
        settings.model,
        settings.connection,
        settings.port,
        settings.baud,
        settings.address,
    )
    user = [
        raw
        for raw in cfg.get_option(PRESETS_OPTION, []) or []
        if str(raw.get("name", "")).lower() != name.lower()
    ]
    record = asdict(preset)
    del record["builtin"]
    cfg.set_option(PRESETS_OPTION, user + [record])
    return preset


def delete_preset(cfg, name: str) -> None:
    """Delete a user preset. A built-in preset with that name shows again."""
    user = cfg.get_option(PRESETS_OPTION, []) or []
    cfg.set_option(
        PRESETS_OPTION,
        [raw for raw in user if str(raw.get("name", "")).lower() != name.lower()],
    )


# NetworkManager runs dnsmasq for the PiFinder access point ("shared" mode).
LEASE_GLOB = "/var/lib/NetworkManager/dnsmasq-*.leases"

_PORT_RE = re.compile(r"^/dev/(tty(USB|ACM)[0-9]+|serial/by-(id|path)/[\w:.+@-]+)$")
_HOST_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.-]{0,252})$")


@dataclass(frozen=True)
class WifiClient:
    hostname: str
    ip: str


def wifi_clients(lease_glob: str = LEASE_GLOB) -> list[WifiClient]:
    """Devices with a DHCP lease from the PiFinder access point, for
    example a mount controller in station mode. Empty if there are none or
    the lease files cannot be read."""
    clients = []
    for path in sorted(glob.glob(lease_glob)):
        try:
            with open(path) as f:
                lines = f.readlines()
        except OSError:
            continue
        for line in lines:
            # expiry mac ip hostname client-id
            fields = line.split()
            if len(fields) >= 4:
                hostname = "" if fields[3] == "*" else fields[3]
                clients.append(WifiClient(hostname=hostname, ip=fields[2]))
    return clients


def check_address(address: str) -> str:
    """Return the normalised "host:port" (either part may be empty), or
    raise ValueError."""
    address = address.strip()
    if not address:
        return ""
    host, sep, port = address.rpartition(":")
    if not sep:
        host, port = address, ""
    if host and not _HOST_RE.match(host):
        raise ValueError(_("Address must be a host name or an IP address"))
    if port and not (port.isdigit() and 0 < int(port) < 65536):
        raise ValueError(_("Port must be a number from 1 to 65535"))
    return f"{host}:{port}" if port else host


def settings_from_form(form: Mapping[str, str]) -> MountSettings:
    """The settings from the Mount form. Raises ValueError with a message
    for the user."""
    connection = form.get("connection", "usb")
    if connection not in CONNECTIONS:
        raise ValueError(_("Unknown connection"))
    model = form.get("model", "")
    if model and indi_drivers.find_model(model) is None:
        raise ValueError(_("Unknown mount model"))
    port = form.get("port", "").strip() or USB_PORTS[0]
    if not _PORT_RE.match(port):
        raise ValueError(
            _("Port must be a USB serial device, for example /dev/ttyUSB0")
        )
    try:
        baud = int(form.get("baud", "9600"))
    except ValueError:
        baud = 0
    if baud not in BAUD_RATES:
        raise ValueError(_("Unknown baud rate"))
    return MountSettings(
        enabled=form.get("enabled") == "on",
        model=model,
        connection=connection,
        port=port,
        baud=baud,
        address=check_address(form.get("address", "")),
    )
