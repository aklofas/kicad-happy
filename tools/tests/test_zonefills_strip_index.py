"""ZoneFills point queries (zones_at_point, fill_regions_at_point, has_copper_at) go through a
per-fill strip index: only the edges whose y-span overlaps the query's strip are ray-cast. The
answer must equal the full-walk _point_in_polygon for every point, including vertices, edge
midpoints, bbox corners and strip boundaries.

Adapted from the test in the pull request that proposed the strip index (alan-ryu)."""
import math
import random
import sys
import tracemalloc
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))

from pcb.geometry import ZoneFills, _point_in_polygon, _polygon_bbox, _strip_of  # noqa: E402


def _star(n, rng, snap=3):
    pts = []
    for i in range(n):
        a, r = 2 * math.pi * i / n, rng.uniform(2, 50)
        pts.append((round(100 + r * math.cos(a), snap), round(80 + r * math.sin(a), snap)))
    return pts


def _polygons():
    rng = random.Random(1)
    yield [(0, 0), (10, 0), (10, 10), (0, 10)]
    yield [(0, 5), (10, 5), (5, 5)]                                              # zero height
    yield [(x, 0 if x % 2 else 10) for x in range(101)] + [(100, -5), (0, -5)]   # comb
    yield [(0, 0), (40, 0), (40, 40), (30, 40), (30, 10), (10, 10), (10, 40), (0, 40)]  # U shape
    yield [(0, 0), (10, 10)]                                                     # not a polygon
    for n in (3, 20, 200, 3000):
        yield _star(n, rng)


def _query_points(poly, rng):
    x0, y0, x1, y1 = _polygon_bbox(poly)
    pts = list(poly)
    pts += [((poly[i][0] + poly[i - 1][0]) / 2, (poly[i][1] + poly[i - 1][1]) / 2)
            for i in range(len(poly))]
    pts += [(x0, y0), (x1, y1), (x0, y1), (x1, y0)]
    pts += [(rng.uniform(x0, x1), rng.uniform(y0, y1)) for _ in range(3000)]
    zf = ZoneFills()
    zf.add(0, "F.Cu", poly)
    sy0, h, k, _strips = zf._strip_index(0)
    for b in range(k + 1):                                              # strip boundaries
        yb = sy0 + b * h
        x = rng.uniform(x0, x1)
        pts += [(x, yb), (x, math.nextafter(yb, -math.inf)), (x, math.nextafter(yb, math.inf))]
    pts += [(x0, y0 - 1), (x0, y1 + 1), (x0, float("nan"))]             # outside the polygon
    inf = math.inf
    pts += [(x0, inf), (x0, -inf), (inf, y0), (-inf, y1), (inf, inf), (-inf, -inf)]
    return pts


class StripIndex(unittest.TestCase):
    def test_contains_matches_full_walk(self):
        rng = random.Random(2)
        for poly in _polygons():
            zf = ZoneFills()
            zf.add(0, "F.Cu", poly)
            for x, y in _query_points(poly, rng):
                self.assertEqual(zf._contains(0, x, y, poly), _point_in_polygon(x, y, poly),
                                 (len(poly), x, y))

    def test_inflated_fill_keeps_the_edge_distance_rule(self):
        # a stroke centre line: the copper is the polygon grown by the radius
        rng = random.Random(5)
        poly = _star(60, rng)
        zf = ZoneFills()
        zf.add(0, "F.Cu", poly, inflate=0.4)
        for x, y in _query_points(poly, rng)[:600]:
            want = _point_in_polygon(x, y, poly) or zf._near_edge(0, x, y, 0.4)
            self.assertEqual(zf._contains(0, x, y, poly), want, (x, y))

    def test_public_queries_match_full_walk(self):
        rng = random.Random(3)
        polys = list(_polygons())
        zones = [{"net_name": f"N{i}"} for i in range(len(polys))]
        zf = ZoneFills()
        for i, poly in enumerate(polys):
            zf.add(i, "F.Cu", poly)
        for i, poly in enumerate(polys):
            for x, y in _query_points(poly, rng)[:500]:
                want = [j for j, p in enumerate(polys)
                        if _polygon_bbox(p)[0] <= x <= _polygon_bbox(p)[2]
                        and _polygon_bbox(p)[1] <= y <= _polygon_bbox(p)[3]
                        and _point_in_polygon(x, y, p)]
                self.assertEqual([r[1] for r in zf.fill_regions_at_point(x, y, "F.Cu", zones)], want)
                self.assertEqual([z["net_name"] for z in zf.zones_at_point(x, y, "F.Cu", zones)],
                                 [f"N{j}" for j in want])
                self.assertEqual(zf.has_copper_at(x, y, "F.Cu"), bool(want))
                self.assertFalse(zf.has_copper_at(x, y, "B.Cu"))

    def test_strip_holds_every_crossing_edge(self):
        rng = random.Random(4)
        poly = _star(500, rng)
        zf = ZoneFills()
        zf.add(0, "F.Cu", poly)
        y0, h, k, strips = zf._strip_index(0)
        for _x, y in _query_points(poly, rng):
            if y != y:
                continue
            crossing = {i for i in range(len(poly)) if (poly[i][1] > y) != (poly[i - 1][1] > y)}
            self.assertLessEqual(crossing, set(strips[_strip_of(y, y0, h, k)]), y)

    def test_comb_fill_gets_a_bounded_index(self):
        # every tooth is a full-height edge: the strip count falls until the index stays small
        poly = [(x, 0 if x % 2 else 100) for x in range(4000)] + [(3999, -5), (0, -5)]
        zf = ZoneFills()
        zf.add(0, "F.Cu", poly)
        _y0, _h, _k, strips = zf._strip_index(0)
        self.assertLessEqual(sum(map(len, strips)), 32 * len(poly))
        rng = random.Random(6)
        for _ in range(1500):
            x, y = rng.uniform(-1, 4000), rng.uniform(-6, 101)
            self.assertEqual(zf._contains(0, x, y, poly), _point_in_polygon(x, y, poly), (x, y))

    def test_comb_fill_index_build_stays_within_its_bound(self):
        # the strip count is chosen before the strips are filled: no oversized index on the way
        poly = [(x, 0 if x % 2 else 100) for x in range(4000)] + [(3999, -5), (0, -5)]
        zf = ZoneFills()
        zf.add(0, "F.Cu", poly)
        tracemalloc.start()
        try:
            zf._strip_index(0)
            _cur, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        # 32n list slots of 8 bytes, with room for list headers and growth
        self.assertLess(peak, 2 * 32 * len(poly) * 8)

    def test_edges_argument_defaults_to_full_walk(self):
        poly = [(0, 0), (10, 0), (10, 10), (0, 10)]
        for x, y in ((5, 5), (15, 5), (0, 0), (10, 10), (5, 10)):
            self.assertEqual(_point_in_polygon(x, y, poly),
                             _point_in_polygon(x, y, poly, range(len(poly))))


if __name__ == "__main__":
    unittest.main()
