"""Tests for the pure-Python INDI client."""

import logging
import os
import shutil
import socket
import subprocess
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from PiFinder.indi_client import (
    TELESCOPE_INTERFACE,
    IndiClient,
    IndiProperty,
    parse_number,
)

MOUNT_DEFS = b"""<defTextVector device="Mount" name="DRIVER_INFO" label="Driver Info"
 group="General Info" state="Idle" perm="ro" timeout="0">
  <defText name="DRIVER_NAME" label="Name">Fake Mount</defText>
  <defText name="DRIVER_INTERFACE" label="Interface">
    5
  </defText>
</defTextVector>
<defSwitchVector device="Mount" name="CONNECTION" label="Connection"
 group="Main Control" state="Idle" perm="rw" rule="OneOfMany" timeout="60">
  <defSwitch name="CONNECT" label="Connect">Off</defSwitch>
  <defSwitch name="DISCONNECT" label="Disconnect">On</defSwitch>
</defSwitchVector>
<defSwitchVector device="Mount" name="OPTIONS" label="Options" group="Main"
 state="Idle" perm="rw" rule="AnyOfMany" timeout="0">
  <defSwitch name="A">Off</defSwitch>
  <defSwitch name="B">On</defSwitch>
</defSwitchVector>
<defNumberVector device="Mount" name="EQUATORIAL_EOD_COORD" label="Eq. Coordinates"
 group="Main Control" state="Ok" perm="rw" timeout="60">
  <defNumber name="RA" label="RA (hh:mm:ss)" format="%010.6m" min="0" max="24"
   step="0">12:30:15.5</defNumber>
  <defNumber name="DEC" label="DEC (dd:mm:ss)" format="%010.6m" min="-90" max="90"
   step="0"> -5 30 0 </defNumber>
</defNumberVector>
<defTextVector device="Mount" name="SITE_NAME" label="Site" group="Site"
 state="Idle" perm="rw" timeout="0">
  <defText name="NAME">Home</defText>
  <defText name="NOTE">none</defText>
</defTextVector>
<defLightVector device="Mount" name="STATUS" label="Status" group="Main"
 state="Idle">
  <defLight name="TRACKING">Ok</defLight>
</defLightVector>
<defBLOBVector device="Mount" name="CCD1" label="Image" group="Image"
 state="Idle" perm="ro">
  <defBLOB name="CCD1" label="Image"/>
</defBLOBVector>
<message device="Mount" timestamp="2026-11-11T20:00:00" message="Hello &amp; welcome"/>
"""


