"""
Unit tests for the pure BQ25895 fast-charge config planning.

``plan_charging_writes`` and the ``_encode_*`` helpers are pure (no
hardware), so the read-modify-write logic — bit preservation, field
encoding, watchdog ordering and idempotency — is testable without a
board. Register layout is cross-checked against ``BQ25895-datasheet.pdf``
(TI SLUSC88C) and the live rev4 readings noted in the battery handoff.
See ``docs/adr/0017-battery-fast-charge-config.md``.
"""

import pytest

from PiFinder.battery_bq25895 import (
    AUTO_DPDM_MASK,
    ICHG_MASK,
    IINLIM_MASK,
    REG00,
    REG02,
    REG04,
    REG07,
    TARGET_CHARGE_CURRENT_MA,
    TARGET_INPUT_LIMIT_MA,
    WATCHDOG_MASK,
    _encode_ichg,
    _encode_iinlim,
    plan_charging_writes,
)

# Live rev4 defaults read off a unit before configuration (see handoff):
# REG00 0x48 (EN_ILIM=1, IINLIM=500 mA), REG04 0x20 (2048 mA), REG07 0x9D
# (40 s watchdog). REG02 0x3D is the datasheet power-on value (ICO/HVDCP/
# MaxCharge enabled, BOOST_FREQ=500 kHz, AUTO_DPDM_EN=1).
DEFAULT_REG00 = 0x48
DEFAULT_REG02 = 0x3D
DEFAULT_REG04 = 0x20
DEFAULT_REG07 = 0x9D


@pytest.mark.unit
def test_encode_iinlim_targets_1500ma():
    """1500 mA -> IINLIM field 28 (0x1C): 100 + 28*50 = 1500 mA."""
    assert _encode_iinlim(1500) == 0x1C
    assert TARGET_INPUT_LIMIT_MA == 1500


@pytest.mark.unit
def test_encode_ichg_targets_1500ma():
    """1500 mA -> nearest ICHG step 23 (0x17): 23*64 = 1472 mA (~1.5 A)."""
    assert _encode_ichg(1500) == 0x17
    assert TARGET_CHARGE_CURRENT_MA == 1500


@pytest.mark.unit
def test_encode_clamps_to_field_width():
    """Out-of-range requests clamp to the field, never overflow it."""
    assert _encode_iinlim(100_000) == IINLIM_MASK
    assert _encode_iinlim(0) == 0  # (0-100)/50 rounds negative -> clamped
    assert _encode_ichg(100_000) == ICHG_MASK
    assert _encode_ichg(0) == 0


@pytest.mark.unit
def test_plan_from_defaults_writes_all_four():
    """From the factory/post-reset defaults, all four registers change.

    REG07 (watchdog) must come first so disabling it precedes the other
    writes.
    """
    writes = plan_charging_writes(
        DEFAULT_REG00, DEFAULT_REG02, DEFAULT_REG04, DEFAULT_REG07
    )

    assert [reg for reg, _ in writes] == [REG07, REG02, REG00, REG04]
    values = dict(writes)
    # Watchdog bits cleared, every other REG07 bit preserved.
    assert values[REG07] == DEFAULT_REG07 & ~WATCHDOG_MASK == 0x8D
    # AUTO_DPDM_EN (bit0) cleared, every other REG02 bit preserved.
    assert values[REG02] == DEFAULT_REG02 & ~AUTO_DPDM_MASK == 0x3C
    # IINLIM set to 1500 mA; EN_ILIM (bit6) and EN_HIZ (bit7) preserved.
    assert values[REG00] == 0x5C  # 0x48 -> keep 0x40, set IINLIM 0x1C
    # ICHG set to ~1.5 A; EN_PUMPX (bit7) preserved (was 0).
    assert values[REG04] == 0x17


@pytest.mark.unit
def test_plan_disables_auto_dpdm_and_preserves_other_reg02_bits():
    """Clearing AUTO_DPDM_EN is what makes the input limit survive a cable
    replug while powered off (ADR 0017). The write must clear only bit 0
    and leave the rest of REG02 (CONV_RATE, BOOST_FREQ, ICO_EN, HVDCP_EN,
    MAXC_EN, FORCE_DPDM) untouched."""
    # Every REG02 bit set except CONV_START — a deliberately noisy value.
    reg02 = 0x7F
    writes = dict(
        plan_charging_writes(DEFAULT_REG00, reg02, DEFAULT_REG04, DEFAULT_REG07)
    )
    assert writes[REG02] == reg02 & ~AUTO_DPDM_MASK == 0x7E
    assert writes[REG02] & AUTO_DPDM_MASK == 0  # AUTO_DPDM_EN off


@pytest.mark.unit
def test_plan_preserves_en_ilim_and_en_hiz():
    """The IINLIM write must not disturb EN_ILIM/EN_HIZ — the ILIM-pin
    ceiling stays in force (ADR 0017)."""
    # EN_HIZ=1, EN_ILIM=1, plus some stale IINLIM bits.
    reg00 = 0xC0 | 0x05
    writes = dict(
        plan_charging_writes(reg00, DEFAULT_REG02, DEFAULT_REG04, DEFAULT_REG07)
    )
    assert writes[REG00] & 0xC0 == 0xC0  # both high bits kept
    assert writes[REG00] & IINLIM_MASK == _encode_iinlim(TARGET_INPUT_LIMIT_MA)


@pytest.mark.unit
def test_plan_preserves_en_pumpx():
    """The ICHG write must preserve EN_PUMPX (REG04 bit7)."""
    reg04 = 0x80 | 0x20  # EN_PUMPX set
    writes = dict(
        plan_charging_writes(DEFAULT_REG00, DEFAULT_REG02, reg04, DEFAULT_REG07)
    )
    assert writes[REG04] & 0x80 == 0x80
    assert writes[REG04] & ICHG_MASK == _encode_ichg(TARGET_CHARGE_CURRENT_MA)


@pytest.mark.unit
def test_plan_is_idempotent_when_already_configured():
    """Re-running against an already-configured chip emits no writes, so
    the per-poll re-assert costs nothing in steady state."""
    configured = plan_charging_writes(
        DEFAULT_REG00, DEFAULT_REG02, DEFAULT_REG04, DEFAULT_REG07
    )
    reg00, reg02, reg04, reg07 = (
        DEFAULT_REG00,
        DEFAULT_REG02,
        DEFAULT_REG04,
        DEFAULT_REG07,
    )
    for reg, value in configured:
        if reg == REG00:
            reg00 = value
        elif reg == REG02:
            reg02 = value
        elif reg == REG04:
            reg04 = value
        elif reg == REG07:
            reg07 = value

    assert plan_charging_writes(reg00, reg02, reg04, reg07) == []


@pytest.mark.unit
def test_plan_reasserts_only_drifted_register():
    """If only the watchdog snapped back (e.g. after a reset), only REG07
    is rewritten."""
    # Start configured, then flip the watchdog back on (bits 5:4 = 01).
    reg00 = (DEFAULT_REG00 & ~IINLIM_MASK) | _encode_iinlim(TARGET_INPUT_LIMIT_MA)
    reg02 = DEFAULT_REG02 & ~AUTO_DPDM_MASK
    reg04 = (DEFAULT_REG04 & ~ICHG_MASK) | _encode_ichg(TARGET_CHARGE_CURRENT_MA)
    reg07 = 0x8D | 0x10  # watchdog = 40 s again

    writes = plan_charging_writes(reg00, reg02, reg04, reg07)
    assert [reg for reg, _ in writes] == [REG07]
