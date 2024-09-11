from PiFinder.ui.text_menu import UITextMenu
from PiFinder.ui.object_list import UIObjectList
from PiFinder.ui.status import UIStatus
from PiFinder.ui.console import UIConsole
from PiFinder.ui.software import UISoftware
from PiFinder.ui.chart import UIChart
from PiFinder.ui.align import UIAlign
from PiFinder.ui.textentry import UITextEntry
from PiFinder.ui.preview import UIPreview
import PiFinder.ui.callbacks as callbacks

pifinder_menu = {
    "name": "PiFinder",
    "class": UITextMenu,
    "select": "single",
    "start_index": 2,
    "items": [
        {
            "name": "Camera",
            "class": UIPreview,
        },
        {
            "name": "Chart",
            "class": UIChart,
            "stateful": True,
            "preload": True,
        },
        {
            "name": "Objects",
            "class": UITextMenu,
            "select": "single",
            "items": [
                {
                    "name": "All Filtered",
                    "class": UIObjectList,
                    "objects": "catalogs.filtered",
                },
                {
                    "name": "By Catalog",
                    "class": UITextMenu,
                    "select": "single",
                    "items": [
                        {
                            "name": "Planets",
                            "class": UIObjectList,
                            "objects": "catalog",
                            "value": "PL",
                        },
                        {
                            "name": "NGC",
                            "class": UIObjectList,
                            "objects": "catalog",
                            "value": "NGC",
                        },
                        {
                            "name": "Messier",
                            "class": UIObjectList,
                            "objects": "catalog",
                            "value": "M",
                        },
                        {
                            "name": "DSO...",
                            "class": UITextMenu,
                            "select": "single",
                            "items": [
                                {
                                    "name": "Abell Pn",
                                    "class": UIObjectList,
                                    "objects": "catalog",
                                    "value": "Abl",
                                },
                                {
                                    "name": "Arp Galaxies",
                                    "class": UIObjectList,
                                    "objects": "catalog",
                                    "value": "Arp",
                                },
                                {
                                    "name": "Barnard",
                                    "class": UIObjectList,
                                    "objects": "catalog",
                                    "value": "B",
                                },
                                {
                                    "name": "Caldwell",
                                    "class": UIObjectList,
                                    "objects": "catalog",
                                    "value": "C",
                                },
                                {
                                    "name": "Collinder",
                                    "class": UIObjectList,
                                    "objects": "catalog",
                                    "value": "Col",
                                },
                                {
                                    "name": "E.G. Globs",
                                    "class": UIObjectList,
                                    "objects": "catalog",
                                    "value": "EGC",
                                },
                                {
                                    "name": "Herschel 400",
                                    "class": UIObjectList,
                                    "objects": "catalog",
                                    "value": "H",
                                },
                                {
                                    "name": "IC",
                                    "class": UIObjectList,
                                    "objects": "catalog",
                                    "value": "IC",
                                },
                                {
                                    "name": "Messier",
                                    "class": UIObjectList,
                                    "objects": "catalog",
                                    "value": "M",
                                },
                                {
                                    "name": "NGC",
                                    "class": UIObjectList,
                                    "objects": "catalog",
                                    "value": "NGC",
                                },
                                {
                                    "name": "Sharpless",
                                    "class": UIObjectList,
                                    "objects": "catalog",
                                    "value": "Sh2",
                                },
                                {
                                    "name": "TAAS 200",
                                    "class": UIObjectList,
                                    "objects": "catalog",
                                    "value": "Ta2",
                                },
                            ],
                        },
                        {
                            "name": "Stars...",
                            "class": UITextMenu,
                            "select": "single",
                            "items": [
                                {
                                    "name": "Bright Named",
                                    "class": UIObjectList,
                                    "objects": "catalog",
                                    "value": "Str",
                                },
                                {
                                    "name": "SAC Doubles",
                                    "class": UIObjectList,
                                    "objects": "catalog",
                                    "value": "SaM",
                                },
                                {
                                    "name": "SAC Asterisms",
                                    "class": UIObjectList,
                                    "objects": "catalog",
                                    "value": "SaA",
                                },
                                {
                                    "name": "SAC Red Stars",
                                    "class": UIObjectList,
                                    "objects": "catalog",
                                    "value": "SaR",
                                },
                                {
                                    "name": "RASC Doubles",
                                    "class": UIObjectList,
                                    "objects": "catalog",
                                    "value": "RDS",
                                },
                                {
                                    "name": "TLK 90 Variables",
                                    "class": UIObjectList,
                                    "objects": "catalog",
                                    "value": "TLK",
                                },
                            ],
                        },
                    ],
                },
                {
                    "name": "Recent",
                    "class": UIObjectList,
                    "objects": "recent",
                    "label": "recent",
                },
                {
                    "name": "Name Search",
                    "class": UITextEntry,
                },
            ],
        },
        {
            "name": "Filter",
            "class": UITextMenu,
            "select": "single",
            "label": "filter_options",
            "items": [
                {
                    "name": "Reset All",
                    "class": UITextMenu,
                    "select": "Single",
                    "items": [
                        {"name": "Confirm", "callback": callbacks.reset_filters},
                        {"name": "Cancel", "callback": callbacks.go_back},
                    ],
                },
                {
                    "name": "Catalogs",
                    "class": UITextMenu,
                    "select": "multi",
                    "config_option": "active_catalogs",
                    "items": [
                        {
                            "name": "Planets",
                            "value": "PL",
                        },
                        {
                            "name": "NGC",
                            "value": "NGC",
                        },
                        {
                            "name": "Messier",
                            "value": "M",
                        },
                        {
                            "name": "DSO...",
                            "class": UITextMenu,
                            "select": "multi",
                            "config_option": "active_catalogs",
                            "items": [
                                {
                                    "name": "Abell Pn",
                                    "value": "Abl",
                                },
                                {
                                    "name": "Arp Galaxies",
                                    "value": "Arp",
                                },
                                {
                                    "name": "Barnard",
                                    "value": "B",
                                },
                                {
                                    "name": "Caldwell",
                                    "value": "C",
                                },
                                {
                                    "name": "Collinder",
                                    "value": "Col",
                                },
                                {
                                    "name": "E.G. Globs",
                                    "value": "EGC",
                                },
                                {
                                    "name": "Herschel 400",
                                    "value": "H",
                                },
                                {
                                    "name": "IC",
                                    "value": "IC",
                                },
                                {
                                    "name": "Messier",
                                    "value": "M",
                                },
                                {
                                    "name": "NGC",
                                    "value": "NGC",
                                },
                                {
                                    "name": "Sharpless",
                                    "value": "Sh2",
                                },
                                {
                                    "name": "TAAS 200",
                                    "value": "Ta2",
                                },
                            ],
                        },
                        {
                            "name": "Stars...",
                            "class": UITextMenu,
                            "select": "multi",
                            "config_option": "active_catalogs",
                            "items": [
                                {
                                    "name": "Bright Named",
                                    "value": "Str",
                                },
                                {
                                    "name": "SAC Doubles",
                                    "value": "SaM",
                                },
                                {
                                    "name": "SAC Asterisms",
                                    "value": "SaA",
                                },
                                {
                                    "name": "SAC Red Stars",
                                    "value": "SaR",
                                },
                                {
                                    "name": "RASC Doubles",
                                    "value": "RDS",
                                },
                                {
                                    "name": "TLK 90 Variables",
                                    "value": "TLK",
                                },
                            ],
                        },
                    ],
                },
                {
                    "name": "Type",
                    "class": UITextMenu,
                    "select": "multi",
                    "config_option": "filter.object_types",
                    "items": [
                        {
                            "name": "Galaxy",
                            "value": "Gx",
                        },
                        {
                            "name": "Open Cluster",
                            "value": "OC",
                        },
                        {
                            "name": "Globular",
                            "value": "Gb",
                        },
                        {
                            "name": "Nebula",
                            "value": "Nb",
                        },
                        {
                            "name": "P. Nebula",
                            "value": "Pl",
                        },
                        {
                            "name": "Double Str",
                            "value": "D*",
                        },
                        {
                            "name": "Asterism",
                            "value": "Ast",
                        },
                        {
                            "name": "Planet",
                            "value": "Pla",
                        },
                    ],
                },
                {
                    "name": "Altitude",
                    "class": UITextMenu,
                    "select": "single",
                    "config_option": "filter.altitude",
                    "items": [
                        {
                            "name": "None",
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
                    "name": "Magnitude",
                    "class": UITextMenu,
                    "select": "single",
                    "config_option": "filter.magnitude",
                    "items": [
                        {
                            "name": "None",
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
                    "name": "Observed",
                    "class": UITextMenu,
                    "select": "single",
                    "config_option": "filter.observed",
                    "items": [
                        {
                            "name": "Any",
                            "value": "Any",
                        },
                        {
                            "name": "Observed",
                            "value": "Yes",
                        },
                        {
                            "name": "Not Observed",
                            "value": "No",
                        },
                    ],
                },
            ],
        },
        {
            "name": "Settings",
            "class": UITextMenu,
            "select": "single",
            "items": [
                {
                    "name": "User Pref...",
                    "class": UITextMenu,
                    "select": "single",
                    "items": [
                        {
                            "name": "Key Bright",
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
                            "name": "Sleep Time",
                            "class": UITextMenu,
                            "select": "single",
                            "config_option": "sleep_timeout",
                            "items": [
                                {
                                    "name": "Off",
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
                            "name": "Menu Anim",
                            "class": UITextMenu,
                            "select": "single",
                            "config_option": "menu_anim_speed",
                            "items": [
                                {
                                    "name": "Off",
                                    "value": 0,
                                },
                                {
                                    "name": "Fast",
                                    "value": 0.05,
                                },
                                {
                                    "name": "Medium",
                                    "value": 0.1,
                                },
                                {
                                    "name": "Slow",
                                    "value": 0.2,
                                },
                            ],
                        },
                        {
                            "name": "Scroll Speed",
                            "class": UITextMenu,
                            "select": "single",
                            "config_option": "text_scroll_speed",
                            "items": [
                                {
                                    "name": "Off",
                                    "value": "Off",
                                },
                                {
                                    "name": "Fast",
                                    "value": "Fast",
                                },
                                {
                                    "name": "Medium",
                                    "value": "Med",
                                },
                                {
                                    "name": "Slow",
                                    "value": "Slow",
                                },
                            ],
                        },
                    ],
                },
                {
                    "name": "Chart...",
                    "class": UITextMenu,
                    "select": "single",
                    "label": "chart_settings",
                    "items": [
                        {
                            "name": "Reticle",
                            "class": UITextMenu,
                            "select": "single",
                            "config_option": "chart_reticle",
                            "items": [
                                {
                                    "name": "Off",
                                    "value": 0,
                                },
                                {
                                    "name": "Low",
                                    "value": 64,
                                },
                                {
                                    "name": "Medium",
                                    "value": 128,
                                },
                                {
                                    "name": "High",
                                    "value": 192,
                                },
                            ],
                        },
                        {
                            "name": "Constellation",
                            "class": UITextMenu,
                            "select": "single",
                            "config_option": "chart_constellations",
                            "items": [
                                {
                                    "name": "Off",
                                    "value": 0,
                                },
                                {
                                    "name": "Low",
                                    "value": 64,
                                },
                                {
                                    "name": "Medium",
                                    "value": 128,
                                },
                                {
                                    "name": "High",
                                    "value": 192,
                                },
                            ],
                        },
                        {
                            "name": "DSO Display",
                            "class": UITextMenu,
                            "select": "single",
                            "config_option": "chart_dso",
                            "items": [
                                {
                                    "name": "Off",
                                    "value": 0,
                                },
                                {
                                    "name": "Low",
                                    "value": 64,
                                },
                                {
                                    "name": "Medium",
                                    "value": 128,
                                },
                                {
                                    "name": "High",
                                    "value": 192,
                                },
                            ],
                        },
                        {
                            "name": "RA/DEC Disp.",
                            "class": UITextMenu,
                            "select": "single",
                            "config_option": "chart_radec",
                            "items": [
                                {
                                    "name": "Off",
                                    "value": "Off",
                                },
                                {
                                    "name": "HH:MM",
                                    "value": "HH:MM",
                                },
                                {
                                    "name": "Degrees",
                                    "value": "Degr",
                                },
                            ],
                        },
                    ],
                },
                {
                    "name": "Camera Exp",
                    "class": UITextMenu,
                    "select": "single",
                    "config_option": "camera_exp",
                    "label": "camera_exposure",
                    "post_callback": callbacks.set_exposure,
                    "items": [
                        {
                            "name": "0.025s",
                            "value": 25000,
                        },
                        {
                            "name": "0.05s",
                            "value": 50000,
                        },
                        {
                            "name": "0.1s",
                            "value": 100000,
                        },
                        {
                            "name": "0.2s",
                            "value": 200000,
                        },
                        {
                            "name": "0.4s",
                            "value": 400000,
                        },
                        {
                            "name": "0.8s",
                            "value": 800000,
                        },
                        {
                            "name": "1s",
                            "value": 1000000,
                        },
                    ],
                },
                {
                    "name": "WiFi Mode",
                    "class": UITextMenu,
                    "select": "single",
                    "items": [
                        {"name": "Client Mode", "callback": callbacks.go_wifi_cli},
                        {"name": "AP Mode", "callback": callbacks.go_wifi_ap},
                    ],
                },
                {
                    "name": "PiFinder Type",
                    "class": UITextMenu,
                    "select": "single",
                    "config_option": "screen_direction",
                    "post_callback": callbacks.restart_pifinder,
                    "items": [
                        {
                            "name": "Left",
                            "value": "left",
                        },
                        {
                            "name": "Right",
                            "value": "right",
                        },
                        {
                            "name": "Straight",
                            "value": "straight",
                        },
                        {
                            "name": "Flat v3",
                            "value": "flat3",
                        },
                        {
                            "name": "Flat v2",
                            "value": "flat",
                        },
                    ],
                },
                {
                    "name": "Mount Type",
                    "class": UITextMenu,
                    "select": "single",
                    "config_option": "mount_type",
                    "post_callback": callbacks.restart_pifinder,
                    "items": [
                        {
                            "name": "Alt/Az",
                            "value": "Alt/Az",
                        },
                        {
                            "name": "Equitorial",
                            "value": "EQ",
                        },
                    ],
                },
                {
                    "name": "Camera Type",
                    "class": UITextMenu,
                    "select": "single",
                    "items": [
                        {
                            "name": "v2 - imx477",
                            "callback": callbacks.switch_cam_imx477,
                        },
                        {
                            "name": "v3 - imx296",
                            "callback": callbacks.switch_cam_imx296,
                        },
                    ],
                },
            ],
        },
        {
            "name": "Tools",
            "class": UITextMenu,
            "select": "single",
            "items": [
                {"name": "Status", "class": UIStatus},
                {"name": "Console", "class": UIConsole},
                {"name": "Software Upd", "class": UISoftware},
                {"name": "Test Mode", "callback": callbacks.activate_debug},
                {
                    "name": "Shutdown",
                    "class": UITextMenu,
                    "select": "Single",
                    "label": "shutdown",
                    "items": [
                        {"name": "Confirm", "callback": callbacks.shutdown},
                        {"name": "Cancel", "callback": callbacks.go_back},
                    ],
                },
                {
                    "name": "Experimental",
                    "class": UITextMenu,
                    "select": "Single",
                    "items": [
                        {
                            "name": "Align",
                            "class": UIAlign,
                            "stateful": True,
                            "preload": True,
                        },
                    ],
                },
            ],
        },
    ],
}
