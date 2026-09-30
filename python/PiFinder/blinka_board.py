"""Tell Adafruit Blinka which Raspberry Pi Compute Module this is.

Blinka (through Adafruit PlatformDetect) identifies a Pi by its revision
code: the ``Revision`` field in /proc/cpuinfo, or
/proc/device-tree/system/linux,revision. The Pi firmware writes that value
into the device tree it passes on. On NixOS, U-Boot loads the device tree
from /boot instead (FDTDIR), so the value is missing, and 64-bit kernels show
no ``Revision`` in /proc/cpuinfo.

PlatformDetect then falls back to the model string. That works for
"Raspberry Pi 4 Model B", but not for "Raspberry Pi Compute Module 4": the
board stays unknown, and ``import board`` fails. For a Compute Module with no
revision code, this module sets BLINKA_FORCEBOARD, which PlatformDetect reads
first. It changes nothing when a revision code exists or the variable is
already set.
"""

import os
from pathlib import Path
from typing import MutableMapping, Optional

MODEL_FILE = Path("/proc/device-tree/model")
REVISION_FILE = Path("/proc/device-tree/system/linux,revision")

# Model string prefix -> PlatformDetect board id. Longest prefixes first, so
# "Compute Module 5 Lite" is not taken for "Compute Module 5".
_COMPUTE_MODULES = (
    ("Raspberry Pi Compute Module 5 Lite", "RASPBERRY_PI_CM5_LITE"),
    ("Raspberry Pi Compute Module 5", "RASPBERRY_PI_CM5"),
    ("Raspberry Pi Compute Module 4S", "RASPBERRY_PI_CM4S"),
    ("Raspberry Pi Compute Module 4", "RASPBERRY_PI_CM4"),
)


def board_for_model(model: str) -> Optional[str]:
    """PlatformDetect board id for a Compute Module model string, else None."""
    for prefix, board_id in _COMPUTE_MODULES:
        if model.startswith(prefix):
            return board_id
    return None


def force_pi_board(
    environ: MutableMapping[str, str] = os.environ,
    model_file: Path = MODEL_FILE,
    revision_file: Path = REVISION_FILE,
) -> Optional[str]:
    """Set BLINKA_FORCEBOARD for a Compute Module without a revision code.

    Returns the board id it set, or None when it changed nothing.
    """
    if "BLINKA_FORCEBOARD" in environ or revision_file.exists():
        return None
    try:
        model = model_file.read_bytes().rstrip(b"\x00").decode(errors="replace")
    except OSError:
        return None
    board_id = board_for_model(model)
    if board_id:
        environ["BLINKA_FORCEBOARD"] = board_id
    return board_id
