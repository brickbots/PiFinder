# MF PiFinder GPS 시간 동기화와 소프트웨어 PPS

이 문서는 GPS 시간 품질 감시, 소프트웨어 PPS, 선택적 Linux system clock/RTC 동기화 기능을 설명합니다.

기본값은 안전을 위해 모두 꺼져 있습니다. GPS 수신이 약하거나 실내 테스트처럼 `valid: false` 상태인 경우에는 시간 보정 명령을 실행하지 않고 상태 파일에 진단 정보만 기록합니다.

## 설정

기본값은 다음과 같습니다.

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

실내 기능 확인처럼 관찰만 하려면 `~/PiFinder_data/config.json`에 다음 값을 추가하고 PiFinder를 재시작합니다.

```json
"gps_time_sync": true,
"software_pps": true
```

실외에서 GPS 시간이 `stable`이 되는지 확인한 뒤 system clock 또는 RTC 동기화를 테스트하려면 필요한 항목만 추가로 켭니다.

```json
"gps_time_sync": true,
"gps_time_sync_system_clock": true,
"rtc_sync": true
```

`gps_time_sync_system_clock`과 `rtc_sync`는 명시적으로 켰을 때만 동작합니다.

## 상태 파일

GPS 시간 감시 상태는 다음 파일에 기록됩니다.

```text
~/PiFinder_data/gps_time_status.json
```

주요 항목은 다음과 같습니다.

| 항목 | 의미 |
| --- | --- |
| `state` | `waiting_for_gps_time`, `collecting`, `stable`, `unstable`, `low_quality`, `stale` 등 |
| `latest.gps_time` | 마지막 GPS 시간 샘플 |
| `latest.valid` | GPS가 해당 시간 샘플을 유효하다고 표시했는지 여부 |
| `latest.message_class` | UBX 입력의 경우 `NAV-PVT`, `NAV-TIMEGPS` 등 |
| `latest.offset_seconds` | GPS 시간과 PiFinder 내부 시간의 차이 |
| `latest.system_offset_seconds` | GPS 시간과 Linux system clock의 차이 |
| `offset.jitter_seconds` | 최근 샘플 offset 흔들림 |
| `software_pps.tick_count` | 소프트웨어 tick 누적 수 |
| `system_clock_sync.state` | `disabled`, `waiting_for_stable_gps`, `in_sync`, `synced`, `cooldown`, `error` 등 |
| `rtc_sync.state` | `disabled`, `waiting_for_stable_gps`, `synced`, `cooldown`, `error` 등 |

## 판정 방식

GPS 시간 샘플이 들어오면 PiFinder 내부 시간과 비교해 offset을 계산합니다. 설정된 샘플 수를 모은 뒤 offset과 jitter가 기준 안에 있으면 `stable` 상태가 됩니다.

기본 기준은 다음과 같습니다.

| 설정 | 기본값 |
| --- | --- |
| `gps_time_sync_min_samples` | `5` |
| `gps_time_sync_window_seconds` | `120` |
| `gps_time_sync_stale_seconds` | `30` |
| `gps_time_sync_max_tacc_ns` | `1000000000` |
| `gps_time_sync_stable_jitter_ms` | `250` |
| `gps_time_sync_stable_offset_ms` | `1000` |

UBX GPS에서 `tAcc`가 제공되면 `gps_time_sync_max_tacc_ns`보다 큰 샘플은 `low_quality`로 표시됩니다. GPS가 시간 후보를 보내지만 valid bit가 꺼져 있으면 PiFinder 내부 시간은 갱신하지 않고 상태 파일에만 `low_quality` 후보로 기록합니다.

실내나 안테나 상태가 좋지 않은 경우 `GPSD-SKY` 또는 `NAV-PVT` 후보 시간이 보이더라도 `valid: false`, `uSat: 0`, `tAcc_ns: 4294967295`처럼 표시될 수 있습니다. 이 상태는 GPS 수신기가 아직 신뢰 가능한 시간을 만들지 못했다는 의미이며, system clock/RTC 동기화는 실행되지 않습니다.

## System Clock과 RTC 동기화

`gps_time_sync_system_clock`이 켜져 있고 GPS 시간이 `stable`이면 PiFinder는 Linux system clock과 GPS 시간 차이를 확인합니다. 차이가 `gps_time_sync_system_clock_step_threshold_ms`보다 작으면 `in_sync`로 기록하고, 더 크면 `/usr/bin/date -u --set @<timestamp>` 명령으로 system clock 보정을 시도합니다.

`rtc_sync`가 켜져 있고 GPS 시간이 `stable`이면 `/usr/sbin/hwclock --utc --set --date <utc-time>` 명령으로 RTC 기록을 시도합니다. Raspberry Pi 5의 하드웨어 RTC 또는 별도 RTC 모듈이 있는 Pi 4에서 사용할 수 있습니다.

현재 `pifinder.service`는 일반 사용자로 실행되므로 system clock 또는 RTC 쓰기 권한이 없으면 `error` 상태와 실패 메시지가 기록됩니다. 이 실패는 PiFinder 기본 기능을 중단하지 않습니다.

chrony 설정은 변경하지 않습니다.

## 소프트웨어 PPS

`software_pps`를 켜면 PiFinder 메인 루프에서 monotonic clock 기준의 주기적 tick을 생성하고 상태 파일에 기록합니다.

```json
"software_pps": true,
"software_pps_interval_seconds": 1.0
```

이 tick은 하드웨어 PPS가 아닙니다. Linux 사용자 공간 스케줄링 영향을 받으므로 정밀한 하드웨어 펄스 대신 다음 기능에서 사용할 수 있는 주기 이벤트 기준으로 취급해야 합니다.

## 실외 테스트 절차

1. 실내에서는 `gps_time_sync`와 `software_pps`만 켜고 상태 파일을 확인합니다.
2. 실외에서 GPS 안테나 시야를 확보한 뒤 `latest.valid`가 `true`가 되는지 확인합니다.
3. 상태가 `collecting`에서 `stable`로 바뀌는지 확인합니다.
4. system clock 또는 RTC 동기화를 테스트할 때만 `gps_time_sync_system_clock` 또는 `rtc_sync`를 켭니다.
5. 권한 문제가 있으면 `system_clock_sync.state` 또는 `rtc_sync.state`가 `error`가 되며 메시지에 실패 이유가 기록됩니다.

## 테스트

단위 테스트는 다음 명령으로 실행할 수 있습니다.

```bash
cd ~/PiFinder/python
pytest tests/test_gps_time_sync.py tests/test_gps_time_sources.py -q
```

실기 테스트는 상태 파일을 확인합니다.

```bash
watch -n 1 cat ~/PiFinder_data/gps_time_status.json
```
