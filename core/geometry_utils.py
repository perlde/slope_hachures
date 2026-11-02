# -*- coding: utf-8 -*-
"""
Planar geometry helpers for the slope engine. No UI and no processing imports.

Queries that run for every crest station work on core.polyline.Polyline objects.
QgsGeometry is used for the breaklines and for operations that run a few times
per crest part.

SPDX-License-Identifier: GPL-3.0-or-later
"""

import math
from typing import List, Optional, Sequence, Tuple

from qgis.core import QgsFeature, QgsGeometry, QgsPointXY, QgsRectangle, QgsSpatialIndex, QgsWkbTypes

from .models import HachureMode, Hit
from .polyline import Polyline, orientation_vote, signed_area
from .tuning import (
    MAX_SLOPE_DOT,
    MIN_TARGET_DIST,
    NORMAL_DELTA_FACTOR,
    NORMAL_DELTA_MAX,
    NORMAL_DELTA_MIN,
    ORIENTATION_SAMPLES,
    RING_CLOSE_TOLERANCE,
    SLOPE_ANGLE_DELTA,
    SPATIAL_INDEX_MIN_SEGMENTS,
)

Vector = Tuple[float, float]


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def measure(p1: QgsPointXY, p2: QgsPointXY) -> float:
    """Planar distance in map units. Intentionally not ellipsoidal, so that
    attribute lengths match the geometry that is actually drawn."""
    return math.hypot(p2.x() - p1.x(), p2.y() - p1.y())


def segment(p1: QgsPointXY, p2: QgsPointXY) -> QgsGeometry:
    return QgsGeometry.fromPolylineXY([p1, p2])


def ray(origin: QgsPointXY, direction: Vector, length: float) -> QgsGeometry:
    return segment(
        origin,
        QgsPointXY(origin.x() + direction[0] * length,
                   origin.y() + direction[1] * length),
    )


# ------------------------------------------------------------------ polylines
def to_polyline(geom: QgsGeometry, indexed: bool = False) -> Polyline:
    """Builds a Polyline from a single LineString geometry.

    With indexed=True a QgsSpatialIndex of the segments is attached, so ray and
    nearest-point queries only test the segments near the query.
    """
    line = Polyline([(p.x(), p.y()) for p in geom.asPolyline()])
    if indexed and line.segment_count >= SPATIAL_INDEX_MIN_SEGMENTS:
        line.attach_lookup(_segment_lookup(line))
    return line


def _segment_lookup(line: Polyline):
    """Returns a lookup backed by a QgsSpatialIndex, or None if the index cannot be built."""
    index = QgsSpatialIndex()
    for number, (xmin, ymin, xmax, ymax) in enumerate(line.segment_boxes()):
        if not index.addFeature(number, QgsRectangle(xmin, ymin, xmax, ymax)):
            return None  # fall back to scanning all segments

    def lookup(box: Tuple[float, float, float, float]) -> List[int]:
        return index.intersects(QgsRectangle(*box))

    return lookup


def unit_tangent(line: Polyline, station: float, delta: float) -> Optional[Vector]:
    """Unit direction of a line around a station, estimated over +/- delta."""
    return line.tangent(station, delta)


def unit_normal(line: Polyline, station: float, interval: float) -> Optional[Vector]:
    """Unit normal (left of the tangent) at a station."""
    delta = clamp(interval * NORMAL_DELTA_FACTOR, NORMAL_DELTA_MIN, NORMAL_DELTA_MAX)
    tangent = line.tangent(station, delta)
    if tangent is None:
        return None
    tx, ty = tangent
    return -ty, tx


def is_valid_slope_angle(
    crest: Polyline,
    station: float,
    p_start: QgsPointXY,
    p_target: QgsPointXY,
) -> bool:
    """Rejects targets that would lie almost along the crest line."""
    tangent = crest.tangent(station, SLOPE_ANGLE_DELTA)
    if tangent is None:
        return True
    vx = p_target.x() - p_start.x()
    vy = p_target.y() - p_start.y()
    v_len = math.hypot(vx, vy)
    if v_len == 0.0:
        return False
    dot = tangent[0] * vx / v_len + tangent[1] * vy / v_len
    return abs(dot) <= MAX_SLOPE_DOT


def is_near_any(
    point: QgsPointXY,
    geoms: Sequence[QgsGeometry],
    threshold: float,
) -> bool:
    if not geoms:
        return False
    pt = QgsGeometry.fromPointXY(point)
    return any(pt.distance(g) < threshold for g in geoms)


