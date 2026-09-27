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
        # PyGObjects Overrides fuer GTK sind reines Python und gehoeren ins
        # Buendel - GTK selbst (Bibliotheken, Typelibs) kommt vom Wirt.
        # PyInstaller nimmt sie nur mit, wenn sein GTK-Hook greift, und der
        # sucht GTK 3: auf einem Rechner mit nur GTK 4 fehlten sie, und die
        # Oberflaeche brach beim Start mit "set_text() takes exactly 3
        # arguments" ab.
        "gi.overrides.Gtk", "gi.overrides.Gdk", "gi.overrides.GdkPixbuf",
        "gi.overrides.Pango", "gi.overrides.keysyms", "gi._gtktemplate",
    ],
    hookspath=[],
    excludes=["tkinter", "test", "unittest", "pydoc_data"],
    noarchive=False,
)

# Grafikbibliotheken, die GTK auf dem Wirt ohnehin mitbringt. PyInstaller
# zieht sie ueber die Gdk-/cairo-Typelibs herein; im Buendel wuerden sie neben
# dem GTK des Wirts geladen und koennten mit dessen Fassungen kollidieren.
# Dieselben Namen stehen auf der Ausschlussliste der AppImage-Gemeinschaft.
# Die Kommandozeile laedt keine davon.
HOST_PROVIDED = (
    "libX11.", "libXau.", "libXdmcp.", "libXext.", "libXrender.", "libxcb",
    "libcairo", "libpixman-", "libfontconfig.", "libfreetype.", "libpng16.",
    "libexpat.", "libbrotli", "libgcc_s.",
)
a.binaries = [entry for entry in a.binaries
              if not Path(entry[0]).name.startswith(HOST_PROVIDED)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="mp3releaser",
    console=True,
    strip=False,
    upx=False,
)
