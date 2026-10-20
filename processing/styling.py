# -*- coding: utf-8 -*-
"""
Standard cartographic symbology for slope hachures.

The post-processor is a module-level singleton. Its Python object therefore
stays alive for as long as the module is loaded, while QGIS uses it.

SPDX-License-Identifier: GPL-3.0-or-later
"""

from typing import Optional

from qgis.core import (
    QgsLineSymbol,
    QgsMapLayer,
    QgsProcessingLayerPostProcessorInterface,
    QgsRuleBasedRenderer,
    QgsVectorLayer,
)
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
    after the run. Therefore a new instance is created for every run. Reusing one
    instance fails on the second run with "wrapped C/C++ object has been deleted".
    """

    instance: Optional["SlopeStylePostProcessor"] = None  # reference to the current run's instance

    def postProcessLayer(self, layer: QgsMapLayer, context, feedback) -> None:
        if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
            return
        apply_slope_style(layer)
        layer.triggerRepaint()

    @classmethod
    def create(cls) -> "SlopeStylePostProcessor":
        cls.instance = cls()
        return cls.instance


