# MF PiFinder GPS Time Sync and Software PPS

This document describes GPS time-quality monitoring, software PPS, and optional Linux system clock/RTC synchronization.

All features are disabled by default. When GPS reception is weak, such as during indoor testing with `valid: false`, PiFinder records diagnostics only and does not run clock-sync commands.

## Settings

Default values:

```json
"gps_time_sync": false,
"gps_time_sync_system_clock": false,
"gps_time_sync_system_clock_min_interval_seconds": 300,
"gps_time_sync_system_clock_step_threshold_ms": 500,
"software_pps": false,
"software_pps_interval_seconds": 1.0,
"rtc_sync": false,
"rtc_sync_min_interval_seconds": 3600
```

For indoor observation-only testing, add these values to `~/PiFinder_data/config.json` and restart PiFinder:

```json
"gps_time_sync": true,
"software_pps": true
```

After outdoor testing confirms that GPS time reaches `stable`, enable only the sync actions you want to test:

```json
"gps_time_sync": true,
"gps_time_sync_system_clock": true,
"rtc_sync": true
```

`gps_time_sync_system_clock` and `rtc_sync` do nothing unless explicitly enabled.

## Status File

GPS time-monitor status is written here:

```text
~/PiFinder_data/gps_time_status.json
```

Important fields:

| Field | Meaning |
| --- | --- |
| `state` | `waiting_for_gps_time`, `collecting`, `stable`, `unstable`, `low_quality`, `stale`, and related states |
| `latest.gps_time` | Last GPS time sample |
| `latest.valid` | Whether the GPS receiver marked the time sample as valid |
| `latest.message_class` | UBX source message such as `NAV-PVT` or `NAV-TIMEGPS` |
| `latest.offset_seconds` | Difference between GPS time and PiFinder internal time |
| `latest.system_offset_seconds` | Difference between GPS time and the Linux system clock |
| `offset.jitter_seconds` | Recent offset variation |
| `software_pps.tick_count` | Number of software ticks emitted |
| `system_clock_sync.state` | `disabled`, `waiting_for_stable_gps`, `in_sync`, `synced`, `cooldown`, `error`, and related states |
| `rtc_sync.state` | `disabled`, `waiting_for_stable_gps`, `synced`, `cooldown`, `error`, and related states |

## Quality Logic

When a GPS time sample arrives, PiFinder compares it with the current internal PiFinder time and records the offset. After enough samples are collected, the monitor reports `stable` when both offset and jitter are within the configured thresholds.

Default thresholds:

| Setting | Default |
| --- | --- |
| `gps_time_sync_min_samples` | `5` |
| `gps_time_sync_window_seconds` | `120` |
| `gps_time_sync_stale_seconds` | `30` |
| `gps_time_sync_max_tacc_ns` | `1000000000` |
| `gps_time_sync_stable_jitter_ms` | `250` |
| `gps_time_sync_stable_offset_ms` | `1000` |

When UBX GPS provides `tAcc`, samples above `gps_time_sync_max_tacc_ns` are reported as `low_quality`. If the GPS receiver sends a time candidate but its valid bit is not set, PiFinder does not update its internal time and records the candidate as `low_quality` in the status file only.

Indoors or with a weak antenna view, `GPSD-SKY` or `NAV-PVT` candidate times may appear with values such as `valid: false`, `uSat: 0`, or `tAcc_ns: 4294967295`. That means the receiver has not produced trustworthy time yet, and system clock/RTC sync actions will not run.

## System Clock and RTC Sync

When `gps_time_sync_system_clock` is enabled and GPS time is `stable`, PiFinder compares the Linux system clock against GPS time. If the offset is below `gps_time_sync_system_clock_step_threshold_ms`, it records `in_sync`. If the offset is larger, it attempts to adjust the system clock with `/usr/bin/date -u --set @<timestamp>`.

When `rtc_sync` is enabled and GPS time is `stable`, PiFinder attempts to write GPS time to the RTC with `/usr/sbin/hwclock --utc --set --date <utc-time>`. This is intended for the Raspberry Pi 5 hardware RTC or a Pi 4 with an added RTC module.

The default `pifinder.service` runs as a normal user, so writing the system clock or RTC may fail without additional privileges. Permission failures are recorded as `error` states and do not stop normal PiFinder operation.

chrony configuration is not changed.

## Software PPS

When `software_pps` is enabled, PiFinder's main loop emits a periodic monotonic-clock tick and records it in the status file.

```json
"software_pps": true,
"software_pps_interval_seconds": 1.0
```

This is not hardware PPS. It is affected by Linux userspace scheduling, so treat it as a periodic event source for future features rather than a precision electrical pulse.

## Outdoor Test Flow

1. Indoors, enable only `gps_time_sync` and `software_pps`, then watch the status file.
2. Outdoors, give the GPS antenna a clear sky view and wait for `latest.valid` to become `true`.
3. Confirm that the state moves from `collecting` to `stable`.
4. Enable `gps_time_sync_system_clock` or `rtc_sync` only when you are ready to test those actions.
5. If permissions are missing, `system_clock_sync.state` or `rtc_sync.state` becomes `error` and the message records the failure.

## Test

Run unit tests with:

```bash
cd ~/PiFinder/python
pytest tests/test_gps_time_sync.py tests/test_gps_time_sources.py -q
```

For hardware testing, watch the status file:

```bash
watch -n 1 cat ~/PiFinder_data/gps_time_status.json
```
