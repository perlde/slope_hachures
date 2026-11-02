# -*- coding: utf-8 -*-
"""
Core geometry engine for engineering slope hachures.

Computes primary targets between crest (Kamm) and toe (Fuß) and hands them to
the emitter. It has no UI and no processing dependencies.

SPDX-License-Identifier: GPL-3.0-or-later
"""

import math
from typing import Callable, List, Optional, Sequence

from qgis.core import QgsGeometry, QgsPointXY, QgsProcessingFeedback

from .emission import HachureEmitter
from .geometry_utils import (
    align_toe_line,
    as_single_polyline,
    cast_both_ways,
    clamp,
    extract_points,
    has_self_intersection,
    is_near_any,
    is_valid_slope_angle,
    line_ends,
    measure,
    nearest_crossing,
    project_onto,
    segment,
    to_polyline,
    toe_side,
    unit_normal,
)
from .models import HachureData, HachureMode, Hit, Target
from .polyline import Polyline, circular_delta
from .tuning import (
    CANCEL_CHECK_INTERVAL,
    ENDPOINT_PREFERENCE,
    KEHLE_ANCHOR_DIST,
    KEHLE_NEAR_FACTOR,
    KEHLE_SNAP_DIST,
    KEHLE_TOE_MAX_DIST,
    MAX_SHORT_RATIO,
    MIN_INTERVAL,
    MIN_SEARCH_DIST,
    MIN_SECTION_LENGTH,
    MIN_SHORT_RATIO,
    MIN_STATION,
    MIN_TARGET_DIST,
    NORMAL_DELTA_FACTOR,
    NORMAL_DELTA_MAX,
    NORMAL_DELTA_MIN,
    RING_CLOSE_TOLERANCE,
    STATION_DEDUP_DIST,
)

ProgressCallback = Callable[[float], None]

# Share of the progress of one crest part spent on the target search; the rest is emission.
_TARGET_PHASE = 0.5


