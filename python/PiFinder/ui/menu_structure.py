from PiFinder.ui.text_menu import UITextMenu
from PiFinder.ui.object_list import UIObjectList
from PiFinder.ui.status import UIStatus
from PiFinder.ui.software import UISoftware

pifinder_menu = {
    "name": "PiFinder",
    "class": UITextMenu,
    "select": "single",
    "items": [
        {
            "name": "Filter",
            "class": UITextMenu,
            "select": "single",
            "items": [
                {
                    "name": "Catalogs",
                    "class": UITextMenu,
                    "select": "multi",
                    "config_option": "active_catalogs",
                    "items": [
                        {
                            "name": "Planets",
                            "value": "P",
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
                                    "name": "NGC",
                                    "value": "NGC",
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
                                    "name": "Caldwell",
                                    "value": "C",
                                },
                                {
                                    "name": "Collinder",
                                    "value": "Col",
                                },
                                {
                                    "name": "TAAS 200",
                                    "value": "Ta2",
                                },
                                {
                                    "name": "Herschel 400",
                                    "value": "H",
                                },
                                {
                                    "name": "E.G. Globs",
                                    "value": "EGC",
                                },
                                {
                                    "name": "Barnard",
                                    "value": "B",
                                },
                                {
                                    "name": "Sharpless",
                                    "value": "Sh2",
                                },
                                {
                                    "name": "Abell Pn",
                                    "value": "Abl",
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
                                    "value": "STR",
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
                            ],
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
                            "value": "0",
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
                    "config_option": "filter.altitude",
                    "items": [
                        {
                            "name": "None",
                            "value": "0",
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
            ],
        },
        {
            "name": "Objects",
            "class": UITextMenu,
            "select": "single",
            "items": [
                {"name": "List", "class": UIObjectList},
                {
                    "name": "Catalogs",
                    "class": "screen",
                },
                {
                    "name": "Nearby",
                    "class": "screen",
                },
                {
                    "name": "Name Search",
                    "class": "screen",
                },
            ],
        },
        {
            "name": "Chart",
            "class": "screen",
            "class": "",
        },
        {
            "name": "Camera",
            "class": "screen",
            "class": "",
        },
        {
            "name": "Settings",
            "class": UITextMenu,
            "select": "single",
            "items": [
                {
                    "name": "Camera Exp",
                    "class": UITextMenu,
                    "select": "single",
                    "config_option": "camera_exp",
                    "items": [
                        {
                            "name": "0.1s",
                            "value": 0.1,
                        },
                        {
                            "name": "0.2s",
                            "value": 0.2,
                        },
                        {
                            "name": "0.4s",
                            "value": 0.4,
                        },
                        {
                            "name": "0.8s",
                            "value": 0.8,
                        },
                        {
                            "name": "1s",
                            "value": 1,
                        },
                    ],
                },
                {
                    "name": "Key Bright",
                    "class": UITextMenu,
                    "select": "single",
                    "config_option": "keypad_brightness",
                    "items": [
                        {
                            "name": "-3",
                            "value": -3,
                        },
                        {
                            "name": "-2",
                            "value": -2,
                        },
                        {
                            "name": "-1",
                            "value": -1,
                        },
                        {
                            "name": "0",
                            "value": 0,
                        },
                        {
                            "name": "1",
                            "value": 1,
                        },
                        {
                            "name": "2",
                            "value": 2,
                        },
                        {
                            "name": "3",
                            "value": 3,
                        },
                    ],
                },
                {
                    "name": "PiFinder Dir",
                    "class": UITextMenu,
                    "select": "single",
                    "config_option": "screen_direction",
                    "items": [
                        {
                            "name": "Left",
                            "value": "Left",
                        },
                        {
                            "name": "Right",
                            "value": "Right",
                        },
                        {
                            "name": "Flat",
                            "value": "Flat",
                        },
                    ],
                },
                {
                    "name": "Mount Type",
                    "class": UITextMenu,
                    "select": "single",
                    "config_option": "mount_type",
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
            ],
        },
        {
            "name": "Tools",
            "class": UITextMenu,
            "select": "single",
            "items": [
                {"name": "Status", "class": UIStatus},
                {
                    "name": "Software Upd",
                    "class": UISoftware,
                },
            ],
        },
    ],
}
