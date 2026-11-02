# Slope Hachures for QGIS (Böschungsschraffen)

[![QGIS Version](https://img.shields.io/badge/QGIS-3.22%20%E2%80%93%204.x-brightgreen.svg)](https://qgis.org)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Ko-fi](https://img.shields.io/badge/Ko--fi-Support-ff5e5b?logo=kofi&logoColor=white)](https://ko-fi.com/perlde)

A QGIS Processing plugin that creates slope hachures (embankment ticks, Taludschraffur) from crest and toe lines according to **RE 2012**, **OKSTRA 0486** and **DIN 2425 / 18702**.

![Slope hachures](media/slope.png)

## Examples

| | |
|:--:|:--:|
| <img src="media/stresstest.png" width="320"><br>Stress test overview | <img src="media/stresstest_1.png" width="320"><br>Stress test 1 |
| <img src="media/stresstest_2.png" width="320"><br>Stress test 2 | <img src="media/stresstest_3.png" width="320"><br>Stress test 3 |
| <img src="media/stresstest_4.png" width="320"><br>Stress test 4 | <img src="media/stresstest_5.png" width="320"><br>Stress test 5 |

## Features

- Standard cartographic look: long and short hachures in earth brown, styled automatically.
- Breakline support (Kehlen) for excavation pits, ramps and daylight transitions (OKSTRA 0486).
- Even spacing per crest section: the spacing is adjusted per section, so no compressed hachure remains at a section end.
- Overlap reduction at sharp bends and breaklines.
- Closed lines: crest and toe rings (e.g. around a pit or a mound) are hachured all the way round, whatever their direction and start vertex.
- Fast on long and densely digitised lines: the cost per hachure does not grow with the number of vertices.
- Automatic CRS transformation: crest, toe and breakline layers may use different projected CRS.
- Strict attribute grouping: a NULL group only matches a NULL group.
- Integrated into the Processing Toolbox, Graphical Modeler and Batch mode.
- German and English interface, selected automatically from the QGIS language.

## Recommended spacing by print scale

| Print scale | Typical use | Recommended interval |
| :--- | :--- | :--- |
| 1 : 250 | Site details, building pits | 1.0 – 1.5 m |
| 1 : 500 | Standard civil engineering plans | 2.0 – 3.0 m |
| 1 : 1000 | Overview plans, road design | 4.0 – 5.0 m |

## Installation

**From ZIP:** Plugins → Manage and Install Plugins → Install from ZIP → select the ZIP file.

**Manually:** Copy the folder `slope_hachures` into the QGIS plugin folder, then restart QGIS.

## Quick start

1. Use layers with a projected, metric CRS (e.g. UTM EPSG:25832).
2. Open Processing Toolbox → Terrain & Tracing → Generate Slope Hachures (OKSTRA / RE 2012).
3. Select the crest line (Kamm) and the toe line (Fuß).
4. Optional: select the breakline layer (Kehlen) for pits and corners. Where a hachure drawn perpendicular to the crest no longer meets the toe line because the toe line ends earlier, add a breakline (Randkehle) at that point. Start a closed crest line (e.g. around a pit) at a corner where a breakline meets it: if its first vertex lies 0.25–2.5 m beside a breakline, single hachures can cross there.
5. Set the interval and run.

## Development

```bash
# Compile translations (requires lrelease)
cd i18n && python build_translations.py

# Run the tests (from the repository root)
python3 -m unittest discover -s tests -v
```

Layout: `core/` contains the geometry engine without any UI or processing code. `core/polyline.py` holds the per-station line queries in plain Python (no QGIS imports). `processing/` contains the Processing algorithm, the provider and the styling. `plugin.py` is the QGIS entry point.

Tests: `tests/test_polyline.py` and the `.ts` checks run with any Python 3. The other tests need QGIS and are skipped without it; they compare the line queries with GEOS, run the engine on open lines and rings, and run the full Processing algorithm. The GitHub workflow runs everything in the `qgis/qgis` docker images for QGIS 3.22, the current LTR and QGIS 4, and runs the official Qt6 compatibility check ([pyqgis4-checker](https://github.com/qgis/pyqgis4-checker)) on the plugin files; its findings appear as warnings on the workflow run.

The `tests/` folder and `.github/` are not needed in the plugin ZIP.

## License

GNU General Public License v3.0 or later. See `LICENSE`.

## Support

If this plugin saves you time on projects, you can support its maintenance: [Ko-fi](https://ko-fi.com/perlde).
