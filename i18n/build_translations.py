#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Compiles all .ts files in i18n/ to .qm files via lrelease.

Usage:
    python build_translations.py                  # compile all .ts files
    python build_translations.py --lrelease PATH  # explicit lrelease path

Requirements:
    - Qt tools installed (lrelease on PATH, or passed with --lrelease)
    - Windows: typically C:\\Qt\\<version>\\<compiler>\\bin\\lrelease.exe
    - Linux:   apt install qttools5-dev-tools (or qt6-tools-dev-tools)
    - macOS:   brew install qt
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional


def find_lrelease(explicit: Optional[str] = None) -> Optional[str]:
    """Looks for lrelease at the explicit path, on PATH, or in common install locations."""
    if explicit:
        return explicit if os.path.isfile(explicit) else None

    for name in ("lrelease", "lrelease-qt6", "lrelease-qt5"):
        path = shutil.which(name)
        if path:
            return path

    candidates: List[str] = [
        r"C:\OSGeo4W\apps\Qt5\bin\lrelease.exe",
        r"C:\OSGeo4W\apps\Qt6\bin\lrelease.exe",
        r"C:\OSGeo4W64\apps\Qt5\bin\lrelease.exe",
        "/Applications/QGIS.app/Contents/MacOS/bin/lrelease",
        "/Applications/QGIS-LTR.app/Contents/MacOS/bin/lrelease",
        "/usr/lib/qt5/bin/lrelease",
        "/usr/lib/qt6/bin/lrelease",
    ]
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return None


def compile_all(lrelease: str, i18n_dir: Path) -> int:
    """Compiles all .ts files. Returns 0 on success, otherwise a non-zero exit code."""
    ts_files = sorted(i18n_dir.glob("slope_hachures_*.ts"))
    if not ts_files:
        print(f"[!] No .ts files found in {i18n_dir}.")
        return 1

    failures = 0
    for ts in ts_files:
        qm = ts.with_suffix(".qm")
        print(f"[*] {ts.name}  ->  {qm.name}")
        result = subprocess.run(
            [lrelease, str(ts), "-qm", str(qm)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.stdout.strip():
            print(f"    {result.stdout.strip()}")
        if result.returncode != 0:
            print(f"    [ERROR] {result.stderr.strip()}", file=sys.stderr)
            failures += 1
        elif not qm.exists() or qm.stat().st_size == 0:
            print(f"    [ERROR] {qm.name} was not created.", file=sys.stderr)
            failures += 1
        else:
            print(f"    [OK] {qm.stat().st_size} bytes")

    return 0 if failures == 0 else 2


def main() -> int:
    parser = argparse.ArgumentParser(description="Compiles all .ts files in i18n/ to .qm files.")
    parser.add_argument("--lrelease", default=None, help="Explicit path to the lrelease binary.")
    args = parser.parse_args()

    lrelease = find_lrelease(args.lrelease)
    if not lrelease:
        print(
            "[ERROR] lrelease not found.\n"
            "  Windows: C:\\Qt\\<version>\\<compiler>\\bin\\lrelease.exe\n"
            "  Linux:   sudo apt install qttools5-dev-tools\n"
            "  macOS:   brew install qt\n"
            "Or use: --lrelease /path/to/lrelease",
            file=sys.stderr,
        )
        return 1
    print(f"[*] lrelease: {lrelease}")

    i18n_dir = Path(__file__).resolve().parent
    return compile_all(lrelease, i18n_dir)


if __name__ == "__main__":
    sys.exit(main())
