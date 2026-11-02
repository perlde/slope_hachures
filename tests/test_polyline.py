# -*- coding: utf-8 -*-
"""Pure-Python tests of core.polyline (no QGIS needed).

SPDX-License-Identifier: GPL-3.0-or-later
"""

import math
import random
import unittest
from fractions import Fraction

from _bootstrap import plugin_module

polyline = plugin_module("core.polyline")
Polyline = polyline.Polyline


def naive_point_at(points, station):
    remaining = max(0.0, station)
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        seg = math.hypot(x2 - x1, y2 - y1)
        if remaining <= seg:
            t = 0.0 if seg == 0 else remaining / seg
            return x1 + t * (x2 - x1), y1 + t * (y2 - y1)
        remaining -= seg
    return points[-1]


def exact_crossings(points, origin, end):
    """Reference: exact rational intersection points of a segment with a polyline."""
    o = [Fraction(v) for v in origin]
    e = [Fraction(v) for v in end]
    found = set()
    for (ax, ay), (bx, by) in zip(points, points[1:]):
        a = (Fraction(ax), Fraction(ay))
        b = (Fraction(bx), Fraction(by))
        r = (e[0] - o[0], e[1] - o[1])
        s = (b[0] - a[0], b[1] - a[1])
        den = r[0] * s[1] - r[1] * s[0]
        if den == 0:
            continue  # parallel cases are covered by dedicated tests
        t = ((a[0] - o[0]) * s[1] - (a[1] - o[1]) * s[0]) / den
        u = ((a[0] - o[0]) * r[1] - (a[1] - o[1]) * r[0]) / den
        if 0 <= t <= 1 and 0 <= u <= 1:
            found.add((float(o[0] + t * r[0]), float(o[1] + t * r[1])))
    return found


def random_polyline(rng, count):
    x = y = 0.0
    points = [(x, y)]
    for _ in range(count):
        x += rng.uniform(-8.0, 12.0)
        y += rng.uniform(-8.0, 8.0)
        points.append((x, y))
    return points


def grid_lookup(line):
    """A simple pure-Python segment lookup, standing in for QgsSpatialIndex."""
    boxes = line.segment_boxes()

    def lookup(box):
        xmin, ymin, xmax, ymax = box
        return [i for i, (a, b, c, d) in enumerate(boxes)
                if not (a > xmax or c < xmin or b > ymax or d < ymin)]
    return lookup


class OrientationTest(unittest.TestCase):
    def test_signs(self):
        self.assertEqual(polyline.orientation(0, 0, 1, 0, 0, 1), 1)
        self.assertEqual(polyline.orientation(0, 0, 1, 0, 0, -1), -1)
        self.assertEqual(polyline.orientation(0, 0, 1, 0, 2, 0), 0)

    def test_exact_near_collinear(self):
        # Classic case where naive floating point gets the sign wrong.
        rng = random.Random(3)
        for _ in range(2000):
            ax, ay = rng.uniform(-1, 1), rng.uniform(-1, 1)
            bx, by = rng.uniform(-1, 1), rng.uniform(-1, 1)
            t = rng.uniform(-2, 2)
            cx, cy = ax + t * (bx - ax), ay + t * (by - ay)  # (almost) on the line
            exact = ((Fraction(ax) - Fraction(cx)) * (Fraction(by) - Fraction(cy))
                     - (Fraction(ay) - Fraction(cy)) * (Fraction(bx) - Fraction(cx)))
            expected = (exact > 0) - (exact < 0)
            self.assertEqual(polyline.orientation(ax, ay, bx, by, cx, cy), expected)


class StationTest(unittest.TestCase):
    def test_point_at_matches_walk(self):
        rng = random.Random(1)
        for _ in range(200):
            points = random_polyline(rng, rng.randint(1, 40))
            line = Polyline(points)
            for _ in range(10):
                s = rng.uniform(-5.0, line.length + 5.0)
                got = line.point_at(s)
                want = naive_point_at(points, min(max(s, 0.0), line.length))
                self.assertLess(math.dist(got, want), 1e-9)

    def test_vertices_are_exact(self):
        line = Polyline([(0.1, 0.2), (3.3, 4.7), (9.9, 1.1)])
        self.assertEqual(line.point_at(line.cum[1]), (3.3, 4.7))
        self.assertEqual(line.point_at(line.length), (9.9, 1.1))
        self.assertEqual(line.point_at(0.0), (0.1, 0.2))

    def test_tangent(self):
        line = Polyline([(0, 0), (10, 0), (10, 10)])
        self.assertEqual(line.tangent(5.0, 1.0), (1.0, 0.0))
        tx, ty = line.tangent(10.0, 1.0)  # across the corner
        self.assertAlmostEqual(tx, math.sqrt(0.5))
        self.assertAlmostEqual(ty, math.sqrt(0.5))
        self.assertIsNone(Polyline([(0, 0), (0, 0)]).tangent(0.0, 1.0))

    def test_rejects_single_point(self):
        with self.assertRaises(ValueError):
            Polyline([(0, 0)])


