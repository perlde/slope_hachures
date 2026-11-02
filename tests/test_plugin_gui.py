# -*- coding: utf-8 -*-
"""Plugin metadata and the GUI lifecycle (initGui / unload) as QGIS runs it.

The lifecycle test needs a GUI-enabled QgsApplication. It runs in a separate
Python process, so a crash there cannot take the other tests down.

SPDX-License-Identifier: GPL-3.0-or-later
"""

import configparser
import os
import subprocess
import sys
import textwrap
import unittest

from _bootstrap import HAS_QGIS, ROOT, plugin_module

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))

LIFECYCLE_SCRIPT = textwrap.dedent("""
    import sys
    sys.path.insert(0, {tests_dir!r})
    import _bootstrap
    from qgis.core import QgsApplication

    app = QgsApplication([], True)
    app.initQgis()

    class Iface:
        def __init__(self):
            self.menu, self.toolbar = [], []
        def mainWindow(self):
            return None
        def messageBar(self):
            return None
        def addPluginToVectorMenu(self, name, action):
            self.menu.append((name, action))
        def removePluginVectorMenu(self, name, action):
            self.menu.remove((name, action))
        def addVectorToolBarIcon(self, action):
            self.toolbar.append(action)
        def removeVectorToolBarIcon(self, action):
            self.toolbar.remove(action)

    import slope_hachures
    iface = Iface()
    plugin = slope_hachures.classFactory(iface)
    plugin.initGui()
    registry = QgsApplication.processingRegistry()
    assert registry.providerById("slope_hachures") is not None, "provider not registered"
    assert registry.algorithmById("slope_hachures:generate_slope_hachures") is not None, "algorithm missing"
    assert len(iface.menu) == 1 and len(iface.toolbar) == 1, "action not added"
    assert iface.toolbar[0].text(), "action has no text"
    plugin.initGui()  # a second call must not add a second action
    assert len(iface.toolbar) == 1, "action added twice"
    plugin.unload()
    assert registry.providerById("slope_hachures") is None, "provider not removed"
    assert not iface.menu and not iface.toolbar, "action not removed"
    plugin.unload()  # unloading twice must be harmless
    print("LIFECYCLE OK")
""")


def read_metadata():
    parser = configparser.ConfigParser()
    parser.read(os.path.join(ROOT, "metadata.txt"), encoding="utf-8")
    return parser["general"]


class MetadataTest(unittest.TestCase):
    def test_qgis_versions(self):
        meta = read_metadata()
        self.assertEqual(meta["qgisMinimumVersion"], "3.22")
        self.assertEqual(meta["qgisMaximumVersion"], "4.99")  # QGIS 4 compatible
        # supportsQt6 is no longer recognised by QGIS and should not be set
        self.assertNotIn("supportsQt6", meta)

    def test_version_matches_provider(self):
        self.assertEqual(read_metadata()["version"], plugin_module("constants").PROVIDER_VERSION)


@unittest.skipUnless(HAS_QGIS, "needs QGIS")
class GuiLifecycleTest(unittest.TestCase):
    def test_init_gui_and_unload(self):
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        result = subprocess.run(
            [sys.executable, "-c", LIFECYCLE_SCRIPT.format(tests_dir=TESTS_DIR)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env, timeout=300,
            check=False,
        )
        self.assertIn("LIFECYCLE OK", result.stdout, result.stdout[-3000:])
        self.assertEqual(result.returncode, 0, result.stdout[-3000:])


if __name__ == "__main__":
    unittest.main()
