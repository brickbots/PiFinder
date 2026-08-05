from typing import Optional

from PiFinder.state import SharedStateObj
import time


_TARGET_PERIOD = 1.0 / 30.0
_last_wake: Optional[float] = None

# Exceptions raised on a SharedStateObj proxy call when the multiprocessing
# Manager process that owns the shared state has died. The proxy connection is
# then permanently broken, so a worker that sees one of these can never recover
# by retrying -- it should log once and stop its loop instead of spinning.
DEAD_MANAGER_EXCEPTIONS = (BrokenPipeError, ConnectionResetError, EOFError)


class SharedStateLost(RuntimeError):
    """The shared-state Manager process is gone; the worker should stop.

    Raised by :func:`sleep_for_framerate` so the documented spin site surfaces
    a single, intentional signal rather than a raw connection error.
    """


def is_dead_manager_error(exc: BaseException) -> bool:
    """Return True when *exc* signals the shared-state Manager process is gone.

    Worker loops should treat this as terminal: log once and exit the loop
    cleanly instead of retrying forever (which floods the logs).
    """
    return isinstance(exc, DEAD_MANAGER_EXCEPTIONS + (SharedStateLost,))


def sleep_for_framerate(shared_state: SharedStateObj, limit_framerate=True) -> bool:
    global _last_wake

    try:
        powered = shared_state.power_state() > 0
    except DEAD_MANAGER_EXCEPTIONS as e:
        raise SharedStateLost(str(e)) from e

    if not powered:
        time.sleep(0.5)
        _last_wake = time.monotonic()
        return True

    if limit_framerate and _last_wake is not None:
        remaining = _TARGET_PERIOD - (time.monotonic() - _last_wake)
        if remaining > 0:
            time.sleep(remaining)

    _last_wake = time.monotonic()
    return False
