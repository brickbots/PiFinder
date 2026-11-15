"""The INDI mount drivers that are installed, read from the INDI driver XML
files (the "Telescopes" group), and the FIFO that starts them in indiserver."""

import logging
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger("MountControl.Drivers")

DEFAULT_DATA_DIR = "/run/current-system/sw/share/indi"
DEFAULT_FIFO = "/run/indi/fifo"
# indiserver keeps no list of the drivers that PiFinder started, so PiFinder
# records the running driver here and stops it before it starts another.
RUNNING_DRIVER_FILE = "running-driver"

SIMULATOR = "Telescope Simulator"


@dataclass(frozen=True)
class MountModel:
    """One mount model: the label is unique and is what the config stores."""

    manufacturer: str
    label: str
    driver: str
    device_name: str


def data_dir() -> Path:
    return Path(os.environ.get("INDI_DATA_DIR", DEFAULT_DATA_DIR))


def fifo_path() -> Path:
    return Path(os.environ.get("INDI_FIFO", DEFAULT_FIFO))


def mount_models(directory: Optional[Path] = None) -> list[MountModel]:
    """All mount models in the driver XML files, sorted by manufacturer and
    label. Empty if INDI is not installed."""
    directory = directory or data_dir()
    models: dict[str, MountModel] = {}
    for path in sorted(directory.glob("*.xml")):
        try:
            root = ET.parse(path).getroot()
        except (ET.ParseError, OSError) as e:
            logger.warning("Cannot read INDI driver file %s: %s", path, e)
            continue
        if root.tag != "driversList":
            continue
        for group in root.iter("devGroup"):
            if group.get("group") != "Telescopes":
                continue
            for device in group.iter("device"):
                driver = device.find("driver")
                label = device.get("label")
                if driver is None or not driver.text or not label:
                    continue
                models[label] = MountModel(
                    manufacturer=device.get("manufacturer") or "Others",
                    label=label,
                    driver=driver.text.strip(),
                    device_name=driver.get("name") or label,
                )
    return sorted(models.values(), key=lambda m: (m.manufacturer.lower(), m.label))


def find_model(label: str, directory: Optional[Path] = None) -> Optional[MountModel]:
    for model in mount_models(directory):
        if model.label == label:
            return model
    return None


def _fifo_command(line: str, fifo: Path) -> bool:
    # O_NONBLOCK: opening a FIFO with no reader fails at once (indiserver is
    # not running) instead of blocking for ever.
    try:
        fd = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
    except OSError as e:
        logger.error("Cannot open the indiserver FIFO %s: %s", fifo, e)
        return False
    try:
        os.write(fd, (line + "\n").encode())
    finally:
        os.close(fd)
    logger.info("indiserver: %s", line)
    return True


def _read_running(running_file: Path) -> tuple[str, str]:
    try:
        driver, _sep, device_name = running_file.read_text().strip().partition("\t")
    except OSError:
        return "", ""
    return driver, device_name


def _stop_command(driver: str, device_name: str) -> str:
    if device_name:
        return f'stop {driver} -n "{device_name}"'
    return f"stop {driver}"


def start_driver(model: MountModel, fifo: Optional[Path] = None) -> bool:
    """Start the driver of model in indiserver. A different driver that
    PiFinder started before is stopped first."""
    fifo = fifo or fifo_path()
    running_file = fifo.parent / RUNNING_DRIVER_FILE
    running = _read_running(running_file)
    if running == (model.driver, model.device_name):
        return True
    if running[0]:
        _fifo_command(_stop_command(*running), fifo)
    if not _fifo_command(f'start {model.driver} -n "{model.device_name}"', fifo):
        return False
    try:
        running_file.write_text(f"{model.driver}\t{model.device_name}\n")
    except OSError as e:
        logger.warning("Cannot record the running driver: %s", e)
    return True


def stop_driver(fifo: Optional[Path] = None) -> None:
    """Stop the driver that PiFinder started, if any."""
    fifo = fifo or fifo_path()
    running_file = fifo.parent / RUNNING_DRIVER_FILE
    running = _read_running(running_file)
    if running[0] and _fifo_command(_stop_command(*running), fifo):
        running_file.unlink(missing_ok=True)
