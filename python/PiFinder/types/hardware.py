"""
Dataclasses for the Battery (Power & Charging) context.

These types implement the canonical Battery vocabulary
(see ``docs/ax/battery/CONTEXT.md`` and
``docs/adr/0006-battery-read-only-telemetry.md``).

* **Battery voltage** is the canonical, *measured* single-cell terminal
  voltage. Everything else about charge is derived from it.
* **State of charge** (``state_of_charge_pct``) is a coarse 0-100%
  *estimate* off a voltage curve. UI-only, and ``None`` while charging
  (the charger pulls the terminal voltage up, so a percentage would lie).
* **Charge status** is the charger state-machine phase; **power source**
  (``on_external_power``) is whether input power is present. They are
  separate facts — you can be on external power and not charging.

The ``battery_`` prefix is deliberate: it keeps this telemetry clear of
the unrelated sleep/wake ``power_state`` / ``PowerManager`` concept.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ChargeStatus(Enum):
    """The charger's reported charge phase (BQ25895 REG0B ``CHRG_STAT``).

    Distinct from whether external power is present — see
    ``BatteryState.on_external_power``.
    """

    NOT_CHARGING = 0
    PRE_CHARGE = 1
    FAST_CHARGING = 2
    CHARGE_DONE = 3


@dataclass
class BatteryState:
    """Published battery telemetry, carried on ``SharedStateObj``
    (``shared_state.battery()`` / ``set_battery()``).

    Read-only for consumers. ``shared_state.battery()`` is ``None`` when
    no charger is present (rev3 hardware / monitor not running) — that
    is distinct from a real ``BatteryState`` with a low
    ``state_of_charge_pct`` (detected, nearly empty).
    """

    battery_voltage: float  # V, canonical measured value (REG0E)
    charge_status: ChargeStatus  # from REG0B CHRG_STAT
    on_external_power: bool  # from REG0B PG_STAT (power-good)
    state_of_charge_pct: Optional[int]  # derived; None while charging
    charge_current_ma: float  # REG12
    vbus_voltage: float  # REG11
    sys_voltage: float  # REG0F
    timestamp: float


@dataclass
class HardwareCapabilities:
    """Startup-detected record of which optional hardware is present on
    this board. Built once by ``hardware_detect`` and published into
    ``SharedStateObj`` (``shared_state.hardware()`` / ``set_hardware()``)
    as the single source of truth for rev-dependent decisions.

    Distinct from ``hardware_platform`` (the ``"Pi"``/``"Fake"`` string).
    """

    has_bq25895: bool = False
    has_buzzer: bool = False  # rev4 passive piezo on PWM ch0 (see Sound context)
    # room to grow: other rev-dependent hardware facts go here
