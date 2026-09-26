"""Datenmodell einer Release.

Bewusst frei von Audio-/Tag-Bibliotheken: der Metadaten-Layer erzeugt diese
Objekte, der SKL-Renderer konsumiert sie. Dadurch bleibt der Renderer ohne
mutagen testbar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Track:
    no: int
    title: str
    seconds: float = 0.0
    disc: int = 1
    path: Optional[str] = None
    size_bytes: int = 0

    #: abweichender Artist dieses Tracks (Sampler). Leer = Artist der Release.
    #: Steht am Ende, damit bestehende positionale Aufrufe gueltig bleiben.
    artist: str = ""

    #: technische Werte, vom Audio-Layer gefuellt
    bitrate: Optional[int] = None
    samplerate: Optional[int] = None
    channel_mode: Optional[str] = None
    vbr: bool = False


@dataclass
class Disc:
    number: int = 1
    title: Optional[str] = None
    year: Optional[int] = None
    tracks: list[Track] = field(default_factory=list)

    @property
    def seconds(self) -> float:
        return sum(t.seconds for t in self.tracks)

    @property
    def size_bytes(self) -> int:
        return sum(t.size_bytes for t in self.tracks)

    def directory(self, root):
        """Verzeichnis, in dem die Dateien dieser CD liegen.

        Fallback auf ``root``, wenn kein Track einen Pfad hat.
        """
        from pathlib import Path

        for track in self.tracks:
            if track.path:
                return Path(track.path).parent
        return Path(root)


@dataclass
class Release:
    artist: str = ""
    album: str = ""
    year: Optional[int] = None

    genre: str = ""
    subgenre: str = ""
    style: str = ""
    language: str = ""
    country: str = ""
    company: str = ""
    catalog_no: str = ""
    release_type: str = ""          # Album, Single, Maxi, EP ...
    source: str = ""                # CDDA, WEB, Vinyl ...
    audio_format: str = ""          # MP3, FLAC, EAC3 ...

    ripper: str = ""
    supplier: str = ""
    grabber: str = ""
    encoder: str = ""

    release_date: str = ""
    store_date: str = ""
    liveset_date: str = ""

    url: str = ""
    url2: str = ""
    release_counter: str = ""
    released_with: str = ""
    album_addition: str = ""        # z. B. "(CDS)" -> #Albwthadd
    dirname: str = ""               # Verzeichnisname der Release -> #Fullrelease

    notes: list[str] = field(default_factory=list)
    group_news: list[str] = field(default_factory=list)

    discs: list[Disc] = field(default_factory=list)

    # technische Gesamtwerte (vom Audio-Layer gesetzt)
    bitrate: Optional[int] = None
    samplerate: Optional[int] = None
    bits_per_sample: Optional[int] = None
    channel_mode: str = ""
    vbr: bool = False
    vbr_string: str = ""
    flac_compression: Optional[float] = None

    # ---------------------------------------------------------------- helpers

    @property
    def tracks(self) -> list[Track]:
        return [t for d in self.discs for t in d.tracks]

    @property
    def multi_disc(self) -> bool:
        return len(self.discs) > 1

    @property
    def total_tracks(self) -> int:
        return len(self.tracks)

    @property
    def seconds(self) -> float:
        return sum(d.seconds for d in self.discs)

    @property
    def size_bytes(self) -> int:
        return sum(d.size_bytes for d in self.discs)

    @property
    def size_mb(self) -> float:
        return self.size_bytes / (1024 * 1024)

    @property
    def release_name(self) -> str:
        """'Artist - Album' - die Basis fuer #Release / #Releasenc."""
        if self.artist and self.album:
            return f"{self.artist} - {self.album}"
        return self.artist or self.album

    @property
    def full_name(self) -> str:
        """Kompletter Releasename im Verzeichnis-Stil, Fallback auf Artist - Album."""
        return self.dirname or self.release_name

    def disc(self, number: int) -> Optional[Disc]:
        for d in self.discs:
            if d.number == number:
                return d
        return None
