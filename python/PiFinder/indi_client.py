"""A small pure-Python INDI client.

The client speaks the INDI XML protocol (version 1.7) over TCP to an
``indiserver``. It keeps a thread-safe store of all properties that the server
defines, and it sends new switch, number and text values to the drivers.

One daemon thread reads the socket. It parses the stream of top-level XML
elements, updates the property store and calls the listeners.
"""

import collections
import dataclasses
import logging
import re
import socket
import threading
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable, Iterator, Mapping
from typing import cast
from xml.sax.saxutils import escape

logger = logging.getLogger("MountControl.IndiClient")

TELESCOPE_INTERFACE = 1

IndiValue = float | bool | str
Listener = Callable[[str, str, str | None, "IndiProperty | None"], None]

_DEF_TYPES = {
    "defNumberVector": "number",
    "defSwitchVector": "switch",
    "defTextVector": "text",
    "defLightVector": "light",
    "defBLOBVector": "blob",
}
_SET_TYPES = {
    "setNumberVector": "number",
    "setSwitchVector": "switch",
    "setTextVector": "text",
    "setLightVector": "light",
    "setBLOBVector": "blob",
}
_SEXAGESIMAL_SPLIT = re.compile(r"[:\s]+")
_RECV_SIZE = 65536


def parse_number(text: str) -> float:
    """Parse an INDI number, which can be decimal or sexagesimal text.

    Sexagesimal examples: "12:30:15.5", "-5 30 0", "12:30", "-0:30".
    Raise ValueError if the text is not a number.
    """
    text = text.strip()
    if not text:
        raise ValueError("empty number")
    try:
        return float(text)
    except ValueError:
        pass
    negative = text.startswith("-")
    parts = [p for p in _SEXAGESIMAL_SPLIT.split(text.lstrip("+-")) if p]
    if not parts or len(parts) > 3:
        raise ValueError(f"bad number {text!r}")
    value = 0.0
    for index, part in enumerate(parts):
        value += abs(float(part)) / (60.0**index)
    return -value if negative else value


def quoteattr(value: str) -> str:
    """Return value as a double-quoted, escaped XML attribute value."""
    return '"' + escape(value, {'"': "&quot;"}) + '"'


def _format_number(value: float) -> str:
    return format(float(value), ".10g")


@dataclasses.dataclass
class IndiProperty:
    """One INDI property vector and the values of its elements."""

    device: str
    name: str
    type: str
    state: str = "Idle"
    perm: str = "ro"
    rule: str = ""
    label: str = ""
    group: str = ""
    elements: dict[str, IndiValue] = dataclasses.field(default_factory=dict)
    element_labels: dict[str, str] = dataclasses.field(default_factory=dict)
    number_limits: dict[str, tuple[float, float, float]] = dataclasses.field(
        default_factory=dict
    )

    def copy(self) -> "IndiProperty":
        return dataclasses.replace(
            self,
            elements=dict(self.elements),
            element_labels=dict(self.element_labels),
            number_limits=dict(self.number_limits),
        )


