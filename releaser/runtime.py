"""Laufzeitumgebung erkennen und vermessen.

Dasselbe Programm wird in drei Formen ausgeliefert: als Quelltext für die
Kommandozeile, als gebündelte Anwendung (AppImage) und als Container mit
Weboberfläche. Die Formen unterscheiden sich nicht in dem, was sie können,
sondern darin, **was sie voraussetzen** - an Hardware, an Rechten, an Wissen
und daran, wo die Daten liegen.

Dieses Modul misst diese Unterschiede, statt sie zu behaupten. ``releaser
metrics`` gibt sie aus; in einer Präsentation lassen sich die drei Ausgaben
nebeneinander legen.

Gemessen wird nur, was sich zur Laufzeit ehrlich bestimmen lässt. Wo das nicht
geht, steht ``None`` und nicht eine plausible Zahl.
"""

from __future__ import annotations

import os
import platform
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional, Sequence

#: Zeitpunkt, zu dem dieses Modul geladen wurde - Bezugspunkt für die
#: Startzeit. Genauer wäre der Prozessstart, den holt ``_process_start``.
_IMPORTED_AT = time.monotonic()


class Variant(Enum):
    """Auslieferungsform."""

    SOURCE = "source"        # direkt aus dem Quelltext, Kommandozeile
    APPIMAGE = "appimage"    # gebündelte Anwendung
    CONTAINER = "container"  # Docker o. ä., meist mit Weboberfläche
    FROZEN = "frozen"        # anderweitig gebündelt (PyInstaller)

    @property
    def label(self) -> str:
        return {
            Variant.SOURCE: "Quelltext / CLI",
            Variant.APPIMAGE: "AppImage",
            Variant.CONTAINER: "Container",
            Variant.FROZEN: "gebündelt",
        }[self]


def detect_variant() -> Variant:
    """Erkennt, in welcher Form das Programm gerade läuft."""
    if os.environ.get("APPIMAGE") or os.environ.get("APPDIR"):
        return Variant.APPIMAGE
    if _in_container():
        return Variant.CONTAINER
    if getattr(sys, "frozen", False):
        return Variant.FROZEN
    return Variant.SOURCE


def _in_container() -> bool:
    if Path("/.dockerenv").exists():
        return True
    if os.environ.get("container"):
        return True
    try:
        cgroup = Path("/proc/self/cgroup").read_text(encoding="utf-8")
    except OSError:
        return False
    return any(marker in cgroup for marker in ("docker", "containerd", "kubepods"))


# ------------------------------------------------------------------ Messung


def _read_status(key: str) -> Optional[int]:
    """Wert aus ``/proc/self/status`` in Kilobyte."""
    try:
        for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
            if line.startswith(key):
                return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        return None
    return None


def _process_start() -> Optional[float]:
    """Sekunden seit dem Start dieses Prozesses."""
    try:
        stat = Path("/proc/self/stat").read_text(encoding="utf-8")
        # Feld 22 ist die Startzeit in Ticks seit Systemstart. Der Name des
        # Programms steht in Klammern und kann Leerzeichen enthalten - deshalb
        # hinter der schließenden Klammer trennen.
        fields = stat[stat.rindex(")") + 2:].split()
        ticks = int(fields[19])
        hertz = os.sysconf("SC_CLK_TCK")
        uptime = float(Path("/proc/uptime").read_text().split()[0])
        return max(0.0, uptime - ticks / hertz)
    except (OSError, ValueError, IndexError):
        return None


def directory_size(path: str | Path) -> int:
    """Summe der Dateigrößen unterhalb eines Pfades."""
    total = 0
    for entry in Path(path).rglob("*"):
        try:
            if entry.is_file() and not entry.is_symlink():
                total += entry.stat().st_size
        except OSError:
            continue
    return total


def dependency_size() -> Optional[int]:
    """Platzbedarf der Fremdbibliotheken, soweit getrennt auffindbar.

    In einem Buendel stecken sie in derselben Datei wie das Programm und sind
    nicht getrennt messbar - dann ``None``, nicht null.
    """
    if bundle_path() is not None:
        return None
    try:
        import mutagen
    except ImportError:
        return None
    return directory_size(Path(mutagen.__file__).parent)


def bundle_path() -> Optional[Path]:
    """Pfad des Buendels, wenn wir in einem laufen."""
    appimage = os.environ.get("APPIMAGE")
    if appimage and Path(appimage).is_file():
        return Path(appimage)
    if getattr(sys, "frozen", False):
        return Path(sys.executable)
    return None


