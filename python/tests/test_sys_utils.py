import pytest
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
    wpa_list = [line.strip() for line in wpa_supplicant_example.strip().split('\n') if line.strip()]
    result = sys_utils.Network._parse_wpa_supplicant(wpa_list)
    print("result is", result)
    assert result[1]['psk'] == 'compl3x=p@ssw0rd!'