def extract_points(geom: Optional[QgsGeometry]) -> List[QgsPointXY]:
    """All vertices of a (possibly collection-typed) geometry."""
    points: List[QgsPointXY] = []
    if geom is None or geom.isEmpty():
        return points
    flat = QgsWkbTypes.flatType(geom.wkbType())
    if flat == QgsWkbTypes.Type.Point:
        points.append(geom.asPoint())
    elif flat == QgsWkbTypes.Type.MultiPoint:
        points.extend(geom.asMultiPoint())
    elif flat == QgsWkbTypes.Type.LineString:
        if geom.length() > 0:
            points.extend(geom.asPolyline())
    elif flat == QgsWkbTypes.Type.MultiLineString:
        for line in geom.asMultiPolyline():
            points.extend(line)
    elif flat == QgsWkbTypes.Type.GeometryCollection:
        for part in geom.asGeometryCollection():
            points.extend(extract_points(part))
    return points


def project_onto(line: QgsGeometry, point: QgsPointXY) -> Tuple[QgsPointXY, float]:
    """Nearest point on a line and its distance along the line."""
    near = line.nearestPoint(QgsGeometry.fromPointXY(point)).asPoint()
    param = line.lineLocatePoint(QgsGeometry.fromPointXY(near))
    return near, param


def _part_self_intersects(points: Sequence[QgsPointXY]) -> bool:
    segment_count = len(points) - 1
    if segment_count < 2:
        return False
    closed = points[0].x() == points[-1].x() and points[0].y() == points[-1].y()
    segments = [
        QgsGeometry.fromPolylineXY([points[i], points[i + 1]])
        for i in range(segment_count)
    ]
    index = QgsSpatialIndex()
    for i, seg in enumerate(segments):
        feature = QgsFeature(i)
        feature.setGeometry(seg)
        index.addFeature(feature)
    for i, seg in enumerate(segments):
        for j in index.intersects(seg.boundingBox()):
            if j <= i + 1:
                continue  # same segment or direct neighbour (shares a vertex)
            if closed and i == 0 and j == segment_count - 1:
                continue  # first and last segment of a closed ring
            if seg.intersects(segments[j]):
                return True
    return False


def has_self_intersection(geom: Optional[QgsGeometry]) -> bool:
    """True if a line crosses itself. GEOS accepts such lines as valid,
    so isGeosValid() cannot detect them."""
    if geom is None or geom.isEmpty():
        return False
    parts = geom.asMultiPolyline() if geom.isMultipart() else [geom.asPolyline()]
    return any(_part_self_intersects(part) for part in parts)


def find_best_collision(
    origin: QgsPointXY,
    direction: Vector,
    max_dist: float,
    toe: Polyline,
    kehlen: Sequence[QgsGeometry],
) -> Optional[Hit]:
    """Closest valid hit of a ray on the toe line or on a breakline.

    A breakline hit wins only if it is strictly closer than the toe hit.
    """
    best: Optional[Hit] = None
    best_dist = max_dist

    toe_hit = toe.first_hit((origin.x(), origin.y()), direction, max_dist, MIN_TARGET_DIST)
    if toe_hit is not None:
        best_dist = toe_hit.distance
        best = Hit(QgsPointXY(*toe_hit.point), toe_hit.param, HachureMode.PROJEKTION)

    if kehlen:
        ray_geom = ray(origin, direction, max_dist)
        for kehle in kehlen:
            inter_k = ray_geom.intersection(kehle)
            if inter_k.isEmpty():
                continue
            for p in extract_points(inter_k):
                d = measure(origin, p)
                if MIN_TARGET_DIST < d < best_dist:
                    best_dist = d
                    best = Hit(p, None, HachureMode.KEHLE)

    return best


def cast_both_ways(
    origin: QgsPointXY,
    normal: Vector,
    max_dist: float,
    toe: Polyline,
    kehlen: Sequence[QgsGeometry],
) -> Optional[Hit]:
    """Casts along the normal, then against it if nothing was hit."""
    hit = find_best_collision(origin, normal, max_dist, toe, kehlen)
    if hit is None:
        back = (-normal[0], -normal[1])
        hit = find_best_collision(origin, back, max_dist, toe, kehlen)
    return hit


def nearest_crossing(
    origin: QgsPointXY,
    segment_geom: QgsGeometry,
    kehlen: Sequence[QgsGeometry],
    limit: float,
    margin: float = 0.0,
) -> Optional[QgsPointXY]:
    """Breakline crossing of a segment that lies closer to the origin than the
    limit. Crossings are accepted in sequence; each new one must be closer than
    the previous one by at least `margin`. The result is a point or None."""
    best = limit
    found: Optional[QgsPointXY] = None
    for kehle in kehlen:
        inter = segment_geom.intersection(kehle)
        if inter.isEmpty():
            continue
        for kp in extract_points(inter):
            kd = measure(origin, kp)
            if MIN_TARGET_DIST < kd < (limit - MIN_TARGET_DIST) and kd < best - margin:
                best = kd
                found = kp
    return found


