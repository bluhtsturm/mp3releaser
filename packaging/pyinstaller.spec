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
    # Der Textsatz von GTK. Seit die NFO-Ansicht Pango und Graphene selbst
    # einbindet (0.25.0), zog PyInstaller sie aus dem Bausystem mit herein.
    # Im Buendel geladen, verdraengten sie die neueren des Wirts: Auf Debian
    # 13 fand dessen libpangoft2 die Funktion
    # pango_font_description_set_features in der alten libpango nicht, und
    # GTK liess sich gar nicht laden.
    "libpango", "libharfbuzz", "libgraphene", "libfribidi.", "libthai.",
    "libdatrie.", "libgraphite2.", "libgtk", "libgdk", "libepoxy.",
)
a.binaries = [entry for entry in a.binaries
              if not Path(entry[0]).name.startswith(HOST_PROVIDED)]

# Die Typelibs dazu ebenso: Sie beschreiben die Bibliotheken des Wirts und
# muessen zu deren Fassung passen. Ohne Kopie im Buendel findet
# GObject-Introspection die des Wirts in seinem Standardpfad - so kommt auch
# Gtk-4.0.typelib schon immer vom System.
HOST_TYPELIBS = (
    "Pango-", "PangoCairo-", "PangoFT2-", "PangoOT-", "PangoFc-",
    "HarfBuzz-", "Graphene-", "Gtk-", "Gdk-", "GdkPixbuf-", "Gsk-",
    "cairo-", "freetype2-", "fontconfig-",
)
a.datas = [entry for entry in a.datas
           if not (entry[0].startswith("gi_typelibs/")
                   and Path(entry[0]).name.startswith(HOST_TYPELIBS))]

pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="mp3releaser",
    console=True,
    strip=False,
    upx=False,
)
