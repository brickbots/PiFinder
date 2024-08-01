import pytest
import tempfile
import os
import logging
import PiFinder.multiproclogging as mpl

from io import StringIO
from multiprocessing import Queue, Process


def test_mpl_without_config():
    # Should not throw an error.
    mpl.MultiprocLogging()


def test_mpl_with_empty_config():
    empty_config = """
    {
        "version": 1,
        "disable_existing_loggers": false
    }
    """
    f = StringIO(empty_config)
    Mpl = mpl.MultiprocLogging()
    Mpl.read_config(f)


def test_mpl_file_not_found_exception():
    try:
        mpl.MultiprocLogging(log_conf="file_does_not_exist")
        pytest.fail("Should have raised a FileNotFoundError")
    except FileNotFoundError:
        pass


def log_a_thing(q: Queue):
    mpl.MultiprocLogging.configurer(q)
    logging.getLogger().setLevel(logging.DEBUG)
    logging.getLogger("SeparateProcess").info("A thing")


def test_configurer_enqueuing():
    q = Queue()
    logProc = Process(target=log_a_thing, args=(q,))
    logProc.start()
    logProc.join()
    # There should be one log record in the queue:
    rec = q.get_nowait()
    assert rec is not None, "Rec should be an object"
    assert rec.name == "SeparateProcess", "Name in log record is wrong"
    assert rec.levelno == logging.INFO, "Level in log record is wrong"
    assert rec.message == "A thing", "msg in log record is wrong"
    assert q.empty()


def test_mpl_end_to_end():
    with tempfile.TemporaryDirectory() as d:
        logging.getLogger().setLevel(logging.DEBUG)
        log_file = os.path.join(d, "test.log")
        Mpl = mpl.MultiprocLogging(out_file=log_file)
        q = Mpl.get_queue()
        Mpl.start()
        logProc = Process(name="Proc1", target=log_a_thing, args=(q,))
        logProc.start()
        logProc.join()
        Mpl.join()
        str = open(log_file, "r").read()
        assert "SeparateProcess" in str
        assert "INFO" in str
        assert "A thing" in str
        assert "Proc1" in str


def test_mpl_2procs():
    with tempfile.TemporaryDirectory() as d:
        logging.getLogger().setLevel(logging.DEBUG)
        log_file = os.path.join(d, "test.log")
        Mpl = mpl.MultiprocLogging(out_file=log_file)
        q1 = Mpl.get_queue()
        q2 = Mpl.get_queue()
        Mpl.start()
        logProc1 = Process(name="Proc1", target=log_a_thing, args=(q1,))
        logProc2 = Process(name="Proc2", target=log_a_thing, args=(q2,))
        logProc1.start()
        logProc2.start()
        logProc1.join()
        logProc2.join()
        Mpl.join()
        str = open(log_file, "r").read()
        assert "SeparateProcess" in str
        assert "INFO" in str
        assert "A thing" in str
        assert "Proc1" in str
        assert "Proc2" in str
        # print(str)
        # assert False
