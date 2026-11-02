# -*- coding: utf-8 -*-
"""End-to-end tests of the Processing algorithm, styling and plugin (skipped without QGIS).

SPDX-License-Identifier: GPL-3.0-or-later
"""

import unittest

from _bootstrap import HAS_QGIS, plugin_module, qgis_app

if HAS_QGIS:
    from qgis.core import (
        QgsCoordinateReferenceSystem,
        QgsCoordinateTransform,
        QgsFeature,
        QgsGeometry,
        QgsPointXY,
        QgsProcessingContext,
        QgsProcessingFeedback,
        QgsProject,
        QgsRectangle,
        QgsRuleBasedRenderer,
        QgsSettings,
        QgsVectorLayer,
    )
    from qgis.PyQt.QtCore import QMetaType, QVariant

    slope_algorithm = plugin_module("processing.slope_algorithm")
    styling = plugin_module("processing.styling")

X0, Y0 = 500000.0, 5500000.0  # UTM 32N, central Germany


def setUpModule():
    if HAS_QGIS:
        qgis_app()


def memory_layer(name, lines, crs="EPSG:25832", with_group=True):
    uri = f"LineString?crs={crs}" + ("&field=grp:string" if with_group else "")
    layer = QgsVectorLayer(uri, name, "memory")
    features = []
    for points, group in lines:
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPolylineXY([QgsPointXY(x, y) for x, y in points]))
        if with_group:
            feature.setAttributes([group])
        features.append(feature)
    layer.dataProvider().addFeatures(features)
    return layer


class RecordingFeedback(QgsProcessingFeedback if HAS_QGIS else object):
    def __init__(self):
        super().__init__()
        self.warnings = []
        self.errors = []

    def pushWarning(self, warning):  # noqa: N802 (QGIS API name)
        self.warnings.append(warning)

    def reportError(self, error, fatalError=False):  # noqa: N802,N803 (QGIS API names)
        self.errors.append(error)


def run(params, feedback=None):
    """Runs the algorithm; returns (ok, output layer, feedback).

    The output layer is taken out of the processing context, which would delete it
    when it goes out of scope.
    """
    algorithm = slope_algorithm.SlopeHachuresAlgorithm().create()
    context = QgsProcessingContext()
    context.setProject(QgsProject.instance())
    feedback = feedback or RecordingFeedback()
    values = {"INTERVAL": 4.0, "SHORT_RATIO": 50.0, "MAX_SEARCH_DIST": 50.0, "OUTPUT": "memory:"}
    values.update(params)
    results, ok = algorithm.run(values, context, feedback)
    layer = context.takeResultLayer(results["OUTPUT"]) if ok else None
    return ok, layer, feedback


def field_kind(field):
    """Field type as a plain string, for QGIS versions with QVariant or QMetaType types."""
    names = {
        "int64": {QVariant.LongLong, QMetaType.Type.LongLong},
        "string": {QVariant.String, QMetaType.Type.QString},
        "double": {QVariant.Double, QMetaType.Type.Double},
    }
    value = field.type()
    for kind, options in names.items():
        if any(value == option for option in options):
            return kind
    return str(value)


