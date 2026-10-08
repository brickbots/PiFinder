import pytest

try:
    from PiFinder import sys_utils

    @pytest.mark.unit
    def test_wpa_supplicant_parsing():
        # This could be read from a file or passed from another function
        wpa_supplicant_example = """
        ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
        update_config=1
        country=US

        network={
            ssid="My Home Network"
            psk="password123"
            key_mgmt=WPA-PSK
        }

        network={
            ssid="Work Network"
            psk="compl3x=p@ssw0rd!"
            key_mgmt=WPA-PSK
        }
        """
        wpa_list = [
            line.strip()
            for line in wpa_supplicant_example.strip().split("\n")
            if line.strip()
        ]
        result = sys_utils.Network._parse_wpa_supplicant(wpa_list)
        assert result[1]["psk"] == "compl3x=p@ssw0rd!"

        example2 = """
        ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
        update_config=1

















        network={
                ssid="testytest"
                psk="oesrucoeahu1234"
                key_mgmt=WPA-PSK
        }

        network={
                ssid="00xx33"
                psk="1234@===!!!"
                key_mgmt=WPA-PSK
        }
        """
        wpa_list = [line for line in example2.split("\n") if line.strip()]
        result = sys_utils.Network._parse_wpa_supplicant(wpa_list)
        assert result[1]["psk"] == "1234@===!!!"

    @pytest.mark.unit
    def test_rewrite_hosts_standard_line():
        contents = (
            "127.0.0.1\tlocalhost\n"
            "::1\t\tlocalhost ip6-localhost ip6-loopback\n"
            "127.0.1.1\tpifinder\n"
        )
        result = sys_utils.Network._rewrite_hosts(contents, "pf-rich")
        assert "127.0.1.1\tpf-rich\n" in result
        assert "pifinder" not in result
        assert "127.0.0.1\tlocalhost\n" in result

    @pytest.mark.unit
    def test_rewrite_hosts_preserves_aliases_and_spacing():
        contents = "  127.0.1.1   pifinder pifinder.local  # primary\n"
        result = sys_utils.Network._rewrite_hosts(contents, "pf-rich")
        assert result == "  127.0.1.1   pf-rich pifinder.local  # primary\n"

    @pytest.mark.unit
    def test_rewrite_hosts_appends_when_missing():
        contents = "127.0.0.1\tlocalhost\n"
        result = sys_utils.Network._rewrite_hosts(contents, "pf-rich")
        assert result.endswith("127.0.1.1\tpf-rich\n")
        assert "127.0.0.1\tlocalhost\n" in result

    @pytest.mark.unit
    def test_rewrite_hosts_appends_with_missing_trailing_newline():
        contents = "127.0.0.1\tlocalhost"
        result = sys_utils.Network._rewrite_hosts(contents, "pf-rich")
        assert result == "127.0.0.1\tlocalhost\n127.0.1.1\tpf-rich\n"

    @pytest.mark.unit
    def test_rewrite_hosts_ignores_commented_line():
        contents = "# 127.0.1.1 oldname\n127.0.0.1\tlocalhost\n"
        result = sys_utils.Network._rewrite_hosts(contents, "pf-rich")
        # commented line is untouched; a real 127.0.1.1 entry is appended
        assert "# 127.0.1.1 oldname\n" in result
        assert result.endswith("127.0.1.1\tpf-rich\n")

    @pytest.mark.unit
    def test_parse_bluetooth_devices_merges_fields():
        output = """
        \x1b[0;94m[bluetooth]# Device AA:BB:CC:DD:EE:FF Keychron K2\r
        Device AA:BB:CC:DD:EE:FF Paired: yes
        Device AA:BB:CC:DD:EE:FF Connected: no
        Device AA:BB:CC:DD:EE:FF Icon: input-keyboard
        Device 11:22:33:44:55:66 11:22:33:44:55:66
        Device 11:22:33:44:55:66 Name: Travel Mouse
        """

        devices = sys_utils._parse_bluetooth_devices(output)

        keyboard = devices["AA:BB:CC:DD:EE:FF"]
        assert keyboard["name"] == "Keychron K2"
        assert keyboard["paired"] is True
        assert keyboard["connected"] is False
        assert keyboard["icon"] == "input-keyboard"
        assert sys_utils.is_bluetooth_keyboard(keyboard)

        mouse = devices["11:22:33:44:55:66"]
        assert mouse["name"] == "Travel Mouse"
        assert not sys_utils.is_bluetooth_keyboard(mouse)

    @pytest.mark.unit
    def test_list_bluetooth_devices_uses_info_status(monkeypatch):
        def fake_bluetoothctl(commands, timeout=20):
            if commands == ["power on", "devices", "devices Paired"]:
                return "Device AA:BB:CC:DD:EE:FF AA:BB:CC:DD:EE:FF\n"
            if commands == ["info AA:BB:CC:DD:EE:FF"]:
                return """
                Name: Compact Keyboard
                Paired: yes
                Trusted: yes
                Connected: yes
                Icon: input-keyboard
                """
            return ""

        monkeypatch.setattr(sys_utils, "_bluetoothctl", fake_bluetoothctl)

        devices = sys_utils.list_bluetooth_devices()

        assert devices == [
            {
                "address": "AA:BB:CC:DD:EE:FF",
                "name": "Compact Keyboard",
                "paired": True,
                "trusted": True,
                "connected": True,
                "blocked": False,
                "icon": "input-keyboard",
            }
        ]


except ImportError:
    pass