class SlopeEngine:
    """Computes slope hachures between crest (OK) and toe (UK)."""

    def __init__(
        self,
        interval: float = 4.0,
        short_ratio: float = 0.5,
        max_search_dist: float = 50.0,
    ) -> None:
        # Invalid values are rejected here. They are not silently corrected.
        if interval < MIN_INTERVAL:
            raise ValueError(f"interval must be >= {MIN_INTERVAL} m")
        if not MIN_SHORT_RATIO <= short_ratio <= MAX_SHORT_RATIO:
            raise ValueError(
                f"short_ratio must be between {MIN_SHORT_RATIO} and {MAX_SHORT_RATIO}"
            )
        if max_search_dist < MIN_SEARCH_DIST:
            raise ValueError(f"max_search_dist must be >= {MIN_SEARCH_DIST} m")
        self.interval = float(interval)
        self.short_ratio = float(short_ratio)
        self.max_search_dist = float(max_search_dist)

    # ----------------------------------------------------------- public API
    def compute_hachures(
        self,
        ok_geom: QgsGeometry,
        uk_geom: QgsGeometry,
        kehlen_geoms: Optional[Sequence[QgsGeometry]] = None,
        feedback: Optional[QgsProcessingFeedback] = None,
        validate: bool = True,
        progress: Optional[ProgressCallback] = None,
    ) -> List[HachureData]:
        """Computes the hachures of one crest line against one toe line.

        validate=False skips the validity and self-crossing checks. The Processing
        algorithm checks every input feature once, before it calls the engine.
        progress, if given, receives the completed fraction (0..1) of this call.
        """
        log = feedback if feedback is not None else QgsProcessingFeedback()

        if validate:
            error = self._validate_input(ok_geom, uk_geom)
        else:
            error = self._check_present(ok_geom, uk_geom)
        if error is not None:
            log.pushWarning(f"SlopeEngine: {error}, skipped.")
            return []

        kehlen = [k for k in (kehlen_geoms or []) if k is not None and not k.isEmpty()]
        crest_geom = as_single_polyline(ok_geom)
        if crest_geom is None:
            log.pushWarning("SlopeEngine: crest line is not one continuous line, skipped.")
            return []
        ok_len = crest_geom.length()
        if ok_len <= 0.0:
            log.pushWarning("SlopeEngine: degenerate crest geometry, skipped.")
            return []

        toe_geom = align_toe_line(crest_geom, uk_geom)
        if toe_geom is None or toe_geom.length() <= 0.0:
            log.pushWarning("SlopeEngine: toe line is not one continuous line, skipped.")
            return []

        crest = to_polyline(crest_geom)
        toe = to_polyline(toe_geom, indexed=True)
        ring_period = toe.ring_period(RING_CLOSE_TOLERANCE)
        crest_is_ring = crest.ring_period(RING_CLOSE_TOLERANCE) is not None
        # Open lines keep the 1.1.2 behaviour (left normal first). With a ring the
        # first ray must point to the toe, otherwise it can cross a small mound or
        # pit and hit the far side of the toe ring.
        side = toe_side(crest, toe_geom) if (crest_is_ring or ring_period is not None) else 1.0

        primary = self._primary_targets(
            crest_geom, crest, toe_geom, toe, kehlen, ok_len,
            crest_is_ring, ring_period is not None, side, log, progress,
        )
        if log.isCanceled():
            return []
        if len(primary) < 2:
            log.pushInfo(f"SlopeEngine: only {len(primary)} target(s), skipped.")
            return []

        targets = enforce_monotonicity(primary, ring_period)
        emitter = HachureEmitter(
            crest, toe, kehlen,
            self.interval, self.short_ratio, self.max_search_dist, side,
        )
        emit_progress = _scaled(progress, _TARGET_PHASE, 1.0) if progress is not None else None
        return emitter.emit(targets, log, emit_progress)

    # ------------------------------------------------------------ validation
    @staticmethod
    def _check_present(ok_geom: Optional[QgsGeometry], uk_geom: Optional[QgsGeometry]) -> Optional[str]:
        for name, geom in (("crest", ok_geom), ("toe", uk_geom)):
            if geom is None or geom.isEmpty():
                return f"{name} geometry is null or empty"
        return None

    @staticmethod
    def _validate_input(ok_geom: Optional[QgsGeometry], uk_geom: Optional[QgsGeometry]) -> Optional[str]:
        for name, geom in (("crest", ok_geom), ("toe", uk_geom)):
            if geom is None or geom.isEmpty():
                return f"{name} geometry is null or empty"
            if not geom.isGeosValid():
                return f"{name} geometry is invalid"
            if has_self_intersection(geom):
                return f"{name} geometry crosses itself"
        return None

    # --------------------------------------------------------- target search
    def _primary_targets(
        self,
        ok: QgsGeometry,
        crest: Polyline,
        uk: QgsGeometry,
        toe: Polyline,
        kehlen: List[QgsGeometry],
        ok_len: float,
        crest_is_ring: bool,
        toe_is_ring: bool,
        side: float,
        log: QgsProcessingFeedback,
        progress: Optional[ProgressCallback],
    ) -> List[Target]:
        targets: List[Target] = []
        bounds = [0.0] + find_kehlen_stations(ok, kehlen, ok_len) + [ok_len]
        last_section = len(bounds) - 2
        counter = 0
        ring_start: Optional[Target] = None

        for idx in range(len(bounds) - 1):
            s_start, s_end = bounds[idx], bounds[idx + 1]
            sec_len = s_end - s_start
            if sec_len < MIN_SECTION_LENGTH:
                continue

            if idx == 0:
                start = None
                if crest_is_ring:
                    start = self._ring_start_target(crest, toe, kehlen, ok_len, side)
                if start is None:
                    start = self._boundary_target(crest, uk, toe, kehlen, True, ok_len, toe_is_ring)
                if start is not None:
                    targets.append(start)
                    if crest_is_ring:
                        ring_start = start

            segments = max(1, round(sec_len / self.interval))
            step_len = sec_len / segments
            for step in range(1, segments):
                counter += 1
                if counter % CANCEL_CHECK_INTERVAL == 0:
                    if log.isCanceled():
                        return targets
                    if progress is not None:
                        progress(_TARGET_PHASE * (s_start + step * step_len) / ok_len)
                station = s_start + step * step_len
                p_ok = QgsPointXY(*crest.point_at(station))
                if is_near_any(p_ok, kehlen, KEHLE_NEAR_FACTOR * self.interval):
                    continue
                internal = self._internal_target(crest, toe, kehlen, station, p_ok, side)
                if internal is not None:
                    targets.append(internal)

            if idx == last_section:
                if ring_start is not None:
                    # The crest ring closes on its start: same hachure, drawn once.
                    end = Target(ok_len, ring_start.uk_param, ring_start.point, ring_start.mode,
                                 draw_long=False)
                else:
                    end = self._boundary_target(crest, uk, toe, kehlen, False, ok_len, toe_is_ring)
                if end is not None:
                    targets.append(end)
            else:
                p_section_end = QgsPointXY(*crest.point_at(s_end))
                anchor = find_kehle_toe_point(p_section_end, kehlen, uk)
                targets.append(Target(s_end, None, anchor, HachureMode.KEHLE_ANKER))

        if progress is not None:
            progress(_TARGET_PHASE)
        return targets

    def _ring_start_target(
        self,
        crest: Polyline,
        toe: Polyline,
        kehlen: List[QgsGeometry],
        ok_len: float,
        side: float,
    ) -> Optional[Target]:
        """Target at the start of a crest ring.

        A ring has no flanks: its start is an ordinary station, so it is cast along
        the normal like its neighbours. The direction is taken across the ring
        closure. Returns None if the start lies near a breakline or nothing is hit;
        the caller then uses the boundary logic.
        """
        p_ok = QgsPointXY(*crest.point_at(0.0))
        if is_near_any(p_ok, kehlen, KEHLE_NEAR_FACTOR * self.interval):
            return None
        delta = min(ok_len / 4.0, clamp(self.interval * NORMAL_DELTA_FACTOR,
                                        NORMAL_DELTA_MIN, NORMAL_DELTA_MAX))
        before = crest.point_at(ok_len - delta)
        after = crest.point_at(delta)
        tx = after[0] - before[0]
        ty = after[1] - before[1]
        norm = math.hypot(tx, ty)
        hit: Optional[Hit] = None
        if norm > 0.0:
            normal = (-ty / norm * side, tx / norm * side)
            hit = cast_both_ways(p_ok, normal, self.max_search_dist, toe, kehlen)
        if hit is None:
            hit = self._fallback_nearest(crest, toe, kehlen, 0.0, p_ok)
        if hit is None:
            return None
        return Target(0.0, hit.uk_param, hit.point, hit.mode)

    def _boundary_target(
        self,
        crest: Polyline,
        uk: QgsGeometry,
        toe: Polyline,
        kehlen: List[QgsGeometry],
        at_start: bool,
        ok_len: float,
        toe_is_ring: bool,
    ) -> Optional[Target]:
        """Target at the crest start or end.

        The toe-side point is the projection of the crest end onto the toe line,
        not the end of the toe line. Otherwise a toe line that reaches beyond the
        crest pulls the hachure away from the crest. A ring has no ends, so the
        projection is always used there.
        """
        station = 0.0 if at_start else ok_len
        p_ok = QgsPointXY(*crest.point_at(station))
        p_uk, uk_param = project_onto(uk, p_ok)

        if not toe_is_ring:
            # Prefer the toe END if it is not much farther away than the perpendicular foot.
            # Otherwise the toe beyond the last hachure stays unhatched.
            uk_start = QgsPointXY(*toe.points[0])
            uk_end = QgsPointXY(*toe.points[-1])
            end_point, end_param = (uk_start, 0.0) if at_start else (uk_end, uk.length())
            d_proj = measure(p_ok, p_uk)
            d_end = measure(p_ok, end_point)
            if d_end <= self.max_search_dist and d_end <= ENDPOINT_PREFERENCE * d_proj:
                p_uk, uk_param = end_point, end_param

        if is_near_any(p_ok, kehlen, KEHLE_ANCHOR_DIST):
            return Target(station, None, p_uk, HachureMode.KEHLE_ANKER)

        direct = measure(p_ok, p_uk)
        if direct > self.max_search_dist:
            return None

        crossing = nearest_crossing(
            p_ok, segment(p_ok, p_uk), kehlen, limit=direct, margin=MIN_TARGET_DIST,
        )
        if crossing is not None:
            return Target(station, None, crossing, HachureMode.KEHLE)

        mode = HachureMode.ANFANGSFLANKE if at_start else HachureMode.ENDFLANKE
        return Target(station, uk_param, p_uk, mode)

    def _internal_target(
        self,
        crest: Polyline,
        toe: Polyline,
        kehlen: List[QgsGeometry],
        station: float,
        p_ok: QgsPointXY,
        side: float = 1.0,
    ) -> Optional[Target]:
        hit: Optional[Hit] = None
        normal = unit_normal(crest, station, self.interval)
        if normal is not None:
            normal = (normal[0] * side, normal[1] * side)
            hit = cast_both_ways(p_ok, normal, self.max_search_dist, toe, kehlen)
        if hit is None:
            hit = self._fallback_nearest(crest, toe, kehlen, station, p_ok)
        if hit is None:
            return None
        return Target(station, hit.uk_param, hit.point, hit.mode)

    def _fallback_nearest(
        self,
        crest: Polyline,
        toe: Polyline,
        kehlen: List[QgsGeometry],
        station: float,
        p_ok: QgsPointXY,
    ) -> Optional[Hit]:
        near = toe.nearest((p_ok.x(), p_ok.y()), self.max_search_dist)
        if near is None:
            return None

        cand_t = near.param
        cand_pt = QgsPointXY(*near.point)
        if not is_valid_slope_angle(crest, station, p_ok, cand_pt):
            return None

        if kehlen:
            crossing = nearest_crossing(
                p_ok, segment(p_ok, cand_pt), kehlen, limit=measure(p_ok, cand_pt), margin=0.0,
            )
            if crossing is not None:
                return Hit(crossing, None, HachureMode.KEHLE)
        return Hit(cand_pt, cand_t, HachureMode.PROJEKTION)


