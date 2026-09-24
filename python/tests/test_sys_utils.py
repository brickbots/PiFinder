import pytest

try:
    from PiFinder import board_config
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
    @pytest.mark.parametrize(
        ("model", "profile", "gps_device", "uart_overlay"),
        [
            (
                "Raspberry Pi 5 Model B Rev 1.0",
                "pi5_class",
                "/dev/ttyAMA2",
                "dtoverlay=uart2-pi5",
            ),
            (
                "Raspberry Pi Compute Module 5 Rev 1.0",
                "pi5_class",
                "/dev/ttyAMA2",
                "dtoverlay=uart2-pi5",
            ),
            (
                "Raspberry Pi 4 Model B Rev 1.5",
                "pi4",
                "/dev/ttyAMA3",
                "dtoverlay=uart3",
            ),
            (
                "Raspberry Pi 3 Model B Plus Rev 1.3",
                "legacy",
                "/dev/ttyAMA1",
                "dtoverlay=uart3",
            ),
        ],
    )
    def test_board_profile_by_model(model, profile, gps_device, uart_overlay):
        board_profile = board_config.get_board_profile(model)

        assert board_profile.name == profile
        assert board_profile.gps_device == gps_device
        assert board_profile.uart_overlay == uart_overlay

    @pytest.mark.unit
    def test_resolve_gpsd_device_uses_board_default(monkeypatch):
        monkeypatch.setattr(sys_utils, "get_default_gpsd_device", lambda: "/dev/ttyAMA3")

        assert sys_utils.resolve_gpsd_device(None) == "/dev/ttyAMA3"
        assert sys_utils.resolve_gpsd_device("auto") == "/dev/ttyAMA3"
        assert sys_utils.resolve_gpsd_device("/dev/ttyACM0") == "/dev/ttyACM0"

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


except ImportError:
    pass
