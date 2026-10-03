# MF_PiFinder 키보드 매핑

이 문서는 `mf_pifinder` 브랜치의 USB/Bluetooth 키보드와 GPIO 키패드 입력
매핑을 간단히 정리한다.

## USB/Bluetooth 키보드

| 키 | PiFinder 입력 |
| --- | --- |
| 방향키 | `LEFT`, `UP`, `DOWN`, `RIGHT` |
| Enter / Keypad Enter | `SQUARE` |
| Esc | `LEFT` |
| Backspace | `MINUS` |
| `=` / Keypad `+` | `PLUS` |
| `-` / Keypad `-` | `MINUS` |
| 숫자 `0-9` / Keypad 숫자 | 숫자 `0-9` |
| Space | 공백 문자 |
| `a-z` | 영문 소문자 |
| `Shift + a-z` | 영문 대문자 |

## Alt 조합

| 키 | PiFinder 입력 |
| --- | --- |
| `Alt + 방향키` | `ALT_LEFT`, `ALT_UP`, `ALT_DOWN`, `ALT_RIGHT` |
| `Alt + =` / `Alt + Keypad +` | `ALT_PLUS` |
| `Alt + -` / `Alt + Keypad -` | `ALT_MINUS` |
| `Alt + 0` / `Alt + Keypad 0` | `ALT_0` |
| `Alt + Enter` / `Alt + Keypad Enter` | `ALT_SQUARE` |

## 길게 누르기

1초 이상 누르면 long key로 처리된다.

| 키 | PiFinder 입력 |
| --- | --- |
| 길게 `Left` | `LNG_LEFT` |
| 길게 `Right` | `LNG_RIGHT` |
| 길게 `Enter` / `Keypad Enter` | `LNG_SQUARE` |
| 길게 `Up` | `UP` 반복 |
| 길게 `Down` | `DOWN` 반복 |

호환용으로 `Shift` 또는 `Ctrl`과 함께 `Left`, `Up`, `Down`, `Right`,
`Enter`를 누르면 각각 `LNG_LEFT`, `LNG_UP`, `LNG_DOWN`, `LNG_RIGHT`,
`LNG_SQUARE`로 처리된다.

## GPIO 키패드

| 키패드 | PiFinder 입력 |
| --- | --- |
| 숫자 키 | 숫자 `0-9` |
| `+` | `PLUS` |
| `-` | `MINUS` |
| 사각/확인 키 | `SQUARE` |
| 방향키 | `LEFT`, `UP`, `DOWN`, `RIGHT` |

GPIO 키패드는 `SQUARE`를 누른 상태에서 방향키, `+`, `-`, `0`을 누르면
해당 `ALT_*` 입력으로 처리된다.

## INDI 마운트 제어

INDI 마운트 제어는 선택 기능이다. `scripts/install_indi_mount.sh`로 INDI
지원을 설치하고 PiFinder UI에서 다음 설정을 켠 경우에만 동작한다.

```text
Settings > Experimental > Mount Control > On
```

Mount Control이 켜져 있고 Object Details 화면을 보고 있을 때, 숫자 키는
마운트 제어 명령으로 사용된다. USB/Bluetooth 키보드의 숫자 키와 keypad
숫자 키, GPIO 숫자 키가 같은 방식으로 동작한다.

| 키 | INDI 마운트 동작 |
| --- | --- |
| `0` | 마운트 정지 |
| `1` | INDI 연결 초기화, PiFinder solve가 있으면 Sync |
| `2` | 현재 step 크기만큼 South 이동 |
| `3` | step 크기 줄이기 |
| `4` | 현재 step 크기만큼 West 이동 |
| `5` | 현재 Object Details 대상 GoTo |
| `6` | 현재 step 크기만큼 East 이동 |
| `7` | 현재 PiFinder solve 위치로 마운트 Sync |
| `8` | 현재 step 크기만큼 North 이동 |
| `9` | step 크기 키우기 |

수동 이동은 현재 마운트 RA/Dec 좌표에서 작은 GoTo 오프셋을 보내는 방식이다.
기본 step은 1도이며 `3`은 절반으로 줄이고 `9`는 두 배로 키운다.

INDI 서버나 마운트 연결에 문제가 있어도 PiFinder 기본 기능은 계속 동작한다.
마운트 연결 상태는 다음 파일에서 확인할 수 있다.

```text
~/PiFinder_data/mount_control_status.json
```
