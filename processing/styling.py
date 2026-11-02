# -*- coding: utf-8 -*-
"""
Standard cartographic symbology for slope hachures.

SPDX-License-Identifier: GPL-3.0-or-later
"""

from typing import Set

from qgis.core import (
    QgsLineSymbol,
    QgsMapLayer,
    QgsProcessingLayerPostProcessorInterface,
    QgsRuleBasedRenderer,
    QgsVectorLayer,
)
from qgis.PyQt import sip
from qgis.PyQt.QtCore import QCoreApplication

_TR_CONTEXT = "SlopeHachuresAlgorithm"
_EARTH_BROWN = "110,65,30,255"
_DARK_BROWN = "70,40,15,255"


def apply_slope_style(layer: QgsVectorLayer) -> None:
    """Applies the rule-based symbology for long, short and breakline hachures."""
    root_rule = QgsRuleBasedRenderer.Rule(None)
    specs = (
        (_EARTH_BROWN, "0.22", "lang", "Long hatch"),
        (_EARTH_BROWN, "0.18", "kurz", "Short hatch"),
        (_DARK_BROWN, "0.35", "kehle", "Valley / Breakline (OKSTRA 0486)"),
    )
    for color, width, typ, label in specs:
        symbol = QgsLineSymbol.createSimple({"color": color, "width": width})
        expression = '"typ" = ' + repr(typ)
        description = QCoreApplication.translate(_TR_CONTEXT, label)
        root_rule.appendChild(
            QgsRuleBasedRenderer.Rule(symbol, 0, 0, expression, description)
        )
    layer.setRenderer(QgsRuleBasedRenderer(root_rule))


class SlopeStylePostProcessor(QgsProcessingLayerPostProcessorInterface):
    """Applies the standard symbology when a processing output layer is loaded.

    QGIS takes ownership of the instance passed to setPostProcessor() and deletes it
    after the run, so a new instance is created for every run. Reusing one instance
    fails on the second run with "wrapped C/C++ object has been deleted".

    The Python side must keep each instance alive until QGIS has called it,
    otherwise the Python object can be garbage-collected while QGIS still holds
    the C++ pointer. Several runs can be pending at the same time (batch mode,
    models with several outputs), so every pending instance is kept, not only
    the most recent one. An instance is released once it has run; instances whose
    C++ object QGIS has already deleted are dropped on the next create().
    """

    _pending: Set["SlopeStylePostProcessor"] = set()

    def postProcessLayer(self, layer: QgsMapLayer, context, feedback) -> None:
        try:
            if isinstance(layer, QgsVectorLayer) and layer.isValid():
                apply_slope_style(layer)
                layer.triggerRepaint()
        finally:
            SlopeStylePostProcessor._pending.discard(self)

    @classmethod
    def create(cls) -> "SlopeStylePostProcessor":
        cls._pending = {item for item in cls._pending if not sip.isdeleted(item)}
        instance = cls()
        cls._pending.add(instance)
        return instance

    @classmethod
    def pending_count(cls) -> int:
        """Number of instances waiting to be called (for tests)."""
        return len(cls._pending)
