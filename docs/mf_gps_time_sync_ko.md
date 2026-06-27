# MF PiFinder GPS 시간 동기화 1차 구현

이 문서는 GPS 시간 품질 감시와 소프트웨어 PPS 1차 구현을 설명합니다.

1차 구현은 안전을 위해 관찰 모드로 동작합니다. PiFinder 내부 GPS 시간 샘플을 평가하고 상태 파일을 기록하지만, Linux 시스템 시간, chrony 설정, Raspberry Pi 5 RTC는 직접 변경하지 않습니다.

## 설정

기본값은 모두 꺼짐입니다.

```json
"gps_time_sync": false,
"gps_time_sync_system_clock": false,
"software_pps": false,
"rtc_sync": false
```

1차 기능 테스트를 하려면 `~/PiFinder_data/config.json`에 다음 값을 추가하고 PiFinder를 재시작합니다.

```json
"gps_time_sync": true,
"software_pps": true
```

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
| `latest.offset_seconds` | GPS 시간과 PiFinder 내부 시간의 차이 |
| `offset.jitter_seconds` | 최근 샘플 offset 흔들림 |
| `software_pps.tick_count` | 소프트웨어 tick 누적 수 |
| `system_clock_sync_state` | 1차에서는 `not_implemented_phase1` |
| `rtc_sync_state` | 1차에서는 `not_implemented_phase1` |

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

UBX GPS에서 `tAcc`가 제공되면 `gps_time_sync_max_tacc_ns`보다 큰 샘플은 `low_quality`로 표시됩니다. GPSD처럼 시간 정확도 값이 없는 입력은 offset과 jitter 기준으로 평가합니다.

## 소프트웨어 PPS

`software_pps`를 켜면 PiFinder 메인 루프에서 monotonic clock 기준의 주기적 tick을 생성하고 상태 파일에 기록합니다.

```json
"software_pps": true,
"software_pps_interval_seconds": 1.0
```

이 tick은 하드웨어 PPS가 아닙니다. Linux 사용자 공간 스케줄링 영향을 받으므로 정밀한 하드웨어 펄스 대신 다음 기능에서 사용할 수 있는 주기 이벤트 기준으로 취급해야 합니다.

## 현재 제한

- Linux 시스템 시간은 변경하지 않습니다.
- chrony 설정은 변경하지 않습니다.
- Raspberry Pi 5 RTC는 읽거나 쓰지 않습니다.
- INDI 마운트 동작의 필수 조건이 아닙니다.

이 제한 덕분에 GPS 연결이 불안정해도 기본 PiFinder 기능은 기존처럼 계속 동작합니다.

## 테스트

단위 테스트는 다음 명령으로 실행할 수 있습니다.

```bash
cd ~/PiFinder/python
pytest tests/test_gps_time_sync.py -q
```

실기 테스트는 `gps_time_sync`와 `software_pps`를 켠 뒤 상태 파일을 확인합니다.

```bash
watch -n 1 cat ~/PiFinder_data/gps_time_status.json
```
