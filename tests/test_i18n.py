# -*- coding: utf-8 -*-
"""Translation tests: every tr() string is in the .ts file, and the .qm file is up to date.

SPDX-License-Identifier: GPL-3.0-or-later
"""

import ast
import os
import unittest
import xml.etree.ElementTree as ElementTree

from _bootstrap import HAS_QGIS, ROOT, qgis_app

TS_FILE = os.path.join(ROOT, "i18n", "slope_hachures_de.ts")
QM_FILE = os.path.join(ROOT, "i18n", "slope_hachures_de.qm")

# context name -> source files whose self.tr() calls use that context
SOURCES = {
    "BoeschungPlugin": ["plugin.py"],
    "SlopeHachuresAlgorithm": ["processing/slope_algorithm.py"],
}
STYLE_LABELS = ["Long hatch", "Short hatch", "Valley / Breakline (OKSTRA 0486)"]


def ts_messages():
    """(context, source) -> translation from the .ts file."""
    messages = {}
    for context in ElementTree.parse(TS_FILE).getroot().iter("context"):
        name = context.findtext("name")
        for message in context.iter("message"):
            translation = message.find("translation")
            messages[(name, message.findtext("source"))] = (
                translation.text or "", translation.get("type"),
            )
    return messages


def tr_strings(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as handle:
        tree = ast.parse(handle.read())
    found = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "tr" and node.args
                and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
            found.append(node.args[0].value)
    return found


class TsFileTest(unittest.TestCase):
    def test_every_tr_string_is_translated(self):
        messages = ts_messages()
        missing = []
        for context, files in SOURCES.items():
            for path in files:
                for text in tr_strings(path):
                    if (context, text) not in messages:
                        missing.append((context, text))
        for label in STYLE_LABELS:
            if ("SlopeHachuresAlgorithm", label) not in messages:
                missing.append(("SlopeHachuresAlgorithm", label))
        self.assertEqual(missing, [])

    def test_no_unfinished_or_empty_translations(self):
        for key, (text, kind) in ts_messages().items():
            self.assertTrue(text.strip(), key)
            self.assertNotIn(kind, ("unfinished", "obsolete", "vanished"), key)


@unittest.skipUnless(HAS_QGIS, "needs QGIS")
class QmFileTest(unittest.TestCase):
    def test_qm_matches_ts(self):
        """Looks every message up the way the plugin does: QCoreApplication.translate()."""
        qgis_app()
        from qgis.PyQt.QtCore import QCoreApplication, QTranslator
        translator = QTranslator()
        self.assertTrue(translator.load(QM_FILE))
        self.assertTrue(QCoreApplication.installTranslator(translator))
        try:
            stale = [key for key, (text, _) in ts_messages().items()
                     if QCoreApplication.translate(key[0], key[1]) != text]
        finally:
            QCoreApplication.removeTranslator(translator)
        self.assertEqual(stale, [], "the .qm file is out of date: run i18n/build_translations.py")


if __name__ == "__main__":
    unittest.main()
