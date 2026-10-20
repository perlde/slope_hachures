# -*- coding: utf-8 -*-
"""
Processing algorithm "Generate Slope Hachures".

Handles parameters, input validation, CRS alignment, feature I/O and output.
The geometry is computed in core.slope_engine.

SPDX-License-Identifier: GPL-3.0-or-later
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsFeatureSink,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingFeatureSource,
    QgsProcessingFeedback,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterNumber,
    QgsSpatialIndex,
    QgsUnitTypes,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.PyQt.QtGui import QIcon

from ..common import is_german_locale, plugin_icon
from ..constants import ALGORITHM_ID
from ..core.geometry_utils import has_self_intersection
from ..core.slope_engine import SlopeEngine
from ..core.tuning import (
    AMBIGUITY_SAMPLES,
    CHAIN_TOLERANCE,
    MAX_SEGMENTS_PER_CREST,
    MAX_SHORT_RATIO,
    MIN_INTERVAL,
    MIN_SEARCH_DIST,
    MIN_SHORT_RATIO,
)
from .styling import SlopeStylePostProcessor


@dataclass(frozen=True)
class _IndexedLine:
    """A line in the lookup. Its key is a sequential number, not the source feature ID."""

    key: int
    geometry: QgsGeometry
    group: Any
    source_id: int


@dataclass(frozen=True)
class _LineIndex:
    items: Dict[int, _IndexedLine]
    index: QgsSpatialIndex


class SlopeHachuresAlgorithm(QgsProcessingAlgorithm):
    """Generates slope hachures from crest, toe and optional breakline layers."""

    INPUT_OK = "INPUT_OK"
    INPUT_UK = "INPUT_UK"
    INPUT_KEHLEN = "INPUT_KEHLEN"
    GROUP_FIELD = "GROUP_FIELD"
    INTERVAL = "INTERVAL"
    SHORT_RATIO = "SHORT_RATIO"
    MAX_SEARCH_DIST = "MAX_SEARCH_DIST"
    OUTPUT = "OUTPUT"

    FIELD_OK_FID = "ok_fid"
    FIELD_TYP = "typ"
    FIELD_STATION = "station_m"
    FIELD_LEN_GEZ = "len_gez_m"
    FIELD_LEN_GES = "len_ges_m"
    FIELD_MODUS = "modus"

    # ------------------------------------------------------------- metadata
    def createInstance(self) -> "SlopeHachuresAlgorithm":
        return SlopeHachuresAlgorithm()

    def name(self) -> str:
        return ALGORITHM_ID

    def tr(self, string: str) -> str:
        return QCoreApplication.translate("SlopeHachuresAlgorithm", string)

    def displayName(self) -> str:
        return self.tr("Generate Slope Hachures (OKSTRA / RE 2012)")

    def group(self) -> str:
        return self.tr("Terrain & Tracing")

    def groupId(self) -> str:
        return "terrain_tracing"

    def icon(self) -> QIcon:
        return plugin_icon()

    def shortHelpString(self) -> str:
        if is_german_locale():
            return (
                "<h3>Professionelle Böschungsschraffen (OKSTRA / RE 2012 / DIN 2425)</h3>"
                "<p>Erzeugt normgerechte Böschungspläne mit automatischer Standard-Symbolik "
                "(Erdbraun), Überschneidungsvermeidung und Kehlenbegrenzung.</p>"
                "<h4>Empfohlene Schraffenabstände nach Planmaßstab:</h4>"
                "<table border=\"1\" cellpadding=\"4\" cellspacing=\"0\" "
                "style=\"border-collapse:collapse; width:100%;\">"
                "  <tr style=\"background-color:#eee;\"><th>Druckmaßstab</th>"
                "<th>Einsatzzweck</th><th>Empf. Abstand</th></tr>"
                "  <tr><td><b>1 : 250</b></td><td>Detail- / Baugrubenplan</td>"
                "<td><b>1.0 – 1.5 m</b></td></tr>"
                "  <tr><td><b>1 : 500</b></td><td>Standard-Lageplan / Erdbau</td>"
                "<td><b>2.0 – 3.0 m</b></td></tr>"
                "  <tr><td><b>1 : 1000</b></td><td>Übersichts- / Trassenplan</td>"
                "<td><b>4.0 – 5.0 m</b></td></tr>"
                "</table>"
                "<h4>Praxistipps für die Planerstellung:</h4>"
                "<ul>"
                "  <li><b>Baugruben:</b> Zeichne an den 4 Grubenecken diagonale Linien "
                "      im Kehlen-Layer (von Außenecke zu Innenecke). Das Werkzeug setzt "
                "      die Böschungswände dort ohne Überschneidungen an.</li>"
                "  <li><b>Kantenüberhänge:</b> Trifft eine senkrecht zum Kamm gezogene "
                "      Schraffe die Unterkante nicht mehr, weil diese vorher endet, setze an "
                "      dieser Stelle eine Randkehle. Ohne Kehle können Schraffen dort falsch verlaufen.</li>"
                "  <li><b>Mehrstufige Böschungen (Bermen):</b> Berechne gestufte Hänge "
                "      nacheinander (1. Durchlauf: Kamm &rarr; Berme; "
                "      2. Durchlauf: Berme &rarr; Sohle).</li>"
                "  <li><b>Koordinatensystem:</b> Alle Layer sollten in einem metrischen "
                "      System vorliegen (z. B. UTM EPSG:25832). Abweichende Systeme werden "
                "      automatisch transformiert.</li>"
                "</ul>"
            )
        return (
            "<h3>Professional Slope Hachures (Talud / Embankment Ticks)</h3>"
            "<p>Generates standardized engineering slope hachures with automatic "
            "cartographic styling, overlap reduction and breakline boundary "
            "support (OKSTRA 0486).</p>"
            "<h4>Recommended Spacing by Map Scale:</h4>"
            "<table border=\"1\" cellpadding=\"4\" cellspacing=\"0\" "
            "style=\"border-collapse:collapse; width:100%;\">"
            "  <tr style=\"background-color:#eee;\"><th>Print Scale</th>"
            "<th>Application</th><th>Rec. Interval</th></tr>"
            "  <tr><td><b>1 : 250</b></td><td>Excavation pits / Site details</td>"
            "<td><b>1.0 – 1.5 m</b></td></tr>"
            "  <tr><td><b>1 : 500</b></td><td>Standard site & grading plans</td>"
            "<td><b>2.0 – 3.0 m</b></td></tr>"
            "  <tr><td><b>1 : 1000</b></td><td>Overview / Road alignment</td>"
            "<td><b>4.0 – 5.0 m</b></td></tr>"
            "</table>"
            "<h4>Practical Tips:</h4>"
            "<ul>"
            "  <li><b>Excavation Pits:</b> Draw corner diagonals in the breakline layer "
            "      (from outer to inner corners). The tool sets the slope faces "
            "      without overlapping hachures.</li>"
            "  <li><b>Terraced Slopes (Berms):</b> Calculate multi-level embankments "
            "      stepwise (Step 1: Crest &rarr; Berm; Step 2: Berm &rarr; Toe).</li>"
            "  <li><b>Edge overhangs:</b> If a hachure drawn perpendicular to the crest no longer "
            "      meets the toe line because the toe line ends earlier, place a breakline (Randkehle) "
            "      there. Without it, hachures can run incorrectly.</li>"
            "  <li><b>Coordinate System:</b> Layers should use a projected metric CRS "
            "      (e.g., UTM / Gauß-Krüger). Other systems are transformed automatically.</li>"
            "</ul>"
        )

    # ------------------------------------------------------------ parameters
    def initAlgorithm(self, config=None) -> None:
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.INPUT_OK,
            self.tr("Crest line / Top of slope (Kamm)"),
            [QgsProcessing.SourceType.TypeVectorLine],
        ))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.INPUT_UK,
            self.tr("Toe line / Bottom of slope (Fuß)"),
            [QgsProcessing.SourceType.TypeVectorLine],
        ))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.INPUT_KEHLEN,
            self.tr("Valleys / Breaklines / Corners (optional)"),
            [QgsProcessing.SourceType.TypeVectorLine],
            optional=True,
        ))
        self.addParameter(QgsProcessingParameterField(
            self.GROUP_FIELD,
            self.tr("Grouping attribute field (optional)"),
            parentLayerParameterName=self.INPUT_OK,
            optional=True,
        ))
        self.addParameter(QgsProcessingParameterNumber(
            self.INTERVAL,
            self.tr("Interval between long hatches [m]"),
            type=QgsProcessingParameterNumber.Type.Double,
            defaultValue=4.0,
            minValue=MIN_INTERVAL,
        ))
        self.addParameter(QgsProcessingParameterNumber(
            self.SHORT_RATIO,
            self.tr("Length of short hatches [%]"),
            type=QgsProcessingParameterNumber.Type.Double,
            defaultValue=50.0,
            minValue=MIN_SHORT_RATIO * 100.0,
            maxValue=MAX_SHORT_RATIO * 100.0,
        ))
        self.addParameter(QgsProcessingParameterNumber(
            self.MAX_SEARCH_DIST,
            self.tr("Maximum search distance [m]"),
            type=QgsProcessingParameterNumber.Type.Double,
            defaultValue=50.0,
            minValue=MIN_SEARCH_DIST,
        ))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT,
            self.tr("Slope plan (Hachures & Breaklines)"),
            QgsProcessing.SourceType.TypeVectorLine,
        ))

    # --------------------------------------------------------------- process
    def processAlgorithm(
        self,
        parameters,
        context,
        feedback: QgsProcessingFeedback,
    ):
        ok_source = self.parameterAsSource(parameters, self.INPUT_OK, context)
        uk_source = self.parameterAsSource(parameters, self.INPUT_UK, context)
        kehlen_source = self.parameterAsSource(parameters, self.INPUT_KEHLEN, context)
        if ok_source is None:
            raise QgsProcessingException(self.tr("Invalid crest layer (INPUT_OK)."))
        if uk_source is None:
            raise QgsProcessingException(self.tr("Invalid toe layer (INPUT_UK)."))

        role_crest = self.tr("Crest")
        role_toe = self.tr("Toe")
        role_kehle = self.tr("Breakline")

        ok_crs = self._require_metric_crs(ok_source, role_crest)
        self._require_metric_crs(uk_source, role_toe)
        if kehlen_source is not None:
            self._require_metric_crs(kehlen_source, role_kehle)

        interval = self.parameterAsDouble(parameters, self.INTERVAL, context)
        short_pct = self.parameterAsDouble(parameters, self.SHORT_RATIO, context)
        max_dist = self.parameterAsDouble(parameters, self.MAX_SEARCH_DIST, context)
        group_field = self.parameterAsString(parameters, self.GROUP_FIELD, context) or ""

        ok_group_idx = self._group_index(ok_source, group_field, role_crest)
        uk_group_idx = self._group_index(uk_source, group_field, role_toe)

        fields = self._build_output_fields()
        sink, dest_id = self.parameterAsSink(
            parameters, self.OUTPUT, context, fields,
            QgsWkbTypes.Type.LineString, ok_crs,
        )
        if sink is None:
            raise QgsProcessingException(self.tr("Could not create output sink."))
        if context.willLoadLayerOnCompletion(dest_id):
            context.layerToLoadOnCompletionDetails(dest_id).setPostProcessor(
                SlopeStylePostProcessor.create()
            )

        transform_ctx = context.transformContext()
        uk_index = self._build_index(
            uk_source, uk_group_idx, ok_crs, transform_ctx, feedback, role_toe,
        )
        if kehlen_source is not None:
            kehlen_index = self._build_index(
                kehlen_source, -1, ok_crs, transform_ctx, feedback, role_kehle,
            )
        else:
            kehlen_index = _LineIndex({}, QgsSpatialIndex())

        engine = SlopeEngine(
            interval=interval,
            short_ratio=short_pct / 100.0,
            max_search_dist=max_dist,
        )

        total = ok_source.featureCount()
        created = 0
        written_kehlen: Set[int] = set()

        for position, ok_feat in enumerate(ok_source.getFeatures()):
            if feedback.isCanceled():
                break
            if total > 0:
                feedback.setProgress(min(99, int(100.0 * position / total)))
            if not ok_feat.hasGeometry():
                continue
            ok_geom = ok_feat.geometry()
            if ok_geom.isEmpty() or not ok_geom.isGeosValid() or has_self_intersection(ok_geom):
                feedback.pushWarning(self.tr(
                    "Skipping invalid crest feature ID {}."
                ).format(ok_feat.id()))
                continue

            ok_fid = int(ok_feat.id())
            ok_group = ok_feat.attributes()[ok_group_idx] if ok_group_idx >= 0 else None

            for part in self._linear_parts(ok_geom):
                if part.length() / interval > MAX_SEGMENTS_PER_CREST:
                    raise QgsProcessingException(self.tr(
                        "Interval too small for crest feature ID {}: "
                        "more than {} stations would be created."
                    ).format(ok_fid, MAX_SEGMENTS_PER_CREST))
                created += self._process_part(
                    sink, fields, engine, part, ok_fid, ok_group,
                    uk_index, kehlen_index, group_field, max_dist,
                    written_kehlen, feedback,
                )

        feedback.pushInfo(self.tr("Done: {count} elements created.").format(count=created))
        return {self.OUTPUT: dest_id}

    # ----------------------------------------------------------- per crest part
    def _process_part(
        self,
        sink,
        fields: QgsFields,
        engine: SlopeEngine,
        part: QgsGeometry,
        ok_fid: int,
        ok_group: Any,
        uk_index: _LineIndex,
        kehlen_index: _LineIndex,
        group_field: str,
        max_dist: float,
        written_kehlen: Set[int],
        feedback: QgsProcessingFeedback,
    ) -> int:
        """Computes the hachures of one crest part and writes them. Returns the count."""
        uk_geom, reason = self._resolve_local_uk(
            part, ok_fid, ok_group, uk_index, group_field, max_dist, feedback,
        )
        if uk_geom is None:
            feedback.pushWarning(self._reason_message(reason, ok_fid))
            return 0

        kehlen_hits = self._resolve_local_kehlen(part, kehlen_index, max_dist)
        results = engine.compute_hachures(
            ok_geom=part,
            uk_geom=uk_geom,
            kehlen_geoms=[hit.geometry for hit in kehlen_hits],
            feedback=feedback,
        )

        written = 0
        for item in results:
            self._write(sink, fields, item.geometry, [
                ok_fid,
                item.hachure_type,
                float(item.station),
                float(item.length),
                float(item.full_length),
                item.mode.value,
            ])
            written += 1

        for hit in kehlen_hits:
            if hit.key in written_kehlen:
                continue
            k_len = float(hit.geometry.length())
            self._write(sink, fields, hit.geometry, [
                ok_fid, "kehle", 0.0, k_len, k_len, "okstra_0486",
            ])
            written_kehlen.add(hit.key)
            written += 1
        return written

    # ----------------------------------------------------------- helpers
    def _require_metric_crs(
        self,
        source: QgsProcessingFeatureSource,
        role: str,
    ) -> QgsCoordinateReferenceSystem:
        crs = source.sourceCrs()
        name = source.sourceName()
        if not crs.isValid():
            raise QgsProcessingException(self.tr(
                "Layer '{}' ({}) has no coordinate reference system."
            ).format(name, role))
        if crs.isGeographic():
            raise QgsProcessingException(self.tr(
                "Layer '{}' ({}) uses a geographic CRS ({}). Slope hachures require "
                "a projected, metric CRS (e.g. UTM / Gauß-Krüger)."
            ).format(name, role, crs.authid()))
        if crs.mapUnits() != QgsUnitTypes.DistanceUnit.DistanceMeters:
            raise QgsProcessingException(self.tr(
                "Layer '{}' ({}) uses CRS units other than meters ({}). "
                "Please reproject to a metric CRS."
            ).format(name, role, crs.mapUnits()))
        return crs

    def _group_index(
        self,
        source: QgsProcessingFeatureSource,
        group_field: str,
        role: str,
    ) -> int:
        if not group_field:
            return -1
        index = source.fields().lookupField(group_field)
        if index < 0:
            raise QgsProcessingException(self.tr(
                "Grouping field '{}' not found in layer '{}' ({})."
            ).format(group_field, source.sourceName(), role))
        return index

    def _build_index(
        self,
        source: QgsProcessingFeatureSource,
        group_idx: int,
        target_crs: QgsCoordinateReferenceSystem,
        transform_context,
        feedback: QgsProcessingFeedback,
        role: str,
    ) -> _LineIndex:
        """Loads lines, transforms them to the target CRS if needed, and indexes them.

        Index keys are sequential numbers, so empty or duplicate source IDs
        cannot overwrite each other.
        """
        transform: Optional[QgsCoordinateTransform] = None
        if source.sourceCrs() != target_crs:
            transform = QgsCoordinateTransform(source.sourceCrs(), target_crs, transform_context)

        items: Dict[int, _IndexedLine] = {}
        index = QgsSpatialIndex()
        for feat in source.getFeatures():
            if feedback.isCanceled():
                break
            if not feat.hasGeometry():
                continue
            geom = feat.geometry()
            if geom.isEmpty():
                continue
            if transform is not None and geom.transform(transform) != 0:
                raise QgsProcessingException(self.tr(
                    "Coordinate transformation failed for layer '{}' ({}), feature {}."
                ).format(source.sourceName(), role, feat.id()))
            if not geom.isGeosValid() or has_self_intersection(geom):
                feedback.pushWarning(self.tr(
                    "Skipping invalid feature ID {} in layer '{}'."
                ).format(feat.id(), source.sourceName()))
                continue

            key = len(items)
            group = feat.attributes()[group_idx] if group_idx >= 0 else None
            items[key] = _IndexedLine(key, geom, group, int(feat.id()))

            indexed = QgsFeature(key)
            indexed.setGeometry(geom)
            index.addFeature(indexed)
        return _LineIndex(items, index)

    @staticmethod
    def _linear_parts(geom: QgsGeometry) -> List[QgsGeometry]:
        """Splits the crest into continuous parts. Gaps are not bridged."""
        merged = geom.mergeLines() if geom.isMultipart() else geom
        if not merged.isMultipart():
            return [merged]
        return [
            QgsGeometry.fromPolylineXY(part)
            for part in merged.asMultiPolyline()
            if len(part) >= 2
        ]

    def _resolve_local_uk(
        self,
        ok_geom: QgsGeometry,
        ok_fid: int,
        ok_group: Any,
        uk_index: _LineIndex,
        group_field: str,
        max_dist: float,
        feedback: QgsProcessingFeedback,
    ) -> Tuple[Optional[QgsGeometry], str]:
        """Returns the toe geometry for a crest part and a reason code.

        The reason is "" on success, otherwise "none", "merge" or "ambiguous".
        Grouping is strict: NULL matches only NULL. Otherwise the value must be equal.
        """
        search_box = ok_geom.boundingBox()
        search_box.grow(max_dist)

        candidates: List[Tuple[float, QgsGeometry]] = []
        for key in uk_index.index.intersects(search_box):
            item = uk_index.items.get(key)
            if item is None:
                continue
            if group_field and item.group != ok_group:
                continue
            dist = ok_geom.distance(item.geometry)
            if dist <= max_dist:
                candidates.append((dist, item.geometry))

        if not candidates:
            return None, "none"

        candidates.sort(key=lambda entry: entry[0])
        chain, others = self._split_chain([geom for _, geom in candidates])
        toe = chain[0] if len(chain) == 1 else QgsGeometry.unaryUnion(chain)
        if toe.isEmpty():
            return None, "merge"
        if not toe.isGeosValid():
            toe = toe.makeValid()
            if toe.isEmpty():
                return None, "merge"

        if others and self._is_ambiguous(ok_geom, toe, others, max_dist):
            return None, "ambiguous"
        return toe, ""

    @staticmethod
    def _split_chain(
        geoms: List[QgsGeometry],
    ) -> Tuple[List[QgsGeometry], List[QgsGeometry]]:
        """Splits toe geometries (sorted by distance) into the chain that touches
        the nearest one, and all remaining geometries."""
        pending = list(geoms)
        chain = [pending.pop(0)]
        grew = True
        while grew and pending:
            grew = False
            still_pending: List[QgsGeometry] = []
            for geom in pending:
                if any(geom.distance(member) <= CHAIN_TOLERANCE for member in chain):
                    chain.append(geom)
                    grew = True
                else:
                    still_pending.append(geom)
            pending = still_pending
        return chain, pending

    @staticmethod
    def _is_ambiguous(
        ok_geom: QgsGeometry,
        toe: QgsGeometry,
        others: List[QgsGeometry],
        max_dist: float,
    ) -> bool:
        """True if another toe line is at least as close as the chosen one at a
        sampled point of the crest part. The chosen line would then silently decide
        the geometry, so the crest part is skipped with a warning instead."""
        length = ok_geom.length()
        if length <= 0.0:
            return False
        for k in range(AMBIGUITY_SAMPLES + 1):
            point = QgsGeometry.fromPointXY(
                ok_geom.interpolate(length * k / AMBIGUITY_SAMPLES).asPoint()
            )
            d_toe = point.distance(toe)
            for other in others:
                d_other = point.distance(other)
                if d_other <= max_dist and d_other <= d_toe + CHAIN_TOLERANCE:
                    return True
        return False

    def _reason_message(self, reason: str, ok_fid: int) -> str:
        if reason == "ambiguous":
            return self.tr(
                "Toe lines are ambiguous for crest feature ID {}: a second toe line "
                "runs alongside the same crest section. The crest section was skipped."
            ).format(ok_fid)
        if reason == "merge":
            return self.tr(
                "Toe lines could not be merged for crest feature ID {}."
            ).format(ok_fid)
        return self.tr(
            "No toe line within search distance for crest feature ID {}."
        ).format(ok_fid)

    @staticmethod
    def _resolve_local_kehlen(
        ok_geom: QgsGeometry,
        kehlen_index: _LineIndex,
        max_dist: float,
    ) -> List[_IndexedLine]:
        search_box = ok_geom.boundingBox()
        search_box.grow(max_dist)
        hits: List[_IndexedLine] = []
        for key in kehlen_index.index.intersects(search_box):
            item = kehlen_index.items.get(key)
            if item is not None and ok_geom.distance(item.geometry) <= max_dist:
                hits.append(item)
        return hits

    @staticmethod
    def _build_output_fields() -> QgsFields:
        fields = QgsFields()
        fields.append(QgsField(SlopeHachuresAlgorithm.FIELD_OK_FID, QVariant.LongLong))
        fields.append(QgsField(SlopeHachuresAlgorithm.FIELD_TYP, QVariant.String))
        fields.append(QgsField(SlopeHachuresAlgorithm.FIELD_STATION, QVariant.Double))
        fields.append(QgsField(SlopeHachuresAlgorithm.FIELD_LEN_GEZ, QVariant.Double))
        fields.append(QgsField(SlopeHachuresAlgorithm.FIELD_LEN_GES, QVariant.Double))
        fields.append(QgsField(SlopeHachuresAlgorithm.FIELD_MODUS, QVariant.String))
        return fields

    def _write(
        self,
        sink,
        fields: QgsFields,
        geometry: QgsGeometry,
        attributes: List[Any],
    ) -> None:
        """Writes one feature. A failed write aborts the run instead of being ignored."""
        feat = QgsFeature(fields)
        feat.setGeometry(geometry)
        feat.setAttributes(attributes)
        if not sink.addFeature(feat, QgsFeatureSink.Flag.FastInsert):
            raise QgsProcessingException(self.tr("Could not write feature to output layer."))
