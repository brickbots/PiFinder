from typing import Any
from PiFinder.ui.timeentry import UITimeEntry
from PiFinder.ui.text_menu import UITextMenu
from PiFinder.ui.object_list import UIObjectList
from PiFinder.ui.status import UIStatus
from PiFinder.ui.console import UIConsole
from PiFinder.ui.software import UISoftware
from PiFinder.ui.gpsstatus import UIGPSStatus
from PiFinder.ui.chart import UIChart
from PiFinder.ui.align import UIAlign
from PiFinder.ui.textentry import UITextEntry
from PiFinder.ui.preview import UIPreview
from PiFinder.ui.equipment import UIEquipment
from PiFinder.ui.location_list import UILocationList
from PiFinder.ui.radec_entry import UIRADecEntry
import PiFinder.ui.callbacks as callbacks


# override locally the gettext marker function, i.e. the strings are not translated on load, but extracted. CHECK END OF FILE
def _(key: str) -> Any:
    return key


s = _("Language: de")  # this way ruff lint and mypy type_hints warnings are silenced
s = _("Language: en")
s = _("Language: es")
s = _("Language: fr")
s = s
del s

pifinder_menu = {
    "name": "PiFinder",
    "class": UITextMenu,
    "select": "single",
    "start_index": 2,
    "items": [
        {
            "name": _("Start"),
            "class": UITextMenu,
            "select": "single",
            "items": [
                {
                    "name": _("Focus"),
                    "class": UIPreview,
                },
                {
                    "name": _("Align"),
                    "class": UIAlign,
                    "stateful": True,
                    "preload": True,
                },
                {
                    "name": _("GPS Status"),
                    "class": UIGPSStatus,
                },
            ],
        },
        {
            "name": _("Chart"),
            "class": UIChart,
            "stateful": True,
            "preload": True,
        },
        {
            "name": _("Objects"),
            "class": UITextMenu,
            "select": "single",
            "items": [
                {
                    "name": _("All Filtered"),
                    "class": UIObjectList,
                    "objects": "catalogs.filtered",
                },
                {
                    "name": _("By Catalog"),
                    "class": UITextMenu,
                    "select": "single",
                    "items": [
                        {
                            "name": _("Planets"),
                            "class": UIObjectList,
                            "objects": "catalog",
                            "value": "PL",
                        },
                        {
                            "name": "Comets",
                            "class": UIObjectList,
                            "objects": "catalog",
                            "value": "CM",
                        },
                        {
                            "name": _("NGC"),
                            "class": UIObjectList,
                            "objects": "catalog",
                            "value": "NGC",
                        },
                        {
                            "name": _("Messier"),
                            "class": UIObjectList,
                            "objects": "catalog",
                            "value": "M",
                        },
                        {
                            "name": _("DSO..."),
                            "class": UITextMenu,
                            "select": "single",
                            "items": [
                                {
                                    "name": _("Abell Pn"),
                                    "class": UIObjectList,
                                    "objects": "catalog",
                                    "value": "Abl",
                                },
                                {
                                    "name": _("Arp Galaxies"),
                                    "class": UIObjectList,
                                    "objects": "catalog",
                                    "value": "Arp",
                                },
                                {
                                    "name": _("Barnard"),
                                    "class": UIObjectList,
                                    "objects": "catalog",
                                    "value": "B",
                                },
                                {
                                    "name": _("Caldwell"),
                                    "class": UIObjectList,
                                    "objects": "catalog",
                                    "value": "C",
                                },
                                {
                                    "name": _("Collinder"),
                                    "class": UIObjectList,
                                    "objects": "catalog",
                                    "value": "Col",
                                },
                                {
                                    "name": _("E.G. Globs"),
                                    "class": UIObjectList,
                                    "objects": "catalog",
                                    "value": "EGC",
                                },
                                {
                                    "name": _("Herschel 400"),
                                    "class": UIObjectList,
                                    "objects": "catalog",
                                    "value": "H",
                                },
                                {
                                    "name": _("IC"),
                                    "class": UIObjectList,
                                    "objects": "catalog",
                                    "value": "IC",
                                },
                                {
                                    "name": _("Messier"),
                                    "class": UIObjectList,
                                    "objects": "catalog",
                                    "value": "M",
                                },
                                {
                                    "name": _("NGC"),
                                    "class": UIObjectList,
                                    "objects": "catalog",
                                    "value": "NGC",
                                },
                                {
                                    "name": _("Sharpless"),
                                    "class": UIObjectList,
                                    "objects": "catalog",
                                    "value": "Sh2",
                                },
                                {
                                    "name": _("TAAS 200"),
                                    "class": UIObjectList,
                                    "objects": "catalog",
                                    "value": "Ta2",
                                },
                            ],
                        },
                        {
                            "name": _("Stars..."),
                            "class": UITextMenu,
                            "select": "single",
                            "items": [
                                {
                                    "name": _("Bright Named"),
                                    "class": UIObjectList,
                                    "objects": "catalog",
                                    "value": "Str",
                                },
                                {
                                    "name": _("SAC Doubles"),
                                    "class": UIObjectList,
                                    "objects": "catalog",
                                    "value": "SaM",
                                },
                                {
                                    "name": _("SAC Asterisms"),
                                    "class": UIObjectList,
                                    "objects": "catalog",
                                    "value": "SaA",
                                },
                                {
                                    "name": _("SAC Red Stars"),
                                    "class": UIObjectList,
                                    "objects": "catalog",
                                    "value": "SaR",
                                },
                                {
                                    "name": _("RASC Doubles"),
                                    "class": UIObjectList,
                                    "objects": "catalog",
                                    "value": "RDS",
                                },
                                {
                                    "name": _("WDS Doubles"),
                                    "class": UIObjectList,
                                    "objects": "catalog",
                                    "value": "WDS",
                                },
                                {
                                    "name": _("TLK 90 Variables"),
                                    "class": UIObjectList,
                                    "objects": "catalog",
                                    "value": "TLK",
                                },
                            ],
                        },
                    ],
                },
                {
                    "name": _("Recent"),
                    "class": UIObjectList,
                    "objects": "recent",
                    "label": "recent",
                },
                {
                    "name": _("Custom"),
                    "class": UIRADecEntry,
                    "custom_callback": callbacks.handle_radec_entry,
                },
                {
                    "name": _("Name Search"),
                    "class": UITextEntry,
                },
            ],
        },
        {
            "name": _("Filter"),
            "class": UITextMenu,
            "select": "single",
            "label": "filter_options",
            "items": [
                {
                    "name": _("Reset All"),
                    "class": UITextMenu,
                    "select": "Single",
                    "items": [
                        {"name": _("Confirm"), "callback": callbacks.reset_filters},
                        {"name": _("Cancel"), "callback": callbacks.go_back},
                    ],
                },
                {
                    "name": _("Catalogs"),
                    "class": UITextMenu,
                    "select": "multi",
                    "config_option": "filter.selected_catalogs",
                    "items": [
                        {
                            "name": _("Planets"),
                            "value": "PL",
                        },
                        {
                            "name": _("NGC"),
                            "value": "NGC",
                        },
                        {
                            "name": _("Messier"),
                            "value": "M",
                        },
                        {
                            "name": _("DSO..."),
                            "class": UITextMenu,
                            "select": "multi",
                            "config_option": "filter.selected_catalogs",
                            "items": [
                                {
                                    "name": _("Abell Pn"),
                                    "value": "Abl",
                                },
                                {
                                    "name": _("Arp Galaxies"),
                                    "value": "Arp",
                                },
                                {
                                    "name": _("Barnard"),
                                    "value": "B",
                                },
                                {
                                    "name": _("Caldwell"),
                                    "value": "C",
                                },
                                {
                                    "name": _("Collinder"),
                                    "value": "Col",
                                },
                                {
                                    "name": _("E.G. Globs"),
                                    "value": "EGC",
                                },
                                {
                                    "name": _("Herschel 400"),
                                    "value": "H",
                                },
                                {
                                    "name": _("IC"),
                                    "value": "IC",
                                },
                                {
                                    "name": _("Messier"),
                                    "value": "M",
                                },
                                {
                                    "name": _("NGC"),
                                    "value": "NGC",
                                },
                                {
                                    "name": _("Sharpless"),
                                    "value": "Sh2",
                                },
                                {
                                    "name": _("TAAS 200"),
                                    "value": "Ta2",
                                },
                            ],
                        },
                        {
                            "name": _("Stars..."),
                            "class": UITextMenu,
                            "select": "multi",
                            "config_option": "filter.selected_catalogs",
                            "items": [
                                {
                                    "name": _("Bright Named"),
                                    "value": "Str",
                                },
                                {
                                    "name": _("SAC Doubles"),
                                    "value": "SaM",
                                },
                                {
                                    "name": _("SAC Asterisms"),
                                    "value": "SaA",
                                },
                                {
                                    "name": _("SAC Red Stars"),
                                    "value": "SaR",
                                },
                                {
                                    "name": _("RASC Doubles"),
                                    "value": "RDS",
                                },
                                {
                                    "name": _("TLK 90 Variables"),
                                    "value": "TLK",
                                },
                            ],
                        },
                    ],
                },
                {
                    "name": _("Type"),
                    "class": UITextMenu,
                    "select": "multi",
                    "config_option": "filter.object_types",
                    "items": [
                        {
                            "name": _("Galaxy"),
                            "value": "Gx",
                        },
                        {
                            "name": _("Open Cluster"),
                            "value": "OC",
                        },
                        {
                            "name": _("Cluster/Neb"),
                            "value": "C+N",
                        },
                        {
                            "name": _("Globular"),
                            "value": "Gb",
                        },
                        {
                            "name": _("Nebula"),
                            "value": "Nb",
                        },
                        {
                            "name": _("P. Nebula"),
                            "value": "PN",
                        },
                        {
                            "name": _("Dark Nebula"),
                            "value": "DN",
                        },
                        {
                            "name": _("Star"),
                            "value": "*",
                        },
                        {
                            "name": _("Double Str"),
                            "value": "D*",
                        },
                        {
                            "name": _("Triple Str"),
                            "value": "***",
                        },
                        {
                            "name": _("Knot"),
                            "value": "Kt",
                        },
                        {
                            "name": _("Asterism"),
                            "value": "Ast",
                        },
                        {
                            "name": _("Planet"),
                            "value": "Pla",
                        },
                        {
                            "name": _("Comet"),
                            "value": "CM",
                        },
                        {
                            "name": _("Unknown"),
                            "value": "?",
                        },
                    ],
                },
                {
                    "name": _("Altitude"),
                    "class": UITextMenu,
                    "select": "single",
                    "config_option": "filter.altitude",
                    "items": [
                        {
                            "name": _("None"),
                            "value": -1,
                        },
                        {
                            "name": "0",
                            "value": 0,
                        },
                        {
                            "name": "10",
                            "value": 10,
                        },
                        {
                            "name": "20",
                            "value": 20,
                        },
                        {
                            "name": "30",
                            "value": 30,
                        },
                        {
                            "name": "40",
                            "value": 40,
                        },
                    ],
                },
                {
                    "name": _("Magnitude"),
                    "class": UITextMenu,
                    "select": "single",
                    "config_option": "filter.magnitude",
                    "items": [
                        {
                            "name": _("None"),
                            "value": -1,
                        },
                        {
                            "name": "6",
                            "value": 6,
                        },
                        {
                            "name": "7",
                            "value": 7,
                        },
                        {
                            "name": "8",
                            "value": 8,
                        },
                        {
                            "name": "9",
                            "value": 9,
                        },
                        {
                            "name": "10",
                            "value": 10,
                        },
                        {
                            "name": "11",
                            "value": 11,
                        },
                        {
                            "name": "12",
                            "value": 12,
                        },
                        {
                            "name": "13",
                            "value": 13,
                        },
                        {
                            "name": "14",
                            "value": 14,
                        },
                        {
                            "name": "15",
                            "value": 15,
                        },
                    ],
                },
                {
                    "name": _("Observed"),
                    "class": UITextMenu,
                    "select": "single",
                    "config_option": "filter.observed",
                    "items": [
                        {
                            "name": _("Any"),
                            "value": "Any",
                        },
                        {
                            "name": _("Observed"),
                            "value": "Yes",
                        },
                        {
                            "name": _("Not Observed"),
                            "value": "No",
                        },
                    ],
                },
            ],
        },
        {
            "name": _("Settings"),
            "class": UITextMenu,
            "select": "single",
            "items": [
                {
                    "name": _("User Pref..."),
                    "class": UITextMenu,
                    "select": "single",
                    "items": [
                        {
                            "name": _("Key Bright"),
                            "class": UITextMenu,
                            "select": "single",
                            "config_option": "keypad_brightness",
                            "items": [
                                {
                                    "name": "-4",
                                    "value": "-4",
                                },
                                {
                                    "name": "-3",
                                    "value": "-3",
                                },
                                {
                                    "name": "-2",
                                    "value": "-2",
                                },
                                {
                                    "name": "-1",
                                    "value": "-1",
                                },
                                {
                                    "name": "0",
                                    "value": "0",
                                },
                                {
                                    "name": "1",
                                    "value": "+1",
                                },
                                {
                                    "name": "2",
                                    "value": "+2",
                                },
                                {
                                    "name": "3",
                                    "value": "+3",
                                },
                            ],
                        },
                        {
                            "name": _("Sleep Time"),
                            "class": UITextMenu,
                            "select": "single",
                            "config_option": "sleep_timeout",
                            "items": [
                                {
                                    "name": _("Off"),
                                    "value": "Off",
                                },
                                {
                                    "name": "10s",
                                    "value": "10s",
                                },
                                {
                                    "name": "20s",
                                    "value": "20s",
                                },
                                {
                                    "name": "30s",
                                    "value": "30s",
                                },
                                {
                                    "name": "1m",
                                    "value": "1m",
                                },
                                {
                                    "name": "2m",
                                    "value": "2m",
                                },
                            ],
                        },
                        {
                            "name": _("Menu Anim"),
                            "class": UITextMenu,
                            "select": "single",
                            "config_option": "menu_anim_speed",
                            "items": [
                                {
                                    "name": _("Off"),
                                    "value": 0,
                                },
                                {
                                    "name": _("Fast"),
                                    "value": 0.05,
                                },
                                {
                                    "name": _("Medium"),
                                    "value": 0.1,
                                },
                                {
                                    "name": _("Slow"),
                                    "value": 0.2,
                                },
                            ],
                        },
                        {
                            "name": _("Scroll Speed"),
                            "class": UITextMenu,
                            "select": "single",
                            "config_option": "text_scroll_speed",
                            "items": [
                                {
                                    "name": _("Off"),
                                    "value": "Off",
                                },
                                {
                                    "name": _("Fast"),
                                    "value": "Fast",
                                },
                                {
                                    "name": _("Medium"),
                                    "value": "Med",
                                },
                                {
                                    "name": _("Slow"),
                                    "value": "Slow",
                                },
                            ],
                        },
                        {
                            "name": _("Az Arrows"),
                            "class": UITextMenu,
                            "select": "single",
                            "config_option": "pushto_az_arrows",
                            "label": "pushto_az_arrows",
                            "items": [
                                {
                                    "name": _("Default"),
                                    "value": "Default",
                                },
                                {
                                    "name": _("Reverse"),
                                    "value": "Reverse",
                                },
                            ],
                        },
                        {
                            "name": _("Language"),
                            "class": UITextMenu,
                            "select": "single",
                            "config_option": "language",
                            "post_callback": callbacks.switch_language,
                            "items": [
                                {
                                    "name": _("English"),
                                    "value": "en",
                                },
                                {
                                    "name": _("German"),
                                    "value": "de",
                                },
                                {
                                    "name": _("French"),
                                    "value": "fr",
                                },
                                {
                                    "name": _("Spanish"),
                                    "value": "es",
                                },
                            ],
                        },
                    ],
                },
                {
                    "name": _("Chart..."),
                    "class": UITextMenu,
                    "select": "single",
                    "label": "chart_settings",
                    "items": [
                        {
                            "name": _("Reticle"),
                            "class": UITextMenu,
                            "select": "single",
                            "config_option": "chart_reticle",
                            "items": [
                                {
                                    "name": _("Off"),
                                    "value": 0,
                                },
                                {
                                    "name": _("Low"),
                                    "value": 64,
                                },
                                {
                                    "name": _("Medium"),
                                    "value": 128,
                                },
                                {
                                    "name": _("High"),
                                    "value": 192,
                                },
                            ],
                        },
                        {
                            "name": _("Constellation"),
                            "class": UITextMenu,
                            "select": "single",
                            "config_option": "chart_constellations",
                            "items": [
                                {
                                    "name": _("Off"),
                                    "value": 0,
                                },
                                {
                                    "name": _("Low"),
                                    "value": 64,
                                },
                                {
                                    "name": _("Medium"),
                                    "value": 128,
                                },
                                {
                                    "name": _("High"),
                                    "value": 192,
                                },
                            ],
                        },
                        {
                            "name": _("DSO Display"),
                            "class": UITextMenu,
                            "select": "single",
                            "config_option": "chart_dso",
                            "items": [
                                {
                                    "name": _("Off"),
                                    "value": 0,
                                },
                                {
                                    "name": _("Low"),
                                    "value": 64,
                                },
                                {
                                    "name": _("Medium"),
                                    "value": 128,
                                },
                                {
                                    "name": _("High"),
                                    "value": 192,
                                },
                            ],
                        },
                        {
                            "name": _("RA/DEC Disp."),
                            "class": UITextMenu,
                            "select": "single",
                            "config_option": "chart_radec",
                            "items": [
                                {
                                    "name": _("Off"),
                                    "value": "Off",
                                },
                                {
                                    "name": _("HH:MM"),
                                    "value": "HH:MM",
                                },
                                {
                                    "name": _("Degrees"),
                                    "value": "Degr",
                                },
                            ],
                        },
                    ],
                },
                {
                    "name": _("Camera Exp"),
                    "class": UITextMenu,
                    "select": "single",
                    "config_option": "camera_exp",
                    "label": "camera_exposure",
                    "post_callback": callbacks.set_exposure,
                    "items": [
                        {
                            "name": _("0.025s"),
                            "value": 25000,
                        },
                        {
                            "name": _("0.05s"),
                            "value": 50000,
                        },
                        {
                            "name": _("0.1s"),
                            "value": 100000,
                        },
                        {
                            "name": _("0.2s"),
                            "value": 200000,
                        },
                        {
                            "name": _("0.4s"),
                            "value": 400000,
                        },
                        {
                            "name": _("0.8s"),
                            "value": 800000,
                        },
                        {
                            "name": _("1s"),
                            "value": 1000000,
                        },
                    ],
                },
                {
                    "name": _("WiFi Mode"),
                    "class": UITextMenu,
                    "select": "single",
                    "value_callback": callbacks.get_wifi_mode,
                    "items": [
                        {
                            "name": _("Client Mode"),
                            "value": "Client",
                            "callback": callbacks.go_wifi_cli,
                        },
                        {
                            "name": _("AP Mode"),
                            "value": "AP",
                            "callback": callbacks.go_wifi_ap,
                        },
                    ],
                },
                {
                    "name": _("Mount Type"),
                    "class": UITextMenu,
                    "select": "single",
                    "config_option": "mount_type",
                    "post_callback": callbacks.restart_pifinder,
                    "items": [
                        {
                            "name": _("Alt/Az"),
                            "value": "Alt/Az",
                        },
                        {
                            "name": _("Equitorial"),
                            "value": "EQ",
                        },
                    ],
                },
                {
                    "name": _("Advanced"),
                    "class": UITextMenu,
                    "select": "single",
                    "pre_callback": callbacks.show_advanced_message,
                    "items": [
                        {
                            "name": _("PiFinder Type"),
                            "class": UITextMenu,
                            "select": "single",
                            "config_option": "screen_direction",
                            "post_callback": callbacks.restart_pifinder,
                            "items": [
                                {
                                    "name": _("Left"),
                                    "value": "left",
                                },
                                {
                                    "name": _("Right"),
                                    "value": "right",
                                },
                                {
                                    "name": _("Straight"),
                                    "value": "straight",
                                },
                                {
                                    "name": _("Flat v3"),
                                    "value": "flat3",
                                },
                                {
                                    "name": _("Flat v2"),
                                    "value": "flat",
                                },
                                {
                                    "name": _("AS Bloom"),
                                    "value": "as_bloom",
                                },
                            ],
                        },
                        {
                            "name": _("Camera Type"),
                            "class": UITextMenu,
                            "select": "single",
                            "value_callback": callbacks.get_camera_type,
                            "items": [
                                {
                                    "name": _("v2 - imx477"),
                                    "callback": callbacks.switch_cam_imx477,
                                    "value": "imx477",
                                },
                                {
                                    "name": _("v3 - imx296"),
                                    "callback": callbacks.switch_cam_imx296,
                                    "value": "imx296",
                                },
                                {
                                    "name": _("v3 - imx462"),
                                    "callback": callbacks.switch_cam_imx462,
                                    "value": "imx462",
                                },
                            ],
                        },
                        {
                            "name": _("GPS Settings"),
                            "class": UITextMenu,
                            "select": "single",
                            "items": [
                                {
                                    "name": _("GPS Type"),
                                    "class": UITextMenu,
                                    "select": "single",
                                    "config_option": "gps_type",
                                    "label": "gps_type",
                                    "post_callback": callbacks.restart_pifinder,
                                    "items": [
                                        {
                                            "name": _("UBlox"),
                                            "value": "ublox",
                                        },
                                        {
                                            "name": _("GPSD (generic)"),
                                            "value": "gpsd",
                                        },
                                    ],
                                },
                                {
                                    "name": _("GPS Baud Rate"),
                                    "class": UITextMenu,
                                    "select": "single",
                                    "config_option": "gps_baud_rate",
                                    "label": "gps_baud_rate",
                                    "post_callback": callbacks.update_gpsd_baud_rate,
                                    "items": [
                                        {
                                            "name": _("9600 (standard)"),
                                            "value": 9600,
                                        },
                                        {
                                            "name": _("115200 (UBlox-10)"),
                                            "value": 115200,
                                        },
                                    ],
                                },
                            ],
                        },
                    ],
                },
                {
                    "name": _("IMU Sensit."),
                    "class": UITextMenu,
                    "select": "single",
                    "config_option": "imu_threshold_scale",
                    "post_callback": callbacks.restart_pifinder,
                    "items": [
                        {
                            "name": _("Off"),
                            "value": 100,
                        },
                        {
                            "name": _("Very Low"),
                            "value": 3,
                        },
                        {
                            "name": _("Low"),
                            "value": 2,
                        },
                        {
                            "name": _("Medium"),
                            "value": 1,
                        },
                        {
                            "name": _("High"),
                            "value": 0.5,
                        },
                    ],
                },
            ],
        },
        {
            "name": _("Tools"),
            "class": UITextMenu,
            "select": "single",
            "items": [
                {"name": _("Status"), "class": UIStatus},
                {"name": _("Equipment"), "class": UIEquipment, "label": "equipment"},
                {
                    "name": _("Place & Time"),
                    "class": UITextMenu,
                    "select": "single",
                    "items": [
                        {
                            "name": _("GPS Status"),
                            "class": UIGPSStatus,
                        },
                        {
                            "name": _("Set Location"),
                            "class": UILocationList,
                        },
                        {
                            "name": _("Set Time"),
                            "class": UITimeEntry,
                            "custom_callback": callbacks.set_time,
                        },
                        {"name": _("Reset"), "callback": callbacks.gps_reset},
                    ],
                },
                {"name": _("Console"), "class": UIConsole},
                {"name": _("Software Upd"), "class": UISoftware},
                {"name": _("Test Mode"), "callback": callbacks.activate_debug},
                {
                    "name": _("Power"),
                    "class": UITextMenu,
                    "select": "Single",
                    "label": "power",
                    "items": [
                        {
                            "name": _("Shutdown"),
                            "class": UITextMenu,
                            "select": "Single",
                            "label": "shutdown",
                            "items": [
                                {"name": "Confirm", "callback": callbacks.shutdown},
                                {"name": "Cancel", "callback": callbacks.go_back},
                            ],
                        },
                        {
                            "name": _("Restart"),
                            "class": UITextMenu,
                            "select": "Single",
                            "label": "restart",
                            "items": [
                                {
                                    "name": _("Confirm"),
                                    "callback": callbacks.restart_system,
                                },
                                {"name": _("Cancel"), "callback": callbacks.go_back},
                            ],
                        },
                    ],
                },
                {
                    "name": _("Experimental"),
                    "class": UITextMenu,
                    "select": "Single",
                    "items": [],
                },
            ],
        },
    ],
}


# Remove local definition and reactivate the global gettext function (that translates)
del _
