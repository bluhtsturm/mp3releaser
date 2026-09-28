"""Woher ein Wert stammt.

Der Scanner zieht seine Angaben aus verschiedenen Quellen: aus den Tags der
Dateien, aus Dateinamen, aus einem CUE, aus dem Verzeichnisnamen - oder er
leitet sie ab, etwa die Mehrheit über alle Dateien. Bisher ging diese
Information nach dem Zusammenbauen verloren.

Für eine Oberfläche ist sie aber genau das, was den Unterschied macht: Ein
Feld, das aus einem gepflegten Tag kommt, verdient anderes Zutrauen als eines,
das aus einem Dateinamen geraten wurde. Wer das sieht, weiß, wo er
nachschauen muss.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Origin(Enum):
    TAG = "tag"
    FILENAME = "filename"
    CUE = "cue"
    DIRECTORY = "directory"
    #: aus mehreren Dateien zusammengeführt oder sonst abgeleitet
    DERIVED = "derived"
    #: aus der Uhr des Rechners - das Releasedatum ist fast immer heute
    SYSTEM = "system"
    MANUAL = "manual"
    UNKNOWN = "unknown"

    @property
    def label(self) -> str:
        return {
            Origin.TAG: "aus den Tags",
            Origin.FILENAME: "aus dem Dateinamen",
            Origin.CUE: "aus dem CUE",
            Origin.DIRECTORY: "aus dem Verzeichnisnamen",
            Origin.DERIVED: "abgeleitet",
            Origin.SYSTEM: "aus der Systemzeit",
            Origin.MANUAL: "von Hand",
            Origin.UNKNOWN: "unbekannt",
        }[self]

    @property
    def trustworthy(self) -> bool:
        """Ob der Wert ohne Nachsehen übernommen werden kann."""
        return self in (Origin.TAG, Origin.CUE, Origin.SYSTEM, Origin.MANUAL)


@dataclass
class OriginMap:
    """Herkunft je Feld - für die Release und je Track."""

    release: dict[str, Origin] = field(default_factory=dict)
    #: (CD-Nummer, Tracknummer) -> Feld -> Herkunft
    tracks: dict[tuple[int, int], dict[str, Origin]] = field(default_factory=dict)

    def set(self, name: str, origin: Origin) -> None:
        self.release[name] = origin

    def set_track(self, disc: int, track: int, name: str, origin: Origin) -> None:
        self.tracks.setdefault((disc, track), {})[name] = origin

    def get(self, name: str, default: Origin = Origin.UNKNOWN) -> Origin:
        return self.release.get(name, default)

    def get_track(self, disc: int, track: int, name: str,
                  default: Origin = Origin.UNKNOWN) -> Origin:
        return self.tracks.get((disc, track), {}).get(name, default)

    def mark_manual(self, name: str) -> None:
        """Wird gesetzt, sobald jemand das Feld in einer Oberfläche ändert."""
        self.release[name] = Origin.MANUAL

    def uncertain(self) -> list[str]:
        """Felder, bei denen ein Blick lohnt."""
        return sorted(name for name, origin in self.release.items()
                      if not origin.trustworthy)

    def summary(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for origin in self.release.values():
            counts[origin.value] = counts.get(origin.value, 0) + 1
        for fields_ in self.tracks.values():
            for origin in fields_.values():
                counts[origin.value] = counts.get(origin.value, 0) + 1
        return counts


def first_known(*candidates: Optional[Origin]) -> Origin:
    for candidate in candidates:
        if candidate is not None and candidate is not Origin.UNKNOWN:
            return candidate
    return Origin.UNKNOWN
