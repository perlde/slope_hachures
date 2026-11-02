# -*- coding: utf-8 -*-
"""
Coordinate-level polyline queries for the slope engine.

A Polyline is built once per crest part and once per toe line. It answers the
queries that run for every station (point at a station, local direction, ray
crossings, nearest point) without converting the whole line for each call, as
the QgsGeometry methods do. The cost of a query therefore no longer grows with
the number of vertices.

The formulas follow QGIS/GEOS: interpolation walks the cumulative segment
lengths; crossings are decided with exact orientation predicates and classified
like the GEOS LineIntersector (a touch at a vertex returns the vertex itself, a
collinear overlap returns its end points); ties are resolved towards the start
of the line.

In near-degenerate input (a vertex within about 1e-15 m of a ray, which only
synthetic data such as rays at exactly 45 degrees through an integer grid
produce) the exact predicate decides; GEOS may instead snap the ray onto the
vertex. On all test scenarios, real-world-like and integer grids, the engine
output is identical to version 1.1.2.

No QGIS imports: the module works on plain (x, y) tuples and can be tested
without QGIS. A segment lookup can be attached (the engine attaches a
QgsSpatialIndex); without one, all segments are scanned.

SPDX-License-Identifier: GPL-3.0-or-later
"""

import math
from bisect import bisect_right
from fractions import Fraction
from typing import Callable, Iterable, List, NamedTuple, Optional, Sequence, Set, Tuple

Coord = Tuple[float, float]
Vector = Tuple[float, float]
Box = Tuple[float, float, float, float]  # xmin, ymin, xmax, ymax
SegmentLookup = Callable[[Box], Iterable[int]]

DUPLICATE_TOLERANCE = 1e-9   # hits closer than this (distance and parameter) are one hit
BOX_PADDING = 1e-7           # padding [m] of lookup boxes against rounding
RAY_CHUNKS = 8               # an indexed ray is looked up in this many pieces, nearest first

# Error bound of the floating-point orientation filter (Shewchuk, ccwerrboundA).
_EPSILON = 2.0 ** -53
_ORIENTATION_ERROR_BOUND = (3.0 + 16.0 * _EPSILON) * _EPSILON


def orientation(ax: float, ay: float, bx: float, by: float, cx: float, cy: float) -> int:
    """Exact sign of the turn a -> b -> c: 1 left, -1 right, 0 collinear.

    The floating-point result is used when it is provably correct; otherwise the
    determinant is evaluated exactly with fractions (rare, near-collinear input).
    """
    det_left = (ax - cx) * (by - cy)
    det_right = (ay - cy) * (bx - cx)
    det = det_left - det_right
    bound = _ORIENTATION_ERROR_BOUND * (abs(det_left) + abs(det_right))
    if det > bound:
        return 1
    if det < -bound:
        return -1
    exact = ((Fraction(ax) - Fraction(cx)) * (Fraction(by) - Fraction(cy))
             - (Fraction(ay) - Fraction(cy)) * (Fraction(bx) - Fraction(cx)))
    return (exact > 0) - (exact < 0)


def _in_box(x: float, y: float, x1: float, y1: float, x2: float, y2: float) -> bool:
    return min(x1, x2) <= x <= max(x1, x2) and min(y1, y2) <= y <= max(y1, y2)


class LineHit(NamedTuple):
    """A location on the polyline found by a query."""

    distance: float  # distance from the query origin
    point: Coord
    param: float     # distance along the polyline from its start


def segment_length(p1: Coord, p2: Coord) -> float:
    """Planar segment length, computed like QgsLineString::length()."""
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    return math.sqrt(dx * dx + dy * dy)


def signed_area(points: Sequence[Coord]) -> float:
    """Shoelace area of a ring (positive = counter-clockwise). The ring is closed implicitly."""
    total = 0.0
    count = len(points)
    for index in range(count):
        x1, y1 = points[index]
        x2, y2 = points[(index + 1) % count]
        total += x1 * y2 - x2 * y1
    return total / 2.0


def circular_delta(start: float, end: float, period: float) -> float:
    """Shortest signed step from start to end on a ring of the given length."""
    delta = (end - start) % period
    if delta > period / 2.0:
        delta -= period
    return delta


def orientation_vote(params: Sequence[float], period: Optional[float], cyclic: bool) -> int:
    """Sum of the signs of the steps between consecutive line parameters.

    Positive: the samples run along the line, negative: against it. With a period
    the parameters lie on a ring and steps are taken the short way round.
    """
    count = len(params)
    pairs = count if cyclic else count - 1
    vote = 0
    for index in range(max(0, pairs)):
        start, end = params[index], params[(index + 1) % count]
        step = circular_delta(start, end, period) if period else end - start
        if step > DUPLICATE_TOLERANCE:
            vote += 1
        elif step < -DUPLICATE_TOLERANCE:
            vote -= 1
    return vote


