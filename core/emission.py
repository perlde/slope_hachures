# -*- coding: utf-8 -*-
"""
Emission of long and short hachures between consecutive targets.

SPDX-License-Identifier: GPL-3.0-or-later
"""

import math
from typing import List, Sequence

from qgis.core import QgsGeometry, QgsPointXY, QgsProcessingFeedback

from .geometry_utils import (
    cast_both_ways,
    is_near_any,
    measure,
    segment,
    unit_normal,
)
from .models import HachureData, HachureMode, Target
from .tuning import (
    KEHLE_NEAR_FACTOR,
    MIN_AVG_DIRECTION_LENGTH,
    MIN_LONG_LENGTH,
    MIN_SHORT_FULL_LENGTH,
    MIN_SHORT_LENGTH,
    ZWICKEL_FACTOR,
)

SHORT_MODE_MAP = {
    HachureMode.PROJEKTION: HachureMode.PROJEKTION_KURZ,
    HachureMode.KEHLE: HachureMode.KEHLE_KURZ,
    HachureMode.KEHLE_ANKER: HachureMode.KEHLE_ANKER_KURZ,
    HachureMode.ANFANGSFLANKE: HachureMode.ANFANGSFLANKE_KURZ,
    HachureMode.ENDFLANKE: HachureMode.ENDFLANKE_KURZ,
}


class HachureEmitter:
    """Creates the hachure list for a sequence of primary targets."""

    def __init__(
        self,
        ok_geom: QgsGeometry,
        uk_geom: QgsGeometry,
        kehlen: Sequence[QgsGeometry],
        interval: float,
        short_ratio: float,
        max_search_dist: float,
    ) -> None:
        self.ok = ok_geom
        self.uk = uk_geom
        self.kehlen = list(kehlen)
        self.interval = interval
        self.short_ratio = short_ratio
        self.max_dist = max_search_dist

    def emit(
        self,
        targets: List[Target],
        feedback: QgsProcessingFeedback,
    ) -> List[HachureData]:
        result: List[HachureData] = []
        for index, current in enumerate(targets):
            if feedback.isCanceled():
                break
            if current.mode != HachureMode.KEHLE_ANKER:
                self._emit_long(current, result)
            if index < len(targets) - 1:
                self._emit_short(current, targets[index + 1], result)
        return result

    # ------------------------------------------------------------- long
    def _emit_long(self, target: Target, out: List[HachureData]) -> None:
        start = self.ok.interpolate(target.station).asPoint()
        full_len = measure(start, target.point)
        if full_len <= MIN_LONG_LENGTH:
            return
        out.append(HachureData(
            geometry=segment(start, target.point),
            hachure_type="lang",
            station=target.station,
            length=full_len,
            full_length=full_len,
            mode=target.mode,
        ))

    # ------------------------------------------------------------- short
    def _emit_short(
        self,
        current: Target,
        following: Target,
        out: List[HachureData],
    ) -> None:
        if following.station - current.station < ZWICKEL_FACTOR * self.interval:
            return

        mid_station = (current.station + following.station) / 2.0
        mid_start = self.ok.interpolate(mid_station).asPoint()
        if is_near_any(mid_start, self.kehlen, KEHLE_NEAR_FACTOR * self.interval):
            return

        is_anchor = (
            current.mode == HachureMode.KEHLE_ANKER
            or following.mode == HachureMode.KEHLE_ANKER
        )

        hit = None
        normal = unit_normal(self.ok, mid_station, self.interval)
        if normal is not None:
            hit = cast_both_ways(mid_start, normal, self.max_dist, self.uk, self.kehlen)

        if is_anchor:
            mode = HachureMode.KEHLE_KURZ
        elif hit is not None:
            mode = SHORT_MODE_MAP.get(hit.mode, HachureMode.PROJEKTION_KURZ)
        else:
            mode = SHORT_MODE_MAP.get(current.mode, HachureMode.PROJEKTION_KURZ)

        if hit is not None:
            self._short_from_hit(mid_start, hit.point, mid_station, mode, out)
        else:
            self._short_fallback(mid_start, mid_station, current, following, mode, out)

    def _short_from_hit(
        self,
        start: QgsPointXY,
        hit_point: QgsPointXY,
        station: float,
        mode: HachureMode,
        out: List[HachureData],
    ) -> None:
        full_len = measure(start, hit_point)
        draw_len = full_len * self.short_ratio
        if draw_len < MIN_SHORT_LENGTH or full_len <= MIN_SHORT_FULL_LENGTH:
            return
        ux = (hit_point.x() - start.x()) / full_len
        uy = (hit_point.y() - start.y()) / full_len
        end = QgsPointXY(start.x() + ux * draw_len, start.y() + uy * draw_len)
        out.append(HachureData(
            geometry=segment(start, end),
            hachure_type="kurz",
            station=station,
            length=draw_len,
            full_length=full_len,
            mode=mode,
        ))

    def _short_fallback(
        self,
        mid_start: QgsPointXY,
        mid_station: float,
        current: Target,
        following: Target,
        mode: HachureMode,
        out: List[HachureData],
    ) -> None:
        """No collision at the midpoint: average the directions of both neighbours."""
        left_start = self.ok.interpolate(current.station).asPoint()
        right_start = self.ok.interpolate(following.station).asPoint()

        v1 = (current.point.x() - left_start.x(), current.point.y() - left_start.y())
        v2 = (following.point.x() - right_start.x(), following.point.y() - right_start.y())
        l1 = math.hypot(*v1)
        l2 = math.hypot(*v2)
        if l1 <= MIN_LONG_LENGTH or l2 <= MIN_LONG_LENGTH:
            return

        u1 = (v1[0] / l1, v1[1] / l1)
        u2 = (v2[0] / l2, v2[1] / l2)
        avg = ((u1[0] + u2[0]) / 2.0, (u1[1] + u2[1]) / 2.0)
        avg_len = math.hypot(*avg)
        if avg_len <= MIN_AVG_DIRECTION_LENGTH:
            return

        ux = avg[0] / avg_len
        uy = avg[1] / avg_len
        avg_full_len = (l1 + l2) / 2.0
        draw_len = avg_full_len * self.short_ratio
        if draw_len < MIN_SHORT_LENGTH:
            return

        end = QgsPointXY(mid_start.x() + ux * draw_len, mid_start.y() + uy * draw_len)
        out.append(HachureData(
            geometry=segment(mid_start, end),
            hachure_type="kurz",
            station=mid_station,
            length=draw_len,
            full_length=avg_full_len,
            mode=mode,
        ))
