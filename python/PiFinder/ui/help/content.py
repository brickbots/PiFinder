"""
Help content definitions with Babel translation support.
All text strings use _() for internationalization.
Icons use descriptive names that get resolved by the renderer.
"""

import PiFinder.i18n  # noqa: F401  # Enables _() function for translations

def get_help_content():
    """
    Returns help content structure for all UI modules.
    Content is organized by module name matching __help_name__ attributes.
    Icons use descriptive names that get resolved to actual glyphs by the renderer.
    """
    return {
        "align": {
            "pages": [
                {
                    "title": _("ALIGN HELP"),
                    "content": [
                        {
                            "icon": "PLUS_MINUS",
                            "action": _("Zoom")
                        },
                        {
                            "icon": "SQUARE",
                            "action": _("Align")
                        },
                        {
                            "icon": "NUMBER_0",
                            "action": _("Abort")
                        },
                        {
                            "icon": "NUMBER_1",
                            "action": _("Reset")
                        },
                        {
                            "text": _("The Align screen is for telling the PiFinder where in the sky your telescope is pointing so that it can make sure DSOs end up in your eyepiece. Point your scope at a star that is recognizable to start and press Square to start alignment and use the arrow keys to select the star your telescope is pointing to. When finished press Square again to set the alignment.")
                        }
                    ]
                }
            ]
        },
        
        "camera": {
            "pages": [
                {
                    "title": _("CAMERA HELP"),
                    "content": [
                        {
                            "icon": "SQUARE",
                            "action": _("Align")
                        },
                        {
                            "icon": "PLUS_MINUS",
                            "action": _("Zoom")
                        }
                    ],
                    "footer": _("more")
                },
                {
                    "title": _("CAMERA HELP"),
                    "content": [
                        {
                            "text": _("CAMERA shows a live preview with zoom and align features")
                        }
                    ],
                    "navigation": {
                        "up": _("more")
                    }
                }
            ]
        },
        
        "chart": {
            "pages": [
                {
                    "title": _("CHART HELP"),
                    "content": [
                        {
                            "icon": "PLUS_MINUS",
                            "action": _("Zoom")
                        },
                        {
                            "text": _("A star chart with constellation lines and DSOs plotted")
                        }
                    ],
                    "footer": _("more")
                },
                {
                    "title": _("CHART HELP"),
                    "content": [
                        {
                            "text": _("You can set the brightness of display elements in the settings menu")
                        }
                    ],
                    "navigation": {
                        "up": _("more")
                    }
                }
            ]
        },
        
        "log": {
            "pages": [
                {
                    "title": _("LOGGING HELP"),
                    "content": [
                        {
                            "icon": "UP_DOWN",
                            "action": _("Choose")
                        },
                        {
                            "icon": "RIGHT",
                            "action": _("Select")
                        },
                        {
                            "icon": "NUMBERS_0_5",
                            "action": _("Stars")
                        }
                    ],
                    "footer": _("more")
                },
                {
                    "title": _("LOGGING HELP"),
                    "content": [
                        {
                            "text": _("Writes an entry to the log of your observing session. Set ratings and choose SAVE")
                        }
                    ],
                    "navigation": {
                        "up": _("more")
                    }
                }
            ]
        },
        
        "menu": {
            "pages": [
                {
                    "title": _("MENU HELP"),
                    "content": [
                        {
                            "icon": "UP_DOWN",
                            "action": _("Scroll")
                        },
                        {
                            "icon": "RIGHT",
                            "action": _("Select")
                        },
                        {
                            "icon": "LEFT",
                            "action": _("Back")
                        }
                    ],
                    "footer": _("more")
                },
                {
                    "title": _("MENU HELP"),
                    "content": [
                        {
                            "text": _("Thank you for using a PiFinder")
                        }
                    ],
                    "navigation": {
                        "up": _("more")
                    }
                }
            ]
        },
        
        "object_details": {
            "pages": [
                {
                    "title": _("OBJECT DETAILS"),
                    "content": [
                        {
                            "icon": "UP_DOWN",
                            "action": _("Scroll")
                        },
                        {
                            "icon": "RIGHT",
                            "action": _("Log")
                        },
                        {
                            "icon": "SQUARE",
                            "action": _("Switch Info")
                        }
                    ],
                    "footer": _("more")
                },
                {
                    "title": _("OBJECT DETAILS"),
                    "content": [
                        {
                            "text": _("The OBJECT DETAILS page shows info on the currently selected object")
                        }
                    ],
                    "navigation": {
                        "up": _("more"),
                        "down": _("more")
                    }
                },
                {
                    "title": _("OBJECT DETAILS"),
                    "content": [
                        {
                            "text": _("Use Square to cycle through catalog details, image and push-to instructions")
                        }
                    ],
                    "navigation": {
                        "up": _("more")
                    }
                }
            ]
        },
        
        "object_list": {
            "pages": [
                {
                    "title": _("OBJECT LIST"),
                    "content": [
                        {
                            "icon": "UP_DOWN",
                            "action": _("Scroll")
                        },
                        {
                            "icon": "RIGHT",
                            "action": _("Select")
                        },
                        {
                            "icon": "LEFT",
                            "action": _("Back")
                        },
                        {
                            "icon": "NUMBERS_0_9",
                            "action": _("Jump To")
                        }
                    ],
                    "footer": _("more")
                },
                {
                    "title": _("OBJECT LIST"),
                    "content": [
                        {
                            "text": _("The OBJECT LIST is sortable via the Radial Menu and you can")
                        }
                    ],
                    "navigation": {
                        "up": _("more"),
                        "down": _("more")
                    }
                },
                {
                    "title": _("OBJECT LIST"),
                    "content": [
                        {
                            "text": _("cycle thru object info using the Square key")
                        }
                    ],
                    "navigation": {
                        "up": _("more"),
                        "down": _("more")
                    }
                },
                {
                    "title": _("OBJECT LIST"),
                    "content": [
                        {
                            "text": _("Type a number to jump to a specific object or use Square to exit")
                        }
                    ],
                    "navigation": {
                        "up": _("more")
                    }
                }
            ]
        }
    }