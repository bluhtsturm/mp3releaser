"""Begleitdateien eines Releases finden und aufräumen.

Wird ein Release erneut gebaut - etwa nach einer Umbenennung -, bleiben die
Begleitdateien des vorigen Laufs liegen und zeigen auf Dateinamen, die es nicht
mehr gibt. Ein altes ``.sfv`` meldet dann lauter fehlende Dateien.

Das Original hatte dafür eine Option ("Removes old nfo's, sfv's and m3u's").
Hier ist sie bewusst nicht voreingestellt: Löschen ist die einzige Operation
des Programms, die Daten vernichtet, und ein NFO kann von Hand nachbearbeitet
worden sein.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

#: Endungen, die dieses Programm selbst erzeugt.
COMPANION_SUFFIXES: frozenset[str] = frozenset({".nfo", ".sfv", ".m3u", ".m3u8"})

#: Bilddateien, die zum Release gehören (Cover, Proof).
COVER_SUFFIXES: frozenset[str] = frozenset({".jpg", ".jpeg", ".png"})


def find_companions(root: str | Path,
                    suffixes: Iterable[str] = COMPANION_SUFFIXES) -> list[Path]:
    """Alle Begleitdateien unterhalb von ``root``, sortiert."""
    wanted = {s.lower() for s in suffixes}
    return sorted(p for p in Path(root).rglob("*")
                  if p.is_file() and p.suffix.lower() in wanted)


def remove_companions(root: str | Path,
                      keep: Iterable[Path] = (),
                      suffixes: Iterable[str] = COMPANION_SUFFIXES) -> list[Path]:
    """Löscht Begleitdateien und gibt zurück, was entfernt wurde.

    ``keep`` schützt einzelne Pfade - damit lässt sich ein gerade erzeugter
    Satz Dateien vom Aufräumen ausnehmen.
    """
    protected = {Path(p).resolve() for p in keep}
    removed: list[Path] = []
    for path in find_companions(root, suffixes):
        if path.resolve() in protected:
            continue
        path.unlink()
        removed.append(path)
    return removed


def find_covers(root: str | Path,
                suffixes: Iterable[str] = COVER_SUFFIXES) -> list[Path]:
    """Bilddateien des Releases, sortiert."""
    wanted = {s.lower() for s in suffixes}
    return sorted(p for p in Path(root).rglob("*")
                  if p.is_file() and p.suffix.lower() in wanted)
