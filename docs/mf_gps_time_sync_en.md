# MF PiFinder GPS Time Sync Phase 1

This document describes the first phase of GPS time-quality monitoring and software PPS support.

Phase 1 is intentionally observational. It evaluates GPS time samples already flowing through PiFinder and writes a status file, but it does not change the Linux system clock, chrony configuration, or Raspberry Pi 5 RTC.

## Settings

All options are disabled by default.

```json
"gps_time_sync": false,
"gps_time_sync_system_clock": false,
"software_pps": false,
"rtc_sync": false
```

To test the phase-1 feature, add these values to `~/PiFinder_data/config.json` and restart PiFinder:

```json
"gps_time_sync": true,
"software_pps": true
```

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
| `offset.jitter_seconds` | Recent offset variation |
| `software_pps.tick_count` | Number of software ticks emitted |
| `system_clock_sync_state` | `not_implemented_phase1` in phase 1 |
| `rtc_sync_state` | `not_implemented_phase1` in phase 1 |

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

When UBX GPS provides `tAcc`, samples above `gps_time_sync_max_tacc_ns` are reported as `low_quality`. If the GPS receiver sends a time candidate but its valid bit is not set, PiFinder does not update its internal time and records the candidate as `low_quality` in the status file only. Inputs without a time-accuracy value, such as GPSD samples, are evaluated with offset and jitter only.

Indoors or with a weak antenna view, `GPSD-SKY` or `NAV-PVT` candidate times may appear with values such as `valid: false`, `uSat: 0`, or `tAcc_ns: 4294967295`. That means the receiver is producing time candidates but has not produced trustworthy time yet.

## Software PPS

When `software_pps` is enabled, PiFinder's main loop emits a periodic monotonic-clock tick and records it in the status file.

```json
"software_pps": true,
"software_pps_interval_seconds": 1.0
```

This is not hardware PPS. It is affected by Linux userspace scheduling, so treat it as a periodic event source for future features rather than a precision electrical pulse.

## Current Limits

- The Linux system clock is not changed.
- chrony configuration is not changed.
- Raspberry Pi 5 RTC is not read or written.
- INDI mount control does not require this feature.

These limits keep normal PiFinder behavior unchanged when GPS reception is weak or unavailable.

## Test

Run unit tests with:

```bash
cd ~/PiFinder/python
pytest tests/test_gps_time_sync.py -q
```

For hardware testing, enable `gps_time_sync` and `software_pps`, restart PiFinder, then watch the status file:

```bash
watch -n 1 cat ~/PiFinder_data/gps_time_status.json
```
