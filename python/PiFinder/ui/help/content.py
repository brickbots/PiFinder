"""
Help content definitions with Babel translation support.

This module provides help content for all UI screens in the PiFinder application.
Content is organized by module name matching __help_name__ attributes from the UI classes.

Structure:
- Each help module contains one or more pages
- Pages have titles, content (icon/action pairs or text), and optional navigation
- All text strings use _() for internationalization via Babel
- Icons use descriptive names that get resolved to actual glyphs by the renderer

UI Module Mapping:
- align.py → "align"
- preview.py → "camera" 
- chart.py → "chart"
- equipment.py → "equipment"
- gpsstatus.py → "gpsstatus"
- log.py → "log"
- object_details.py → "object_details"
- object_list.py → "object_list"
- status.py → "status"
- text_menu.py → "menu"
"""

import PiFinder.i18n  # noqa: F401  # Enables _() function for translations


def get_help_content():
    """
    Returns help content structure for all UI modules.
    Content is organized by module name matching __help_name__ attributes.
    Icons use descriptive names that get resolved to actual glyphs by the renderer.
    """
    return {
        # ========================================================================
        # CORE FUNCTIONALITY MODULES
        # ========================================================================
        
        "align": {
            # Telescope alignment and plate solving functionality
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
            # Live camera preview and image capture controls
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
                        },
                        {
                            "text": _("CAMERA shows a live preview with zoom and align features")
                        }
                    ]
                }
            ]
        },
        
        "chart": {
            # Star chart display with constellation lines and DSO plotting
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
                        },
                        {
                            "text": _("You can set the brightness of display elements in the settings menu")
                        }
                    ]
                }
            ]
        },

        # ========================================================================
        # OBJECT MANAGEMENT MODULES
        # ========================================================================
        
        "object_details": {
            # Individual astronomical object information and actions
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
                        },
                        {
                            "text": _("The OBJECT DETAILS page shows info on the currently selected object")
                        },
                        {
                            "text": _("Use Square to cycle through catalog details, image and push-to instructions")
                        }
                    ]
                }
            ]
        },
        
        "object_list": {
            # Astronomical object catalog browsing and filtering
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
                        },
                        {
                            "text": _("The OBJECT LIST is sortable via the Radial Menu and you can")
                        },
                        {
                            "text": _("cycle thru object info using the Square key")
                        },
                        {
                            "text": _("Type a number to jump to a specific object or use Square to exit")
                        }
                    ]
                }
            ]
        },

        # ========================================================================
        # OBSERVING SESSION MODULES
        # ========================================================================
        
        "log": {
            # Observation logging and session management
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
                        },
                        {
                            "text": _("Writes an entry to the log of your observing session. Set ratings and choose SAVE")
                        }
                    ]
                }
            ]
        },

        # ========================================================================
        # SYSTEM AND CONFIGURATION MODULES
        # ========================================================================
        
        "gpsstatus": {
            # GPS status, location management and satellite information
            "pages": [
                {
                    "title": _("GPS STATUS"),
                    "content": [
                        {
                            "icon": "LEFT",
                            "action": _("Save")
                        },
                        {
                            "icon": "RIGHT",
                            "action": _("Lock")
                        },
                        {
                            "icon": "SQUARE",
                            "action": _("Toggle Details")
                        },
                        {
                            "text": _("Shows GPS satellite lock status and location accuracy. Use Save to store the current location or Lock to use manual coordinates.")
                        }
                    ]
                }
            ]
        },

        "equipment": {
            # Telescope and eyepiece selection and configuration
            "pages": [
                {
                    "title": _("EQUIPMENT"),
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
                            "icon": "LEFT",
                            "action": _("Back")
                        },
                        {
                            "text": _("Select your telescope and eyepiece to calculate magnification and field of view. This affects object visibility and targeting accuracy.")
                        }
                    ]
                }
            ]
        },

        "status": {
            # System status and hardware information display
            "pages": [
                {
                    "title": _("STATUS"),
                    "content": [
                        {
                            "icon": "UP_DOWN",
                            "action": _("Scroll")
                        },
                        {
                            "text": _("Displays system information including GPS status, sensor readings, and hardware configuration.")
                        }
                    ]
                }
            ]
        },

        # ========================================================================
        # NAVIGATION AND INTERFACE MODULES
        # ========================================================================
        
        "menu": {
            # General menu navigation and interface help
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
                        },
                        {
                            "text": _("Thank you for using a PiFinder")
                        }
                    ]
                }
            ]
        }
    }