# -*- coding: utf-8 -*-
"""
Named tuning constants for the slope engine. Distances are in map units (metres).

SPDX-License-Identifier: GPL-3.0-or-later
"""

from typing import Final

# Parameter limits (must match the Processing parameter definitions)
MIN_INTERVAL: Final[float] = 0.5
MIN_SEARCH_DIST: Final[float] = 1.0
MIN_SHORT_RATIO: Final[float] = 0.05
MAX_SHORT_RATIO: Final[float] = 0.95

# Geometry thresholds
MIN_TARGET_DIST: Final[float] = 0.05
MIN_LONG_LENGTH: Final[float] = 0.05
MIN_SHORT_LENGTH: Final[float] = 0.30
MIN_SHORT_FULL_LENGTH: Final[float] = 0.08
MIN_AVG_DIRECTION_LENGTH: Final[float] = 0.001
MIN_SECTION_LENGTH: Final[float] = 0.2
MIN_STATION: Final[float] = 0.5
STATION_DEDUP_DIST: Final[float] = 0.6

# Breakline (Kehle) handling
KEHLE_NEAR_FACTOR: Final[float] = 0.20   # times interval
KEHLE_ANCHOR_DIST: Final[float] = 0.25   # absolute buffer
KEHLE_SNAP_DIST: Final[float] = 0.35
KEHLE_TOE_MAX_DIST: Final[float] = 0.50

# Hachure geometry
ZWICKEL_FACTOR: Final[float] = 0.25      # times interval
MAX_SLOPE_DOT: Final[float] = 0.85
SLOPE_ANGLE_DELTA: Final[float] = 0.25
NORMAL_DELTA_FACTOR: Final[float] = 0.20  # times interval
NORMAL_DELTA_MIN: Final[float] = 0.2
NORMAL_DELTA_MAX: Final[float] = 0.8

# Toe line merging and safety limits (processing layer)
CHAIN_TOLERANCE: Final[float] = 0.05
AMBIGUITY_SAMPLES: Final[int] = 200     # sample points along a crest part for the ambiguity check
# A crest end connects to the toe END if that end is at most this factor farther away
# than the perpendicular foot. Otherwise the part of the toe beyond the last hachure
# would stay unhatched.
ENDPOINT_PREFERENCE: Final[float] = 1.5
MAX_SEGMENTS_PER_CREST: Final[int] = 100_000

# Closed lines (rings)
# A line whose end lies within this distance of its start is treated as a ring.
RING_CLOSE_TOLERANCE: Final[float] = 0.05
# Crest sample points used to decide the toe direction when crest or toe is a ring
# but not both (for two rings the winding is compared instead).
ORIENTATION_SAMPLES: Final[int] = 24

# Performance
# Toe lines with at least this many segments get a spatial index for ray queries.
SPATIAL_INDEX_MIN_SEGMENTS: Final[int] = 64
# The cancel button is checked every this many crest stations.
CANCEL_CHECK_INTERVAL: Final[int] = 16
