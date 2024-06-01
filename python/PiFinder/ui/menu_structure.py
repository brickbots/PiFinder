from PiFinder.ui.chart import UIChart
from PiFinder.ui.text_meuu import UITextMenu
from PiFinder.ui.nearby import UINearby
from PiFinder.ui.preview import UIPreview
from PiFinder.ui.status import UIStatus
from PiFinder.ui.catalog import UICatalog
from PiFinder.ui.locate import UILocate
from PiFinder.ui.log import UILog

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
                    "class": "screen",
                    "class": "",
                },
                {
                    "name": "Altitude",
                    "class": "config",
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
                {
                    "name": "List",
                    "class": "screen",
                    "class": "",
                },
                {
                    "name": "Catalogs",
                    "class": "screen",
                    "class": "",
                },
                {
                    "name": "Nearby",
                    "class": "screen",
                    "class": "",
                },
                {
                    "name": "Name Search",
                    "class": "screen",
                    "class": "",
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
                    "name": "Keypad Brightness",
                    "class": "config",
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
            ],
        },
    ],
}
