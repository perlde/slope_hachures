# -*- coding: utf-8 -*-
"""Engine tests against real QGIS/GEOS (skipped without QGIS).

SPDX-License-Identifier: GPL-3.0-or-later
"""

import math
import random
import unittest

from _bootstrap import HAS_QGIS, plugin_module, qgis_app

if HAS_QGIS:
    from qgis.core import QgsGeometry, QgsPointXY, QgsProcessingFeedback

    geometry_utils = plugin_module("core.geometry_utils")
    models = plugin_module("core.models")
    slope_engine = plugin_module("core.slope_engine")
    tuning = plugin_module("core.tuning")


def setUpModule():
    if HAS_QGIS:
        qgis_app()


def line(points):
    return QgsGeometry.fromPolylineXY([QgsPointXY(x, y) for x, y in points])


def circle(radius, ccw=True, start_deg=0.0, count=180, close=True):
    points = []
    for k in range(count):
        angle = math.radians(start_deg) + (1 if ccw else -1) * 2 * math.pi * k / count
        points.append((radius * math.cos(angle), radius * math.sin(angle)))
    if close:
        points.append(points[0])
    return points


def random_points(rng, count, step=10.0):
    x = y = 0.0
    points = [(x, y)]
    for _ in range(count):
        x += rng.uniform(0.2, step)
        y += rng.uniform(-step / 2, step / 2)
        points.append((x, y))
    return points


def longs(hachures):
    return [h for h in hachures if h.hachure_type == "lang"]


def max_gap(hachures):
    stations = sorted(h.station for h in longs(hachures))
    return max(b - a for a, b in zip(stations, stations[1:]))


class RecordingFeedback(QgsProcessingFeedback if HAS_QGIS else object):
    def __init__(self):
        super().__init__()
        self.warnings = []

    def pushWarning(self, warning):  # noqa: N802 (QGIS API name)
        self.warnings.append(warning)


