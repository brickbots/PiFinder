"""Convert wpa_supplicant.conf to NetworkManager keyfiles.

Runs during the pre-migration phase on Debian, before reboot into the
initramfs. Keyfiles get staged into the initramfs build dir and the
init script just copies them into the new rootfs — much safer than
generating them in busybox shell after the rootfs has been formatted.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import uuid
from pathlib import Path
from typing import Callable, Iterable, List, Optional


WPA_NETWORK_OPEN = re.compile(r"^\s*network\s*=\s*\{")
WPA_NETWORK_CLOSE = re.compile(r"^\s*\}")
WPA_KEY_VALUE = re.compile(r"^\s*([a-zA-Z0-9_]+)\s*=\s*(.*?)\s*$")

HEX_PSK_RE = re.compile(r"^[0-9a-fA-F]{64}$")
HEX_STRING_RE = re.compile(r"^(?:[0-9a-fA-F]{2})+$")


class Network:
    __slots__ = ("ssid", "psk")

    def __init__(self, ssid: str, psk: Optional[str]) -> None:
        self.ssid = ssid
        self.psk = psk

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, Network)
            and self.ssid == other.ssid
            and self.psk == other.psk
        )

    def __repr__(self) -> str:
        psk_repr = "None" if self.psk is None else f"<{len(self.psk)}c>"
        return f"Network(ssid={self.ssid!r}, psk={psk_repr})"


def _unquote(value: str) -> str:
    """Strip a single surrounding pair of double quotes if present."""
    if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    return value


def _parse_ssid(value: str) -> str:
    """Decode a wpa_supplicant ssid value.

    Quoted values are plain strings. Unquoted values are hex-encoded byte
    strings per wpa_supplicant syntax — decode them here, or the network
    name ends up mangled; surrogateescape keeps non-UTF-8 SSID bytes
    round-trippable into the keyfile byte list.
    """
    if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    if HEX_STRING_RE.fullmatch(value):
        return bytes.fromhex(value).decode("utf-8", "surrogateescape")
    return value


def parse_wpa_supplicant_conf(text: str) -> List[Network]:
    """Parse the subset of wpa_supplicant.conf we care about.

    Recognises `network={ ... }` blocks containing `ssid=` and `psk=`.
    Quoted values get their outer quotes stripped. Unquoted PSKs (the
    64-hex-char pre-shared-key form) are kept verbatim — NetworkManager
    accepts both. Networks without an SSID are skipped.

    Returns the networks in declaration order.
    """
    networks: List[Network] = []
    in_net = False
    ssid: Optional[str] = None
    psk: Optional[str] = None

    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue

        if WPA_NETWORK_OPEN.match(line):
            in_net = True
            ssid = None
            psk = None
            continue

        if WPA_NETWORK_CLOSE.match(line):
            if in_net and ssid is not None:
                networks.append(Network(ssid=ssid, psk=psk))
            in_net = False
            ssid = None
            psk = None
            continue

        if not in_net:
            continue

        match = WPA_KEY_VALUE.match(line)
        if not match:
            continue
        key, value = match.group(1), match.group(2)
        if key == "ssid":
            ssid = _parse_ssid(value)
        elif key == "psk":
            psk = _unquote(value)

    return networks


def ssid_to_bytelist(ssid: str) -> str:
    """Encode an SSID as a NetworkManager keyfile byte list (`97;112;...`).

    NM's keyfile format documents exactly two ssid forms: a plain string and
    a semicolon-separated list of DECIMAL byte values. Anything else (hex,
    0x-prefixed or not) is silently kept as a literal-string SSID, mangling
    the network name so the device can never join it. surrogateescape
    restores non-UTF-8 bytes captured from wpa_supplicant's hex ssid form.
    """
    return "".join(f"{b};" for b in ssid.encode("utf-8", "surrogateescape"))


def escape_keyfile_value(value: str) -> str:
    """Escape characters that have meaning in NM keyfile values.

    Backslash and semicolon are the only special characters in a plain
    string value. (The byte-list format uses the semicolon as separator,
    but we don't use that for the PSK.)
    """
    return value.replace("\\", "\\\\").replace(";", "\\;")


_SAFE_FN_CHARS = re.compile(r"[^A-Za-z0-9._-]")


def sanitize_filename(ssid: str) -> str:
    """Build a safe filename for a connection keyfile from an SSID.

    Non-alphanumeric characters (except `.`, `_`, `-`) are replaced with
    `_`. The result is also guarded against the empty string and `.`/`..`
    so a hostile or odd SSID can't escape the connections directory.
    """
    cleaned = _SAFE_FN_CHARS.sub("_", ssid)
    if cleaned in ("", ".", ".."):
        return "wifi"
    return cleaned


def build_keyfile(
    ssid: str,
    psk: Optional[str],
    connection_uuid: Optional[str] = None,
) -> str:
    """Build a NetworkManager keyfile body for a single WiFi connection.

    `psk=None` produces an open-network keyfile (no [wifi-security]).
    `connection_uuid=None` generates a fresh v4 UUID.
    """
    if connection_uuid is None:
        connection_uuid = str(uuid.uuid4())

    id_escaped = escape_keyfile_value(ssid)
    ssid_encoded = ssid_to_bytelist(ssid)

    lines = [
        "[connection]",
        f"id={id_escaped}",
        f"uuid={connection_uuid}",
        "type=wifi",
        "autoconnect=true",
        "",
        "[wifi]",
        "mode=infrastructure",
        f"ssid={ssid_encoded}",
        "",
    ]

    if psk is not None and psk != "":
        psk_escaped = escape_keyfile_value(psk)
        lines.extend(
            [
                "[wifi-security]",
                "key-mgmt=wpa-psk",
                f"psk={psk_escaped}",
                "",
            ]
        )

    lines.extend(
        [
            "[ipv4]",
            "method=auto",
            "",
            "[ipv6]",
            "method=auto",
            "",
        ]
    )
    return "\n".join(lines)


def emit_keyfiles(
    networks: Iterable[Network],
    output_dir: Path,
    uuid_factory: Callable[[], str] = lambda: str(uuid.uuid4()),
) -> List[Path]:
    """Write a keyfile per network into `output_dir`.

    Filenames are based on a sanitised SSID; collisions get a numeric
    suffix. Files are mode 0600. Returns the list of paths written.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    written: List[Path] = []
    used: set = set()

    for net in networks:
        base = sanitize_filename(net.ssid)
        name = base
        n = 1
        while name in used:
            n += 1
            name = f"{base}_{n}"
        used.add(name)

        path = output_dir / f"{name}.nmconnection"
        body = build_keyfile(net.ssid, net.psk, connection_uuid=uuid_factory())
        path.write_text(body)
        os.chmod(path, 0o600)
        written.append(path)

    return written


def _main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Convert wpa_supplicant.conf to NetworkManager keyfiles for "
            "the PiFinder NixOS migration."
        )
    )
    parser.add_argument(
        "--wpa-conf",
        required=True,
        help="Path to the source wpa_supplicant.conf file.",
    )
    parser.add_argument(
        "--out",
        required=True,
        help="Directory to write the .nmconnection files into (created if absent).",
    )
    args = parser.parse_args(argv)

    src = Path(args.wpa_conf)
    if not src.exists():
        print(f"wpa_supplicant.conf not found at {src}", file=sys.stderr)
        return 0

    networks = parse_wpa_supplicant_conf(src.read_text())
    if not networks:
        print(f"No networks parsed from {src}", file=sys.stderr)
        return 0

    written = emit_keyfiles(networks, Path(args.out))
    print(f"Wrote {len(written)} keyfile(s) to {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(_main())
