# -*- coding: utf-8 -*-
"""
QGIS plugin entry point for Slope Hachures.

SPDX-License-Identifier: GPL-3.0-or-later
"""


def classFactory(iface):
    """Called by QGIS when the plugin is loaded."""
    from .plugin import BoeschungPlugin
    return BoeschungPlugin(iface)