@unittest.skipUnless(HAS_QGIS, "needs QGIS")
class AlgorithmTest(unittest.TestCase):
    def crest_toe(self):
        crest = memory_layer("ok", [([(X0, Y0), (X0 + 100, Y0)], "a")])
        toe = memory_layer("uk", [([(X0, Y0 - 10), (X0 + 100, Y0 - 10)], "a")])
        return crest, toe

    def test_basic_run_and_fields(self):
        crest, toe = self.crest_toe()
        ok, layer, _ = run({"INPUT_OK": crest, "INPUT_UK": toe})
        self.assertTrue(ok)
        self.assertEqual(layer.featureCount(), 51)  # same as version 1.1.2
        kinds = {f.name(): field_kind(f) for f in layer.fields()}
        self.assertEqual(kinds, {
            "ok_fid": "int64", "typ": "string", "station_m": "double",
            "len_gez_m": "double", "len_ges_m": "double", "modus": "string",
        })

    def test_toe_in_other_crs_is_transformed(self):
        crest, _ = self.crest_toe()
        transform = QgsCoordinateTransform(
            QgsCoordinateReferenceSystem("EPSG:25832"), QgsCoordinateReferenceSystem("EPSG:25833"),
            QgsProject.instance(),
        )
        toe_points = []
        for x, y in [(X0, Y0 - 10), (X0 + 100, Y0 - 10)]:
            p = transform.transform(QgsPointXY(x, y))
            toe_points.append((p.x(), p.y()))
        toe = memory_layer("uk33", [(toe_points, "a")], crs="EPSG:25833")
        feedback = RecordingFeedback()
        ok, layer, _ = run({"INPUT_OK": crest, "INPUT_UK": toe}, feedback)
        self.assertTrue(ok, feedback.warnings)
        self.assertEqual(layer.featureCount(), 51)
        self.assertEqual(feedback.warnings, [])

    def test_grouping_uses_matching_toe(self):
        crest = memory_layer("ok", [([(X0, Y0), (X0 + 100, Y0)], "a")])
        toe = memory_layer("uk", [
            ([(X0, Y0 - 5), (X0 + 100, Y0 - 5)], "b"),     # closer, other group
            ([(X0, Y0 - 12), (X0 + 100, Y0 - 12)], "a"),
        ])
        ok, layer, _ = run({"INPUT_OK": crest, "INPUT_UK": toe, "GROUP_FIELD": "grp"})
        self.assertTrue(ok)
        lengths = {round(f["len_ges_m"], 3) for f in layer.getFeatures() if f["typ"] == "lang"}
        self.assertEqual(lengths, {12.0})

    def test_ambiguity_check_with_rounding_overshoot(self):
        """A second toe line in range triggers the ambiguity check. Its last sample
        lies at length * 200 / 200, which exceeds the length by rounding for this
        crest; version 1.1.2 then failed in QGIS 3.22 (null geometry)."""
        n = plugin_module("core.tuning").AMBIGUITY_SAMPLES

        def crest_points(size):
            # diagonal, so that the length has a full mantissa (axis-parallel lines at
            # UTM coordinates have short ones and never round up)
            return [(X0, Y0), (X0 + 0.6 * size, Y0 + 0.8 * size)]

        def length(size):
            return QgsGeometry.fromPolylineXY([QgsPointXY(*p) for p in crest_points(size)]).length()

        size = next(s for s in (100.0 + k * 0.37 for k in range(2000)) if length(s) * n / n > length(s))

        def shifted(offset):
            return [(x - 0.8 * offset, y + 0.6 * offset) for x, y in crest_points(size)]

        crest = memory_layer("ok", [(crest_points(size), "a")])
        toe = memory_layer("uk", [
            (shifted(-10.0), "a"),
            (shifted(30.0), "a"),  # other side, farther: not ambiguous
        ])
        feedback = RecordingFeedback()
        ok, layer, _ = run({"INPUT_OK": crest, "INPUT_UK": toe}, feedback)
        self.assertTrue(ok, feedback.errors)
        self.assertGreater(layer.featureCount(), 0)

    def test_far_toe_outside_window_is_ignored(self):
        crest, _ = self.crest_toe()
        toe = memory_layer("uk", [
            ([(X0, Y0 - 10), (X0 + 100, Y0 - 10)], "a"),
            ([(X0 + 50000, Y0), (X0 + 50100, Y0)], "a"),
        ])
        ok, layer, _ = run({"INPUT_OK": crest, "INPUT_UK": toe})
        self.assertTrue(ok)
        self.assertEqual(layer.featureCount(), 51)

    def test_search_window_helpers(self):
        algorithm = slope_algorithm.SlopeHachuresAlgorithm
        item = slope_algorithm._CrestItem(1, QgsGeometry.fromPolylineXY(
            [QgsPointXY(X0, Y0), QgsPointXY(X0 + 100, Y0)]), None)
        window = algorithm._search_window([item], 50.0)
        self.assertEqual((window.xMinimum(), window.yMinimum(), window.xMaximum(), window.yMaximum()),
                         (X0 - 50, Y0 - 50, X0 + 150, Y0 + 50))
        self.assertIsNone(algorithm._search_window([], 50.0))
        crs32 = QgsCoordinateReferenceSystem("EPSG:25832")
        crs33 = QgsCoordinateReferenceSystem("EPSG:25833")
        same = algorithm._window_in_crs(window, crs32, crs32, QgsProject.instance().transformContext())
        self.assertEqual(same, window)
        other = algorithm._window_in_crs(window, crs32, crs33, QgsProject.instance().transformContext())
        self.assertIsInstance(other, QgsRectangle)
        self.assertNotEqual(other, window)

    def test_too_small_interval_skips_instead_of_aborting(self):
        crest = memory_layer("ok", [([(X0, Y0), (X0 + 60000, Y0)], "a"),
                                    ([(X0, Y0 + 100), (X0 + 100, Y0 + 100)], "a")])
        toe = memory_layer("uk", [([(X0, Y0 - 10), (X0 + 60000, Y0 - 10)], "a"),
                                  ([(X0, Y0 + 90), (X0 + 100, Y0 + 90)], "a")])
        feedback = RecordingFeedback()
        ok, layer, _ = run({"INPUT_OK": crest, "INPUT_UK": toe, "INTERVAL": 0.5}, feedback)
        self.assertTrue(ok)
        self.assertTrue(any("skipped" in w for w in feedback.warnings), feedback.warnings)
        self.assertGreater(layer.featureCount(), 0)  # the second, short crest was still processed

    def test_invalid_crest_is_skipped(self):
        crest = memory_layer("ok", [
            ([(X0, Y0), (X0 + 50, Y0 + 50), (X0 + 50, Y0), (X0, Y0 + 50)], "a"),  # crosses itself
            ([(X0, Y0 + 200), (X0 + 100, Y0 + 200)], "a"),
        ])
        toe = memory_layer("uk", [([(X0, Y0 + 190), (X0 + 100, Y0 + 190)], "a")])
        feedback = RecordingFeedback()
        ok, layer, _ = run({"INPUT_OK": crest, "INPUT_UK": toe}, feedback)
        self.assertTrue(ok)
        self.assertTrue(any("invalid" in w for w in feedback.warnings), feedback.warnings)
        self.assertEqual(layer.featureCount(), 51)

    def test_merged_multipart_crest_that_crosses_itself_is_skipped(self):
        layer = QgsVectorLayer("MultiLineString?crs=EPSG:25832", "ok", "memory")
        feature = QgsFeature(layer.fields())
        pts = [[(0, 0), (10, 0)], [(10, 0), (10, 5), (5, 5), (5, -5)]]
        feature.setGeometry(QgsGeometry.fromMultiPolylineXY(
            [[QgsPointXY(X0 + x, Y0 + y) for x, y in part] for part in pts]))
        layer.dataProvider().addFeatures([feature])
        toe = memory_layer("uk", [([(X0 - 5, Y0 - 10), (X0 + 15, Y0 - 10)], "a")])
        feedback = RecordingFeedback()
        ok, out, _ = run({"INPUT_OK": layer, "INPUT_UK": toe}, feedback)
        self.assertTrue(ok)
        self.assertTrue(any("invalid" in w for w in feedback.warnings), feedback.warnings)
        self.assertEqual(out.featureCount(), 0)

    def test_geographic_crs_is_rejected(self):
        crest = memory_layer("ok", [([(8.0, 50.0), (8.001, 50.0)], "a")], crs="EPSG:4326")
        toe = memory_layer("uk", [([(8.0, 49.9999), (8.001, 49.9999)], "a")], crs="EPSG:4326")
        ok, _, feedback = run({"INPUT_OK": crest, "INPUT_UK": toe})
        self.assertFalse(ok)
        self.assertTrue(any("geographic" in e for e in feedback.errors), feedback.errors)

    def test_canceled_run_returns_quickly(self):
        crest, toe = self.crest_toe()
        feedback = RecordingFeedback()
        feedback.cancel()
        ok, layer, _ = run({"INPUT_OK": crest, "INPUT_UK": toe}, feedback)
        if ok:
            self.assertEqual(layer.featureCount(), 0)

    def test_transform_result_check(self):
        geom = QgsGeometry.fromPointXY(QgsPointXY(X0, Y0))
        transform = QgsCoordinateTransform(
            QgsCoordinateReferenceSystem("EPSG:25832"), QgsCoordinateReferenceSystem("EPSG:25833"),
            QgsProject.instance(),
        )
        self.assertTrue(slope_algorithm._operation_succeeded(geom.transform(transform)))
        self.assertTrue(slope_algorithm._operation_succeeded(0))
        self.assertFalse(slope_algorithm._operation_succeeded(1000))


