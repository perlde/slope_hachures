# -*- coding: utf-8 -*-
"""
QGIS Processing Algorithm for generating cartographic slope hachures.
Handles CRS validation, spatial indexing, and automated layer post-processing.

Part of the Slope Hachures QGIS Plugin.
SPDX-License-Identifier: GPL-3.0-or-later
"""

from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.PyQt.QtGui import QIcon
from qgis.core import (
    QgsApplication,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterNumber,
    QgsProcessingParameterField,
    QgsProcessingParameterFeatureSink,
    QgsProcessingLayerPostProcessorInterface,
    QgsFeatureSink,
    QgsFeature,
    QgsFields,
    QgsField,
    QgsWkbTypes,
    QgsGeometry,
    QgsSpatialIndex,
    QgsRuleBasedRenderer,
    QgsLineSymbol
)

from ..core.slope_engine import SlopeEngine


# Integriertes Wörterbuch für automatische deutsche Übersetzung
I18N_DE = {
    'Generate Slope Hachures (OKSTRA / RE 2012)': 'Böschungsschraffen erzeugen (OKSTRA / RE 2012)',
    'Terrain & Tracing': 'Gelände & Trassierung',
    'Crest line / Top of slope (Kamm)': 'Böschungsoberkante (Kamm)',
    'Toe line / Bottom of slope (Fuß)': 'Böschungsunterkante (Fuß)',
    'Valleys / Breaklines / Corners (optional)': 'Kehlen / Eck-Diagonalen (optional)',
    'Grouping attribute field (optional)': 'Gruppierungs-Attribut (optional)',
    'Interval between long hatches [m]': 'Abstand der langen Schraffen [m]',
    'Length of short hatches [%]': 'Länge der kurzen Schraffen [%]',
    'Maximum search distance [m]': 'Maximale Suchlänge [m]',
    'Slope plan (Hachures & Breaklines)': 'Böschungsplan (Schraffen & Kehlen)',
    'Invalid crest or toe layer.': 'Ober- oder Unterkantenlayer ungültig.',
    'Could not create output sink.': 'Ausgabelayer konnte nicht angelegt werden.',
    'Done: {count} elements created.': 'Fertig: {count} Elemente erzeugt.',
    'Long hatch': 'Lange Schraffe',
    'Short hatch': 'Kurze Schraffe',
    'Valley / Breakline (OKSTRA 0486)': 'Kehle / Bruchkante (OKSTRA 0486)',
}


class SlopeStylePostProcessor(QgsProcessingLayerPostProcessorInterface):
    """
    Applies the standardized cartographic slope styling on layer completion.
    """
    instance = None

    def __init__(self):
        super().__init__()

    def postProcessLayer(self, layer, context, feedback):
        if not layer or not layer.isValid():
            return

        self._apply_native_slope_style(layer)
        layer.triggerRepaint()

    def _apply_native_slope_style(self, layer):
        root_rule = QgsRuleBasedRenderer.Rule(None)
        is_de = QgsApplication.locale().startswith('de')

        lbl_lang = 'Lange Schraffe' if is_de else 'Long hatch'
        lbl_kurz = 'Kurze Schraffe' if is_de else 'Short hatch'
        lbl_kehle = 'Kehle (OKSTRA 0486)' if is_de else 'Valley (OKSTRA 0486)'

        # 1. Long hatch (Earth brown 0.22 mm)
        sym_lang = QgsLineSymbol.createSimple({'color': '110,65,30,255', 'width': '0.22'})
        rule_lang = QgsRuleBasedRenderer.Rule(sym_lang, 0, 0, '"typ" = \'lang\'', lbl_lang)
        root_rule.appendChild(rule_lang)

        # 2. Short hatch (Earth brown 0.18 mm)
        sym_kurz = QgsLineSymbol.createSimple({'color': '110,65,30,255', 'width': '0.18'})
        rule_kurz = QgsRuleBasedRenderer.Rule(sym_kurz, 0, 0, '"typ" = \'kurz\'', lbl_kurz)
        root_rule.appendChild(rule_kurz)

        # 3. Valley / Corner breakline (Dark brown 0.35 mm)
        sym_kehle = QgsLineSymbol.createSimple({'color': '70,40,15,255', 'width': '0.35'})
        rule_kehle = QgsRuleBasedRenderer.Rule(sym_kehle, 0, 0, '"typ" = \'kehle\'', lbl_kehle)
        root_rule.appendChild(rule_kehle)

        layer.setRenderer(QgsRuleBasedRenderer(root_rule))

    @classmethod
    def create(cls) -> 'SlopeStylePostProcessor':
        cls.instance = cls()
        return cls.instance


