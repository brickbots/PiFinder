# MF PiFinder 시간 동기화

이 문서는 PiFinder의 통합 시간 동기화 기능을 설명합니다. 시간 소스는 GPS와 NTP를 함께 사용할 수 있고, 선택된 시간은 선택적으로 Linux system clock과 RTC 동기화 요청에 사용됩니다. 소프트웨어 PPS는 별도 주기 이벤트로 관리됩니다.

기본값은 안전을 위해 전체 기능이 `Off`입니다. 전체 `Time Sync`를 `On`으로 바꾸면 기본 소스 모드는 `Best`이며, GPS와 NTP 중 추정 품질이 더 좋은 값을 선택합니다. NTP 네트워크가 느리거나 끊기면 NTP는 `unavailable` 또는 `low_quality`로 표시되고, 사용 가능한 GPS 시간이 있으면 GPS를 선택합니다.

## UI 설정

설정 위치:

```text
Settings > Advanced > Time Sync
```

상태 확인 위치:

```text
Tools > Place & Time > Time Sync
```

주요 UI 항목:

| UI 항목 | 설정 키 | 기본값 | 의미 |
| --- | --- | --- | --- |
| `Time Sync` | `time_sync_enabled` | `Off` | 통합 시간 동기화 전체 스위치 |
| `Source Mode` | `time_sync_source_mode` | `Best` | `Best`, `GPS`, `NTP` 중 선택 |
| `GPS Source` | `gps_time_sync` | `On` | GPS 시간 소스 사용 |
| `NTP Source` | `ntp_time_sync` | `On` | NTP 시간 소스 사용 |
| `NTP Server` | `ntp_server` | `pool.ntp.org` | 기본 NTP 서버 목록 선택 |
| `Custom NTP Server` | `ntp_server_custom` | 빈 값 | 목록에 없는 NTP 서버 입력 |
| `System Clock` | `time_sync_system_clock` | `On` | 선택된 시간으로 Linux system clock 동기화 요청 |
| `RTC Sync` | `rtc_sync` | `Off` | 선택된 시간으로 RTC 동기화 요청 |
| `Software PPS` | `software_pps` | `Off` | 소프트웨어 주기 tick 생성 |

NTP 서버 기본 목록:

```text
pool.ntp.org
time.google.com
time.cloudflare.com
time.nist.gov
Custom
```

`Custom`을 사용할 때는 먼저 `Custom NTP Server`에서 서버 주소를 입력합니다. 입력 후 `NTP Server`는 자동으로 `Custom`으로 설정됩니다.

## 기본 설정 값

`default_config.json`의 주요 기본값은 다음과 같습니다.

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

## 선택 방식

`Best` 모드에서는 안정적인 GPS 후보와 유효한 NTP 후보를 비교합니다.

GPS는 `valid`, `tAcc`, 최근 샘플 jitter, stale 여부를 기준으로 판단합니다. NTP는 응답 유효성, stratum, 왕복 지연, root dispersion, stale 여부를 기준으로 판단합니다.

GPS와 NTP가 모두 사용할 수 있으면 추정 품질값이 더 작은 소스를 선택합니다. NTP 지연이 `ntp_max_delay_ms`보다 크면 `low_quality`로 표시되고 선택 후보에서 제외됩니다.

## System Clock과 RTC

PiFinder 본체는 일반 사용자 권한으로 실행됩니다. system clock 또는 RTC를 실제로 쓰려면 별도 root helper 서비스가 필요합니다.

실외 최종 테스트 전에는 dry-run으로 먼저 확인하는 것을 권장합니다.

```bash
cd ~/PiFinder
./scripts/install_gps_time_sync_helper.sh enable-dry-run
```

실제 쓰기를 허용하려면 다음으로 전환합니다.

```bash
cd ~/PiFinder
./scripts/install_gps_time_sync_helper.sh enable
```

helper는 요청 파일을 검증한 뒤에만 `/usr/bin/date` 또는 `/usr/sbin/hwclock`을 실행합니다. 요청은 같은 부팅 세션의 최신 요청인지, 선택된 시간 소스가 유효한지, 모니터 상태가 `stable`인지 확인됩니다.

## 상태 파일

상태 파일은 기존 경로를 유지합니다.

```text
~/PiFinder_data/gps_time_status.json
```

주요 항목:

| 항목 | 의미 |
| --- | --- |
| `state` | 통합 시간 동기화 상태 |
| `selected` | 현재 선택된 시간 소스와 시간 |
| `latest` | 마지막 GPS 시간 샘플 |
| `ntp` | 마지막 NTP 조회 결과 |
| `sources.gps` | GPS 소스 상태와 후보 |
| `sources.ntp` | NTP 소스 상태와 후보 |
| `system_clock_sync` | system clock 동기화 요청 상태 |
| `rtc_sync` | RTC 동기화 요청 상태 |
| `software_pps` | 소프트웨어 PPS tick 상태 |
| `helper` | root helper의 마지막 처리 결과 |

helper 요청 파일:

```text
~/PiFinder_data/gps_time_sync_request.json
```

helper 상태 파일:

```text
~/PiFinder_data/gps_time_sync_helper_status.json
```

파일명은 기존 설치와 helper 서비스 호환성을 위해 유지합니다.

## 테스트

단위 테스트:

```bash
cd ~/PiFinder/python
pytest tests/test_gps_time_sync.py tests/test_gps_time_sync_helper.py tests/test_gps_time_sync_status_ui.py -q
```

실기 상태 확인:

```bash
watch -n 1 cat ~/PiFinder_data/gps_time_status.json
```