# ------------------------------------------------------------------ helpers
def _scaled(progress: ProgressCallback, start: float, end: float) -> ProgressCallback:
    """Maps a 0..1 progress into the range start..end of another callback."""
    def report(fraction: float) -> None:
        progress(start + (end - start) * fraction)
    return report


def find_kehlen_stations(
    ok: QgsGeometry,
    kehlen: Sequence[QgsGeometry],
    ok_len: float,
) -> List[float]:
    """Crest stations where breaklines meet the crest. Close stations are merged."""
    if not kehlen:
        return []
    stations: List[float] = []
    for kehle in kehlen:
        inter = ok.intersection(kehle)
        if not inter.isEmpty():
            for p in extract_points(inter):
                s = ok.lineLocatePoint(QgsGeometry.fromPointXY(p))
                if MIN_STATION < s < (ok_len - MIN_STATION):
                    stations.append(s)

        for kp in line_ends(kehle):
            kp_geom = QgsGeometry.fromPointXY(kp)
            if ok.distance(kp_geom) < KEHLE_SNAP_DIST:
                near = ok.nearestPoint(kp_geom)
                s = ok.lineLocatePoint(near)
                if MIN_STATION < s < (ok_len - MIN_STATION):
                    stations.append(s)

    stations.sort()
    cleaned: List[float] = []
    for s in stations:
        if not cleaned or (s - cleaned[-1]) > STATION_DEDUP_DIST:
            cleaned.append(s)
    return cleaned


