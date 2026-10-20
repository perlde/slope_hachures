# -*- coding: utf-8 -*-
"""
Core geometry engine for engineering slope hachures.

Computes primary targets between crest (Kamm) and toe (Fuß) and hands them to
the emitter. It has no UI and no processing dependencies.

SPDX-License-Identifier: GPL-3.0-or-later
"""

from typing import List, Optional, Sequence

from qgis.core import QgsGeometry, QgsPointXY, QgsProcessingFeedback

from .emission import HachureEmitter
from .geometry_utils import (
    align_toe_line,
    extract_points,
    has_self_intersection,
    project_onto,
    is_near_any,
    is_valid_slope_angle,
    measure,
    nearest_crossing,
    segment,
    cast_both_ways,
    unit_normal,
)
from .models import HachureData, HachureMode, Hit, Target
from .tuning import (
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
    ENDPOINT_PREFERENCE,
    MIN_TARGET_DIST,
    STATION_DEDUP_DIST,
)


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
    ) -> List[HachureData]:
        log = feedback if feedback is not None else QgsProcessingFeedback()

        error = self._validate_input(ok_geom, uk_geom)
        if error is not None:
            log.pushWarning(f"SlopeEngine: {error}, skipped.")
            return []

        kehlen = [k for k in (kehlen_geoms or []) if k is not None and not k.isEmpty()]
        ok_len = ok_geom.length()
        if ok_len <= 0.0:
            log.pushWarning("SlopeEngine: degenerate crest geometry, skipped.")
            return []

        toe = align_toe_line(ok_geom, uk_geom)
        if toe is None or toe.length() <= 0.0:
            log.pushWarning("SlopeEngine: toe line is not one continuous line, skipped.")
            return []

        primary = self._primary_targets(ok_geom, toe, kehlen, ok_len)
        if len(primary) < 2:
            log.pushInfo(f"SlopeEngine: only {len(primary)} target(s), skipped.")
            return []

        targets = enforce_monotonicity(primary)
        emitter = HachureEmitter(
            ok_geom, toe, kehlen,
            self.interval, self.short_ratio, self.max_search_dist,
        )
        return emitter.emit(targets, log)

    # ------------------------------------------------------------ validation
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
        uk: QgsGeometry,
        kehlen: List[QgsGeometry],
        ok_len: float,
    ) -> List[Target]:
        targets: List[Target] = []
        bounds = [0.0] + find_kehlen_stations(ok, kehlen, ok_len) + [ok_len]
        last_section = len(bounds) - 2

        for idx in range(len(bounds) - 1):
            s_start, s_end = bounds[idx], bounds[idx + 1]
            sec_len = s_end - s_start
            if sec_len < MIN_SECTION_LENGTH:
                continue

            if idx == 0:
                start = self._boundary_target(ok, uk, kehlen, True, ok_len)
                if start is not None:
                    targets.append(start)

            segments = max(1, round(sec_len / self.interval))
            step_len = sec_len / segments
            for step in range(1, segments):
                station = s_start + step * step_len
                p_ok = ok.interpolate(station).asPoint()
                if is_near_any(p_ok, kehlen, KEHLE_NEAR_FACTOR * self.interval):
                    continue
                internal = self._internal_target(ok, uk, kehlen, station, p_ok)
                if internal is not None:
                    targets.append(internal)

            if idx == last_section:
                end = self._boundary_target(ok, uk, kehlen, False, ok_len)
                if end is not None:
                    targets.append(end)
            else:
                p_section_end = ok.interpolate(s_end).asPoint()
                anchor = find_kehle_toe_point(p_section_end, kehlen, uk)
                targets.append(Target(s_end, None, anchor, HachureMode.KEHLE_ANKER))

        return targets

    def _boundary_target(
        self,
        ok: QgsGeometry,
        uk: QgsGeometry,
        kehlen: List[QgsGeometry],
        at_start: bool,
        ok_len: float,
    ) -> Optional[Target]:
        """Target at the crest start or end.

        The toe-side point is the projection of the crest end onto the toe line,
        not the end of the toe line. Otherwise a toe line that reaches beyond the
        crest pulls the hachure away from the crest.
        """
        station = 0.0 if at_start else ok_len
        p_ok = ok.interpolate(station).asPoint()
        p_uk, uk_param = project_onto(uk, p_ok)
        uk_start = uk.interpolate(0.0).asPoint()
        uk_end = uk.interpolate(uk.length()).asPoint()
        if measure(uk_start, uk_end) < 1e-6 and measure(p_uk, uk_start) < 1e-6:
            # Closed toe ring: start and end coincide, pin the parameter to the requested side.
            uk_param = 0.0 if at_start else uk.length()

        # Prefer the toe END if it is not much farther away than the perpendicular foot.
        # Otherwise the toe beyond the last hachure stays unhatched.
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
        ok: QgsGeometry,
        uk: QgsGeometry,
        kehlen: List[QgsGeometry],
        station: float,
        p_ok: QgsPointXY,
    ) -> Optional[Target]:
        hit: Optional[Hit] = None
        normal = unit_normal(ok, station, self.interval)
        if normal is not None:
            hit = cast_both_ways(p_ok, normal, self.max_search_dist, uk, kehlen)
        if hit is None:
            hit = self._fallback_nearest(ok, uk, kehlen, station, p_ok)
        if hit is None:
            return None
        return Target(station, hit.uk_param, hit.point, hit.mode)

    def _fallback_nearest(
        self,
        ok: QgsGeometry,
        uk: QgsGeometry,
        kehlen: List[QgsGeometry],
        station: float,
        p_ok: QgsPointXY,
    ) -> Optional[Hit]:
        near = uk.nearestPoint(QgsGeometry.fromPointXY(p_ok))
        if near.isEmpty() or measure(p_ok, near.asPoint()) > self.max_search_dist:
            return None

        cand_t = uk.lineLocatePoint(near)
        cand_pt = uk.interpolate(cand_t).asPoint()
        if not is_valid_slope_angle(ok, station, p_ok, cand_pt):
            return None

        cand_dist = measure(p_ok, cand_pt)
        crossing = nearest_crossing(
            p_ok, segment(p_ok, cand_pt), kehlen, limit=cand_dist, margin=0.0,
        )
        if crossing is not None:
            return Hit(crossing, None, HachureMode.KEHLE)
        return Hit(cand_pt, cand_t, HachureMode.PROJEKTION)


# ------------------------------------------------------------------ helpers
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

        for kp in (kehle.interpolate(0.0).asPoint(),
                   kehle.interpolate(kehle.length()).asPoint()):
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
        k_start = best.interpolate(0.0).asPoint()
        k_end = best.interpolate(best.length()).asPoint()
        if measure(crest_point, k_start) > measure(crest_point, k_end):
            return k_start
        return k_end

    near = uk.nearestPoint(c_geom)
    if not near.isEmpty():
        return near.asPoint()
    if uk.length() > 0:
        return uk.interpolate(0.0).asPoint()
    return crest_point


def enforce_monotonicity(targets: List[Target]) -> List[Target]:
    """Drops targets that would move backwards along the toe line and cause crossings."""
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
            if current.uk_param < previous.uk_param - MIN_TARGET_DIST:
                if current.mode == HachureMode.ENDFLANKE:
                    cleaned.append(current)
                continue
        cleaned.append(current)
    return cleaned
