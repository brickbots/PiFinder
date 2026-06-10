import math
import pytest
from PiFinder.cat_images import (
    cardinal_vectors,
    size_overlay_points,
    vertex_overlay_points,
)
from PiFinder.composite_object import SizeObject


def approx_pt(pt, abs=1e-6):
    return pytest.approx(pt, abs=abs)


# --- cardinal_vectors ---


@pytest.mark.unit
class TestCardinalVectors:
    def test_no_rotation(self):
        """image_rotate=0: POSS north-up, east-left → N at (0, -1), E at (-1, 0)."""
        (nx, ny), (ex, ey) = cardinal_vectors(0)
        assert (nx, ny) == approx_pt((0, -1))
        assert (ex, ey) == approx_pt((-1, 0))

    def test_180_rotation(self):
        """image_rotate=180: N flips to (0, 1), E to (1, 0)."""
        (nx, ny), (ex, ey) = cardinal_vectors(180)
        assert (nx, ny) == approx_pt((0, 1))
        assert (ex, ey) == approx_pt((1, 0))

    def test_90_rotation(self):
        """image_rotate=90: N at (1, 0), E at (0, -1)."""
        (nx, ny), (ex, ey) = cardinal_vectors(90)
        assert (nx, ny) == approx_pt((1, 0))
        assert (ex, ey) == approx_pt((0, -1))

    def test_flip_mirrors_x(self):
        """flip negates x components of both vectors."""
        (nx, ny), (ex, ey) = cardinal_vectors(0, fx=-1)
        assert (nx, ny) == approx_pt((0, -1))
        assert (ex, ey) == approx_pt((1, 0))

    def test_flop_mirrors_y(self):
        """flop negates y components of both vectors."""
        (nx, ny), (ex, ey) = cardinal_vectors(0, fy=-1)
        assert (nx, ny) == approx_pt((0, 1))
        assert (ex, ey) == approx_pt((-1, 0))

    def test_flip_and_flop(self):
        """Both flip and flop: equivalent to 180° rotation of vectors."""
        (nx, ny), (ex, ey) = cardinal_vectors(0, fx=-1, fy=-1)
        assert (nx, ny) == approx_pt((0, 1))
        assert (ex, ey) == approx_pt((1, 0))

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
        """No rotation, no PA: major axis aligned with North (vertical)."""
        cx, cy = 64, 64
        pts = size_overlay_points([120, 60], 0, 0, 1.0, cx, cy)
        xs = [p[0] - cx for p in pts]
        ys = [p[1] - cy for p in pts]
        # PA=0 → major axis along North → vertical
        assert max(abs(x) for x in xs) == pytest.approx(30, abs=0.5)
        assert max(abs(y) for y in ys) == pytest.approx(60, abs=0.5)

    def test_two_extents_rotation(self):
        """90° image rotation moves major axis from vertical to horizontal."""
        cx, cy = 64, 64
        pts = size_overlay_points([120, 60], 0, 90, 1.0, cx, cy)
        xs = [p[0] - cx for p in pts]
        ys = [p[1] - cy for p in pts]
        # 90° rotation: North moves to +X, major axis now horizontal
        assert max(abs(x) for x in xs) == pytest.approx(60, abs=0.5)
        assert max(abs(y) for y in ys) == pytest.approx(30, abs=0.5)

    def test_position_angle(self):
        """PA=90 rotates opposite to image_rotate (PA goes N→E, image_rotate goes CW)."""
        cx, cy = 64, 64
        pts_rot = size_overlay_points([120, 60], 0, 270, 1.0, cx, cy)
        pts_pa = size_overlay_points([120, 60], 90, 0, 1.0, cx, cy)
        for a, b in zip(pts_rot, pts_pa):
            assert a[0] == pytest.approx(b[0], abs=1e-6)
            assert a[1] == pytest.approx(b[1], abs=1e-6)

    def test_pa90_aligns_with_east(self):
        """PA=90° major axis must align with the East vector from cardinal_vectors."""
        cx, cy = 64, 64
        for rot in [0, 90, 180, 270]:
            _, (ex, ey) = cardinal_vectors(rot)
            pts = size_overlay_points([200, 40], 90, rot, 1.0, cx, cy)
            dists = [(p[0] - cx, p[1] - cy) for p in pts]
            farthest = max(dists, key=lambda d: math.hypot(*d))
            direction = (
                farthest[0] / math.hypot(*farthest),
                farthest[1] / math.hypot(*farthest),
            )
            dot = abs(direction[0] * ex + direction[1] * ey)
            assert dot == pytest.approx(1.0, abs=0.02), (
                f"PA=90 major axis not along East at image_rotate={rot}"
            )

    def test_pa0_aligns_with_north(self):
        """PA=0 major axis must align with the North vector from cardinal_vectors."""
        cx, cy = 64, 64
        for rot in [0, 90, 180, 270]:
            (nx, ny), _ = cardinal_vectors(rot)
            pts = size_overlay_points([200, 40], 0, rot, 1.0, cx, cy)
            # Find the point farthest from center — should be along North
            dists = [(p[0] - cx, p[1] - cy) for p in pts]
            farthest = max(dists, key=lambda d: math.hypot(*d))
            direction = (
                farthest[0] / math.hypot(*farthest),
                farthest[1] / math.hypot(*farthest),
            )
            # Should be parallel to North (same or opposite direction)
            dot = abs(direction[0] * nx + direction[1] * ny)
            assert dot == pytest.approx(1.0, abs=0.02), (
                f"PA=0 major axis not along North at image_rotate={rot}"
            )

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


