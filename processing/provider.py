# -*- coding: utf-8 -*-
"""
QGIS Processing Provider registration for Slope Hachures.

Part of the Slope Hachures QGIS Plugin.
SPDX-License-Identifier: GPL-3.0-or-later
"""

import os
from qgis.PyQt.QtGui import QIcon
from qgis.core import QgsApplication, QgsProcessingProvider
from .slope_algorithm import SlopeHachuresAlgorithm


class SlopeProcessingProvider(QgsProcessingProvider):

    def loadAlgorithms(self):
        self.addAlgorithm(SlopeHachuresAlgorithm())

    def id(self) -> str:
        # Saubere, einheitliche interne ID
        return 'slope_hachures'

    def name(self) -> str:
        if QgsApplication.locale().startswith('de'):
            return 'Böschungsschraffen'
        return 'Slope Hachures'

    def icon(self) -> QIcon:
        plugin_dir = os.path.dirname(os.path.dirname(__file__))
        icon_path = os.path.join(plugin_dir, 'icon.svg')
        if os.path.exists(icon_path):
            return QIcon(icon_path)
        return super().icon()