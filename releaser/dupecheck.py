"""Dupe-Prüfung.

Vergleicht einen Releasenamen gegen eine Liste bereits vorhandener. Die Liste
kann eine Textdatei sein (ein Name je Zeile) oder ein Verzeichnis, dessen
Unterordner die Releases sind.

Der Vergleich läuft über eine normalisierte Form: Gruppenkürzel, Quellen- und
Formatangaben fallen weg, Trennzeichen werden vereinheitlicht. Dadurch gelten

    Der_Artist-Das_Album-CDDA-2026-GRP
    der.artist-das.album-web-2026-ANDERE

als dasselbe Release in zwei Fassungen - genau der Fall, den man finden will.

Zusätzlich gibt es einen unscharfen Vergleich über ``difflib``, der Tippfehler
und abweichende Schreibweisen findet. Er liefert Kandidaten, keine Urteile:
die Entscheidung bleibt beim Menschen.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable

#: Bestandteile, die für den Vergleich nichts beitragen: Quelle, Format und
#: Ausgabekennzeichen. Bewusst *nicht* enthalten sind Wörter, die Teil eines
#: echten Titels sein können - "Album", "Single" oder "Sampler" stehen oft im
#: Werktitel selbst, und sie zu entfernen würde verschiedene Releases
#: fälschlich zusammenfallen lassen.
NOISE_WORDS: frozenset[str] = frozenset({
    "cdda", "cds", "cdm", "cdr", "cdep", "va", "web", "webrip",
    "vinyl", "vls", "tape", "sat", "cable", "dvbc", "dvbs", "line", "flac",
    "mp3", "aac", "wav", "atmos", "eac3", "ac3", "alac", "opus", "ogg", "mpc",
    "proper", "repack", "retail", "promo", "advance",
    "reissue", "remastered", "limited", "deluxe", "explicit", "read", "int",
})

_SEPARATORS = re.compile(r"[^a-z0-9]+")
_YEAR = re.compile(r"^(19|20)\d{2}$")
#: Gruppenkürzel steht konventionell hinter dem letzten Bindestrich.
_GROUP = re.compile(r"-([A-Za-z0-9_]{2,})$")

DEFAULT_THRESHOLD = 0.88


def split_group(name: str) -> tuple[str, str]:
    """(Name ohne Gruppenkürzel, Gruppenkürzel)."""
    match = _GROUP.search(name)
    if not match:
        return name, ""
    return name[:match.start()], match.group(1)


def normalise(name: str) -> str:
    """Vergleichsform eines Releasenamens."""
    base, _group = split_group(name)
    tokens = [t for t in _SEPARATORS.split(base.lower()) if t]
    kept = [t for t in tokens if t not in NOISE_WORDS and not _YEAR.match(t)]
    return "-".join(kept or tokens)


@dataclass
class Match:
    name: str
    ratio: float
    exact: bool

    @property
    def percent(self) -> int:
        return round(self.ratio * 100)


@dataclass
class DupeIndex:
    """Bekannte Releasenamen in normalisierter Form."""

    #: Vergleichsform -> Originalnamen
    entries: dict[str, list[str]] = field(default_factory=dict)

    def __len__(self) -> int:
        return sum(len(v) for v in self.entries.values())

    def add(self, name: str) -> None:
        key = normalise(name)
        if not key:
            return
        self.entries.setdefault(key, []).append(name)

    def extend(self, names: Iterable[str]) -> None:
        for name in names:
            self.add(name)

    def check(self, name: str,
              threshold: float = DEFAULT_THRESHOLD,
              limit: int = 5) -> list[Match]:
        """Treffer zu einem Namen, beste zuerst."""
        key = normalise(name)
        if not key:
            return []

        matches: list[Match] = []
        for candidate, originals in self.entries.items():
            if candidate == key:
                matches.extend(Match(o, 1.0, True) for o in originals)
                continue
            ratio = SequenceMatcher(None, key, candidate).ratio()
            if ratio >= threshold:
                matches.extend(Match(o, ratio, False) for o in originals)

        matches.sort(key=lambda m: (-m.ratio, m.name))
        return matches[:limit]


def from_lines(lines: Iterable[str]) -> DupeIndex:
    index = DupeIndex()
    index.extend(line.strip() for line in lines
                 if line.strip() and not line.lstrip().startswith("#"))
    return index


def from_directory(path: str | Path) -> DupeIndex:
    """Baut den Index aus den Unterverzeichnissen eines Ordners."""
    index = DupeIndex()
    index.extend(p.name for p in sorted(Path(path).iterdir()) if p.is_dir())
    return index


def load(source: str | Path) -> DupeIndex:
    """Liest eine Textdatei oder ein Verzeichnis."""
    p = Path(source)
    if p.is_dir():
        return from_directory(p)
    if p.is_file():
        return from_lines(p.read_text(encoding="utf-8",
                                      errors="replace").splitlines())
    raise FileNotFoundError(str(p))
