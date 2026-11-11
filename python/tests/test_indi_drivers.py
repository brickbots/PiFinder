"""The INDI mount driver list and the indiserver FIFO commands."""

import os
import shutil
import threading

import pytest

from PiFinder import indi_drivers

pytestmark = pytest.mark.unit

DRIVERS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<driversList>
  <devGroup group="Telescopes">
    <device label="LX200 OnStep" manufacturer="OnStep">
      <driver name="LX200 OnStep">indi_lx200_OnStep</driver>
    </device>
    <device label="SAL-33" manufacturer="MLAstro">
      <driver name="LX200 OnStep">indi_lx200_OnStep</driver>
    </device>
    <device label="No Maker">
      <driver>indi_nomaker</driver>
    </device>
  </devGroup>
  <devGroup group="CCDs">
    <device label="Some Camera" manufacturer="ZWO">
      <driver name="Some Camera">indi_cam</driver>
    </device>
  </devGroup>
</driversList>
"""

EQMOD_XML = """<?xml version="1.0" encoding="UTF-8"?>
<driversList><devGroup group="Telescopes">
  <device label="EQMod Mount" manufacturer="SkyWatcher">
    <driver name="EQMod Mount">indi_eqmod_telescope</driver>
  </device>
</devGroup></driversList>
"""


@pytest.fixture
def data_dir(tmp_path):
    (tmp_path / "drivers.xml").write_text(DRIVERS_XML)
    (tmp_path / "indi_eqmod.xml").write_text(EQMOD_XML)
    (tmp_path / "indi_eqmod_sk.xml").write_text("<INDIDriver/>")  # skeleton
    (tmp_path / "broken.xml").write_text("<driversList><devGroup")
    return tmp_path


def test_mount_models_reads_only_telescopes_from_all_files(data_dir):
    models = indi_drivers.mount_models(data_dir)
    assert [m.label for m in models] == [
        "SAL-33",
        "LX200 OnStep",
        "No Maker",
        "EQMod Mount",
    ]
    sal = indi_drivers.find_model("SAL-33", data_dir)
    assert sal == indi_drivers.MountModel(
        "MLAstro", "SAL-33", "indi_lx200_OnStep", "LX200 OnStep"
    )
    assert indi_drivers.find_model("No Maker", data_dir).manufacturer == "Others"
    assert indi_drivers.find_model("No Maker", data_dir).device_name == "No Maker"
    assert indi_drivers.find_model("Some Camera", data_dir) is None


def test_mount_models_empty_without_indi(tmp_path):
    assert indi_drivers.mount_models(tmp_path / "missing") == []


def test_data_dir_from_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("INDI_DATA_DIR", str(tmp_path))
    assert indi_drivers.data_dir() == tmp_path


class _FifoReader:
    """Reads lines from a FIFO in a thread, as indiserver does."""

    def __init__(self, path):
        self.path = path
        self.lines: list[str] = []
        os.mkfifo(path)
        # Keep a reader open so writers do not fail with ENXIO.
        self._fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)

    def read(self):
        try:
            data = os.read(self._fd, 4096)
        except BlockingIOError:
            data = b""
        self.lines += data.decode().splitlines()
        return self.lines

    def close(self):
        os.close(self._fd)


@pytest.fixture
def fifo(tmp_path):
    reader = _FifoReader(tmp_path / "fifo")
    yield reader
    reader.close()


def test_start_driver_writes_start_and_records_it(fifo):
    model = indi_drivers.MountModel("OnStep", "LX200 OnStep", "indi_x", "X Dev")
    assert indi_drivers.start_driver(model, fifo.path)
    assert fifo.read() == ['start indi_x -n "X Dev"']
    # The same driver again: nothing to do.
    assert indi_drivers.start_driver(model, fifo.path)
    assert fifo.read() == ['start indi_x -n "X Dev"']


def test_start_other_driver_stops_the_running_one(fifo):
    first = indi_drivers.MountModel("A", "A", "indi_a", "A Dev")
    second = indi_drivers.MountModel("B", "B", "indi_b", "B Dev")
    indi_drivers.start_driver(first, fifo.path)
    indi_drivers.start_driver(second, fifo.path)
    assert fifo.read() == [
        'start indi_a -n "A Dev"',
        'stop indi_a -n "A Dev"',
        'start indi_b -n "B Dev"',
    ]
    indi_drivers.stop_driver(fifo.path)
    assert fifo.read()[-1] == 'stop indi_b -n "B Dev"'
    assert not (fifo.path.parent / indi_drivers.RUNNING_DRIVER_FILE).exists()


def test_start_driver_fails_without_indiserver(tmp_path):
    # A FIFO with no reader, and a path with no FIFO: both fail at once.
    os.mkfifo(tmp_path / "fifo")
    model = indi_drivers.MountModel("A", "A", "indi_a", "A Dev")
    result: list[bool] = []
    t = threading.Thread(
        target=lambda: result.append(
            indi_drivers.start_driver(model, tmp_path / "fifo")
        )
    )
    t.start()
    t.join(timeout=2)
    assert result == [False]
    assert not indi_drivers.start_driver(model, tmp_path / "none" / "fifo")


@pytest.mark.skipif(shutil.which("indiserver") is None, reason="needs INDI")
def test_installed_indi_lists_the_simulator():
    # With INDI installed, INDI_DATA_DIR or the default path has the
    # simulator. Skip if neither has driver files.
    models = indi_drivers.mount_models()
    if not models:
        pytest.skip("no INDI driver XML at the data directory")
    assert indi_drivers.find_model(indi_drivers.SIMULATOR) is not None
