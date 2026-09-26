"""Erzeugt ``templates/standard.skl``.

Die Vorlage wird erzeugt statt von Hand geschrieben: Eine .skl ist
spaltengenau, und ein einziges Leerzeichen zu viel verschiebt den rechten
Rahmen. Der Generator baut jede Zeile auf dieselbe Breite und prüft das am
Ende selbst.

Inhalt: jedes Feld, das sich in einer Oberfläche eintragen lässt, dazu die
berechneten Werte (Bitrate, Laufzeiten, Größe, Trackliste). Von Werten, für
die es mehrere Ausrichtungsvarianten gibt - ``#Tpti``, ``Tpti#``,
``#hhhTpti`` -, steht jeweils eine drin; die übrigen würden denselben Wert
nur noch einmal anders ausgerichtet wiederholen.

Aufruf::

    python3 tools/make_standard_skl.py

Die Rahmenzeichen stammen aus Codepage 437, wie in NFOs üblich. Die Grafik
ist eigene Gestaltung.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "templates" / "standard.skl"

#: Breite der Innenseite zwischen den beiden Rahmenlinien
INNER = 76
LABEL = 16

TOP = "╔" + "═" * INNER + "╗"
BOTTOM = "╚" + "═" * INNER + "╝"


def row(text: str = "") -> str:
    if len(text) > INNER:
        raise ValueError(f"Zeile zu lang ({len(text)}): {text!r}")
    return "║" + text.ljust(INNER) + "║"


def section(title: str) -> str:
    label = f"[ {title} ]"
    left = (INNER - len(label)) // 2
    return "╠" + "═" * left + label + "═" * (INNER - left - len(label)) + "╣"


def field(label: str, tag: str) -> str:
    """Eine Zeile "   Beschriftung : #Tag", das Feld reicht bis zum Rahmen."""
    return row(f"   {label.ljust(LABEL)}: {tag}")


def centered(tag: str) -> str:
    """Ein zentrierter Tag über die volle Breite, mit Rand links und rechts."""
    return row("  " + tag)


def build() -> list[str]:
    lines = [
        TOP,
        row(),
        centered("#Release"),
        centered("#CntUrl"),
        row(),
        section("RELEASE"),
        row(),
        field("Artist", "#Artist"),
        field("Album", "#Album"),
        field("Full title", "#Albwthadd"),
        field("Release", "#Fullrelease"),
        field("Genre", "#Genre"),
        field("Subgenre", "#Subgenre"),
        field("Style", "#Style"),
        field("Year", "#Year"),
        field("Type", "#Typ"),
        field("Source", "#Source"),
        field("Format", "#Format"),
        field("Language", "#Language"),
        field("Country", "#Country"),
        field("Label", "#Company"),
        field("Catalog no.", "#Catnr"),
        field("Release date", "#Rdate"),
        field("Store date", "#Sdate"),
        field("Recorded", "#Ldate"),
        field("Released with", "#RelWith"),
        field("Release no.", "#Rc"),
        row(),
        section("CREDITS"),
        row(),
        field("Ripper", "#Rip"),
        field("Supplier", "#Sup"),
        field("Grabber", "#Grab"),
        field("Encoder", "#Enc"),
        row(),
        section("AUDIO"),
        row(),
        field("Bitrate", "#Br"),
        # Einheiten in die Beschriftung, nicht hinter das Feld: sonst haengt
        # der Abstand davon ab, wie viel Platz der Wert gerade braucht
        # ("44.1kHz", aber "48  kHz").
        field("Samplerate (kHz)", "#Hz"),
        field("Resolution (bit)", "#Bps"),
        field("Channels", "#Mode"),
        field("FLAC ratio", "#FlacC"),
        field("Tracks", "#Tn"),
        field("Per disc", "#Sn"),
        field("Playtime", "#Tpti"),
        field("Size (MB)", "#Size"),
        row(),
        section("LINKS"),
        row(),
        field("URL", "#Url"),
        field("Mirror", "#2ndUrl"),
        row(),
        section("NOTES"),
        row(),
        # Zweite Zeile mit demselben Tag: Fortsetzung fuer weitere Notizen
        row("   #Rnotes"),
        row("   #Rnotes"),
        row(),
        section("GROUP NEWS"),
        row(),
        row("   #Gnews"),
        row("   #Gnews"),
        row(),
        section("TRACKLIST"),
        row(),
    ]

    # Trackzeile: Nummer, Titel, rechts die Laufzeit in eckigen Klammern.
    # Die Fortsetzungszeile darunter nimmt lange Titel und bei Mehr-CD-
    # Releases die CD-Kopfzeilen auf.
    duration = "[#Ptit]"
    track = "   #N. #Trk"
    lines.append(row(track.ljust(INNER - len(duration) - 3) + duration))
    lines.append(row("       #Trk"))
    lines.append(row(" " * (INNER - len(duration) - 3) + "─" * len(duration)))
    total = "#TptCTT#"
    lines.append(row(" " * (INNER - len(total) - 4) + total))
    lines += [row(), BOTTOM]
    return lines


def main() -> int:
    lines = build()
    widths = {len(line) for line in lines}
    if widths != {INNER + 2}:
        print(f"Fehler: ungleiche Zeilenbreiten {sorted(widths)}", file=sys.stderr)
        return 1

    TARGET.write_bytes(("\r\n".join(lines) + "\r\n").encode("cp437"))
    print(f"{TARGET.relative_to(ROOT)}: {len(lines)} Zeilen, {INNER + 2} Spalten")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