@unittest.skipUnless(HAS_QGIS, "needs QGIS")
class GeosParityTest(unittest.TestCase):
    """The Polyline queries must give the same answers as the QgsGeometry calls they replace."""

    def test_point_at_matches_interpolate(self):
        rng = random.Random(1)
        for _ in range(100):
            points = random_points(rng, rng.randint(1, 80))
            geom = line(points)
            poly = geometry_utils.to_polyline(geom)
            self.assertAlmostEqual(poly.length, geom.length(), places=9)
            for _ in range(10):
                s = rng.uniform(0.0, geom.length())
                want = geom.interpolate(s).asPoint()
                got = poly.point_at(s)
                self.assertLess(math.hypot(got[0] - want.x(), got[1] - want.y()), 1e-8)

    def _geos_first_hit(self, geom, origin, direction, length):
        """The 1.1.2 implementation: GEOS intersection plus lineLocatePoint."""
        ray = geometry_utils.ray(QgsPointXY(*origin), direction, length)
        best = None
        best_dist = length
        inter = ray.intersection(geom)
        for p in geometry_utils.extract_points(inter):
            d = math.hypot(p.x() - origin[0], p.y() - origin[1])
            if tuning.MIN_TARGET_DIST < d < best_dist:
                best_dist = d
                best = (d, (p.x(), p.y()), geom.lineLocatePoint(QgsGeometry.fromPointXY(p)))
        return best

    def _check_rays(self, rng, points, rays=40):
        geom = line(points)
        for indexed in (False, True):
            poly = geometry_utils.to_polyline(geom, indexed=indexed)
            xs = [p[0] for p in points]
            for _ in range(rays):
                origin = (rng.uniform(min(xs), max(xs)), rng.uniform(-25, 25))
                angle = rng.uniform(0, 2 * math.pi)
                direction = (math.cos(angle), math.sin(angle))
                length = rng.uniform(5, 80)
                want = self._geos_first_hit(geom, origin, direction, length)
                got = poly.first_hit(origin, direction, length, tuning.MIN_TARGET_DIST)
                if want is None:
                    self.assertIsNone(got)
                    continue
                self.assertIsNotNone(got)
                self.assertAlmostEqual(got.distance, want[0], places=7)
                self.assertLess(math.dist(got.point, want[1]), 1e-7)
                self.assertAlmostEqual(got.param, want[2], places=6)

    def test_ray_hits_match_geos_random(self):
        rng = random.Random(2)
        for _ in range(60):
            self._check_rays(rng, random_points(rng, rng.choice([5, 40, 200])))

    def test_ray_hits_match_geos_grid(self):
        # Integer staircase: rays through vertices and collinear overlaps. The line must
        # be valid (no overlapping back-and-forth steps), as the plugin rejects anything
        # else; on such input GEOS falls back to a snapping overlay.
        rng = random.Random(3)
        checked = skipped = 0
        for _ in range(60):
            x = y = 0
            points = [(0, 0)]
            vertical = False
            for _ in range(rng.randint(30, 90)):
                if vertical or rng.random() < 0.5:
                    x += rng.choice([1, 2, 4])
                    vertical = False
                else:
                    y += rng.choice([-2, -1, 1, 2])
                    vertical = True
                points.append((x, y))
            geom = line(points)
            self.assertFalse(geometry_utils.has_self_intersection(geom))
            for indexed in (False, True):
                poly = geometry_utils.to_polyline(geom, indexed=indexed)
                for _ in range(40):
                    origin = (rng.randint(0, max(1, x)), rng.randint(-6, 6))
                    direction = rng.choice([(1.0, 0.0), (0.0, 1.0), (0.0, -1.0),
                                            (math.sqrt(0.5), math.sqrt(0.5)),
                                            (math.sqrt(0.5), -math.sqrt(0.5))])
                    length = float(rng.randint(3, 20))
                    if self._grazes_vertex(points, origin, direction, length):
                        skipped += 1
                        continue
                    checked += 1
                    want = self._geos_first_hit(geom, origin, direction, length)
                    got = poly.first_hit(origin, direction, length, tuning.MIN_TARGET_DIST)
                    if want is None:
                        self.assertIsNone(got, (points, origin, direction, length))
                        continue
                    self.assertIsNotNone(got, (points, origin, direction, length))
                    detail = repr((indexed, points, origin, direction, length, want, got))
                    self.assertAlmostEqual(got.distance, want[0], places=7, msg=detail)
                    self.assertAlmostEqual(got.param, want[2], places=6, msg=detail)
        self.assertGreater(checked, 5 * skipped)

    @staticmethod
    def _grazes_vertex(points, origin, direction, length):
        """True if a vertex lies within 1e-9 of the ray without lying exactly on it.

        The exact predicate says the ray passes the vertex; GEOS may snap the ray onto
        it instead (its overlay falls back to snapping when floating-point noding is
        inconsistent). Only synthetic data, like rays at exactly 45 degrees through an
        integer grid, produce such cases.
        """
        polyline = plugin_module("core.polyline")
        ox, oy = origin
        tx, ty = ox + direction[0] * length, oy + direction[1] * length
        for vx, vy in points:
            u = max(0.0, min(1.0, ((vx - ox) * (tx - ox) + (vy - oy) * (ty - oy))
                             / ((tx - ox) ** 2 + (ty - oy) ** 2)))
            dist = math.hypot(ox + u * (tx - ox) - vx, oy + u * (ty - oy) - vy)
            if dist < 1e-9 and polyline.orientation(ox, oy, tx, ty, vx, vy) != 0:
                return True
        return False

    def test_nearest_matches_geos(self):
        rng = random.Random(4)
        for _ in range(60):
            points = random_points(rng, rng.choice([5, 40, 200]))
            geom = line(points)
            for indexed in (False, True):
                poly = geometry_utils.to_polyline(geom, indexed=indexed)
                for _ in range(30):
                    p = QgsPointXY(rng.uniform(-20, points[-1][0] + 20), rng.uniform(-40, 40))
                    max_dist = rng.uniform(1, 60)
                    near = geom.nearestPoint(QgsGeometry.fromPointXY(p)).asPoint()
                    d = math.hypot(near.x() - p.x(), near.y() - p.y())
                    got = poly.nearest((p.x(), p.y()), max_dist)
                    if d > max_dist:
                        self.assertIsNone(got)
                        continue
                    self.assertIsNotNone(got)
                    self.assertAlmostEqual(got.distance, d, places=7)
                    param = geom.lineLocatePoint(QgsGeometry.fromPointXY(near))
                    self.assertAlmostEqual(got.param, param, places=6)