class RayTest(unittest.TestCase):
    def test_hits_match_exact_reference(self):
        rng = random.Random(11)
        for _ in range(300):
            points = random_polyline(rng, rng.randint(2, 60))
            line = Polyline(points)
            xs = [p[0] for p in points]
            for _ in range(20):
                origin = (rng.uniform(min(xs), max(xs)), rng.uniform(-20, 20))
                angle = rng.uniform(0, 2 * math.pi)
                direction = (math.cos(angle), math.sin(angle))
                length = rng.uniform(5, 60)
                hits = line.ray_hits(origin, direction, length)
                end = (origin[0] + direction[0] * length, origin[1] + direction[1] * length)
                want = exact_crossings(points, origin, end)
                self.assertEqual(len(hits), len(want))
                for hit in hits:
                    self.assertTrue(any(math.dist(hit.point, w) < 1e-9 for w in want))
                    self.assertLess(math.dist(line.point_at(hit.param), hit.point), 1e-7)

    def test_vertex_hit_reported_once_as_vertex(self):
        line = Polyline([(0, 0), (10, 0), (10, 10)])
        hits = line.ray_hits((5, -5), (math.sqrt(0.5), math.sqrt(0.5)), 20)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].point, (10.0, 0.0))
        self.assertEqual(hits[0].param, 10.0)

    def test_collinear_overlap_returns_end_points(self):
        line = Polyline([(0, 0), (10, 0), (10, 10)])
        hits = line.ray_hits((10, -5), (0.0, 1.0), 25)
        self.assertEqual([h.point for h in hits], [(10.0, 0.0), (10.0, 10.0)])
        self.assertEqual([h.param for h in hits], [10.0, 20.0])

    def test_grazing_corner_follows_exact_predicate(self):
        # The ray end point is not exactly representable: whether it touches the
        # corner is decided exactly, like GEOS does, not with a tolerance.
        line = Polyline([(0, -4), (4, -4), (4, 0)])
        d = (math.sqrt(0.5), -math.sqrt(0.5))
        hits = line.ray_hits((0.0, 0.0), d, 20.0)
        end = (d[0] * 20.0, d[1] * 20.0)
        want = exact_crossings(line.points, (0.0, 0.0), end)
        self.assertEqual(len(hits), len(want))

    def test_first_hit_with_lookup_equals_scan(self):
        rng = random.Random(5)
        for _ in range(200):
            points = random_polyline(rng, rng.randint(5, 150))
            plain = Polyline(points)
            indexed = Polyline(points)
            indexed.attach_lookup(grid_lookup(indexed))
            xs = [p[0] for p in points]
            for _ in range(10):
                origin = (rng.uniform(min(xs), max(xs)), rng.uniform(-20, 20))
                angle = rng.uniform(0, 2 * math.pi)
                direction = (math.cos(angle), math.sin(angle))
                length = rng.uniform(5, 80)
                a = plain.first_hit(origin, direction, length, 0.05)
                b = indexed.first_hit(origin, direction, length, 0.05)
                self.assertEqual(a, b)

    def test_first_hit_respects_limits(self):
        line = Polyline([(-10, 1), (10, 1)])
        self.assertIsNone(line.first_hit((0, 0), (0.0, 1.0), 1.0, 0.05))   # hit at the end: excluded
        self.assertIsNone(line.first_hit((0, 0.98), (0.0, 1.0), 5.0, 0.05))  # closer than min
        self.assertAlmostEqual(line.first_hit((0, 0), (0.0, 1.0), 5.0, 0.05).distance, 1.0)


class NearestTest(unittest.TestCase):
    def test_first_segment_wins_tie(self):
        line = Polyline([(0, 0), (10, 0), (10, 10)])
        hit = line.nearest((5, 5), 100.0)
        self.assertEqual(hit.point, (5.0, 0.0))
        self.assertEqual(hit.param, 5.0)

    def test_max_distance(self):
        line = Polyline([(0, 0), (10, 0)])
        self.assertIsNone(line.nearest((5, 5), 4.9))
        self.assertEqual(line.nearest((5, 5), 5.0).point, (5.0, 0.0))

    def test_lookup_equals_scan(self):
        rng = random.Random(9)
        for _ in range(200):
            points = random_polyline(rng, rng.randint(5, 150))
            plain = Polyline(points)
            indexed = Polyline(points)
            indexed.attach_lookup(grid_lookup(indexed))
            for _ in range(10):
                p = (rng.uniform(-50, 400), rng.uniform(-60, 60))
                dist = rng.uniform(1, 80)
                self.assertEqual(plain.nearest(p, dist), indexed.nearest(p, dist))


class RingHelperTest(unittest.TestCase):
    def test_signed_area(self):
        square = [(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)]
        self.assertGreater(polyline.signed_area(square), 0)
        self.assertLess(polyline.signed_area(square[::-1]), 0)

    def test_circular_delta(self):
        self.assertAlmostEqual(polyline.circular_delta(390.0, 10.0, 400.0), 20.0)
        self.assertAlmostEqual(polyline.circular_delta(10.0, 390.0, 400.0), -20.0)
        self.assertAlmostEqual(polyline.circular_delta(10.0, 30.0, 400.0), 20.0)

    def test_orientation_vote(self):
        self.assertGreater(polyline.orientation_vote([1, 2, 3, 4], None, False), 0)
        self.assertLess(polyline.orientation_vote([4, 3, 2, 1], None, False), 0)
        # wrapping forward across the ring start
        self.assertGreater(polyline.orientation_vote([380, 390, 5, 15], 400.0, False), 0)

    def test_ring_period(self):
        ring = Polyline([(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)])
        self.assertEqual(ring.ring_period(0.05), 40.0)
        almost = Polyline([(0, 0), (10, 0), (10, 10), (0, 10), (0, 0.03)])
        self.assertAlmostEqual(almost.ring_period(0.05), 40.0)
        self.assertIsNone(Polyline([(0, 0), (10, 0), (10, 10)]).ring_period(0.05))


if __name__ == "__main__":
    unittest.main()