# --- SizeObject vertex mode ---


@pytest.mark.unit
class TestSizeObjectVertices:
    def test_from_vertices_stores_nested_pairs(self):
        verts = [[10.0, 20.0], [10.1, 20.1], [10.2, 20.0]]
        s = SizeObject.from_vertices(verts)
        assert s.extents == verts
        assert s.position_angle == 0.0

    def test_is_vertices_true(self):
        s = SizeObject.from_vertices([[10.0, 20.0], [10.1, 20.1]])
        assert s.is_vertices is True

    def test_is_vertices_false_for_numeric(self):
        s = SizeObject.from_arcsec(100, 50)
        assert s.is_vertices is False

    def test_is_vertices_false_for_empty(self):
        s = SizeObject([])
        assert s.is_vertices is False

    def test_max_extent_arcsec_same_dec(self):
        """Two points at same dec, 1° apart in RA at dec=0."""
        s = SizeObject.from_vertices([[10.0, 0.0], [11.0, 0.0]])
        expected = 3600.0  # 1 degree = 3600 arcsec
        assert s.max_extent_arcsec == pytest.approx(expected, rel=1e-3)

    def test_max_extent_arcsec_same_ra(self):
        """Two points at same RA, 0.5° apart in dec."""
        s = SizeObject.from_vertices([[10.0, 20.0], [10.0, 20.5]])
        expected = 1800.0  # 0.5 degree
        assert s.max_extent_arcsec == pytest.approx(expected, rel=1e-3)

    def test_max_extent_arcsec_numeric_fallback(self):
        s = SizeObject.from_arcsec(100, 200, 150)
        assert s.max_extent_arcsec == 200

    def test_to_display_string_vertices(self):
        """Vertex mode shows ~span format."""
        s = SizeObject.from_vertices([[10.0, 20.0], [10.0, 20.5]])
        display = s.to_display_string()
        assert display.startswith("~")
        assert "'" in display  # 1800 arcsec = 30 arcmin

    def test_json_roundtrip(self):
        verts = [[10.0, 20.0], [10.1, 20.1]]
        s = SizeObject.from_vertices(verts)
        s2 = SizeObject.from_json(s.to_json())
        assert s2.is_vertices is True
        assert s2.extents == verts


# --- vertex_overlay_points ---


@pytest.mark.unit
class TestVertexOverlayPoints:
    def test_center_vertex_at_center(self):
        """A vertex at the object center projects to (cx, cy)."""
        pts = vertex_overlay_points([[10.0, 20.0]], 10.0, 20.0, 0, 1.0, 64, 64)
        assert len(pts) == 1
        assert pts[0][0] == pytest.approx(64, abs=0.1)
        assert pts[0][1] == pytest.approx(64, abs=0.1)

    def test_offset_vertex_north(self):
        """A vertex 100" north of center should appear above center (lower y)."""
        dec_offset = 100.0 / 3600.0  # 100 arcsec in degrees
        pts = vertex_overlay_points(
            [[10.0, 20.0 + dec_offset]], 10.0, 20.0, 0, 1.0, 64, 64
        )
        # image_rotate=0: POSS has N at top of raw image but after
        # the 180+roll rotation in get_display_image, here we test
        # raw projection
        assert len(pts) == 1
        # With image_rotate=0 and no flip, north (positive dec) goes to negative dy
        assert pts[0][1] < 64

    def test_two_vertices_produce_two_points(self):
        pts = vertex_overlay_points(
            [[10.0, 20.0], [10.01, 20.01]], 10.0, 20.0, 0, 1.0, 64, 64
        )
        assert len(pts) == 2

    def test_scaling(self):
        """Doubling px_per_arcsec doubles offset from center."""
        dec_off = 100.0 / 3600.0
        pts1 = vertex_overlay_points(
            [[10.0, 20.0 + dec_off]], 10.0, 20.0, 0, 1.0, 64, 64
        )
        pts2 = vertex_overlay_points(
            [[10.0, 20.0 + dec_off]], 10.0, 20.0, 0, 2.0, 64, 64
        )
        dx1 = pts1[0][0] - 64
        dy1 = pts1[0][1] - 64
        dx2 = pts2[0][0] - 64
        dy2 = pts2[0][1] - 64
        assert dx2 == pytest.approx(2 * dx1, abs=0.1)
        assert dy2 == pytest.approx(2 * dy1, abs=0.1)
