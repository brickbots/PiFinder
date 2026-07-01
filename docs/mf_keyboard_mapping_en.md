# MF_PiFinder Keyboard Mapping

This document summarizes the USB/Bluetooth keyboard and GPIO keypad mappings in
the `mf_pifinder` branch.

## USB/Bluetooth Keyboard

| Key | PiFinder input |
| --- | --- |
| Arrow keys | `LEFT`, `UP`, `DOWN`, `RIGHT` |
| Enter / Keypad Enter | `SQUARE` |
| Esc | `LEFT` |
| Backspace | `MINUS` |
| `=` / Keypad `+` | `PLUS` |
| `-` / Keypad `-` | `MINUS` |
| Number `0-9` / Keypad numbers | Number `0-9` |
| Space | Space character |
| `a-z` | Lowercase text input |
| `Shift + a-z` | Uppercase text input |

## Alt Combinations

| Key | PiFinder input |
| --- | --- |
| `Alt + Arrow key` | `ALT_LEFT`, `ALT_UP`, `ALT_DOWN`, `ALT_RIGHT` |
| `Alt + =` / `Alt + Keypad +` | `ALT_PLUS` |
| `Alt + -` / `Alt + Keypad -` | `ALT_MINUS` |
| `Alt + 0` / `Alt + Keypad 0` | `ALT_0` |
| `Alt + Enter` / `Alt + Keypad Enter` | `ALT_SQUARE` |

## Long Press

Holding a key for at least 1 second sends a long-key input.

| Key | PiFinder input |
| --- | --- |
| Hold `Left` | `LNG_LEFT` |
| Hold `Right` | `LNG_RIGHT` |
| Hold `Enter` / `Keypad Enter` | `LNG_SQUARE` |
| Hold `Up` | Repeated `UP` |
| Hold `Down` | Repeated `DOWN` |

For compatibility, pressing `Shift` or `Ctrl` with `Left`, `Up`, `Down`,
`Right`, or `Enter` sends `LNG_LEFT`, `LNG_UP`, `LNG_DOWN`, `LNG_RIGHT`, or
`LNG_SQUARE`.

## GPIO Keypad

| Keypad key | PiFinder input |
| --- | --- |
| Number keys | Number `0-9` |
| `+` | `PLUS` |
| `-` | `MINUS` |
| Square/confirm key | `SQUARE` |
| Direction keys | `LEFT`, `UP`, `DOWN`, `RIGHT` |

On the GPIO keypad, holding `SQUARE` while pressing a direction key, `+`, `-`,
or `0` sends the matching `ALT_*` input.

## INDI Mount Control

INDI mount control is optional. It is available only after installing INDI
support with `scripts/install_indi_mount.sh` and enabling this PiFinder setting:

```text
Settings > Experimental > Mount Control > On
```

When Mount Control is enabled and the Object Details screen is open, number keys
send mount-control commands. USB/Bluetooth number keys, keypad number keys, and
GPIO number keys behave the same way.

| Key | INDI mount action |
| --- | --- |
| `0` | Stop mount |
| `1` | Initialize INDI connection and sync if PiFinder has a solve |
| `2` | Move south by the current step size |
| `3` | Decrease step size |
| `4` | Move west by the current step size |
| `5` | GoTo the current Object Details target |
| `6` | Move east by the current step size |
| `7` | Sync mount to the current PiFinder solved position |
| `8` | Move north by the current step size |
| `9` | Increase step size |

Manual movement is implemented as a small RA/Dec GoTo offset from the current
mount coordinates. The default step size is 1 degree; `3` halves it and `9`
doubles it.

If the INDI server or mount connection has a problem, the normal PiFinder
features continue running. Mount connection status is written here:

```text
~/PiFinder_data/mount_control_status.json
```
