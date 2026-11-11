# Mount control uses a local indiserver, a pure-Python INDI client and a driver FIFO

**Status: accepted.** Implemented in mrosseel#125. Based on the mount control state machine of brickbots#367.

PiFinder can move a GoTo mount: goto the selected object, sync to the plate solve, move in small steps, and refine the position with a new plate solve. The build is generic: PiFinder does not know which mount a user has. INDI has drivers for most mounts, from OnStep/OnStepX and SkyWatcher to iOptron, Celestron and Meade, so PiFinder talks to the mount through INDI.

## Decision

- **INDI from nixpkgs.** The NixOS image includes core INDI and the 3rd-party mount drivers (eqmod, celestronaux, starbook), with no camera drivers. All parts are in the public binary cache, so nothing compiles on the device.
- **One `indiserver` service with no driver.** It runs as `pifinder` with group `dialout` on port 7624, which the firewall does not open. PiFinder starts the driver of the selected mount by writing `start <driver> -n "<device>"` to `/run/indi/fifo`, and stops it with `stop`. A driver change needs no service restart.
- **The mount list comes from INDI.** PiFinder reads the "Telescopes" group of the INDI driver XML files. The config stores the model label, for example "SAL-33", which is unique.
- **A pure-Python INDI client** (`indi_client.py`) speaks the INDI XML protocol over TCP with the standard library. It finds the telescope device by the `DRIVER_INTERFACE` bit, not by its name.
- **The mount process always runs.** It is idle while mount control is off. A `reload_config` command makes it read the settings again and apply them at once.
- **The mount gets JNow coordinates.** Catalog positions and plate solves are J2000. The mount process converts them in one place (`calc_utils.j2000_to_jnow`).
- **REFINE uses only a plate solve whose exposure ended after the mount settled.** It compares that solve with the target, syncs and moves again, and stops after 3 rounds.
- **USB serial contention is solved in the system, not at run time.** ModemManager is off. A udev rule keeps gpsd hotplug off the generic USB-serial bridges (CP210x, ATEN UC-232A, a Prolific variant), unless GPS Type is "GPSD (generic)". In that case PiFinder creates `/var/lib/pifinder/usb/generic-gps`, and the rule lets gpsd have them.

## Considered options

- **Build INDI from source on the device (rejected).** brickbots#367 did this. It takes 30 to 60 minutes, stops PiFinder during the build and runs `apt upgrade`.
- **`pyindi-client` (rejected).** It is a SWIG binding to the C++ library. It must compile on the device, CI needs a PPA and `swig`, and nixpkgs does not have it. PiFinder uses only a few INDI operations, and about 550 lines of Python do them.
- **`indiwebmanager` (rejected).** It is a FastAPI service, installed from a fork branch, that starts `indiserver`. The FIFO of `indiserver` does the same job. In #367, turning mount control on or off also rebooted the device.
- **Direct LX200/NexStar serial code, no INDI (rejected).** Two protocols cover many mounts, but not all. INDI covers OnStepX and many others, and it keeps a later path open to KStars and NINA (`indi_alpaca_server`).
- **A sudo helper that takes a port from gpsd (rejected).** It worked, but gpsd still opened the port first at boot and probed the mount controller at several baud rates. It also added a root command for the pifinder user. The fixed udev rule has no race and adds no privilege.
- **Restart PiFinder after a settings change (rejected).** It was the first version. The reload command applies the change at once.

## Consequences

- A USB GPS dongle on one of the generic bridges starts gpsd only with GPS Type "GPSD (generic)". After a change of GPS Type, a device that is already plugged in needs a replug, and PiFinder tells the user.
- `indiserver` binds a local socket with a fixed default name, so only one runs per machine. The tests start theirs with a private socket (`-u`).
- The INDI telescope simulator confirms a sync, but it does not move its reported position. The integration tests check the driver message.
- PiFinder does not change the pointing model inside the mount controller (for example OnStepX). It turns off only the INDI alignment subsystem. A controller pointing model can disagree with the plate solve.
- WiFi mounts use the driver's TCP connection. An empty host or port keeps the driver default, for example UDP 11880 on the AZ-GTi driver.
- INDI applies `TELESCOPE_TRACK_RATE` only in the `TRACK_CUSTOM` track mode. Drift compensation sets that mode first, and a new goto goes back to sidereal. A mount without custom tracking keeps sidereal tracking and skips drift compensation.
- After a sync, the driver confirms with a position update in state Ok, and that reply can come after the next goto was sent. A slew therefore ends only after the driver reported Busy for it, or after 3 s.
- Presets live in the config (`mount_control_presets`). A user preset with the name of a built-in preset overrides it.