def package_size() -> int:
    """Platzbedarf des Programms.

    In einem Buendel liegt der Code in einem Archiv - dort zaehlt die Groesse
    der ausgelieferten Datei, nicht die eines Verzeichnisses, das es nicht
    gibt.
    """
    bundle = bundle_path()
    if bundle is not None:
        try:
            return bundle.stat().st_size
        except OSError:
            return 0
    return directory_size(Path(__file__).parent)


@dataclass
class Metrics:
    variant: Variant
    python: str
    platform_name: str

    startup_seconds: Optional[float]
    resident_kb: Optional[int]
    package_bytes: int
    dependency_bytes: Optional[int]

    euid: int
    writable_cwd: bool
    #: Wo die zu bearbeitenden Dateien liegen, aus Sicht dieser Form
    data_location: str
    #: Braucht diese Form erhöhte Rechte, um überhaupt zu starten?
    needs_privileges: bool
    notes: list[str] = field(default_factory=list)

    @property
    def total_bytes(self) -> int:
        return self.package_bytes + (self.dependency_bytes or 0)

    @property
    def bundled(self) -> bool:
        return self.variant in (Variant.APPIMAGE, Variant.FROZEN)

    @property
    def running_as_root(self) -> bool:
        return self.euid == 0


def collect() -> Metrics:
    variant = detect_variant()
    notes: list[str] = []

    if variant is Variant.CONTAINER:
        data_location = "im Container - Dateien müssen hineingereicht werden"
        needs_privileges = True
        notes.append("Der Container-Dienst braucht Rechte am Docker-Socket; "
                     "wer ihn starten darf, hat faktisch Root auf dem Wirt.")
    elif variant in (Variant.APPIMAGE, Variant.FROZEN):
        data_location = "beim Nutzer, im eigenen Dateisystem"
        needs_privileges = False
        notes.append("Bringt Python und alle Bibliotheken mit - keine "
                     "Installation, keine Paketverwaltung, kein Netzzugang "
                     "nötig. Dafür liegt die gesamte Laufzeitumgebung in "
                     "jeder Kopie.")
        from .frontends import gtkui

        notes.append("GTK wird nicht mitgeliefert: die grafische Oberfläche "
                     "nutzt das GTK des Wirts."
                     + ("" if gtkui.is_available()
                        else " Hier ist keins vorhanden - die Kommandozeile "
                             "funktioniert trotzdem."))
    else:
        data_location = "beim Nutzer, im eigenen Dateisystem"
        needs_privileges = False
        notes.append("Setzt eine passende Python-Version voraus - und die "
                     "Bereitschaft, eine Kommandozeile zu benutzen.")

    euid = os.geteuid() if hasattr(os, "geteuid") else -1
    if euid == 0:
        notes.append("Läuft als root.")

    # Nur nachfragen, nicht ausprobieren: eine Messung darf keine Datei im
    # Verzeichnis des Nutzers anlegen, auch keine kurzlebige.
    try:
        writable = os.access(Path.cwd(), os.W_OK)
    except OSError:
        writable = False
    if not writable:
        notes.append("Das aktuelle Verzeichnis ist nicht beschreibbar.")

    return Metrics(
        variant=variant,
        python=platform.python_version(),
        platform_name=f"{platform.system()} {platform.machine()}",
        startup_seconds=_process_start(),
        resident_kb=_read_status("VmRSS"),
        package_bytes=package_size(),
        dependency_bytes=dependency_size(),
        euid=euid,
        writable_cwd=writable,
        data_location=data_location,
        needs_privileges=needs_privileges,
        notes=notes,
    )


# ----------------------------------------------------------------- Ausgabe


def human_bytes(value: Optional[int]) -> str:
    if value is None:
        return "unbekannt"
    step = 1024.0
    number = float(value)
    for unit in ("B", "KB", "MB", "GB"):
        if number < step:
            return f"{number:.1f} {unit}".replace(".0 ", " ")
        number /= step
    return f"{number:.1f} TB"


