# -*- coding: utf-8 -*-
"""
Planar geometry helpers for the slope engine. No UI and no processing imports.

SPDX-License-Identifier: GPL-3.0-or-later
"""

import math
from typing import List, Optional, Sequence, Tuple

from qgis.core import QgsFeature, QgsGeometry, QgsPointXY, QgsSpatialIndex, QgsWkbTypes

from .models import HachureMode, Hit
from .tuning import (
    MAX_SLOPE_DOT,
    MIN_TARGET_DIST,
    NORMAL_DELTA_FACTOR,
    NORMAL_DELTA_MAX,
    NORMAL_DELTA_MIN,
    SLOPE_ANGLE_DELTA,
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


def unit_tangent(geom: QgsGeometry, station: float, delta: float) -> Optional[Vector]:
    """Unit direction of a line around a station, estimated over +/- delta."""
    total = geom.length()
    s1 = max(0.0, station - delta)
    s2 = min(total, station + delta)
    if s2 <= s1:
        return None
    p1 = geom.interpolate(s1).asPoint()
    p2 = geom.interpolate(s2).asPoint()
    dx = p2.x() - p1.x()
    dy = p2.y() - p1.y()
    length = math.hypot(dx, dy)
    if length <= 0.0:
        return None
    return dx / length, dy / length


def unit_normal(geom: QgsGeometry, station: float, interval: float) -> Optional[Vector]:
    """Unit normal (left of the tangent) at a station."""
    delta = clamp(interval * NORMAL_DELTA_FACTOR, NORMAL_DELTA_MIN, NORMAL_DELTA_MAX)
    tangent = unit_tangent(geom, station, delta)
    if tangent is None:
        return None
    tx, ty = tangent
    return -ty, tx


def is_valid_slope_angle(
    ok_geom: QgsGeometry,
    station: float,
    p_start: QgsPointXY,
    p_target: QgsPointXY,
) -> bool:
    """Rejects targets that would lie almost along the crest line."""
    tangent = unit_tangent(ok_geom, station, SLOPE_ANGLE_DELTA)
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
    ray_geom: QgsGeometry,
    uk_geom: QgsGeometry,
    kehlen: Sequence[QgsGeometry],
    max_dist: float,
) -> Optional[Hit]:
    """Closest valid hit of a ray on the toe line or on a breakline."""
    best: Optional[Hit] = None
    best_dist = max_dist

    inter_uk = ray_geom.intersection(uk_geom)
    if not inter_uk.isEmpty():
        for p in extract_points(inter_uk):
            d = measure(origin, p)
            if MIN_TARGET_DIST < d < best_dist:
                best_dist = d
                uk_param = uk_geom.lineLocatePoint(QgsGeometry.fromPointXY(p))
                best = Hit(p, uk_param, HachureMode.PROJEKTION)

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
    uk_geom: QgsGeometry,
    kehlen: Sequence[QgsGeometry],
) -> Optional[Hit]:
    """Casts along the normal, then against it if nothing was hit."""
    hit = find_best_collision(
        origin, ray(origin, normal, max_dist), uk_geom, kehlen, max_dist
    )
    if hit is None:
        back = (-normal[0], -normal[1])
        hit = find_best_collision(
            origin, ray(origin, back, max_dist), uk_geom, kehlen, max_dist
        )
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


def align_toe_line(ok_geom: QgsGeometry, uk_geom: QgsGeometry) -> Optional[QgsGeometry]:
    """Returns the toe line as one LineString, oriented like the crest line.

    Returns None if the toe line is not one continuous line.
    """
    toe = as_single_polyline(uk_geom)
    if toe is None:
        return None
    points = toe.asPolyline()
    ok_start = ok_geom.interpolate(0.0).asPoint()
    ok_end = ok_geom.interpolate(ok_geom.length()).asPoint()
    direct = measure(ok_start, points[0]) + measure(ok_end, points[-1])
    reverse = measure(ok_start, points[-1]) + measure(ok_end, points[0])
    if reverse < direct:
        points = list(reversed(points))
    return QgsGeometry.fromPolylineXY(points)
