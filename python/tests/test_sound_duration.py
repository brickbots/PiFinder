"""
Unit tests for ``total_duration_ms``.

``total_duration_ms`` sums an earcon's note durations. The shutdown bounded
wait (``callbacks.shutdown`` -> main ``play_shutdown_sound``) depends on it
being right for SHUTDOWN, so the cue plays before the OS cuts power. PURE.
"""

import pytest

from PiFinder.sound import CATALOG, total_duration_ms
from PiFinder.types.sound import Earcon


@pytest.mark.unit
@pytest.mark.parametrize("earcon", list(CATALOG))
def test_matches_sum_of_note_durations(earcon):
    expected = sum(n.duration_ms for n in CATALOG[earcon].notes)
    assert total_duration_ms(earcon) == expected


@pytest.mark.unit
@pytest.mark.parametrize("earcon", list(CATALOG))
def test_every_earcon_has_positive_duration(earcon):
    """Each catalog earcon takes some time — the shutdown wait must be > 0,
    and a zero-length earcon would be silent by accident."""
    assert total_duration_ms(earcon) > 0


@pytest.mark.unit
def test_shutdown_duration_matches_catalog():
    """The value the shutdown wait keys off equals the SHUTDOWN note sum."""
    notes = CATALOG[Earcon.SHUTDOWN].notes
    assert total_duration_ms(Earcon.SHUTDOWN) == sum(n.duration_ms for n in notes)
