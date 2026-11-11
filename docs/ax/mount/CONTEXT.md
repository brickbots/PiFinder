# Mount

The Mount context moves a GoTo telescope mount through INDI: it starts the driver of the selected **mount model** in the local `indiserver`, connects the mount, and runs the **mount phases** (goto, refine, tracking). It runs as the **mount process**, which holds `shared_state` and reads the plate solve from it. See [ADR 0046](../../adr/0046-mount-control-over-indi.md).

## Language

**Mount process**:
The `multiprocessing.Process` named `"MountControl"` that `main.py` starts at every boot (`mountcontrol_indi.run`). It is idle while mount control is off. It receives commands on `command_queues["mountcontrol"]` and sends screen messages on `console_queue`.
_Avoid_: mount thread, mount service (the service is `indiserver`).

**Mount model**:
One `<device>` of the "Telescopes" group in the INDI driver XML files: a unique **label** (what the config stores, for example "SAL-33"), a manufacturer, the **driver** binary and the device name. Several models can share one driver; the SAL-33 uses `indi_lx200_OnStep`.
_Avoid_: mount type (that is Alt/Az or EQ, from `mount_type`), driver (the binary only).

**Driver FIFO**:
`/run/indi/fifo`. PiFinder writes `start <driver> -n "<device>"` and `stop ...` lines to it, and `indiserver` starts or stops the driver. PiFinder records the running driver in `/run/indi/running-driver`.

**Connection**:
`usb` (the driver's serial port and baud rate) or `wifi` (the driver's TCP connection with `host:port`). An empty host or port keeps the driver's own value.
_Avoid_: port (for WiFi, say address).

**Mount settings**:
`mount_settings.MountSettings`: on/off, model, connection, port, baud, address. The config holds them as `mount_control*` options. A `reload_config` command makes the mount process apply changed settings at once.

**Preset**:
A named mount setup (model, connection, port, baud, address) that does not change on/off. Built-in presets cover common defaults. A user preset with the same name (case-insensitive) overrides a built-in one.

**Mount phase**:
`MountControlPhases`: `MOUNT_UNKNOWN` (off or init failed), `MOUNT_INIT_TELESCOPE`, `MOUNT_TRACKING`, `MOUNT_STOPPED`, `MOUNT_TARGET_ACQUISITION_MOVE` (slewing), `MOUNT_TARGET_ACQUISITION_REFINE`, `MOUNT_DRIFT_COMPENSATION`.

**Goto / sync / refine**:
**Goto** sends the target and the mount slews and tracks. **Sync** tells the mount where it points, from the last plate solve. **Refine** waits for a plate solve whose exposure ended after the mount settled, syncs to it and goes to the target again, at most 3 rounds, until the solve is within 0.01°.

**JNow**:
Coordinates of the epoch of date, which INDI mounts use (`EQUATORIAL_EOD_COORD`). Catalog positions and plate solves are J2000; the mount process converts them (`calc_utils.j2000_to_jnow`).
_Avoid_: current coordinates (ambiguous with the mount position).

**Mount message**:
A `["MOUNT", text]` item on `console_queue`: short progress text ("Slewing", "On target") that the main loop shows on the screen for 1.5 s. Faults are `["WARNING", text]`.

**Mount status**:
`types.mount.MountStatus` in the `mount_status` snapshot slot: the phase text, the distance from the mount position to the target, the step, the model and the write time. The mount process writes it when the phase or the step changes, at most once per second when only the distance changes, and at least every 2 s. A status older than 5 s shows as "No mount status". The mount page of Object Details and the web Mount page show it with `status_lines()`.

**Generic USB bridge**:
A USB-serial chip that both GPS dongles and mount controllers use (CP210x `10c4`, ATEN `0557`, Prolific `067b`). gpsd hotplug gets it only with GPS Type "GPSD (generic)" (`usb_gps.py`, `/var/lib/pifinder/usb/generic-gps`).
