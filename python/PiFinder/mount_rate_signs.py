"""The signs of the custom track rates of a mount driver, for each pier side.

The sign of TELESCOPE_TRACK_RATE differs between drivers, and some drivers
(the INDI telescope simulator) turn the direction of an axis with the pier
side. The mount learns the sign of each axis from the motion (see
MountControlIndi.set_track_rates). ``RateSigns`` keeps one sign for each
axis and each value of TELESCOPE_PIER_SIDE. A mount without that property
has one shared sign, which is not stored.

A confirmed sign goes to a JSON file, for each mount model and pier side:
{"<model>": {"PIER_EAST": [ra, dec], "PIER_WEST": [ra, dec]}}. An axis
without a confirmed sign is null. The file is separate from config.json:
the UI process keeps config.json in memory and writes all of it again, so
a key from the mount process would be lost.
"""

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger("MountControl.RateSigns")

FILE_NAME = "mount_rate_signs.json"
PIER_SIDES = ("PIER_EAST", "PIER_WEST")
DEFAULT_RA_SIGN = -1.0
DEFAULT_DEC_SIGN = 1.0
# Measurements in a row that confirm a sign.
CONFIRM_COUNT = 2
# Measurements in a row against a sign that turn it: one for a sign that
# is not confirmed, so a fast target is not lost, two for a confirmed sign.
TURN_UNCONFIRMED = 1
TURN_CONFIRMED = 2

StoredSigns = dict[str, list[Optional[float]]]


class RateSignStore:
    """The file of the confirmed signs. Without a path the signs stay in
    memory only (tests, and a mount without a data directory)."""

    def __init__(self, path: Optional[Path] = None):
        self.path = path
        self._memory: dict[str, StoredSigns] = {}

    def _read_all(self) -> dict[str, StoredSigns]:
        if self.path is None:
            return self._memory
        try:
            data = json.loads(self.path.read_text())
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as exc:
            logger.warning("Cannot read %s: %s", self.path, exc)
            return {}
        return data if isinstance(data, dict) else {}

    def load(self, model: str) -> StoredSigns:
        """The stored signs of the model: pier side to [ra, dec]."""
        entry = self._read_all().get(model, {})
        result: StoredSigns = {}
        if not isinstance(entry, dict):
            return result
        for pier, signs in entry.items():
            if pier in PIER_SIDES and isinstance(signs, list) and len(signs) == 2:
                result[pier] = [_sign_or_none(value) for value in signs]
        return result

    def save(self, model: str, pier: str, signs: list[Optional[float]]) -> None:
        data = self._read_all()
        entry = data.get(model)
        if not isinstance(entry, dict):
            entry = {}
        entry[pier] = list(signs)
        data[model] = entry
        if self.path is None:
            self._memory = data
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(data, indent=2))
            os.replace(temporary, self.path)
        except OSError as exc:
            logger.warning("Cannot write %s: %s", self.path, exc)


def _sign_or_none(value) -> Optional[float]:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value:
        return 1.0 if value > 0 else -1.0
    return None


@dataclass
class AxisSign:
    """The sign of one rate axis, and the measurements in a row."""

    sign: float
    confirmed: bool = False
    along: int = 0
    against: int = 0

    def measure(self, moved_with: bool, moved_against: bool) -> bool:
        """Count one measurement. True when the sign changed or became
        confirmed, so the store needs an update."""
        self.along = self.along + 1 if moved_with else 0
        self.against = self.against + 1 if moved_against else 0
        if moved_with and not self.confirmed and self.along >= CONFIRM_COUNT:
            self.confirmed = True
            return True
        if self.against >= (TURN_CONFIRMED if self.confirmed else TURN_UNCONFIRMED):
            # Two measurements against a confirmed sign are as sure as two
            # with it: the turned sign is confirmed.
            self.sign = -self.sign
            self.against = 0
            self.along = 0
            return self.confirmed
        return False

    def turn(self) -> None:
        """Turn the sign from other evidence (the drift compensation). The
        new sign is not confirmed."""
        self.sign = -self.sign
        self.confirmed = False
        self.along = 0
        self.against = 0

    def set(self, sign: Optional[float]) -> None:
        """Use a stored sign (confirmed), or keep this sign without
        confirmation for None."""
        if sign is not None:
            self.sign = sign
        self.confirmed = sign is not None
        self.along = 0
        self.against = 0


class RateSigns:
    """The rate signs of a driver on the current pier side."""

    def __init__(self, store: Optional[RateSignStore] = None):
        self.store = store or RateSignStore()
        self.ra = AxisSign(DEFAULT_RA_SIGN)
        self.dec = AxisSign(DEFAULT_DEC_SIGN)
        self.model = ""
        self.pier: Optional[str] = None
        self._stored: StoredSigns = {}

    def reset(self) -> None:
        """The default signs, for a new driver."""
        self.ra = AxisSign(DEFAULT_RA_SIGN)
        self.dec = AxisSign(DEFAULT_DEC_SIGN)
        self.pier = None
        self._stored = {}

    def load(self, model: str) -> None:
        """Read the stored signs of the model, at the connection."""
        self.model = model
        self._stored = self.store.load(model)
        self.pier = None
        logger.info("Stored rate signs of %s: %s", model, self._stored)

    def set_pier(self, pier: Optional[str]) -> bool:
        """The mount is on this pier side (None: no TELESCOPE_PIER_SIDE).
        A new side uses its stored signs at once. A side without a stored
        sign keeps the current sign, not confirmed. True when the side
        changed."""
        if pier == self.pier:
            return False
        self.pier = pier
        stored = self._stored.get(pier, [None, None]) if pier else [None, None]
        self.ra.set(stored[0])
        self.dec.set(stored[1])
        logger.info(
            "Pier side %s: rate signs RA %+.0f%s, Dec %+.0f%s",
            pier,
            self.ra.sign,
            "" if self.ra.confirmed else "?",
            self.dec.sign,
            "" if self.dec.confirmed else "?",
        )
        return True

    def measure(
        self,
        ra_with: bool,
        ra_against: bool,
        dec_with: bool,
        dec_against: bool,
    ) -> None:
        old = (self.ra.sign, self.dec.sign)
        changed = self.ra.measure(ra_with, ra_against)
        changed = self.dec.measure(dec_with, dec_against) or changed
        if old[0] != self.ra.sign:
            logger.info("RA track rate sign of this driver: %+.0f", self.ra.sign)
        if old[1] != self.dec.sign:
            logger.info("Dec track rate sign of this driver: %+.0f", self.dec.sign)
        if changed:
            self._store()

    def _store(self) -> None:
        if self.pier is None or not self.model:
            return
        signs = [
            self.ra.sign if self.ra.confirmed else None,
            self.dec.sign if self.dec.confirmed else None,
        ]
        old = self._stored.get(self.pier, [None, None])
        # A side keeps a stored sign of the other axis until it is measured.
        signs = [new if new is not None else was for new, was in zip(signs, old)]
        self._stored[self.pier] = signs
        self.store.save(self.model, self.pier, signs)
        logger.info("Stored rate signs of %s on %s: %s", self.model, self.pier, signs)
