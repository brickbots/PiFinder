"""
Unit tests for the drain policy (``select_winner``).

``select_winner`` picks the single earcon to play from a drained batch:
important earcons never expire and win; transient earcons older than
max-age are dropped; among survivors the newest wins. PURE — no hardware
and no clock (stamps and ``now`` are passed in explicitly), so all the
timing behaviour is testable off a board. Dropping a stale transient is
normal, intended behaviour (see ADR 0008), not an error.
"""

import pytest

from PiFinder.sound import DEFAULT_MAX_AGE_MS, select_winner
from PiFinder.types.sound import Earcon

# KEYPRESS and SOLVE_LOCK are transient; STARTUP / SHUTDOWN are important.
MAX_AGE_S = DEFAULT_MAX_AGE_MS / 1000.0


@pytest.mark.unit
def test_empty_returns_none():
    assert select_winner([], now=10.0) is None


@pytest.mark.unit
def test_single_fresh_transient_wins():
    assert select_winner([(Earcon.KEYPRESS, 10.0)], now=10.0) is Earcon.KEYPRESS


@pytest.mark.unit
def test_stale_transient_dropped():
    """A transient older than max-age is discarded -> None."""
    stale_ts = 10.0 - MAX_AGE_S - 0.1  # clearly past the window
    assert select_winner([(Earcon.KEYPRESS, stale_ts)], now=10.0) is None


@pytest.mark.unit
def test_newest_fresh_transient_wins():
    """Among several fresh transients, the newest wins."""
    pending = [
        (Earcon.KEYPRESS, 10.01),
        (Earcon.SOLVE_LOCK, 10.05),  # newest
        (Earcon.KEYPRESS, 10.02),
    ]
    assert select_winner(pending, now=10.06) is Earcon.SOLVE_LOCK


@pytest.mark.unit
def test_important_past_max_age_still_wins():
    """An important earcon is exempt from staleness (10 s old, still wins)."""
    assert select_winner([(Earcon.STARTUP, 0.0)], now=10.0) is Earcon.STARTUP


@pytest.mark.unit
def test_important_beats_newer_transient():
    """important-wins-else-newest: an important beats a newer transient."""
    pending = [
        (Earcon.STARTUP, 10.00),  # important, older
        (Earcon.KEYPRESS, 10.05),  # transient, newer
    ]
    assert select_winner(pending, now=10.06) is Earcon.STARTUP


@pytest.mark.unit
def test_newest_important_wins_among_importants():
    pending = [
        (Earcon.STARTUP, 10.00),
        (Earcon.SHUTDOWN, 10.05),  # newest important
    ]
    assert select_winner(pending, now=10.1) is Earcon.SHUTDOWN


@pytest.mark.unit
def test_only_transients_all_stale_returns_none():
    """A flood of stale transients leaves nothing to play."""
    base = 10.0 - MAX_AGE_S - 1.0
    pending = [(Earcon.KEYPRESS, base + i * 0.001) for i in range(5)]
    assert select_winner(pending, now=10.0) is None


@pytest.mark.unit
def test_important_survives_flood_of_stale_transients():
    """An important earcon wins even buried in stale transients."""
    base = 10.0 - MAX_AGE_S - 1.0
    pending = [(Earcon.KEYPRESS, base + i * 0.001) for i in range(10)]
    pending.insert(5, (Earcon.SHUTDOWN, base))  # old, but important
    assert select_winner(pending, now=10.0) is Earcon.SHUTDOWN
