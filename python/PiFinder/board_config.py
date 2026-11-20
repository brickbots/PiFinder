from dataclasses import dataclass
from pathlib import Path


MODEL_PATH = Path("/proc/device-tree/model")


@dataclass(frozen=True)
class BoardProfile:
    name: str
    gps_device: str
    uart_overlay: str


PI5_CLASS = BoardProfile(
    name="pi5_class",
    gps_device="/dev/ttyAMA2",
    uart_overlay="dtoverlay=uart2-pi5",
)
PI4 = BoardProfile(
    name="pi4",
    gps_device="/dev/ttyAMA3",
    uart_overlay="dtoverlay=uart3",
)
LEGACY = BoardProfile(
    name="legacy",
    gps_device="/dev/ttyAMA1",
    uart_overlay="dtoverlay=uart3",
)


def read_board_model(model_path: Path = MODEL_PATH) -> str:
    try:
        return model_path.read_bytes().decode(errors="ignore").strip("\x00")
    except OSError:
        return ""


def get_board_profile(model: str | None = None) -> BoardProfile:
    model = read_board_model() if model is None else model
    if "Raspberry Pi 5" in model or "Compute Module 5" in model:
        return PI5_CLASS
    if "Raspberry Pi 4" in model:
        return PI4
    return LEGACY


def get_default_gpsd_device(model: str | None = None) -> str:
    return get_board_profile(model).gps_device


def get_uart_overlay(model: str | None = None) -> str:
    return get_board_profile(model).uart_overlay
