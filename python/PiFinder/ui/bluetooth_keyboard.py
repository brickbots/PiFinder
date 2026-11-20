#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Bluetooth keyboard pairing and connection UI.
"""

import fcntl
import os
import re
import select
import subprocess
import time
from typing import Any, TYPE_CHECKING

from PiFinder import utils
from PiFinder.ui.text_menu import UITextMenu

if TYPE_CHECKING:

    def _(a) -> Any:
        return a


sys_utils = utils.get_sys_utils()

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
PASSKEY_RE = re.compile(r"Passkey:\s*([0-9]{4,8})", re.IGNORECASE)
MAC_ADDRESS_RE = re.compile(r"^[0-9A-Fa-f:]{17}$")
DEVICE_NAME_MAX = 20
SCAN_SECONDS = 12
PAIR_TIMEOUT = 90


class UIBluetoothKeyboard(UITextMenu):
    """
    Small Bluetooth HID manager for pairing keyboards from the PiFinder UI.
    USB keyboards need no pairing; they are handled by the normal libinput path.
    """

    __title__ = "Keyboard"

    def __init__(self, *args, **kwargs):
        self.devices: list[dict[str, Any]] = []
        self.status = ""
        self.action_menu_active = False
        self.action_index = 0
        self.selected_device: dict[str, Any] | None = None

        self.pair_process: subprocess.Popen | None = None
        self.pair_address = ""
        self.pair_name = ""
        self.pair_started = 0.0
        self.pair_status = ""
        self.pair_output = ""
        self.pair_done_at: float | None = None
        self.pair_success = False
        self.pair_connect_sent = False
        self.pair_yes_sent = False

        self._refresh_devices()
        kwargs["item_definition"] = self._create_menu_definition()
        super().__init__(*args, **kwargs)

    def _refresh_devices(self):
        try:
            self.devices = sys_utils.list_bluetooth_devices()
            self.status = ""
        except Exception as e:
            self.devices = []
            self.status = f"BT error: {e}"

    def _create_menu_definition(self):
        items = [
            {"name": _("Scan / Pair"), "value": "__scan__"},
            {"name": _("Reconnect"), "value": "__reconnect__"},
            {"name": _("Refresh"), "value": "__refresh__"},
        ]
        for device in self.devices:
            items.append(
                {
                    "name": self._device_label(device),
                    "value": device["address"],
                    "device": device,
                }
            )
        if not self.devices:
            items.append({"name": _("No BT devices"), "value": None})
        return {"name": _("Keyboard"), "select": "single", "items": items}

    def _rebuild_menu(self):
        self.item_definition = self._create_menu_definition()
        self._menu_items = [x["name"] for x in self.item_definition["items"]]
        if self._current_item_index >= len(self._menu_items):
            self._current_item_index = max(0, len(self._menu_items) - 1)

    def _device_label(self, device: dict[str, Any]) -> str:
        if device.get("connected"):
            marker = "*"
        elif device.get("paired"):
            marker = "+"
        else:
            marker = "-"
        name = self._device_name(device)
        available = max(5, DEVICE_NAME_MAX - 2)
        if len(name) > available:
            name = name[: available - 3] + "..."
        return f"{marker} {name}"

    def _device_name(self, device: dict[str, Any]) -> str:
        name = str(device.get("name") or device.get("alias") or "").strip()
        address = str(device.get("address") or "").strip()
        if not name or MAC_ADDRESS_RE.match(name):
            return f"Unknown {address[-5:]}" if address else "Unknown"
        return name

    def _short_address(self, device: dict[str, Any]) -> str:
        address = str(device.get("address") or "").strip()
        if not address:
            return ""
        return f"MAC ...{address[-8:]}"

    def _selected_item(self) -> dict[str, Any]:
        return self.item_definition["items"][self._current_item_index]

    def _run_scan(self):
        self.message(_("BT scanning"), SCAN_SECONDS)
        try:
            self.devices = sys_utils.scan_bluetooth_devices(SCAN_SECONDS)
            self.status = f"Found {len(self.devices)}"
        except Exception as e:
            self.status = f"Scan error: {e}"
        self._rebuild_menu()

    def _run_reconnect(self):
        self.message(_("Connecting"), 2)
        try:
            count = sys_utils.reconnect_bluetooth_keyboards()
            self.status = f"Reconnect {count}"
        except Exception as e:
            self.status = f"Conn error: {e}"
        self._refresh_devices()
        self._rebuild_menu()

    def _open_action_menu(self, device: dict[str, Any]):
        self.selected_device = device
        self.action_menu_active = True
        self.action_index = 0

    def _action_items(self) -> list[tuple[str, str]]:
        device = self.selected_device or {}
        actions: list[tuple[str, str]] = []
        if not device.get("paired"):
            actions.append((_("Pair+Connect"), "pair"))
        else:
            actions.append((_("Pair Again"), "pair"))
        actions.append((_("Connect"), "connect"))
        if device.get("connected"):
            actions.append((_("Disconnect"), "disconnect"))
        actions.append((_("Remove"), "remove"))
        actions.append((_("Cancel"), "cancel"))
        return actions

    def _perform_action(self):
        if self.selected_device is None:
            self.action_menu_active = False
            return

        label, action = self._action_items()[self.action_index]
        address = str(self.selected_device["address"])
        if action == "cancel":
            self.action_menu_active = False
            return
        if action == "pair":
            self._start_pairing(address, str(self.selected_device.get("name", "")))
            return

        self.message(label, 1)
        try:
            if action == "connect":
                output = sys_utils.connect_bluetooth_device(address)
            elif action == "disconnect":
                output = sys_utils.disconnect_bluetooth_device(address)
            elif action == "remove":
                output = sys_utils.remove_bluetooth_device(address)
            else:
                output = ""
            self.status = self._short_result(output)
        except Exception as e:
            self.status = f"BT error: {e}"
        self.action_menu_active = False
        self._refresh_devices()
        self._rebuild_menu()

    def _short_result(self, output: str) -> str:
        clean = self._clean_text(output)
        for line in reversed([x.strip() for x in clean.splitlines() if x.strip()]):
            if "successful" in line.lower() or "failed" in line.lower():
                return line[:24]
        return "Done"

    def _start_pairing(self, address: str, name: str):
        self._close_pair_process()
        self.pair_address = address
        self.pair_name = name or address
        self.pair_started = time.time()
        self.pair_status = "Starting"
        self.pair_output = ""
        self.pair_done_at = None
        self.pair_success = False
        self.pair_connect_sent = False
        self.pair_yes_sent = False

        try:
            self.pair_process = subprocess.Popen(
                [sys_utils.BLUETOOTHCTL_COMMAND],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=False,
            )
            assert self.pair_process.stdout is not None
            flags = fcntl.fcntl(self.pair_process.stdout.fileno(), fcntl.F_GETFL)
            fcntl.fcntl(
                self.pair_process.stdout.fileno(), fcntl.F_SETFL, flags | os.O_NONBLOCK
            )
            for command in [
                "power on",
                "agent KeyboardDisplay",
                "default-agent",
                "pairable on",
                f"pair {address}",
            ]:
                self._send_pair_command(command)
            self.pair_status = "Pairing"
        except Exception as e:
            self.pair_status = f"Start failed: {e}"
            self._finish_pairing(False)

    def _send_pair_command(self, command: str):
        if self.pair_process is None or self.pair_process.stdin is None:
            return
        try:
            self.pair_process.stdin.write((command + "\n").encode())
            self.pair_process.stdin.flush()
        except BrokenPipeError:
            pass

    def _clean_text(self, text: str) -> str:
        return ANSI_ESCAPE_RE.sub("", text).replace("\r", "\n")

    def _read_pair_output(self):
        if self.pair_process is None or self.pair_process.stdout is None:
            return
        fd = self.pair_process.stdout.fileno()
        while True:
            ready, _, _ = select.select([fd], [], [], 0)
            if not ready:
                break
            try:
                chunk = os.read(fd, 4096)
            except BlockingIOError:
                break
            if not chunk:
                break
            text = chunk.decode(errors="replace")
            self.pair_output = (self.pair_output + text)[-4000:]
            self._handle_pair_text(self._clean_text(self.pair_output))

    def _handle_pair_text(self, text: str):
        passkey = PASSKEY_RE.search(text)
        if passkey:
            self.pair_status = f"Type {passkey.group(1)}"

        if (
            not self.pair_yes_sent
            and (
                "Confirm passkey" in text
                or "Authorize service" in text
                or "Accept pairing" in text
            )
        ):
            self._send_pair_command("yes")
            self.pair_yes_sent = True

        pair_ok = "Pairing successful" in text or "AlreadyExists" in text
        if pair_ok and not self.pair_connect_sent:
            self.pair_status = "Connecting"
            self._send_pair_command(f"trust {self.pair_address}")
            self._send_pair_command(f"connect {self.pair_address}")
            self.pair_connect_sent = True

        if "Connection successful" in text:
            self.pair_status = "Connected"
            self._finish_pairing(True)
            return

        failure_tokens = [
            "AuthenticationCanceled",
            "AuthenticationFailed",
            "Failed to pair",
            "Failed to connect",
            "not available",
            "No default controller",
        ]
        if any(token in text for token in failure_tokens):
            if pair_ok:
                self.pair_status = "Paired"
            else:
                self.pair_status = "Pair failed"
            self._finish_pairing(pair_ok)

    def _finish_pairing(self, success: bool):
        if self.pair_done_at is not None:
            return
        self.pair_success = success
        self.pair_done_at = time.time()
        self._send_pair_command("quit")

    def _close_pair_process(self):
        if self.pair_process is None:
            return
        try:
            if self.pair_process.poll() is None:
                self.pair_process.terminate()
                self.pair_process.wait(timeout=1)
        except Exception:
            try:
                self.pair_process.kill()
            except Exception:
                pass
        self.pair_process = None

    def _update_pairing(self):
        if self.pair_process is None:
            return
        self._read_pair_output()
        if time.time() - self.pair_started > PAIR_TIMEOUT:
            self.pair_status = "Pair timeout"
            self._finish_pairing(False)
        if self.pair_process.poll() is not None and self.pair_done_at is None:
            self._finish_pairing(self.pair_success)
        if self.pair_done_at and time.time() - self.pair_done_at > 2.5:
            self._close_pair_process()
            self.action_menu_active = False
            self._refresh_devices()
            self._rebuild_menu()

    def _draw_lines(self, lines: list[str], selected: int | None = None):
        self.clear_screen()
        draw_y = self.display_class.titlebar_height + 2
        max_chars = max(4, (self.display_class.resX - 4) // self.fonts.base.width)
        for idx, line in enumerate(lines):
            if draw_y > self.display_class.resY - self.fonts.base.height:
                break
            if len(line) > max_chars:
                line = line[: max_chars - 3] + "..."
            fill = self.colors.get(255 if selected == idx else 128)
            font = self.fonts.bold.font if selected == idx else self.fonts.base.font
            self.draw.text((2, draw_y), line, font=font, fill=fill)
            draw_y += self.fonts.base.height + 2

    def _draw_action_menu(self):
        device = self.selected_device or {}
        name = self._device_name(device)
        state = []
        if device.get("connected"):
            state.append("Conn")
        if device.get("paired"):
            state.append("Pair")
        if device.get("trusted"):
            state.append("Trust")
        lines = [name, self._short_address(device), " ".join(state) or "New device"]
        lines.extend(label for label, _ in self._action_items())
        self._draw_lines(lines, self.action_index + 3)
        return self.screen_update()

    def _draw_pairing(self):
        self._update_pairing()
        lines = [
            "Pair Keyboard",
            self.pair_name,
            self.pair_status,
        ]
        if self.pair_done_at:
            lines.append("OK" if self.pair_success else "Failed")
        else:
            lines.append("Left cancels")
        self._draw_lines(lines)
        return self.screen_update()

    def update(self, force=False):
        if self.pair_process is not None:
            return self._draw_pairing()
        if self.action_menu_active:
            return self._draw_action_menu()
        result = super().update(force)
        if self.status:
            y = self.display_class.resY - self.fonts.base.height - 1
            max_chars = max(4, (self.display_class.resX - 4) // self.fonts.base.width)
            status = self.status[:max_chars]
            self.draw.rectangle(
                [0, y - 1, self.display_class.resX, self.display_class.resY],
                fill=self.colors.get(0),
            )
            self.draw.text((2, y), status, font=self.fonts.base.font, fill=self.colors.get(192))
            return self.screen_update()
        return result

    def key_up(self):
        if self.action_menu_active:
            self.action_index = (self.action_index - 1) % len(self._action_items())
            return
        super().key_up()

    def key_down(self):
        if self.action_menu_active:
            self.action_index = (self.action_index + 1) % len(self._action_items())
            return
        super().key_down()

    def key_right(self):
        if self.pair_process is not None:
            return
        if self.action_menu_active:
            return self._perform_action()

        selected_item = self._selected_item()
        value = selected_item.get("value")
        if value == "__scan__":
            return self._run_scan()
        if value == "__reconnect__":
            return self._run_reconnect()
        if value == "__refresh__":
            self._refresh_devices()
            self._rebuild_menu()
            return
        if selected_item.get("device"):
            return self._open_action_menu(selected_item["device"])

    def key_left(self) -> bool:
        if self.pair_process is not None:
            self._close_pair_process()
            self.pair_status = "Canceled"
            self.action_menu_active = False
            self._refresh_devices()
            self._rebuild_menu()
            return False
        if self.action_menu_active:
            self.action_menu_active = False
            return False
        return True