@unittest.skipUnless(HAS_QGIS, "needs QGIS")
class EngineTest(unittest.TestCase):
    def setUp(self):
        self.engine = slope_engine.SlopeEngine(interval=4.0, short_ratio=0.5, max_search_dist=50.0)

    def test_open_parallel_lines(self):
        result = self.engine.compute_hachures(line([(0, 0), (100, 0)]), line([(0, -10), (100, -10)]))
        self.assertEqual(len(result), 51)          # same as version 1.1.2
        self.assertEqual(len(longs(result)), 26)
        self.assertAlmostEqual(max_gap(result), 4.0)
        for h in longs(result):
            self.assertAlmostEqual(h.length, 10.0, places=6)

    def _assert_ring_covered(self, crest, toe, width):
        result = self.engine.compute_hachures(line(crest), line(toe))
        self.assertTrue(result)
        self.assertLessEqual(max_gap(result), 4.0 * 1.05)
        ends = [tuple(round(c, 6) for p in h.geometry.asPolyline() for c in (p.x(), p.y()))
                for h in longs(result)]
        self.assertEqual(len(ends), len(set(ends)), "duplicate long hachure")
        for h in longs(result):
            self.assertAlmostEqual(h.length, width, delta=0.2)
        return result

    def test_rings_same_orientation_offset_start(self):
        self._assert_ring_covered(circle(60, True, 0), circle(70, True, 120), 10.0)

    def test_rings_opposite_orientation(self):
        # version 1.1.2: 3 long hachures and a 373 m gap on this ring
        self._assert_ring_covered(circle(60, True, 0), circle(70, False, 0), 10.0)

    def test_rings_inner_toe(self):
        self._assert_ring_covered(circle(60, False, 33), circle(52, True, 200), 8.0)

    def test_nearly_closed_toe(self):
        toe = circle(70, False, 77)
        toe[-1] = (toe[-1][0], toe[-1][1] + 0.02)  # 2 cm gap
        self._assert_ring_covered(circle(60, True, 0), toe, 10.0)

    def test_small_mound_both_directions(self):
        # Crest radius + toe radius < search distance: the ray along the inward normal
        # would cross the mound and hit the far side of the toe ring.
        for ccw in (True, False):
            result = self._assert_ring_covered(circle(15, ccw, 0), circle(25, not ccw, 40), 10.0)
            self.assertTrue(all(h.length < 11.0 for h in result))

    def test_small_pit_both_directions(self):
        for ccw in (True, False):
            self._assert_ring_covered(circle(25, ccw, 0), circle(15, ccw, 70), 10.0)

    def test_open_arc_around_small_mound(self):
        crest = circle(15, True, 10, count=180, close=False)[:90]
        result = self.engine.compute_hachures(line(crest), line(circle(25, False, 250)))
        self.assertGreater(len(longs(result)), 10)
        self.assertTrue(all(h.length < 11.0 for h in longs(result)))

    def test_multipart_breakline_ends(self):
        kehle = QgsGeometry.fromMultiPolylineXY([
            [QgsPointXY(50.0, 0.0), QgsPointXY(50.0, -4.0)],
            [QgsPointXY(50.0, -4.0), QgsPointXY(50.0 + 1e-13, -10.0)],
        ])
        start, end = geometry_utils.line_ends(kehle)
        self.assertEqual((start.x(), start.y()), (50.0, 0.0))
        self.assertEqual(end.y(), -10.0)
        result = self.engine.compute_hachures(
            line([(0, 0), (100, 0)]), line([(0, -10), (100, -10)]), [kehle])
        self.assertTrue(result)

    def test_open_crest_on_toe_ring(self):
        crest = circle(60, True, 10, count=180, close=False)[:60]
        result = self.engine.compute_hachures(line(crest), line(circle(70, False, 250)))
        self.assertLessEqual(max_gap(result), 4.0 * 1.05)

    def test_monotonicity_on_ring(self):
        point = QgsPointXY(0, 0)
        mode = models.HachureMode.PROJEKTION
        targets = [models.Target(float(i), p, point, mode) for i, p in enumerate([390.0, 396.0, 2.0, 8.0])]
        self.assertEqual(len(slope_engine.enforce_monotonicity(targets, 400.0)), 4)
        self.assertEqual(len(slope_engine.enforce_monotonicity(targets)), 2)  # open line: a step back

    def test_validate_flag_gives_same_result(self):
        rng = random.Random(8)
        crest = random_points(rng, 50, step=4.0)
        toe = [(x, y - 9.0) for x, y in crest]
        a = self.engine.compute_hachures(line(crest), line(toe), validate=True)
        b = self.engine.compute_hachures(line(crest), line(toe), validate=False)
        self.assertEqual([(h.station, h.length, h.mode) for h in a],
                         [(h.station, h.length, h.mode) for h in b])

    def test_progress_and_cancel(self):
        crest = line([(0, 0), (2000, 0)])
        toe = line([(0, -10), (2000, -10)])
        seen = []
        self.engine.compute_hachures(crest, toe, progress=seen.append)
        self.assertTrue(seen)
        self.assertEqual(seen, sorted(seen))
        self.assertAlmostEqual(seen[-1], 1.0)

        feedback = QgsProcessingFeedback()
        feedback.cancel()
        self.assertEqual(self.engine.compute_hachures(crest, toe, feedback=feedback), [])

    def test_disjoint_multipart_crest_is_rejected(self):
        crest = QgsGeometry.fromMultiPolylineXY([
            [QgsPointXY(0, 0), QgsPointXY(10, 0)],
            [QgsPointXY(20, 0), QgsPointXY(30, 0)],
        ])
        feedback = RecordingFeedback()
        self.assertEqual(self.engine.compute_hachures(crest, line([(0, -5), (30, -5)]), feedback=feedback), [])
        self.assertTrue(feedback.warnings)

    def test_rejects_invalid_parameters(self):
        with self.assertRaises(ValueError):
            slope_engine.SlopeEngine(interval=0.1)
        with self.assertRaises(ValueError):
            slope_engine.SlopeEngine(short_ratio=0.99)


if __name__ == "__main__":
    unittest.main()
