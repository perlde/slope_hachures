# -*- coding: utf-8 -*-
"""
Processing provider registration for Slope Hachures.

SPDX-License-Identifier: GPL-3.0-or-later
"""

from qgis.core import QgsProcessingProvider
from qgis.PyQt.QtGui import QIcon

from ..common import is_german_locale, plugin_icon
from ..constants import (
    PROVIDER_ID,
    PROVIDER_LONG_NAME_DE,
    PROVIDER_LONG_NAME_EN,
    PROVIDER_NAME_DE,
    PROVIDER_NAME_EN,
    PROVIDER_VERSION,
)
from .slope_algorithm import SlopeHachuresAlgorithm


class SlopeProcessingProvider(QgsProcessingProvider):
    """Registers the slope hachures algorithm in the Processing toolbox."""

    def id(self) -> str:
        return PROVIDER_ID

    def name(self) -> str:
        return PROVIDER_NAME_DE if is_german_locale() else PROVIDER_NAME_EN

    def longName(self) -> str:
        return PROVIDER_LONG_NAME_DE if is_german_locale() else PROVIDER_LONG_NAME_EN

    def version(self) -> str:
        return PROVIDER_VERSION

    def icon(self) -> QIcon:
        return plugin_icon()

    def loadAlgorithms(self) -> None:
        self.addAlgorithm(SlopeHachuresAlgorithm())
