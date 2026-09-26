# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller-Beschreibung fuer die gebuendelte Fassung.

Gebuendelt wird der Python-Interpreter samt mutagen - die Kommandozeile
laeuft danach ohne jede Installation. GTK wird *nicht* gebuendelt: die
Bibliothek ist zu gross und zu eng mit dem System verwoben. Die grafische
Oberflaeche nutzt deshalb das GTK des Wirts, und das AppImage sagt das auch.
"""

import sys
from pathlib import Path

project = Path(SPECPATH).parent

a = Analysis(
    [str(project / "packaging" / "entrypoint.py")],
    pathex=[str(project)],
    binaries=[],
    datas=[],
    hiddenimports=[
        "mutagen", "mutagen.mp3", "mutagen.flac", "mutagen.mp4",
        "mutagen.id3", "mutagen.apev2", "mutagen.oggvorbis",
        "mutagen.oggopus", "mutagen.musepack",
    ],
    hookspath=[],
    excludes=["tkinter", "test", "unittest", "pydoc_data"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="mp3releaser",
    console=True,
    strip=False,
    upx=False,
)
