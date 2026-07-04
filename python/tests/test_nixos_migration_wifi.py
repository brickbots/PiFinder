import re

import pytest

from PiFinder.nixos_migration_wifi import (
    Network,
    _parse_ssid,
    build_keyfile,
    emit_keyfiles,
    escape_keyfile_value,
    parse_wpa_supplicant_conf,
    sanitize_filename,
    ssid_to_bytelist,
)


UUID_V4_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


@pytest.mark.unit
class TestParseWpaSupplicantConf:
    def test_empty(self):
        assert parse_wpa_supplicant_conf("") == []

    def test_single_wpa_network(self):
        conf = """
        ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
        update_config=1
        country=BE

        network={
            ssid="APME"
            psk="hunter12"
        }
        """
        assert parse_wpa_supplicant_conf(conf) == [Network("APME", "hunter12")]

    def test_open_network_has_no_psk(self):
        conf = """
        network={
            ssid="OpenNet"
            key_mgmt=NONE
        }
        """
        assert parse_wpa_supplicant_conf(conf) == [Network("OpenNet", None)]

    def test_multiple_networks_preserve_order(self):
        conf = """
        network={
            ssid="first"
            psk="pw1"
        }
        network={
            ssid="second"
            psk="pw2"
        }
        network={
            ssid="third"
            psk="pw3"
        }
        """
        nets = parse_wpa_supplicant_conf(conf)
        assert [n.ssid for n in nets] == ["first", "second", "third"]

    def test_hex_psk_preserved_verbatim(self):
        hex_psk = "a" * 64
        conf = f"""
        network={{
            ssid="HexPsk"
            psk={hex_psk}
        }}
        """
        result = parse_wpa_supplicant_conf(conf)
        assert result == [Network("HexPsk", hex_psk)]

    def test_unquoted_ssid_kept(self):
        # Some configs use unquoted SSIDs for short alphanumerics.
        conf = """
        network={
            ssid=plain
            psk="pw"
        }
        """
        assert parse_wpa_supplicant_conf(conf) == [Network("plain", "pw")]

    def test_ssid_with_special_chars(self):
        conf = """
        network={
            ssid="0x20"
            psk="pw"
        }
        network={
            ssid="hackerspace.gent"
            psk="pw2"
        }
        """
        nets = parse_wpa_supplicant_conf(conf)
        assert nets == [
            Network("0x20", "pw"),
            Network("hackerspace.gent", "pw2"),
        ]

    def test_network_without_ssid_skipped(self):
        conf = """
        network={
            psk="orphan"
        }
        network={
            ssid="valid"
            psk="pw"
        }
        """
        assert parse_wpa_supplicant_conf(conf) == [Network("valid", "pw")]

    def test_comments_and_blank_lines_ignored(self):
        conf = """
        # global comment
        ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev

        network={
            # inner comment
            ssid="commented"
            psk="pw"  # trailing comment
        }
        """
        assert parse_wpa_supplicant_conf(conf) == [Network("commented", "pw")]


@pytest.mark.unit
class TestSsidToBytelist:
    def test_ascii(self):
        assert ssid_to_bytelist("APME") == "65;80;77;69;"

    def test_bytes_are_decimal(self):
        # The whole point of this function — NM only parses DECIMAL byte
        # lists; hex (with or without 0x prefix) is silently kept as a
        # literal-string SSID and the network name is mangled.
        assert ssid_to_bytelist("apollo") == "97;112;111;108;108;111;"

    def test_utf8_bytes(self):
        # SSID can contain non-ASCII; should be encoded as utf-8 bytes
        assert ssid_to_bytelist("é") == "195;169;"

    def test_empty(self):
        assert ssid_to_bytelist("") == ""

    def test_non_utf8_bytes_round_trip(self):
        # A hex wpa ssid holding non-UTF-8 bytes survives parse -> encode.
        assert ssid_to_bytelist(_parse_ssid("ff00")) == "255;0;"


@pytest.mark.unit
class TestParseSsidValue:
    def test_quoted_is_plain_string(self):
        assert _parse_ssid('"apollo"') == "apollo"

    def test_unquoted_hex_is_decoded(self):
        # wpa_supplicant stores SSIDs with special characters as unquoted
        # hex strings; these must be decoded, not used as the name.
        assert _parse_ssid("61706f6c6c6f") == "apollo"

    def test_quoted_hex_lookalike_stays_verbatim(self):
        # A network genuinely NAMED like a hex string is quoted in
        # wpa_supplicant, so it must not be decoded.
        assert _parse_ssid('"61706f"') == "61706f"

    def test_non_hex_unquoted_stays_verbatim(self):
        assert _parse_ssid("abc") == "abc"

    def test_hex_ssid_end_to_end(self):
        conf = """
        network={
            ssid=61706f6c6c6f
            psk="hunter12"
        }
        """
        assert parse_wpa_supplicant_conf(conf) == [Network("apollo", "hunter12")]


@pytest.mark.unit
class TestEscapeKeyfileValue:
    def test_plain(self):
        assert escape_keyfile_value("hunter12") == "hunter12"

    def test_semicolon_escaped(self):
        assert escape_keyfile_value("a;b") == "a\\;b"

    def test_backslash_escaped(self):
        assert escape_keyfile_value("a\\b") == "a\\\\b"

    def test_backslash_before_semicolon(self):
        # Backslash must be escaped first so we don't double-escape the
        # semicolon escape sequence we just produced.
        assert escape_keyfile_value("\\;") == "\\\\\\;"