def as_single_polyline(geom: Optional[QgsGeometry]) -> Optional[QgsGeometry]:
    """Returns the geometry as one continuous LineString, or None.

    Gaps are never bridged: a multipart result after mergeLines() returns None.
    """
    if geom is None or geom.isEmpty():
        return None
    work = geom.mergeLines() if geom.isMultipart() else geom
    if work.isEmpty():
        return None
    if work.isMultipart():
        parts = work.asMultiPolyline()
        if len(parts) != 1:
            return None
        points = parts[0]
    else:
        points = work.asPolyline()
    if len(points) < 2:
        return None
    return QgsGeometry.fromPolylineXY(points)


def line_ends(geom: QgsGeometry) -> Tuple[QgsPointXY, QgsPointXY]:
    """First and last vertex of a (multi)line, read directly from the vertices.

    interpolate(length()) can return a null geometry when rounding puts the
    distance just past the end, notably for multipart lines in QGIS 3.22.
    """
    if geom.isMultipart():
        parts = [part for part in geom.asMultiPolyline() if part]
        return QgsPointXY(parts[0][0]), QgsPointXY(parts[-1][-1])
    points = geom.asPolyline()
    return QgsPointXY(points[0]), QgsPointXY(points[-1])


def toe_side(crest: Polyline, toe_geom: QgsGeometry) -> float:
    """+1 if the toe lies left of the crest (in its direction), -1 if right.

    Decided by a majority of crest samples, each compared with its nearest toe point.
    """
    count = ORIENTATION_SAMPLES
    vote = 0
    for k in range(count):
        station = crest.length * (k + 0.5) / count
        tangent = crest.tangent(station, NORMAL_DELTA_MAX)
        if tangent is None:
            continue
        px, py = crest.point_at(station)
        near = toe_geom.nearestPoint(QgsGeometry.fromPointXY(QgsPointXY(px, py)))
        if near.isEmpty():
            continue
        q = near.asPoint()
        cross = tangent[0] * (q.y() - py) - tangent[1] * (q.x() - px)
        vote += (cross > 0.0) - (cross < 0.0)
    return -1.0 if vote < 0 else 1.0


def _is_ring(points: Sequence[QgsPointXY]) -> bool:
    return len(points) >= 4 and measure(points[0], points[-1]) <= RING_CLOSE_TOLERANCE


def _toe_runs_against_crest(
    crest_points: Sequence[QgsPointXY],
    toe_geom: QgsGeometry,
    crest_is_ring: bool,
    toe_is_ring: bool,
) -> bool:
    """Decides the toe direction by projecting crest samples onto the toe line.

    Used when exactly one of the two lines is a ring: the start/end comparison
    then gives no answer, because the ring's start and end coincide.
    """
    crest = Polyline([(p.x(), p.y()) for p in crest_points])
    toe_len = toe_geom.length()
    if crest.length <= 0.0 or toe_len <= 0.0:
        return False
    count = ORIENTATION_SAMPLES
    divisor = count if crest_is_ring else count - 1
    # Polyline.point_at clamps to the line; QgsGeometry.interpolate() returns a null
    # geometry in QGIS 3.22 if the distance exceeds the length by rounding.
    params = [
        toe_geom.lineLocatePoint(QgsGeometry.fromPointXY(
            QgsPointXY(*crest.point_at(crest.length * k / divisor))))
        for k in range(count)
    ]
    period = None
    if toe_is_ring:
        points = toe_geom.asPolyline()
        period = toe_len + measure(points[0], points[-1])
    return orientation_vote(params, period, cyclic=crest_is_ring) < 0


def align_toe_line(ok_geom: QgsGeometry, uk_geom: QgsGeometry) -> Optional[QgsGeometry]:
    """Returns the toe line as one LineString, oriented like the crest line.

    Returns None if the toe line is not one continuous line. Two open lines are
    compared by their end points; if crest or toe is a ring, the direction is
    taken from the ring winding (two rings) or from projected crest samples.
    """
    toe = as_single_polyline(uk_geom)
    if toe is None:
        return None
    points = toe.asPolyline()
    crest = as_single_polyline(ok_geom)
    crest_points = crest.asPolyline() if crest is not None else []
    crest_is_ring = _is_ring(crest_points)
    toe_is_ring = _is_ring(points)

    if crest_is_ring and toe_is_ring:
        crest_area = signed_area([(p.x(), p.y()) for p in crest_points])
        toe_area = signed_area([(p.x(), p.y()) for p in points])
        reverse = crest_area * toe_area < 0.0
    elif crest_is_ring or toe_is_ring:
        reverse = _toe_runs_against_crest(crest_points, toe, crest_is_ring, toe_is_ring)
    else:
        ok_start = ok_geom.interpolate(0.0).asPoint()
        ok_end = ok_geom.interpolate(ok_geom.length()).asPoint()
        direct = measure(ok_start, points[0]) + measure(ok_end, points[-1])
        reverse_sum = measure(ok_start, points[-1]) + measure(ok_end, points[0])
        reverse = reverse_sum < direct

    if reverse:
        points = list(reversed(points))
    return QgsGeometry.fromPolylineXY(points)
