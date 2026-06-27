# MF PiFinder Time Sync

This document describes PiFinder's integrated time-sync feature. GPS and NTP can both be used as time sources, and the selected time can optionally be used for Linux system clock and RTC sync requests. Software PPS is managed as a separate periodic event source.

The whole feature is `Off` by default. When `Time Sync` is turned `On`, the default source mode is `Best`, which compares GPS and NTP and selects the source with the better estimated quality. If NTP networking is slow or unavailable, NTP is reported as `unavailable` or `low_quality`; usable GPS time can still be selected.

## UI Settings

Settings path:

```text
Settings > Advanced > Time Sync
```

Status path:

```text
Tools > Place & Time > Time Sync
```

Main UI items:

| UI item | Config key | Default | Meaning |
| --- | --- | --- | --- |
| `Time Sync` | `time_sync_enabled` | `Off` | Master switch for integrated time sync |
| `Source Mode` | `time_sync_source_mode` | `Best` | Select `Best`, `GPS`, or `NTP` |
| `GPS Source` | `gps_time_sync` | `On` | Use GPS as a time source |
| `NTP Source` | `ntp_time_sync` | `On` | Use NTP as a time source |
| `NTP Server` | `ntp_server` | `pool.ntp.org` | Select a known NTP server |
| `Custom NTP Server` | `ntp_server_custom` | empty | Enter an NTP server outside the list |
| `System Clock` | `time_sync_system_clock` | `On` | Request Linux system clock sync from the selected time |
| `RTC Sync` | `rtc_sync` | `Off` | Request RTC sync from the selected time |
| `Software PPS` | `software_pps` | `Off` | Emit software periodic ticks |

Default NTP server list:

```text
pool.ntp.org
time.google.com
time.cloudflare.com
time.nist.gov
Custom
```

To use `Custom`, enter the server first in `Custom NTP Server`. After saving, `NTP Server` is automatically set to `Custom`.

## Default Config

Important defaults in `default_config.json`:

```json
"time_sync_enabled": false,
"time_sync_source_mode": "best",
"gps_time_sync": true,
"ntp_time_sync": true,
"ntp_server": "pool.ntp.org",
"ntp_server_custom": "",
"ntp_poll_interval_seconds": 300,
"ntp_timeout_seconds": 1.0,
"ntp_max_delay_ms": 1500,
"ntp_stale_seconds": 900,
"time_sync_system_clock": true,
"rtc_sync": false,
"software_pps": false
```

## Source Selection

In `Best` mode, PiFinder compares stable GPS candidates with valid NTP candidates.

GPS is judged by `valid`, `tAcc`, recent sample jitter, and stale age. NTP is judged by response validity, stratum, round-trip delay, root dispersion, and stale age.

When both GPS and NTP are usable, PiFinder selects the source with the smaller estimated quality value. If NTP delay is above `ntp_max_delay_ms`, NTP is marked `low_quality` and is not selected.

## System Clock and RTC

The main PiFinder service keeps normal user permissions. Actual system clock or RTC writes require the separate root helper service.

Before final outdoor testing, start with dry-run mode:

```bash
cd ~/PiFinder
./scripts/install_gps_time_sync_helper.sh enable-dry-run
```

Switch to real write mode only when dry-run results are correct:

```bash
cd ~/PiFinder
./scripts/install_gps_time_sync_helper.sh enable
```

The helper validates each request before running `/usr/bin/date` or `/usr/sbin/hwclock`. It checks that the request belongs to the current boot, is fresh, has a valid selected time source, and comes from a `stable` monitor state.

## Status Files

The status path keeps the existing filename for compatibility:

```text
~/PiFinder_data/gps_time_status.json
```

Important fields:

| Field | Meaning |
| --- | --- |
| `state` | Integrated time-sync state |
| `selected` | Currently selected time source and time |
| `latest` | Last GPS time sample |
| `ntp` | Last NTP query result |
| `sources.gps` | GPS source state and candidate |
| `sources.ntp` | NTP source state and candidate |
| `system_clock_sync` | System clock sync request state |
| `rtc_sync` | RTC sync request state |
| `software_pps` | Software PPS tick state |
| `helper` | Last root-helper result |

Helper request file:

```text
~/PiFinder_data/gps_time_sync_request.json
```

Helper status file:

```text
~/PiFinder_data/gps_time_sync_helper_status.json
```

The filenames are retained for compatibility with existing installs and the helper service.

## Test

Run unit tests:

```bash
cd ~/PiFinder/python
pytest tests/test_gps_time_sync.py tests/test_gps_time_sync_helper.py tests/test_gps_time_sync_status_ui.py -q
```

Watch hardware status:

```bash
watch -n 1 cat ~/PiFinder_data/gps_time_status.json
```
