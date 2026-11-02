# -*- coding: utf-8 -*-
"""
Test bootstrap: makes the plugin importable as package `slope_hachures`, whatever
the checkout folder is called, and starts a headless QgsApplication when QGIS is
available.

Run all tests (from the repository root):
    python3 -m unittest discover -s tests -v

Tests that need QGIS are skipped when qgis.core cannot be imported. Run them inside
a QGIS Python environment, e.g. the qgis/qgis docker image (see the CI workflow).

SPDX-License-Identifier: GPL-3.0-or-later
"""

import importlib
import importlib.util
import os
import sys

PACKAGE = "slope_hachures"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _register_package() -> None:
    if PACKAGE in sys.modules:
        return
    spec = importlib.util.spec_from_file_location(
        PACKAGE, os.path.join(ROOT, "__init__.py"), submodule_search_locations=[ROOT],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE] = module
    spec.loader.exec_module(module)


_register_package()


def plugin_module(name: str):
    """Imports a plugin submodule, e.g. plugin_module('core.polyline')."""
    return importlib.import_module(f"{PACKAGE}.{name}")


try:
    from qgis.core import QgsApplication
    HAS_QGIS = True
except ImportError:
    QgsApplication = None
    HAS_QGIS = False

_APP = None


def qgis_app():
    """Returns the process-wide headless QgsApplication, starting it on first use."""
    global _APP
    if _APP is None:
        _APP = QgsApplication([], False)
        _APP.initQgis()
    return _APP
