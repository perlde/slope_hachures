# -*- coding: utf-8 -*-
"""
Shared helpers: plugin icon and locale check. No algorithm logic here.

SPDX-License-Identifier: GPL-3.0-or-later
"""

import os

from qgis.core import QgsApplication
from qgis.PyQt.QtGui import QIcon

_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
_ICON_FILES = ("icon.svg", "icon.png")
_FALLBACK_THEME_ICON = "/mActionAddPolygon.svg"


def is_german_locale() -> bool:
    """True if the QGIS interface language is German."""
    return QgsApplication.locale().startswith("de")


def plugin_icon() -> QIcon:
    """Returns the plugin icon, or a theme icon if no icon file is present."""
    for filename in _ICON_FILES:
        path = os.path.join(_PLUGIN_DIR, filename)
        if os.path.isfile(path):
            icon = QIcon(path)
            if not icon.isNull():
                return icon
    return QgsApplication.getThemeIcon(_FALLBACK_THEME_ICON)