class Polyline:
    """A single line with cumulative lengths and an optional segment lookup."""

    def __init__(self, coords: Sequence[Coord]) -> None:
        points = [(float(x), float(y)) for x, y in coords]
        if len(points) < 2:
            raise ValueError("a polyline needs at least two points")
        cum = [0.0]
        for p1, p2 in zip(points, points[1:]):
            cum.append(cum[-1] + segment_length(p1, p2))
        self.points: List[Coord] = points
        self.cum: List[float] = cum
        self.length: float = cum[-1]
        self._lookup: Optional[SegmentLookup] = None

    # ------------------------------------------------------------ structure
    @property
    def segment_count(self) -> int:
        return len(self.points) - 1

    def segment_boxes(self) -> List[Box]:
        """Bounding box of every segment, padded against rounding."""
        pad = BOX_PADDING
        return [
            (min(x1, x2) - pad, min(y1, y2) - pad, max(x1, x2) + pad, max(y1, y2) + pad)
            for (x1, y1), (x2, y2) in zip(self.points, self.points[1:])
        ]

    def attach_lookup(self, lookup: Optional[SegmentLookup]) -> None:
        """Attaches a lookup that returns the indices of segments whose box meets a query box."""
        self._lookup = lookup

    def closing_gap(self) -> float:
        return segment_length(self.points[0], self.points[-1])

    def ring_period(self, tolerance: float) -> Optional[float]:
        """Circumference if the line is a ring (end within tolerance of the start), else None."""
        if self.segment_count < 3 or self.length <= 0.0:
            return None
        gap = self.closing_gap()
        if gap > tolerance:
            return None
        return self.length + gap

    # ------------------------------------------------------------ stations
    def point_at(self, station: float) -> Coord:
        """Point at a distance along the line. Clamped to the line ends."""
        if station <= 0.0:
            return self.points[0]
        if station >= self.length:
            return self.points[-1]
        index = min(bisect_right(self.cum, station) - 1, self.segment_count - 1)
        seg = self.cum[index + 1] - self.cum[index]
        (x1, y1), (x2, y2) = self.points[index], self.points[index + 1]
        if seg <= 0.0:
            return x1, y1
        scale = (station - self.cum[index]) / seg
        return x1 + (x2 - x1) * scale, y1 + (y2 - y1) * scale

    def tangent(self, station: float, delta: float) -> Optional[Vector]:
        """Unit direction around a station, estimated over +/- delta."""
        s1 = max(0.0, station - delta)
        s2 = min(self.length, station + delta)
        if s2 <= s1:
            return None
        x1, y1 = self.point_at(s1)
        x2, y2 = self.point_at(s2)
        dx = x2 - x1
        dy = y2 - y1
        norm = math.hypot(dx, dy)
        if norm <= 0.0:
            return None
        return dx / norm, dy / norm

    # ------------------------------------------------------------ queries
    def _candidates(self, box: Box) -> Iterable[int]:
        if self._lookup is None:
            return range(self.segment_count)
        return sorted(self._lookup(box))

    def _segment_hits(self, index: int, origin: Coord, end: Coord, out: List[LineHit]) -> None:
        """Appends the intersections of segment `index` with the ray segment origin-end.

        Classification as in the GEOS LineIntersector: exact orientation tests decide
        whether the segments meet; a touch returns the touching end point itself, a
        collinear overlap returns the end points that lie inside the other segment,
        and only a proper crossing computes a new point.
        """
        ox, oy = origin
        tx, ty = end
        (ax, ay), (bx, by) = self.points[index], self.points[index + 1]
        if (max(ax, bx) < min(ox, tx) or min(ax, bx) > max(ox, tx)
                or max(ay, by) < min(oy, ty) or min(ay, by) > max(oy, ty)):
            return
        side_a = orientation(ox, oy, tx, ty, ax, ay)
        side_b = orientation(ox, oy, tx, ty, bx, by)
        if side_a == side_b != 0:
            return
        side_o = orientation(ax, ay, bx, by, ox, oy)
        side_t = orientation(ax, ay, bx, by, tx, ty)
        if side_o == side_t != 0:
            return

        if side_a == 0 and side_b == 0 and side_o == 0 and side_t == 0:
            # Collinear overlap: the end points of either segment inside the other one.
            for px, py in ((ax, ay), (bx, by)):
                if _in_box(px, py, ox, oy, tx, ty):
                    self._append_hit(index, (px, py), origin, out)
            for px, py in ((ox, oy), (tx, ty)):
                if _in_box(px, py, ax, ay, bx, by):
                    self._append_hit(index, (px, py), origin, out)
            return

        if side_a == 0 or side_b == 0 or side_o == 0 or side_t == 0:
            # Touch at an end point: take that end point unchanged.
            if (ox, oy) in ((ax, ay), (bx, by)):
                point = (ox, oy)
            elif (tx, ty) in ((ax, ay), (bx, by)):
                point = (tx, ty)
            elif side_a == 0:
                point = (ax, ay)
            elif side_b == 0:
                point = (bx, by)
            elif side_o == 0:
                point = (ox, oy)
            else:
                point = (tx, ty)
            self._append_hit(index, point, origin, out)
            return

        # Proper crossing.
        rx = tx - ox
        ry = ty - oy
        sx = bx - ax
        sy = by - ay
        denom = rx * sy - ry * sx
        u = ((ox - ax) * ry - (oy - ay) * rx) / -denom
        u = min(1.0, max(0.0, u))
        self._append_hit(index, (ax + sx * u, ay + sy * u), origin, out)

    def _append_hit(self, index: int, point: Coord, origin: Coord, out: List[LineHit]) -> None:
        """Records a hit; its parameter is located like lineLocatePoint() on this segment."""
        (ax, ay), (bx, by) = self.points[index], self.points[index + 1]
        seg_len = self.cum[index + 1] - self.cum[index]
        if seg_len <= 0.0:
            param = self.cum[index]
        else:
            ex = bx - ax
            ey = by - ay
            factor = ((point[0] - ax) * ex + (point[1] - ay) * ey) / (ex * ex + ey * ey)
            param = self.cum[index] + seg_len * min(1.0, max(0.0, factor))
        distance = math.hypot(point[0] - origin[0], point[1] - origin[1])
        out.append(LineHit(distance, point, param))

    def ray_hits(self, origin: Coord, direction: Vector, length: float) -> List[LineHit]:
        """All intersections with the ray (origin, unit direction, length), nearest first.

        The ray end point is computed as origin + direction * length, like the ray
        geometry of the engine. A crossing at a shared vertex is reported once.
        """
        end = _ray_point(origin, direction, length)
        hits: List[LineHit] = []
        for index in self._candidates(_ray_box(origin, direction, 0.0, length)):
            self._segment_hits(index, origin, end, hits)
        return _unique(hits)

    def first_hit(
        self,
        origin: Coord,
        direction: Vector,
        length: float,
        min_distance: float,
    ) -> Optional[LineHit]:
        """Nearest crossing with min_distance < distance < length, or None.

        With a lookup the ray is queried piece by piece from the origin outwards and
        the search stops at the first piece that contains a valid crossing.
        """
        if self._lookup is None:
            return _nearest_valid(self.ray_hits(origin, direction, length), min_distance, length)

        end = _ray_point(origin, direction, length)
        hits: List[LineHit] = []
        seen: Set[int] = set()
        step = length / RAY_CHUNKS
        for chunk in range(RAY_CHUNKS):
            t_end = length if chunk == RAY_CHUNKS - 1 else (chunk + 1) * step
            box = _ray_box(origin, direction, chunk * step, t_end)
            for index in self._candidates(box):
                if index not in seen:
                    seen.add(index)
                    self._segment_hits(index, origin, end, hits)
            best = _nearest_valid(hits, min_distance, length)
            if best is not None and best.distance <= t_end:
                return best
        return _nearest_valid(hits, min_distance, length)

    def nearest(self, point: Coord, max_distance: float) -> Optional[LineHit]:
        """Closest location on the line, if it lies within max_distance.

        The first closest segment wins, like GEOS nearestPoint().
        """
        px, py = point
        pad = max_distance + BOX_PADDING
        best: Optional[LineHit] = None
        for index in self._candidates((px - pad, py - pad, px + pad, py + pad)):
            seg_len = self.cum[index + 1] - self.cum[index]
            (ax, ay), (bx, by) = self.points[index], self.points[index + 1]
            if seg_len <= 0.0:
                u = 0.0
            else:
                ex = bx - ax
                ey = by - ay
                u = ((px - ax) * ex + (py - ay) * ey) / (ex * ex + ey * ey)
                u = min(1.0, max(0.0, u))
            if u <= 0.0:
                cx, cy = ax, ay
            elif u >= 1.0:
                cx, cy = bx, by
            else:
                cx, cy = ax + (bx - ax) * u, ay + (by - ay) * u
            dist = math.hypot(cx - px, cy - py)
            if best is None or dist < best.distance:
                best = LineHit(dist, (cx, cy), self.cum[index] + seg_len * u)
        if best is None or best.distance > max_distance:
            return None
        return best


