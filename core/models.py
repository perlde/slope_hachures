# -*- coding: utf-8 -*-
"""
Data types shared by the slope engine modules.

SPDX-License-Identifier: GPL-3.0-or-later
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from qgis.core import QgsGeometry, QgsPointXY


class HachureMode(str, Enum):
    """Discrete, type-safe generation modes."""

    PROJEKTION = "projektion"
    KEHLE = "kehle"
    ANFANGSFLANKE = "anfangsflanke"
    ENDFLANKE = "endflanke"
    KEHLE_ANKER = "kehle_anker"
    PROJEKTION_KURZ = "projektion_kurz"
    KEHLE_KURZ = "kehle_kurz"
    ANFANGSFLANKE_KURZ = "anfangsflanke_kurz"
    ENDFLANKE_KURZ = "endflanke_kurz"
    KEHLE_ANKER_KURZ = "kehle_anker_kurz"


@dataclass(frozen=True)
class HachureData:
    """One generated hachure with raw (unrounded) values."""

    geometry: QgsGeometry
    hachure_type: str      # 'lang', 'kurz' or 'kehle'
    station: float         # station on the crest (m)
    length: float          # drawn length (m)
    full_length: float     # full length up to the collision (m)
    mode: HachureMode


@dataclass(frozen=True)
class Target:
    """A primary target: where a long hachure starts and where it ends."""

    station: float                 # station on the crest (m)
    uk_param: Optional[float]      # distance along the toe line, None for breaklines
    point: QgsPointXY              # end point of the hachure on the toe side
    mode: HachureMode


@dataclass(frozen=True)
class Hit:
    """Result of a ray collision: the hit point and how it was found."""

    point: QgsPointXY
    uk_param: Optional[float]
    mode: HachureMode
