from PiFinder.state import SharedStateObj
import time


def sleep_for_framerate(shared_state: SharedStateObj, limit_framerate=True) -> bool:
    """ """
    if shared_state.power_state() <= 0:
        time.sleep(0.5)
        return True
    elif limit_framerate:
        time.sleep(1 / 30)

    return False