def as_rows(metrics: Metrics) -> list[tuple[str, str]]:
    startup = ("unbekannt" if metrics.startup_seconds is None
               else f"{metrics.startup_seconds * 1000:.0f} ms")
    memory = ("unbekannt" if metrics.resident_kb is None
              else human_bytes(metrics.resident_kb * 1024))
    return [
        ("Form", metrics.variant.label),
        ("Python", metrics.python),
        ("System", metrics.platform_name),
        ("Startzeit", startup),
        ("Arbeitsspeicher", memory),
        ("Programmcode", human_bytes(metrics.package_bytes)),
        ("Fremdbibliotheken",
         "im Bündel enthalten" if metrics.dependency_bytes is None
         and metrics.bundled else human_bytes(metrics.dependency_bytes)),
        ("zusammen", human_bytes(metrics.total_bytes)),
        ("Rechte nötig", "ja" if metrics.needs_privileges else "nein"),
        ("läuft als root", "ja" if metrics.running_as_root else "nein"),
        ("Arbeitsverzeichnis beschreibbar", "ja" if metrics.writable_cwd else "nein"),
        ("Daten liegen", metrics.data_location),
    ]


def format_metrics(metrics: Metrics) -> str:
    rows = as_rows(metrics)
    width = max(len(label) for label, _ in rows)
    lines = [f"  {label.ljust(width)}  {value}" for label, value in rows]
    if metrics.notes:
        lines.append("")
        lines += [f"  * {note}" for note in metrics.notes]
    return "\n".join(lines)


#: Zeilen des Vergleichs: Schluessel im JSON, Beschriftung, Aufbereitung.
COMPARISON_ROWS: tuple[tuple[str, str, str], ...] = (
    ("variant", "Form", "variant"),
    ("python", "Python", "raw"),
    ("startup_seconds", "Startzeit", "seconds"),
    ("resident_kb", "Arbeitsspeicher", "kilobytes"),
    ("total_bytes", "Auslieferungsgröße", "bytes"),
    ("needs_privileges", "Rechte nötig", "yesno"),
    ("data_location", "Daten liegen", "raw"),
)


def _cell(kind: str, value) -> str:
    if value is None:
        return "unbekannt"
    if kind == "variant":
        try:
            return Variant(value).label
        except ValueError:
            return str(value)
    if kind == "seconds":
        return f"{float(value) * 1000:.0f} ms"
    if kind == "kilobytes":
        return human_bytes(int(value) * 1024)
    if kind == "bytes":
        return human_bytes(int(value))
    if kind == "yesno":
        return "ja" if value else "nein"
    return str(value)


def compare(payloads: Sequence[dict]) -> list[list[str]]:
    """Baut eine Vergleichstabelle aus mehreren ``metrics --json``-Ausgaben.

    Gedacht fuer die Gegenueberstellung der Auslieferungsformen: dieselbe
    Software, dieselben Faehigkeiten - verschiedene Voraussetzungen.
    """
    header = [""] + [_cell("variant", p.get("variant")) for p in payloads]
    rows = [header]
    for key, label, kind in COMPARISON_ROWS:
        if key == "variant":
            continue
        rows.append([label] + [_cell(kind, p.get(key)) for p in payloads])
    return rows


def format_comparison(payloads: Sequence[dict]) -> str:
    rows = compare(payloads)
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    lines = ["  ".join(cell.ljust(widths[i]) for i, cell in enumerate(rows[0])),
             "  ".join("-" * w for w in widths)]
    lines += ["  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row))
              for row in rows[1:]]
    notes: list[str] = []
    for payload in payloads:
        for note in payload.get("notes", []):
            entry = f"{_cell('variant', payload.get('variant'))}: {note}"
            if entry not in notes:
                notes.append(entry)
    if notes:
        lines.append("")
        lines += [f"  * {note}" for note in notes]
    return "\n".join(lines)


def as_dict(metrics: Metrics) -> dict:
    """Maschinenlesbare Form - für die Weboberfläche und für Vergleiche."""
    return {
        "variant": metrics.variant.value,
        "python": metrics.python,
        "platform": metrics.platform_name,
        "startup_seconds": metrics.startup_seconds,
        "resident_kb": metrics.resident_kb,
        "package_bytes": metrics.package_bytes,
        "dependency_bytes": metrics.dependency_bytes,
        "total_bytes": metrics.total_bytes,
        "euid": metrics.euid,
        "writable_cwd": metrics.writable_cwd,
        "data_location": metrics.data_location,
        "needs_privileges": metrics.needs_privileges,
        "bundled": metrics.bundled,
        "notes": metrics.notes,
    }


#: Sprechender Name für den Export aus dem Paket.
collect_metrics = collect
