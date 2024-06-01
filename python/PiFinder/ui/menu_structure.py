from PiFinder.ui.chart import UIChart
from PiFinder.ui.nearby import UINearby
from PiFinder.ui.preview import UIPreview
from PiFinder.ui.status import UIStatus
from PiFinder.ui.catalog import UICatalog
from PiFinder.ui.locate import UILocate
from PiFinder.ui.config import UIConfig
from PiFinder.ui.log import UILog

pifinder_menu = {
    "name": "PiFinder",
    "type": "text",
    "select": "single",
    "items": [
        {
            "name": "Filter",
            "type": "text",
            "select": "single",
            "items": [
                {
                    "name": "Catalogs",
                    "type": "screen",
                    "class": "",
                },
                {
                    "name": "Altitude",
                    "type": "config",
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
            "type": "text",
            "select": "single",
            "items": [
                {
                    "name": "List",
                    "type": "screen",
                    "class": "",
                },
                {
                    "name": "Catalogs",
                    "type": "screen",
                    "class": "",
                },
                {
                    "name": "Nearby",
                    "type": "screen",
                    "class": "",
                },
                {
                    "name": "Name Search",
                    "type": "screen",
                    "class": "",
                },
            ],
        },
        {
            "name": "Chart",
            "type": "screen",
            "class": "",
        },
        {
            "name": "Camera",
            "type": "screen",
            "class": "",
        },
        {
            "name": "Settings",
            "type": "text",
            "select": "single",
            "items": [
                {
                    "name": "Keypad Brightness",
                    "type": "config",
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
