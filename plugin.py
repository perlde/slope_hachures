# -*- coding: utf-8 -*-
"""
Plugin lifecycle and GUI integration for Slope Hachures.

SPDX-License-Identifier: GPL-3.0-or-later
"""

import os
import traceback
from typing import Optional

import processing
from qgis.core import Qgis, QgsApplication, QgsMessageLog
from qgis.PyQt.QtCore import QCoreApplication, QLocale, QTranslator
from qgis.PyQt.QtWidgets import QAction

from .common import plugin_icon
from .constants import ALGORITHM_ID, LOG_TAG, PROVIDER_ID, TRANSLATION_BASENAME
from .processing.provider import SlopeProcessingProvider

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))


def find_qm_file() -> Optional[str]:
    """Finds the compiled translation for the current locale, e.g. de_DE, then de."""
    raw = QgsApplication.locale() or QLocale().name()
    for code in dict.fromkeys((raw, raw.split("_")[0])):
        path = os.path.join(PLUGIN_DIR, "i18n", f"{TRANSLATION_BASENAME}_{code}.qm")
        if os.path.isfile(path):
            return path
    return None


class BoeschungPlugin:
    """QGIS plugin entry point for slope hachures."""

    def __init__(self, iface) -> None:
        self.iface = iface
        self.provider: Optional[SlopeProcessingProvider] = None
        self.action: Optional[QAction] = None
        self._translator: Optional[QTranslator] = None
        self.menu_name = self.tr("&Slope Hachures")
        self._install_translator()

    # ------------------------------------------------------------------ i18n
    def _install_translator(self) -> None:
        qm_path = find_qm_file()
        if qm_path is None:
            return
        translator = QTranslator()
        if not translator.load(qm_path):
            QgsMessageLog.logMessage(
                f"Could not load translation file: {qm_path}", LOG_TAG, Qgis.MessageLevel.Warning,
            )
            return
        if QCoreApplication.installTranslator(translator):
            self._translator = translator

    def tr(self, message: str) -> str:
        return QCoreApplication.translate("BoeschungPlugin", message)

    # --------------------------------------------------------------- feedback
    def _warn_user(self, message: str) -> None:
        bar = self.iface.messageBar() if self.iface is not None else None
        if bar is not None:
            bar.pushWarning(self.tr("Slope Hachures"), message)
        else:
            QgsMessageLog.logMessage(message, LOG_TAG, Qgis.MessageLevel.Warning)

    # --------------------------------------------------------------- provider
    def initProcessing(self) -> bool:
        if self.provider is not None:
            return True
        provider = SlopeProcessingProvider()
        if not QgsApplication.processingRegistry().addProvider(provider):
            QgsMessageLog.logMessage(
                f"Could not register provider '{PROVIDER_ID}'.", LOG_TAG, Qgis.MessageLevel.Critical,
            )
            self._warn_user(self.tr(
                "Processing provider could not be registered. "
                "Please check the QGIS log for details."
            ))
            return False
        self.provider = provider
        return True

    # -------------------------------------------------------------- lifecycle
    def initGui(self) -> None:
        if self.action is not None:
            return
        if not self.initProcessing():
            return

        action = QAction(
            plugin_icon(),
            self.tr("Generate Slope Hachures..."),
            self.iface.mainWindow(),
        )
        action.setStatusTip(self.tr("Open dialog to generate engineering slope hachures"))
        action.setToolTip(self.tr("Generate Slope Hachures (OKSTRA / RE 2012)"))
        action.triggered.connect(self.run)

        self.iface.addPluginToVectorMenu(self.menu_name, action)
        self.iface.addVectorToolBarIcon(action)
        self.action = action

    def unload(self) -> None:
        if self.action is not None:
            try:
                self.action.triggered.disconnect(self.run)
            except (TypeError, RuntimeError):
                pass  # already disconnected or the C++ object is gone
            self.iface.removeVectorToolBarIcon(self.action)
            self.iface.removePluginVectorMenu(self.menu_name, self.action)
            self.action.deleteLater()
            self.action = None

        if self.provider is not None:
            QgsApplication.processingRegistry().removeProvider(self.provider)
            self.provider = None

        if self._translator is not None:
            QCoreApplication.removeTranslator(self._translator)
            self._translator = None

    # ----------------------------------------------------------------- action
    def run(self) -> None:
        if self.provider is None:
            self._warn_user(self.tr("Plugin is not initialized. Please restart QGIS."))
            return
        alg_id = f"{PROVIDER_ID}:{ALGORITHM_ID}"
        try:
            processing.execAlgorithmDialog(alg_id)
        except Exception as exc:  # GUI boundary: every error must reach the log
            QgsMessageLog.logMessage(
                f"Could not open algorithm dialog '{alg_id}': {exc}\n"
                f"{traceback.format_exc()}",
                LOG_TAG, Qgis.MessageLevel.Critical,
            )
            self._warn_user(self.tr("Could not open the processing dialog: {}").format(exc))
