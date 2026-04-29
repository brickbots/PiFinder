# Selenium Test Failures - Fix Tasks

## Overview

5 failing tests in 3 files. Root causes identified below. Tests share the PiFinder app
state (single session), so failures cascade.

## Failing Tests

| # | Test | Root Cause |
|---|------|------------|
| 1 | `test_web_remote.py::test_remote_recent` | Missing `W` (1s wait) after pressing R to open UIObjectDetails |
| 2 | `test_web_remote_filter.py::test_filter_reset_all_confirm_resets_filters` | `update_screen` blocks `set_current_ui_state` during message popup (2s timeout) |
| 3 | `test_web_remote_filter.py::test_filter_altitude_select_and_reset` | Single-select filter submenu doesn't auto-navigate back to parent on value change |
| 4 | `test_web_remote_filter.py::test_filter_observed_select_and_reset` | Same as #3 |
| 5 | `test_web_remote_objects.py::test_objects_custom_radec_entry_screen` | Cascades from #2-4: failed filter tests leave app in stuck submenu state |

## Fixes Required

### Fix A – `python/PiFinder/ui/menu_manager.py`
**Problem**: `update_screen()` gates `set_current_ui_state()` behind the message timeout
check. When `reset_filters` callback calls `remove_from_stack()` then `message(...)`,
the display is blocked for 2s, so the API returns stale state (still shows Reset All
confirmation screen instead of Filter menu).

**Fix**: Move `set_current_ui_state()` call *before* the `message_timeout` guard so the
logical UI state (stack top) is always exposed via the API, even while a visual message
popup is active.

Status: [x] done

---

### Fix B – `python/PiFinder/ui/text_menu.py`
**Problem**: `key_right()` for single-select `config_option` menus (filter.altitude,
filter.magnitude, filter.observed) sets the value but never calls `remove_from_stack()`.
The UI stays in the sub-menu rather than returning to the parent (Filter).

The tests expect: selecting the *already-selected* value → stay; selecting a *different*
value → navigate back to parent.

**Fix**: Inside the `if self._menu_type == "single":` branch, check if the new value
differs from the current selection. If it does, call `self.remove_from_stack()` and
return. Scope the change to `config_option.startswith("filter.")` to avoid touching
unrelated single-select menus that may rely on existing behaviour.

Status: [x] done

---

### Fix C – `python/tests/website/test_web_remote.py`
**Problem**: `test_remote_recent` uses key sequence `"RDRDDDR31R"` to navigate to
UIObjectDetails for M 31 but checks state immediately (0.7s after last keypress).
UIObjectDetails loading is async and needs more time. The passing `test_remote_backtotop`
uses the identical sequence but appends `W` (1s wait).

**Fix**: Change `"RDRDDDR31R"` → `"RDRDDDR31RW"` in `test_remote_recent`.

Status: [x] done

---

### Fix D – `test_objects_custom_radec_entry_screen` (expected to auto-fix)
**Problem**: `navigate_to_root_menu()` fails because previous filter tests left the app
stuck in sub-sub-menus (their `press_keys(driver, "ZL")` cleanup is unreachable after
assertion failure). Fixing A + B will make the filter tests pass and execute their ZL
cleanup, restoring a clean root state for the objects test.

**No direct code change needed** – verify passes after A + B + C are applied.

Status: [ ] pending

---

## Test Command
```bash
cd /Users/grimaldi/Projects/PiFinder/jscheidtmann/python && \
  .venv/bin/python -m pytest tests/website/test_web_remote.py::test_remote_recent \
    tests/website/test_web_remote_filter.py::test_filter_reset_all_confirm_resets_filters \
    tests/website/test_web_remote_filter.py::test_filter_altitude_select_and_reset \
    tests/website/test_web_remote_filter.py::test_filter_observed_select_and_reset \
    tests/website/test_web_remote_objects.py::test_objects_custom_radec_entry_screen \
    -v -m web 2>&1 | tail -30
```

## Progress

- [x] Fix A applied
- [x] Fix B applied
- [x] Fix C applied (+ filter reset step added to test_remote_recent)
- [x] All 5 tests green
