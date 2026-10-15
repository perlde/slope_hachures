# -*- coding: utf-8 -*-
"""
Main plugin lifecycle and GUI action management for Slope Hachures.

Part of the Slope Hachures QGIS Plugin.
SPDX-License-Identifier: GPL-3.0-or-later
"""

import os
from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction
from qgis.core import QgsApplication
import processing

from .processing.provider import SlopeProcessingProvider


class BoeschungPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.provider = None
        self.action = None
        is_de = QgsApplication.locale().startswith('de')
        self.menu_name = '&Böschungsschraffen' if is_de else '&Slope Hachures'

    def tr(self, message: str) -> str:
        translated = QCoreApplication.translate('BoeschungPlugin', message)
        if translated != message:
            return translated
        if QgsApplication.locale().startswith('de'):
            de_map = {
                'Generate Slope Hachures...': 'Böschungsschraffen erzeugen...',
                'Open dialog to generate engineering slope hachures': 'Öffnet den Berechnungsdialog für normgerechte Böschungsschraffen',
                'Generate Slope Hachures (OKSTRA / RE 2012)': 'Böschungsschraffen erzeugen (OKSTRA / RE 2012)'
            }
            return de_map.get(message, message)
        return message

    def initProcessing(self):
        self.provider = SlopeProcessingProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)

    def initGui(self):
        self.initProcessing()

        plugin_dir = os.path.dirname(__file__)
        icon_path = os.path.join(plugin_dir, 'icon.svg')
        icon = QIcon(icon_path) if os.path.exists(icon_path) else QIcon()

        self.action = QAction(icon, self.tr('Generate Slope Hachures...'), self.iface.mainWindow())
        self.action.setStatusTip(self.tr('Open dialog to generate engineering slope hachures'))
        self.action.setToolTip(self.tr('Generate Slope Hachures (OKSTRA / RE 2012)'))
        self.action.triggered.connect(self.run)

        self.iface.addPluginToVectorMenu(self.menu_name, self.action)
        self.iface.addVectorToolBarIcon(self.action)

    def unload(self):
        if self.action:
            self.iface.removeVectorToolBarIcon(self.action)
            self.iface.removePluginVectorMenu(self.menu_name, self.action)
            del self.action
            self.action = None

        if self.provider:
            QgsApplication.processingRegistry().removeProvider(self.provider)
            self.provider = None

    def run(self):
        # Synchron zur neuen Provider-ID 'slope_hachures'
        processing.execAlgorithmDialog('slope_hachures:generate_slope_hachures')