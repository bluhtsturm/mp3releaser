# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller-Beschreibung fuer die gebuendelte Fassung.

Gebuendelt wird der Python-Interpreter samt mutagen - die Kommandozeile
laeuft danach ohne jede Installation. GTK wird *nicht* gebuendelt: die
Bibliothek ist zu gross und zu eng mit dem System verwoben. Die grafische
Oberflaeche nutzt deshalb das GTK des Wirts, und das AppImage sagt das auch.
"""

import re
import subprocess
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

# Die grafische Oberflaeche nutzt GTK vom Wirt - und damit alles, was GTK
# laedt, ebenfalls vom Wirt. Eine Bibliothek, die im Buendel liegt, geht vor:
# Ist sie aelter als die des Wirts, fehlen dem GTK des Wirts Funktionen, und es
# laesst sich nicht laden. Die Kommandozeile braucht keine davon.
HOST_PROVIDED = (
    # Grafik - dieselben Namen stehen auf der Ausschlussliste der
    # AppImage-Gemeinschaft
    "libX11.", "libXau.", "libXdmcp.", "libXext.", "libXrender.", "libxcb",
    "libcairo", "libpixman-", "libfontconfig.", "libfreetype.", "libpng16.",
    "libexpat.", "libbrotli", "libgcc_s.",
    # Der Textsatz. Seit die NFO-Ansicht Pango und Graphene selbst einbindet
    # (0.25.0), zog PyInstaller sie aus dem Bausystem mit herein. Auf Debian
    # 13 fand die libpangoft2 des Wirts pango_font_description_set_features
    # in der alten libpango aus dem Buendel nicht.
    "libpango", "libharfbuzz", "libgraphene", "libfribidi.", "libthai.",
    "libdatrie.", "libgraphite2.", "libgtk", "libgdk", "libepoxy.",
    # GLib, GObject, GIO (0.25.2). Das GTK 4.24 von Debian testing bindet
    # GStreamer ein, und dessen libgstaudio braucht g_sort_array aus GLib
    # 2.82 - die GLib 2.80 aus dem Buendel (Ubuntu 24.04) hatte sie nicht.
    "libglib-2.0.", "libgobject-2.0.", "libgio-2.0.", "libgmodule-2.0.",
)
a.binaries = [entry for entry in a.binaries
              if not (Path(entry[0]).name.startswith(HOST_PROVIDED)
                      # GIO-Module laedt die GLib des Wirts aus ihrem
                      # eigenen Ordner, passend zu ihrer Fassung
                      or entry[0].startswith("gio_modules/"))]


def _needed(path):
    """Die Bibliotheken, die eine Datei direkt anfordert (DT_NEEDED)."""
    out = subprocess.run(["objdump", "-p", path], capture_output=True,
                         text=True, check=True).stdout
    return re.findall(r"^\s+NEEDED\s+(\S+)", out, re.M)


# Was danach nur noch die ausgeschlossenen Bibliotheken brauchten, faellt
# mit weg: GnuTLS, Kerberos, libproxy, libmount und Co. kamen allein ueber
# die GIO-Module herein. Behalten wird, was der Interpreter und seine
# Erweiterungsmodule anfordern - direkt oder ueber eine behaltene Bibliothek.
_by_name = {Path(entry[0]).name: entry for entry in a.binaries}
_todo = [entry for entry in a.binaries if entry[2] == "EXTENSION"
         or Path(entry[0]).name.startswith("libpython")]
_kept = set()
while _todo:
    _entry = _todo.pop()
    if _entry[0] in _kept:
        continue
    _kept.add(_entry[0])
    _todo.extend(_by_name[name] for name in _needed(_entry[1])
                 if name in _by_name)
a.binaries = [entry for entry in a.binaries if entry[0] in _kept]

# Daten, die die GLib-Hooks von PyInstaller aus dem Bausystem mitnehmen: den
# Cache der GIO-Module, GSettings-Schemas, die MIME-Datenbank. Sie gehoeren
# zur GLib des Bausystems; neben der GLib und dem GTK des Wirts muessen es
# dessen eigene sein. Die Typelibs bleiben als Rueckfall im Buendel - die des
# Wirts gehen vor (siehe entrypoint.py).
HOST_DATA = (
    "gio_modules/", "share/glib-2.0/", "share/mime/",
)
a.datas = [entry for entry in a.datas if not entry[0].startswith(HOST_DATA)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="mp3releaser",
    console=True,
    strip=False,
    upx=False,
)