class IndiClient:
    """An INDI client with one reader thread and a thread-safe property store."""

    def __init__(
        self, host: str = "localhost", port: int = 7624, max_messages: int = 50
    ) -> None:
        self.host = host
        self.port = port
        self._max_messages = max_messages
        self._lock = threading.RLock()
        self._cond = threading.Condition(self._lock)
        self._send_lock = threading.Lock()
        self._props: dict[tuple[str, str], IndiProperty] = {}
        self._messages: dict[str, collections.deque[str]] = {}
        self._listeners: list[Listener] = []
        self._sock: socket.socket | None = None
        self._reader: threading.Thread | None = None
        self._connected = False
        self._blob_devices: set[str] = set()

    # Connection

    def connect(self, timeout: float = 5.0) -> bool:
        """Open the connection and ask the server for all properties.

        Return False if the server cannot be reached.
        """
        if self.is_connected():
            return True
        try:
            sock = socket.create_connection((self.host, self.port), timeout=timeout)
        except OSError as exc:
            logger.warning(
                "Cannot connect to INDI server %s:%s: %s", self.host, self.port, exc
            )
            return False
        sock.settimeout(None)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        with self._lock:
            self._props.clear()
            self._blob_devices.clear()
            self._sock = sock
            self._connected = True
        self._reader = threading.Thread(
            target=self._read_loop, args=(sock,), name="IndiClientReader", daemon=True
        )
        self._reader.start()
        if not self._send('<getProperties version="1.7"/>\n'):
            self.disconnect()
            return False
        logger.info("Connected to INDI server %s:%s", self.host, self.port)
        return True

    def disconnect(self) -> None:
        """Close the connection. The reader thread then stops."""
        with self._lock:
            sock = self._sock
        if sock is None:
            return
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        reader = self._reader
        if reader is not None and reader is not threading.current_thread():
            reader.join(timeout=2.0)
        self._mark_disconnected(sock)

    def is_connected(self) -> bool:
        with self._lock:
            return self._connected

    # Listeners

    def add_listener(self, callback: Listener) -> None:
        """Add a callback(event, device, name, prop).

        The reader thread calls it for "def", "set", "del", "message" and
        "disconnected" events.
        """
        with self._lock:
            self._listeners.append(callback)

    def remove_listener(self, callback: Listener) -> None:
        with self._lock:
            if callback in self._listeners:
                self._listeners.remove(callback)

    # Property store

    def devices(self) -> list[str]:
        with self._lock:
            return sorted({device for device, _ in self._props})

    def properties(self, device: str) -> list[str]:
        with self._lock:
            return sorted(name for dev, name in self._props if dev == device)

    def get_property(self, device: str, name: str) -> IndiProperty | None:
        """Return a copy of the property, or None if it is not defined."""
        with self._lock:
            prop = self._props.get((device, name))
            return prop.copy() if prop is not None else None

    def get_value(self, device: str, name: str, element: str) -> IndiValue | None:
        with self._lock:
            prop = self._props.get((device, name))
            if prop is None:
                return None
            return prop.elements.get(element)

    def messages(self, device: str = "") -> list[str]:
        """Return the last messages of a device ("" for messages with no device)."""
        with self._lock:
            return list(self._messages.get(device, ()))

    def wait_for(self, predicate: Callable[[], bool], timeout: float) -> bool:
        """Wait until predicate() is True. Return False at the timeout.

        The predicate runs with the store lock held. It can call the getters.
        It is checked again only when the property store or the connection
        state changes.
        """
        with self._cond:
            return self._cond.wait_for(predicate, timeout=timeout)

    def wait_property(
        self, device: str, name: str, timeout: float
    ) -> IndiProperty | None:
        """Wait until the property is defined. Return a copy, or None."""
        if not self.wait_for(lambda: (device, name) in self._props, timeout):
            return None
        return self.get_property(device, name)

    def wait_state(
        self, device: str, name: str, states: Iterable[str], timeout: float
    ) -> bool:
        """Wait until the property state is one of the given states."""
        wanted = set(states)

        def check() -> bool:
            prop = self._props.get((device, name))
            return prop is not None and prop.state in wanted

        return self.wait_for(check, timeout)

    def device_interface(self, device: str) -> int | None:
        """Return the DRIVER_INTERFACE bit mask of the device, or None."""
        value = self.get_value(device, "DRIVER_INFO", "DRIVER_INTERFACE")
        if not isinstance(value, str):
            return None
        try:
            return int(value.strip())
        except ValueError:
            return None

    # Senders

    def set_switch(self, device: str, name: str, element: str, on: bool = True) -> bool:
        """Set one switch element.

        For a OneOfMany vector, send all elements with only this element On.
        For AnyOfMany and AtMostOne, send only this element.
        """
        with self._lock:
            prop = self._props.get((device, name))
            if prop is None or prop.type != "switch" or element not in prop.elements:
                logger.warning("Unknown switch %s.%s.%s", device, name, element)
                return False
            if prop.rule == "OneOfMany" and on:
                values = {elem: elem == element for elem in prop.elements}
            else:
                values = {element: on}
        return self._send_vector("Switch", device, name, values)

    def set_switch_off(self, device: str, name: str) -> bool:
        """Set all elements of a switch vector Off."""
        with self._lock:
            prop = self._props.get((device, name))
            if prop is None or prop.type != "switch":
                logger.warning("Unknown switch %s.%s", device, name)
                return False
            values: dict[str, IndiValue] = {elem: False for elem in prop.elements}
        return self._send_vector("Switch", device, name, values)

    def set_number(self, device: str, name: str, values: dict[str, float]) -> bool:
        """Send a number vector: the given values and the current other values."""
        return self._send_full("number", "Number", device, name, values)

    def set_text(self, device: str, name: str, values: dict[str, str]) -> bool:
        """Send a text vector: the given values and the current other values."""
        return self._send_full("text", "Text", device, name, values)

    def _send_full(
        self,
        prop_type: str,
        tag: str,
        device: str,
        name: str,
        values: dict[str, float] | dict[str, str],
    ) -> bool:
        with self._lock:
            prop = self._props.get((device, name))
            if prop is None or prop.type != prop_type:
                logger.warning("Unknown %s property %s.%s", prop_type, device, name)
                return False
            unknown = set(values) - set(prop.elements)
            if unknown:
                logger.warning(
                    "Unknown elements %s in %s.%s", sorted(unknown), device, name
                )
                return False
            full: dict[str, IndiValue] = dict(prop.elements)
        full.update(values)
        return self._send_vector(tag, device, name, full)

    def _send_vector(
        self, tag: str, device: str, name: str, values: Mapping[str, IndiValue]
    ) -> bool:
        lines = [f"<new{tag}Vector device={quoteattr(device)} name={quoteattr(name)}>"]
        for element, value in values.items():
            if tag == "Switch":
                text = "On" if value else "Off"
            elif tag == "Number":
                text = _format_number(float(value))
            else:
                text = escape(str(value))
            lines.append(f"  <one{tag} name={quoteattr(element)}>{text}</one{tag}>")
        lines.append(f"</new{tag}Vector>\n")
        return self._send("\n".join(lines))

    def _send(self, data: str) -> bool:
        with self._lock:
            sock = self._sock if self._connected else None
        if sock is None:
            return False
        try:
            with self._send_lock:
                sock.sendall(data.encode("utf-8"))
        except OSError as exc:
            logger.warning("INDI send failed: %s", exc)
            return False
        return True

    # Reader thread

    def _new_parser(self) -> ET.XMLPullParser:
        parser = ET.XMLPullParser(events=("start", "end"))
        parser.feed(b"<indi>")
        return parser

    def _read_loop(self, sock: socket.socket) -> None:
        parser = self._new_parser()
        root: ET.Element | None = None
        depth = 0
        try:
            while True:
                try:
                    data = sock.recv(_RECV_SIZE)
                except OSError:
                    break
                if not data:
                    break
                try:
                    parser.feed(data)
                    events = cast(Iterator[tuple[str, object]], parser.read_events())
                    for event, elem in events:
                        if not isinstance(elem, ET.Element):
                            continue
                        if event == "start":
                            depth += 1
                            if depth == 1:
                                root = elem
                            continue
                        depth -= 1
                        if elem.tag == "oneBLOB":
                            elem.text = None
                        if depth == 1:
                            self._handle_element(elem)
                            if root is not None:
                                root.remove(elem)
                except ET.ParseError as exc:
                    logger.error("INDI XML parse error, parser reset: %s", exc)
                    parser = self._new_parser()
                    root = None
                    depth = 0
        finally:
            self._mark_disconnected(sock)

    def _mark_disconnected(self, sock: socket.socket) -> None:
        with self._lock:
            if self._sock is not sock:
                return
            self._sock = None
            was_connected = self._connected
            self._connected = False
            self._cond.notify_all()
        try:
            sock.close()
        except OSError:
            pass
        if was_connected:
            logger.info("Disconnected from INDI server %s:%s", self.host, self.port)
            self._notify("disconnected", "", None, None)

    def _notify(
        self, event: str, device: str, name: str | None, prop: IndiProperty | None
    ) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for listener in listeners:
            try:
                listener(event, device, name, prop)
            except Exception:
                logger.exception(
                    "INDI listener failed on %s %s.%s", event, device, name
                )

    def _handle_element(self, elem: ET.Element) -> None:
        tag = elem.tag
        try:
            if tag in _DEF_TYPES:
                self._handle_def(elem, _DEF_TYPES[tag])
            elif tag in _SET_TYPES:
                self._handle_set(elem, _SET_TYPES[tag])
            elif tag == "delProperty":
                self._handle_del(elem)
            elif tag == "message":
                self._handle_message(elem)
            else:
                logger.debug("Ignored INDI element %s", tag)
        except Exception:
            logger.exception("Failed to handle INDI element %s", tag)

    def _parse_value(self, prop_type: str, text: str | None) -> IndiValue:
        text = (text or "").strip()
        if prop_type == "number":
            try:
                return parse_number(text)
            except ValueError:
                logger.warning("Bad INDI number %r", text)
                return 0.0
        if prop_type == "switch":
            return text == "On"
        if prop_type == "blob":
            return ""
        return text

    def _handle_def(self, elem: ET.Element, prop_type: str) -> None:
        device = elem.get("device", "")
        name = elem.get("name", "")
        prop = IndiProperty(
            device=device,
            name=name,
            type=prop_type,
            state=elem.get("state", "Idle"),
            perm=elem.get("perm", "ro"),
            rule=elem.get("rule", ""),
            label=elem.get("label", name),
            group=elem.get("group", ""),
        )
        for child in elem:
            elem_name = child.get("name", "")
            prop.elements[elem_name] = self._parse_value(prop_type, child.text)
            prop.element_labels[elem_name] = child.get("label", elem_name)
            if prop_type == "number":
                prop.number_limits[elem_name] = (
                    self._attr_number(child, "min"),
                    self._attr_number(child, "max"),
                    self._attr_number(child, "step"),
                )
        with self._lock:
            self._props[(device, name)] = prop
            snapshot = prop.copy()
            first_blob = prop_type == "blob" and device not in self._blob_devices
            if first_blob:
                self._blob_devices.add(device)
            self._cond.notify_all()
        if first_blob:
            self._send(f"<enableBLOB device={quoteattr(device)}>Never</enableBLOB>\n")
        self._record_message(elem)
        self._notify("def", device, name, snapshot)

    def _attr_number(self, elem: ET.Element, attr: str) -> float:
        try:
            return parse_number(elem.get(attr, "0"))
        except ValueError:
            return 0.0

    def _handle_set(self, elem: ET.Element, prop_type: str) -> None:
        device = elem.get("device", "")
        name = elem.get("name", "")
        with self._lock:
            prop = self._props.get((device, name))
            if prop is None or prop.type != prop_type:
                logger.debug("Set for undefined property %s.%s", device, name)
                return
            if "state" in elem.attrib:
                prop.state = elem.attrib["state"]
            for child in elem:
                elem_name = child.get("name", "")
                if elem_name in prop.elements:
                    prop.elements[elem_name] = self._parse_value(prop_type, child.text)
            snapshot = prop.copy()
            self._cond.notify_all()
        self._record_message(elem)
        self._notify("set", device, name, snapshot)

    def _handle_del(self, elem: ET.Element) -> None:
        device = elem.get("device", "")
        name = elem.get("name")
        removed: list[IndiProperty] = []
        with self._lock:
            if name:
                prop = self._props.pop((device, name), None)
                if prop is not None:
                    removed.append(prop)
            else:
                for key in [key for key in self._props if key[0] == device]:
                    removed.append(self._props.pop(key))
                self._blob_devices.discard(device)
            self._cond.notify_all()
        self._record_message(elem)
        if name:
            self._notify("del", device, name, removed[0] if removed else None)
        else:
            self._notify("del", device, None, None)

    def _handle_message(self, elem: ET.Element) -> None:
        if self._record_message(elem):
            self._notify("message", elem.get("device", ""), None, None)

    def _record_message(self, elem: ET.Element) -> bool:
        text = elem.get("message")
        if not text:
            return False
        device = elem.get("device", "")
        timestamp = elem.get("timestamp", time.strftime("%Y-%m-%dT%H:%M:%S"))
        line = f"{timestamp}: {text}"
        with self._lock:
            queue = self._messages.get(device)
            if queue is None:
                queue = collections.deque(maxlen=self._max_messages)
                self._messages[device] = queue
            queue.append(line)
        logger.info("INDI message [%s] %s", device or "server", line)
        return True