class SlopeHachuresAlgorithm(QgsProcessingAlgorithm):
    INPUT_OK = 'INPUT_OK'
    INPUT_UK = 'INPUT_UK'
    INPUT_KEHLEN = 'INPUT_KEHLEN'
    GROUP_FIELD = 'GROUP_FIELD'
    INTERVAL = 'INTERVAL'
    SHORT_RATIO = 'SHORT_RATIO'
    MAX_SEARCH_DIST = 'MAX_SEARCH_DIST'
    OUTPUT = 'OUTPUT'

    def __init__(self):
        super().__init__()
        self.dest_id = None

    def tr(self, string: str) -> str:
        translated = QCoreApplication.translate('SlopeHachuresAlgorithm', string)
        if translated != string:
            return translated
        if QgsApplication.locale().startswith('de'):
            return I18N_DE.get(string, string)
        return string

    def createInstance(self):
        return SlopeHachuresAlgorithm()

    def name(self) -> str:
        return 'generate_slope_hachures'

    def displayName(self) -> str:
        return self.tr('Generate Slope Hachures (OKSTRA / RE 2012)')

    def group(self) -> str:
        return self.tr('Terrain & Tracing')

    def groupId(self) -> str:
        return 'terrain_tracing'

    def icon(self) -> QIcon:
        import os
        plugin_dir = os.path.dirname(os.path.dirname(__file__))
        icon_path = os.path.join(plugin_dir, 'icon.svg')
        if os.path.exists(icon_path):
            return QIcon(icon_path)
        return super().icon()

    def shortHelpString(self) -> str:
        if QgsApplication.locale().startswith('de'):
            return (
                '<h3>Professionelle Böschungsschraffen (OKSTRA / RE 2012 / DIN 2425)</h3>'
                '<p>Erzeugt normgerechte Böschungspläne mit automatischer Standard-Symbolik '
                '(Erdbraun), Kreuzungsschutz und millimetergenauer Kehlenbegrenzung.</p>'
                '<h4>Empfohlene Schraffenabstände nach Planmaßstab:</h4>'
                '<table border="1" cellpadding="4" cellspacing="0" style="border-collapse:collapse; width:100%;">'
                '  <tr style="background-color:#eee;"><th>Druckmaßstab</th><th>Einsatzzweck</th><th>Empf. Abstand</th></tr>'
                '  <tr><td><b>1 : 250</b></td><td>Detail- / Baugrubenplan</td><td><b>1.0 – 1.5 m</b></td></tr>'
                '  <tr><td><b>1 : 500</b></td><td>Standard-Lageplan / Erdbau</td><td><b>2.0 – 3.0 m</b></td></tr>'
                '  <tr><td><b>1 : 1000</b></td><td>Übersichts- / Trassenplan</td><td><b>4.0 – 5.0 m</b></td></tr>'
                '</table>'
                '<h4>Praxistipps für die Planerstellung:</h4>'
                '<ul>'
                '  <li><b>Baugruben:</b> Zeichne an den 4 Grubenecken diagonale Linien im Kehlen-Layer '
                '      (von Außenecke zu Innenecke). Das Werkzeug trennt die Böschungswände dort absolut überschneidungsfrei.</li>'
                '  <li><b>Kantenüberhänge:</b> Wenn die Oberkante länger ist als die Unterkante, setze an der Flanke '
                '      eine Randkehle, um überstehende Schraffen sauber abzufangen.</li>'
                '  <li><b>Mehrstufige Böschungen (Bermen):</b> Berechne gestufte Hänge nacheinander '
                '      (1. Durchlauf: Kamm &rarr; Berme; 2. Durchlauf: Berme &rarr; Sohle).</li>'
                '  <li><b>Koordinatensystem:</b> Layer müssen zwingend in einem metrischen System (z. B. UTM EPSG:25832) vorliegen.</li>'
                '</ul>'
            )
        return (
            '<h3>Professional Slope Hachures (Talud / Embankment Ticks)</h3>'
            '<p>Generates standardized engineering slope hachures with automatic cartographic styling, '
            'collision-free curve handling, and breakline boundary support (OKSTRA 0486).</p>'
            '<h4>Recommended Spacing by Map Scale:</h4>'
            '<table border="1" cellpadding="4" cellspacing="0" style="border-collapse:collapse; width:100%;">'
            '  <tr style="background-color:#eee;"><th>Print Scale</th><th>Application</th><th>Rec. Interval</th></tr>'
            '  <tr><td><b>1 : 250</b></td><td>Excavation pits / Site details</td><td><b>1.0 – 1.5 m</b></td></tr>'
            '  <tr><td><b>1 : 500</b></td><td>Standard site & grading plans</td><td><b>2.0 – 3.0 m</b></td></tr>'
            '  <tr><td><b>1 : 1000</b></td><td>Overview / Road alignment</td><td><b>4.0 – 5.0 m</b></td></tr>'
            '</table>'
            '<h4>Practical Tips:</h4>'
            '<ul>'
            '  <li><b>Excavation Pits:</b> Draw corner diagonals in the breakline layer (from outer to inner corners). '
            '      The tool cleanly separates slope faces without crossing artifacts.</li>'
            '  <li><b>Terraced Slopes (Berms):</b> Calculate multi-level embankments stepwise '
            '      (Step 1: Crest &rarr; Berm; Step 2: Berm &rarr; Toe).</li>'
            '  <li><b>Coordinate System:</b> Layers must use a projected metric CRS (e.g., UTM / Gauß-Krüger).</li>'
            '</ul>'
        )

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT_OK,
                self.tr('Crest line / Top of slope (Kamm)'),
                [QgsProcessing.SourceType.TypeVectorLine]
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT_UK,
                self.tr('Toe line / Bottom of slope (Fuß)'),
                [QgsProcessing.SourceType.TypeVectorLine]
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT_KEHLEN,
                self.tr('Valleys / Breaklines / Corners (optional)'),
                [QgsProcessing.SourceType.TypeVectorLine],
                optional=True
            )
        )
        self.addParameter(
            QgsProcessingParameterField(
                self.GROUP_FIELD,
                self.tr('Grouping attribute field (optional)'),
                parentLayerParameterName=self.INPUT_OK,
                optional=True
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.INTERVAL,
                self.tr('Interval between long hatches [m]'),
                type=QgsProcessingParameterNumber.Type.Double,
                defaultValue=4.0,
                minValue=0.1
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.SHORT_RATIO,
                self.tr('Length of short hatches [%]'),
                type=QgsProcessingParameterNumber.Type.Double,
                defaultValue=50.0,
                minValue=1.0,
                maxValue=99.0
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.MAX_SEARCH_DIST,
                self.tr('Maximum search distance [m]'),
                type=QgsProcessingParameterNumber.Type.Double,
                defaultValue=50.0,
                minValue=0.5
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT,
                self.tr('Slope plan (Hachures & Breaklines)'),
                QgsProcessing.SourceType.TypeVectorLine
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        ok_source = self.parameterAsSource(parameters, self.INPUT_OK, context)
        uk_source = self.parameterAsSource(parameters, self.INPUT_UK, context)
        kehlen_source = self.parameterAsSource(parameters, self.INPUT_KEHLEN, context)
        group_field = self.parameterAsString(parameters, self.GROUP_FIELD, context)
        interval = self.parameterAsDouble(parameters, self.INTERVAL, context)
        short_pct = self.parameterAsDouble(parameters, self.SHORT_RATIO, context)
        max_dist = self.parameterAsDouble(parameters, self.MAX_SEARCH_DIST, context)

        if ok_source is None or uk_source is None:
            raise QgsProcessingException(self.tr('Invalid crest or toe layer.'))

        # CRS validation: metric projection required
        ok_crs = ok_source.sourceCrs()
        if ok_crs.isGeographic():
            msg = (
                f"Der Oberkantenlayer '{ok_source.sourceName()}' verwendet ein geographisches "
                f"Koordinatensystem ({ok_crs.authid()}) in Grad.\n\n"
                "Böschungsschraffen erfordern ein projiziertes, metrisches System (z. B. UTM EPSG:25832)."
                if QgsApplication.locale().startswith('de') else
                f"The crest layer '{ok_source.sourceName()}' uses a geographic coordinate reference system "
                f"({ok_crs.authid()}) in degrees.\n\n"
                "Slope hachures require a projected, metric coordinate system (e.g. UTM / Gauß-Krüger)."
            )
            raise QgsProcessingException(msg)

        uk_crs = uk_source.sourceCrs()
        if uk_crs.isGeographic():
            msg = (
                f"Der Unterkantenlayer '{uk_source.sourceName()}' verwendet ein geographisches KBS in Grad."
                if QgsApplication.locale().startswith('de') else
                f"The toe layer '{uk_source.sourceName()}' uses a geographic coordinate reference system in degrees."
            )
            raise QgsProcessingException(msg)

        fields = QgsFields()
        fields.append(QgsField('ok_fid', QVariant.LongLong))
        fields.append(QgsField('typ', QVariant.String))  # 'lang', 'kurz', 'kehle'
        fields.append(QgsField('station_m', QVariant.Double))
        fields.append(QgsField('len_gez_m', QVariant.Double))
        fields.append(QgsField('len_ges_m', QVariant.Double))
        fields.append(QgsField('modus', QVariant.String))

        sink, self.dest_id = self.parameterAsSink(
            parameters,
            self.OUTPUT,
            context,
            fields,
            QgsWkbTypes.Type.LineString,
            ok_crs
        )
        if sink is None:
            raise QgsProcessingException(self.tr('Could not create output sink.'))

        if context.willLoadLayerOnCompletion(self.dest_id):
            context.layerToLoadOnCompletionDetails(self.dest_id).setPostProcessor(
                SlopeStylePostProcessor.create()
            )

        uk_features = {f.id(): f for f in uk_source.getFeatures() if f.hasGeometry() and not f.geometry().isEmpty()}
        uk_index = QgsSpatialIndex()
        for f in uk_features.values():
            uk_index.addFeature(f)

        kehlen_features = {}
        kehlen_index = None
        if kehlen_source is not None:
            kehlen_features = {f.id(): f for f in kehlen_source.getFeatures() if f.hasGeometry() and not f.geometry().isEmpty()}
            kehlen_index = QgsSpatialIndex()
            for f in kehlen_features.values():
                kehlen_index.addFeature(f)

        engine = SlopeEngine(
            interval=interval,
            short_ratio=short_pct / 100.0,
            max_search_dist=max_dist
        )

        ok_count = ok_source.featureCount()
        total_steps = ok_count if ok_count > 0 else 1
        created_count = 0
        written_kehlen_ids = set()

        for current_idx, ok_feat in enumerate(ok_source.getFeatures()):
            if feedback.isCanceled():
                break

            if not ok_feat.hasGeometry() or ok_feat.geometry().isEmpty():
                continue

            ok_geom = ok_feat.geometry()
            search_box = ok_geom.boundingBox()
            search_box.grow(max_dist)

            candidate_uk_ids = uk_index.intersects(search_box)
            matched_candidates = []

            for uid in candidate_uk_ids:
                uk_cand = uk_features[uid]
                if group_field and ok_feat[group_field] != uk_cand[group_field]:
                    continue

                d = ok_geom.distance(uk_cand.geometry())
                if d <= max_dist:
                    matched_candidates.append((d, uk_cand.geometry()))

            if not matched_candidates:
                continue

            matched_candidates.sort(key=lambda item: item[0])
            primary_uk_geom = matched_candidates[0][1]

            connected_chain = [primary_uk_geom]
            for _, other_geom in matched_candidates[1:]:
                if any(other_geom.distance(c) < 0.05 for c in connected_chain):
                    connected_chain.append(other_geom)

            local_uk_geom = (
                connected_chain[0] if len(connected_chain) == 1
                else QgsGeometry.unaryUnion(connected_chain)
            )

            local_kehlen_geoms = []
            local_kehlen_objs = []
            if kehlen_index is not None:
                candidate_kehl_ids = kehlen_index.intersects(search_box)
                for kid in candidate_kehl_ids:
                    k_cand = kehlen_features[kid]
                    if ok_geom.distance(k_cand.geometry()) <= max_dist:
                        local_kehlen_geoms.append(k_cand.geometry())
                        local_kehlen_objs.append((kid, k_cand.geometry()))

            results = engine.compute_hachures(
                ok_geom=ok_geom,
                uk_geom=local_uk_geom,
                kehlen_geoms=local_kehlen_geoms
            )

            for item in results:
                f = QgsFeature(fields)
                f.setGeometry(item.geometry)
                f.setAttributes([
                    ok_feat.id(),
                    item.hachure_type,
                    item.station,
                    item.length,
                    item.full_length,
                    item.mode
                ])
                sink.addFeature(f, QgsFeatureSink.Flag.FastInsert)
                created_count += 1

            for kid, k_geom in local_kehlen_objs:
                if kid not in written_kehlen_ids:
                    k_feat = QgsFeature(fields)
                    k_feat.setGeometry(k_geom)
                    k_feat.setAttributes([
                        ok_feat.id(),
                        'kehle',
                        0.0,
                        round(k_geom.length(), 3),
                        round(k_geom.length(), 3),
                        'okstra_0486'
                    ])
                    sink.addFeature(k_feat, QgsFeatureSink.Flag.FastInsert)
                    written_kehlen_ids.add(kid)
                    created_count += 1

            feedback.setProgress(int((current_idx / total_steps) * 100))

        feedback.pushInfo(self.tr('Done: {count} elements created.').format(count=created_count))
        return {self.OUTPUT: self.dest_id}