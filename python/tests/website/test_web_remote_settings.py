import pytest
from web_test_utils import (
    login_to_remote,
    navigate_to_root_menu,
    press_keys,
    press_keys_and_validate,
)

"""
Tests for the Settings menu in PiFinder's remote control interface.

Only software-testable Settings items are covered here. Hardware-dependent
settings (Camera Exp, Mount Type, Advanced, IMU Sensit., Chart...) and items
that trigger a system restart are excluded.

Settings menu (root → DD → R) items (0-indexed):
  0: User Pref...  (submenu)
  1: Chart...      (submenu – not tested: chart rendering params)
  2: Camera Exp    (not tested: hardware camera)
  3: WiFi Mode     (not tested: affects connectivity)
  4: Mount Type    (not tested: triggers restart)
  5: Advanced      (not tested: all sub-items trigger restart)
  6: IMU Sensit.   (not tested: hardware + restart)

User Pref submenu (0-indexed):
  0: Key Bright    (not tested: hardware LED)
  1: Sleep Time    (not tested: hardware display)
  2: Menu Anim     (not tested: animation param)
  3: Scroll Speed  (not tested: animation param)
  4: T9 Search     (not tested: input method)
  5: Az Arrows     (not tested: hardware keypad)
  6: Language      (testable: software language switch)

Language submenu items (0-indexed, values depend on translation):
  English (en), German (de), French (fr), Spanish (es), Chinese (zh)

Key sequences from navigate_to_root_menu() (lands on Objects in root menu):
  DD   → highlight Settings (index 4, 2 downs from Objects=2)
  R    → enter Settings submenu (now at User Pref, index 0)
  R    → enter User Pref submenu (now at Key Bright, index 0)
  DDDDDD → navigate to Language (index 6, 6 downs from Key Bright)
  R    → enter Language submenu
"""

# ---------------------------------------------------------------------------
# Settings menu entry
# ---------------------------------------------------------------------------


@pytest.mark.web
def test_settings_menu_entry(driver):
    """Entering the Settings menu lands on User Pref."""
    login_to_remote(driver)
    navigate_to_root_menu(driver)

    # DD = navigate to Settings in root; R = enter Settings submenu
    press_keys_and_validate(
        driver,
        "DDR",
        {
            "ui_type": "UITextMenu",
            "title": "Settings",
            "current_item": "User Pref...",
        },
    )

    press_keys(driver, "ZL")  # back to root


@pytest.mark.web
def test_settings_user_pref_entry(driver):
    """Settings > User Pref opens the User Pref submenu at Key Bright."""
    login_to_remote(driver)
    navigate_to_root_menu(driver)

    # DDR = enter Settings at User Pref; R = enter User Pref submenu
    press_keys_and_validate(
        driver,
        "DDRR",
        {
            "ui_type": "UITextMenu",
            "title": "User Pref...",
            "current_item": "Key Bright",
        },
    )

    press_keys(driver, "ZL")  # back to root


# ---------------------------------------------------------------------------
# Settings > User Pref > Language
# ---------------------------------------------------------------------------


@pytest.mark.web
def test_settings_language_submenu_entry(driver):
    """Settings > User Pref > Language opens the language selection menu."""
    login_to_remote(driver)
    navigate_to_root_menu(driver)

    # DDR = enter Settings; R = enter User Pref at Key Bright (0)
    # DDDDDD = navigate to Language (index 6); R = enter Language submenu
    press_keys_and_validate(
        driver,
        "DDRRDDDDDDR",
        {
            "ui_type": "UITextMenu",
            "title": "Language",
        },
    )

    press_keys(driver, "ZL")  # back to root


@pytest.mark.web
def test_settings_language_has_english_default(driver):
    """The Language menu shows English as the first (default) entry."""
    login_to_remote(driver)
    navigate_to_root_menu(driver)

    # Navigate to Language submenu
    press_keys_and_validate(
        driver,
        "DDRRDDDDDDR",
        {
            "ui_type": "UITextMenu",
            "title": "Language",
        },
    )

    # Navigate to top of the list (many UPs to guarantee we are at index 0)
    # and verify current_item contains "en" or "English"
    result = press_keys_and_validate(
        driver,
        "UUUUUU",  # wrap to top – Language menu has 5 items, 5+ UPs → index 0
        {
            "ui_type": "UITextMenu",
            "title": "Language",
        },
    )

    # The first language entry should represent English.
    # The exact label depends on the translation config (e.g. "Language: en").
    first_item = result.get("current_item", "")
    assert "en" in first_item.lower() or "english" in first_item.lower(), (
        f"Expected first Language entry to be English, got: {first_item!r}"
    )

    press_keys(driver, "ZL")  # back to root


@pytest.mark.web
def test_settings_language_select_german_and_restore(driver):
    """Select German language and immediately restore English."""
    login_to_remote(driver)
    navigate_to_root_menu(driver)

    # Navigate to Language submenu
    press_keys_and_validate(
        driver,
        "DDRRDDDDDDR",
        {"ui_type": "UITextMenu", "title": "Language"},
    )

    # Navigate to top (English = index 0), then D to German (index 1), select
    press_keys_and_validate(
        driver,
        "UUUUUUDR",  # wrap to top, D = German (index 1), R = select
        {},  # state after select is implementation-defined; just validate 200 OK
    )

    # Restore English: navigate back to Language submenu and select English (index 0)
    press_keys_and_validate(
        driver,
        "DDRRDDDDDDR",  # navigate back to Language submenu from wherever we are
        {"ui_type": "UITextMenu", "title": "Language"},
    )
    press_keys_and_validate(
        driver,
        "UUUUUUR",  # wrap to top (English), R = select
        {},
    )

    press_keys(driver, "ZL")  # back to root
