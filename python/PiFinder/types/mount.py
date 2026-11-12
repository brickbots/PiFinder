"""The live mount control status that the mount process publishes."""

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

import PiFinder.i18n  # noqa: F401

if TYPE_CHECKING:

    def _(a) -> Any:
        return a


# With mount control on, a status older than this means the mount process
# does not run or hangs.
STATUS_MAX_AGE_S = 5.0


@dataclass(frozen=True)
class MountStatus:
    """What the mount does now, for the screen and the web page.

    ``text`` is the short phase text ("Slewing", "Refining 2/3"), already
    translated by the mount process. ``distance_deg`` is the angle from the
    mount position to the goto target, or None without a target. ``error``
    is the last fault ("Mount not found"), empty after a good init.
    """

    phase: str
    text: str
    distance_deg: Optional[float]
    step_deg: float
    model: str
    updated: float
    error: str = ""

    def is_stale(self, now: Optional[float] = None) -> bool:
        now = time.time() if now is None else now
        return now - self.updated > STATUS_MAX_AGE_S


# Phases in which the distance to the target means something. In TRACKING
# it tells how far a manual move took the mount from the goto target.
DISTANCE_PHASES = (
    "MOUNT_TARGET_ACQUISITION_MOVE",
    "MOUNT_TARGET_ACQUISITION_REFINE",
    "MOUNT_DRIFT_COMPENSATION",
    "MOUNT_TRACKING",
)


def format_step(step_deg: float) -> str:
    """An angle in the unit that fits it: degrees, arcminutes or arcseconds."""
    if step_deg >= 1.0:
        return f"{step_deg:.1f}°"
    if step_deg >= 1 / 60:
        return f"{step_deg * 60:.1f}'"
    return f'{step_deg * 3600:.0f}"'


def status_lines(
    status: Optional[MountStatus], now: Optional[float] = None
) -> list[str]:
    """The two status lines: the phase with the distance to the target, and
    the step. One line if there is no current status."""
    if status is None or status.is_stale(now):
        return [_("No mount status")]
    first = status.text
    if status.distance_deg is not None and status.phase in DISTANCE_PHASES:
        first = f"{first} {format_step(status.distance_deg)}"
    return [first, _("Step") + " " + format_step(status.step_deg)]