@unittest.skipUnless(HAS_QGIS, "needs QGIS")
class StylingTest(unittest.TestCase):
    def test_every_pending_post_processor_is_kept_until_it_ran(self):
        cls = styling.SlopeStylePostProcessor
        before = cls.pending_count()
        first, second = cls.create(), cls.create()
        self.assertIsNot(first, second)
        self.assertEqual(cls.pending_count(), before + 2)

        layer = memory_layer("out", [([(0, 0), (1, 0)], "a")], with_group=False)
        first.postProcessLayer(layer, QgsProcessingContext(), QgsProcessingFeedback())
        self.assertIsInstance(layer.renderer(), QgsRuleBasedRenderer)
        self.assertEqual(cls.pending_count(), before + 1)
        second.postProcessLayer(layer, QgsProcessingContext(), QgsProcessingFeedback())
        self.assertEqual(cls.pending_count(), before)


@unittest.skipUnless(HAS_QGIS, "needs QGIS")
class PluginTest(unittest.TestCase):
    def test_menu_is_translated(self):
        settings = QgsSettings()
        saved = (settings.value("locale/overrideFlag"), settings.value("locale/userLocale"))
        settings.setValue("locale/overrideFlag", True)
        settings.setValue("locale/userLocale", "de_DE")
        try:
            plugin = plugin_module("plugin").BoeschungPlugin(None)
            try:
                self.assertEqual(plugin.menu_name, "&Böschungsschraffen")
            finally:
                plugin.unload()
        finally:
            settings.setValue("locale/overrideFlag", saved[0] if saved[0] is not None else False)
            settings.setValue("locale/userLocale", saved[1] if saved[1] is not None else "")


if __name__ == "__main__":
    unittest.main()
