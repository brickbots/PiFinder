"""Tests for the NixOS sys_utils (NetworkManager, hostname, upgrade progress)."""

import pytest

# The NixOS sys_utils needs dbus-python and pygobject, which are in the
# aarch64 environment only. The aarch64 CI job runs these tests.
sys_utils = pytest.importorskip(
    "PiFinder.sys_utils", reason="needs dbus-python and pygobject (aarch64 only)"
)


class _Bytes:
    def __init__(self, data):
        self._data = data

    def get_data(self):
        return self._data


class _Wireless:
    def __init__(self, ssid):
        self._ssid = None if ssid is None else _Bytes(ssid)

    def get_ssid(self):
        return self._ssid


class _Connection:
    def __init__(self, conn_id, uuid, ssid=b"", wifi=True):
        self._id = conn_id
        self._uuid = uuid
        self._wireless = _Wireless(ssid) if wifi else None

    def get_id(self):
        return self._id

    def get_uuid(self):
        return self._uuid

    def get_setting_wireless(self):
        return self._wireless


class _Client:
    def __init__(self, connections):
        self._connections = connections

    def get_connections(self):
        return self._connections


def _network(connections=()):
    """A Network with a fake NetworkManager client and no D-Bus connection."""
    net = sys_utils.Network.__new__(sys_utils.Network)
    net._client = _Client(list(connections))
    net._wifi_networks = []
    return net


@pytest.mark.unit
def test_wifi_networks_lists_saved_wifi_connections():
    net = _network(
        [
            _Connection("Home", "uuid-home", b"My Home Network"),
            _Connection(sys_utils.AP_CONNECTION_NAME, "uuid-ap", b"PiFinderAP"),
            _Connection("Wired", "uuid-eth", wifi=False),
            _Connection("Work", "uuid-work", b"Work Network"),
        ]
    )
    net.populate_wifi_networks()
    assert net._wifi_networks == [
        {
            "id": 0,
            "uuid": "uuid-home",
            "ssid": "My Home Network",
            "psk": None,
            "key_mgmt": "WPA-PSK",
        },
        {
            "id": 1,
            "uuid": "uuid-work",
            "ssid": "Work Network",
            "psk": None,
            "key_mgmt": "WPA-PSK",
        },
    ]


@pytest.mark.unit
def test_wifi_networks_bad_or_missing_ssid():
    net = _network(
        [
            _Connection("Broken", "uuid-bad", b"caf\xe9"),
            _Connection("Hidden", "uuid-none", None),
        ]
    )
    net.populate_wifi_networks()
    assert [n["ssid"] for n in net._wifi_networks] == ["caf\ufffd", ""]
    assert [n["uuid"] for n in net._wifi_networks] == ["uuid-bad", "uuid-none"]


@pytest.fixture
def host_name_calls(monkeypatch, tmp_path):
    """Record the commands set_host_name runs and keep its file in tmp_path."""
    calls = []
    results = {}

    class _Result:
        def __init__(self, returncode):
            self.returncode = returncode

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _Result(results.get(cmd[1], 0))

    monkeypatch.setattr(sys_utils.subprocess, "run", fake_run)
    monkeypatch.setenv("PIFINDER_DATA", str(tmp_path))
    return calls, results, tmp_path


@pytest.mark.unit
@pytest.mark.parametrize("name", ["", "bad_name", "-leading", "trailing-", "a" * 64])
def test_set_host_name_rejects_invalid_names(host_name_calls, monkeypatch, name):
    calls, _results, data_dir = host_name_calls
    net = _network()
    monkeypatch.setattr(net, "get_host_name", lambda: "pifinder")
    net.set_host_name(name)
    assert calls == []
    assert not (data_dir / "hostname").exists()


@pytest.mark.unit
def test_set_host_name_same_name_does_nothing(host_name_calls, monkeypatch):
    calls, _results, data_dir = host_name_calls
    net = _network()
    monkeypatch.setattr(net, "get_host_name", lambda: "pifinder")
    net.set_host_name(" pifinder ")
    assert calls == []
    assert not (data_dir / "hostname").exists()


