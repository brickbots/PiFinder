import time
from multiprocessing import Process, Queue
import PiFinder.mountcontrol_indi as mountcontrol
from PiFinder.state import SharedStateObj


def test_mountcontrol_exit_flow():
    mount_queue = Queue()
    console_queue = Queue()
    log_queue = Queue()

    shared_state = SharedStateObj()

    mountcontrol_process = Process(
        name="MountControl",
        target=mountcontrol.run,
        args=(mount_queue, console_queue, shared_state, log_queue, True),
    )
    mountcontrol_process.start()
    time.sleep(0.5)  # Wait for process startup.

    mount_queue.put({"type": "exit"})

    time.sleep(0.1)

    mountcontrol_process.join()


def test_mountcontrol_flow():
    mount_queue = Queue()
    console_queue = Queue()
    log_queue = Queue()

    shared_state = SharedStateObj()

    mountcontrol_process = Process(
        name="MountControl",
        target=mountcontrol.run,
        args=(mount_queue, console_queue, shared_state, log_queue, True),
    )
    mountcontrol_process.start()
    time.sleep(0.5)  # Wait for process startup.

    mount_queue.put({"type": "sync", "ra": 0.0, "dec": 90.0})
    time.sleep(10)
    mount_queue.put({"type": "goto_target", "ra": 15.0, "dec": 15.0})
    time.sleep(10)
    mount_queue.put({"type": "stop_movement"})
    time.sleep(5.0)
    mount_queue.put({"type": "exit"})
    time.sleep(0.1)

    mountcontrol_process.join()

    # assert False, "Need to look at log messages."