@pytest.mark.unit
class TestSanitizeFilename:
    def test_plain(self):
        assert sanitize_filename("APME") == "APME"

    def test_dot_preserved(self):
        assert sanitize_filename("hackerspace.gent") == "hackerspace.gent"

    def test_slash_replaced(self):
        assert sanitize_filename("a/b") == "a_b"

    def test_pathy_chars_replaced(self):
        assert sanitize_filename("../etc/passwd") == ".._etc_passwd"

    def test_empty_becomes_wifi(self):
        assert sanitize_filename("") == "wifi"

    def test_dot_becomes_wifi(self):
        assert sanitize_filename(".") == "wifi"

    def test_dotdot_becomes_wifi(self):
        assert sanitize_filename("..") == "wifi"


@pytest.mark.unit
class TestBuildKeyfile:
    def test_contains_required_sections(self):
        body = build_keyfile("APME", "hunter12", connection_uuid="fixed-uuid")
        assert "[connection]" in body
        assert "[wifi]" in body
        assert "[wifi-security]" in body
        assert "[ipv4]" in body
        assert "[ipv6]" in body

    def test_uuid_present(self):
        body = build_keyfile("APME", "pw", connection_uuid="abc-123")
        assert "uuid=abc-123" in body

    def test_uuid_generated_when_not_provided(self):
        body = build_keyfile("APME", "pw")
        match = re.search(r"^uuid=(.+)$", body, re.MULTILINE)
        assert match
        assert UUID_V4_RE.match(match.group(1))

    def test_ssid_encoded_as_decimal_bytelist(self):
        body = build_keyfile("APME", "pw", connection_uuid="x")
        assert "ssid=65;80;77;69;" in body

    def test_open_network_omits_security(self):
        body = build_keyfile("OpenNet", None, connection_uuid="x")
        assert "[wifi-security]" not in body
        assert "key-mgmt" not in body
        assert "psk=" not in body

    def test_empty_psk_treated_as_open(self):
        body = build_keyfile("OpenNet", "", connection_uuid="x")
        assert "[wifi-security]" not in body

    def test_psk_with_semicolon_escaped(self):
        body = build_keyfile("S", "p;w", connection_uuid="x")
        assert "psk=p\\;w" in body

    def test_psk_with_backslash_escaped(self):
        body = build_keyfile("S", "p\\w", connection_uuid="x")
        assert "psk=p\\\\w" in body

    def test_ipv4_method_auto(self):
        body = build_keyfile("S", "pw", connection_uuid="x")
        assert "[ipv4]\nmethod=auto" in body

    def test_id_uses_ssid(self):
        body = build_keyfile("MyNet", "pw", connection_uuid="x")
        assert "id=MyNet" in body


@pytest.mark.unit
class TestEmitKeyfiles:
    def test_writes_one_file_per_network(self, tmp_path):
        nets = [Network("a", "pw"), Network("b", None), Network("c", "pw3")]
        written = emit_keyfiles(nets, tmp_path)
        assert len(written) == 3
        assert {p.name for p in written} == {
            "a.nmconnection",
            "b.nmconnection",
            "c.nmconnection",
        }

    def test_file_mode_is_600(self, tmp_path):
        emit_keyfiles([Network("a", "pw")], tmp_path)
        mode = (tmp_path / "a.nmconnection").stat().st_mode & 0o777
        assert mode == 0o600

    def test_creates_output_dir(self, tmp_path):
        target = tmp_path / "nested" / "wifi"
        emit_keyfiles([Network("a", "pw")], target)
        assert (target / "a.nmconnection").exists()

    def test_collision_suffix(self, tmp_path):
        # Two SSIDs that sanitize to the same filename
        nets = [Network("a/b", "pw"), Network("a.b", "pw")]
        # sanitize: "a/b" -> "a_b", "a.b" -> "a.b" (different) — pick another pair
        nets = [Network("a/b", "pw"), Network("a;b", "pw")]
        # Both sanitize to "a_b"
        written = emit_keyfiles(nets, tmp_path)
        names = sorted(p.name for p in written)
        assert names == ["a_b.nmconnection", "a_b_2.nmconnection"]

    def test_each_file_gets_unique_uuid(self, tmp_path):
        nets = [Network("a", "pw"), Network("b", "pw")]
        emit_keyfiles(nets, tmp_path)
        u1 = (tmp_path / "a.nmconnection").read_text()
        u2 = (tmp_path / "b.nmconnection").read_text()
        uuid1 = re.search(r"^uuid=(.+)$", u1, re.MULTILINE).group(1)
        uuid2 = re.search(r"^uuid=(.+)$", u2, re.MULTILINE).group(1)
        assert uuid1 != uuid2
        assert UUID_V4_RE.match(uuid1)
        assert UUID_V4_RE.match(uuid2)

    def test_deterministic_with_injected_uuid(self, tmp_path):
        nets = [Network("a", "pw")]
        emit_keyfiles(nets, tmp_path, uuid_factory=lambda: "fixed-uuid-1234")
        body = (tmp_path / "a.nmconnection").read_text()
        assert "uuid=fixed-uuid-1234" in body
