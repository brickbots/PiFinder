"""
Polar alignment package.

The solver lives in :mod:`PiFinder.polar_alignment.polar_alignment`; this
package re-exports its API so ``from PiFinder.polar_alignment import ...``
keeps working.  The Monte Carlo accuracy benchmark is
``python -m PiFinder.polar_alignment.benchmark``.

The underscore names are re-exported for the test suite.
"""

from PiFinder.polar_alignment.polar_alignment import (  # noqa: F401
    MIN_SWEEP_DEG,
    attitude_mat,
    axis_to_altaz_error,
    correction_target,
    extract_plate_solve,
    get_platform_adjustments,
    make_solve_2,
    _SKYFIELD_TETE_FRAME,
    _precession_matrix,
)
