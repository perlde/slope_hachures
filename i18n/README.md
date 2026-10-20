# Translations

## Files

| File | Purpose |
|---|---|
| `slope_hachures.pro` | Qt project file. Lists all source files and languages. |
| `slope_hachures_de.ts` | German translation (XML, editable with Qt Linguist). |
| `slope_hachures_de.qm` | Compiled German translation. QGIS loads this file. Created by the build script. |
| `build_translations.py` | Build script: `.ts` → `.qm`. |

## Build

```bash
cd i18n
python build_translations.py
```

The `.qm` file must be present in the ZIP release. Without it the plugin runs in English.

## Add a new language

1. Create the `.ts` file: `lupdate slope_hachures.pro -ts slope_hachures_fr.ts`
2. Translate the messages in Qt Linguist.
3. Run `python build_translations.py`.

## After code changes

Run `lupdate slope_hachures.pro -ts slope_hachures_de.ts` again. It adds new messages and marks obsolete ones. Then translate the new entries.