class FakeIndiServer:
    """A one-connection TCP server that sends canned XML and records input."""

    def __init__(self) -> None:
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(1)
        self.port = self.listener.getsockname()[1]
        self.conn: socket.socket | None = None
        self.received = b""
        self._lock = threading.Lock()
        self._accepted = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            conn, _ = self.listener.accept()
        except OSError:
            return
        self.conn = conn
        self._accepted.set()
        while True:
            try:
                data = conn.recv(4096)
            except OSError:
                return
            if not data:
                return
            with self._lock:
                self.received += data

    def send(self, data: bytes, chunks: int = 1) -> None:
        """Send data in several chunks with a short pause between them."""
        assert self._accepted.wait(5.0)
        assert self.conn is not None
        size = max(1, len(data) // chunks)
        for start in range(0, len(data), size):
            self.conn.sendall(data[start : start + size])
            time.sleep(0.01)

    def text(self) -> str:
        with self._lock:
            return self.received.decode("utf-8")

    def wait_received(self, needle: str, timeout: float = 2.0) -> bool:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if needle in self.text():
                return True
            time.sleep(0.01)
        return False

    def clear(self) -> None:
        with self._lock:
            self.received = b""

    def close_client(self) -> None:
        if self.conn is not None:
            self.conn.shutdown(socket.SHUT_RDWR)
            self.conn.close()

    def stop(self) -> None:
        try:
            self.close_client()
        except OSError:
            pass
        self.listener.close()


@pytest.fixture
def server() -> Iterator[FakeIndiServer]:
    fake = FakeIndiServer()
    yield fake
    fake.stop()


@pytest.fixture
def client(server: FakeIndiServer) -> Iterator[IndiClient]:
    indi = IndiClient("127.0.0.1", server.port)
    assert indi.connect(timeout=2.0)
    yield indi
    indi.disconnect()


def load_defs(server: FakeIndiServer, client: IndiClient) -> None:
    server.send(MOUNT_DEFS, chunks=7)
    assert client.wait_for(lambda: len(client.messages("Mount")) == 1, 3.0)


@pytest.mark.unit
def test_parse_number_sexagesimal() -> None:
    assert parse_number("12:30:15.5") == pytest.approx(12 + 30 / 60 + 15.5 / 3600)
    assert parse_number("-5 30 0") == pytest.approx(-5.5)
    assert parse_number("12:30") == pytest.approx(12.5)
    assert parse_number("-0:30") == pytest.approx(-0.5)
    assert parse_number("  3.25 ") == pytest.approx(3.25)
    assert parse_number("+1:30:00") == pytest.approx(1.5)
    with pytest.raises(ValueError):
        parse_number("abc")
    with pytest.raises(ValueError):
        parse_number("")


@pytest.mark.unit
def test_connect_sends_get_properties(
    server: FakeIndiServer, client: IndiClient
) -> None:
    assert client.is_connected()
    assert server.wait_received('<getProperties version="1.7"/>')


@pytest.mark.unit
def test_connect_failure_returns_false() -> None:
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    indi = IndiClient("127.0.0.1", port)
    assert indi.connect(timeout=1.0) is False
    assert not indi.is_connected()
    assert indi.set_switch("Mount", "CONNECTION", "CONNECT") is False


@pytest.mark.unit
def test_def_parsing_with_split_chunks(
    server: FakeIndiServer, client: IndiClient
) -> None:
    # Split the stream in the middle of a tag name and in the middle of a value.
    cut1 = MOUNT_DEFS.index(b"defSwitchVector") + 5
    cut2 = MOUNT_DEFS.index(b"12:30:15.5") + 4
    server.send(MOUNT_DEFS[:cut1])
    server.send(MOUNT_DEFS[cut1:cut2])
    server.send(MOUNT_DEFS[cut2:])
    assert client.wait_for(lambda: len(client.messages("Mount")) == 1, 3.0)

    assert client.devices() == ["Mount"]
    assert "CONNECTION" in client.properties("Mount")

    conn = client.get_property("Mount", "CONNECTION")
    assert conn is not None
    assert conn.type == "switch"
    assert conn.rule == "OneOfMany"
    assert conn.perm == "rw"
    assert conn.group == "Main Control"
    assert conn.elements == {"CONNECT": False, "DISCONNECT": True}

    coord = client.get_property("Mount", "EQUATORIAL_EOD_COORD")
    assert coord is not None
    assert coord.type == "number"
    assert coord.state == "Ok"
    assert coord.elements["RA"] == pytest.approx(12.504305555)
    assert coord.elements["DEC"] == pytest.approx(-5.5)
    assert coord.number_limits["DEC"] == (-90.0, 90.0, 0.0)
    assert coord.element_labels["RA"] == "RA (hh:mm:ss)"

    status = client.get_property("Mount", "STATUS")
    assert status is not None
    assert status.type == "light"
    assert status.elements == {"TRACKING": "Ok"}

    blob = client.get_property("Mount", "CCD1")
    assert blob is not None and blob.type == "blob"
    assert server.wait_received('<enableBLOB device="Mount">Never</enableBLOB>')

    interface = client.device_interface("Mount")
    assert interface == 5
    assert interface & TELESCOPE_INTERFACE
    assert client.device_interface("Other") is None
    assert client.messages("Mount") == ["2026-11-11T20:00:00: Hello & welcome"]


@pytest.mark.unit
def test_get_property_returns_copy(server: FakeIndiServer, client: IndiClient) -> None:
    load_defs(server, client)
    prop = client.get_property("Mount", "CONNECTION")
    assert prop is not None
    prop.elements["CONNECT"] = True
    again = client.get_property("Mount", "CONNECTION")
    assert again is not None
    assert again.elements["CONNECT"] is False


@pytest.mark.unit
def test_set_updates_values_and_state(
    server: FakeIndiServer, client: IndiClient
) -> None:
    load_defs(server, client)
    server.send(
        b'<setNumberVector device="Mount" name="EQUATORIAL_EOD_COORD" state="Busy">'
        b'<oneNumber name="RA">6:00:00</oneNumber></setNumberVector>'
        b'<setSwitchVector device="Mount" name="CONNECTION" state="Ok">'
        b'<oneSwitch name="CONNECT">On</oneSwitch>'
        b'<oneSwitch name="DISCONNECT">Off</oneSwitch></setSwitchVector>',
        chunks=5,
    )
    assert client.wait_state("Mount", "CONNECTION", ["Ok"], 2.0)
    coord = client.get_property("Mount", "EQUATORIAL_EOD_COORD")
    assert coord is not None
    assert coord.state == "Busy"
    assert coord.elements["RA"] == pytest.approx(6.0)
    assert coord.elements["DEC"] == pytest.approx(-5.5)
    assert client.get_value("Mount", "CONNECTION", "CONNECT") is True


@pytest.mark.unit
def test_del_property(server: FakeIndiServer, client: IndiClient) -> None:
    load_defs(server, client)
    server.send(b'<delProperty device="Mount" name="STATUS"/>')
    assert client.wait_for(lambda: client.get_property("Mount", "STATUS") is None, 2.0)
    assert client.get_property("Mount", "CONNECTION") is not None
    server.send(b'<delProperty device="Mount"/>')
    assert client.wait_for(lambda: client.devices() == [], 2.0)


@pytest.mark.unit
def test_wait_property(server: FakeIndiServer, client: IndiClient) -> None:
    assert client.wait_property("Mount", "CONNECTION", 0.1) is None
    timer = threading.Timer(0.2, server.send, args=(MOUNT_DEFS,))
    timer.start()
    prop = client.wait_property("Mount", "CONNECTION", 3.0)
    timer.join()
    assert prop is not None
    assert prop.name == "CONNECTION"


@pytest.mark.unit
def test_switch_one_of_many_sends_all(
    server: FakeIndiServer, client: IndiClient
) -> None:
    load_defs(server, client)
    server.clear()
    assert client.set_switch("Mount", "CONNECTION", "CONNECT")
    assert server.wait_received("</newSwitchVector>")
    sent = server.text()
    assert '<newSwitchVector device="Mount" name="CONNECTION">' in sent
    assert '<oneSwitch name="CONNECT">On</oneSwitch>' in sent
    assert '<oneSwitch name="DISCONNECT">Off</oneSwitch>' in sent


@pytest.mark.unit
def test_switch_any_of_many_sends_one(
    server: FakeIndiServer, client: IndiClient
) -> None:
    load_defs(server, client)
    server.clear()
    assert client.set_switch("Mount", "OPTIONS", "A")
    assert server.wait_received("</newSwitchVector>")
    sent = server.text()
    assert '<oneSwitch name="A">On</oneSwitch>' in sent
    assert 'name="B"' not in sent


@pytest.mark.unit
def test_switch_off_sends_all_off(server: FakeIndiServer, client: IndiClient) -> None:
    load_defs(server, client)
    server.clear()
    assert client.set_switch_off("Mount", "CONNECTION")
    assert server.wait_received("</newSwitchVector>")
    sent = server.text()
    assert '<oneSwitch name="CONNECT">Off</oneSwitch>' in sent
    assert '<oneSwitch name="DISCONNECT">Off</oneSwitch>' in sent


@pytest.mark.unit
def test_unknown_property_send_returns_false(
    server: FakeIndiServer, client: IndiClient
) -> None:
    load_defs(server, client)
    assert client.set_switch("Mount", "NOPE", "X") is False
    assert client.set_switch("Mount", "CONNECTION", "NOPE") is False
    assert client.set_number("Mount", "CONNECTION", {"CONNECT": 1.0}) is False
    assert client.set_number("Mount", "EQUATORIAL_EOD_COORD", {"ALT": 1.0}) is False
    assert client.set_text("Other", "SITE_NAME", {"NAME": "x"}) is False


@pytest.mark.unit
def test_number_send_full_vector(server: FakeIndiServer, client: IndiClient) -> None:
    load_defs(server, client)
    server.clear()
    assert client.set_number("Mount", "EQUATORIAL_EOD_COORD", {"RA": 3.25})
    assert server.wait_received("</newNumberVector>")
    sent = server.text()
    assert '<oneNumber name="RA">3.25</oneNumber>' in sent
    assert '<oneNumber name="DEC">-5.5</oneNumber>' in sent


@pytest.mark.unit
def test_text_send_full_vector_escaped(
    server: FakeIndiServer, client: IndiClient
) -> None:
    load_defs(server, client)
    server.clear()
    assert client.set_text("Mount", "SITE_NAME", {"NAME": 'A<b> & "c"'})
    assert server.wait_received("</newTextVector>")
    sent = server.text()
    assert '<oneText name="NAME">A&lt;b&gt; &amp; "c"</oneText>' in sent
    assert '<oneText name="NOTE">none</oneText>' in sent


@pytest.mark.unit
def test_attribute_escaping(server: FakeIndiServer, client: IndiClient) -> None:
    device = 'Odd "<&>" Mount'
    server.send(
        b'<defSwitchVector device="Odd &quot;&lt;&amp;&gt;&quot; Mount" name="S"'
        b' perm="rw" rule="AtMostOne" state="Idle">'
        b'<defSwitch name="X">Off</defSwitch></defSwitchVector>'
    )
    assert client.wait_property(device, "S", 2.0) is not None
    server.clear()
    assert client.set_switch(device, "S", "X")
    assert server.wait_received("</newSwitchVector>")
    assert 'device="Odd &quot;&lt;&amp;&gt;&quot; Mount"' in server.text()


@pytest.mark.unit
def test_blob_contents_ignored(server: FakeIndiServer, client: IndiClient) -> None:
    load_defs(server, client)
    payload = b"QUFB" * 20000
    server.send(
        b'<setBLOBVector device="Mount" name="CCD1" state="Ok">'
        b'<oneBLOB name="CCD1" size="60000" format=".fits">'
        + payload
        + b"</oneBLOB></setBLOBVector>",
        chunks=9,
    )
    assert client.wait_state("Mount", "CCD1", ["Ok"], 3.0)
    blob = client.get_property("Mount", "CCD1")
    assert blob is not None
    assert blob.elements["CCD1"] == ""


@pytest.mark.unit
def test_listener_events(server: FakeIndiServer, client: IndiClient) -> None:
    events: list[tuple[str, str, str | None]] = []
    seen = threading.Event()

    def listener(
        event: str, device: str, name: str | None, prop: IndiProperty | None
    ) -> None:
        events.append((event, device, name))
        if event == "set":
            assert prop is not None
            assert prop.state == "Busy"
        if event == "disconnected":
            seen.set()

    client.add_listener(listener)
    load_defs(server, client)
    server.send(
        b'<setSwitchVector device="Mount" name="CONNECTION" state="Busy"/>'
        b'<message device="Mount" message="Moving"/>'
        b'<delProperty device="Mount" name="STATUS"/>'
    )
    assert client.wait_for(lambda: ("del", "Mount", "STATUS") in events, 2.0)
    server.close_client()
    assert seen.wait(2.0)
    assert ("def", "Mount", "CONNECTION") in events
    assert ("set", "Mount", "CONNECTION") in events
    assert ("message", "Mount", None) in events
    assert events[-1] == ("disconnected", "", None)


@pytest.mark.unit
def test_listener_exception_does_not_stop_reader(
    server: FakeIndiServer, client: IndiClient, caplog: pytest.LogCaptureFixture
) -> None:
    got_set = threading.Event()

    def bad(
        event: str, device: str, name: str | None, prop: IndiProperty | None
    ) -> None:
        raise RuntimeError("listener failure")

    def good(
        event: str, device: str, name: str | None, prop: IndiProperty | None
    ) -> None:
        if event == "set":
            got_set.set()

    client.add_listener(bad)
    client.add_listener(good)
    with caplog.at_level(logging.ERROR, logger="MountControl.IndiClient"):
        load_defs(server, client)
        server.send(b'<setSwitchVector device="Mount" name="CONNECTION" state="Ok"/>')
        assert got_set.wait(2.0)
    assert client.is_connected()
    assert "listener failure" in caplog.text


@pytest.mark.unit
def test_server_close_sets_disconnected(
    server: FakeIndiServer, client: IndiClient
) -> None:
    load_defs(server, client)
    server.close_client()
    assert client.wait_for(lambda: not client.is_connected(), 2.0)
    assert client.set_switch("Mount", "CONNECTION", "CONNECT") is False


@pytest.mark.unit
def test_bad_xml_recovers(server: FakeIndiServer, client: IndiClient) -> None:
    server.send(b"<broken <<>>")
    time.sleep(0.1)
    server.send(MOUNT_DEFS)
    assert client.wait_property("Mount", "CONNECTION", 2.0) is not None
    assert client.is_connected()


# Integration test with a real indiserver and the telescope simulator.

SIMULATOR = "Telescope Simulator"


def _free_port() -> int:
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


@pytest.fixture
def indiserver_port(tmp_path: Path) -> Iterator[int]:
    port = _free_port()
    # The simulator writes ~/.indi/ParkData.xml, so give it a private HOME.
    env = dict(os.environ, HOME=str(tmp_path))
    proc = subprocess.Popen(
        # A private local socket (-u): the default one allows one indiserver
        # per machine.
        [
            "indiserver",
            "-p",
            str(port),
            "-u",
            f"/tmp/indiserver-test-{port}",
            "indi_simulator_telescope",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    try:
        end = time.monotonic() + 10.0
        while time.monotonic() < end:
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
                break
            except OSError:
                time.sleep(0.1)
        yield port
    finally:
        proc.kill()
        proc.wait(timeout=5.0)


def _angle_distance(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    dra = abs(ra1 - ra2) % 24.0
    dra = min(dra, 24.0 - dra) * 15.0
    return max(dra, abs(dec1 - dec2))


@pytest.mark.integration
@pytest.mark.skipif(shutil.which("indiserver") is None, reason="no indiserver")
def test_simulator_goto(indiserver_port: int) -> None:
    indi = IndiClient("127.0.0.1", indiserver_port)
    assert indi.connect(timeout=5.0)
    try:
        assert indi.wait_property(SIMULATOR, "CONNECTION", 10.0) is not None
        assert indi.wait_property(SIMULATOR, "DRIVER_INFO", 5.0) is not None
        interface = indi.device_interface(SIMULATOR)
        assert interface is not None
        assert interface & TELESCOPE_INTERFACE

        assert indi.set_switch(SIMULATOR, "CONNECTION", "CONNECT")
        coord = indi.wait_property(SIMULATOR, "EQUATORIAL_EOD_COORD", 10.0)
        assert coord is not None

        assert indi.wait_property(SIMULATOR, "ON_COORD_SET", 5.0) is not None
        assert indi.set_switch(SIMULATOR, "ON_COORD_SET", "TRACK")

        park = indi.wait_property(SIMULATOR, "TELESCOPE_PARK", 5.0)
        if park is not None and park.elements.get("PARK"):
            assert indi.set_switch(SIMULATOR, "TELESCOPE_PARK", "UNPARK")
            assert indi.wait_for(
                lambda: indi.get_value(SIMULATOR, "TELESCOPE_PARK", "UNPARK") is True,
                10.0,
            )

        coord = indi.get_property(SIMULATOR, "EQUATORIAL_EOD_COORD")
        assert coord is not None
        ra0 = float(coord.elements["RA"])
        dec0 = float(coord.elements["DEC"])
        target_ra = (ra0 + 1.0) % 24.0
        target_dec = 20.0 if dec0 < 0.0 else dec0 - 20.0
        start = _angle_distance(ra0, dec0, target_ra, target_dec)

        assert indi.set_number(
            SIMULATOR, "EQUATORIAL_EOD_COORD", {"RA": target_ra, "DEC": target_dec}
        )

        def closer() -> bool:
            ra = indi.get_value(SIMULATOR, "EQUATORIAL_EOD_COORD", "RA")
            dec = indi.get_value(SIMULATOR, "EQUATORIAL_EOD_COORD", "DEC")
            if not isinstance(ra, float) or not isinstance(dec, float):
                return False
            return _angle_distance(ra, dec, target_ra, target_dec) < start * 0.5

        assert indi.wait_for(closer, 30.0)
        assert indi.wait_state(SIMULATOR, "EQUATORIAL_EOD_COORD", ["Ok"], 60.0)
        final = indi.get_property(SIMULATOR, "EQUATORIAL_EOD_COORD")
        assert final is not None
        assert (
            _angle_distance(
                float(final.elements["RA"]),
                float(final.elements["DEC"]),
                target_ra,
                target_dec,
            )
            # The simulator stops near the target; under load a little further.
            < 0.5
        )
    finally:
        indi.disconnect()
