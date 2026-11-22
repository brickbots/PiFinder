"""System generations, the confirmed-generations ledger and the recovery flag.

ADR 0038. The boot watchdog writes each system that passes its health check
to the ledger, one store path per line. The recovery hold writes the flag
when SQUARE is held at power-on. The upgrade runner (as root) and the
Software screen read both, so this module uses the standard library only.
"""

import os
from pathlib import Path
from typing import FrozenSet, List, Optional, Tuple

PROFILE_DIR = Path("/nix/var/nix/profiles")
CONFIRMED_LEDGER = Path("/var/lib/pifinder/confirmed-generations")
# On the root-owned /run tmpfs: only root can write it, and a boot clears it.
RECOVERY_FLAG = Path("/run/pifinder-recovery-mode")


def recovery_mode_active(flag: Path = RECOVERY_FLAG) -> bool:
    """True when this boot is in recovery mode."""
    try:
        return flag.exists()
    except OSError:
        return False


def read_ledger(ledger: Path = CONFIRMED_LEDGER) -> FrozenSet[str]:
    """The confirmed systems, as store paths. Empty when there is no ledger."""
    try:
        text = ledger.read_text()
    except OSError:
        return frozenset()
    return frozenset(line.strip() for line in text.splitlines() if line.strip())


def bootable_systems(system: Path) -> List[str]:
    """The systems that a generation can boot, resolved to store paths.

    The first is the toplevel of the generation. The others are its camera
    specialisations. The ledger holds the system that ran, which is a
    specialisation on a device with a camera other than the base camera.
    """
    systems = []
    try:
        systems.append(os.path.realpath(system))
        specialisations = sorted((system / "specialisation").iterdir())
    except OSError:
        return systems
    for specialisation in specialisations:
        systems.append(os.path.realpath(specialisation))
    return systems


def confirmed_system(system: Path, ledger: FrozenSet[str]) -> Optional[str]:
    """The system of this generation that is in the ledger, or None."""
    for candidate in bootable_systems(system):
        if candidate in ledger:
            return candidate
    return None


def generation_links(profile_dir: Path = PROFILE_DIR) -> List[Tuple[int, Path]]:
    """The system generation links of the profile, newest first."""
    links = []
    for link in profile_dir.glob("system-*-link"):
        try:
            links.append((int(link.name.split("-")[1]), link))
        except (ValueError, IndexError):
            continue
    links.sort(key=lambda item: item[0], reverse=True)
    return links


def newest_confirmed(
    profile_dir: Path = PROFILE_DIR,
    ledger: Path = CONFIRMED_LEDGER,
    exclude: Optional[str] = None,
) -> Optional[Path]:
    """The newest confirmed system in the profile, or None.

    A generation that can boot `exclude` (its toplevel or a specialisation)
    is skipped. The watchdog walks the profile with the same rule when the
    recovery app fails.
    """
    confirmed = read_ledger(ledger)
    if not confirmed:
        return None
    excluded = os.path.realpath(exclude) if exclude else None
    for _number, link in generation_links(profile_dir):
        if excluded is not None and excluded in bootable_systems(link):
            continue
        system = confirmed_system(link, confirmed)
        if system is not None:
            return Path(system)
    return None