# ------------------------------------------------------------------ helpers
def _ray_point(origin: Coord, direction: Vector, distance: float) -> Coord:
    return origin[0] + direction[0] * distance, origin[1] + direction[1] * distance


def _ray_box(origin: Coord, direction: Vector, t_start: float, t_end: float) -> Box:
    x1, y1 = _ray_point(origin, direction, t_start)
    x2, y2 = _ray_point(origin, direction, t_end)
    pad = BOX_PADDING
    return min(x1, x2) - pad, min(y1, y2) - pad, max(x1, x2) + pad, max(y1, y2) + pad


def _unique(hits: List[LineHit]) -> List[LineHit]:
    hits.sort(key=lambda hit: (hit.distance, hit.param))
    result: List[LineHit] = []
    for hit in hits:
        if result and abs(hit.distance - result[-1].distance) <= DUPLICATE_TOLERANCE \
                and abs(hit.param - result[-1].param) <= DUPLICATE_TOLERANCE:
            continue
        result.append(hit)
    return result


def _nearest_valid(hits: List[LineHit], min_distance: float, length: float) -> Optional[LineHit]:
    best: Optional[LineHit] = None
    for hit in hits:
        if min_distance < hit.distance < length:
            if best is None or (hit.distance, hit.param) < (best.distance, best.param):
                best = hit
    return best
