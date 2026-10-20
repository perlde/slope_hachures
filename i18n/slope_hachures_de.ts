<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE TS>
<TS version="2.1" language="de_DE">
<context>
    <name>BoeschungPlugin</name>
    <message>
        <source>&amp;Slope Hachures</source>
        <translation>&amp;Böschungsschraffen</translation>
    </message>
    <message>
        <source>Slope Hachures</source>
        <translation>Böschungsschraffen</translation>
    </message>
    <message>
        <source>Generate Slope Hachures...</source>
        <translation>Böschungsschraffen erzeugen...</translation>
    </message>
    <message>
        <source>Open dialog to generate engineering slope hachures</source>
        <translation>Öffnet den Berechnungsdialog für normgerechte Böschungsschraffen</translation>
    </message>
    <message>
        <source>Generate Slope Hachures (OKSTRA / RE 2012)</source>
        <translation>Böschungsschraffen erzeugen (OKSTRA / RE 2012)</translation>
    </message>
    <message>
        <source>Processing provider could not be registered. Please check the QGIS log for details.</source>
        <translation>Der Processing-Provider konnte nicht registriert werden. Bitte prüfe das QGIS-Log für Details.</translation>
    </message>
    <message>
        <source>Plugin is not initialized. Please restart QGIS.</source>
        <translation>Das Plugin ist nicht initialisiert. Bitte QGIS neu starten.</translation>
    </message>
    <message>
        <source>Could not open the processing dialog: {}</source>
        <translation>Der Processing-Dialog konnte nicht geöffnet werden: {}</translation>
    </message>
</context>
<context>
    <name>SlopeHachuresAlgorithm</name>
    <message>
        <source>Generate Slope Hachures (OKSTRA / RE 2012)</source>
        <translation>Böschungsschraffen erzeugen (OKSTRA / RE 2012)</translation>
    </message>
    <message>
        <source>Terrain &amp; Tracing</source>
        <translation>Gelände &amp; Trassierung</translation>
    </message>
    <message>
        <source>Crest line / Top of slope (Kamm)</source>
        <translation>Böschungsoberkante (Kamm)</translation>
    </message>
    <message>
        <source>Toe line / Bottom of slope (Fuß)</source>
        <translation>Böschungsunterkante (Fuß)</translation>
    </message>
    <message>
        <source>Valleys / Breaklines / Corners (optional)</source>
        <translation>Kehlen / Eck-Diagonalen (optional)</translation>
    </message>
    <message>
        <source>Grouping attribute field (optional)</source>
        <translation>Gruppierungs-Attribut (optional)</translation>
    </message>
    <message>
        <source>Interval between long hatches [m]</source>
        <translation>Abstand der langen Schraffen [m]</translation>
    </message>
    <message>
        <source>Length of short hatches [%]</source>
        <translation>Länge der kurzen Schraffen [%]</translation>
    </message>
    <message>
        <source>Maximum search distance [m]</source>
        <translation>Maximale Suchlänge [m]</translation>
    </message>
    <message>
        <source>Slope plan (Hachures &amp; Breaklines)</source>
        <translation>Böschungsplan (Schraffen &amp; Kehlen)</translation>
    </message>
    <message>
        <source>Invalid crest layer (INPUT_OK).</source>
        <translation>Oberkantenlayer (INPUT_OK) ungültig.</translation>
    </message>
    <message>
        <source>Invalid toe layer (INPUT_UK).</source>
        <translation>Unterkantenlayer (INPUT_UK) ungültig.</translation>
    </message>
    <message>
        <source>Could not create output sink.</source>
        <translation>Ausgabelayer konnte nicht angelegt werden.</translation>
    </message>
    <message>
        <source>Could not write feature to output layer.</source>
        <translation>Feature konnte nicht in den Ausgabelayer geschrieben werden.</translation>
    </message>
    <message>
        <source>Done: {count} elements created.</source>
        <translation>Fertig: {count} Elemente erzeugt.</translation>
    </message>
    <message>
        <source>Crest</source>
        <translation>Oberkante</translation>
    </message>
    <message>
        <source>Toe</source>
        <translation>Unterkante</translation>
    </message>
    <message>
        <source>Breakline</source>
        <translation>Kehle</translation>
    </message>
    <message>
        <source>Layer '{}' ({}) has no coordinate reference system.</source>
        <translation>Layer '{}' ({}) hat kein Koordinatenbezugssystem.</translation>
    </message>
    <message>
        <source>Layer '{}' ({}) uses a geographic CRS ({}). Slope hachures require a projected, metric CRS (e.g. UTM / Gauß-Krüger).</source>
        <translation>Layer '{}' ({}) verwendet ein geographisches KBS ({}). Böschungsschraffen erfordern ein projiziertes, metrisches System (z. B. UTM / Gauß-Krüger).</translation>
    </message>
    <message>
        <source>Layer '{}' ({}) uses CRS units other than meters ({}). Please reproject to a metric CRS.</source>
        <translation>Layer '{}' ({}) verwendet andere Einheiten als Meter ({}). Bitte in ein metrisches System reprojizieren.</translation>
    </message>
    <message>
        <source>Coordinate transformation failed for layer '{}' ({}), feature {}.</source>
        <translation>Koordinatentransformation für Layer '{}' ({}), Feature {} fehlgeschlagen.</translation>
    </message>
    <message>
        <source>Grouping field '{}' not found in layer '{}' ({}).</source>
        <translation>Gruppierungsfeld '{}' im Layer '{}' ({}) nicht gefunden.</translation>
    </message>
    <message>
        <source>Skipping invalid crest feature ID {}.</source>
        <translation>Überspringe ungültiges Oberkanten-Feature mit ID {}.</translation>
    </message>
    <message>
        <source>Skipping invalid feature ID {} in layer '{}'.</source>
        <translation>Überspringe ungültiges Feature mit ID {} im Layer '{}'.</translation>
    </message>
    <message>
        <source>Interval too small for crest feature ID {}: more than {} stations would be created.</source>
        <translation>Intervall zu klein für Oberkanten-Feature mit ID {}: Es würden mehr als {} Stationen erzeugt.</translation>
    </message>
    <message>
        <source>No toe line within search distance for crest feature ID {}.</source>
        <translation>Keine Unterkante innerhalb der Suchlänge für Oberkanten-Feature mit ID {}.</translation>
    </message>
    <message>
        <source>Toe lines could not be merged for crest feature ID {}.</source>
        <translation>Unterkanten konnten für Oberkanten-Feature mit ID {} nicht zusammengeführt werden.</translation>
    </message>
    <message>
        <source>Toe lines are ambiguous for crest feature ID {}: a second toe line runs alongside the same crest section. The crest section was skipped.</source>
        <translation>Unterkanten sind für das Oberkanten-Feature mit ID {} mehrdeutig: Eine zweite Unterkante verläuft entlang desselben Kammabschnitts. Der Kammabschnitt wurde übersprungen.</translation>
    </message>
    <message>
        <source>Long hatch</source>
        <translation>Lange Schraffe</translation>
    </message>
    <message>
        <source>Short hatch</source>
        <translation>Kurze Schraffe</translation>
    </message>
    <message>
        <source>Valley / Breakline (OKSTRA 0486)</source>
        <translation>Kehle / Bruchkante (OKSTRA 0486)</translation>
    </message>
</context>
</TS>
