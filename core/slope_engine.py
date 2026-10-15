# -*- coding: utf-8 -*-
"""
Core geometry calculation engine for engineering slope hachures.
Handles ray projection, boundary collisions, breaklines, and adaptive spacing.

Part of the Slope Hachures QGIS Plugin.
SPDX-License-Identifier: GPL-3.0-or-later
"""

import math
from dataclasses import dataclass
from typing import List, Optional, Tuple

from qgis.core import (
    QgsGeometry,
    QgsPointXY,
    QgsWkbTypes
)


@dataclass
class HachureData:
    geometry: QgsGeometry
    hachure_type: str  # 'lang', 'kurz', 'kehle'
    station: float
    length: float
    full_length: float
    mode: str  # 'projektion', 'kehle', 'anfangsflanke', 'endflanke', 'kehle_anker'


class SlopeEngine:
    def __init__(
        self,
        interval: float = 4.0,
        short_ratio: float = 0.5,
        max_search_dist: float = 50.0
    ):
        self.interval = max(0.5, float(interval))
        self.short_ratio = max(0.05, min(0.95, float(short_ratio)))
        self.max_search_dist = max(1.0, float(max_search_dist))
        # Mindestlänge einer Kurzschraffe (0.30 m)
        self.min_short_length = 0.30

    def compute_hachures(
        self,
        ok_geom: QgsGeometry,
        uk_geom: QgsGeometry,
        kehlen_geoms: Optional[List[QgsGeometry]] = None
    ) -> List[HachureData]:
        if not ok_geom or ok_geom.isEmpty() or not uk_geom or uk_geom.isEmpty():
            return []

        kehlen = kehlen_geoms or []
        ok_len = ok_geom.length()
        uk_len = uk_geom.length()
        if ok_len <= 0.0 or uk_len <= 0.0:
            return []

        # 1. Ausrichtung der Unterkante (MultiLineString-sicher)
        uk_aligned = self._align_uk_direction(ok_geom, uk_geom)

        # 2. Primäre Zielpunkte ermitteln (inkl. automatischer Zwangspunkt-Teilung an Kehlen)
        primary_targets = self._compute_primary_targets(ok_geom, uk_aligned, kehlen, ok_len, uk_len)
        if len(primary_targets) < 2:
            return []

        # 3. Monotonie prüfen (Kehlen und Kehlen-Anker bleiben geschützt)
        primary_targets = self._enforce_monotonicity(primary_targets)

        result: List[HachureData] = []

        # 4. Erzeugung langer und kurzer Schraffen
        for i in range(len(primary_targets)):
            s_ok, t_uk, p_target, eff_mode = primary_targets[i]

            # A. Lange Schraffe zeichnen (NUR wenn kein virtueller Kehlen-Anker!)
            if eff_mode != "kehle_anker":
                p_start = ok_geom.interpolate(s_ok).asPoint()
                full_len = self._dist(p_start, p_target)

                if full_len > 0.05:
                    long_geom = QgsGeometry.fromPolylineXY([p_start, p_target])
                    result.append(
                        HachureData(
                            geometry=long_geom,
                            hachure_type="lang",
                            station=round(s_ok, 3),
                            length=round(full_len, 3),
                            full_length=round(full_len, 3),
                            mode=eff_mode
                        )
                    )

            # B. Kurze Schraffe im Trichter zwischen Zielpunkt i und i+1
            if i < len(primary_targets) - 1:
                next_s_ok, _, next_p_target, next_mode = primary_targets[i + 1]
                delta_s = next_s_ok - s_ok

                # Zwickel-Filter: Mindestabstand zwischen den Stützpunkten
                if delta_s < (0.25 * self.interval):
                    continue

                mid_s_ok = (s_ok + next_s_ok) / 2.0
                p_mid_start = ok_geom.interpolate(mid_s_ok).asPoint()

                # Puffer zur Kehle: Nicht direkt AUF einer Kehlenlinie zeichnen
                if self._is_near_any_kehle(p_mid_start, kehlen, 0.20 * self.interval):
                    continue

                # Autonomen Normalenstrahl an der Zwischenstation berechnen
                normal_mid = self._calculate_tangent_normal(ok_geom, mid_s_ok)
                p_mid_hit = None
                mid_mode = (
                    "kehle_kurz" if (eff_mode == "kehle_anker" or next_mode == "kehle_anker")
                    else eff_mode + "_kurz"
                )

                if normal_mid is not None:
                    nx_m, ny_m = normal_mid
                    ray_fwd_m = QgsGeometry.fromPolylineXY([
                        p_mid_start,
                        QgsPointXY(
                            p_mid_start.x() + nx_m * self.max_search_dist,
                            p_mid_start.y() + ny_m * self.max_search_dist
                        )
                    ])
                    ray_bwd_m = QgsGeometry.fromPolylineXY([
                        p_mid_start,
                        QgsPointXY(
                            p_mid_start.x() - nx_m * self.max_search_dist,
                            p_mid_start.y() - ny_m * self.max_search_dist
                        )
                    ])

                    p_mid_hit, _, hit_m = self._find_best_collision(p_mid_start, ray_fwd_m, uk_aligned, kehlen)
                    if p_mid_hit is None:
                        p_mid_hit, _, hit_m = self._find_best_collision(p_mid_start, ray_bwd_m, uk_aligned, kehlen)
                    if p_mid_hit is not None:
                        mid_mode = hit_m + "_kurz"

                # Zeichnen entlang des Normalenstrahls mit Mindestlängenprüfung
                if p_mid_hit is not None:
                    full_mid_len = self._dist(p_mid_start, p_mid_hit)
                    draw_len = full_mid_len * self.short_ratio

                    if draw_len >= self.min_short_length and full_mid_len > 0.08:
                        ux = (p_mid_hit.x() - p_mid_start.x()) / full_mid_len
                        uy = (p_mid_hit.y() - p_mid_start.y()) / full_mid_len

                        p_mid_draw_end = QgsPointXY(
                            p_mid_start.x() + ux * draw_len,
                            p_mid_start.y() + uy * draw_len
                        )
                        short_geom = QgsGeometry.fromPolylineXY([p_mid_start, p_mid_draw_end])
                        result.append(
                            HachureData(
                                geometry=short_geom,
                                hachure_type="kurz",
                                station=round(mid_s_ok, 3),
                                length=round(draw_len, 3),
                                full_length=round(full_mid_len, 3),
                                mode=mid_mode
                            )
                        )
                else:
                    # Fallback: Harmonische Vektormittelung der Nachbarn
                    p_start_i = ok_geom.interpolate(s_ok).asPoint()
                    v1_x = p_target.x() - p_start_i.x()
                    v1_y = p_target.y() - p_start_i.y()
                    length1 = math.hypot(v1_x, v1_y)

                    next_p_start = ok_geom.interpolate(next_s_ok).asPoint()
                    v2_x = next_p_target.x() - next_p_start.x()
                    v2_y = next_p_target.y() - next_p_start.y()
                    length2 = math.hypot(v2_x, v2_y)

                    if length1 > 0.05 and length2 > 0.05:
                        u1_x, u1_y = v1_x / length1, v1_y / length1
                        u2_x, u2_y = v2_x / length2, v2_y / length2
                        avg_ux = (u1_x + u2_x) / 2.0
                        avg_uy = (u1_y + u2_y) / 2.0
                        avg_u_len = math.hypot(avg_ux, avg_uy)

                        if avg_u_len > 0.001:
                            avg_ux /= avg_u_len
                            avg_uy /= avg_u_len
                            avg_full_len = (length1 + length2) / 2.0
                            draw_len = avg_full_len * self.short_ratio

                            if draw_len >= self.min_short_length:
                                p_mid_draw_end = QgsPointXY(
                                    p_mid_start.x() + avg_ux * draw_len,
                                    p_mid_start.y() + avg_uy * draw_len
                                )
                                short_geom = QgsGeometry.fromPolylineXY([p_mid_start, p_mid_draw_end])
                                result.append(
                                    HachureData(
                                        geometry=short_geom,
                                        hachure_type="kurz",
                                        station=round(mid_s_ok, 3),
                                        length=round(draw_len, 3),
                                        full_length=round(avg_full_len, 3),
                                        mode=mid_mode
                                    )
                                )

        return result

    def _align_uk_direction(self, ok_geom: QgsGeometry, uk_geom: QgsGeometry) -> QgsGeometry:
        ok_start = ok_geom.interpolate(0.0).asPoint()
        ok_end = ok_geom.interpolate(ok_geom.length()).asPoint()
        uk_start = uk_geom.interpolate(0.0).asPoint()
        uk_end = uk_geom.interpolate(uk_geom.length()).asPoint()

        dist_direct = self._dist(ok_start, uk_start) + self._dist(ok_end, uk_end)
        dist_reverse = self._dist(ok_start, uk_end) + self._dist(ok_end, uk_start)

        if dist_reverse < dist_direct:
            if uk_geom.isMultipart():
                multi_lines = uk_geom.asMultiPolyline()
                reversed_multi = [list(reversed(part)) for part in reversed(multi_lines)]
                return QgsGeometry.fromMultiPolylineXY(reversed_multi)
            else:
                line_pts = uk_geom.asPolyline()
                return QgsGeometry.fromPolylineXY(list(reversed(line_pts)))

        return uk_geom

    def _compute_primary_targets(
        self,
        ok_geom: QgsGeometry,
        uk_geom: QgsGeometry,
        kehlen_geoms: List[QgsGeometry],
        ok_len: float,
        uk_len: float
    ) -> List[Tuple[float, Optional[float], QgsPointXY, str]]:
        """
        Teilt die Trasse an internen Kehlen automatisch in Abschnitte auf.
        Garantiert perfekte 1:1-Takte mit Kurzschraffen links und rechts jeder Kehle!
        """
        targets: List[Tuple[float, Optional[float], QgsPointXY, str]] = []

        # 1. Alle Schnittpunkte / Anknüpfungen von Kehlen an der Oberkante finden
        internal_kehlen = self._find_kehlen_stations(ok_geom, kehlen_geoms, ok_len)
        section_bounds = [0.0] + internal_kehlen + [ok_len]

        # 2. Abschnitte nacheinander berechnen
        for sec_idx in range(len(section_bounds) - 1):
            s_sec_start = section_bounds[sec_idx]
            s_sec_end = section_bounds[sec_idx + 1]
            sec_len = s_sec_end - s_sec_start

            if sec_len < 0.2:
                continue

            # A. Startpunkt des aktuellen Abschnitts
            if sec_idx == 0:
                # Absoluter Trassen-Startpunkt (s = 0.0)
                p_ok_start = ok_geom.interpolate(0.0).asPoint()
                p_uk_start = uk_geom.interpolate(0.0).asPoint()
                d_start = self._dist(p_ok_start, p_uk_start)
                has_start_kehle = self._is_near_any_kehle(p_ok_start, kehlen_geoms, 0.25)

                if has_start_kehle:
                    targets.append((0.0, None, p_uk_start, "kehle_anker"))
                elif d_start <= self.max_search_dist:
                    start_line = QgsGeometry.fromPolylineXY([p_ok_start, p_uk_start])
                    flank_target = p_uk_start
                    flank_mode = "anfangsflanke"
                    flank_t: Optional[float] = 0.0

                    for kehle in kehlen_geoms:
                        inter_k = start_line.intersection(kehle)
                        if not inter_k.isEmpty():
                            for kp in self._extract_points(inter_k):
                                kd = self._dist(p_ok_start, kp)
                                if 0.05 < kd < (d_start - 0.05):
                                    flank_target = kp
                                    flank_mode = "kehle"
                                    flank_t = None
                                    d_start = kd

                    targets.append((0.0, flank_t, flank_target, flank_mode))
            else:
                # Interner Kehlenschnittpunkt als virtueller Takt-Anker
                # (bereits als Endpunkt des vorherigen Abschnitts eingetragen)
                pass

            # B. Gleichmäßige Streckenteilung innerhalb dieses Kehlen-Abschnitts
            num_segments = max(1, round(sec_len / self.interval))
            eff_interval = sec_len / num_segments

            for step in range(1, num_segments):
                curr_s = s_sec_start + step * eff_interval
                p_start = ok_geom.interpolate(curr_s).asPoint()

                # Puffer zu Kehlen beachten
                if self._is_near_any_kehle(p_start, kehlen_geoms, 0.20 * self.interval):
                    continue

                normal = self._calculate_tangent_normal(ok_geom, curr_s)
                target_pt = None
                target_t: Optional[float] = None
                target_mode = "kein_treffer"

                if normal is not None:
                    nx, ny = normal
                    ray_fwd = QgsGeometry.fromPolylineXY([
                        p_start,
                        QgsPointXY(p_start.x() + nx * self.max_search_dist, p_start.y() + ny * self.max_search_dist)
                    ])
                    ray_bwd = QgsGeometry.fromPolylineXY([
                        p_start,
                        QgsPointXY(p_start.x() - nx * self.max_search_dist, p_start.y() - ny * self.max_search_dist)
                    ])

                    target_pt, target_t, target_mode = self._find_best_collision(
                        p_start, ray_fwd, uk_geom, kehlen_geoms
                    )
                    if target_pt is None:
                        target_pt, target_t, target_mode = self._find_best_collision(
                            p_start, ray_bwd, uk_geom, kehlen_geoms
                        )

                # Fallback Nearest-Point mit Kehlen-Barriere
                if target_pt is None:
                    near_pt = uk_geom.nearestPoint(QgsGeometry.fromPointXY(p_start))
                    if not near_pt.isEmpty() and self._dist(p_start, near_pt.asPoint()) <= self.max_search_dist:
                        cand_t = uk_geom.lineLocatePoint(near_pt)
                        cand_pt = uk_geom.interpolate(cand_t).asPoint()

                        if self._is_valid_slope_angle(ok_geom, curr_s, p_start, cand_pt):
                            cand_line = QgsGeometry.fromPolylineXY([p_start, cand_pt])
                            cand_dist = self._dist(p_start, cand_pt)

                            blocked_by_kehle = False
                            closest_k_dist = cand_dist
                            closest_k_pt = None

                            for kehle in kehlen_geoms:
                                inter_k = cand_line.intersection(kehle)
                                if not inter_k.isEmpty():
                                    for kp in self._extract_points(inter_k):
                                        kd = self._dist(p_start, kp)
                                        if 0.05 < kd < (cand_dist - 0.05):
                                            if kd < closest_k_dist:
                                                closest_k_dist = kd
                                                closest_k_pt = kp
                                                blocked_by_kehle = True

                            if blocked_by_kehle and closest_k_pt is not None:
                                target_pt = closest_k_pt
                                target_t = None
                                target_mode = "kehle"
                            else:
                                target_pt = cand_pt
                                target_t = cand_t
                                target_mode = "projektion"

                if target_pt is not None:
                    targets.append((curr_s, target_t, target_pt, target_mode))

            # C. Endpunkt des aktuellen Abschnitts
            if sec_idx == len(section_bounds) - 2:
                # Absolutes Trassenende (s = ok_len)
                p_ok_end = ok_geom.interpolate(ok_len).asPoint()
                p_uk_end = uk_geom.interpolate(uk_len).asPoint()
                d_end = self._dist(p_ok_end, p_uk_end)
                has_end_kehle = self._is_near_any_kehle(p_ok_end, kehlen_geoms, 0.25)

                if has_end_kehle:
                    targets.append((ok_len, None, p_uk_end, "kehle_anker"))
                elif d_end <= self.max_search_dist:
                    end_line = QgsGeometry.fromPolylineXY([p_ok_end, p_uk_end])
                    flank_target = p_uk_end
                    flank_mode = "endflanke"
                    flank_t = uk_len

                    for kehle in kehlen_geoms:
                        inter_k = end_line.intersection(kehle)
                        if not inter_k.isEmpty():
                            for kp in self._extract_points(inter_k):
                                kd = self._dist(p_ok_end, kp)
                                if 0.05 < kd < (d_end - 0.05):
                                    flank_target = kp
                                    flank_mode = "kehle"
                                    flank_t = None
                                    d_end = kd

                    targets.append((ok_len, flank_t, flank_target, flank_mode))
            else:
                # Interner Kehlen-Abschluss: Dient als Takt-Anker für die Kurzschraffe!
                p_sec_end = ok_geom.interpolate(s_sec_end).asPoint()
                k_target = self._find_kehle_toe_point(p_sec_end, kehlen_geoms, uk_geom)
                targets.append((s_sec_end, None, k_target, "kehle_anker"))

        return targets

    def _find_kehlen_stations(
        self,
        ok_geom: QgsGeometry,
        kehlen_geoms: List[QgsGeometry],
        ok_len: float
    ) -> List[float]:
        """Ermittelt alle internen Stationen, an denen Kehlen die Oberkante schneiden oder berühren."""
        stations: List[float] = []
        if not kehlen_geoms:
            return stations

        for kehle in kehlen_geoms:
            # Schnittpunkte prüfen
            inter = ok_geom.intersection(kehle)
            if not inter.isEmpty():
                for p in self._extract_points(inter):
                    s = ok_geom.lineLocatePoint(QgsGeometry.fromPointXY(p))
                    if 0.5 < s < (ok_len - 0.5):
                        stations.append(s)

            # Endpunkte der Kehle prüfen (falls gesnappt)
            k_start = kehle.interpolate(0.0).asPoint()
            k_end = kehle.interpolate(kehle.length()).asPoint()
            for kp in (k_start, k_end):
                d = ok_geom.distance(QgsGeometry.fromPointXY(kp))
                if d < 0.35:
                    near_pt = ok_geom.nearestPoint(QgsGeometry.fromPointXY(kp))
                    s = ok_geom.lineLocatePoint(near_pt)
                    if 0.5 < s < (ok_len - 0.5):
                        stations.append(s)

        # Doppelte Stationen filtern
        stations.sort()
        cleaned: List[float] = []
        for s in stations:
            if not cleaned or (s - cleaned[-1]) > 0.6:
                cleaned.append(s)

        return cleaned

    def _find_kehle_toe_point(
        self,
        crest_point: QgsPointXY,
        kehlen_geoms: List[QgsGeometry],
        uk_geom: QgsGeometry
    ) -> QgsPointXY:
        """Findet den Fußpunkt der Kehle, die an crest_point ansetzt."""
        c_geom = QgsGeometry.fromPointXY(crest_point)
        best_kehle = None
        min_k_dist = 999.0

        for kehle in kehlen_geoms:
            d = c_geom.distance(kehle)
            if d < min_k_dist:
                min_k_dist = d
                best_kehle = kehle

        if best_kehle is not None and min_k_dist < 0.5:
            k_start = best_kehle.interpolate(0.0).asPoint()
            k_end = best_kehle.interpolate(best_kehle.length()).asPoint()
            # Der Fußpunkt ist derjenige Endpunkt der Kehle, der am weitesten vom Kamm weg liegt
            if self._dist(crest_point, k_start) > self._dist(crest_point, k_end):
                return k_start
            return k_end

        # Fallback auf UK
        near_uk = uk_geom.nearestPoint(c_geom)
        return near_uk.asPoint() if not near_uk.isEmpty() else crest_point

    def _find_best_collision(
        self,
        origin: QgsPointXY,
        ray_geom: QgsGeometry,
        uk_geom: QgsGeometry,
        kehlen_geoms: List[QgsGeometry]
    ) -> Tuple[Optional[QgsPointXY], Optional[float], str]:
        closest_pt = None
        min_dist = self.max_search_dist
        closest_t: Optional[float] = None
        mode = "kein_treffer"

        # 1. Schnitt mit Unterkante (UK)
        inter_uk = ray_geom.intersection(uk_geom)
        if not inter_uk.isEmpty():
            for p in self._extract_points(inter_uk):
                d = self._dist(origin, p)
                if 0.05 < d < min_dist:
                    min_dist = d
                    closest_pt = p
                    closest_t = uk_geom.lineLocatePoint(QgsGeometry.fromPointXY(p))
                    mode = "projektion"

        # 2. Schnitt mit Kehlen
        for kehle in kehlen_geoms:
            inter_k = ray_geom.intersection(kehle)
            if not inter_k.isEmpty():
                for p in self._extract_points(inter_k):
                    d = self._dist(origin, p)
                    if 0.05 < d < min_dist:
                        min_dist = d
                        closest_pt = p
                        closest_t = None
                        mode = "kehle"

        return closest_pt, closest_t, mode

    def _calculate_tangent_normal(
        self,
        ok_geom: QgsGeometry,
        station: float
    ) -> Optional[Tuple[float, float]]:
        total_len = ok_geom.length()
        delta = max(0.2, min(0.8, self.interval * 0.2))
        s1 = max(0.0, station - delta)
        s2 = min(total_len, station + delta)
        if s2 <= s1:
            return None

        p1 = ok_geom.interpolate(s1).asPoint()
        p2 = ok_geom.interpolate(s2).asPoint()

        dx = p2.x() - p1.x()
        dy = p2.y() - p1.y()
        length = math.hypot(dx, dy)
        return (-dy / length, dx / length) if length > 0 else None

    def _enforce_monotonicity(
        self,
        targets: List[Tuple[float, Optional[float], QgsPointXY, str]]
    ) -> List[Tuple[float, Optional[float], QgsPointXY, str]]:
        if len(targets) <= 2:
            return targets

        cleaned = [targets[0]]
        for i in range(1, len(targets)):
            prev_s, prev_t, prev_pt, prev_m = cleaned[-1]
            curr_s, curr_t, curr_pt, curr_m = targets[i]

            # Kehlentreffer und Kehlen-Anker sind heilig
            if "kehle" in curr_m or "kehle" in prev_m:
                cleaned.append((curr_s, curr_t, curr_pt, curr_m))
                continue

            # Monotonie-Prüfung auf der regulären Unterkante
            if curr_t is not None and prev_t is not None:
                if curr_t < (prev_t - 0.05):
                    if curr_m == "endflanke":
                        cleaned.append((curr_s, curr_t, curr_pt, curr_m))
                    continue

            cleaned.append((curr_s, curr_t, curr_pt, curr_m))

        return cleaned

    def _is_valid_slope_angle(
        self,
        ok_geom: QgsGeometry,
        station: float,
        p_start: QgsPointXY,
        p_target: QgsPointXY
    ) -> bool:
        tangent = self._calculate_tangent(ok_geom, station)
        if tangent is None:
            return True

        tx, ty = tangent
        vx = p_target.x() - p_start.x()
        vy = p_target.y() - p_start.y()
        v_len = math.hypot(vx, vy)
        if v_len == 0.0:
            return False

        vx /= v_len
        vy /= v_len
        dot = abs(tx * vx + ty * vy)
        return dot <= 0.85

    def _calculate_tangent(self, geom: QgsGeometry, station: float) -> Optional[Tuple[float, float]]:
        delta = 0.25
        total_len = geom.length()
        s1 = max(0.0, station - delta)
        s2 = min(total_len, station + delta)
        if s2 <= s1:
            return None

        p1 = geom.interpolate(s1).asPoint()
        p2 = geom.interpolate(s2).asPoint()
        dx = p2.x() - p1.x()
        dy = p2.y() - p1.y()
        length = math.hypot(dx, dy)
        return (dx / length, dy / length) if length > 0 else None

    def _is_near_any_kehle(
        self,
        point: QgsPointXY,
        kehlen_geoms: List[QgsGeometry],
        threshold: float
    ) -> bool:
        if not kehlen_geoms:
            return False
        pt_geom = QgsGeometry.fromPointXY(point)
        for kehle in kehlen_geoms:
            if pt_geom.distance(kehle) < threshold:
                return True
        return False

    def _extract_points(self, geom: QgsGeometry) -> List[QgsPointXY]:
        pts: List[QgsPointXY] = []
        if geom is None or geom.isEmpty():
            return pts

        flat_type = QgsWkbTypes.flatType(geom.wkbType())
        if flat_type == QgsWkbTypes.Point:
            pts.append(geom.asPoint())
        elif flat_type == QgsWkbTypes.MultiPoint:
            pts.extend(geom.asMultiPoint())
        elif flat_type == QgsWkbTypes.LineString:
            pts.extend(geom.asPolyline())
        elif flat_type == QgsWkbTypes.MultiLineString:
            for line in geom.asMultiPolyline():
                pts.extend(line)
        elif flat_type == QgsWkbTypes.GeometryCollection:
            for g in geom.asGeometryCollection():
                pts.extend(self._extract_points(g))
        return pts

    @staticmethod
    def _dist(p1: QgsPointXY, p2: QgsPointXY) -> float:
        return math.hypot(p2.x() - p1.x(), p2.y() - p1.y())