def find_kehle_toe_point(
    crest_point: QgsPointXY,
    kehlen: Sequence[QgsGeometry],
    uk: QgsGeometry,
) -> QgsPointXY:
    """Toe-side anchor for a breakline. It never returns the crest point itself,
    which would create a zero-length hachure."""
    c_geom = QgsGeometry.fromPointXY(crest_point)
    best: Optional[QgsGeometry] = None
    best_dist = float("inf")
    for kehle in kehlen:
        d = c_geom.distance(kehle)
        if d < best_dist:
            best_dist = d
            best = kehle

    if best is not None and best_dist < KEHLE_TOE_MAX_DIST:
        k_start, k_end = line_ends(best)
        if measure(crest_point, k_start) > measure(crest_point, k_end):
            return k_start
        return k_end

    near = uk.nearestPoint(c_geom)
    if not near.isEmpty():
        return near.asPoint()
    if uk.length() > 0:
        return uk.interpolate(0.0).asPoint()
    return crest_point


def enforce_monotonicity(
    targets: List[Target],
    ring_period: Optional[float] = None,
) -> List[Target]:
    """Drops targets that would move backwards along the toe line and cause crossings.

    On a toe ring (ring_period set) the parameter restarts at the ring's start
    vertex. Steps are then measured the short way round the ring, so passing the
    start vertex is not mistaken for a step backwards.
    """
    if len(targets) <= 2:
        return targets

    cleaned: List[Target] = [targets[0]]
    kehle_modes = (HachureMode.KEHLE, HachureMode.KEHLE_ANKER)
    for current in targets[1:]:
        previous = cleaned[-1]
        if current.mode in kehle_modes or previous.mode in kehle_modes:
            cleaned.append(current)
            continue
        if current.uk_param is not None and previous.uk_param is not None:
            if ring_period:
                step = circular_delta(previous.uk_param, current.uk_param, ring_period)
            else:
                step = current.uk_param - previous.uk_param
            if step < -MIN_TARGET_DIST:
                if current.mode == HachureMode.ENDFLANKE:
                    cleaned.append(current)
                continue
        cleaned.append(current)
    return cleaned
