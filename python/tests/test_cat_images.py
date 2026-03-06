import math
import pytest
from PiFinder.cat_images import cardinal_vectors, size_overlay_points


def approx_pt(pt, abs=1e-6):
    return pytest.approx(pt, abs=abs)


# --- cardinal_vectors ---


@pytest.mark.unit
class TestCardinalVectors:
    def test_no_rotation(self):
        """image_rotate=0: POSS north-up → N at (0, -1), E at (1, 0)."""
        (nx, ny), (ex, ey) = cardinal_vectors(0)
        assert (nx, ny) == approx_pt((0, -1))
        assert (ex, ey) == approx_pt((1, 0))

    def test_180_rotation(self):
        """image_rotate=180: N flips to (0, 1), E to (-1, 0)."""
        (nx, ny), (ex, ey) = cardinal_vectors(180)
        assert (nx, ny) == approx_pt((0, 1))
        assert (ex, ey) == approx_pt((-1, 0))

    def test_90_rotation(self):
        """image_rotate=90: N at (1, 0), E at (0, 1)."""
        (nx, ny), (ex, ey) = cardinal_vectors(90)
        assert (nx, ny) == approx_pt((1, 0))
        assert (ex, ey) == approx_pt((0, 1))

    def test_flip_mirrors_x(self):
        """flip negates x components of both vectors."""
        (nx, ny), (ex, ey) = cardinal_vectors(0, fx=-1)
        assert (nx, ny) == approx_pt((0, -1))
        assert (ex, ey) == approx_pt((-1, 0))

    def test_flop_mirrors_y(self):
        """flop negates y components of both vectors."""
        (nx, ny), (ex, ey) = cardinal_vectors(0, fy=-1)
        assert (nx, ny) == approx_pt((0, 1))
        assert (ex, ey) == approx_pt((1, 0))

    def test_flip_and_flop(self):
        """Both flip and flop: equivalent to 180° rotation of vectors."""
        (nx, ny), (ex, ey) = cardinal_vectors(0, fx=-1, fy=-1)
        assert (nx, ny) == approx_pt((0, 1))
        assert (ex, ey) == approx_pt((-1, 0))

    def test_orthogonality(self):
        """N and E should always be perpendicular."""
        for angle in [0, 45, 90, 135, 180, 270]:
            for fx, fy in [(1, 1), (-1, 1), (1, -1), (-1, -1)]:
                (nx, ny), (ex, ey) = cardinal_vectors(angle, fx, fy)
                dot = nx * ex + ny * ey
                assert dot == pytest.approx(0, abs=1e-10), (
                    f"Not orthogonal at angle={angle}, fx={fx}, fy={fy}"
                )

    def test_unit_length(self):
        """N and E vectors should have unit length."""
        for angle in [0, 30, 45, 90, 180, 270]:
            (nx, ny), (ex, ey) = cardinal_vectors(angle)
            assert math.hypot(nx, ny) == pytest.approx(1)
            assert math.hypot(ex, ey) == pytest.approx(1)


# --- size_overlay_points ---


@pytest.mark.unit
class TestSizeOverlayPoints:
    def test_single_extent_returns_none(self):
        """1 extent → None (caller uses native ellipse)."""
        assert size_overlay_points([100], 0, 0, 1.0, 64, 64) is None

    def test_empty_returns_none(self):
        assert size_overlay_points([], 0, 0, 1.0, 64, 64) is None

    def test_two_extents_point_count(self):
        """2 extents → 36-point ellipse polygon."""
        pts = size_overlay_points([120, 60], 0, 0, 1.0, 64, 64)
        assert len(pts) == 36

    def test_two_extents_centered(self):
        """Ellipse centroid should be at (cx, cy)."""
        cx, cy = 64, 64
        pts = size_overlay_points([120, 60], 0, 0, 1.0, cx, cy)
        avg_x = sum(p[0] for p in pts) / len(pts)
        avg_y = sum(p[1] for p in pts) / len(pts)
        assert avg_x == pytest.approx(cx, abs=0.1)
        assert avg_y == pytest.approx(cy, abs=0.1)

    def test_two_extents_symmetry(self):
        """No rotation, no PA: ellipse should be symmetric about axes."""
        cx, cy = 64, 64
        pts = size_overlay_points([120, 60], 0, 0, 1.0, cx, cy)
        xs = [p[0] - cx for p in pts]
        ys = [p[1] - cy for p in pts]
        assert max(abs(x) for x in xs) == pytest.approx(60, abs=0.5)
        assert max(abs(y) for y in ys) == pytest.approx(30, abs=0.5)

    def test_two_extents_rotation(self):
        """90° rotation swaps major/minor axis orientation."""
        cx, cy = 64, 64
        pts = size_overlay_points([120, 60], 0, 90, 1.0, cx, cy)
        xs = [p[0] - cx for p in pts]
        ys = [p[1] - cy for p in pts]
        # After 90° rotation, the 120-arcsec axis is now vertical
        assert max(abs(x) for x in xs) == pytest.approx(30, abs=0.5)
        assert max(abs(y) for y in ys) == pytest.approx(60, abs=0.5)

    def test_position_angle(self):
        """PA=90 should rotate the ellipse like image_rotate=90."""
        cx, cy = 64, 64
        pts_rot = size_overlay_points([120, 60], 0, 90, 1.0, cx, cy)
        pts_pa = size_overlay_points([120, 60], 90, 0, 1.0, cx, cy)
        for a, b in zip(pts_rot, pts_pa):
            assert a[0] == pytest.approx(b[0], abs=1e-6)
            assert a[1] == pytest.approx(b[1], abs=1e-6)

    def test_flip_mirrors_x(self):
        """fx=-1 mirrors all points horizontally around cx."""
        cx, cy = 64, 64
        pts_normal = size_overlay_points([120, 60], 30, 180, 1.0, cx, cy)
        pts_flip = size_overlay_points([120, 60], 30, 180, 1.0, cx, cy, fx=-1)
        for a, b in zip(pts_normal, pts_flip):
            assert a[0] - cx == pytest.approx(-(b[0] - cx), abs=1e-6)
            assert a[1] == pytest.approx(b[1], abs=1e-6)

    def test_flop_mirrors_y(self):
        """fy=-1 mirrors all points vertically around cy."""
        cx, cy = 64, 64
        pts_normal = size_overlay_points([120, 60], 30, 180, 1.0, cx, cy)
        pts_flop = size_overlay_points([120, 60], 30, 180, 1.0, cx, cy, fy=-1)
        for a, b in zip(pts_normal, pts_flop):
            assert a[0] == pytest.approx(b[0], abs=1e-6)
            assert a[1] - cy == pytest.approx(-(b[1] - cy), abs=1e-6)

    def test_three_extents_point_count(self):
        """3+ extents → polygon with len(extents) points."""
        pts = size_overlay_points([100, 80, 60, 90], 0, 0, 1.0, 64, 64)
        assert len(pts) == 4

    def test_px_per_arcsec_scaling(self):
        """Doubling px_per_arcsec doubles the distance from center."""
        cx, cy = 64, 64
        pts1 = size_overlay_points([120, 60], 0, 0, 1.0, cx, cy)
        pts2 = size_overlay_points([120, 60], 0, 0, 2.0, cx, cy)
        for a, b in zip(pts1, pts2):
            assert (b[0] - cx) == pytest.approx(2 * (a[0] - cx), abs=1e-6)
            assert (b[1] - cy) == pytest.approx(2 * (a[1] - cy), abs=1e-6)
