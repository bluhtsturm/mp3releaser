"""Prüfungen.

Zwei Dinge lassen sich unabhängig voneinander prüfen:

* **Eine Vorlage** — bevor jemand sie benutzt. Zu schmale Felder, fehlende
  Fortsetzungszeile, Tippfehler in Tags: das steckt in der ``.skl`` selbst
  und fällt sonst erst an einem Release auf, dessen Werte zufällig lang
  genug sind.
* **Ein fertiges Release** — nachdem alles erzeugt wurde. Fehlt die NFO,
  stimmen die Prüfsummen, sind alle Tracks getaggt, ist der Name zu lang.

Beide liefern dieselbe Art Befund und keine Urteile: ein Hinweis ist ein
Hinweis, kein Fehler. Was wirklich kaputt ist, steht als ``ERROR`` da.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Iterable, Optional

from .model import Release
from .naming import NamingProfile, unknown_tags
from .skl import Template


class Level(Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"

    @property
    def marker(self) -> str:
        return {Level.ERROR: "x", Level.WARNING: "!", Level.INFO: "-"}[self]


@dataclass
class Issue:
    level: Level
    message: str
    #: worauf sich der Befund bezieht - Tagname, Dateiname, Feld
    subject: str = ""

    def __str__(self) -> str:
        where = f" [{self.subject}]" if self.subject else ""
        return f"{self.level.marker} {self.message}{where}"


@dataclass
class Report:
    issues: list[Issue] = field(default_factory=list)
    checked: str = ""

    def add(self, level: Level, message: str, subject: str = "") -> None:
        self.issues.append(Issue(level, message, subject))

    def of(self, level: Level) -> list[Issue]:
        return [i for i in self.issues if i.level is level]

    @property
    def ok(self) -> bool:
        return not self.of(Level.ERROR)

    @property
    def clean(self) -> bool:
        return not self.issues

    def summary(self) -> str:
        counts = [f"{len(self.of(level))} {name}"
                  for level, name in ((Level.ERROR, "Fehler"),
                                      (Level.WARNING, "Hinweise"),
                                      (Level.INFO, "Anmerkungen"))
                  if self.of(level)]
        return ", ".join(counts) if counts else "keine Beanstandungen"

    def render(self) -> str:
        head = f"{self.checked}: {self.summary()}" if self.checked else self.summary()
        return "\n".join([head] + [f"  {issue}" for issue in self.issues])


# ============================================================ Vorlagenprüfung

#: Felder, die typischerweise lang werden, mit einer sinnvollen Mindestbreite.
MIN_WIDTHS: dict[str, int] = {
    "Artist": 24, "Album": 24, "Release": 40, "Releasenc": 40,
    "Genre": 12, "Enc": 20, "Url": 24, "Rnotes": 40, "Trk": 24,
}

#: Ohne diese Tags ist eine NFO kaum brauchbar.
EXPECTED_TAGS: tuple[tuple[str, str], ...] = (
    ("Artist", "der Artist"),
    ("Album", "das Album"),
    ("Trk", "die Trackliste"),
)

#: Uebliche Breite einer NFO. Breiter wird in vielen Anzeigen umbrochen.
CONVENTIONAL_WIDTH = 80


def check_template(template: Template, source: str = "") -> Report:
    """Prüft eine Vorlage auf sich allein gestellt."""
    report = Report(checked=source or "Vorlage")
    tags = template.tag_names()
    widths = template.field_widths()

    for name, description in EXPECTED_TAGS:
        if name not in tags:
            report.add(Level.WARNING,
                       f"#{name} fehlt - {description} taucht nirgends auf",
                       f"#{name}")

    if "Release" not in tags and not {"Artist", "Album"} <= tags:
        report.add(Level.WARNING,
                   "weder #Release noch #Artist und #Album - die Kopfzeile "
                   "bleibt leer")

    for name, minimum in MIN_WIDTHS.items():
        width = widths.get(name)
        if width is not None and width < minimum:
            report.add(Level.WARNING,
                       f"#{name} hat nur {width} Zeichen Platz, "
                       f"empfohlen sind mindestens {minimum}",
                       f"#{name}")

    track_width, wraps = template.track_layout()
    if track_width and not wraps:
        report.add(Level.WARNING,
                   "keine Fortsetzungszeile in der Trackliste - zu lange "
                   "Titel werden abgeschnitten statt umgebrochen", "#Trk")
    if track_width and track_width < MIN_WIDTHS["Trk"]:
        pass          # bereits oben gemeldet

    for line in template.lines:
        for tag in unknown_tags(line.raw):
            report.add(Level.WARNING,
                       f"{tag} sieht aus wie ein Tag, ist aber keiner - "
                       "er landet wörtlich in der NFO", tag)

    widest = max((len(line.raw) for line in template.lines), default=0)
    if widest > CONVENTIONAL_WIDTH:
        report.add(Level.INFO,
                   f"die Vorlage ist {widest} Zeichen breit - üblich sind "
                   f"höchstens {CONVENTIONAL_WIDTH}")

    if not template.lines or all(not line.raw.strip() for line in template.lines):
        report.add(Level.ERROR, "die Vorlage ist leer")
    elif not tags:
        # Ohne einen einzigen Tag ist die Datei hoechstens ein fester Text -
        # meist ist es schlicht keine Vorlage.
        report.add(Level.ERROR,
                   "kein einziger Tag gefunden - ist das wirklich eine .skl?")

    unused = sorted(tags - set(widths))
    if unused:
        report.add(Level.INFO, f"Tags ohne Feldbreite: {', '.join(unused)}")
    return report


def check_template_file(path: str | Path, codepage: str = "cp437") -> Report:
    p = Path(path)
    try:
        template = Template.from_file(p, codepage=codepage)
    except OSError as exc:
        report = Report(checked=p.name)
        report.add(Level.ERROR, f"nicht lesbar: {exc}")
        return report

    report = check_template(template, source=p.name)
    if p.suffix.lower() != ".skl":
        report.add(Level.INFO,
                   f"die Endung ist {p.suffix or '(keine)'}, erwartet wird .skl")
    return report


# ============================================================ Releaseprüfung


def check_release(release: Release, root: str | Path,
                  naming: Optional[NamingProfile] = None,
                  known_releases: Optional[Iterable[str]] = None) -> Report:
    """Prüft ein fertiges Release im Dateisystem."""
    from .companions import COVER_SUFFIXES, find_companions
    from .sfv import verify_sfv

    root = Path(root)
    naming = naming or NamingProfile()
    report = Report(checked=root.name)

    if not release.tracks:
        report.add(Level.ERROR, "keine Audiodateien gefunden")
        return report

    # ---- Begleitdateien --------------------------------------------------
    companions = find_companions(root)
    for suffix, what in ((".nfo", "NFO"), (".sfv", "SFV"), (".m3u", "Playlist")):
        if not any(p.suffix.lower() == suffix for p in companions):
            report.add(Level.WARNING, f"keine {what} vorhanden", f"*{suffix}")

    for sfv in (p for p in companions if p.suffix.lower() == ".sfv"):
        result = verify_sfv(sfv)
        if result.missing:
            report.add(Level.ERROR,
                       f"{len(result.missing)} Datei(en) fehlen laut SFV",
                       sfv.name)
        for name, expected, actual in result.failed:
            report.add(Level.ERROR,
                       f"Prüfsumme weicht ab: erwartet {expected:08X}, "
                       f"gefunden {actual:08X}", name)
        for name in result.retagged:
            report.add(Level.INFO,
                       "Datei wurde nach dem SFV umgetaggt - Audiodaten sind "
                       "unverändert", name)

    if not any(p.suffix.lower() in COVER_SUFFIXES for p in root.rglob("*")):
        report.add(Level.INFO, "kein Bild im Verzeichnis")

    # ---- Tags ------------------------------------------------------------
    for track in release.tracks:
        missing = [name for name, value in
                   (("Titel", track.title), ("Nummer", track.no)) if not value]
        if missing:
            report.add(Level.WARNING,
                       f"{', '.join(missing)} fehlt",
                       Path(track.path).name if track.path else f"Track {track.no}")
    for name, value in (("Artist", release.artist), ("Album", release.album),
                        ("Jahr", release.year)):
        if not value:
            report.add(Level.WARNING, f"{name} ist nicht gesetzt")

    numbers = [t.no for t in release.tracks]
    if len(set(zip((t.disc for t in release.tracks), numbers))) != len(numbers):
        report.add(Level.ERROR, "doppelte Tracknummern innerhalb einer CD")

    # ---- Name ------------------------------------------------------------
    if len(root.name) > naming.max_dir_length:
        report.add(Level.WARNING,
                   f"der Verzeichnisname ist {len(root.name)} Zeichen lang "
                   f"(Grenze {naming.max_dir_length})", root.name)
    for path in root.rglob("*"):
        if path.is_file() and len(path.name) > naming.max_file_length:
            report.add(Level.WARNING,
                       f"Dateiname mit {len(path.name)} Zeichen", path.name)

    # ---- Dupe ------------------------------------------------------------
    if known_releases is not None:
        from .dupecheck import DupeIndex

        index = DupeIndex()
        index.extend(known_releases)
        for match in index.check(root.name):
            if match.name == root.name:
                continue
            report.add(Level.WARNING if match.exact else Level.INFO,
                       "ähnliches Release bekannt"
                       if not match.exact else "gleiches Release bekannt",
                       match.name)

    return report
