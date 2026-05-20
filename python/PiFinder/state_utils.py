from typing import Optional

from PiFinder.state import SharedStateObj
import time


_TARGET_PERIOD = 1.0 / 30.0
_last_wake: Optional[float] = None


def sleep_for_framerate(shared_state: SharedStateObj, limit_framerate=True) -> bool:
    global _last_wake

    if shared_state.power_state() <= 0:
        time.sleep(0.5)
        _last_wake = time.monotonic()
        return True

    if limit_framerate and _last_wake is not None:
        remaining = _TARGET_PERIOD - (time.monotonic() - _last_wake)
        if remaining > 0:
            time.sleep(remaining)

    _last_wake = time.monotonic()
    return False
