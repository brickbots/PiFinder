# MF PiFinder INDI Mount Control

This document covers the optional INDI mount-control work for Raspberry Pi 4 and Raspberry Pi 5 Bookworm 64-bit builds.

The feature is disabled by default. Normal PiFinder installs do not import PyIndi or start the INDI mount-control process unless `mount_control` is enabled in the PiFinder config.

The installer has been validated on a Raspberry Pi 4 Model B running Bookworm 64-bit. Raspberry Pi 5 and CM5 use the same Bookworm 64-bit packages and aarch64 build path, and the script does not contain Pi 4-only paths or model-specific branches.

## Status

INDI mount control is experimental. Test with the INDI Telescope Simulator first, then test with the real mount in a safe indoor setup before using it under the sky.

The first integrated scope includes:

- INDI server connection through PyIndi
- telescope/mount device detection
- location and UTC time sync from PiFinder
- mount sync from PiFinder plate-solved RA/Dec
- GoTo for the object currently shown in Object Details
- stop command
- small manual RA/Dec offset moves

Automatic target refinement, drift compensation, and alignment-subsystem management from the older reference branch are not enabled in this first modular port.

## Install INDI Support

Run the dedicated installer from the PiFinder checkout:

```bash
cd ~/PiFinder
bash scripts/install_indi_mount.sh
```

The script installs INDI, INDI third-party drivers, PyIndi, INDI Web Manager, and Chrony GPS time support. It stops the `pifinder` service while compiling and starts it again at the end.

INDI Web Manager dependencies are pinned to `FastAPI 0.103.2`, `Starlette 0.27.0`, `Uvicorn 0.23.2`, and `AnyIO 3.7.1`. Newer Starlette releases changed the template response call signature used by this INDI Web Manager branch, which can make the root Web UI return `500 Internal Server Error`.

Useful environment overrides:

```bash
INDI_VERSION=v2.1.6 INDI_3RDPARTY_VERSION=v2.1.6.2 JOBS=2 bash scripts/install_indi_mount.sh
```

`JOBS=2` is the recommended default on Raspberry Pi 4 to keep memory use conservative. On Raspberry Pi 5 or CM5, `JOBS=3` or `JOBS=4` can reduce build time if cooling and power are stable.

## Configure The Mount Driver

Open INDI Web Manager:

```text
http://pifinder.local:8624
```

If mDNS does not resolve, use the PiFinder IP address:

```text
http://<pifinder-ip>:8624
```

Create a profile, choose the correct telescope driver, enable Auto Start and Auto Connect if desired, then start the profile. Common drivers include EQMod, LX200, iOptron, Celestron, and Telescope Simulator.

## Enable PiFinder Control

On the PiFinder UI:

```text
Settings > Experimental > Mount Control > On
```

Changing this option restarts PiFinder so the optional `MountControl` process can start or stop cleanly.

Advanced config keys in `default_config.json`:

```json
"mount_control": false,
"mount_control_indi_host": "localhost",
"mount_control_indi_port": 7624
```

## Object Details Key Map

When Mount Control is enabled, numeric keys on the Object Details screen send mount commands:

| Key | Action |
| --- | --- |
| 0 | Stop mount |
| 1 | Initialize INDI connection and sync if PiFinder has a solve |
| 2 | Move south by the current step size |
| 3 | Decrease step size |
| 4 | Move west by the current step size |
| 5 | GoTo the displayed object |
| 6 | Move east by the current step size |
| 7 | Sync mount to the current PiFinder solved position |
| 8 | Move north by the current step size |
| 9 | Increase step size |

Manual movement is implemented as a small RA/Dec GoTo offset from the current mount coordinates. The default step size is 1 degree; key `3` halves it and key `9` doubles it within safe bounds.

## Logs And Status

PiFinder logs mount-control messages under `MountControl.Indi`.

A small status file is written here:

```text
~/PiFinder_data/mount_control_status.json
```

Useful service checks:

```bash
systemctl status indiwebmanager.service
systemctl status pifinder.service
journalctl -u indiwebmanager.service -n 100
tail -n 100 ~/PiFinder_data/pifinder.log
```

## Safe Test Flow

1. Install INDI support.
2. Start the Telescope Simulator in INDI Web Manager.
3. Enable PiFinder Mount Control.
4. Open any Object Details screen.
5. Press `1` to initialize.
6. After PiFinder has a solve, press `7` to sync.
7. Press `5` to send GoTo.
8. Press `0` to verify stop behavior.

Only move to a real mount after simulator behavior is understood.