@pytest.mark.unit
def test_set_host_name_sets_kernel_and_avahi_and_persists(host_name_calls, monkeypatch):
    calls, _results, data_dir = host_name_calls
    net = _network()
    monkeypatch.setattr(net, "get_host_name", lambda: "pifinder")
    net.set_host_name(" pf-rich ")
    assert calls == [
        ["sudo", "hostname", "pf-rich"],
        ["sudo", "avahi-set-host-name", "pf-rich"],
    ]
    assert (data_dir / "hostname").read_text() == "pf-rich"


@pytest.mark.unit
def test_set_host_name_restarts_avahi_when_rename_fails(host_name_calls, monkeypatch):
    calls, results, data_dir = host_name_calls
    results["avahi-set-host-name"] = 1
    net = _network()
    monkeypatch.setattr(net, "get_host_name", lambda: "pifinder")
    net.set_host_name("pf-rich")
    assert calls[-1] == ["sudo", "systemctl", "restart", "avahi-daemon.service"]
    assert (data_dir / "hostname").read_text() == "pf-rich"


@pytest.mark.unit
def test_upgrade_progress_missing_status_failed_service(tmp_path, monkeypatch):
    monkeypatch.setattr(sys_utils, "UPGRADE_STATUS_FILE", tmp_path / "missing")
    monkeypatch.setattr(sys_utils, "_upgrade_service_state", lambda: "failed")

    assert sys_utils.get_upgrade_progress()["phase"] == "failed"


@pytest.mark.unit
def test_upgrade_progress_stale_downloading_failed_service(tmp_path, monkeypatch):
    status = tmp_path / "upgrade-status"
    status.write_text("downloading 1/10 paths")
    monkeypatch.setattr(sys_utils, "UPGRADE_STATUS_FILE", status)
    monkeypatch.setattr(sys_utils, "_upgrade_service_state", lambda: "failed")

    assert sys_utils.get_upgrade_progress()["phase"] == "failed"


@pytest.mark.unit
def test_upgrade_progress_missing_status_active_service(tmp_path, monkeypatch):
    monkeypatch.setattr(sys_utils, "UPGRADE_STATUS_FILE", tmp_path / "missing")
    monkeypatch.setattr(sys_utils, "_upgrade_service_state", lambda: "active")

    assert sys_utils.get_upgrade_progress()["phase"] == "starting"


@pytest.mark.unit
def test_upgrade_progress_installing(tmp_path, monkeypatch):
    status = tmp_path / "status"
    monkeypatch.setattr(sys_utils, "UPGRADE_STATUS_FILE", status)
    monkeypatch.setattr(sys_utils, "_upgrade_service_state", lambda: "activating")
    status.write_text("installing 12/45 pifinder-src-0.0.1")
    got = sys_utils.get_upgrade_progress()
    assert got["phase"] == "installing"
    assert (got["done"], got["total"], got["unit"]) == (12, 45, "paths")
    assert got["percent"] == 26
    assert got["item"] == "pifinder-src-0.0.1"


@pytest.mark.unit
def test_upgrade_progress_checking_and_patching(tmp_path, monkeypatch):
    status = tmp_path / "status"
    monkeypatch.setattr(sys_utils, "UPGRADE_STATUS_FILE", status)
    monkeypatch.setattr(sys_utils, "_upgrade_service_state", lambda: "activating")
    status.write_text("checking")
    assert sys_utils.get_upgrade_progress()["phase"] == "checking"
    status.write_text("checking 400/1600")
    p = sys_utils.get_upgrade_progress()
    assert (p["phase"], p["done"], p["total"], p["unit"], p["percent"]) == (
        "checking",
        400,
        1600,
        "paths",
        25,
    )
    status.write_text("checking x/y")
    assert sys_utils.get_upgrade_progress()["total"] == 0
    status.write_text("patching 3/12")
    p = sys_utils.get_upgrade_progress()
    assert (p["phase"], p["done"], p["total"], p["unit"], p["percent"]) == (
        "patching",
        3,
        12,
        "paths",
        25,
    )
    status.write_text("patching waiting 5/12")
    p = sys_utils.get_upgrade_progress()
    assert (p["phase"], p["step"], p["done"], p["total"]) == (
        "patching",
        "waiting",
        5,
        12,
    )
    status.write_text("patching applying 2/4")
    p = sys_utils.get_upgrade_progress()
    assert (p["step"], p["done"], p["total"], p["percent"]) == (
        "applying",
        2,
        4,
        50,
    )
